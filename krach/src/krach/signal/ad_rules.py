"""JVP rules for all signal primitives — registered at import time."""

from __future__ import annotations

import math

from krach.ir.primitive import Primitive
from krach.signal.types import ConstParams, PrimitiveParams, Signal
from krach.signal.trace import bind as _bind
from krach.signal.ad import (
    Tangent,
    ZeroTangent,
    is_zero,
    materialize,
    register_jvp,
    tangent_add,
    tangent_mul,
    tangent_neg,
)
from krach.signal.primitives import (
    abs_p, acos_p, add_p, asin_p, atan2_p, atan_p, ceil_p, const_p,
    cos_p, div_p, exp_p, floor_p, fmod_p, gt_p, lt_p,
    log10_p, log_p, max_p, mem_p, min_p, mod_p, mul_p,
    pow_p, remainder_p, round_p, select2_p, sin_p, sqrt_p, sr_p, sub_p, tan_p,
    feedback_p, delay_p, faust_expr_p, control_p,
    COMPARISON_PRIMS,
)


# -- const -------------------------------------------------------------------
def _jvp_const(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    out = _bind(prim, params=params)
    return out, ZeroTangent(aval=out.aval)


register_jvp(const_p, _jvp_const)


# -- sr / zero-output -------------------------------------------------------
def _jvp_zero_output(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    out = _bind(prim, *primals, params=params)
    return out, ZeroTangent(aval=out.aval)


register_jvp(sr_p, _jvp_zero_output)


# -- add ---------------------------------------------------------------------
def _jvp_add(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    return _bind(add_p, a, b), tangent_add(da, db)


register_jvp(add_p, _jvp_add)


# -- sub ---------------------------------------------------------------------
def _jvp_sub(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    return _bind(sub_p, a, b), tangent_add(da, tangent_neg(db))


register_jvp(sub_p, _jvp_sub)


# -- mul (product rule) ------------------------------------------------------
def _jvp_mul(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    return _bind(mul_p, a, b), tangent_add(tangent_mul(b, da), tangent_mul(a, db))


register_jvp(mul_p, _jvp_mul)


# -- div ---------------------------------------------------------------------
def _jvp_div(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    out = _bind(div_p, a, b)
    num = tangent_add(tangent_mul(b, da), tangent_neg(tangent_mul(a, db)))
    if is_zero(num):
        return out, num
    b_sq = _bind(mul_p, b, b)
    assert isinstance(num, Signal)
    return out, _bind(div_p, num, b_sq)


register_jvp(div_p, _jvp_div)


# -- mod / fmod --------------------------------------------------------------
def _jvp_mod(
    prim: Primitive,
    primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...],
    params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    out = _bind(prim, a, b)
    floored = _bind(floor_p, _bind(div_p, a, b))
    t = tangent_add(da, tangent_neg(tangent_mul(floored, db)))
    return out, t


register_jvp(mod_p, _jvp_mod)
register_jvp(fmod_p, _jvp_mod)
register_jvp(remainder_p, _jvp_mod)


# -- trig --------------------------------------------------------------------
def _jvp_sin(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(sin_p, x)
    return out, tangent_mul(_bind(cos_p, x), dx)


register_jvp(sin_p, _jvp_sin)


def _jvp_cos(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(cos_p, x)
    return out, tangent_neg(tangent_mul(_bind(sin_p, x), dx))


register_jvp(cos_p, _jvp_cos)


def _jvp_tan(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(tan_p, x)
    cos_x = _bind(cos_p, x)
    cos_sq = _bind(mul_p, cos_x, cos_x)
    if is_zero(dx):
        return out, dx
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, cos_sq)


register_jvp(tan_p, _jvp_tan)


# -- inverse trig ------------------------------------------------------------
def _jvp_asin(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(asin_p, x)
    if is_zero(dx):
        return out, dx
    denom = _bind(sqrt_p, _bind(sub_p, 1.0, _bind(mul_p, x, x)))
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, denom)


register_jvp(asin_p, _jvp_asin)


def _jvp_acos(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(acos_p, x)
    if is_zero(dx):
        return out, dx
    denom = _bind(sqrt_p, _bind(sub_p, 1.0, _bind(mul_p, x, x)))
    assert isinstance(dx, Signal)
    return out, _bind(mul_p, _bind(div_p, dx, denom), -1.0)


register_jvp(acos_p, _jvp_acos)


def _jvp_atan(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(atan_p, x)
    if is_zero(dx):
        return out, dx
    denom = _bind(add_p, 1.0, _bind(mul_p, x, x))
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, denom)


register_jvp(atan_p, _jvp_atan)


def _jvp_atan2(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    y, x = primals
    dy, dx = tangents
    out = _bind(atan2_p, y, x)
    num = tangent_add(tangent_mul(x, dy), tangent_neg(tangent_mul(y, dx)))
    if is_zero(num):
        return out, num
    denom = _bind(add_p, _bind(mul_p, x, x), _bind(mul_p, y, y))
    assert isinstance(num, Signal)
    return out, _bind(div_p, num, denom)


register_jvp(atan2_p, _jvp_atan2)


# -- exp/log/sqrt ------------------------------------------------------------
def _jvp_exp(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(exp_p, x)
    return out, tangent_mul(out, dx)


register_jvp(exp_p, _jvp_exp)


def _jvp_log(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(log_p, x)
    if is_zero(dx):
        return out, dx
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, x)


register_jvp(log_p, _jvp_log)


def _jvp_log10(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(log10_p, x)
    if is_zero(dx):
        return out, dx
    ln10 = _bind(const_p, params=ConstParams(value=math.log(10.0)))
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, _bind(mul_p, x, ln10))


register_jvp(log10_p, _jvp_log10)


def _jvp_sqrt(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(sqrt_p, x)
    if is_zero(dx):
        return out, dx
    assert isinstance(dx, Signal)
    return out, _bind(div_p, dx, _bind(mul_p, 2.0, out))


register_jvp(sqrt_p, _jvp_sqrt)


# -- abs ---------------------------------------------------------------------
def _jvp_abs(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    (x,) = primals
    (dx,) = tangents
    out = _bind(abs_p, x)
    if is_zero(dx):
        return out, dx
    zero = _bind(const_p, params=ConstParams(value=0.0))
    one = _bind(const_p, params=ConstParams(value=1.0))
    neg_one = _bind(const_p, params=ConstParams(value=-1.0))
    sign = _bind(select2_p, _bind(gt_p, x, zero), neg_one, one)
    sign = _bind(select2_p, _bind(lt_p, x, zero), sign, neg_one)
    assert isinstance(dx, Signal)
    return out, _bind(mul_p, sign, dx)


register_jvp(abs_p, _jvp_abs)

# -- floor, ceil, round — zero tangent ---------------------------------------
register_jvp(floor_p, _jvp_zero_output)
register_jvp(ceil_p, _jvp_zero_output)
register_jvp(round_p, _jvp_zero_output)

# -- comparisons — zero tangent ----------------------------------------------
for _prim in COMPARISON_PRIMS.values():
    register_jvp(_prim, _jvp_zero_output)


# -- select2 -----------------------------------------------------------------
def _jvp_select2(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    sel, a, b = primals
    _dsel, da, db = tangents
    out = _bind(select2_p, sel, a, b)
    t = _bind(select2_p, sel, materialize(da), materialize(db))
    return out, t


register_jvp(select2_p, _jvp_select2)


# -- min/max/pow -------------------------------------------------------------
def _jvp_min(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    out = _bind(min_p, a, b)
    t = _bind(select2_p, _bind(lt_p, a, b), materialize(db), materialize(da))
    return out, t


register_jvp(min_p, _jvp_min)


def _jvp_max(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    out = _bind(max_p, a, b)
    t = _bind(select2_p, _bind(gt_p, a, b), materialize(db), materialize(da))
    return out, t


register_jvp(max_p, _jvp_max)


def _jvp_pow(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    a, b = primals
    da, db = tangents
    out = _bind(pow_p, a, b)
    t1 = tangent_mul(_bind(mul_p, b, _bind(pow_p, a, _bind(sub_p, b, 1.0))), da)
    t2 = tangent_mul(_bind(mul_p, out, _bind(log_p, a)), db)
    return out, tangent_add(t1, t2)


register_jvp(pow_p, _jvp_pow)


# -- stateful / opaque — not differentiable ----------------------------------
def _jvp_not_implemented(
    prim: Primitive, primals: tuple[Signal, ...],
    tangents: tuple[Tangent, ...], params: PrimitiveParams,
) -> tuple[Signal, Tangent]:
    raise NotImplementedError(
        f"Primitive {prim.name!r} is stateful and cannot be differentiated."
    )


for _prim in (mem_p, delay_p, feedback_p):
    register_jvp(_prim, _jvp_not_implemented)

register_jvp(faust_expr_p, _jvp_not_implemented)

# control — zero tangent (constant from AD perspective)
register_jvp(control_p, _jvp_zero_output)
