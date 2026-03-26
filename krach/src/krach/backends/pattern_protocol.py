"""Pattern protocol — client messages and wire serialization.

This is the wire format spoken between krach (Python) and krach-engine (Rust).
ClientMessage wraps commands sent over the socket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from krach.ir.pattern import PatternNode

# ── Client messages ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SetPattern:
    slot: str
    pattern: PatternNode


@dataclass(frozen=True)
class SetPatternFromZero:
    slot: str
    pattern: PatternNode


@dataclass(frozen=True)
class Hush:
    slot: str


@dataclass(frozen=True)
class HushAll:
    pass


@dataclass(frozen=True)
class SetBpm:
    bpm: float


@dataclass(frozen=True)
class SetBeatsPerCycle:
    beats: float


@dataclass(frozen=True)
class SetClockSource:
    source: str  # "internal" or "midi"


@dataclass(frozen=True)
class Ping:
    pass


SimpleCommand = SetPattern | SetPatternFromZero | Hush | HushAll | SetBpm | SetBeatsPerCycle | SetClockSource | Ping


@dataclass(frozen=True)
class Batch:
    commands: tuple[SimpleCommand, ...]

    def __post_init__(self) -> None:
        if len(self.commands) == 0:
            raise ValueError("Batch requires at least one command")


ClientMessage = SimpleCommand | Batch

# ── Serialization ────────────────────────────────────────────────────────────


def _command_to_dict(msg: ClientMessage) -> dict[str, Any]:
    from krach.pattern.serialize import pattern_node_to_dict
    match msg:
        case SetPattern(slot, pattern):
            return {"cmd": "SetPattern", "slot": slot, "pattern": pattern_node_to_dict(pattern)}
        case SetPatternFromZero(slot, pattern):
            return {"cmd": "SetPatternFromZero", "slot": slot, "pattern": pattern_node_to_dict(pattern)}
        case Hush(slot):
            return {"cmd": "Hush", "slot": slot}
        case HushAll():
            return {"cmd": "HushAll"}
        case SetBpm(bpm):
            return {"cmd": "SetBpm", "bpm": bpm}
        case SetBeatsPerCycle(beats):
            return {"cmd": "SetBeatsPerCycle", "beats": beats}
        case SetClockSource(source):
            return {"cmd": "SetClockSource", "source": source}
        case Ping():
            return {"cmd": "Ping"}
        case Batch(commands):
            return {
                "cmd": "Batch",
                "commands": [_command_to_dict(c) for c in commands],
            }


def command_to_json(msg: ClientMessage) -> str:
    return json.dumps(_command_to_dict(msg), separators=(",", ":"))
