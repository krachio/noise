"""VoiceMixer — named audio nodes with stable control labels.

Manages FAUST DSP nodes (sources and effects), per-node gain, and the
underlying audio graph. Control labels: ``{node_name}/{param}``.
Adding or removing a node rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

import inspect
import json
import textwrap
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable  # Any still used for DspDef.fn

from faust_dsl import transpile as _transpile
from krach._bind import bind_ctrl, bind_voice, bind_voice_poly
from krach._handle import NodeHandle
from krach._graph import inst_name as _inst_name, build_graph_ir
from krach._patterns import (  # noqa: F401 — re-exported for backward compat
    build_hit as build_hit,
    build_note as build_note,
    cat, hit, mod_exp, mod_ramp, mod_ramp_down,
    mod_sine, mod_square, mod_tri, note, rand, ramp, saw, seq, sine,
    stack, struct,
)
from krach._patterns import check_finite as _check_finite
from krach.patterns import Session
from krach.patterns.pattern import Pattern
from krach.patterns.pattern import ctrl as _ctrl
from krach.patterns.pattern import rest as _rest

from krach._pitch import ftom as _ftom
from krach._pitch import mtof as _mtof
from krach._pitch import parse_note as _parse_note


@dataclass(frozen=True)
class NodeSnapshot:
    """Frozen snapshot of a Node's state for scene storage."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int = 0
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = ""


@dataclass(frozen=True)
class Scene:
    """Snapshot of the mixer state — nodes, sends, patterns, controls."""

    nodes: dict[str, NodeSnapshot]
    sends: dict[tuple[str, str], float]
    wires: dict[tuple[str, str], str]
    patterns: dict[str, Pattern]
    ctrl_values: dict[str, float]
    tempo: float
    master: float
    muted: dict[str, float]


@dataclass
class Node:
    """A node in the audio graph — source (num_inputs=0) or effect (num_inputs>0)."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int = 0
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = field(default="", repr=False)
    alloc: int = field(default=0, repr=False)




@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    controls: tuple[str, ...]
    num_inputs: int = 0


def dsp(fn: Callable[..., Any]) -> DspDef:
    """Decorator: captures Python source + pre-transpiles to FAUST.

    Usage::

        @dsp
        def acid_bass() -> Signal:
            freq = control("freq", 55.0, 20.0, 800.0)
            gate = control("gate", 0.0, 0.0, 1.0)
            return lowpass(saw(freq), 800.0) * adsr(...) * 0.55

        kr.voice("bass", acid_bass, gain=0.3)
    """
    source = textwrap.dedent(inspect.getsource(fn))
    result = _transpile(fn)  # type: ignore[arg-type]
    return DspDef(
        fn=fn,
        source=source,
        faust=result.source,
        controls=tuple(c.name for c in result.schema.controls),
        num_inputs=result.num_inputs,
    )





# ── VoiceMixer ────────────────────────────────────────────────────────────────


class VoiceMixer:
    """Manages named audio voices with stable control labels.

    Each voice is a FAUST DSP node (string type_id or Python function) with
    an independent gain stage.  Adding/removing voices rebuilds the audio
    graph transparently.  ``gain()`` updates are instant (no rebuild).

    Pattern builders and pitch utilities are exposed as static methods so
    that ``kr.note()``, ``kr.hit()``, etc. work when ``kr`` is an instance.
    """

    # ── Pattern builders (static — no instance state) ─────────────────────
    note = staticmethod(note)
    hit = staticmethod(hit)
    seq = staticmethod(seq)
    rest = staticmethod(_rest)
    ramp = staticmethod(ramp)
    mod_sine = staticmethod(mod_sine)
    mod_tri = staticmethod(mod_tri)
    mod_ramp = staticmethod(mod_ramp)
    mod_ramp_down = staticmethod(mod_ramp_down)
    mod_square = staticmethod(mod_square)
    mod_exp = staticmethod(mod_exp)
    dsp = staticmethod(dsp)

    # ── Continuous pattern values + combinators ─────────────────────────
    sine = staticmethod(sine)
    saw = staticmethod(saw)
    rand = staticmethod(rand)
    cat = staticmethod(cat)
    stack = staticmethod(stack)
    struct = staticmethod(struct)

    # ── Pitch utilities (static) ──────────────────────────────────────────
    mtof = staticmethod(_mtof)
    ftom = staticmethod(_ftom)
    parse_note = staticmethod(_parse_note)

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
        self._scenes: dict[str, Scene] = {}
        self._batching: bool = False
        self._graph_loaded: bool = False
        self._master_gain: float = 0.7
        self._transition_bars: int = 0
        self._flush_scheduled: bool = False
        self._session.master_gain(self._master_gain)

    def _resolve_source(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        fallback_controls: tuple[str, ...] = (),
    ) -> tuple[str, tuple[str, ...], str]:
        """Resolve a source to (type_id, controls, source_text).

        Writes .dsp and .py to dsp_dir and waits for JIT if needed.
        ``source_text`` is the Python source code (empty for string type_ids).
        """
        if isinstance(source, DspDef):
            type_id = f"faust:{name}"
            source_text = source.source
            faust_code, controls = source.faust, source.controls
        elif callable(source):
            type_id = f"faust:{name}"
            source_text = textwrap.dedent(inspect.getsource(source))
            result = _transpile(source)  # type: ignore[arg-type]
            faust_code, controls = result.source, tuple(c.name for c in result.schema.controls)
        else:
            return source, self._node_controls.get(source, fallback_controls), ""

        py_path = self._dsp_dir.joinpath(f"{name}.py")
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(source_text)
        dsp_path = self._dsp_dir.joinpath(f"{name}.dsp")
        dsp_path.parent.mkdir(parents=True, exist_ok=True)
        dsp_path.write_text(faust_code)
        self._node_controls[type_id] = controls
        if not self._batching:
            self._wait_for_type(type_id)
        return type_id, controls, source_text

    def node(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
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
            result = _transpile(source)  # type: ignore[arg-type]
            num_inputs = result.num_inputs
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
        if "/" in path:
            return self._ctrl_values.get(path, 0.0)
        if path in self._nodes:
            return NodeHandle(self, path)
        raise KeyError(f"no node named {path!r}")

    def __setitem__(self, path: str, value: float) -> None:
        """Set via path: ``kr['bass/cutoff'] = 1200`` or ``kr['bass'] = 0.3`` (gain)."""
        if "/" in path:
            self.set(path, value)
        else:
            self.gain(path, value)

    def input(self, name: str = "mic", channel: int = 0, gain: float = 0.5) -> NodeHandle:
        """Add an audio input voice (ADC).

        Starts the system audio input stream (if not already started) and
        creates an ``adc_input`` node in the graph.

        ``channel``: which input channel to capture (0-based).
        """
        self._session.start_input(channel)
        self._node_controls["adc_input"] = ()
        # Use voice() with the built-in adc_input type.
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
        label = self._resolve_path(path)
        self._session.midi_map(channel, cc, label, lo, hi)

    def voice(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        gain: float = 0.5,
        count: int = 1,
        **init: float,
    ) -> NodeHandle:
        """Add or replace a voice.  Rebuilds the graph.

        ``source`` is a ``@dsp``-decorated function, a registered type_id
        string, or a raw Python DSP function (transpiled on the fly).

        ``count``: 1 for mono, >1 for polyphonic (N instances, round-robin).
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        type_id, controls, source_text = self._resolve_source(name, source, tuple(init.keys()))
        self._muted.pop(name, None)

        # Clean up old voice state if replacing
        if name in self._nodes:
            old = self._nodes[name]
            self.hush(name)
            # Clean instance-level muted entries from old poly
            for i in range(old.count):
                self._muted.pop(_inst_name(name, i, old.count), None)

        # Clean sends/wires from old voice
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]

        is_new = name not in self._nodes
        self._nodes[name] = Node(
            type_id=type_id,
            gain=gain,
            controls=controls,
            count=count,
            init=tuple(init.items()),
            source_text=source_text,
            alloc=0,
        )
        if not self._batching:
            if is_new and self._graph_loaded and count == 1:
                self._session.add_voice(name, type_id, controls, gain)
            else:
                self._rebuild()
        return NodeHandle(self, name)

    def remove(self, name: str) -> None:
        """Remove a node. Rebuilds the graph. No-op if not found."""
        if name not in self._nodes:
            return
        voice = self._nodes[name]
        self._muted.pop(name, None)
        self.hush(name)
        # Clean instance-level muted entries
        for i in range(voice.count):
            self._muted.pop(_inst_name(name, i, voice.count), None)
        # Clean sends/wires where this voice is the source
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]
        del self._nodes[name]
        self._rebuild()

    def hush(self, name: str) -> None:
        """Stop the pattern, its fade, and release gates for a voice, control path, or group.

        - Control path (contains ``/``): hushes the ``_ctrl_`` slot
        - Node name: hushes node + fade + gates
        - Group prefix: hushes all matching voices
        """
        # Control path: hush the _ctrl_ slot
        if "/" in name:
            slot = f"_ctrl_{name.replace('/', '_')}"
            self._session.hush(slot)
            # Also try group-prefix resolution
            targets = self._resolve_targets_soft(name)
            for t in targets:
                self._hush_single(t)
            return

        # Exact match or group prefix
        targets = self._resolve_targets_soft(name)
        if targets:
            for t in targets:
                self._hush_single(t)
        else:
            # Not found — still pass through to session (e.g. custom slot names)
            self._session.hush(name)
            self._session.hush(f"_fade_{name}")

    def _hush_single(self, name: str) -> None:
        """Hush a single voice (not a group or path)."""
        self._session.hush(name)
        self._session.hush(f"_fade_{name}")
        voice = self._nodes.get(name)
        if voice is not None:
            for i in range(voice.count):
                inst = _inst_name(name, i, voice.count)
                if voice.count > 1:
                    self._session.hush(inst)
                    self._session.hush(f"_fade_{inst}")
                if "gate" in voice.controls:
                    self._session.set_ctrl(f"{inst}/gate", 0.0)

    def stop(self) -> None:
        """Hush all voices and release all gates."""
        for name in self._nodes:
            self.hush(name)

    def gain(self, name: str, value: float) -> None:
        """Update a node or group gain. Instant — no graph rebuild.

        For poly voices, distributes gain equally across instances.
        Prefix matching: ``gain("drums", 0.5)`` applies to all ``drums/*`` voices.
        """
        _check_finite(value, f"gain for '{name}'")
        targets = self._resolve_targets_soft(name)
        for t in targets:
            self._gain_single(t, value)

    def _gain_single(self, name: str, value: float) -> None:
        """Set gain for a single node. Uses fade inside transition()."""
        if self._transition_bars > 0:
            self.fade(f"{name}/gain", value, bars=self._transition_bars)
            # Update bookkeeping immediately even though audio fades
            if name in self._nodes:
                self._nodes[name].gain = value
            return

        node = self._nodes[name]
        node.gain = value
        if node.count > 1:
            per_node = value / node.count
            for i in range(node.count):
                inst = _inst_name(name, i, node.count)
                self._session.set_ctrl(f"{inst}/gain", float(per_node))
        else:
            self._session.set_ctrl(f"{name}/gain", float(value))

    def mute(self, name: str) -> None:
        """Mute a node or group — stores current gain, sets gain to 0. No-op if not found."""
        targets = self._resolve_targets_soft(name)
        for t in targets:
            self._mute_single(t)

    def _mute_single(self, name: str) -> None:
        """Mute a single node."""
        if name in self._muted:
            return
        if name in self._nodes:
            self._muted[name] = self._nodes[name].gain
        self._gain_single(name, 0.0)

    def unmute(self, name: str) -> None:
        """Unmute a voice or group — restores gain saved by mute()."""
        targets = self._resolve_targets_soft(name)
        if not targets:
            if name not in self._muted:
                return
            # Single name not in current voices — just pop muted
            self._muted.pop(name, None)
            return
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def solo(self, name: str) -> None:
        """Solo a node or group — mutes all others, unmutes targets. No-op if not found."""
        targets = set(self._resolve_targets_soft(name))
        if not targets:
            return
        all_names: set[str] = set(self._nodes.keys())
        for n in all_names:
            if n not in targets:
                self._mute_single(n)
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def unsolo(self) -> None:
        """Unmute all muted voices — reverses solo() or manual mutes."""
        for name in list(self._muted):
            self.unmute(name)

    # ── Scenes ─────────────────────────────────────────────────────────────

    def save(self, name: str) -> None:
        """Save current state as a named scene."""
        self._scenes[name] = Scene(
            nodes={
                n: NodeSnapshot(
                    type_id=v.type_id, gain=v.gain, controls=v.controls,
                    num_inputs=v.num_inputs, count=v.count, init=v.init,
                    source_text=v.source_text,
                )
                for n, v in self._nodes.items()
            },
            sends=dict(self._sends),
            wires=dict(self._wires),
            patterns=dict(self._patterns),
            ctrl_values=dict(self._ctrl_values),
            tempo=self.tempo,
            master=self._master_gain,
            muted=dict(self._muted),
        )

    def recall(self, name: str) -> None:
        """Recall a saved scene — rebuilds graph, replays patterns, restores controls."""
        if name not in self._scenes:
            raise ValueError(f"scene '{name}' not found")
        scene = self._scenes[name]

        # Stop everything
        self.stop()

        # Rebuild nodes
        self._nodes.clear()
        self._sends.clear()
        self._wires.clear()

        for nname, snap in scene.nodes.items():
            self._nodes[nname] = Node(
                type_id=snap.type_id, gain=snap.gain, controls=snap.controls,
                num_inputs=snap.num_inputs, count=snap.count, init=snap.init,
                source_text=snap.source_text,
            )
        self._sends = dict(scene.sends)
        self._wires = dict(scene.wires)
        self._muted = dict(scene.muted)
        self._rebuild()

        # Restore tempo and master
        self.tempo = scene.tempo
        self.master = scene.master

        # Restore control values
        for path, value in scene.ctrl_values.items():
            self.set(path, value)

        # Replay patterns
        for slot, pattern in scene.patterns.items():
            self.play(slot, pattern)

    @property
    def scenes(self) -> list[str]:
        """List of saved scene names."""
        return list(self._scenes.keys())

    def load(self, path: str) -> None:
        """Load and execute a Python file with ``kr`` (and ``mix`` compat) in scope."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"scene file not found: {path}")
        code = p.read_text()
        ns: dict[str, object] = {"kr": self, "mix": self}
        exec(compile(code, path, "exec"), ns)  # noqa: S102

    def export(self, path: str) -> None:
        """Export current session state to a reloadable Python script.

        The generated file can be loaded back with ``kr.load(path)``.
        DSP definitions, voices, buses, sends, patterns, and transport
        settings are all captured.
        """
        from krach.patterns.ir import ir_to_dict

        lines: list[str] = [
            '"""Exported krach session."""',
            "import json",
            "from krach.patterns.ir import dict_to_ir",
            "from krach.patterns.pattern import Pattern",
            "import krach.dsp as krs",
            "",
        ]

        # ── DSP function definitions ──
        emitted_fns: dict[str, str] = {}  # type_id → function name
        for name, voice in self._nodes.items():
            if voice.source_text and voice.type_id.startswith("faust:"):
                fn_name = name.replace("/", "_")
                lines.append("")
                # Emit source with @kr.dsp decorator
                source = voice.source_text.rstrip()
                if "@kr.dsp" not in source and "@dsp" not in source:
                    lines.append("@kr.dsp")
                lines.append(source)
                emitted_fns[voice.type_id] = fn_name
        for bname, bus in self._nodes.items():
            py_path = self._dsp_dir.joinpath(f"{bname}.py")
            if py_path.exists():
                fn_name = bname.replace("/", "_")
                source = py_path.read_text().rstrip()
                if fn_name not in emitted_fns.values():
                    lines.append("")
                    if "@kr.dsp" not in source and "@dsp" not in source:
                        lines.append("@kr.dsp")
                    lines.append(source)
                    emitted_fns[bus.type_id] = fn_name

        # ── Voices and buses ──
        lines.append("")
        lines.append("with kr.batch():")
        for name, voice in self._nodes.items():
            src = emitted_fns.get(voice.type_id, f'"{voice.type_id}"')
            init_kw = "".join(f", {k}={v}" for k, v in voice.init)
            count_kw = f", count={voice.count}" if voice.count > 1 else ""
            lines.append(f'    kr.voice("{name}", {src}, gain={voice.gain}{count_kw}{init_kw})')
        for bname, bus in self._nodes.items():
            src = emitted_fns.get(bus.type_id, f'"{bus.type_id}"')
            lines.append(f'    kr.bus("{bname}", {src}, gain={bus.gain})')

        # ── Sends and wires ──
        for (voice, bus), level in self._sends.items():
            lines.append(f'kr.send("{voice}", "{bus}", level={level})')
        for (voice, bus), port in self._wires.items():
            lines.append(f'kr.wire("{voice}", "{bus}", port="{port}")')

        # ── Transport ──
        try:
            lines.append(f"kr.tempo = {float(self.tempo)}")
        except (TypeError, ValueError):
            pass
        lines.append(f"kr.master = {self._master_gain}")
        try:
            meter = float(self.meter)
            if meter != 4.0:
                lines.append(f"kr.meter = {meter}")
        except (TypeError, ValueError):
            pass

        # ── Patterns as JSON ──
        if self._patterns:
            pat_dict = {slot: ir_to_dict(pat.node) for slot, pat in self._patterns.items()}
            pat_json = json.dumps(pat_dict, separators=(",", ":"))
            lines.append("")
            lines.append(f"_patterns = json.loads('{pat_json}')")
            lines.append("for _slot, _ir in _patterns.items():")
            lines.append("    kr.play(_slot, Pattern(dict_to_ir(_ir)))")

        # ── Control values ──
        for ctrl_path, value in self._ctrl_values.items():
            lines.append(f'kr.set("{ctrl_path}", {value})')

        lines.append("")
        Path(path).write_text("\n".join(lines))

    def _is_voice_or_bus(self, name: str) -> bool:
        """Check if name is a known node."""
        return name in self._nodes

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Play a pattern on a voice or control path.

        - Known voice name (exact match): binds bare params to ``voice/param``
        - Poly voice (count>1): round-robin allocates instances
        - Otherwise with ``/``: control path — rewrites ``"ctrl"`` placeholder
        - Otherwise without ``/``: mono voice binding (may be a new slot)

        ``from_zero``: if True, uses ``play_from_zero`` so the pattern phase
        starts at 0 regardless of the current cycle position.
        """
        if swing is not None:
            pattern = pattern.swing(swing)
        self._patterns[target] = pattern
        send = self._session.play_from_zero if from_zero else self._session.play
        voice = self._nodes.get(target)
        if voice is not None and voice.count > 1:
            bound_node, new_alloc = bind_voice_poly(
                pattern.node, target, voice.count, voice.alloc
            )
            voice.alloc = new_alloc
            send(target, Pattern(bound_node))
        elif self._is_voice_or_bus(target):
            bound = Pattern(bind_voice(pattern.node, target))
            send(target, bound)
        elif "/" in target:
            label = self._resolve_path(target)
            bound = Pattern(bind_ctrl(pattern.node, label))
            slot = f"_ctrl_{target.replace('/', '_')}"
            send(slot, bound)
        else:
            bound = Pattern(bind_voice(pattern.node, target))
            send(target, bound)

    def pattern(self, name: str) -> Pattern | None:
        """Retrieve the last unbound pattern played on a target. None if unplayed."""
        return self._patterns.get(name)

    def set(self, path: str, value: float) -> None:
        """Set a control value by path. Instant unless inside ``transition()``."""
        _check_finite(value, path)
        if self._transition_bars > 0:
            self.fade(path, value, bars=self._transition_bars)
        else:
            self._session.set_ctrl(path, float(value))
        self._ctrl_values[path] = value

    def _resolve_path(self, path: str) -> str:
        """Convert a user-facing ``/``-separated path to the exposed control label.

        Most paths are identity (``bass/cutoff`` → ``bass/cutoff``).
        Send levels use a special convention:
        ``bass/verb_send`` → ``bass_send_verb/gain``
        """
        if "/" not in path:
            return path
        parts = path.rsplit("/", 1)
        name, param = parts[0], parts[1]
        # Check if param ends with _send (send level shorthand)
        if param.endswith("_send"):
            bus = param[: -len("_send")]
            return f"{name}_send_{bus}/gain"
        return path

    def _resolve_targets_soft(self, name: str) -> list[str]:
        """Resolve name to matching nodes. Exact match first, then prefix. Empty if none."""
        if name in self._nodes:
            return [name]
        prefix = name + "/"
        return [n for n in self._nodes if n.startswith(prefix)]

    def fade(
        self, path: str, target: float, bars: int = 4, steps_per_bar: int = 4
    ) -> None:
        """Fade any parameter to target over N bars. One-shot (holds at target).

        Accepts either a voice name (fades gain) or a ``/``-separated path
        like ``"bass/gain"``, ``"bass/cutoff"``.

        For voice names: poly voices fade all instances proportionally.
        """
        if bars < 1 or steps_per_bar < 1:
            raise ValueError("bars and steps_per_bar must be >= 1")

        # Path-based fade: "bass/gain", "bass/cutoff", etc.
        if "/" in path:
            parts = path.split("/", 1)
            voice_name, param = parts[0], parts[1]

            # Determine current value
            if path in self._ctrl_values:
                current = self._ctrl_values[path]
            elif param == "gain" and voice_name in self._nodes:
                current = self._nodes[voice_name].gain
            else:
                current = 0.0

            # Clear any existing pattern-based control on this path
            ctrl_slot = f"_ctrl_{path.replace('/', '_')}"
            self._session.hush(ctrl_slot)

            # Use native automation (one-shot ramp)
            label = self._resolve_path(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(
                label, "ramp", current, target, period_secs, one_shot=True
            )
            self._ctrl_values[path] = target

            # Update gain bookkeeping if applicable
            if param == "gain":
                self._update_gain_bookkeeping(voice_name, target)
            return

        # Plain voice name → fade gain
        name = path
        if name not in self._nodes:
            return

        voice = self._nodes[name]
        for i in range(voice.count):
            inst = _inst_name(name, i, voice.count)
            self._fade_voice(inst, target / voice.count, bars, steps_per_bar)
        voice.gain = target

    def _fade_voice(
        self, name: str, target: float, bars: int, steps_per_bar: int
    ) -> None:
        """Schedule a gain fade for a single voice instance."""
        self._session.hush(f"_fade_{name}")
        # Find current gain for this instance
        # For poly instances, compute from parent
        current = target  # fallback
        for vname, voice in self._nodes.items():
            if voice.count == 1 and vname == name:
                current = voice.gain
                break
            if voice.count > 1:
                for i in range(voice.count):
                    if _inst_name(vname, i, voice.count) == name:
                        current = voice.gain / voice.count
                        break

        total_steps = bars * steps_per_bar
        ramp_atoms: list[Pattern] = []
        for i in range(total_steps + 1):
            t = i / total_steps
            value = current + (target - current) * t
            ramp_atoms.append(_ctrl(f"{name}/gain", value))
        # Hold: repeat target for 19x (one-shot behavior)
        hold_atom = _ctrl(f"{name}/gain", target)
        hold_atoms = [hold_atom] * (total_steps * 19)
        all_atoms = ramp_atoms + hold_atoms
        pattern = all_atoms[0]
        for a in all_atoms[1:]:
            pattern = pattern + a
        self._session.play(f"_fade_{name}", pattern.over(bars * 20))

    def _update_gain_bookkeeping(self, name: str, target: float) -> None:
        """Update gain bookkeeping after a path-based fade."""
        if name in self._nodes:
            self._nodes[name].gain = target

    def bus(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
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
        # Clean up old node if replacing
        if name in self._nodes:
            old = self._nodes[name]
            self.hush(name)
            self._muted.pop(name, None)
            for i in range(old.count):
                self._muted.pop(_inst_name(name, i, old.count), None)
            for key in [k for k in self._sends if k[0] == name or k[1] == name]:
                del self._sends[key]
            for key in [k for k in self._wires if k[0] == name or k[1] == name]:
                del self._wires[key]
        type_id, controls, _source_text = self._resolve_source(name, source)
        self._nodes[name] = Node(type_id=type_id, gain=gain, controls=controls, num_inputs=num_inputs)
        if not self._batching:
            self._rebuild()
        return NodeHandle(self, name)

    def send(self, voice: str, bus: str, level: float = 0.5) -> None:
        """Route a source node to a target node via a gain-controlled send.

        If the (voice, bus) pair already exists, does an instant level update
        (no rebuild). Otherwise stores the send and rebuilds.
        Raises ValueError if a wire exists for the same (voice, bus) pair.
        """
        _check_finite(level, f"send level for '{voice}' → '{bus}'")
        if voice not in self._nodes or bus not in self._nodes:
            missing = [n for n in (voice, bus) if n not in self._nodes]
            import warnings
            warnings.warn(f"send: skipped — node(s) not found: {missing}", stacklevel=2)
            return

        key = (voice, bus)

        if key in self._wires:
            raise ValueError(f"wire already exists for ('{voice}', '{bus}') — cannot also send")

        if key in self._sends:
            # Instant update — no rebuild
            self._sends[key] = level
            self._session.set_ctrl(f"{voice}_send_{bus}/gain", level)
            return

        self._sends[key] = level
        if not self._batching:
            self._rebuild()

    def wire(self, voice: str, bus: str, port: str = "in0") -> None:
        """Wire a source node directly to a target node port (no gain stage).

        Raises ValueError if a send exists for the same (voice, bus) pair.
        """
        if voice not in self._nodes or bus not in self._nodes:
            missing = [n for n in (voice, bus) if n not in self._nodes]
            import warnings
            warnings.warn(f"wire: skipped — node(s) not found: {missing}", stacklevel=2)
            return

        key = (voice, bus)

        if key in self._sends:
            raise ValueError(f"send already exists for ('{voice}', '{bus}') — cannot also wire")

        self._wires[key] = port
        if not self._batching:
            self._rebuild()

    def remove_bus(self, name: str) -> None:
        """Remove a bus and all sends/wires targeting it. No-op if not found."""
        if name not in self._nodes:
            return
        del self._nodes[name]
        for key in [k for k in self._sends if k[1] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[1] == name]:
            del self._wires[key]
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
            label = self._resolve_path(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(label, pattern_or_shape, lo, hi, period_secs)
        else:
            self.play(path, pattern_or_shape.over(bars), from_zero=True)

    @contextmanager
    def batch(self) -> Generator[None]:
        """Batch voice declarations into a single graph rebuild.

        Writes all .dsp files immediately but defers hot-reload waits and
        graph loading until the context manager exits.
        """
        self._batching = True
        snap_voices = dict(self._nodes)
        ok = False
        try:
            yield
            ok = True
        finally:
            self._batching = False
            if ok:
                self._flush()
            else:
                self._nodes = snap_voices

    @contextmanager
    def transition(self, bars: int = 4) -> Generator[None]:
        """Scoped interpolation: all gain/control changes inside become fades.

        Every ``set()``, ``gain()``, and ``NodeHandle[param] = value``
        inside this block will emit a ``fade()`` over ``bars`` bars
        instead of an instant change.
        """
        if self._transition_bars > 0:
            raise RuntimeError("nested transitions not supported")
        self._transition_bars = bars
        try:
            yield
        finally:
            self._transition_bars = 0

    def __repr__(self) -> str:
        count = len(self._nodes)
        lines = [f"VoiceMixer({count} nodes)"]
        if not self._nodes:
            return lines[0]

        max_name = max(len(n) for n in self._nodes)
        for name, node in self._nodes.items():
            kind = "fx" if node.num_inputs > 0 else "src"
            parts = f"  {name + ':':.<{max_name + 2}} {node.type_id}  gain={node.gain:.2f}  [{kind}]"
            if name in self._muted:
                parts += "  [muted]"
            if node.count > 1:
                parts += f"  poly({node.count})"
            lines.append(parts)

        return "\n".join(lines)

    def disconnect(self) -> None:
        """Disconnect from the audio engine."""
        self._session.disconnect()

    @property
    def master(self) -> float:
        """Master output gain (0.0-1.0)."""
        return self._master_gain

    @master.setter
    def master(self, value: float) -> None:
        _check_finite(value, "master gain")
        self._master_gain = value
        self._session.master_gain(value)

    @property
    def tempo(self) -> float:
        """Current tempo (BPM), delegated to session."""
        return self._session.tempo

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self._session.tempo = bpm

    @property
    def bpm(self) -> float:
        """Alias for tempo."""
        return self._session.tempo

    @bpm.setter
    def bpm(self, value: float) -> None:
        self._session.tempo = value

    @property
    def meter(self) -> float:
        """Current beats per cycle, delegated to session."""
        return self._session.meter

    @meter.setter
    def meter(self, beats: float) -> None:
        self._session.meter = beats

    @property
    def slots(self) -> dict[str, Any]:
        """Read-only snapshot of session slots."""
        return self._session.slots

    def get_node(self, name: str) -> Node | None:
        """Look up a node by name, or None if not found."""
        return self._nodes.get(name)

    def get_voice(self, name: str) -> Node | None:
        """Backward compat — same as get_node."""
        return self._nodes.get(name)

    def get_ctrl(self, node: str, param: str) -> float:
        """Get the last-set value for a node's control parameter."""
        return self._ctrl_values.get(f"{node}/{param}", 0.0)

    def is_muted(self, name: str) -> bool:
        """Check if a node is currently muted."""
        return name in self._muted

    def get_bus(self, name: str) -> Node | None:
        """Backward compat — same as get_node."""
        return self._nodes.get(name)

    @property
    def voice_data(self) -> dict[str, Node]:
        """Read-only snapshot of all nodes as raw Node structs."""
        return dict(self._nodes)

    @property
    def nodes(self) -> dict[str, NodeHandle]:
        """All nodes as name → NodeHandle."""
        return {name: NodeHandle(self, name) for name in self._nodes}

    @property
    def sources(self) -> dict[str, NodeHandle]:
        """Source nodes (num_inputs=0) as name → NodeHandle."""
        return {n: NodeHandle(self, n) for n, v in self._nodes.items() if v.num_inputs == 0}

    @property
    def effects(self) -> dict[str, NodeHandle]:
        """Effect nodes (num_inputs>0) as name → NodeHandle."""
        return {n: NodeHandle(self, n) for n, v in self._nodes.items() if v.num_inputs > 0}

    # Backward compat — prefer nodes/sources/effects
    @property
    def voices(self) -> dict[str, NodeHandle]:
        """Alias for sources."""
        return self.sources

    @property
    def buses(self) -> dict[str, NodeHandle]:
        """Alias for effects."""
        return self.effects

    @property
    def node_controls(self) -> dict[str, tuple[str, ...]]:
        """Read-only snapshot of known node type controls."""
        return dict(self._node_controls)

    def _flush(self) -> None:
        """Wait for all pending FAUST types and rebuild the graph once."""
        seen: set[str] = set()
        for node in self._nodes.values():
            if node.type_id.startswith("faust:") and node.type_id not in seen:
                seen.add(node.type_id)
                self._wait_for_type(node.type_id)
        self._rebuild()

    def _rebuild(self) -> None:
        ir = build_graph_ir(
            self._nodes,
            sends=self._sends,
            wires=self._wires,
        )
        self._session.load_graph(ir)
        self._graph_loaded = True

    def _wait_for_type(self, type_id: str, timeout: float = 10.0) -> None:
        """Poll until the engine has loaded the given FAUST type.

        Raises TimeoutError if the type doesn't appear within `timeout` seconds.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if type_id in self._session.list_nodes():
                    return
            except (TimeoutError, ConnectionError):
                pass
            time.sleep(0.1)
        raise TimeoutError(f"FAUST type '{type_id}' not ready after {timeout}s")


