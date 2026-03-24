"""Pattern parsing — converts string input to Pattern objects.

Supports two formats:
1. Mini-notation: "x . x . x . . x", "C4 E4 G4 ~ C5"
2. Builder expression: "note('C4', 'E4').over(2) + rest()"
"""

from __future__ import annotations

from krach._mininotation import p as _mini_p
from krach._patterns import (
    cat, hit, mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square,
    mod_tri, note, ramp, rand, saw, seq, sine, stack, struct,
)
from krach.patterns.pattern import Pattern, rest

# Namespace for eval — only safe pattern builders, no I/O
_EVAL_NS: dict[str, object] = {
    "note": note,
    "hit": hit,
    "seq": seq,
    "rest": rest,
    "cat": cat,
    "stack": stack,
    "struct": struct,
    "ramp": ramp,
    "rand": rand,
    "sine": sine,
    "saw": saw,
    "mod_sine": mod_sine,
    "mod_tri": mod_tri,
    "mod_ramp": mod_ramp,
    "mod_ramp_down": mod_ramp_down,
    "mod_square": mod_square,
    "mod_exp": mod_exp,
    "Pattern": Pattern,
}


def parse_pattern(text: str) -> Pattern:
    """Parse a pattern string — tries mini-notation first, then builder eval.

    Mini-notation: "x . x .", "C4 E4 ~ G4", "[C4 E4] G4"
    Builder: "note('C4').over(2) + rest()", "hit() * 4"
    """
    text = text.strip()
    if not text:
        raise ValueError("empty pattern string")

    # Heuristic: if it contains Python syntax (parens, dots after idents,
    # operators like * + |), try builder eval first
    if "(" in text or "*" in text:
        try:
            result = eval(text, {"__builtins__": {}}, _EVAL_NS)  # noqa: S307
            if isinstance(result, Pattern):
                return result
        except Exception:
            pass

    # Try mini-notation
    try:
        return _mini_p(text)
    except Exception:
        pass

    # Last resort: try as a single note
    try:
        return note(text)
    except Exception:
        raise ValueError(f"cannot parse pattern: {text!r}") from None
