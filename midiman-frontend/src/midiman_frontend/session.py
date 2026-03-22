from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from typing import IO, Any

from midiman_frontend.ir import (
    Batch,
    ClientMessage,
    Hush,
    HushAll,
    Ping,
    SetBeatsPerCycle,
    SetBpm,
    SetPattern,
    SetPatternFromZero,
    command_to_json,
)
from midiman_frontend.graph import GraphIr
from midiman_frontend.pattern import Pattern


class KernelError(Exception):
    """Raised when the midiman kernel returns an error response."""


@dataclass(frozen=True)
class SlotState:
    pattern: Pattern
    playing: bool


def _default_socket_path() -> str:
    return os.environ.get("NOISE_SOCKET", "/tmp/noise-engine.sock")


def _parse_response(line: bytes) -> dict[str, Any]:
    if not line:
        raise ConnectionError("kernel closed connection")
    data: dict[str, Any] = json.loads(line)
    if data.get("status") == "Error":
        raise KernelError(data.get("msg", "unknown error"))
    return data


@dataclass
class Session:
    socket_path: str = field(default_factory=_default_socket_path)
    _sock: socket.socket | None = field(default=None, init=False, repr=False)
    _reader: IO[bytes] | None = field(default=None, init=False, repr=False)
    _slots: dict[str, SlotState] = field(
        default_factory=lambda: dict[str, SlotState](), init=False, repr=False
    )
    _tempo: float = field(default=120.0, init=False, repr=False)
    _meter: float = field(default=4.0, init=False, repr=False)

    # ── Connection ──────────────────────────────────────────────────────

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)
        self._sock.settimeout(5.0)
        self._reader = self._sock.makefile("rb")

    def disconnect(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> Session:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    # ── Slot management ─────────────────────────────────────────────────

    def play(self, slot: str, pattern: Pattern) -> None:
        self._slots[slot] = SlotState(pattern=pattern, playing=True)
        self.send(SetPattern(slot=slot, pattern=pattern.node))

    def play_from_zero(self, slot: str, pattern: Pattern) -> None:
        """Like play(), but resets phase so the pattern starts from cycle 0."""
        self._slots[slot] = SlotState(pattern=pattern, playing=True)
        self.send(SetPatternFromZero(slot=slot, pattern=pattern.node))

    def hush(self, slot: str) -> None:
        if slot in self._slots:
            state = self._slots[slot]
            self._slots[slot] = SlotState(pattern=state.pattern, playing=False)
        self.send(Hush(slot=slot))

    def resume(self, slot: str) -> None:
        state = self._slots[slot]  # raises KeyError if unknown
        if not state.playing:
            self._slots[slot] = SlotState(pattern=state.pattern, playing=True)
            self.send(SetPattern(slot=slot, pattern=state.pattern.node))

    def remove(self, slot: str) -> None:
        self._slots.pop(slot, None)
        self.send(Hush(slot=slot))

    def stop(self) -> None:
        self._slots = {
            name: SlotState(pattern=state.pattern, playing=False)
            for name, state in self._slots.items()
        }
        self.send(HushAll())

    def launch(self, patterns: dict[str, Pattern]) -> None:
        commands: list[SetPattern] = []
        for slot, pattern in patterns.items():
            self._slots[slot] = SlotState(pattern=pattern, playing=True)
            commands.append(SetPattern(slot=slot, pattern=pattern.node))
        self.send(Batch(commands=tuple(commands)))

    # ── State visibility ────────────────────────────────────────────────

    @property
    def slots(self) -> dict[str, SlotState]:
        return dict(self._slots)

    @property
    def tempo(self) -> float:
        return self._tempo

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        if bpm == self._tempo:
            return
        self._tempo = bpm
        self.send(SetBpm(bpm=bpm))

    @property
    def meter(self) -> float:
        """Current beats per cycle."""
        return self._meter

    @meter.setter
    def meter(self, beats: float) -> None:
        if beats == self._meter:
            return
        self._meter = beats
        self.send(SetBeatsPerCycle(beats=beats))

    # ── IPC ──────────────────────────────────────────────────────────────

    def ping(self) -> None:
        self.send(Ping())

    def send(self, msg: ClientMessage) -> None:
        if self._sock is None or self._reader is None:
            raise RuntimeError("not connected — call connect() or use context manager")
        data = command_to_json(msg) + "\n"
        try:
            self._sock.sendall(data.encode())
            _parse_response(self._reader.readline())
        except socket.timeout:
            raise ConnectionError("engine not responding (socket timeout)")

    # ── Graph commands (soundman-style, via unified binary) ──────────────

    def _send_json(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Send raw JSON to the unified binary and return the parsed response."""
        if self._sock is None or self._reader is None:
            raise RuntimeError("not connected — call connect() or use context manager")
        data = json.dumps(obj, separators=(",", ":")) + "\n"
        try:
            self._sock.sendall(data.encode())
            return _parse_response(self._reader.readline())
        except socket.timeout:
            raise ConnectionError("engine not responding (socket timeout)")

    def load_graph(self, graph: GraphIr) -> None:
        """Load an audio graph via the unified binary."""
        if self._sock is None or self._reader is None:
            raise RuntimeError("not connected — call connect() or use context manager")
        # GraphIr.to_json() already produces the inner JSON; wrap with type tag
        # in a single pass (avoids serialize → parse → re-serialize).
        inner = graph.to_json()
        msg = f'{{"type":"load_graph",{inner[1:]}'  # replace leading '{' with '{"type":"load_graph",'
        try:
            self._sock.sendall((msg + "\n").encode())
            _parse_response(self._reader.readline())
        except socket.timeout:
            raise ConnectionError("engine not responding (socket timeout)")

    def add_voice(
        self,
        name: str,
        type_id: str,
        controls: tuple[str, ...],
        gain: float,
    ) -> None:
        """Add a voice to the existing graph without full rebuild.

        Sends a GraphBatch of AddNode + Connect + ExposeControl — one
        recompile, one SwapGraph, existing nodes reused.
        """
        commands: list[dict[str, Any]] = [
            {"type": "add_node", "id": name, "type_id": type_id, "controls": {}},
            {"type": "add_node", "id": f"{name}_g", "type_id": "gain", "controls": {"gain": gain}},
            {"type": "connect", "from_node": name, "from_port": "out", "to_node": f"{name}_g", "to_port": "in"},
            {"type": "connect", "from_node": f"{name}_g", "from_port": "out", "to_node": "out", "to_port": "in"},
        ]
        for param in controls:
            commands.append({"type": "expose_control", "label": f"{name}/{param}", "node_id": name, "control_name": param})
        commands.append({"type": "expose_control", "label": f"{name}/gain", "node_id": f"{name}_g", "control_name": "gain"})
        self._send_json({"type": "graph_batch", "commands": commands})

    def set_ctrl(self, label: str, value: float) -> None:
        """Set an exposed control parameter on the audio engine."""
        self._send_json({"type": "set_control", "label": label, "value": value})

    def master_gain(self, value: float) -> None:
        """Set the master output gain (0.0–1.0)."""
        self._send_json({"type": "set_master_gain", "gain": value})

    def list_nodes(self) -> list[str]:
        """Query registered node type IDs from the audio engine."""
        resp = self._send_json({"type": "list_nodes", "reply_port": 0})
        return list(resp.get("types", []))

    def shutdown(self) -> None:
        """Shut down the unified binary."""
        self._send_json({"type": "shutdown"})

    # ── Repr ─────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "connected" if self._sock else "disconnected"
        lines = [f"Session({status}, tempo={self._tempo})"]
        for name, state in self._slots.items():
            label = "playing" if state.playing else "stopped"
            lines.append(f"  {name}: {label}")
        return "\n".join(lines)
