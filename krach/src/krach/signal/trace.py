"""TraceContext and bind() — the signal tracing runtime.

This module owns all tracing state: the thread-local trace stack,
signal ID allocation, and the bind() function that records equations.
ir/ is pure data — this is where it comes alive.
"""

from __future__ import annotations

import threading

from krach.ir.primitive import Primitive
from krach.ir.registry import RuleRegistry
from krach.ir.signal import (
    ConstParams,
    DspGraph,
    Equation,
    NoParams,
    Precision,
    PrimitiveParams,
    Signal,
    SignalLike,
    SignalType,
)

# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from krach.backends.faust import FaustLoweringContext

type AbstractEvalRule = Callable[..., SignalType]
type LoweringRule = Callable[[FaustLoweringContext, Equation], str]

# ---------------------------------------------------------------------------
# Rule registries — one instance each for abstract_eval and lowering
# ---------------------------------------------------------------------------

abstract_eval: RuleRegistry[Primitive, AbstractEvalRule] = RuleRegistry("abstract_eval")
lowering: RuleRegistry[Primitive, LoweringRule] = RuleRegistry("lowering")

# ---------------------------------------------------------------------------
# Thread-safe ID allocation
# ---------------------------------------------------------------------------

_local = threading.local()
_next_ctx_id = 0
_next_signal_id = 0
_id_lock = threading.Lock()


def _get_next_ctx_id() -> int:
    global _next_ctx_id
    with _id_lock:
        cid = _next_ctx_id
        _next_ctx_id += 1
    return cid


def _get_next_signal_id() -> int:
    global _next_signal_id
    with _id_lock:
        sid = _next_signal_id
        _next_signal_id += 1
    return sid


# ---------------------------------------------------------------------------
# TraceContext
# ---------------------------------------------------------------------------


class TraceContext:
    """Manages tracing state for one make_graph or feedback invocation."""

    __slots__ = ("ctx_id", "precision", "inputs", "equations")

    def __init__(self, precision: Precision = Precision.FLOAT32) -> None:
        self.ctx_id = _get_next_ctx_id()
        self.precision = precision
        self.inputs: list[Signal] = []
        self.equations: list[Equation] = []

    def new_signal(self, aval: SignalType | None = None) -> Signal:
        if aval is None:
            aval = SignalType(precision=self.precision)
        return Signal(aval=aval, id=_get_next_signal_id(), owner_id=self.ctx_id)

    def new_input(self, aval: SignalType | None = None) -> Signal:
        sig = self.new_signal(aval)
        self.inputs.append(sig)
        return sig

    def record(self, eqn: Equation) -> None:
        self.equations.append(eqn)

    def to_graph(self, outputs: tuple[Signal, ...]) -> DspGraph:
        return DspGraph(
            inputs=tuple(self.inputs),
            outputs=outputs,
            equations=tuple(self.equations),
            precision=self.precision,
        )


# ---------------------------------------------------------------------------
# Trace stack management (thread-safe)
# ---------------------------------------------------------------------------


class TraceStackToken:
    """Opaque token returned by push_trace."""
    __slots__ = ("prev",)

    def __init__(self, prev: list[TraceContext]) -> None:
        self.prev = prev


def _trace_stack() -> list[TraceContext]:
    stack: list[TraceContext] | None = getattr(_local, "trace_stack", None)
    if stack is None:
        stack = []
        _local.trace_stack = stack
    return stack


def active_precision() -> Precision:
    """Return the precision of the active TraceContext, or FLOAT32 if none active."""
    stack = _trace_stack()
    if stack:
        return stack[-1].precision
    return Precision.FLOAT32


def current_trace() -> TraceContext:
    """Return the active TraceContext."""
    stack = _trace_stack()
    if not stack:
        raise RuntimeError("No active TraceContext. Are you inside transpile()?")
    return stack[-1]


def push_trace(ctx: TraceContext) -> TraceStackToken:
    """Push a TraceContext onto the thread-local stack."""
    stack = _trace_stack()
    token = TraceStackToken(list(stack))
    stack.append(ctx)
    return token


def pop_trace(token: TraceStackToken) -> None:
    """Restore the trace stack to the state captured in token."""
    _local.trace_stack = token.prev


# ---------------------------------------------------------------------------
# coerce_to_signal
# ---------------------------------------------------------------------------


def coerce_to_signal(val: SignalLike) -> Signal:
    """Convert a scalar to a const signal, or pass through a Signal."""
    if isinstance(val, Signal):
        return val
    from krach.signal.primitives import const_p
    return bind(const_p, params=ConstParams(value=float(val)))


# ---------------------------------------------------------------------------
# bind — the core tracing operation
# ---------------------------------------------------------------------------


def bind(
    primitive: Primitive,
    *args: SignalLike,
    params: PrimitiveParams | None = None,
) -> Signal:
    """Record a primitive application in the current trace context."""
    ctx = current_trace()
    if params is None:
        params = NoParams()

    coerced = tuple(coerce_to_signal(a) for a in args)
    avals = tuple(s.aval for s in coerced)

    rule = abstract_eval.lookup(primitive)
    out_aval = rule(*avals, params=params)

    out_signal = ctx.new_signal(out_aval)
    eqn = Equation(
        primitive=primitive,
        inputs=coerced,
        outputs=(out_signal,),
        params=params,
    )
    ctx.record(eqn)
    return out_signal
