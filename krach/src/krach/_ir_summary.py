"""Human-readable pattern summary.

Walks a PatternNode tree and returns a compact string like:
  "A2, D3, ~, E2"  or  "freq=220 | gate=1, gate=0"
"""

from __future__ import annotations

from krach._pitch import midi_to_name
from krach.ir.pattern import (
    AtomParams,
    DegradeParams,
    EuclidParams,
    EveryParams,
    FastParams,
    PatternNode,
    SlowParams,
    WarpParams,
)
from krach.patterns.values import Cc, Control, Note


def summarize(node: PatternNode, max_items: int = 8) -> str:
    """Compact human-readable summary of a pattern tree."""

    def _go(nd: PatternNode) -> str:
        p = nd.primitive.name

        if p == "atom":
            assert isinstance(nd.params, AtomParams)
            return _atom(nd.params)
        if p == "silence":
            return "~"
        if p == "freeze":
            return _go(nd.children[0]) if nd.children else "freeze()"
        if p == "cat":
            return _join(tuple(_go(c) for c in nd.children), ", ")
        if p == "stack":
            return _join(tuple(_go(c) for c in nd.children), " | ")
        if p == "fast":
            assert isinstance(nd.params, FastParams)
            return f"{_go(nd.children[0])} *{_factor(nd.params.factor)}"
        if p == "slow":
            assert isinstance(nd.params, SlowParams)
            return f"{_go(nd.children[0])} /{_factor(nd.params.factor)}"
        if p == "rev":
            return f"{_go(nd.children[0])} rev"
        if p == "early" or p == "late":
            return _go(nd.children[0])
        if p == "every":
            assert isinstance(nd.params, EveryParams)
            return f"{_go(nd.children[1])} every({nd.params.n})"
        if p == "euclid":
            assert isinstance(nd.params, EuclidParams)
            return f"{_go(nd.children[0])} spread({nd.params.pulses},{nd.params.steps})"
        if p == "degrade":
            assert isinstance(nd.params, DegradeParams)
            return f"{_go(nd.children[0])} thin({nd.params.prob:.0%})"
        if p == "warp":
            assert isinstance(nd.params, WarpParams)
            return f"{_go(nd.children[0])} {nd.params.kind}({nd.params.amount:.2f})"
        raise RuntimeError(f"no summary for pattern primitive {p!r}")

    def _join(parts: tuple[str, ...], sep: str) -> str:
        if len(parts) <= max_items:
            return sep.join(parts)
        shown = list(parts[:max_items])
        remaining = len(parts) - max_items
        return sep.join(shown) + f" ...+{remaining} more"

    return _go(node)


def _atom(params: AtomParams) -> str:
    val = params.value
    if isinstance(val, Note):
        return midi_to_name(val.note)
    if isinstance(val, Control):
        return f"{val.label}={_fmt_value(val.value)}"
    if isinstance(val, Cc):
        return f"cc({val.controller},{val.value})"
    return f"osc({val.address})"


def _fmt_value(v: float) -> str:
    if v == int(v) and abs(v) < 1e6:
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _factor(f: tuple[int, int]) -> str:
    if f[1] == 1:
        return str(f[0])
    return f"{f[0]}/{f[1]}"
