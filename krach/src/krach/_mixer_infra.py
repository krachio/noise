"""VoiceMixer infrastructure — properties, accessors, graph rebuild.

Separated from _mixer.py to keep VoiceMixer under 500 lines.
These are pure read/delegate operations with no orchestration logic.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from krach._graph import build_graph_ir
from krach._handle import NodeHandle
from krach._patterns import check_finite as _check_finite
from krach._types import Node

if TYPE_CHECKING:
    from krach.patterns import Session


class MixerInfra:
    """Infrastructure mixin: properties, accessors, graph rebuild."""

    # These fields are defined on VoiceMixer.__init__ — declared here for type checking
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
    def slots(self) -> dict[str, Any]:
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
    def voice_data(self) -> dict[str, Node]:
        """Read-only snapshot of all nodes as raw Node structs."""
        return dict(self._nodes)

    @property
    def nodes(self) -> dict[str, NodeHandle]:
        """All nodes as name → NodeHandle."""
        return {name: NodeHandle(self, name) for name in self._nodes}  # type: ignore[arg-type]

    @property
    def sources(self) -> dict[str, NodeHandle]:
        """Source nodes (num_inputs=0) as name → NodeHandle."""
        return {n: NodeHandle(self, n) for n, v in self._nodes.items() if v.num_inputs == 0}  # type: ignore[arg-type]

    @property
    def effects(self) -> dict[str, NodeHandle]:
        """Effect nodes (num_inputs>0) as name → NodeHandle."""
        return {n: NodeHandle(self, n) for n, v in self._nodes.items() if v.num_inputs > 0}  # type: ignore[arg-type]

    @property
    def node_controls(self) -> dict[str, tuple[str, ...]]:
        """Read-only snapshot of known node type controls."""
        return dict(self._node_controls)

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

    # ── Repr ──────────────────────────────────────────────────────

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
