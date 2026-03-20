from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from midiman_frontend.ir import (
    Atom,
    AtomGroup,
    Cat,
    Cc,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    IrNode,
    Late,
    Note,
    Osc,
    OscArg,
    Rev,
    Silence,
    Slow,
    Stack,
)


def _to_rational(value: int | float) -> tuple[int, int]:
    if isinstance(value, int):
        return (value, 1)
    f = Fraction(value).limit_denominator(256)
    return (f.numerator, f.denominator)


def _invert_rational(r: tuple[int, int]) -> tuple[int, int]:
    return (r[1], r[0])


def _flatten_cat(left: IrNode, right: IrNode) -> tuple[IrNode, ...]:
    left_children = left.children if isinstance(left, Cat) else (left,)
    right_children = right.children if isinstance(right, Cat) else (right,)
    return (*left_children, *right_children)


def _flatten_stack(left: IrNode, right: IrNode) -> tuple[IrNode, ...]:
    left_children = left.children if isinstance(left, Stack) else (left,)
    right_children = right.children if isinstance(right, Stack) else (right,)
    return (*left_children, *right_children)


@dataclass(frozen=True)
class Pattern:
    node: IrNode

    # ── Operators ────────────────────────────────────────────────────────

    def __add__(self, other: Pattern) -> Pattern:
        return Pattern(Cat(_flatten_cat(self.node, other.node)))

    def __or__(self, other: Pattern) -> Pattern:
        return Pattern(Stack(_flatten_stack(self.node, other.node)))

    def __mul__(self, n: int) -> Pattern:
        return Pattern(Cat(tuple(self.node for _ in range(n))))

    # ── Time transforms ──────────────────────────────────────────────────

    def over(self, cycles: int | float) -> Pattern:
        r = _to_rational(cycles)
        if r[0] * r[1] > 0 and r[0] >= r[1]:
            return Pattern(Slow(factor=r, child=self.node))
        return Pattern(Fast(factor=_invert_rational(r), child=self.node))

    def scale(self, factor: int | float) -> Pattern:
        r = _to_rational(factor)
        if r[0] * r[1] > 0 and r[0] >= r[1]:
            return Pattern(Fast(factor=r, child=self.node))
        return Pattern(Slow(factor=_invert_rational(r), child=self.node))

    def shift(self, offset: int | float) -> Pattern:
        r = _to_rational(offset)
        if r[0] >= 0:
            return Pattern(Late(offset=r, child=self.node))
        return Pattern(Early(offset=(abs(r[0]), r[1]), child=self.node))

    # ── Structural transforms ────────────────────────────────────────────

    def reverse(self) -> Pattern:
        return Pattern(Rev(child=self.node))

    def every(self, n: int, fn: Callable[[Pattern], Pattern]) -> Pattern:
        transformed = fn(self)
        return Pattern(Every(n=n, transform=transformed.node, child=self.node))

    def spread(self, pulses: int, steps: int, rotation: int = 0) -> Pattern:
        return Pattern(
            Euclid(pulses=pulses, steps=steps, rotation=rotation, child=self.node)
        )

    def thin(self, prob: float, seed: int = 0) -> Pattern:
        return Pattern(Degrade(prob=prob, seed=seed, child=self.node))


# ── Atom constructors ────────────────────────────────────────────────────


def note(
    pitch: int, velocity: int = 100, channel: int = 0, duration: float = 1.0
) -> Pattern:
    return Pattern(Atom(Note(channel=channel, note=pitch, velocity=velocity, dur=duration)))


def rest() -> Pattern:
    return Pattern(Silence())


def cc(controller: int, value: int, channel: int = 0) -> Pattern:
    return Pattern(Atom(Cc(channel=channel, controller=controller, value=value)))


def osc(address: str, *args: OscArg) -> Pattern:
    return Pattern(Atom(Osc(address=address, args=tuple(args))))


def atom_group(values: tuple[Osc, ...], reset: Osc | None = None) -> Pattern:
    """Multiple values at onset + optional reset at end. Counts as ONE atom."""
    return Pattern(AtomGroup(values=values, reset=reset))
