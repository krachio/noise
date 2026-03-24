"""Pattern backend — lower PatternNode tree to old IrNode tree for the Rust engine.

This is a temporary bridge during migration. Once the Rust engine accepts
PatternNode directly (or a new wire format), this module goes away.
"""

from __future__ import annotations

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
    Atom,
    Cat,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Freeze,
    IrNode,
    Late,
    Rev,
    Silence,
    Slow,
    Stack,
    Warp,
)


def to_ir_node(node: PatternNode) -> IrNode:
    """Convert a PatternNode tree to the old IrNode tree for the Rust engine."""
    children = tuple(to_ir_node(c) for c in node.children)

    match node.params:
        case AtomParams(value=value):
            return Atom(value)
        case SilenceParams():
            return Silence()
        case CatParams():
            return Cat(children)
        case StackParams():
            return Stack(children)
        case FreezeParams():
            assert len(children) == 1
            return Freeze(children[0])
        case FastParams(factor=factor):
            assert len(children) == 1
            return Fast(factor, children[0])
        case SlowParams(factor=factor):
            assert len(children) == 1
            return Slow(factor, children[0])
        case EarlyParams(offset=offset):
            assert len(children) == 1
            return Early(offset, children[0])
        case LateParams(offset=offset):
            assert len(children) == 1
            return Late(offset, children[0])
        case RevParams():
            assert len(children) == 1
            return Rev(children[0])
        case EveryParams(n=n):
            assert len(children) == 2
            return Every(n, children[0], children[1])
        case EuclidParams(pulses=pulses, steps=steps, rotation=rotation):
            assert len(children) == 1
            return Euclid(pulses, steps, rotation, children[0])
        case DegradeParams(prob=prob, seed=seed):
            assert len(children) == 1
            return Degrade(prob, seed, children[0])
        case WarpParams(kind=kind, amount=amount, grid=grid):
            assert len(children) == 1
            return Warp(kind, amount, grid, children[0])
        case _:
            raise ValueError(f"Unknown pattern params type: {type(node.params).__name__}")


