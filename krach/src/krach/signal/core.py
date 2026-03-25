"""User-facing DSP functions: feedback, mem, delay, math intrinsics, comparisons, select2."""

from __future__ import annotations

from collections.abc import Callable
from typing import overload

from krach.ir.signal import (
    DelayParams,
    Equation,
    FaustExprParams,
    DspGraph,
    FeedbackParams,
    NoParams,
    Signal,
    SignalLike,
)
from krach.signal.trace import (
    TraceContext,
    bind,
    current_trace,
    pop_trace,
    push_trace,
)
from krach.signal.primitives import (
    abs_p,
    acos_p,
    asin_p,
    atan2_p,
    atan_p,
    ceil_p,
    cos_p,
    delay_p,
    eq_p,
    exp_p,
    faust_expr_p,
    feedback_p,
    floor_p,
    fmod_p,
    ge_p,
    gt_p,
    le_p,
    log10_p,
    log_p,
    lt_p,
    max_p,
    mem_p,
    min_p,
    ne_p,
    pow_p,
    remainder_p,
    round_p,
    select2_p,
    sin_p,
    sqrt_p,
    sr_p,
    tan_p,
)

# ---------------------------------------------------------------------------
# sr() — sample rate
# ---------------------------------------------------------------------------


def sr() -> Signal:
    """Sample rate signal (lowers to ma.SR)."""
    return bind(sr_p, params=NoParams())


# ---------------------------------------------------------------------------
# faust_expr() — inline Faust expression escape hatch
# ---------------------------------------------------------------------------


def faust_expr(template: str, *inputs: SignalLike) -> Signal:
    """Inline Faust expression escape hatch.

    Placeholders ``{0}``, ``{1}``, ... are replaced with the corresponding inputs.
    """
    import re
    placeholders = {int(m.group(1)) for m in re.finditer(r"\{(\d+)\}", template)}
    if placeholders and max(placeholders) >= len(inputs):
        raise ValueError(
            f"faust_expr template has placeholder {{{max(placeholders)}}} "
            f"but only {len(inputs)} input(s) provided"
        )
    return bind(faust_expr_p, *inputs, params=FaustExprParams(template=template))


# ---------------------------------------------------------------------------
# mem() — single-sample delay
# ---------------------------------------------------------------------------


def mem(sig: Signal) -> Signal:
    """Single-sample delay (z^-1)."""
    return bind(mem_p, sig, params=NoParams())


# ---------------------------------------------------------------------------
# delay() — variable delay
# ---------------------------------------------------------------------------


def delay(sig: Signal, n: SignalLike) -> Signal:
    """Variable-length delay line."""
    return bind(delay_p, sig, n, params=DelayParams())


# ---------------------------------------------------------------------------
# Unary math intrinsics
# ---------------------------------------------------------------------------


def sin(sig: Signal) -> Signal:
    return bind(sin_p, sig, params=NoParams())


def cos(sig: Signal) -> Signal:
    return bind(cos_p, sig, params=NoParams())


def tan(sig: Signal) -> Signal:
    return bind(tan_p, sig, params=NoParams())


def asin(sig: Signal) -> Signal:
    return bind(asin_p, sig, params=NoParams())


def acos(sig: Signal) -> Signal:
    return bind(acos_p, sig, params=NoParams())


def atan(sig: Signal) -> Signal:
    return bind(atan_p, sig, params=NoParams())


def exp(sig: Signal) -> Signal:
    return bind(exp_p, sig, params=NoParams())


def log(sig: Signal) -> Signal:
    return bind(log_p, sig, params=NoParams())


def log10(sig: Signal) -> Signal:
    return bind(log10_p, sig, params=NoParams())


def sqrt(sig: Signal) -> Signal:
    return bind(sqrt_p, sig, params=NoParams())


def abs_(sig: Signal) -> Signal:
    return bind(abs_p, sig, params=NoParams())


def floor(sig: Signal) -> Signal:
    return bind(floor_p, sig, params=NoParams())


def ceil(sig: Signal) -> Signal:
    return bind(ceil_p, sig, params=NoParams())


def round_(sig: Signal) -> Signal:
    return bind(round_p, sig, params=NoParams())


# ---------------------------------------------------------------------------
# Binary math intrinsics
# ---------------------------------------------------------------------------


def min_(a: SignalLike, b: SignalLike) -> Signal:
    return bind(min_p, a, b, params=NoParams())


def max_(a: SignalLike, b: SignalLike) -> Signal:
    return bind(max_p, a, b, params=NoParams())


def pow_(base: SignalLike, exponent: SignalLike) -> Signal:
    return bind(pow_p, base, exponent, params=NoParams())


def fmod(a: SignalLike, b: SignalLike) -> Signal:
    return bind(fmod_p, a, b, params=NoParams())


def remainder(a: SignalLike, b: SignalLike) -> Signal:
    return bind(remainder_p, a, b, params=NoParams())


def atan2(y: SignalLike, x: SignalLike) -> Signal:
    return bind(atan2_p, y, x, params=NoParams())


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------


def gt(a: SignalLike, b: SignalLike) -> Signal:
    return bind(gt_p, a, b, params=NoParams())


def lt(a: SignalLike, b: SignalLike) -> Signal:
    return bind(lt_p, a, b, params=NoParams())


def ge(a: SignalLike, b: SignalLike) -> Signal:
    return bind(ge_p, a, b, params=NoParams())


def le(a: SignalLike, b: SignalLike) -> Signal:
    return bind(le_p, a, b, params=NoParams())


def eq(a: SignalLike, b: SignalLike) -> Signal:
    return bind(eq_p, a, b, params=NoParams())


def ne(a: SignalLike, b: SignalLike) -> Signal:
    return bind(ne_p, a, b, params=NoParams())


# ---------------------------------------------------------------------------
# select2 — conditional routing
# ---------------------------------------------------------------------------


def select2(
    selector: SignalLike,
    when_zero: SignalLike,
    when_one: SignalLike,
) -> Signal:
    """Two-way conditional signal router."""
    return bind(select2_p, selector, when_zero, when_one, params=NoParams())


# ---------------------------------------------------------------------------
# feedback() — the hard part
# ---------------------------------------------------------------------------


@overload
def feedback(body_fn: Callable[[Signal], tuple[Signal, Signal]]) -> Signal: ...
@overload
def feedback(body_fn: Callable[[Signal], Signal]) -> Signal: ...


def feedback(
    body_fn: Callable[[Signal], tuple[Signal, Signal]] | Callable[[Signal], Signal],
) -> Signal:
    """Create a feedback loop -- Faust's ~ operator."""
    parent_ctx = current_trace()

    child_ctx = TraceContext(precision=parent_ctx.precision)
    fb_signal = child_ctx.new_input()

    token = push_trace(child_ctx)
    try:
        result = body_fn(fb_signal)
    finally:
        pop_trace(token)

    if isinstance(result, Signal):
        output = result
        feedback_value = result
    else:
        output, feedback_value = result

    free_vars = _collect_free_vars(child_ctx)

    remap: dict[int, Signal] = {}
    for parent_sig in free_vars:
        child_input = child_ctx.new_input()
        remap[parent_sig.id] = child_input

    rewritten_eqns = _rewrite_equations(child_ctx.equations, remap)

    if output.id == feedback_value.id:
        body_outputs = (output,)
    else:
        body_outputs = (output, feedback_value)

    body_graph = DspGraph(
        inputs=tuple(child_ctx.inputs),
        outputs=body_outputs,
        equations=tuple(rewritten_eqns),
        precision=parent_ctx.precision,
    )

    params = FeedbackParams(
        body_graph=body_graph,
        feedback_input_index=0,
        free_var_signals=tuple(free_vars),
    )
    result_sig = parent_ctx.new_signal(output.aval)
    parent_ctx.record(
        Equation(
            primitive=feedback_p,
            inputs=tuple(free_vars),
            outputs=(result_sig,),
            params=params,
        )
    )
    return result_sig


# ---------------------------------------------------------------------------
# Free variable detection
# ---------------------------------------------------------------------------


def _collect_free_vars(child_ctx: TraceContext) -> tuple[Signal, ...]:
    defined: set[int] = {s.id for s in child_ctx.inputs}
    for eqn in child_ctx.equations:
        for o in eqn.outputs:
            defined.add(o.id)

    free: dict[int, Signal] = {}
    for eqn in child_ctx.equations:
        for s in eqn.inputs:
            if s.id not in defined and s.id not in free:
                free[s.id] = s
    return tuple(free.values())


# ---------------------------------------------------------------------------
# Equation rewriting
# ---------------------------------------------------------------------------


def _rewrite_signal(sig: Signal, remap: dict[int, Signal]) -> Signal:
    return remap.get(sig.id, sig)


def _rewrite_equations(
    equations: list[Equation], remap: dict[int, Signal]
) -> list[Equation]:
    if not remap:
        return equations
    result: list[Equation] = []
    for eqn in equations:
        new_inputs = tuple(_rewrite_signal(s, remap) for s in eqn.inputs)
        if new_inputs != eqn.inputs:
            result.append(
                Equation(
                    primitive=eqn.primitive,
                    inputs=new_inputs,
                    outputs=eqn.outputs,
                    params=eqn.params,
                )
            )
        else:
            result.append(eqn)
    return result


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

sample_rate = sr
unit_delay = mem
