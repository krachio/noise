"""Pattern parsing — converts string input to Pattern objects.

Supports two formats:
1. Mini-notation: "x . x . x . . x", "C4 E4 G4 ~ C5"
2. Builder expression: "note('C4', 'E4').over(2) + rest()"
"""

from __future__ import annotations

import ast
from typing import Any

from krach.pattern.mininotation import p as _mini_p
from krach.pattern.builders import (
    cat, hit, mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square,
    mod_tri, note, ramp, rand, saw, seq, sine, stack, struct,
)
from krach.pattern.pattern import Pattern, rest


def chord(*notes: str | int | float) -> Pattern:
    """Build a chord — simultaneous notes stacked for polyphonic playback."""
    return note(*notes)


def euclid(pulses: int, steps: int, rotation: int = 0) -> Pattern:
    """Build a Euclidean rhythm — evenly distribute pulses across steps."""
    return (hit() * steps).spread(pulses, steps, rotation)


# Namespace for eval — only safe pattern builders, no I/O, no internal types
_EVAL_NS: dict[str, Any] = {
    "note": note,
    "hit": hit,
    "seq": seq,
    "rest": rest,
    "cat": cat,
    "stack": stack,
    "struct": struct,
    "chord": chord,
    "euclid": euclid,
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
}

# Methods allowed on Pattern objects (returned by builders)
_ALLOWED_METHODS: frozenset[str] = frozenset({
    "over", "fast", "slow", "shift", "reverse", "spread",
    "thin", "swing", "mask", "every",
})


class _SafeEvalError(Exception):
    pass


def _safe_eval(node: ast.expr) -> Any:
    """Evaluate an AST node using only allowed names and operations."""
    match node:
        case ast.Constant(value=v) if isinstance(v, (int, float, str, type(None))):
            return v
        case ast.Name(id=name) if name in _EVAL_NS:
            return _EVAL_NS[name]
        case ast.Name(id="None"):
            return None
        case ast.Call(func=func, args=args, keywords=kws):
            fn = _safe_eval(func)
            evaluated_args = [_safe_eval(a) for a in args]
            evaluated_kws = {k.arg: _safe_eval(k.value) for k in kws if k.arg is not None}
            return fn(*evaluated_args, **evaluated_kws)
        case ast.Attribute(value=val, attr=attr) if attr in _ALLOWED_METHODS:
            obj = _safe_eval(val)
            return getattr(obj, attr)
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            return _safe_eval(left) + _safe_eval(right)
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _safe_eval(left) | _safe_eval(right)
        case ast.BinOp(left=left, op=ast.Mult(), right=right):
            return _safe_eval(left) * _safe_eval(right)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_safe_eval(operand)
        case _:
            raise _SafeEvalError(f"disallowed expression: {ast.dump(node)}")


def _try_builder_eval(text: str) -> Pattern | None:
    """Parse and safely evaluate a builder expression. Returns None on failure."""
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    try:
        result = _safe_eval(tree.body)
    except (_SafeEvalError, TypeError, ValueError, AttributeError, KeyError):
        return None
    if isinstance(result, Pattern):
        return result
    return None


def parse_pattern(text: str) -> Pattern:
    """Parse a pattern string — tries mini-notation first, then builder eval.

    Mini-notation: "x . x .", "C4 E4 ~ G4", "[C4 E4] G4"
    Builder: "note('C4').over(2) + rest()", "hit() * 4"
    """
    text = text.strip()
    if not text:
        raise ValueError("empty pattern string")

    # Heuristic: if it contains Python syntax, try builder eval first
    if "(" in text or "*" in text:
        result = _try_builder_eval(text)
        if result is not None:
            return result

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
