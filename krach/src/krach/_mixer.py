"""Mixer — graph-based audio node manager.

Manages FAUST DSP nodes (sources and effects), per-node gain, and the
underlying audio graph. Control labels: ``{node_name}/{param}``.
Adding or removing a node rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

import inspect
import warnings
from pathlib import Path
from typing import Literal

from krach.patterns.bind import bind_ctrl, bind_voice, bind_voice_poly
from krach._handle import NodeHandle
from krach._module_ir import ControlDef, ModuleIr, MutedDef, NodeDef, PatternDef, RouteDef
from krach._module_proxy import ModuleProxy
from krach._types import (  # noqa: F401
    ControlPath, DspDef, DspSource, GroupPath, Node, NodePath,
    ResolvedSource, UnknownPath,
    dsp as dsp, resolve_dsp_source, resolve_path,
)
from krach._graph import build_graph_ir as build_graph_ir  # noqa: F401 re-export
from krach._graph import inst_name as _inst_name
from krach._mixer_infra import MixerInfra
from krach._patterns import (  # noqa: F401 — re-exported for tests/namespace
    build_hit as build_hit, build_note as build_note,
    cat as cat, hit as hit, mod_exp as mod_exp, mod_ramp as mod_ramp,
    mod_ramp_down as mod_ramp_down, mod_sine as mod_sine,
    mod_square as mod_square, mod_tri as mod_tri, note as note,
    rand as rand, ramp as ramp, saw as saw, seq as seq,
    sine as sine, stack as stack, struct as struct,
)
from krach._patterns import check_finite as _check_finite
from krach.patterns import Session
from krach.patterns.pattern import Pattern


# ── Mixer ────────────────────────────────────────────────────────────────


class Mixer(MixerInfra):
    """Manages named audio nodes with stable control labels.

    Each node is a FAUST DSP source or effect (string type_id or Python function)
    with an independent gain stage. Adding/removing nodes rebuilds the audio
    graph transparently. ``gain()`` updates are instant (no rebuild).

    Pattern builders and pitch utilities are exposed as static methods so
    that ``kr.note()``, ``kr.hit()``, etc. work when ``kr`` is an instance.
    """

    # Settable public properties — __setattr__ rejects unknown public names.
    _PUBLIC_SETTERS = frozenset({"master", "tempo", "bpm", "meter"})

    def __setattr__(self, name: str, value: object) -> None:
        # Allow: private attrs, known property setters, class-defined attrs,
        # and callable assignments (e.g., kr.status = status_fn from __init__.py).
        if (name.startswith("_")
            or name in self._PUBLIC_SETTERS
            or hasattr(type(self), name)
            or callable(value)):
            super().__setattr__(name, value)
        else:
            raise AttributeError(
                f"kr has no property {name!r}. "
                f"Settable properties: {', '.join(sorted(self._PUBLIC_SETTERS))}"
            )

    def __init__(
        self,
        session: Session,
        dsp_dir: Path,
        node_controls: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._session = session
        self._dsp_dir = dsp_dir
        self._node_controls: dict[str, tuple[str, ...]] = dict(node_controls or {})
        self._nodes: dict[str, Node] = {}
        self._muted: dict[str, float] = {}  # name → gain before mute
        self._sends: dict[tuple[str, str], float] = {}  # (source, target) → gain
        self._wires: dict[tuple[str, str], str] = {}    # (source, target) → port
        self._ctrl_values: dict[str, float] = {}  # path → last set value (for fade start)
        self._patterns: dict[str, Pattern] = {}  # target → last unbound pattern
        self._scenes: dict[str, ModuleIr] = {}
        self._batching: bool = False
        self._graph_loaded: bool = False
        self._master_gain: float = 0.7
        self._transition_bars: int = 0
        self._flush_scheduled: bool = False
        self._session.master_gain(self._master_gain)

    def _cleanup_node(self, name: str, direction: Literal["source", "both"] = "source") -> None:
        """Clean up state for a node being replaced or removed.

        direction="source": clean sends/wires where this node is the source.
        direction="both": clean sends/wires where this node is source OR target.
        """
        if name in self._nodes:
            old = self._nodes[name]
            self.hush(name)
            self._muted.pop(name, None)
            for i in range(old.count):
                self._muted.pop(_inst_name(name, i, old.count), None)
        def _matches(k: tuple[str, str]) -> bool:
            return k[0] == name or (direction == "both" and k[1] == name)
        for key in [k for k in self._sends if _matches(k)]:
            del self._sends[key]
        for key in [k for k in self._wires if _matches(k)]:
            del self._wires[key]

    def _resolve_source(
        self, name: str, source: DspSource, fallback_controls: tuple[str, ...] = (),
    ) -> ResolvedSource:
        """Resolve a source to type_id, controls, source_text, and control ranges."""
        return resolve_dsp_source(
            name, source, self._dsp_dir, self._node_controls, fallback_controls,
            wait=None if self._batching else self._wait_for_type,
        )

    def node(
        self,
        name: str,
        source: DspSource,
        gain: float = 0.5,
        count: int = 1,
        **init: float,
    ) -> NodeHandle:
        """Add a node to the audio graph.

        Auto-detects source (0 audio inputs) vs effect (1+ audio inputs)
        from the DSP definition. Use ``count > 1`` for polyphonic nodes.
        """
        num_inputs = 0
        if isinstance(source, DspDef):
            num_inputs = source.num_inputs
        elif callable(source) and not isinstance(source, str):
            sig = inspect.signature(source)
            num_inputs = sum(
                1 for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
            )
        if num_inputs > 0:
            return self.bus(name, source, gain=gain)
        return self.voice(name, source, gain=gain, count=count, **init)

    def connect(self, source: str, target: str, level: float = 1.0, port: str | None = None) -> None:
        """Connect source node to target node.

        Creates a gain-controlled send. If ``port`` is specified,
        creates a direct wire to that port instead.
        If the target has num_inputs=0, promotes it to an effect (num_inputs=1)
        so the graph builder creates an audio input port.
        """
        if target in self._nodes and self._nodes[target].num_inputs == 0:
            self._nodes[target].num_inputs = 1
        if port is not None:
            self.wire(source, target, port=port)
        else:
            self.send(source, target, level=level)

    def __getitem__(self, path: str) -> NodeHandle | float:
        """Path dispatch: ``kr['bass']`` → NodeHandle, ``kr['bass/cutoff']`` → float."""
        match resolve_path(path, self._nodes):
            case NodePath(name):
                return NodeHandle(self, name)
            case ControlPath(label=label):
                return self._ctrl_values.get(label, 0.0)
            case GroupPath():
                raise KeyError(f"{path!r} is a group prefix, not a single node")
            case UnknownPath(raw):
                raise KeyError(f"no node named {raw!r}")

    def __setitem__(self, path: str, value: float) -> None:
        """Set via path: ``kr['bass/cutoff'] = 1200`` or ``kr['bass'] = 0.3`` (gain)."""
        match resolve_path(path, self._nodes):
            case NodePath(name):
                self.gain(name, value)
            case ControlPath():
                self.set(path, value)
            case GroupPath(prefix=prefix):
                self.gain(prefix, value)
            case UnknownPath(raw):
                warnings.warn(f"kr['{raw}'] = {value}: no node named '{raw}'", stacklevel=2)
                self.gain(path, value)

    def input(self, name: str = "mic", channel: int = 0, gain: float = 0.5) -> NodeHandle:
        """Add an audio input node (ADC).

        Starts the system audio input stream (if not already started) and
        creates an ``adc_input`` node in the graph.

        ``channel``: which input channel to capture (0-based).
        """
        self._session.start_input(channel)
        self._node_controls["adc_input"] = ()
        return self.voice(name, "adc_input", gain=gain)

    def midi_map(
        self,
        cc: int,
        path: str,
        lo: float = 0.0,
        hi: float = 1.0,
        channel: int = 0,
    ) -> None:
        """Map a MIDI CC to a control path.

        ``cc``: MIDI CC number (0-127).
        ``path``: control path, e.g. ``"bass/cutoff"`` or ``"bass/gain"``.
        ``lo``/``hi``: output range the CC 0-127 is scaled to.
        ``channel``: MIDI channel (0-based, default 0).
        """
        label = self._resolve_label(path)
        self._session.midi_map(channel, cc, label, lo, hi)

    def voice(
        self,
        name: str,
        source: DspSource,
        gain: float = 0.5,
        count: int = 1,
        **init: float,
    ) -> NodeHandle:
        """Add or replace a source node. Rebuilds the graph.

        ``count``: 1 for mono, >1 for polyphonic (N instances, round-robin).
        Prefer ``node()`` which auto-detects source vs effect.
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        resolved = self._resolve_source(name, source, tuple(init.keys()))
        self._muted.pop(name, None)
        self._cleanup_node(name)

        is_new = name not in self._nodes
        self._nodes[name] = Node(
            type_id=resolved.type_id,
            gain=gain,
            controls=resolved.controls,
            count=count,
            init=tuple(init.items()),
            source_text=resolved.source_text,
            control_ranges=resolved.control_ranges,
            control_defaults=resolved.control_defaults,
            alloc=0,
        )
        # Seed ctrl_values with hslider defaults so __getitem__ returns init values
        for ctrl, default in resolved.control_defaults.items():
            self._ctrl_values.setdefault(f"{name}/{ctrl}", default)
        if not self._batching:
            if is_new and self._graph_loaded and count == 1:
                self._session.add_voice(name, resolved.type_id, resolved.controls, gain)
            else:
                self._rebuild()
        return NodeHandle(self, name)

    def remove(self, name: str) -> None:
        """Remove a node or group and all routing. Rebuilds once. No-op if not found."""
        match resolve_path(name, self._nodes):
            case NodePath(n):
                self._cleanup_node(n, direction="both")
                del self._nodes[n]
                self._rebuild()
            case GroupPath(_, members):
                for m in members:
                    self._cleanup_node(m, direction="both")
                    del self._nodes[m]
                self._rebuild()
            case _:
                return  # no-op

    remove_bus = remove

    def hush(self, name: str) -> None:
        """Stop the pattern, its fade, and release gates for a node, control path, or group."""
        match resolve_path(name, self._nodes):
            case NodePath(n):
                self._hush_single(n)
            case ControlPath():
                slot = f"_ctrl_{name.replace('/', '_')}"
                self._session.hush(slot)
            case GroupPath(members=members):
                for m in members:
                    self._hush_single(m)
            case UnknownPath(raw):
                self._session.hush(raw)
                self._session.hush(f"_fade_{raw}")

    def _hush_single(self, name: str) -> None:
        """Hush a single node (not a group or path)."""
        self._session.hush(name)
        self._session.hush(f"_fade_{name}")
        node = self._nodes.get(name)
        if node is not None:
            for i in range(node.count):
                inst = _inst_name(name, i, node.count)
                if node.count > 1:
                    self._session.hush(inst)
                    self._session.hush(f"_fade_{inst}")
                if "gate" in node.controls:
                    self._session.set_ctrl(f"{inst}/gate", 0.0)

    def stop(self) -> None:
        """Hush all nodes and release all gates."""
        for name in self._nodes:
            self.hush(name)


    # ── Scenes ─────────────────────────────────────────────────────────────

    def save(self, name: str) -> None:
        """Save current state as a named scene (via ModuleIr)."""
        self._scenes[name] = self.capture()

    def recall(self, name: str) -> None:
        """Recall a saved scene — clears state, then instantiates the saved ModuleIr."""
        if name not in self._scenes:
            raise ValueError(f"scene '{name}' not found")
        self.stop()
        # Clear current state before restoring
        for n in list(self._nodes):
            self._cleanup_node(n, direction="both")
        self._nodes.clear()
        self._sends.clear()
        self._wires.clear()
        self._ctrl_values.clear()
        self._muted.clear()
        self._patterns.clear()
        self.instantiate(self._scenes[name])

    @property
    def scenes(self) -> list[str]:
        """List of saved scene names."""
        return list(self._scenes.keys())

    def trace(self) -> ModuleProxy:
        """Return a tracing proxy that records calls as ModuleIr.

        Usage::

            proxy = kr.trace()
            proxy.node("bass", bass_fn, gain=0.3)
            proxy.send("bass", "verb", level=0.4)
            ir = proxy.build()
            kr.instantiate(ir)
        """
        return ModuleProxy()

    def module(self, name: str) -> ModuleIr:
        """Get a saved module/scene by name."""
        if name not in self._scenes:
            raise ValueError(f"module '{name}' not found")
        return self._scenes[name]

    def load(self, path: str) -> None:
        """Load and execute a Python file with ``kr`` in scope."""
        from krach._scene import load_file
        load_file(path, {"kr": self, "mix": self})

    # ── Module capture / instantiate ──────────────────────────────────

    def capture(self) -> ModuleIr:
        """Snapshot current mixer state as a frozen ModuleIr."""
        nodes = tuple(
            NodeDef(
                name=name,
                source=node.type_id,
                gain=self._muted.get(name, node.gain),
                count=node.count,
                num_inputs=node.num_inputs,
                init=node.init,
                source_text=node.source_text,
            )
            for name, node in self._nodes.items()
        )
        routing: list[RouteDef] = []
        for (src, tgt), level in self._sends.items():
            routing.append(RouteDef(source=src, target=tgt, kind="send", level=level))
        for (src, tgt), port in self._wires.items():
            routing.append(RouteDef(source=src, target=tgt, kind="wire", port=port))

        controls = tuple(
            ControlDef(path=path, value=val)
            for path, val in self._ctrl_values.items()
        )
        muted = tuple(
            MutedDef(name=name, saved_gain=gain)
            for name, gain in self._muted.items()
        )
        try:
            tempo = float(self.tempo)
        except (TypeError, ValueError):
            tempo = None
        try:
            meter = float(self.meter)
        except (TypeError, ValueError):
            meter = None

        patterns = tuple(
            PatternDef(target=target, pattern=pat.node)
            for target, pat in self._patterns.items()
        )

        return ModuleIr(
            nodes=nodes,
            routing=tuple(routing),
            patterns=patterns,
            controls=controls,
            muted=muted,
            tempo=tempo,
            meter=meter,
            master=self._master_gain,
        )

    def instantiate(self, ir: ModuleIr) -> None:
        """Replay a ModuleIr onto this mixer. Batches all nodes into one rebuild."""
        with self.batch():
            for nd in ir.nodes:
                self.voice(nd.name, nd.source, gain=nd.gain, count=nd.count, **dict(nd.init))
                # Restore metadata that voice() can't infer from type_id alone
                node = self._nodes[nd.name]
                if nd.num_inputs:
                    node.num_inputs = nd.num_inputs
                if nd.source_text:
                    node.source_text = nd.source_text

        for rd in ir.routing:
            if rd.kind == "send":
                self.send(rd.source, rd.target, level=rd.level)
            else:
                self.wire(rd.source, rd.target, port=rd.port)

        if ir.tempo is not None:
            self.tempo = ir.tempo
        if ir.meter is not None:
            self.meter = ir.meter
        if ir.master is not None:
            self.master = ir.master

        for cd in ir.controls:
            self.set(cd.path, cd.value)

        for pd in ir.patterns:
            self.play(pd.target, Pattern(pd.pattern))

        for md in ir.muted:
            self.mute(md.name)

    def export(self, path: str) -> None:
        """Export current session state to a reloadable Python script."""
        from krach._export import export_session
        try:
            tempo = float(self.tempo)
        except (TypeError, ValueError):
            tempo = 120.0
        try:
            meter = float(self.meter)
        except (TypeError, ValueError):
            meter = 4.0
        export_session(
            path, self._nodes, self._dsp_dir, self._sends, self._wires,
            self._patterns, self._ctrl_values, tempo, meter, self._master_gain,
        )

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Play a pattern on a node or control path.

        - Known node name (exact match): binds bare params to ``node/param``
        - Poly node (count>1): round-robin allocates instances
        - Otherwise with ``/``: control path — rewrites ``"ctrl"`` placeholder
        - Otherwise without ``/``: mono node binding

        ``from_zero``: if True, uses ``play_from_zero`` so the pattern phase
        starts at 0 regardless of the current cycle position.
        """
        if swing is not None:
            pattern = pattern.swing(swing)
        self._patterns[target] = pattern
        send = self._session.play_from_zero if from_zero else self._session.play

        pn = pattern.node  # PatternNode — bind operates on this directly

        match resolve_path(target, self._nodes):
            case NodePath(name):
                node = self._nodes[name]
                self._warn_unknown_controls(name, node, pattern)
                if node.count > 1:
                    bound, new_alloc = bind_voice_poly(pn, name, node.count, node.alloc)
                    node.alloc = new_alloc
                    send(name, Pattern(bound))
                else:
                    send(name, Pattern(bind_voice(pn, name)))
            case ControlPath(node=node_name, param=param):
                self._warn_pattern_range(node_name, param, pattern)
                n = self._nodes.get(node_name)
                if n is not None and n.count > 1:
                    for i in range(n.count):
                        inst_label = f"{_inst_name(node_name, i, n.count)}/{param}"
                        slot = f"_ctrl_{inst_label.replace('/', '_')}"
                        send(slot, Pattern(bind_ctrl(pn, inst_label)))
                else:
                    inst_label = self._resolve_label(target)
                    slot = f"_ctrl_{target.replace('/', '_')}"
                    send(slot, Pattern(bind_ctrl(pn, inst_label)))
            case GroupPath(members=members):
                for m in members:
                    send(m, Pattern(bind_voice(pn, m)))
            case UnknownPath(raw):
                if "/" in raw:
                    slot = f"_ctrl_{raw.replace('/', '_')}"
                    send(slot, Pattern(bind_ctrl(pn, raw)))
                else:
                    send(raw, Pattern(bind_voice(pn, raw)))

    def pattern(self, name: str) -> Pattern | None:
        """Retrieve the last unbound pattern played on a target. None if unplayed."""
        return self._patterns.get(name)


    def bus(
        self,
        name: str,
        source: DspSource,
        gain: float = 0.5,
    ) -> NodeHandle:
        """Add or replace an effect bus. Rebuilds the graph."""
        # Validate early: effects must have audio inputs
        num_inputs: int
        if isinstance(source, DspDef):
            num_inputs = source.num_inputs
        elif callable(source) and not isinstance(source, str):
            num_inputs = len(inspect.signature(source).parameters)
        else:
            num_inputs = 1
        if num_inputs == 0 and not isinstance(source, str):
            raise ValueError(
                f"bus '{name}': DSP has no audio inputs — effects need function "
                f"parameters for audio input, e.g. def verb(inp: Signal) -> Signal"
            )
        self._cleanup_node(name, direction="both")
        resolved = self._resolve_source(name, source)
        self._nodes[name] = Node(
            type_id=resolved.type_id, gain=gain, controls=resolved.controls,
            num_inputs=num_inputs, control_ranges=resolved.control_ranges,
            control_defaults=resolved.control_defaults,
        )
        for ctrl, default in resolved.control_defaults.items():
            self._ctrl_values.setdefault(f"{name}/{ctrl}", default)
        if not self._batching:
            self._rebuild()
        return NodeHandle(self, name)

    def send(self, source: str, target: str, level: float = 0.5) -> None:
        """Route a source node to a target node via a gain-controlled send.

        If the pair already exists, does an instant level update (no rebuild).
        """
        _check_finite(level, f"send level for '{source}' → '{target}'")
        if source not in self._nodes or target not in self._nodes:
            missing = [n for n in (source, target) if n not in self._nodes]
            warnings.warn(f"send: skipped — node(s) not found: {missing}", stacklevel=2)
            return

        key = (source, target)

        if key in self._wires:
            raise ValueError(f"wire already exists for ('{source}', '{target}') — cannot also send")

        if key in self._sends:
            # Instant update — no rebuild
            self._sends[key] = level
            self._session.set_ctrl(f"{source}_send_{target}/gain", level)
            return

        self._sends[key] = level
        if not self._batching:
            self._rebuild()

    def wire(self, source: str, target: str, port: str = "in0") -> None:
        """Wire a source node directly to a target node port (no gain stage)."""
        if source not in self._nodes or target not in self._nodes:
            missing = [n for n in (source, target) if n not in self._nodes]
            warnings.warn(f"wire: skipped — node(s) not found: {missing}", stacklevel=2)
            return

        key = (source, target)

        if key in self._sends:
            raise ValueError(f"send already exists for ('{source}', '{target}') — cannot also wire")

        self._wires[key] = port
        if not self._batching:
            self._rebuild()

    def unsend(self, source: str, target: str) -> None:
        """Remove a send or wire between two nodes. Rebuilds the graph."""
        key = (source, target)
        removed = key in self._sends or key in self._wires
        self._sends.pop(key, None)
        self._wires.pop(key, None)
        if removed:
            self._rebuild()

    def mod(
        self, path: str, pattern_or_shape: Pattern | str,
        lo: float = 0.0, hi: float = 1.0, bars: int = 1,
    ) -> None:
        """Modulate a control parameter.

        If ``pattern_or_shape`` is a ``Pattern``, schedules it as a timed
        pattern (legacy path).  If it is a ``str`` (e.g. ``"sine"``,
        ``"tri"``), sends a native automation to the audio engine.
        """
        if isinstance(pattern_or_shape, str):
            label = self._resolve_label(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(label, pattern_or_shape, lo, hi, period_secs)
        else:
            self.play(path, pattern_or_shape.over(bars), from_zero=True)
