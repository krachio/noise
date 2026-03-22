from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from krach.patterns.pattern import Pattern


@dataclass(frozen=True)
class Transform:
    _fn: Callable[[Pattern], Pattern]

    def __call__(self, p: Pattern) -> Pattern:
        return self._fn(p)

    def __rshift__(self, other: Transform) -> Transform:
        left, right = self._fn, other._fn
        return Transform(lambda p: right(left(p)))


def fast(factor: int | float) -> Transform:
    return Transform(lambda p: p.fast(factor))


reverse: Transform = Transform(lambda p: p.reverse())


def shift(offset: int | float) -> Transform:
    return Transform(lambda p: p.shift(offset))


def every(n: int, transform: Transform) -> Transform:
    return Transform(lambda p: p.every(n, transform))


def spread(pulses: int, steps: int, rotation: int = 0) -> Transform:
    return Transform(lambda p: p.spread(pulses, steps, rotation))


def thin(prob: float, seed: int = 0) -> Transform:
    return Transform(lambda p: p.thin(prob, seed))
