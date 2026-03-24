"""Value types — the leaf data carried by pattern atoms.

Note, Cc, Osc, Control are the four kinds of musical event a pattern can emit.
Value codec functions (to/from dict) live here so both IrNode and PatternNode
serializers can share them without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


@dataclass(frozen=True)
class Control:
    label: str
    value: float


Value = Note | Cc | Osc | Control


# ── Value codecs ────────────────────────────────────────────────────────


def osc_arg_to_dict(a: OscArg) -> dict[str, Any]:
    if isinstance(a, OscFloat):
        return {"Float": a.value}
    if isinstance(a, OscInt):
        return {"Int": a.value}
    return {"Str": a.value}


def value_to_dict(v: Value) -> dict[str, Any]:
    if isinstance(v, Note):
        return {"type": "Note", "channel": v.channel, "note": v.note,
                "velocity": v.velocity, "dur": v.dur}
    if isinstance(v, Cc):
        return {"type": "Cc", "channel": v.channel, "controller": v.controller,
                "value": v.value}
    if isinstance(v, Osc):
        return {"type": "Osc", "address": v.address,
                "args": [osc_arg_to_dict(a) for a in v.args]}
    return {"type": "Control", "label": v.label, "value": v.value}


def dict_to_osc_arg(d: dict[str, Any]) -> OscArg:
    if "Float" in d:
        return OscFloat(d["Float"])
    if "Int" in d:
        return OscInt(d["Int"])
    if "Str" in d:
        return OscStr(d["Str"])
    raise ValueError(f"unknown OscArg: {d}")


def dict_to_value(d: dict[str, Any]) -> Value:
    t = d["type"]
    if t == "Note":
        return Note(channel=d["channel"], note=d["note"],
                    velocity=d["velocity"], dur=d["dur"])
    if t == "Control":
        return Control(label=d["label"], value=d["value"])
    if t == "Cc":
        return Cc(channel=d["channel"], controller=d["controller"],
                  value=d["value"])
    if t == "Osc":
        return Osc(address=d["address"],
                   args=tuple(dict_to_osc_arg(a) for a in d["args"]))
    raise ValueError(f"unknown value type: {t}")
