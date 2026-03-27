"""Primitive instances and abstract_eval rules."""

from __future__ import annotations

from krach.ir.primitive import Primitive
from krach.signal.types import (
    ConstParams,
    ControlParams,
    DelayParams,
    FaustExprParams,
    FeedbackParams,
    NoParams,
    PrimitiveParams,
    RdTableParams,
    RwTableParams,
    SignalType,
)
from krach.signal.trace import abstract_eval, active_precision

# ---------------------------------------------------------------------------
# Primitive instances — arithmetic
# ---------------------------------------------------------------------------

add_p = Primitive("add")
sub_p = Primitive("sub")
mul_p = Primitive("mul")
div_p = Primitive("div")
mod_p = Primitive("mod")
const_p = Primitive("const")

# ---------------------------------------------------------------------------
# Primitive instances — DSP
# ---------------------------------------------------------------------------

mem_p = Primitive("mem", stateful=True)
delay_p = Primitive("delay", stateful=True)
feedback_p = Primitive("feedback", stateful=True)
sr_p = Primitive("sr")
rwtable_p = Primitive("rwtable", stateful=True)
rdtable_p = Primitive("rdtable", stateful=True)

# ---------------------------------------------------------------------------
# Primitive instances — math intrinsics (unary)
# ---------------------------------------------------------------------------

UNARY_MATH_NAMES = (
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "exp",
    "log",
    "log10",
    "sqrt",
    "abs",
    "floor",
    "ceil",
    "round",
)

sin_p = Primitive("sin")
cos_p = Primitive("cos")
tan_p = Primitive("tan")
asin_p = Primitive("asin")
acos_p = Primitive("acos")
atan_p = Primitive("atan")
exp_p = Primitive("exp")
log_p = Primitive("log")
log10_p = Primitive("log10")
sqrt_p = Primitive("sqrt")
abs_p = Primitive("abs")
floor_p = Primitive("floor")
ceil_p = Primitive("ceil")
round_p = Primitive("round")

UNARY_MATH_PRIMS: dict[str, Primitive] = {
    "sin": sin_p,
    "cos": cos_p,
    "tan": tan_p,
    "asin": asin_p,
    "acos": acos_p,
    "atan": atan_p,
    "exp": exp_p,
    "log": log_p,
    "log10": log10_p,
    "sqrt": sqrt_p,
    "abs": abs_p,
    "floor": floor_p,
    "ceil": ceil_p,
    "round": round_p,
}

# ---------------------------------------------------------------------------
# Primitive instances — math intrinsics (binary)
# ---------------------------------------------------------------------------

BINARY_MATH_NAMES = ("min", "max", "pow", "fmod", "remainder", "atan2")

min_p = Primitive("min")
max_p = Primitive("max")
pow_p = Primitive("pow")
fmod_p = Primitive("fmod")
remainder_p = Primitive("remainder")
atan2_p = Primitive("atan2")

BINARY_MATH_PRIMS: dict[str, Primitive] = {
    "min": min_p,
    "max": max_p,
    "pow": pow_p,
    "fmod": fmod_p,
    "remainder": remainder_p,
    "atan2": atan2_p,
}

# ---------------------------------------------------------------------------
# Primitive instances — comparison
# ---------------------------------------------------------------------------

gt_p = Primitive("gt")
lt_p = Primitive("lt")
ge_p = Primitive("ge")
le_p = Primitive("le")
eq_p = Primitive("eq")
ne_p = Primitive("ne")

COMPARISON_PRIMS: dict[str, Primitive] = {
    "gt": gt_p,
    "lt": lt_p,
    "ge": ge_p,
    "le": le_p,
    "eq": eq_p,
    "ne": ne_p,
}

# ---------------------------------------------------------------------------
# Primitive instances — select2
# ---------------------------------------------------------------------------

select2_p = Primitive("select2")

# ---------------------------------------------------------------------------
# Primitive instances — control (hslider)
# ---------------------------------------------------------------------------

control_p = Primitive("control")

# ---------------------------------------------------------------------------
# faust_expr — inline Faust expression
# ---------------------------------------------------------------------------

faust_expr_p = Primitive("faust_expr")

# ---------------------------------------------------------------------------
# Abstract eval rules (registered via RuleRegistry)
# ---------------------------------------------------------------------------


def _check_broadcast_channels(a: SignalType, b: SignalType) -> None:
    if a.channels != b.channels and a.channels != 1 and b.channels != 1:
        raise ValueError(f"Channel mismatch: {a.channels} vs {b.channels}")


def _binop_eval(a: SignalType, b: SignalType, *, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    _check_broadcast_channels(a, b)
    channels = max(a.channels, b.channels)
    return SignalType(channels=channels, precision=a.precision)


abstract_eval.register(add_p, _binop_eval)
abstract_eval.register(sub_p, _binop_eval)
abstract_eval.register(mul_p, _binop_eval)
abstract_eval.register(div_p, _binop_eval)
abstract_eval.register(mod_p, _binop_eval)

for _prim in BINARY_MATH_PRIMS.values():
    abstract_eval.register(_prim, _binop_eval)


def _const_eval(*, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, ConstParams):
        raise TypeError(f"Expected ConstParams, got {type(params).__name__}")
    return SignalType(precision=active_precision())


abstract_eval.register(const_p, _const_eval)


def _unary_eval(a: SignalType, *, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    return SignalType(channels=a.channels, precision=a.precision)


for _prim in UNARY_MATH_PRIMS.values():
    abstract_eval.register(_prim, _unary_eval)


def _mem_eval(a: SignalType, *, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    return SignalType(channels=a.channels, precision=a.precision)


abstract_eval.register(mem_p, _mem_eval)


def _delay_eval(
    sig: SignalType, n: SignalType, *, params: PrimitiveParams
) -> SignalType:
    if not isinstance(params, DelayParams):
        raise TypeError(f"Expected DelayParams, got {type(params).__name__}")
    return SignalType(channels=sig.channels, precision=sig.precision)


abstract_eval.register(delay_p, _delay_eval)


def _comparison_eval(
    a: SignalType, b: SignalType, *, params: PrimitiveParams
) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    _check_broadcast_channels(a, b)
    return SignalType(channels=1, precision=a.precision)


for _prim in COMPARISON_PRIMS.values():
    abstract_eval.register(_prim, _comparison_eval)


def _select2_eval(
    sel: SignalType, a: SignalType, b: SignalType, *, params: PrimitiveParams
) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    if a.channels != b.channels:
        raise ValueError(f"Channel mismatch in select2: {a.channels} vs {b.channels}")
    return SignalType(channels=a.channels, precision=a.precision)


abstract_eval.register(select2_p, _select2_eval)


def _feedback_eval(*, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, FeedbackParams):
        raise TypeError(f"Expected FeedbackParams, got {type(params).__name__}")
    out_sig = params.body_graph.outputs[0]
    return out_sig.aval


abstract_eval.register(feedback_p, _feedback_eval)


def _sr_eval(*, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, NoParams):
        raise TypeError(f"Expected NoParams, got {type(params).__name__}")
    return SignalType(precision=active_precision())


abstract_eval.register(sr_p, _sr_eval)


def _faust_expr_eval(*args: SignalType, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, FaustExprParams):
        raise TypeError(f"Expected FaustExprParams, got {type(params).__name__}")
    return SignalType(precision=active_precision())


abstract_eval.register(faust_expr_p, _faust_expr_eval)


def _control_eval(*, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, ControlParams):
        raise TypeError(f"Expected ControlParams, got {type(params).__name__}")
    return SignalType(precision=active_precision())


abstract_eval.register(control_p, _control_eval)


def _rwtable_eval(
    init: SignalType, w_idx: SignalType, w_val: SignalType, r_idx: SignalType,
    *, params: PrimitiveParams,
) -> SignalType:
    if not isinstance(params, RwTableParams):
        raise TypeError(f"Expected RwTableParams, got {type(params).__name__}")
    return SignalType(channels=1, precision=init.precision)


abstract_eval.register(rwtable_p, _rwtable_eval)


def _rdtable_eval(r_idx: SignalType, *, params: PrimitiveParams) -> SignalType:
    if not isinstance(params, RdTableParams):
        raise TypeError(f"Expected RdTableParams, got {type(params).__name__}")
    return SignalType(channels=1, precision=r_idx.precision)


abstract_eval.register(rdtable_p, _rdtable_eval)

# ── Completeness set ─────────────────────────────────────────────────────

ALL_SIGNAL_PRIMITIVES: frozenset[Primitive] = frozenset({
    add_p, sub_p, mul_p, div_p, mod_p, const_p,
    mem_p, delay_p, feedback_p, sr_p,
    rwtable_p, rdtable_p,
    *UNARY_MATH_PRIMS.values(),
    *BINARY_MATH_PRIMS.values(),
    *COMPARISON_PRIMS.values(),
    select2_p, control_p, faust_expr_p,
})

abstract_eval.check_complete(ALL_SIGNAL_PRIMITIVES)
