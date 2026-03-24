"""Human-readable IR pattern summary.

Walks a pattern IR tree and returns a compact string like:
  "A2, D3, ~, E2"  or  "freq=220 | gate=1, gate=0"
"""

from __future__ import annotations

from krach._pitch import midi_to_name
from krach.patterns.ir import (
    Atom,
    Cat,
    Control,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Freeze,
    IrNode,
    Late,
    Note,
    Rev,
    Silence,
    Slow,
    Stack,
    Warp,
)


def summarize(node: IrNode, max_items: int = 8) -> str:
    """Compact human-readable summary of a pattern IR tree."""
    match node:
        case Atom(Note(note=midi)):
            return midi_to_name(midi)
        case Atom(Control(label=label, value=value)):
            return f"{label}={_fmt_value(value)}"
        case Atom():
            return "atom"
        case Silence():
            return "~"
        case Freeze(child):
            return summarize(child, max_items)
        case Cat(children):
            return _join_children(children, ", ", max_items)
        case Stack(children):
            return _join_children(children, " | ", max_items)
        case Fast(factor, child):
            f = factor[0] // factor[1] if factor[1] == 1 else f"{factor[0]}/{factor[1]}"
            return f"{summarize(child, max_items)} *{f}"
        case Slow(factor, child):
            f = factor[0] // factor[1] if factor[1] == 1 else f"{factor[0]}/{factor[1]}"
            return f"{summarize(child, max_items)} /{f}"
        case Rev(child):
            return f"{summarize(child, max_items)} rev"
        case Early(_, child):
            return summarize(child, max_items)
        case Late(_, child):
            return summarize(child, max_items)
        case Every(n, _, child):
            return f"{summarize(child, max_items)} every({n})"
        case Euclid(pulses, steps, _, child):
            return f"{summarize(child, max_items)} spread({pulses},{steps})"
        case Degrade(prob, _, child):
            return f"{summarize(child, max_items)} thin({prob:.0%})"
        case Warp(kind, amount, _, child):
            return f"{summarize(child, max_items)} {kind}({amount:.2f})"
        case _:
            return "?"


def _join_children(children: tuple[IrNode, ...], sep: str, max_items: int) -> str:
    """Join child summaries, truncating if too many."""
    if len(children) <= max_items:
        return sep.join(summarize(c, max_items) for c in children)
    shown = [summarize(c, max_items) for c in children[:max_items]]
    remaining = len(children) - max_items
    return sep.join(shown) + f" ...+{remaining} more"


def _fmt_value(v: float) -> str:
    """Format a float compactly: drop trailing zeros, no unnecessary decimals."""
    if v == int(v) and abs(v) < 1e6:
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")
