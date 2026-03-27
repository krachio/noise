"""Mixer — graph-based audio node manager.

Manages FAUST DSP nodes (sources and effects), per-node gain, and the
underlying audio graph. Control labels: ``{node_name}/{param}``.
Adding or removing a node rebuilds the graph; gain updates are instant.

Contains: MixerProtocol (typed interface for NodeHandle), NodeHandle (proxy),
and Mixer (the graph manager).
"""

from __future__ import annotations

import inspect
import time
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from dataclasses import dataclass

from krach.graph.node import build_graph_ir, inst_name as _inst_name
from krach.pattern.mininotation import p as _p
from krach.graph.proxy import GraphProxy
from krach.graph.node import (
    ControlPath, DspDef, DspSource, GroupPath, Node, NodePath,
    ResolvedSource, UnknownPath, resolve_dsp_source, resolve_path,
)
from krach.ir.graph import ControlDef, GraphIr, MutedDef, NodeDef, PatternDef, RouteDef
from krach.pattern.bind import bind_ctrl, bind_voice, bind_voice_poly
from krach.pattern.builders import check_finite as _check_finite
from krach.pattern.pattern import Pattern
from krach.session import SlotState

if TYPE_CHECKING:
    from krach.pattern import Session


# ── MixerProtocol ────────────────────────────────────────────────────────


class MixerProtocol(Protocol):
    """Typed interface consumed by NodeHandle — decouples handle from Mixer."""

    def connect(self, source: str, target: str, level: float = ..., port: str | None = ...) -> None: ...
    def play(self, target: str, pattern: Pattern, *, from_zero: bool = ..., swing: float | None = ...) -> None: ...
    def hush(self, name: str) -> None: ...
    def send(self, source: str, target: str, level: float = ...) -> None: ...
    def pattern(self, name: str) -> Pattern | None: ...
    def remove(self, name: str) -> None: ...
    def set(self, path: str, value: float) -> None: ...
    def fade(self, path: str, target: float, bars: int = ..., steps_per_bar: int = ...) -> None: ...
    def mute(self, name: str) -> None: ...
    def unmute(self, name: str) -> None: ...
    def gain(self, name: str, value: float) -> None: ...
    def get_ctrl(self, node: str, param: str) -> float: ...
    def get_node(self, name: str) -> Node | None: ...
    def is_muted(self, name: str) -> bool: ...


# ── NodeHandle ───────────────────────────────────────────────────────────


class NodeHandle:
    """Proxy for a named node in the audio graph.

    Supports operator DSL: ``>>`` (routing), ``@`` (patterns), ``[]`` (controls).
    All operators delegate to Mixer methods.
    """

    def __init__(self, mixer: MixerProtocol, name: str) -> None:
        self._mixer = mixer
        self._name = name

    # ── Operator DSL ────────────────────────────────────────────────

    def __rshift__(self, other: NodeHandle | GraphHandle | tuple[NodeHandle | GraphHandle, float]) -> NodeHandle | GraphHandle:
        """Route signal: ``bass >> verb`` or ``bass >> (verb, 0.4)`` or ``bass >> module``."""
        if isinstance(other, tuple):
            target, level = other
            if isinstance(target, GraphHandle):
                self._mixer.connect(self._name, target.input._name, level=level)
                return target
            self._mixer.connect(self._name, target._name, level=level)
            return target
        if isinstance(other, GraphHandle):
            self._mixer.connect(self._name, other.input._name)
            return other
        if isinstance(other, NodeHandle):  # pyright: ignore[reportUnnecessaryIsInstance]
            self._mixer.connect(self._name, other._name)
            return other
        raise TypeError(
            f"{self._name} >> {type(other).__name__} — expected NodeHandle, GraphHandle, or tuple.\n"
            f"  Try: {self._name} >> verb           — route to verb\n"
            f"       {self._name} >> (verb, 0.4)    — route at 40% level"
        )

    def __matmul__(self, pattern: Pattern | str | tuple[str, Pattern] | None) -> NodeHandle:
        """Play pattern: ``bass @ pattern``, ``bass @ \"A2 D3\"``, ``bass @ None``."""
        if pattern is None:
            self._mixer.hush(self._name)
        elif isinstance(pattern, str):
            self._mixer.play(self._name, _p(pattern))
        elif isinstance(pattern, tuple):
            if len(pattern) == 2:
                param, pat = pattern
                if isinstance(param, str) and isinstance(pat, Pattern):  # pyright: ignore[reportUnnecessaryIsInstance]
                    self._mixer.play(f"{self._name}/{param}", pat)
                    return self
            raise TypeError(f"expected (str, Pattern) tuple, got {pattern!r}")
        else:
            self._mixer.play(self._name, pattern)
        return self

    def __getitem__(self, param: str) -> float:
        """Get control value: ``bass[\"cutoff\"]``."""
        return self._mixer.get_ctrl(self._name, param)

    def __setitem__(self, param: str, value: float) -> None:
        """Set control value: ``bass[\"cutoff\"] = 1200``."""
        self._mixer.set(f"{self._name}/{param}", value)

    # ── Explicit API ───────────────────────────────────────────────

    def play(self, target_or_pattern: str | Pattern, pattern: Pattern | None = None) -> None:
        """Play a pattern on this node or a specific control path."""
        if pattern is not None and isinstance(target_or_pattern, str):
            self._mixer.play(f"{self._name}/{target_or_pattern}", pattern)
        else:
            if not isinstance(target_or_pattern, Pattern):
                raise TypeError(
                    f"{self._name}.play() expected Pattern or (param_name, Pattern), "
                    f"got {type(target_or_pattern).__name__}"
                )
            self._mixer.play(self._name, target_or_pattern)

    def pattern(self) -> Pattern | None:
        """Retrieve the last unbound pattern played on this node."""
        return self._mixer.pattern(self._name)

    def set(self, param: str, value: float) -> None:
        self._mixer.set(f"{self._name}/{param}", value)

    def fade(self, param: str, target: float, bars: int = 4) -> None:
        self._mixer.fade(f"{self._name}/{param}", target, bars=bars)

    def send(self, bus: NodeHandle | str, level: float = 0.5) -> None:
        bus_name = bus.name if isinstance(bus, NodeHandle) else bus
        self._mixer.send(self._name, bus_name, level)

    def mute(self) -> None:
        self._mixer.mute(self._name)

    def unmute(self) -> None:
        self._mixer.unmute(self._name)

    def hush(self) -> None:
        self._mixer.hush(self._name)

    def gain(self, value: float) -> None:
        self._mixer.gain(self._name, value)

    @property
    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:
        node = self._mixer.get_node(self._name)
        if node:
            parts = f"Node('{self._name}', {node.type_id}, gain={node.gain:.2f}"
            if node.count > 1:
                parts += f", count={node.count}"
            if self._mixer.is_muted(self._name):
                parts += ", muted"
            return parts + ")"
        return f"Node('{self._name}', removed)"


# ── GraphHandle ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GraphHandle:
    """Thin operator proxy for an instantiated module."""

    prefix: str
    nodes: dict[str, NodeHandle]
    inputs: tuple[str, ...] | None
    outputs: tuple[str, ...] | None

    def _strip_prefix(self, name: str) -> str:
        """Strip prefix from a fully-qualified name to get relative name."""
        pfx = self.prefix + "/"
        return name[len(pfx):] if name.startswith(pfx) else name

    @property
    def input(self) -> NodeHandle:
        """First declared input as NodeHandle."""
        if not self.inputs:
            raise ValueError(f"module {self.prefix!r} has no declared inputs")
        return self.nodes[self._strip_prefix(self.inputs[0])]

    @property
    def output(self) -> NodeHandle:
        """First declared output as NodeHandle."""
        if not self.outputs:
            raise ValueError(f"module {self.prefix!r} has no declared outputs")
        return self.nodes[self._strip_prefix(self.outputs[0])]

    def __rshift__(self, other: NodeHandle | GraphHandle | tuple[NodeHandle | GraphHandle, float]) -> NodeHandle | GraphHandle:
        """Route module output to target."""
        return self.output >> other  # type: ignore[operator, return-value]

    def __rrshift__(self, other: NodeHandle) -> GraphHandle:
        """Allow node >> module_handle."""
        _ = other >> self.input
        return self

    def __matmul__(self, pattern: object) -> GraphHandle:
        """Play pattern on first input."""
        _ = self.input @ pattern  # type: ignore[operator]
        return self

    def __getitem__(self, path: str) -> float:
        """Get control: handle['node/param']."""
        return self.nodes[path.split("/")[0]]["/".join(path.split("/")[1:])]  # type: ignore[return-value]

    def __setitem__(self, path: str, value: float) -> None:
        """Set control: handle['node/param'] = value."""
        full_path = f"{self.prefix}/{path}"
        first_node = next(iter(self.nodes.values()))
        first_node._mixer.set(full_path, value)  # pyright: ignore[reportPrivateUsage]

    def __repr__(self) -> str:
        inputs = list(self.inputs) if self.inputs else []
        outputs = list(self.outputs) if self.outputs else []
        return f"GraphHandle({self.prefix!r}, inputs={inputs}, outputs={outputs})"


# ── Mixer ────────────────────────────────────────────────────────────────


class Mixer:
    """Manages named audio nodes with stable control labels.

    Each node is a FAUST DSP source or effect (string type_id or Python function)
    with an independent gain stage. Adding/removing nodes rebuilds the audio
    graph transparently. ``gain()`` updates are instant (no rebuild).

    For REPL convenience, use ``LiveMixer`` from ``krach.repl`` —
    it adds ``__setattr__`` typo guard. Pattern builders live in ``krp``
    (``from krach import pattern as krp``).
    """

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
        self._muted: dict[str, float] = {}
        self._sends: dict[tuple[str, str], float] = {}
        self._wires: dict[tuple[str, str], str] = {}
        self._ctrl_values: dict[str, float] = {}
        self._patterns: dict[str, Pattern] = {}
        self._scenes: dict[str, GraphIr] = {}
        self._batching: bool = False
        self._shadow_sub_graphs: list[tuple[str, GraphIr]] = []

        self._graph_sent: bool = False
        self._master_gain: float = 0.7
        self._transition_bars: int = 0
        self._flush_scheduled: bool = False
        self._session.master_gain(self._master_gain)

    # ── Transport properties ──────────────────────────────────────

    @property
    def master(self) -> float:
        """Master output gain (0.0-1.0)."""
        return self._master_gain

    @master.setter
    def master(self, value: float) -> None:
        _check_finite(value, "master gain")
        if abs(value) > 2.0:
            warnings.warn(f"master gain {value}: magnitude >2.0 — risk of clipping", stacklevel=2)
        self._master_gain = value
        self._session.master_gain(value)

    @property
    def tempo(self) -> float:
        """Current tempo (BPM), delegated to session."""
        return self._session.tempo

    @tempo.setter
    def tempo(self, value: float) -> None:
        self._session.tempo = value

    @property
    def meter(self) -> float:
        """Current beats per cycle, delegated to session."""
        return self._session.meter

    @meter.setter
    def meter(self, beats: float) -> None:
        self._session.meter = beats

    @property
    def sync(self) -> str:
        """Current clock source: "internal" or "midi"."""
        return self._session.clock_source

    @sync.setter
    def sync(self, source: str) -> None:
        self._session.set_clock_source(source)

    # ── State accessors ───────────────────────────────────────────

    @property
    def slots(self) -> dict[str, SlotState]:
        """Read-only snapshot of session slots."""
        return self._session.slots

    def get_node(self, name: str) -> Node | None:
        """Look up a node by name, or None if not found."""
        return self._nodes.get(name)

    def get_ctrl(self, node: str, param: str) -> float:
        """Get the last-set value for a node's control parameter."""
        return self._ctrl_values.get(f"{node}/{param}", 0.0)

    def is_muted(self, name: str) -> bool:
        """Check if a node is currently muted."""
        return name in self._muted

    @property
    def node_data(self) -> dict[str, Node]:
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

    @property
    def node_controls(self) -> dict[str, tuple[str, ...]]:
        """Read-only snapshot of known node type controls."""
        return dict(self._node_controls)

    @property
    def routing(self) -> list[tuple[str, str, str, float | str]]:
        """Routing snapshot: list of (source, target, kind, level_or_port)."""
        sends = dict(self._sends)
        wires = dict(self._wires)
        result: list[tuple[str, str, str, float | str]] = []
        for (src, tgt), lvl in sends.items():
            result.append((src, tgt, "send", lvl))
        for (src, tgt), port in wires.items():
            result.append((src, tgt, "wire", port))
        return result

    @property
    def ctrl_values(self) -> dict[str, float]:
        """Read-only snapshot of all set control values."""
        return dict(self._ctrl_values)

    # ── State sync ─────────────────────────────────────────────────

    def pull(self) -> None:
        """Sync local state from the engine (source of truth).

        Rebuilds _nodes, _sends, _ctrl_values, and transport from the
        engine snapshot. Preserves local-only state: source_text,
        control_ranges, patterns, scenes, muted.
        """
        state = self._session.pull()
        nodes_raw: list[dict[str, object]] = state.get("nodes", [])  # type: ignore[assignment]
        connections: list[dict[str, str]] = state.get("connections", [])  # type: ignore[assignment]
        ctrl_vals: dict[str, float] = state.get("control_values", {})  # type: ignore[assignment]
        transport: dict[str, float] = state.get("transport", {})  # type: ignore[assignment]

        # Build lookup: node_id → raw node dict
        raw_by_id: dict[str, dict[str, object]] = {
            str(n.get("id", "")): n for n in nodes_raw
        }

        # Identify helper nodes: gain wrappers ({name}_g) and send gains ({a}_send_{b})
        real_nodes: dict[str, dict[str, object]] = {}
        gain_nodes: dict[str, float] = {}  # node_id → gain value
        send_nodes: dict[str, tuple[str, str, float]] = {}  # node_id → (src, dst, level)

        for nid, raw in raw_by_id.items():
            type_id = str(raw.get("type_id", ""))
            controls = raw.get("controls", {})
            gain_val = float(controls.get("gain", 0.5)) if isinstance(controls, dict) else 0.5  # type: ignore[union-attr]

            if nid == "out" and type_id == "dac":
                continue  # skip output node
            if type_id == "gain" and nid.endswith("_g"):
                gain_nodes[nid] = gain_val
            elif type_id == "gain" and "_send_" in nid:
                parts = nid.split("_send_", 1)
                if len(parts) == 2:
                    send_nodes[nid] = (parts[0], parts[1], gain_val)
            else:
                real_nodes[nid] = raw

        # Reconstruct Node entries for real nodes
        new_nodes: dict[str, Node] = {}
        for nid, raw in real_nodes.items():
            type_id = str(raw.get("type_id", ""))
            controls_dict: dict[str, float] = (
                raw.get("controls") if isinstance(raw.get("controls"), dict) else {}  # type: ignore[assignment]
            )
            ctrl_names: tuple[str, ...] = tuple(controls_dict.keys())
            gain = gain_nodes.get(f"{nid}_g", 0.5)

            # Detect num_inputs from connections (any connection TO this node)
            has_audio_input = any(
                c.get("to_node") == nid and c.get("to_port", "").startswith("in")
                and c.get("from_node") not in send_nodes  # exclude send gain → effect
                for c in connections
            )
            # Preserve existing node if we have it (keeps source_text, control_ranges)
            existing = self._nodes.get(nid)
            if existing is not None:
                existing.gain = gain
                new_nodes[nid] = existing
            else:
                new_nodes[nid] = Node(
                    type_id=type_id,
                    gain=gain,
                    controls=ctrl_names,
                    num_inputs=1 if has_audio_input else 0,
                )

        self._nodes = new_nodes

        # Reconstruct sends
        new_sends: dict[tuple[str, str], float] = {}
        for _, (src, dst, level) in send_nodes.items():
            if src in new_nodes and dst in new_nodes:
                new_sends[(src, dst)] = level
        self._sends = new_sends

        # Sync control values (only for labels we can see)
        self._ctrl_values.update(ctrl_vals)

        # Sync transport
        if "master" in transport:
            self._master_gain = float(transport["master"])



    # ── Node lifecycle ────────────────────────────────────────────

    def _cleanup_node(self, name: str, direction: Literal["source", "both"] = "source") -> None:
        """Clean up state for a node being replaced or removed."""
        if name in self._nodes:
            old = self._nodes[name]
            self.hush(name)
            self._muted.pop(name, None)
            for i in range(old.count):
                self._muted.pop(_inst_name(name, i, old.count), None)
            # Clean up ctrl_values for parent and all voice instances
            prefix = f"{name}/"
            inst_prefixes = [
                f"{_inst_name(name, i, old.count)}/"
                for i in range(old.count) if old.count > 1
            ]
            stale = [
                k for k in self._ctrl_values
                if k.startswith(prefix) or any(k.startswith(p) for p in inst_prefixes)
            ]
            for k in stale:
                del self._ctrl_values[k]
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
        If the target has num_inputs=0, promotes it to an effect (num_inputs=1).
        """
        if target in self._nodes and self._nodes[target].num_inputs == 0:
            self._nodes[target].num_inputs = 1
        if port is not None:
            self.wire(source, target, port=port)
        else:
            self.send(source, target, level=level)

    def voice(
        self,
        name: str,
        source: DspSource,
        gain: float = 0.5,
        count: int = 1,
        **init: float,
    ) -> NodeHandle:
        """Add or replace a source node. Rebuilds the graph."""
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
        for ctrl, default in resolved.control_defaults.items():
            self._ctrl_values.setdefault(f"{name}/{ctrl}", default)
        if not self._batching:
            if is_new and self._graph_sent and count == 1:
                self._session.add_voice(name, resolved.type_id, resolved.controls, gain)
            else:
                self._rebuild()
        return NodeHandle(self, name)

    def bus(
        self,
        name: str,
        source: DspSource,
        gain: float = 0.5,
    ) -> NodeHandle:
        """Add or replace an effect bus. Rebuilds the graph."""
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
                return
        # Clean shadow sub_graphs: remove exact prefix match OR any prefix
        # whose nodes have been partially/fully removed (partial module = invalid)
        self._shadow_sub_graphs = [
            (p, ir) for p, ir in self._shadow_sub_graphs
            if p != name and all(
                f"{p}/{nd.name}" in self._nodes for nd in ir.nodes
            )
        ]

    def input(self, name: str = "mic", channel: int = 0, gain: float = 0.5) -> NodeHandle:
        """Add an audio input node (ADC)."""
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
        """Map a MIDI CC to a control path."""
        label = self._resolve_label(path)
        self._session.midi_map(channel, cc, label, lo, hi)

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

    # ── Play / pattern ────────────────────────────────────────────

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Play a pattern on a node or control path."""
        if swing is not None:
            pattern = pattern.swing(swing)
        self._patterns[target] = pattern
        send = self._session.play_from_zero if from_zero else self._session.play

        pn = pattern.node

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
                warnings.warn(
                    f"play('{raw}', ...): no node named '{raw}' — pattern sent but may produce no audio",
                    stacklevel=2,
                )
                if "/" in raw:
                    slot = f"_ctrl_{raw.replace('/', '_')}"
                    send(slot, Pattern(bind_ctrl(pn, raw)))
                else:
                    send(raw, Pattern(bind_voice(pn, raw)))

    def pattern(self, name: str) -> Pattern | None:
        """Retrieve the last unbound pattern played on a target. None if unplayed."""
        return self._patterns.get(name)

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

    # ── Routing ───────────────────────────────────────────────────

    def send(self, source: str, target: str, level: float = 0.5) -> None:
        """Route a source node to a target node via a gain-controlled send."""
        _check_finite(level, f"send level for '{source}' → '{target}'")
        if source not in self._nodes or target not in self._nodes:
            missing = [n for n in (source, target) if n not in self._nodes]
            warnings.warn(f"send: skipped — node(s) not found: {missing}", stacklevel=2)
            return

        key = (source, target)

        if key in self._wires:
            raise ValueError(f"wire already exists for ('{source}', '{target}') — cannot also send")

        if key in self._sends:
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

    # ── Gain / mute / solo ─────────────────────────────────────────

    def _resolve_node_targets(self, name: str) -> list[str]:
        """Resolve name to matching node names via resolve_path."""
        match resolve_path(name, self._nodes):
            case NodePath(n):
                return [n]
            case GroupPath(members=members):
                return list(members)
            case ControlPath() | UnknownPath():
                return []

    def gain(self, name: str, value: float) -> None:
        """Update a node or group gain. Instant — no graph rebuild."""
        _check_finite(value, f"gain for '{name}'")
        if abs(value) > 2.0:
            warnings.warn(f"gain('{name}', {value}): magnitude >2.0 — risk of clipping", stacklevel=2)
        for t in self._resolve_node_targets(name):
            self._gain_single(t, value)

    def _gain_single(self, name: str, value: float) -> None:
        if self._transition_bars > 0:
            self.fade(f"{name}/gain", value, bars=self._transition_bars)
            if name in self._nodes:
                self._nodes[name].gain = value
            return
        node = self._nodes[name]
        node.gain = value
        if node.count > 1:
            per_node = value / node.count
            for i in range(node.count):
                self._session.set_ctrl(f"{_inst_name(name, i, node.count)}/gain", float(per_node))
        else:
            self._session.set_ctrl(f"{name}/gain", float(value))

    def mute(self, name: str) -> None:
        """Mute a node or group. No-op if not found."""
        for t in self._resolve_node_targets(name):
            if t not in self._muted and t in self._nodes:
                self._muted[t] = self._nodes[t].gain
            self._gain_single(t, 0.0)

    def unmute(self, name: str) -> None:
        """Unmute a node or group — restores gain saved by mute()."""
        targets = self._resolve_node_targets(name)
        if not targets:
            self._muted.pop(name, None)
            return
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def solo(self, name: str) -> None:
        """Solo a node or group — mutes all others. No-op if not found."""
        targets = set(self._resolve_node_targets(name))
        if not targets:
            return
        for n in set(self._nodes.keys()):
            if n not in targets:
                if n not in self._muted and n in self._nodes:
                    self._muted[n] = self._nodes[n].gain
                self._gain_single(n, 0.0)
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def unsolo(self) -> None:
        """Unmute all muted nodes."""
        for name in list(self._muted):
            self.unmute(name)

    # ── Control set ────────────────────────────────────────────────

    def set(self, path: str, value: float) -> None:
        """Set a control value by path. Fans out to all instances for poly nodes."""
        _check_finite(value, path)
        self._warn_if_outside_range(path, value)
        self._ctrl_values[path] = value
        if self._transition_bars > 0:
            self.fade(path, value, bars=self._transition_bars)
            return
        for label in self._expand_poly_labels(path):
            self._session.set_ctrl(label, float(value))

    def _warn_if_outside_range(self, path: str, value: float) -> None:
        match resolve_path(path, self._nodes):
            case ControlPath(node=node_name, param=param):
                n = self._nodes.get(node_name)
                if n is None:
                    return
                rng = n.control_ranges.get(param)
                if rng is None:
                    return
                lo, hi = rng
                if value < lo or value > hi:
                    warnings.warn(
                        f"set('{path}', {value}): value outside declared range "
                        f"[{lo}, {hi}] for '{param}' — Faust will clamp",
                        stacklevel=3,
                    )
            case _:
                pass

    def _warn_unknown_controls(self, name: str, node: Node, pattern: Pattern) -> None:
        from krach.pattern.bind import collect_control_labels
        labels = collect_control_labels(pattern.node)
        if not labels:
            return
        known = set(node.controls) | {"gain"}
        unknown = {lab for lab in labels if lab not in known}
        if unknown:
            warnings.warn(
                f"play('{name}', ...): unknown control(s) {sorted(unknown)} "
                f"— available: {sorted(known)}",
                stacklevel=4,
            )

    def _warn_pattern_range(self, node_name: str, param: str, pattern: Pattern) -> None:
        from krach.pattern.bind import collect_control_values
        n = self._nodes.get(node_name)
        if n is None:
            return
        rng = n.control_ranges.get(param)
        if rng is None:
            return
        lo, hi = rng
        values = collect_control_values(pattern.node)
        if not values:
            return
        v_min, v_max = min(values), max(values)
        if v_min < lo or v_max > hi:
            warnings.warn(
                f"play('{node_name}/{param}', ...): pattern values [{v_min}, {v_max}] "
                f"outside declared range [{lo}, {hi}] — Faust will clamp",
                stacklevel=3,
            )

    def _expand_poly_labels(self, path: str) -> list[str]:
        """Expand a control path to per-instance labels for poly nodes."""
        match resolve_path(path, self._nodes):
            case ControlPath(node=node, param=param):
                n = self._nodes.get(node)
                if n is not None and n.count > 1:
                    return [
                        f"{_inst_name(node, i, n.count)}/{param}"
                        for i in range(n.count)
                    ]
                return [path]
            case _:
                return [path]

    def _resolve_label(self, path: str) -> str:
        """Resolve a user-facing path to an engine control label."""
        match resolve_path(path, self._nodes):
            case ControlPath(label=label):
                return label
            case _:
                return path

    # ── Fade / automation ──────────────────────────────────────────

    def fade(
        self, path: str, target: float, bars: int = 4, steps_per_bar: int = 4
    ) -> None:
        """Fade any parameter to target over N bars."""
        if bars < 1 or steps_per_bar < 1:
            raise ValueError("bars and steps_per_bar must be >= 1")
        match resolve_path(path, self._nodes):
            case NodePath(name):
                self._fade_node(name, target, bars)
            case ControlPath(node=node, param=param, label=label):
                self._fade_control(path, node, param, label, target, bars)
            case GroupPath(members=members):
                for m in members:
                    self._fade_node(m, target, bars)
            case UnknownPath():
                self._fade_node(path, target, bars)

    def _fade_control(
        self, path: str, node: str, param: str, label: str,
        target: float, bars: int,
    ) -> None:
        if path in self._ctrl_values:
            current = self._ctrl_values[path]
        elif param == "gain" and node in self._nodes:
            current = self._nodes[node].gain
        else:
            current = 0.0
        ctrl_slot = f"_ctrl_{path.replace('/', '_')}"
        self._session.hush(ctrl_slot)
        beats = bars * self._session.meter
        period_secs = beats * 60.0 / max(float(self._session.tempo), 1.0)
        for inst_label in self._expand_poly_labels(path):
            self._session.set_automation(inst_label, "ramp", current, target, period_secs, one_shot=True)
        self._ctrl_values[path] = target
        if param == "gain" and node in self._nodes:
            self._nodes[node].gain = target

    def _fade_node(self, name: str, target: float, bars: int) -> None:
        if name not in self._nodes:
            return
        node = self._nodes[name]
        per_gain = node.gain / node.count
        for i in range(node.count):
            inst = _inst_name(name, i, node.count)
            self._fade_instance(inst, per_gain, target / node.count, bars)
        node.gain = target

    def _fade_instance(self, label: str, current: float, target: float, bars: int) -> None:
        try:
            period_secs = bars * float(self._session.meter) * 60.0 / max(float(self._session.tempo), 1.0)
        except (TypeError, ValueError):
            period_secs = bars * 2.0
        self._session.set_automation(f"{label}/gain", "ramp", current, target, period_secs, one_shot=True)

    # ── Modulation ────────────────────────────────────────────────

    def mod(
        self, path: str, pattern_or_shape: Pattern | str,
        lo: float = 0.0, hi: float = 1.0, bars: int = 1,
    ) -> None:
        """Modulate a control parameter."""
        if isinstance(pattern_or_shape, str):
            label = self._resolve_label(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(label, pattern_or_shape, lo, hi, period_secs)
        else:
            self.play(path, pattern_or_shape.over(bars), from_zero=True)

    # ── Graph rebuild infrastructure ──────────────────────────────

    def disconnect(self) -> None:
        """Disconnect from the audio engine."""
        self._session.disconnect()

    def _flush(self) -> None:
        """Wait for all pending FAUST types and rebuild the graph once."""
        seen: set[str] = set()
        for node in self._nodes.values():
            if node.type_id.startswith("faust:") and node.type_id not in seen:
                seen.add(node.type_id)
                self._wait_for_type(node.type_id)
        self._rebuild()

    def _rebuild(self) -> None:
        ir = build_graph_ir(self._nodes, sends=self._sends, wires=self._wires)
        self._session.load_graph(ir)

        self._graph_sent = True

    def _wait_for_type(self, type_id: str, timeout: float = 10.0) -> None:
        """Poll until the engine has loaded the given FAUST type."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if type_id in self._session.list_nodes():
                    return
            except (TimeoutError, ConnectionError):
                pass
            time.sleep(0.1)
        raise TimeoutError(f"FAUST type '{type_id}' not ready after {timeout}s")

    # ── Context managers ───────────────────────────────────────────

    @contextmanager
    def batch(self) -> Generator[None]:
        """Batch node declarations into a single graph rebuild."""
        self._batching = True
        snap_nodes = dict(self._nodes)
        snap_sends = dict(self._sends)
        snap_wires = dict(self._wires)
        snap_ctrl = dict(self._ctrl_values)
        snap_patterns = dict(self._patterns)
        snap_muted = dict(self._muted)
        ok = False
        try:
            yield
            ok = True
        finally:
            self._batching = False
            if ok:
                self._flush()
            else:
                self._nodes = snap_nodes
                self._sends = snap_sends
                self._wires = snap_wires
                self._ctrl_values = snap_ctrl
                self._patterns = snap_patterns
                self._muted = snap_muted

    @contextmanager
    def transition(self, bars: int = 4) -> Generator[None]:
        """Scoped interpolation: gain/control changes become fades over N bars."""
        if self._transition_bars > 0:
            raise RuntimeError("nested transitions not supported")
        self._transition_bars = bars
        try:
            yield
        finally:
            self._transition_bars = 0

    # ── Scenes ─────────────────────────────────────────────────────

    def save(self, name: str) -> None:
        """Save current state as a named scene (via GraphIr)."""
        self._scenes[name] = self.capture()

    def recall(self, name: str) -> None:
        """Recall a saved scene — clears state, then instantiates the saved GraphIr."""
        if name not in self._scenes:
            raise ValueError(f"scene '{name}' not found")
        self.stop()
        for n in list(self._nodes):
            self._cleanup_node(n, direction="both")
        self._nodes.clear()
        self._sends.clear()
        self._wires.clear()
        self._ctrl_values.clear()
        self._muted.clear()
        self._patterns.clear()
        self._shadow_sub_graphs.clear()
        self.load(self._scenes[name])

    @property
    def scenes(self) -> list[str]:
        """List of saved scene names."""
        return list(self._scenes.keys())

    # ── Module operations ─────────────────────────────────────────

    def trace(self) -> GraphProxy:
        """Return a tracing proxy that records calls as GraphIr."""
        return GraphProxy()

    def scene(self, name: str) -> GraphIr:
        """Get a saved scene by name."""
        if name not in self._scenes:
            raise ValueError(f"scene '{name}' not found")
        return self._scenes[name]

    def exec_file(self, path: str) -> None:
        """Load and execute a Python file with ``kr`` in scope."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"scene file not found: {path}")
        code = p.read_text()
        try:
            exec(compile(code, path, "exec"), {"kr": self, "mix": self})  # noqa: S102
        except Exception as e:
            raise RuntimeError(f"error loading {path}: {e}") from e

    def capture(self) -> GraphIr:
        """Snapshot current mixer state as a frozen GraphIr."""
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

        return GraphIr(
            nodes=nodes,
            routing=tuple(routing),
            patterns=patterns,
            controls=controls,
            muted=muted,
            tempo=tempo,
            meter=meter,
            master=self._master_gain,
            sub_graphs=tuple(self._shadow_sub_graphs),
        )

    def load(self, ir: GraphIr) -> None:
        """Replay a GraphIr onto this mixer. Batches all nodes into one rebuild."""
        from krach.ir.graph import flatten

        # Save sub_graphs before flatten (flatten resolves them into flat nodes)
        original_sub_graphs = ir.sub_graphs
        ir = flatten(ir)
        # Restore shadow sub_graphs from the original IR
        for prefix, sub_ir in original_sub_graphs:
            self._shadow_sub_graphs.append((prefix, sub_ir))
        with self.batch():
            for nd in ir.nodes:
                source: DspSource
                if isinstance(nd.source, str):
                    source = nd.source
                else:
                    if not nd.source_text:
                        raise ValueError(f"node '{nd.name}': DspGraph source requires source_text for replay")
                    source = nd.source_text
                self.voice(nd.name, source, gain=nd.gain, count=nd.count, **dict(nd.init))
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

    def instantiate(self, ir: GraphIr, prefix: str) -> GraphHandle:
        """Instantiate a module with prefix namespace. Returns a GraphHandle."""
        from krach.ir.graph import prefix_ir, flatten

        flat = flatten(prefix_ir(ir, prefix))
        self.load(flat)

        # Build node handles for all prefixed nodes
        nodes: dict[str, NodeHandle] = {}
        for nd in flat.nodes:
            # Strip prefix to get relative name
            rel = nd.name[len(prefix) + 1:] if nd.name.startswith(prefix + "/") else nd.name
            nodes[rel] = NodeHandle(self, nd.name)

        # Resolve inputs/outputs to prefixed names
        flat_inputs = flat.inputs
        flat_outputs = flat.outputs

        # Record shadow
        self._shadow_sub_graphs.append((prefix, ir))

        return GraphHandle(
            prefix=prefix,
            nodes=nodes,
            inputs=flat_inputs,
            outputs=flat_outputs,
        )

    def export(self, path: str) -> None:
        """Export current session state to a reloadable Python script."""
        from krach.export import export_session
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

    # ── Repr ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        count = len(self._nodes)
        lines = [f"Mixer({count} nodes)"]
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
