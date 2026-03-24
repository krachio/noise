"""Mixer infrastructure — properties, accessors, graph rebuild.

Separated from _mixer.py to keep Mixer under 500 lines.
These are pure read/delegate operations with no orchestration logic.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from krach._graph import build_graph_ir, inst_name as _inst_name
from krach._handle import NodeHandle
from krach._patterns import (
    cat, check_finite as _check_finite, hit, mod_exp, mod_ramp, mod_ramp_down,
    mod_sine, mod_square, mod_tri, note, rand, ramp, saw, seq, sine, stack, struct,
)
from krach._pitch import ftom as _ftom, mtof as _mtof, parse_note as _parse_note
from krach._types import ControlPath, GroupPath, Node, NodePath, UnknownPath, dsp, resolve_path
from krach.patterns.pattern import Pattern
from krach.patterns.session import SlotState
from krach.patterns.pattern import rest as _rest

if TYPE_CHECKING:
    from krach.patterns import Session


class MixerInfra:
    """Infrastructure mixin: properties, accessors, graph rebuild, static API surface."""

    # ── Pattern builders (static) ─────────────────────────────────────
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
    sine = staticmethod(sine)
    saw = staticmethod(saw)
    rand = staticmethod(rand)
    cat = staticmethod(cat)
    stack = staticmethod(stack)
    struct = staticmethod(struct)
    mtof = staticmethod(_mtof)
    ftom = staticmethod(_ftom)
    parse_note = staticmethod(_parse_note)
    from krach._mininotation import p as _p
    p = staticmethod(_p)

    # Methods implemented by Mixer — declared here so NodeHandle can type-check against MixerInfra
    def connect(self, source: str, target: str, level: float = 1.0, port: str | None = None) -> None:
        raise NotImplementedError

    def play(self, target: str, pattern: Pattern, *, from_zero: bool = False, swing: float | None = None) -> None:
        raise NotImplementedError

    def hush(self, name: str) -> None:
        raise NotImplementedError

    def send(self, source: str, target: str, level: float = 0.5) -> None:
        raise NotImplementedError

    def pattern(self, name: str) -> Pattern | None:
        raise NotImplementedError

    def remove(self, name: str) -> None:
        raise NotImplementedError

    # Fields defined on Mixer.__init__ — declared here for type checking
    _session: Session
    _master_gain: float
    _nodes: dict[str, Node]
    _ctrl_values: dict[str, float]
    _muted: dict[str, float]
    _sends: dict[tuple[str, str], float]
    _wires: dict[tuple[str, str], str]
    _node_controls: dict[str, tuple[str, ...]]
    _graph_loaded: bool
    _batching: bool
    _transition_bars: int

    # ── Transport properties ──────────────────────────────────────────

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

    # ── State accessors ───────────────────────────────────────────────

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

    # ── Graph rebuild infrastructure ──────────────────────────────────

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
        self._graph_loaded = True

    # ── Context managers ───────────────────────────────────────────

    @contextmanager
    def batch(self) -> Generator[None]:
        """Batch node declarations into a single graph rebuild."""
        self._batching = True
        snap = dict(self._nodes)
        ok = False
        try:
            yield
            ok = True
        finally:
            self._batching = False
            if ok:
                self._flush()
            else:
                self._nodes = snap

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
        """Warn if value is outside the control's declared range."""
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
        """Warn if a pattern references controls not present on the node."""
        from krach._bind import collect_control_labels
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
        """Warn if a control pattern's values fall outside the declared range."""
        from krach._bind import collect_control_values
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
        """Expand a control path to per-instance labels for poly nodes.

        'pad/cutoff' with count=4 → ['pad_v0/cutoff', ..., 'pad_v3/cutoff'].
        'bass/cutoff' with count=1 → ['bass/cutoff'] (unchanged).
        """
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
