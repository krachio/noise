from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ── Value types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Note:
    channel: int
    note: int
    velocity: int
    dur: float


@dataclass(frozen=True)
class Cc:
    channel: int
    controller: int
    value: int


@dataclass(frozen=True)
class OscFloat:
    value: float


@dataclass(frozen=True)
class OscInt:
    value: int


@dataclass(frozen=True)
class OscStr:
    value: str


OscArg = OscFloat | OscInt | OscStr


@dataclass(frozen=True)
class Osc:
    address: str
    args: tuple[OscArg, ...]


Value = Note | Cc | Osc

# ── IR node types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Atom:
    value: Value


@dataclass(frozen=True)
class AtomGroup:
    """Multiple values fired at onset + optional reset at end. Counts as ONE atom."""
    values: tuple[Value, ...]
    reset: Value | None = None


@dataclass(frozen=True)
class Silence:
    pass


@dataclass(frozen=True)
class Cat:
    children: tuple[IrNode, ...]

    def __post_init__(self) -> None:
        if len(self.children) == 0:
            raise ValueError("Cat requires at least one child")


@dataclass(frozen=True)
class Stack:
    children: tuple[IrNode, ...]

    def __post_init__(self) -> None:
        if len(self.children) == 0:
            raise ValueError("Stack requires at least one child")


@dataclass(frozen=True)
class Fast:
    factor: tuple[int, int]
    child: IrNode

    def __post_init__(self) -> None:
        if self.factor[0] <= 0 or self.factor[1] <= 0:
            raise ValueError("factor numerator and denominator must be positive")


@dataclass(frozen=True)
class Slow:
    factor: tuple[int, int]
    child: IrNode

    def __post_init__(self) -> None:
        if self.factor[0] <= 0 or self.factor[1] <= 0:
            raise ValueError("factor numerator and denominator must be positive")


@dataclass(frozen=True)
class Early:
    offset: tuple[int, int]
    child: IrNode

    def __post_init__(self) -> None:
        if self.offset[1] == 0:
            raise ValueError("offset denominator must not be zero")


@dataclass(frozen=True)
class Late:
    offset: tuple[int, int]
    child: IrNode

    def __post_init__(self) -> None:
        if self.offset[1] == 0:
            raise ValueError("offset denominator must not be zero")


@dataclass(frozen=True)
class Rev:
    child: IrNode


@dataclass(frozen=True)
class Every:
    n: int
    transform: IrNode
    child: IrNode

    def __post_init__(self) -> None:
        if self.n <= 0:
            raise ValueError("n must be > 0")


@dataclass(frozen=True)
class Euclid:
    pulses: int
    steps: int
    rotation: int
    child: IrNode

    def __post_init__(self) -> None:
        if self.steps <= 0:
            raise ValueError("steps must be > 0")
        if self.pulses > self.steps:
            raise ValueError("pulses must be <= steps")


@dataclass(frozen=True)
class Degrade:
    prob: float
    seed: int
    child: IrNode

    def __post_init__(self) -> None:
        if self.prob < 0.0 or self.prob > 1.0:
            raise ValueError("prob must be in [0.0, 1.0]")


IrNode = (
    Atom
    | AtomGroup
    | Silence
    | Cat
    | Stack
    | Fast
    | Slow
    | Early
    | Late
    | Rev
    | Every
    | Euclid
    | Degrade
)

# ── Client messages ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SetPattern:
    slot: str
    pattern: IrNode


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
class Ping:
    pass


SimpleCommand = SetPattern | Hush | HushAll | SetBpm | Ping


@dataclass(frozen=True)
class Batch:
    commands: tuple[SimpleCommand, ...]

    def __post_init__(self) -> None:
        if len(self.commands) == 0:
            raise ValueError("Batch requires at least one command")


ClientMessage = SimpleCommand | Batch

# ── Serialization ────────────────────────────────────────────────────────────


def _osc_arg_to_dict(arg: OscArg) -> dict[str, Any]:
    match arg:
        case OscFloat(v):
            return {"Float": v}
        case OscInt(v):
            return {"Int": v}
        case OscStr(v):
            return {"Str": v}


def _value_to_dict(v: Value) -> dict[str, Any]:
    match v:
        case Note(channel, note, velocity, dur):
            return {
                "type": "Note",
                "channel": channel,
                "note": note,
                "velocity": velocity,
                "dur": dur,
            }
        case Cc(channel, controller, value):
            return {
                "type": "Cc",
                "channel": channel,
                "controller": controller,
                "value": value,
            }
        case Osc(address, args):
            return {
                "type": "Osc",
                "address": address,
                "args": [_osc_arg_to_dict(a) for a in args],
            }


def ir_to_dict(node: IrNode) -> dict[str, Any]:
    match node:
        case Atom(value):
            return {"op": "Atom", "value": _value_to_dict(value)}
        case AtomGroup(values, reset):
            d: dict[str, Any] = {
                "op": "AtomGroup",
                "values": [_value_to_dict(v) for v in values],
            }
            if reset is not None:
                d["reset"] = _value_to_dict(reset)
            return d
        case Silence():
            return {"op": "Silence"}
        case Cat(children):
            return {"op": "Cat", "children": [ir_to_dict(c) for c in children]}
        case Stack(children):
            return {"op": "Stack", "children": [ir_to_dict(c) for c in children]}
        case Fast(factor, child):
            return {"op": "Fast", "factor": list(factor), "child": ir_to_dict(child)}
        case Slow(factor, child):
            return {"op": "Slow", "factor": list(factor), "child": ir_to_dict(child)}
        case Early(offset, child):
            return {
                "op": "Early",
                "offset": list(offset),
                "child": ir_to_dict(child),
            }
        case Late(offset, child):
            return {
                "op": "Late",
                "offset": list(offset),
                "child": ir_to_dict(child),
            }
        case Rev(child):
            return {"op": "Rev", "child": ir_to_dict(child)}
        case Every(n, transform, child):
            return {
                "op": "Every",
                "n": n,
                "transform": ir_to_dict(transform),
                "child": ir_to_dict(child),
            }
        case Euclid(pulses, steps, rotation, child):
            return {
                "op": "Euclid",
                "pulses": pulses,
                "steps": steps,
                "rotation": rotation,
                "child": ir_to_dict(child),
            }
        case Degrade(prob, seed, child):
            return {
                "op": "Degrade",
                "prob": prob,
                "seed": seed,
                "child": ir_to_dict(child),
            }


def _command_to_dict(msg: ClientMessage) -> dict[str, Any]:
    match msg:
        case SetPattern(slot, pattern):
            return {"cmd": "SetPattern", "slot": slot, "pattern": ir_to_dict(pattern)}
        case Hush(slot):
            return {"cmd": "Hush", "slot": slot}
        case HushAll():
            return {"cmd": "HushAll"}
        case SetBpm(bpm):
            return {"cmd": "SetBpm", "bpm": bpm}
        case Ping():
            return {"cmd": "Ping"}
        case Batch(commands):
            return {
                "cmd": "Batch",
                "commands": [_command_to_dict(c) for c in commands],
            }



def command_to_json(msg: ClientMessage) -> str:
    return json.dumps(_command_to_dict(msg), separators=(",", ":"))
