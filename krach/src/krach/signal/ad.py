"""Forward-mode automatic differentiation (JVP) for DspGraph.

Usage::

    from krach.signal.ad import jvp

    # Differentiate a single-input graph w.r.t. its input
    jvp_graph = jvp(lambda x: x * x, num_inputs=1)
    # jvp_graph outputs: [primal, tangent]
    # jvp_graph inputs:  [x, dx]
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from krach.ir.signal import (
    ConstParams,
    DspGraph,
    Precision,
    Primitive,
    PrimitiveParams,
    Signal,
    SignalType,
    TraceContext,
    pop_trace,
    push_trace,
)
from krach.signal.compose import DspFunc

# ---------------------------------------------------------------------------
# ZeroTangent — symbolic zero, avoids emitting 0*x nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZeroTangent:
    """Symbolic zero tangent — carries type info without emitting graph nodes."""
    aval: SignalType


type Tangent = Signal | ZeroTangent

# ---------------------------------------------------------------------------
# Tangent helpers
# ---------------------------------------------------------------------------


def is_zero(t: Tangent) -> bool:
    return isinstance(t, ZeroTangent)


def tangent_add(a: Tangent, b: Tangent) -> Tangent:
    """Add two tangents, short-circuiting on symbolic zeros."""
    if is_zero(a) and is_zero(b):
        return a
    if is_zero(a):
        return b
    if is_zero(b):
        return a
    from krach.signal.primitives import add_p
    assert isinstance(a, Signal) and isinstance(b, Signal)
    return add_p.bind(a, b)


def tangent_mul(primal: Signal, tangent: Tangent) -> Tangent:
    """Multiply a primal signal by a tangent, short-circuiting on zero."""
    if is_zero(tangent):
        return tangent
    from krach.signal.primitives import mul_p
    assert isinstance(tangent, Signal)
    return mul_p.bind(primal, tangent)


def tangent_neg(t: Tangent) -> Tangent:
    """Negate a tangent, short-circuiting on zero."""
    if is_zero(t):
        return t
    from krach.signal.primitives import mul_p
    assert isinstance(t, Signal)
    return mul_p.bind(t, -1.0)


def materialize(t: Tangent) -> Signal:
    """Convert a ZeroTangent to const(0.0), or pass through a Signal."""
    if isinstance(t, Signal):
        return t
    from krach.signal.primitives import const_p
    return const_p.bind(params=ConstParams(value=0.0))


# ---------------------------------------------------------------------------
# JVP rule registry
# ---------------------------------------------------------------------------

type JvpRule = Callable[
    [Primitive, tuple[Signal, ...], tuple[Tangent, ...], PrimitiveParams],
    tuple[Signal, Tangent],
]

_JVP_RULES: dict[str, JvpRule] = {}


def register_jvp(prim: Primitive, fn: JvpRule) -> None:
    _JVP_RULES[prim.name] = fn


# ---------------------------------------------------------------------------
# jvp_graph transform
# ---------------------------------------------------------------------------


def jvp_graph(graph: DspGraph, *, wrt: list[int] | None = None) -> DspGraph:
    """Transform graph into one that computes (primals..., tangents...).

    Args:
        graph: Source graph to differentiate.
        wrt: Input indices to differentiate w.r.t. If None, all inputs.

    Returns:
        New graph with inputs [primals..., tangents_for_wrt...] and
        outputs [primals..., tangents...].
    """
    if wrt is None:
        wrt = list(range(len(graph.inputs)))

    ctx = TraceContext(precision=graph.precision)
    token = push_trace(ctx)
    try:
        env, tang = _setup_inputs(graph, ctx, wrt)
        for eqn in graph.equations:
            _process_equation(eqn, env, tang)
        outputs = _collect_outputs(graph, env, tang)
    finally:
        pop_trace(token)

    return ctx.to_graph(outputs)


def _setup_inputs(
    graph: DspGraph,
    ctx: TraceContext,
    wrt: list[int],
) -> tuple[dict[int, Signal], dict[int, Tangent]]:
    """Create primal and tangent inputs in the new context."""
    env: dict[int, Signal] = {}
    tang: dict[int, Tangent] = {}

    for orig in graph.inputs:
        new_primal = ctx.new_input(orig.aval)
        env[orig.id] = new_primal

    wrt_set = set(wrt)
    for idx, orig in enumerate(graph.inputs):
        if idx in wrt_set:
            tang[orig.id] = ctx.new_input(orig.aval)
        else:
            tang[orig.id] = ZeroTangent(aval=orig.aval)

    return env, tang


def _process_equation(
    eqn: object,
    env: dict[int, Signal],
    tang: dict[int, Tangent],
) -> None:
    from krach.ir.signal import Equation
    assert isinstance(eqn, Equation)
    assert len(eqn.outputs) == 1, "JVP requires single-output primitives"

    rule = _JVP_RULES.get(eqn.primitive.name)
    if rule is None:
        raise NotImplementedError(
            f"No JVP rule for primitive {eqn.primitive.name!r}"
        )

    primals_in = tuple(env[s.id] for s in eqn.inputs)
    tangents_in = tuple(tang[s.id] for s in eqn.inputs)

    primal_out, tangent_out = rule(eqn.primitive, primals_in, tangents_in, eqn.params)

    out_id = eqn.outputs[0].id
    env[out_id] = primal_out
    tang[out_id] = tangent_out


def _collect_outputs(
    graph: DspGraph,
    env: dict[int, Signal],
    tang: dict[int, Tangent],
) -> tuple[Signal, ...]:
    primals = tuple(env[s.id] for s in graph.outputs)
    tangents = tuple(materialize(tang[s.id]) for s in graph.outputs)
    return primals + tangents


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def jvp(
    fn_or_graph: Callable[..., Signal | tuple[Signal, ...]] | DspFunc | DspGraph,
    *,
    num_inputs: int | None = None,
    wrt: list[int] | None = None,
    precision: Precision = Precision.FLOAT32,
) -> DspGraph:
    """Compute the forward-mode JVP transform of a DSP function or graph.

    Args:
        fn_or_graph: A Python DSP function or an existing DspGraph.
        num_inputs: Required when fn_or_graph is a callable (if not auto-detectable).
        wrt: Input indices to differentiate w.r.t. Defaults to all inputs.
        precision: Tracing precision (ignored when fn_or_graph is a DspGraph).

    Returns:
        A DspGraph with inputs [primals..., tangent_inputs...] and
        outputs [primals..., tangents...].
    """
    if isinstance(fn_or_graph, DspGraph):
        graph = fn_or_graph
    else:
        from krach.signal.transpile import make_graph
        n = num_inputs if num_inputs is not None else 1
        graph = make_graph(fn_or_graph, num_inputs=n, precision=precision)

    return jvp_graph(graph, wrt=wrt)


# ---------------------------------------------------------------------------
# JVP rules — registered at import time
# ---------------------------------------------------------------------------


def _register_all() -> None:
    from krach.signal.primitives import (
        abs_p, acos_p, add_p, asin_p, atan2_p, atan_p, ceil_p, const_p,
        cos_p, div_p, exp_p, floor_p, fmod_p, gt_p, lt_p,
        log10_p, log_p, max_p, mem_p, min_p, mod_p, mul_p,
        pow_p, remainder_p, round_p, select2_p, sin_p, sqrt_p, sr_p, sub_p, tan_p,
        feedback_p, delay_p,
    )

    # -- const ---------------------------------------------------------------
    def _jvp_const(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        out = prim.bind(params=params)
        return out, ZeroTangent(aval=out.aval)

    register_jvp(const_p, _jvp_const)

    # -- sr ------------------------------------------------------------------
    def _jvp_zero_output(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        out = prim.bind(*primals, params=params)
        return out, ZeroTangent(aval=out.aval)

    register_jvp(sr_p, _jvp_zero_output)

    # -- add -----------------------------------------------------------------
    def _jvp_add(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        return add_p.bind(a, b), tangent_add(da, db)

    register_jvp(add_p, _jvp_add)

    # -- sub -----------------------------------------------------------------
    def _jvp_sub(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        return sub_p.bind(a, b), tangent_add(da, tangent_neg(db))

    register_jvp(sub_p, _jvp_sub)

    # -- mul (product rule) --------------------------------------------------
    def _jvp_mul(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        return mul_p.bind(a, b), tangent_add(tangent_mul(b, da), tangent_mul(a, db))

    register_jvp(mul_p, _jvp_mul)

    # -- div -----------------------------------------------------------------
    def _jvp_div(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        out = div_p.bind(a, b)
        # d(a/b) = (b*da - a*db) / b^2
        num = tangent_add(tangent_mul(b, da), tangent_neg(tangent_mul(a, db)))
        if is_zero(num):
            return out, num
        b_sq = mul_p.bind(b, b)
        assert isinstance(num, Signal)
        return out, div_p.bind(num, b_sq)

    register_jvp(div_p, _jvp_div)

    # -- mod / fmod ----------------------------------------------------------
    def _jvp_mod(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        from krach.signal.primitives import floor_p
        a, b = primals
        da, db = tangents
        out = prim.bind(a, b)
        # d(a mod b) = da - floor(a/b) * db
        floored = floor_p.bind(div_p.bind(a, b))
        t = tangent_add(da, tangent_neg(tangent_mul(floored, db)))
        return out, t

    register_jvp(mod_p, _jvp_mod)
    register_jvp(fmod_p, _jvp_mod)
    register_jvp(remainder_p, _jvp_mod)

    # -- sin -----------------------------------------------------------------
    def _jvp_sin(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = sin_p.bind(x)
        return out, tangent_mul(cos_p.bind(x), dx)

    register_jvp(sin_p, _jvp_sin)

    # -- cos -----------------------------------------------------------------
    def _jvp_cos(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = cos_p.bind(x)
        return out, tangent_neg(tangent_mul(sin_p.bind(x), dx))

    register_jvp(cos_p, _jvp_cos)

    # -- tan -----------------------------------------------------------------
    def _jvp_tan(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = tan_p.bind(x)
        # d(tan x) = dx / cos(x)^2
        cos_x = cos_p.bind(x)
        cos_sq = mul_p.bind(cos_x, cos_x)
        if is_zero(dx):
            return out, dx
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, cos_sq)

    register_jvp(tan_p, _jvp_tan)

    # -- asin ----------------------------------------------------------------
    def _jvp_asin(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = asin_p.bind(x)
        if is_zero(dx):
            return out, dx
        # d(asin x) = dx / sqrt(1 - x^2)
        denom = sqrt_p.bind(sub_p.bind(1.0, mul_p.bind(x, x)))
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, denom)

    register_jvp(asin_p, _jvp_asin)

    # -- acos ----------------------------------------------------------------
    def _jvp_acos(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = acos_p.bind(x)
        if is_zero(dx):
            return out, dx
        # d(acos x) = -dx / sqrt(1 - x^2)
        denom = sqrt_p.bind(sub_p.bind(1.0, mul_p.bind(x, x)))
        assert isinstance(dx, Signal)
        return out, mul_p.bind(div_p.bind(dx, denom), -1.0)

    register_jvp(acos_p, _jvp_acos)

    # -- atan ----------------------------------------------------------------
    def _jvp_atan(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = atan_p.bind(x)
        if is_zero(dx):
            return out, dx
        # d(atan x) = dx / (1 + x^2)
        denom = add_p.bind(1.0, mul_p.bind(x, x))
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, denom)

    register_jvp(atan_p, _jvp_atan)

    # -- atan2 ---------------------------------------------------------------
    def _jvp_atan2(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        y, x = primals
        dy, dx = tangents
        out = atan2_p.bind(y, x)
        # d(atan2(y,x)) = (x*dy - y*dx) / (x^2 + y^2)
        num = tangent_add(tangent_mul(x, dy), tangent_neg(tangent_mul(y, dx)))
        if is_zero(num):
            return out, num
        denom = add_p.bind(mul_p.bind(x, x), mul_p.bind(y, y))
        assert isinstance(num, Signal)
        return out, div_p.bind(num, denom)

    register_jvp(atan2_p, _jvp_atan2)

    # -- exp -----------------------------------------------------------------
    def _jvp_exp(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = exp_p.bind(x)
        return out, tangent_mul(out, dx)

    register_jvp(exp_p, _jvp_exp)

    # -- log -----------------------------------------------------------------
    def _jvp_log(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = log_p.bind(x)
        if is_zero(dx):
            return out, dx
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, x)

    register_jvp(log_p, _jvp_log)

    # -- log10 ---------------------------------------------------------------
    def _jvp_log10(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = log10_p.bind(x)
        if is_zero(dx):
            return out, dx
        # d(log10 x) = dx / (x * ln(10))
        ln10 = const_p.bind(params=ConstParams(value=math.log(10.0)))
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, mul_p.bind(x, ln10))

    register_jvp(log10_p, _jvp_log10)

    # -- sqrt ----------------------------------------------------------------
    def _jvp_sqrt(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = sqrt_p.bind(x)
        if is_zero(dx):
            return out, dx
        # d(sqrt x) = dx / (2 * sqrt(x))
        assert isinstance(dx, Signal)
        return out, div_p.bind(dx, mul_p.bind(2.0, out))

    register_jvp(sqrt_p, _jvp_sqrt)

    # -- abs -----------------------------------------------------------------
    def _jvp_abs(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        (x,) = primals
        (dx,) = tangents
        out = abs_p.bind(x)
        if is_zero(dx):
            return out, dx
        # sign(x): +1 if x>0, -1 if x<0, 0 if x==0
        zero = const_p.bind(params=ConstParams(value=0.0))
        one = const_p.bind(params=ConstParams(value=1.0))
        neg_one = const_p.bind(params=ConstParams(value=-1.0))
        sign = select2_p.bind(gt_p.bind(x, zero), neg_one, one)
        sign = select2_p.bind(lt_p.bind(x, zero), sign, neg_one)
        assert isinstance(dx, Signal)
        return out, mul_p.bind(sign, dx)

    register_jvp(abs_p, _jvp_abs)

    # -- floor, ceil — zero tangent -----------------------------------------
    register_jvp(floor_p, _jvp_zero_output)
    register_jvp(ceil_p, _jvp_zero_output)
    register_jvp(round_p, _jvp_zero_output)

    # -- comparisons — zero tangent -----------------------------------------
    from krach.signal.primitives import COMPARISON_PRIMS
    for _prim in COMPARISON_PRIMS.values():
        register_jvp(_prim, _jvp_zero_output)

    # -- select2 -------------------------------------------------------------
    def _jvp_select2(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        sel, a, b = primals
        _dsel, da, db = tangents
        out = select2_p.bind(sel, a, b)
        t = select2_p.bind(sel, materialize(da), materialize(db))
        return out, t

    register_jvp(select2_p, _jvp_select2)

    # -- min -----------------------------------------------------------------
    def _jvp_min(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        out = min_p.bind(a, b)
        # tangent comes from the smaller operand
        t = select2_p.bind(lt_p.bind(a, b), materialize(db), materialize(da))
        return out, t

    register_jvp(min_p, _jvp_min)

    # -- max -----------------------------------------------------------------
    def _jvp_max(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        out = max_p.bind(a, b)
        # tangent comes from the larger operand
        t = select2_p.bind(gt_p.bind(a, b), materialize(db), materialize(da))
        return out, t

    register_jvp(max_p, _jvp_max)

    # -- pow -----------------------------------------------------------------
    def _jvp_pow(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        a, b = primals
        da, db = tangents
        out = pow_p.bind(a, b)
        # d(a^b) = b*a^(b-1)*da + a^b*log(a)*db
        t1 = tangent_mul(mul_p.bind(b, pow_p.bind(a, sub_p.bind(b, 1.0))), da)
        t2 = tangent_mul(mul_p.bind(out, log_p.bind(a)), db)
        return out, tangent_add(t1, t2)

    register_jvp(pow_p, _jvp_pow)

    # -- stateful / opaque — not differentiable ------------------------------
    def _jvp_not_implemented(
        prim: Primitive,
        primals: tuple[Signal, ...],
        tangents: tuple[Tangent, ...],
        params: PrimitiveParams,
    ) -> tuple[Signal, Tangent]:
        raise NotImplementedError(
            f"Primitive {prim.name!r} is stateful and cannot be differentiated."
        )

    for _prim in (mem_p, delay_p, feedback_p):
        register_jvp(_prim, _jvp_not_implemented)

    # faust_expr — not differentiable
    from krach.signal.primitives import faust_expr_p
    register_jvp(faust_expr_p, _jvp_not_implemented)

    # control — zero tangent (it's a constant from the AD perspective)
    from krach.signal.primitives import control_p
    register_jvp(control_p, _jvp_zero_output)


_register_all()
