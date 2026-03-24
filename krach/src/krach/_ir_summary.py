"""Human-readable pattern summary via per-primitive summary rules.

Walks a PatternNode tree using fold and returns a compact string like:
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
from krach.patterns.ir import Cc, Control, Note
from krach.patterns.primitives import (
    atom_p, cat_p, degrade_p, def_summary, early_p, euclid_p, every_p,
    fast_p, fold, freeze_p, late_p, rev_p, silence_p, slow_p, stack_p, warp_p,
)


# ── Summary rules ────────────────────────────────────────────────────────


def _fmt_value(v: float) -> str:
    if v == int(v) and abs(v) < 1e6:
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _join(parts: tuple[str, ...], sep: str, max_items: int) -> str:
    if len(parts) <= max_items:
        return sep.join(parts)
    shown = list(parts[:max_items])
    remaining = len(parts) - max_items
    return sep.join(shown) + f" ...+{remaining} more"


def _atom_summary(node: PatternNode, _children: tuple[str, ...]) -> str:
    assert isinstance(node.params, AtomParams)
    val = node.params.value
    if isinstance(val, Note):
        return midi_to_name(val.note)
    if isinstance(val, Control):
        return f"{val.label}={_fmt_value(val.value)}"
    if isinstance(val, Cc):
        return f"cc({val.controller},{val.value})"
    return f"osc({val.address})"


def _factor_str(factor: tuple[int, int]) -> str:
    if factor[1] == 1:
        return str(factor[0])
    return f"{factor[0]}/{factor[1]}"


def _silence_summary(_node: PatternNode, _children: tuple[str, ...]) -> str:
    return "~"


def _cat_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    return _join(children, ", ", _max_items_ctx)


def _stack_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    return _join(children, " | ", _max_items_ctx)


def _freeze_summary(_node: PatternNode, children: tuple[str, ...]) -> str:
    return children[0] if children else "freeze()"


def _fast_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, FastParams)
    return f"{children[0]} *{_factor_str(node.params.factor)}"


def _slow_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, SlowParams)
    return f"{children[0]} /{_factor_str(node.params.factor)}"


def _rev_summary(_node: PatternNode, children: tuple[str, ...]) -> str:
    return f"{children[0]} rev"


def _early_summary(_node: PatternNode, children: tuple[str, ...]) -> str:
    return children[0]


def _late_summary(_node: PatternNode, children: tuple[str, ...]) -> str:
    return children[0]


def _every_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, EveryParams)
    # children[0]=transform, children[1]=source — show source
    return f"{children[1]} every({node.params.n})"


def _euclid_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, EuclidParams)
    p = node.params
    return f"{children[0]} spread({p.pulses},{p.steps})"


def _degrade_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, DegradeParams)
    return f"{children[0]} thin({node.params.prob:.0%})"


def _warp_summary(node: PatternNode, children: tuple[str, ...]) -> str:
    assert isinstance(node.params, WarpParams)
    p = node.params
    return f"{children[0]} {p.kind}({p.amount:.2f})"


# ── Registration ─────────────────────────────────────────────────────────

def_summary(atom_p, _atom_summary)
def_summary(silence_p, _silence_summary)
def_summary(cat_p, _cat_summary)
def_summary(stack_p, _stack_summary)
def_summary(freeze_p, _freeze_summary)
def_summary(fast_p, _fast_summary)
def_summary(slow_p, _slow_summary)
def_summary(early_p, _early_summary)
def_summary(late_p, _late_summary)
def_summary(rev_p, _rev_summary)
def_summary(every_p, _every_summary)
def_summary(euclid_p, _euclid_summary)
def_summary(degrade_p, _degrade_summary)
def_summary(warp_p, _warp_summary)


# ── Public API ───────────────────────────────────────────────────────────

# Thread-local-ish context for max_items (avoids threading it through fold).
_max_items_ctx: int = 8


def summarize(node: PatternNode, max_items: int = 8) -> str:
    """Compact human-readable summary of a pattern tree."""
    global _max_items_ctx
    prev = _max_items_ctx
    _max_items_ctx = max_items
    try:
        from krach.patterns.primitives import get_summary_rule
        result: str = fold(node, lambda nd, children: get_summary_rule(nd.primitive)(nd, children))
        return result
    finally:
        _max_items_ctx = prev
