"""Pattern protocol — IrNode types, client messages, and wire serialization.

This is the wire format spoken between krach (Python) and krach-engine (Rust).
IrNode is the old tree IR consumed by the Rust pattern engine.
ClientMessage wraps commands sent over the socket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from krach.patterns.values import (
    Value,
    value_to_dict,
    dict_to_value,
)

# ── IR node types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Atom:
    value: Value


@dataclass(frozen=True)
class Silence:
    pass


@dataclass(frozen=True)
class Freeze:
    """Marks a sub-pattern as an indivisible unit. Transparent in evaluation."""
    child: IrNode


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


@dataclass(frozen=True)
class Warp:
    kind: str
    amount: float
    grid: int
    child: IrNode

    def __post_init__(self) -> None:
        if self.kind != "swing":
            raise ValueError(f"unknown warp kind: {self.kind}")
        if self.grid <= 0 or self.grid % 2 != 0:
            raise ValueError("grid must be even and > 0")
        if not (0.0 < self.amount < 1.0):
            raise ValueError("amount must be in (0, 1)")


IrNode = (
    Atom
    | Silence
    | Freeze
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
    | Warp
)

# ── Client messages ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SetPattern:
    slot: str
    pattern: IrNode


@dataclass(frozen=True)
class SetPatternFromZero:
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
class SetBeatsPerCycle:
    beats: float


@dataclass(frozen=True)
class Ping:
    pass


SimpleCommand = SetPattern | SetPatternFromZero | Hush | HushAll | SetBpm | SetBeatsPerCycle | Ping


@dataclass(frozen=True)
class Batch:
    commands: tuple[SimpleCommand, ...]

    def __post_init__(self) -> None:
        if len(self.commands) == 0:
            raise ValueError("Batch requires at least one command")


ClientMessage = SimpleCommand | Batch

# ── Serialization ────────────────────────────────────────────────────────────


def ir_to_dict(node: IrNode) -> dict[str, Any]:
    match node:
        case Atom(value):
            return {"op": "Atom", "value": value_to_dict(value)}
        case Silence():
            return {"op": "Silence"}
        case Freeze(child):
            return {"op": "Freeze", "child": ir_to_dict(child)}
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
        case Warp(kind, amount, grid, child):
            return {
                "op": "Warp",
                "kind": kind,
                "amount": amount,
                "grid": grid,
                "child": ir_to_dict(child),
            }


def _command_to_dict(msg: ClientMessage) -> dict[str, Any]:
    match msg:
        case SetPattern(slot, pattern):
            return {"cmd": "SetPattern", "slot": slot, "pattern": ir_to_dict(pattern)}
        case SetPatternFromZero(slot, pattern):
            return {"cmd": "SetPatternFromZero", "slot": slot, "pattern": ir_to_dict(pattern)}
        case Hush(slot):
            return {"cmd": "Hush", "slot": slot}
        case HushAll():
            return {"cmd": "HushAll"}
        case SetBpm(bpm):
            return {"cmd": "SetBpm", "bpm": bpm}
        case SetBeatsPerCycle(beats):
            return {"cmd": "SetBeatsPerCycle", "beats": beats}
        case Ping():
            return {"cmd": "Ping"}
        case Batch(commands):
            return {
                "cmd": "Batch",
                "commands": [_command_to_dict(c) for c in commands],
            }


def command_to_json(msg: ClientMessage) -> str:
    return json.dumps(_command_to_dict(msg), separators=(",", ":"))


# ── Deserialization ─────────────────────────────────────────────────────────


def dict_to_ir(d: dict[str, Any]) -> IrNode:
    """Reconstruct an IR node from a dict (inverse of ``ir_to_dict``)."""
    op = d["op"]
    match op:
        case "Atom":
            return Atom(dict_to_value(d["value"]))
        case "Silence":
            return Silence()
        case "Freeze":
            return Freeze(child=dict_to_ir(d["child"]))
        case "Cat":
            return Cat(tuple(dict_to_ir(c) for c in d["children"]))
        case "Stack":
            return Stack(tuple(dict_to_ir(c) for c in d["children"]))
        case "Fast":
            return Fast(factor=tuple(d["factor"]), child=dict_to_ir(d["child"]))  # type: ignore[arg-type]
        case "Slow":
            return Slow(factor=tuple(d["factor"]), child=dict_to_ir(d["child"]))  # type: ignore[arg-type]
        case "Early":
            return Early(offset=tuple(d["offset"]), child=dict_to_ir(d["child"]))  # type: ignore[arg-type]
        case "Late":
            return Late(offset=tuple(d["offset"]), child=dict_to_ir(d["child"]))  # type: ignore[arg-type]
        case "Rev":
            return Rev(child=dict_to_ir(d["child"]))
        case "Every":
            return Every(n=d["n"], transform=dict_to_ir(d["transform"]),
                         child=dict_to_ir(d["child"]))
        case "Euclid":
            return Euclid(pulses=d["pulses"], steps=d["steps"],
                          rotation=d["rotation"], child=dict_to_ir(d["child"]))
        case "Degrade":
            return Degrade(prob=d["prob"], seed=d["seed"],
                           child=dict_to_ir(d["child"]))
        case "Warp":
            return Warp(kind=d["kind"], amount=d["amount"],
                        grid=d["grid"], child=dict_to_ir(d["child"]))
        case _:
            raise ValueError(f"unknown IR op: {op}")
