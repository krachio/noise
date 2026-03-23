from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from krach.patterns.ir import (
    Atom,
    Cat,
    Cc,
    Control,
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
    Warp,
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
        if not isinstance(cycles, int) and not math.isfinite(cycles):
            raise ValueError(f"over() requires positive cycles, got {cycles}")
        if cycles <= 0:
            raise ValueError(f"over() requires positive cycles, got {cycles}")
        r = _to_rational(cycles)
        if r[0] * r[1] > 0 and r[0] >= r[1]:
            return Pattern(Slow(factor=r, child=self.node))
        return Pattern(Fast(factor=_invert_rational(r), child=self.node))

    def fast(self, factor: int | float) -> Pattern:
        if not isinstance(factor, int) and not math.isfinite(factor):
            raise ValueError(f"fast() requires a positive factor, got {factor}")
        if factor <= 0:
            raise ValueError(f"fast() requires a positive factor, got {factor}")
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
        """Drop events with probability prob (0.0 = keep all, 1.0 = drop all)."""
        return Pattern(Degrade(prob=prob, seed=seed, child=self.node))

    def swing(self, amount: float = 0.67, grid: int = 8) -> Pattern:
        """Apply swing. amount=0.5 is straight, 0.67 is standard, 0.75 is heavy."""
        return Pattern(Warp(kind="swing", amount=amount, grid=grid, child=self.node))

    def mask(self, mask_str: str) -> Pattern:
        """Suppress events where mask has gaps.

        ``kr.seq("A2", "D3", "E2").mask("1 1 0")`` silences the third event.
        Mask tokens: ``1``/``x`` = keep, ``0``/``.``/``~`` = silence.
        """
        tokens = mask_str.split()
        keep = [t in ("1", "x", "X") for t in tokens]
        # Walk the Cat children and replace masked positions with Silence
        node = self.node
        if isinstance(node, Cat):
            new_children: list[IrNode] = []
            for i, child in enumerate(node.children):
                if i < len(keep) and not keep[i]:
                    new_children.append(Silence())
                else:
                    new_children.append(child)
            return Pattern(Cat(tuple(new_children)))
        return self

    def sometimes(self, prob: float, fn: Callable[[Pattern], Pattern], seed: int = 0) -> Pattern:
        """Apply transform with probability ``prob`` each cycle.

        ``p.sometimes(0.3, reverse)`` reverses 30% of cycles.
        Uses ``Degrade`` internally for deterministic randomness.
        """
        transformed = fn(self)
        # Interleave: degrade the original, reverse-degrade the transform
        return Pattern(Stack((
            Degrade(prob=1.0 - prob, seed=seed, child=transformed.node),
            Degrade(prob=prob, seed=seed + 1, child=self.node),
        )))


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


def ctrl(label: str, value: float) -> Pattern:
    return Pattern(Atom(Control(label=label, value=value)))


def freeze(pat: Pattern) -> Pattern:
    """Mark a pattern as an indivisible unit — transforms won't descend."""
    from krach.patterns.ir import Freeze
    return Pattern(Freeze(child=pat.node))
