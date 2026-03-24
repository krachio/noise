"""Pattern — composable temporal structures built from PatternNode.

Pattern wraps a PatternNode tree. Operators (+, |, *, .over(), etc.)
produce new PatternNode trees. `.ir_node` lowers to old IrNode at the
engine boundary via backends/pattern_backend.to_ir_node().
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

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
from krach.patterns.ir import Cc, Control, IrNode, Note, Osc, OscArg
from krach.patterns.primitives import (
    atom_p, cat_p, degrade_p, early_p, euclid_p, every_p,
    fast_p, freeze_p, late_p, rev_p, silence_p, slow_p, stack_p, warp_p,
)


def _to_rational(value: int | float) -> tuple[int, int]:
    if isinstance(value, int):
        return (value, 1)
    f = Fraction(value).limit_denominator(256)
    return (f.numerator, f.denominator)


def _invert_rational(r: tuple[int, int]) -> tuple[int, int]:
    return (r[1], r[0])


def _flatten_cat(left: PatternNode, right: PatternNode) -> tuple[PatternNode, ...]:
    left_c = left.children if left.primitive == cat_p else (left,)
    right_c = right.children if right.primitive == cat_p else (right,)
    return (*left_c, *right_c)


def _flatten_stack(left: PatternNode, right: PatternNode) -> tuple[PatternNode, ...]:
    left_c = left.children if left.primitive == stack_p else (left,)
    right_c = right.children if right.primitive == stack_p else (right,)
    return (*left_c, *right_c)


@dataclass(frozen=True)
class Pattern:
    node: PatternNode

    @functools.cached_property
    def ir_node(self) -> IrNode:
        """Lower to IrNode for the Rust engine. Cached on first access."""
        from krach.backends.pattern_backend import to_ir_node
        return to_ir_node(self.node)

    def __repr__(self) -> str:
        from krach._ir_summary import summarize
        return f"Pattern({summarize(self.node)})"

    # ── Operators ────────────────────────────────────────────────────────

    def __add__(self, other: Pattern) -> Pattern:
        return Pattern(PatternNode(cat_p, _flatten_cat(self.node, other.node), CatParams()))

    def __or__(self, other: Pattern) -> Pattern:
        return Pattern(PatternNode(stack_p, _flatten_stack(self.node, other.node), StackParams()))

    def __mul__(self, n: int) -> Pattern:
        return Pattern(PatternNode(cat_p, tuple(self.node for _ in range(n)), CatParams()))

    # ── Time transforms ──────────────────────────────────────────────────

    def over(self, cycles: int | float) -> Pattern:
        if not isinstance(cycles, int) and not math.isfinite(cycles):
            raise ValueError(f"over() requires positive cycles, got {cycles}")
        if cycles <= 0:
            raise ValueError(f"over() requires positive cycles, got {cycles}")
        r = _to_rational(cycles)
        if r[0] * r[1] > 0 and r[0] >= r[1]:
            return Pattern(PatternNode(slow_p, (self.node,), SlowParams(factor=r)))
        return Pattern(PatternNode(fast_p, (self.node,), FastParams(factor=_invert_rational(r))))

    def fast(self, factor: int | float) -> Pattern:
        if not isinstance(factor, int) and not math.isfinite(factor):
            raise ValueError(f"fast() requires a positive factor, got {factor}")
        if factor <= 0:
            raise ValueError(f"fast() requires a positive factor, got {factor}")
        r = _to_rational(factor)
        if r[0] * r[1] > 0 and r[0] >= r[1]:
            return Pattern(PatternNode(fast_p, (self.node,), FastParams(factor=r)))
        return Pattern(PatternNode(slow_p, (self.node,), SlowParams(factor=_invert_rational(r))))

    def shift(self, offset: int | float) -> Pattern:
        r = _to_rational(offset)
        if r[0] >= 0:
            return Pattern(PatternNode(late_p, (self.node,), LateParams(offset=r)))
        return Pattern(PatternNode(early_p, (self.node,), EarlyParams(offset=(abs(r[0]), r[1]))))

    # ── Structural transforms ────────────────────────────────────────────

    def reverse(self) -> Pattern:
        return Pattern(PatternNode(rev_p, (self.node,), RevParams()))

    def every(self, n: int, fn: Callable[[Pattern], Pattern]) -> Pattern:
        transformed = fn(self)
        return Pattern(PatternNode(every_p, (transformed.node, self.node), EveryParams(n=n)))

    def spread(self, pulses: int, steps: int, rotation: int = 0) -> Pattern:
        return Pattern(PatternNode(euclid_p, (self.node,), EuclidParams(pulses, steps, rotation)))

    def thin(self, prob: float, seed: int = 0) -> Pattern:
        return Pattern(PatternNode(degrade_p, (self.node,), DegradeParams(prob, seed)))

    def swing(self, amount: float = 0.67, grid: int = 8) -> Pattern:
        return Pattern(PatternNode(warp_p, (self.node,), WarpParams("swing", amount, grid)))

    def mask(self, mask_str: str) -> Pattern:
        tokens = mask_str.split()
        keep = [t in ("1", "x", "X") for t in tokens]
        node = self.node
        if node.primitive == cat_p:
            new_children: list[PatternNode] = []
            for i, child in enumerate(node.children):
                if i < len(keep) and not keep[i]:
                    new_children.append(PatternNode(silence_p, (), SilenceParams()))
                else:
                    new_children.append(child)
            return Pattern(PatternNode(cat_p, tuple(new_children), CatParams()))
        return self

    def sometimes(self, prob: float, fn: Callable[[Pattern], Pattern], seed: int = 0) -> Pattern:
        transformed = fn(self)
        return Pattern(PatternNode(stack_p, (
            PatternNode(degrade_p, (transformed.node,), DegradeParams(1.0 - prob, seed)),
            PatternNode(degrade_p, (self.node,), DegradeParams(prob, seed + 1)),
        ), StackParams()))


# ── Atom constructors ────────────────────────────────────────────────────


def note(
    pitch: int, velocity: int = 100, channel: int = 0, duration: float = 1.0
) -> Pattern:
    return Pattern(PatternNode(atom_p, (), AtomParams(Note(channel, pitch, velocity, duration))))


def rest() -> Pattern:
    return Pattern(PatternNode(silence_p, (), SilenceParams()))


def cc(controller: int, value: int, channel: int = 0) -> Pattern:
    return Pattern(PatternNode(atom_p, (), AtomParams(Cc(channel, controller, value))))


def osc(address: str, *args: OscArg) -> Pattern:
    return Pattern(PatternNode(atom_p, (), AtomParams(Osc(address, tuple(args)))))


def ctrl(label: str, value: float) -> Pattern:
    return Pattern(PatternNode(atom_p, (), AtomParams(Control(label, value))))


def freeze(pat: Pattern) -> Pattern:
    return Pattern(PatternNode(freeze_p, (pat.node,), FreezeParams()))
