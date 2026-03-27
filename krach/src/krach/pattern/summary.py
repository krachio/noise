"""Human-readable pattern summary.

Walks a PatternNode tree and returns a compact string like:
  "A2, D3, ~, E2"  or  "freq=220 | gate=1, gate=0"
"""

from __future__ import annotations

from collections.abc import Callable

from krach.pattern.pitch import midi_to_name
from krach.pattern.types import (
    AtomParams,
    DegradeParams,
    EuclidParams,
    EveryParams,
    FastParams,
    PatternNode,
    SlowParams,
    WarpParams,
)
from krach.ir.values import Cc, Control, Note


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
    return str(f[0]) if f[1] == 1 else f"{f[0]}/{f[1]}"


# ── Per-primitive summary handlers ───────────────────────────────────
# Each handler receives (node, go, join) where go recurses and join
# truncates. Registering here guarantees import-time completeness.

type _GoFn = Callable[[PatternNode], str]
type _JoinFn = Callable[[tuple[str, ...], str], str]
type _Handler = Callable[[PatternNode, _GoFn, _JoinFn], str]

_HANDLERS: dict[str, _Handler] = {
    "atom":    lambda nd, go, _j: _atom(nd.params) if isinstance(nd.params, AtomParams) else "atom",
    "silence": lambda _n, _g, _j: "~",
    "freeze":  lambda nd, go, _j: go(nd.children[0]) if nd.children else "freeze()",
    "cat":     lambda nd, go, j: j(tuple(go(c) for c in nd.children), ", "),
    "stack":   lambda nd, go, j: j(tuple(go(c) for c in nd.children), " | "),
    "fast":    lambda nd, go, _j: f"{go(nd.children[0])} *{_factor(nd.params.factor)}" if isinstance(nd.params, FastParams) else "?",
    "slow":    lambda nd, go, _j: f"{go(nd.children[0])} /{_factor(nd.params.factor)}" if isinstance(nd.params, SlowParams) else "?",
    "rev":     lambda nd, go, _j: f"{go(nd.children[0])} rev",
    "early":   lambda nd, go, _j: go(nd.children[0]),
    "late":    lambda nd, go, _j: go(nd.children[0]),
    "every":   lambda nd, go, _j: f"{go(nd.children[1])} every({nd.params.n})" if isinstance(nd.params, EveryParams) else "?",
    "euclid":  lambda nd, go, _j: f"{go(nd.children[0])} spread({nd.params.pulses},{nd.params.steps})" if isinstance(nd.params, EuclidParams) else "?",
    "degrade": lambda nd, go, _j: f"{go(nd.children[0])} thin({nd.params.prob:.0%})" if isinstance(nd.params, DegradeParams) else "?",
    "warp":    lambda nd, go, _j: f"{go(nd.children[0])} {nd.params.kind}({nd.params.amount:.2f})" if isinstance(nd.params, WarpParams) else "?",
}

# Import-time completeness check — fail loud if a primitive is missing.
from krach.pattern.primitives import ALL_PATTERN_PRIMITIVES  # noqa: E402

_expected = {p.name for p in ALL_PATTERN_PRIMITIVES}
_registered = set(_HANDLERS.keys())
_missing = _expected - _registered
if _missing:
    raise RuntimeError(f"summary handlers missing for primitives: {_missing}")


# ── Public API ───────────────────────────────────────────────────────


def summarize(node: PatternNode, max_items: int = 8) -> str:
    """Compact human-readable summary of a pattern tree."""

    def _go(nd: PatternNode) -> str:
        handler = _HANDLERS.get(nd.primitive.name)
        if handler is None:
            raise RuntimeError(f"no summary for pattern primitive {nd.primitive.name!r}")
        return handler(nd, _go, _join)

    def _join(parts: tuple[str, ...], sep: str) -> str:
        if len(parts) <= max_items:
            return sep.join(parts)
        shown = list(parts[:max_items])
        return sep.join(shown) + f" ...+{len(parts) - max_items} more"

    return _go(node)
