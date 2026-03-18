from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from typing import IO, Any

from midiman_frontend.ir import (
    ClientMessage,
    Hush,
    HushAll,
    Ping,
    SetBpm,
    SetPattern,
    Stack,
    command_to_json,
)
from midiman_frontend.pattern import Pattern


class KernelError(Exception):
    """Raised when the midiman kernel returns an error response."""


def _default_socket_path() -> str:
    return os.environ.get("MIDIMAN_SOCKET", "/tmp/midiman.sock")


def _parse_response(line: bytes) -> None:
    if not line:
        raise ConnectionError("kernel closed connection")
    data: dict[str, Any] = json.loads(line)
    status = data.get("status")
    if status == "Error":
        raise KernelError(data.get("msg", "unknown error"))


class Track:
    def __init__(self, name: str, session: Session) -> None:
        self._name = name
        self._session = session
        self._clips: dict[str, Pattern] = {}

    @property
    def name(self) -> str:
        return self._name

    def __setitem__(self, clip_name: str, pattern: Pattern) -> None:
        self._clips[clip_name] = pattern
        self._sync()

    def __delitem__(self, clip_name: str) -> None:
        del self._clips[clip_name]
        self._sync()

    def stop(self) -> None:
        self._clips.clear()
        self._session.send(Hush(slot=self._name))

    def _sync(self) -> None:
        if not self._clips:
            self._session.send(Hush(slot=self._name))
            return
        clips = tuple(self._clips.values())
        if len(clips) == 1:
            node = clips[0].node
        else:
            node = Stack(children=tuple(c.node for c in clips))
        self._session.send(SetPattern(slot=self._name, pattern=node))


@dataclass
class Session:
    socket_path: str = field(default_factory=_default_socket_path)
    _sock: socket.socket | None = field(default=None, init=False, repr=False)
    _reader: IO[bytes] | None = field(default=None, init=False, repr=False)
    _tracks: dict[str, Track] = field(
        default_factory=lambda: dict[str, Track](), init=False, repr=False
    )

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

    @property
    def tempo(self) -> float:
        return 0.0  # write-only in practice; kernel doesn't send back

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self.send(SetBpm(bpm=bpm))

    def track(self, name: str) -> Track:
        if name not in self._tracks:
            self._tracks[name] = Track(name, self)
        return self._tracks[name]

    def stop(self) -> None:
        self.send(HushAll())

    def ping(self) -> None:
        self.send(Ping())

    def send(self, msg: ClientMessage) -> None:
        if self._sock is None or self._reader is None:
            raise RuntimeError("not connected — call connect() or use context manager")
        data = command_to_json(msg) + "\n"
        self._sock.sendall(data.encode())
        _parse_response(self._reader.readline())
