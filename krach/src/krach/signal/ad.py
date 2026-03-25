"""Forward-mode automatic differentiation (JVP) for DspGraph.

Usage::

    from krach.signal.ad import jvp

    # Differentiate a single-input graph w.r.t. its input
    jvp_graph = jvp(lambda x: x * x, num_inputs=1)
    # jvp_graph outputs: [primal, tangent]
    # jvp_graph inputs:  [x, dx]
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from krach.ir.primitive import Primitive
from krach.ir.signal import (
    ConstParams,
    DspGraph,
    Precision,
    PrimitiveParams,
    Signal,
    SignalType,
)
from krach.signal.trace import (
    TraceContext,
    bind as _bind,
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
    return _bind(add_p, a, b)


def tangent_mul(primal: Signal, tangent: Tangent) -> Tangent:
    """Multiply a primal signal by a tangent, short-circuiting on zero."""
    if is_zero(tangent):
        return tangent
    from krach.signal.primitives import mul_p
    assert isinstance(tangent, Signal)
    return _bind(mul_p, primal, tangent)


def tangent_neg(t: Tangent) -> Tangent:
    """Negate a tangent, short-circuiting on zero."""
    if is_zero(t):
        return t
    from krach.signal.primitives import mul_p
    assert isinstance(t, Signal)
    return _bind(mul_p, t, -1.0)


def materialize(t: Tangent) -> Signal:
    """Convert a ZeroTangent to const(0.0), or pass through a Signal."""
    if isinstance(t, Signal):
        return t
    from krach.signal.primitives import const_p
    return _bind(const_p, params=ConstParams(value=0.0))


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


# Import ad_rules to register all JVP rules at module load time.
import krach.signal.ad_rules as _ad_rules  # noqa: E402, F401  # pyright: ignore[reportUnusedImport]
