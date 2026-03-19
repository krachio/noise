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
    SetBpm,
    SetPattern,
    command_to_json,
)
from midiman_frontend.pattern import Pattern


class KernelError(Exception):
    """Raised when the midiman kernel returns an error response."""


@dataclass(frozen=True)
class SlotState:
    pattern: Pattern
    playing: bool


def _default_socket_path() -> str:
    return os.environ.get("MIDIMAN_SOCKET", "/tmp/midiman.sock")


def _parse_response(line: bytes) -> None:
    if not line:
        raise ConnectionError("kernel closed connection")
    data: dict[str, Any] = json.loads(line)
    if data.get("status") == "Error":
        raise KernelError(data.get("msg", "unknown error"))


@dataclass
class Session:
    socket_path: str = field(default_factory=_default_socket_path)
    _sock: socket.socket | None = field(default=None, init=False, repr=False)
    _reader: IO[bytes] | None = field(default=None, init=False, repr=False)
    _slots: dict[str, SlotState] = field(
        default_factory=lambda: dict[str, SlotState](), init=False, repr=False
    )
    _tempo: float = field(default=120.0, init=False, repr=False)

    # ── Connection ──────────────────────────────────────────────────────

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)
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
        self._tempo = bpm
        self.send(SetBpm(bpm=bpm))

    # ── IPC ──────────────────────────────────────────────────────────────

    def ping(self) -> None:
        self.send(Ping())

    def send(self, msg: ClientMessage) -> None:
        if self._sock is None or self._reader is None:
            raise RuntimeError("not connected — call connect() or use context manager")
        data = command_to_json(msg) + "\n"
        self._sock.sendall(data.encode())
        _parse_response(self._reader.readline())

    # ── Repr ─────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "connected" if self._sock else "disconnected"
        lines = [f"Session({status}, tempo={self._tempo})"]
        for name, state in self._slots.items():
            label = "playing" if state.playing else "stopped"
            lines.append(f"  {name}: {label}")
        return "\n".join(lines)
