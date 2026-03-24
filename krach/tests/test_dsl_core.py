"""Tests for Commit 1 — Core tracer."""

from __future__ import annotations

from krach.ir.signal import (
    ConstParams,
    FeedbackParams,
    NoParams,
    Signal,
    TraceContext,
    pop_trace,
    push_trace,
)
from krach.dsl.primitives import abs_p, add_p, const_p, feedback_p, mul_p, pow_p
from krach.dsl.core import feedback
from krach.dsl.transpile import make_graph


def _make_ctx() -> TraceContext:
    return TraceContext()


def _with_ctx(ctx: TraceContext) -> object:
    """Context manager for pushing/popping a trace context."""
    class _CM:
        def __enter__(self) -> TraceContext:
            self._token = push_trace(ctx)
            return ctx
        def __exit__(self, *args: object) -> None:
            pop_trace(self._token)
    return _CM()


def test_signal_add_records_equation() -> None:
    ctx = _make_ctx()
    with _with_ctx(ctx):  # type: ignore[union-attr]
        a = ctx.new_input()
        b = ctx.new_input()
        _out = a + b

    assert len(ctx.equations) == 1
    eqn = ctx.equations[0]
    assert eqn.primitive is add_p
    assert eqn.inputs == (a, b)
    assert isinstance(eqn.params, NoParams)


def test_signal_mul_records_equation() -> None:
    ctx = _make_ctx()
    with _with_ctx(ctx):  # type: ignore[union-attr]
        a = ctx.new_input()
        _out = a * 2.0

    # a * 2.0 => const_p(2.0) + mul_p(a, const)
    assert len(ctx.equations) == 2
    # First equation is const_p for 2.0
    assert ctx.equations[0].primitive is const_p
    assert isinstance(ctx.equations[0].params, ConstParams)
    assert ctx.equations[0].params.value == 2.0
    # Second equation is mul_p
    assert ctx.equations[1].primitive is mul_p


def test_signal_pow_records_equation() -> None:
    ctx = _make_ctx()
    with _with_ctx(ctx):  # type: ignore[union-attr]
        a = ctx.new_input()
        _out = a ** 2.0

    # a ** 2.0 => const_p(2.0) + pow_p(a, const)
    assert len(ctx.equations) == 2
    assert ctx.equations[0].primitive is const_p
    assert ctx.equations[1].primitive is pow_p


def test_signal_rpow_records_equation() -> None:
    ctx = _make_ctx()
    with _with_ctx(ctx):  # type: ignore[union-attr]
        a = ctx.new_input()
        _out = 2.0 ** a

    # 2.0 ** a => const_p(2.0) + pow_p(const, a)
    assert len(ctx.equations) == 2
    assert ctx.equations[0].primitive is const_p
    assert ctx.equations[1].primitive is pow_p


def test_signal_abs_records_equation() -> None:
    ctx = _make_ctx()
    with _with_ctx(ctx):  # type: ignore[union-attr]
        a = ctx.new_input()
        _out = abs(a)

    assert len(ctx.equations) == 1
    assert ctx.equations[0].primitive is abs_p


def test_feedback_records_feedback_equation() -> None:
    def dsp() -> Signal:
        return feedback(lambda fb: fb * 0.5)

    graph = make_graph(dsp)

    # The graph should have a feedback_p equation
    fb_eqns = [e for e in graph.equations if e.primitive is feedback_p]
    assert len(fb_eqns) == 1
    assert isinstance(fb_eqns[0].params, FeedbackParams)


def test_make_graph_input_output_counts() -> None:
    def two_in_one_out(a: Signal, b: Signal) -> Signal:
        return a + b

    graph = make_graph(two_in_one_out)
    assert len(graph.inputs) == 2
    assert len(graph.outputs) == 1


def test_nested_ops_form_chain() -> None:
    def dsp(a: Signal, b: Signal, c: Signal) -> Signal:
        return (a + b) * c

    graph = make_graph(dsp)
    # (a + b) * c:
    # eq0: add(a, b) -> t0
    # eq1: mul(t0, c) -> out
    assert len(graph.equations) == 2
    assert graph.equations[0].primitive is add_p
    assert graph.equations[1].primitive is mul_p
    # mul input[0] should be the output of add
    assert graph.equations[1].inputs[0] == graph.equations[0].outputs[0]
