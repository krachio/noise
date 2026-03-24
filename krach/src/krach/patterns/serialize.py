"""PatternNode serialization — dict round-trip for export/load."""

from __future__ import annotations

from typing import Any

from krach.ir.pattern import (
    AtomParams,
    CatParams,
    DegradeParams,
    EarlyParams,
    EuclidParams,
    EveryParams,
    FastParams,
    FreezeParams,
    LateParams,
    PatternNode,
    RevParams,
    SilenceParams,
    SlowParams,
    StackParams,
    WarpParams,
)
from krach.patterns.ir import (
    Cc,
    Control,
    Note,
    Osc,
    OscArg,
    OscFloat,
    OscInt,
    OscStr,
    Value,
)
from krach.patterns.primitives import (
    atom_p, cat_p, degrade_p, def_serialize, early_p, euclid_p, every_p,
    fast_p, fold, freeze_p, late_p, rev_p, silence_p, slow_p, stack_p, warp_p,
)


# ── Value serialization (shared with IrNode protocol) ────────────────────


def _osc_arg_to_dict(a: OscArg) -> dict[str, Any]:
    if isinstance(a, OscFloat):
        return {"Float": a.value}
    if isinstance(a, OscInt):
        return {"Int": a.value}
    return {"Str": a.value}


def _value_to_dict(v: Value) -> dict[str, Any]:
    if isinstance(v, Note):
        return {"type": "Note", "channel": v.channel, "note": v.note,
                "velocity": v.velocity, "dur": v.dur}
    if isinstance(v, Cc):
        return {"type": "Cc", "channel": v.channel, "controller": v.controller,
                "value": v.value}
    if isinstance(v, Osc):
        return {"type": "Osc", "address": v.address,
                "args": [_osc_arg_to_dict(a) for a in v.args]}
    return {"type": "Control", "label": v.label, "value": v.value}


def _dict_to_osc_arg(d: dict[str, Any]) -> OscArg:
    if "Float" in d:
        return OscFloat(d["Float"])
    if "Int" in d:
        return OscInt(d["Int"])
    if "Str" in d:
        return OscStr(d["Str"])
    raise ValueError(f"unknown OscArg: {d}")


def _dict_to_value(d: dict[str, Any]) -> Value:
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
                   args=tuple(_dict_to_osc_arg(a) for a in d["args"]))
    raise ValueError(f"unknown value type: {t}")


# ── Per-primitive serialize rules ────────────────────────────────────────


def _atom_ser(node: PatternNode, _children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, AtomParams)
    return {"op": "Atom", "value": _value_to_dict(node.params.value)}


def _silence_ser(_node: PatternNode, _children: tuple[Any, ...]) -> dict[str, Any]:
    return {"op": "Silence"}


def _cat_ser(_node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    return {"op": "Cat", "children": list(children)}


def _stack_ser(_node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    return {"op": "Stack", "children": list(children)}


def _freeze_ser(_node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    return {"op": "Freeze", "child": children[0]}


def _fast_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, FastParams)
    return {"op": "Fast", "factor": list(node.params.factor), "child": children[0]}


def _slow_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, SlowParams)
    return {"op": "Slow", "factor": list(node.params.factor), "child": children[0]}


def _early_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, EarlyParams)
    return {"op": "Early", "offset": list(node.params.offset), "child": children[0]}


def _late_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, LateParams)
    return {"op": "Late", "offset": list(node.params.offset), "child": children[0]}


def _rev_ser(_node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    return {"op": "Rev", "child": children[0]}


def _every_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, EveryParams)
    return {"op": "Every", "n": node.params.n,
            "transform": children[0], "child": children[1]}


def _euclid_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, EuclidParams)
    p = node.params
    return {"op": "Euclid", "pulses": p.pulses, "steps": p.steps,
            "rotation": p.rotation, "child": children[0]}


def _degrade_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, DegradeParams)
    return {"op": "Degrade", "prob": node.params.prob,
            "seed": node.params.seed, "child": children[0]}


def _warp_ser(node: PatternNode, children: tuple[Any, ...]) -> dict[str, Any]:
    assert isinstance(node.params, WarpParams)
    p = node.params
    return {"op": "Warp", "kind": p.kind, "amount": p.amount,
            "grid": p.grid, "child": children[0]}


# ── Registration ─────────────────────────────────────────────────────────

def_serialize(atom_p, _atom_ser)
def_serialize(silence_p, _silence_ser)
def_serialize(cat_p, _cat_ser)
def_serialize(stack_p, _stack_ser)
def_serialize(freeze_p, _freeze_ser)
def_serialize(fast_p, _fast_ser)
def_serialize(slow_p, _slow_ser)
def_serialize(early_p, _early_ser)
def_serialize(late_p, _late_ser)
def_serialize(rev_p, _rev_ser)
def_serialize(every_p, _every_ser)
def_serialize(euclid_p, _euclid_ser)
def_serialize(degrade_p, _degrade_ser)
def_serialize(warp_p, _warp_ser)


# ── Public API ───────────────────────────────────────────────────────────


def pattern_node_to_dict(node: PatternNode) -> dict[str, Any]:
    """Serialize a PatternNode tree to a JSON-friendly dict."""
    from krach.patterns.primitives import get_serialize_rule
    return fold(node, lambda nd, children: get_serialize_rule(nd.primitive)(nd, children))


def dict_to_pattern_node(d: dict[str, Any]) -> PatternNode:
    """Deserialize a dict back to a PatternNode tree."""
    op = d["op"]
    if op == "Atom":
        return PatternNode(atom_p, (), AtomParams(_dict_to_value(d["value"])))
    if op == "Silence":
        return PatternNode(silence_p, (), SilenceParams())

    # Multi-child ops
    if op == "Cat":
        children = tuple(dict_to_pattern_node(c) for c in d["children"])
        return PatternNode(cat_p, children, CatParams())
    if op == "Stack":
        children = tuple(dict_to_pattern_node(c) for c in d["children"])
        return PatternNode(stack_p, children, StackParams())

    # Single-child ops
    child = dict_to_pattern_node(d["child"])
    if op == "Freeze":
        return PatternNode(freeze_p, (child,), FreezeParams())
    if op == "Fast":
        return PatternNode(fast_p, (child,), FastParams(tuple(d["factor"])))  # type: ignore[arg-type]
    if op == "Slow":
        return PatternNode(slow_p, (child,), SlowParams(tuple(d["factor"])))  # type: ignore[arg-type]
    if op == "Early":
        return PatternNode(early_p, (child,), EarlyParams(tuple(d["offset"])))  # type: ignore[arg-type]
    if op == "Late":
        return PatternNode(late_p, (child,), LateParams(tuple(d["offset"])))  # type: ignore[arg-type]
    if op == "Rev":
        return PatternNode(rev_p, (child,), RevParams())
    if op == "Every":
        transform = dict_to_pattern_node(d["transform"])
        return PatternNode(every_p, (transform, child), EveryParams(n=d["n"]))
    if op == "Euclid":
        return PatternNode(euclid_p, (child,), EuclidParams(
            pulses=d["pulses"], steps=d["steps"], rotation=d["rotation"]))
    if op == "Degrade":
        return PatternNode(degrade_p, (child,), DegradeParams(
            prob=d["prob"], seed=d["seed"]))
    if op == "Warp":
        return PatternNode(warp_p, (child,), WarpParams(
            kind=d["kind"], amount=d["amount"], grid=d["grid"]))
    raise ValueError(f"unknown PatternNode op: {op}")
