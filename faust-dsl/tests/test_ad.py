"""Tests for ad.py — forward-mode automatic differentiation (JVP)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from faust_dsl import (
    FaustGraph,
    Signal,
    abs_,
    ceil,
    cos,
    exp,
    floor,
    gt,
    log,
    mem,
    sin,
    sqrt,
)
from faust_dsl._core import ConstParams, Precision, SignalType, TraceContext, pop_trace, push_trace
from faust_dsl._dsp import feedback
from faust_dsl.ad import ZeroTangent, is_zero, materialize, tangent_add, tangent_mul, tangent_neg
from faust_dsl.transpile import make_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aval() -> SignalType:
    return SignalType(channels=1, precision=Precision.FLOAT32)


type DspFn1 = Callable[[Signal], Signal]


def _eval_graph(graph: FaustGraph, *input_vals: float) -> list[float]:
    """Numerically evaluate a FaustGraph by walking equations in order."""
    import math as _math

    vals: dict[int, float] = {}
    for sig, val in zip(graph.inputs, input_vals):
        vals[sig.id] = val

    for eqn in graph.equations:
        name = eqn.primitive.name
        in_vals = [vals[s.id] for s in eqn.inputs]

        if name == "const":
            assert isinstance(eqn.params, ConstParams)
            result = eqn.params.value
        elif name == "sr":
            result = 44100.0
        elif name == "add":
            result = in_vals[0] + in_vals[1]
        elif name == "sub":
            result = in_vals[0] - in_vals[1]
        elif name == "mul":
            result = in_vals[0] * in_vals[1]
        elif name == "div":
            result = in_vals[0] / in_vals[1]
        elif name == "mod":
            result = in_vals[0] % in_vals[1]
        elif name == "fmod":
            result = _math.fmod(in_vals[0], in_vals[1])
        elif name == "sin":
            result = _math.sin(in_vals[0])
        elif name == "cos":
            result = _math.cos(in_vals[0])
        elif name == "tan":
            result = _math.tan(in_vals[0])
        elif name == "asin":
            result = _math.asin(in_vals[0])
        elif name == "acos":
            result = _math.acos(in_vals[0])
        elif name == "atan":
            result = _math.atan(in_vals[0])
        elif name == "atan2":
            result = _math.atan2(in_vals[0], in_vals[1])
        elif name == "exp":
            result = _math.exp(in_vals[0])
        elif name == "log":
            result = _math.log(in_vals[0])
        elif name == "log10":
            result = _math.log10(in_vals[0])
        elif name == "sqrt":
            result = _math.sqrt(in_vals[0])
        elif name == "abs":
            result = abs(in_vals[0])
        elif name == "floor":
            result = float(_math.floor(in_vals[0]))
        elif name == "ceil":
            result = float(_math.ceil(in_vals[0]))
        elif name == "pow":
            result = in_vals[0] ** in_vals[1]
        elif name == "min":
            result = min(in_vals[0], in_vals[1])
        elif name == "max":
            result = max(in_vals[0], in_vals[1])
        elif name == "gt":
            result = float(in_vals[0] > in_vals[1])
        elif name == "lt":
            result = float(in_vals[0] < in_vals[1])
        elif name == "ge":
            result = float(in_vals[0] >= in_vals[1])
        elif name == "le":
            result = float(in_vals[0] <= in_vals[1])
        elif name == "eq":
            result = float(in_vals[0] == in_vals[1])
        elif name == "ne":
            result = float(in_vals[0] != in_vals[1])
        elif name == "select2":
            result = in_vals[2] if int(in_vals[0]) else in_vals[1]
        else:
            raise ValueError(f"Unknown primitive in eval: {name!r}")

        vals[eqn.outputs[0].id] = result

    return [vals[s.id] for s in graph.outputs]


def _finite_diff(fn: DspFn1, x: float, dx: float = 1e-5) -> float:
    """Finite difference derivative of a single-input, single-output graph fn."""
    g = make_graph(fn, num_inputs=1)
    f_plus = _eval_graph(g, x + dx)[0]
    f_minus = _eval_graph(g, x - dx)[0]
    return (f_plus - f_minus) / (2 * dx)


def _jvp_deriv(fn: DspFn1, x: float) -> float:
    """Compute derivative via jvp at x (tangent input = 1.0)."""
    from faust_dsl.ad import jvp
    jvp_g = jvp(fn, num_inputs=1)
    # outputs: [primal, tangent]; inputs: [x, dx]
    return _eval_graph(jvp_g, x, 1.0)[1]


def _assert_deriv(fn: DspFn1, x: float, tol: float = 1e-4) -> None:
    expected = _finite_diff(fn, x)
    got = _jvp_deriv(fn, x)
    assert abs(got - expected) < tol, f"deriv mismatch: got {got}, expected {expected}"


# ---------------------------------------------------------------------------
# ZeroTangent
# ---------------------------------------------------------------------------


def test_zero_tangent_carries_aval() -> None:
    aval = _aval()
    z = ZeroTangent(aval=aval)
    assert z.aval is aval


def test_zero_tangent_is_frozen() -> None:
    z = ZeroTangent(aval=_aval())
    with pytest.raises((AttributeError, TypeError)):
        z.aval = _aval()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# is_zero
# ---------------------------------------------------------------------------


def test_is_zero_true_for_zero_tangent() -> None:
    assert is_zero(ZeroTangent(aval=_aval()))


def test_is_zero_false_for_signal() -> None:
    graph = make_graph(lambda x: x, num_inputs=1)  # type: ignore[arg-type]
    assert not is_zero(graph.inputs[0])


# ---------------------------------------------------------------------------
# tangent_add
# ---------------------------------------------------------------------------


def test_tangent_add_zero_plus_zero_is_zero() -> None:
    z = ZeroTangent(aval=_aval())
    assert is_zero(tangent_add(z, z))


def test_tangent_add_zero_plus_signal_is_signal() -> None:
    graph = make_graph(lambda x: x, num_inputs=1)  # type: ignore[arg-type]
    sig = graph.inputs[0]
    assert tangent_add(ZeroTangent(aval=sig.aval), sig) is sig


def test_tangent_add_signal_plus_zero_is_signal() -> None:
    graph = make_graph(lambda x: x, num_inputs=1)  # type: ignore[arg-type]
    sig = graph.inputs[0]
    assert tangent_add(sig, ZeroTangent(aval=sig.aval)) is sig


def test_tangent_add_signal_plus_signal_emits_add_node() -> None:
    from faust_dsl._primitives import add_p

    ctx = TraceContext()
    token = push_trace(ctx)
    try:
        a = ctx.new_input()
        b = ctx.new_input()
        result = tangent_add(a, b)
    finally:
        pop_trace(token)

    assert not is_zero(result)
    assert isinstance(result, Signal)
    assert any(eqn.primitive is add_p and result in eqn.outputs for eqn in ctx.equations)


# ---------------------------------------------------------------------------
# tangent_mul
# ---------------------------------------------------------------------------


def test_tangent_mul_zero_tangent_is_zero() -> None:
    ctx = TraceContext()
    token = push_trace(ctx)
    try:
        primal = ctx.new_input()
        result = tangent_mul(primal, ZeroTangent(aval=primal.aval))
    finally:
        pop_trace(token)

    assert is_zero(result)


def test_tangent_mul_signal_tangent_emits_mul_node() -> None:
    from faust_dsl._primitives import mul_p

    ctx = TraceContext()
    token = push_trace(ctx)
    try:
        primal = ctx.new_input()
        tangent = ctx.new_input()
        result = tangent_mul(primal, tangent)
    finally:
        pop_trace(token)

    assert not is_zero(result)
    assert isinstance(result, Signal)
    assert any(eqn.primitive is mul_p and result in eqn.outputs for eqn in ctx.equations)


# ---------------------------------------------------------------------------
# tangent_neg
# ---------------------------------------------------------------------------


def test_tangent_neg_zero_is_zero() -> None:
    assert is_zero(tangent_neg(ZeroTangent(aval=_aval())))


def test_tangent_neg_signal_emits_neg_node() -> None:
    ctx = TraceContext()
    token = push_trace(ctx)
    try:
        sig = ctx.new_input()
        result = tangent_neg(sig)
    finally:
        pop_trace(token)

    assert not is_zero(result)


# ---------------------------------------------------------------------------
# materialize
# ---------------------------------------------------------------------------


def test_materialize_signal_is_identity() -> None:
    graph = make_graph(lambda x: x, num_inputs=1)  # type: ignore[arg-type]
    sig = graph.inputs[0]
    assert materialize(sig) is sig


def test_materialize_zero_tangent_emits_const_zero() -> None:
    from faust_dsl._primitives import const_p

    ctx = TraceContext()
    token = push_trace(ctx)
    try:
        z = ZeroTangent(aval=_aval())
        result = materialize(z)
    finally:
        pop_trace(token)

    assert not is_zero(result)
    assert any(
        eqn.primitive is const_p
        and isinstance(eqn.params, ConstParams)
        and eqn.params.value == 0.0
        and result in eqn.outputs
        for eqn in ctx.equations
    )


# ---------------------------------------------------------------------------
# jvp — arithmetic
# ---------------------------------------------------------------------------


def _add_const(x: Signal) -> Signal:
    return x + 3.0


def _sub_const(x: Signal) -> Signal:
    return x - 1.5


def _mul_const(x: Signal) -> Signal:
    return x * 4.0


def _div_const(x: Signal) -> Signal:
    return x / 2.0


def _square(x: Signal) -> Signal:
    return x * x


def test_jvp_add() -> None:
    _assert_deriv(_add_const, 2.0)


def test_jvp_sub() -> None:
    _assert_deriv(_sub_const, 2.0)


def test_jvp_mul() -> None:
    _assert_deriv(_mul_const, 2.0)


def test_jvp_div() -> None:
    _assert_deriv(_div_const, 3.0)


def test_jvp_mul_product_rule() -> None:
    _assert_deriv(_square, 3.0)


# ---------------------------------------------------------------------------
# jvp — math intrinsics
# ---------------------------------------------------------------------------


def _dsp_sin(x: Signal) -> Signal:
    return sin(x)


def _dsp_cos(x: Signal) -> Signal:
    return cos(x)


def _dsp_exp(x: Signal) -> Signal:
    return exp(x)


def _dsp_log(x: Signal) -> Signal:
    return log(x)


def _dsp_sqrt(x: Signal) -> Signal:
    return sqrt(x)


def _dsp_abs(x: Signal) -> Signal:
    return abs_(x)


def _dsp_floor(x: Signal) -> Signal:
    return floor(x)


def _dsp_ceil(x: Signal) -> Signal:
    return ceil(x)


def _dsp_gt(x: Signal) -> Signal:
    return gt(x, 1.0)


def test_jvp_sin() -> None:
    _assert_deriv(_dsp_sin, 1.0)


def test_jvp_cos() -> None:
    _assert_deriv(_dsp_cos, 1.0)


def test_jvp_exp() -> None:
    _assert_deriv(_dsp_exp, 1.0)


def test_jvp_log() -> None:
    _assert_deriv(_dsp_log, 2.0)


def test_jvp_sqrt() -> None:
    _assert_deriv(_dsp_sqrt, 4.0)


def test_jvp_abs_positive() -> None:
    _assert_deriv(_dsp_abs, 2.0)


def test_jvp_abs_negative() -> None:
    _assert_deriv(_dsp_abs, -2.0)


def test_jvp_floor_tangent_is_zero() -> None:
    assert _jvp_deriv(_dsp_floor, 2.3) == 0.0


def test_jvp_ceil_tangent_is_zero() -> None:
    assert _jvp_deriv(_dsp_ceil, 2.3) == 0.0


def test_jvp_comparison_tangent_is_zero() -> None:
    assert _jvp_deriv(_dsp_gt, 2.0) == 0.0


# ---------------------------------------------------------------------------
# jvp — wrt parameter
# ---------------------------------------------------------------------------


def test_jvp_wrt_second_input() -> None:
    """d/dy (x + y) at y=3 with x=2 should be 1."""
    from faust_dsl.ad import jvp

    def fn(x: Signal, y: Signal) -> Signal:
        return x + y

    g = jvp(fn, num_inputs=2, wrt=[1])
    # inputs: [x, y, dy]; outputs: [primal, tangent]
    results = _eval_graph(g, 2.0, 3.0, 1.0)
    assert abs(results[1] - 1.0) < 1e-6


def test_jvp_wrt_all_inputs() -> None:
    """jvp with wrt=None computes directional derivative along tangent vector."""
    from faust_dsl.ad import jvp

    def fn(x: Signal, y: Signal) -> Signal:
        return x * y

    g = jvp(fn, num_inputs=2, wrt=None)
    # inputs: [x, y, dx, dy]; outputs: [primal, tangent]
    # tangent = y*dx + x*dy  (product rule)
    # dx=1, dy=0 at x=2,y=3 → tangent = y = 3
    results = _eval_graph(g, 2.0, 3.0, 1.0, 0.0)
    assert abs(results[0] - 6.0) < 1e-6   # primal = 2*3 = 6
    assert abs(results[1] - 3.0) < 1e-6   # tangent = y = 3
    # dx=0, dy=1 at x=2,y=3 → tangent = x = 2
    results2 = _eval_graph(g, 2.0, 3.0, 0.0, 1.0)
    assert abs(results2[1] - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# jvp — stateful ops raise NotImplementedError
# ---------------------------------------------------------------------------


def test_jvp_mem_raises() -> None:
    from faust_dsl.ad import jvp

    def fn(x: Signal) -> Signal:
        return mem(x)

    with pytest.raises(NotImplementedError):
        jvp(fn, num_inputs=1)


def test_jvp_feedback_raises() -> None:
    from faust_dsl.ad import jvp

    def fn(x: Signal) -> Signal:
        return feedback(lambda fb: x + fb)

    with pytest.raises(NotImplementedError):
        jvp(fn, num_inputs=1)


# ---------------------------------------------------------------------------
# jvp — public API accepts FaustGraph directly
# ---------------------------------------------------------------------------


def test_jvp_accepts_faust_graph() -> None:
    from faust_dsl.ad import jvp

    def fn(x: Signal) -> Signal:
        return x * 2.0

    graph = make_graph(fn, num_inputs=1)
    jvp_g = jvp(graph)
    results = _eval_graph(jvp_g, 3.0, 1.0)
    assert abs(results[0] - 6.0) < 1e-6   # primal: 3 * 2 = 6
    assert abs(results[1] - 2.0) < 1e-6   # tangent: d(2x)/dx = 2
