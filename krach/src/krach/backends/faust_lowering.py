"""Lowering rules: DspGraph equations -> Faust expression strings."""

from __future__ import annotations

import math
import re

from krach.ir.signal import (
    ConstParams,
    ControlParams,
    DelayParams,
    Equation,
    FaustExprParams,
    FeedbackParams,
    Signal,
)
from krach.signal.trace import lowering
from krach.signal.primitives import (
    BINARY_MATH_PRIMS,
    COMPARISON_PRIMS,
    UNARY_MATH_PRIMS,
    add_p,
    const_p,
    control_p,
    delay_p,
    div_p,
    faust_expr_p,
    feedback_p,
    mem_p,
    mod_p,
    mul_p,
    select2_p,
    sr_p,
    sub_p,
)

# ---------------------------------------------------------------------------
# FaustLoweringContext — maps Signals to Faust expression strings
# ---------------------------------------------------------------------------


class FaustLoweringContext:
    """Accumulates Faust expression bindings during lowering."""

    __slots__ = ("_bindings", "with_defs", "body_counter")

    def __init__(self) -> None:
        self._bindings: dict[int, str] = {}
        self.with_defs: list[str] = []
        self.body_counter: int = 0

    def bind(self, sig: Signal, expr: str) -> None:
        self._bindings[sig.id] = expr

    def expr(self, sig: Signal) -> str:
        if sig.id not in self._bindings:
            raise KeyError(f"Signal s{sig.id} has no binding in lowering context")
        return self._bindings[sig.id]

    def fresh_body_name(self) -> str:
        name = f"body_{self.body_counter}"
        self.body_counter += 1
        return name


# ---------------------------------------------------------------------------
# Arithmetic lowering rules
# ---------------------------------------------------------------------------


def _make_infix_lower(op: str):  # noqa: ANN202
    def _lower(ctx: FaustLoweringContext, eqn: Equation) -> str:
        a, b = eqn.inputs
        return f"({ctx.expr(a)} {op} {ctx.expr(b)})"
    return _lower


lowering.register(add_p, _make_infix_lower("+"))
lowering.register(sub_p, _make_infix_lower("-"))
lowering.register(mul_p, _make_infix_lower("*"))
lowering.register(div_p, _make_infix_lower("/"))
lowering.register(mod_p, _make_infix_lower("%"))


def _lower_const(_ctx: FaustLoweringContext, eqn: Equation) -> str:
    if not isinstance(eqn.params, ConstParams):
        raise TypeError(f"Expected ConstParams, got {type(eqn.params).__name__}")
    v = eqn.params.value
    if math.isfinite(v) and v == int(v):
        return str(int(v))
    return str(v)


lowering.register(const_p, _lower_const)


def _lower_mem(ctx: FaustLoweringContext, eqn: Equation) -> str:
    (a,) = eqn.inputs
    return f"{ctx.expr(a)}'"


lowering.register(mem_p, _lower_mem)


def _lower_delay(ctx: FaustLoweringContext, eqn: Equation) -> str:
    if not isinstance(eqn.params, DelayParams):
        raise TypeError(f"Expected DelayParams, got {type(eqn.params).__name__}")
    sig, n = eqn.inputs
    return f"({ctx.expr(sig)}@{ctx.expr(n)})"


lowering.register(delay_p, _lower_delay)


# ---------------------------------------------------------------------------
# Unary math lowering
# ---------------------------------------------------------------------------


def _make_unary_lower(name: str):  # noqa: ANN202
    def _lower(ctx: FaustLoweringContext, eqn: Equation) -> str:
        (a,) = eqn.inputs
        return f"{name}({ctx.expr(a)})"
    return _lower


for _name, _prim in UNARY_MATH_PRIMS.items():
    lowering.register(_prim, _make_unary_lower(_name))


# ---------------------------------------------------------------------------
# Binary math lowering
# ---------------------------------------------------------------------------


def _make_binary_func_lower(name: str):  # noqa: ANN202
    def _lower(ctx: FaustLoweringContext, eqn: Equation) -> str:
        a, b = eqn.inputs
        return f"{name}({ctx.expr(a)}, {ctx.expr(b)})"
    return _lower


for _name, _prim in BINARY_MATH_PRIMS.items():
    lowering.register(_prim, _make_binary_func_lower(_name))


# ---------------------------------------------------------------------------
# Comparison lowering
# ---------------------------------------------------------------------------

_COMPARISON_OPS = {
    "gt": ">",
    "lt": "<",
    "ge": ">=",
    "le": "<=",
    "eq": "==",
    "ne": "!=",
}

for _name, _prim in COMPARISON_PRIMS.items():
    lowering.register(_prim, _make_infix_lower(_COMPARISON_OPS[_name]))


# ---------------------------------------------------------------------------
# select2 lowering
# ---------------------------------------------------------------------------


def _lower_select2(ctx: FaustLoweringContext, eqn: Equation) -> str:
    sel, a, b = eqn.inputs
    return f"select2({ctx.expr(sel)}, {ctx.expr(a)}, {ctx.expr(b)})"


lowering.register(select2_p, _lower_select2)


# ---------------------------------------------------------------------------
# Feedback lowering
# ---------------------------------------------------------------------------


def _lower_feedback(ctx: FaustLoweringContext, eqn: Equation) -> str:
    if not isinstance(eqn.params, FeedbackParams):
        raise TypeError(f"Expected FeedbackParams, got {type(eqn.params).__name__}")
    body_graph = eqn.params.body_graph
    free_vars = eqn.params.free_var_signals

    body_name = ctx.fresh_body_name()
    body_id = body_name.removeprefix("body_")

    body_ctx = FaustLoweringContext()
    body_ctx.body_counter = ctx.body_counter

    fb_param = f"fb{body_id}"
    fv_params = [f"fv{body_id}_{i}" for i in range(len(free_vars))]

    for inp, pname in zip(body_graph.inputs, [fb_param, *fv_params], strict=True):
        body_ctx.bind(inp, pname)

    for body_eqn in body_graph.equations:
        rule = lowering.lookup(body_eqn.primitive)
        expr = rule(body_ctx, body_eqn)
        body_ctx.bind(body_eqn.outputs[0], expr)

    ctx.body_counter = body_ctx.body_counter

    body_output_exprs = [body_ctx.expr(o) for o in body_graph.outputs]

    all_params = ", ".join([fb_param, *fv_params])
    body_expr = ", ".join(body_output_exprs)

    body_with_inner = body_ctx.with_defs
    if body_with_inner:
        inner_with = (
            "\n    with {\n"
            + "\n".join(f"        {d}" for d in body_with_inner)
            + "\n    }"
        )
        body_def = f"{body_name}({all_params}) = {body_expr}{inner_with};"
    else:
        body_def = f"{body_name}({all_params}) = {body_expr};"

    ctx.with_defs.append(body_def)

    fv_args = ", ".join(ctx.expr(fv) for fv in free_vars)
    call_args = f"_, {fv_args}" if fv_args else "_"

    simple_feedback = len(body_graph.outputs) == 1

    if simple_feedback:
        return f"(({body_name}({call_args})) ~ _)"
    else:
        return f"(({body_name}({call_args})) ~ _ : (!, _))"


lowering.register(feedback_p, _lower_feedback)


# ---------------------------------------------------------------------------
# sr lowering
# ---------------------------------------------------------------------------


def _lower_sr(_ctx: FaustLoweringContext, _eqn: Equation) -> str:
    return "ma.SR"


lowering.register(sr_p, _lower_sr)


# ---------------------------------------------------------------------------
# faust_expr lowering
# ---------------------------------------------------------------------------


def _lower_faust_expr(ctx: FaustLoweringContext, eqn: Equation) -> str:
    if not isinstance(eqn.params, FaustExprParams):
        raise TypeError(f"Expected FaustExprParams, got {type(eqn.params).__name__}")
    template = eqn.params.template
    inputs = eqn.inputs

    def _replace(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return ctx.expr(inputs[idx])

    return re.sub(r"\{(\d+)\}", _replace, template)


lowering.register(faust_expr_p, _lower_faust_expr)


# ---------------------------------------------------------------------------
# control lowering — hslider
# ---------------------------------------------------------------------------


_GATE_NAMES = ("gate", "trig", "trigger")


def _lower_control(_ctx: FaustLoweringContext, eqn: Equation) -> str:
    if not isinstance(eqn.params, ControlParams):
        raise TypeError(f"Expected ControlParams, got {type(eqn.params).__name__}")
    p = eqn.params
    hslider = f'hslider("{p.name}", {p.init}, {p.lo}, {p.hi}, {p.step})'
    if any(g in p.name.lower() for g in _GATE_NAMES):
        return hslider
    return f"({hslider} : si.smoo)"


lowering.register(control_p, _lower_control)
