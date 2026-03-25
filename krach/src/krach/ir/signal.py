"""Foundation types: Signal, Equation, DspGraph, TraceContext, Primitive."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from krach.backends.faust_lowering import FaustLoweringContext

# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


class Precision(Enum):
    """Faust compilation precision: 32-bit or 64-bit floating point."""

    FLOAT32 = "float"
    FLOAT64 = "double"


# ---------------------------------------------------------------------------
# SignalType (abstract value)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalType:
    """Abstract value for signals — tracks channel count and precision."""

    channels: int = 1
    precision: Precision = Precision.FLOAT32


# ---------------------------------------------------------------------------
# Signal — the traced value
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Signal:
    """Proxy object during tracing.

    Represents a signal in the computation graph. Operator overloads
    dispatch to Primitive.bind() via deferred imports.

    Attributes:
        aval: Abstract type information (channels, precision).
        id: Globally unique identifier for this signal.
        owner_id: ID of the TraceContext that created this signal.
    """

    aval: SignalType
    id: int
    owner_id: int

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Signal):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.id)

    def __add__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import add_p
        return add_p.bind(self, other)

    def __radd__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import add_p
        return add_p.bind(other, self)

    def __sub__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import sub_p
        return sub_p.bind(self, other)

    def __rsub__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import sub_p
        return sub_p.bind(other, self)

    def __mul__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import mul_p
        return mul_p.bind(self, other)

    def __rmul__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import mul_p
        return mul_p.bind(other, self)

    def __truediv__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import div_p
        return div_p.bind(self, other)

    def __rtruediv__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import div_p
        return div_p.bind(other, self)

    def __mod__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import mod_p
        return mod_p.bind(self, other)

    def __rmod__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import mod_p
        return mod_p.bind(other, self)

    def __pow__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import pow_p
        return pow_p.bind(self, other)

    def __rpow__(self, other: SignalLike) -> Signal:
        from krach.signal.primitives import pow_p
        return pow_p.bind(other, self)

    def __abs__(self) -> Signal:
        from krach.signal.primitives import abs_p
        return abs_p.bind(self)

    def __neg__(self) -> Signal:
        from krach.signal.primitives import mul_p
        return mul_p.bind(self, -1.0)

    def __gt__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.primitives import gt_p
        return gt_p.bind(self, other)

    def __lt__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.primitives import lt_p
        return lt_p.bind(self, other)

    def __ge__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.primitives import ge_p
        return ge_p.bind(self, other)

    def __le__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.primitives import le_p
        return le_p.bind(self, other)

    def __bool__(self) -> bool:
        raise TypeError(
            "Cannot use a Signal in a Python if/while/and/or. "
            "Use krs.select2() for conditional signal routing."
        )


# ---------------------------------------------------------------------------
# SignalLike — type alias
# ---------------------------------------------------------------------------

type SignalLike = Signal | float | int


# ---------------------------------------------------------------------------
# Typed Params
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoParams:
    """Parameters for primitives that take no configuration."""
    pass


@dataclass(frozen=True, slots=True)
class ConstParams:
    """Parameters for the const primitive."""
    value: float


@dataclass(frozen=True, slots=True)
class DelayParams:
    """Parameters for the delay primitive."""
    pass


@dataclass(frozen=True, slots=True)
class FeedbackParams:
    """Parameters for the feedback primitive (Faust ~)."""
    body_graph: DspGraph
    feedback_input_index: int
    free_var_signals: tuple[Signal, ...]


@dataclass(frozen=True, slots=True)
class FaustExprParams:
    """Parameters for faust_expr — raw Faust code with {0}-style placeholders."""
    template: str


@dataclass(frozen=True, slots=True)
class ControlParams:
    """Parameters for the control primitive — lowers to hslider(...)."""
    name: str
    init: float
    lo: float
    hi: float
    step: float


type PrimitiveParams = (
    NoParams
    | ConstParams
    | DelayParams
    | FeedbackParams
    | FaustExprParams
    | ControlParams
)


# ---------------------------------------------------------------------------
# Equation — one operation in the graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Equation:
    """A single operation in the graph."""
    primitive: Primitive
    inputs: tuple[Signal, ...]
    outputs: tuple[Signal, ...]
    params: PrimitiveParams


# ---------------------------------------------------------------------------
# DspGraph — the IR
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DspGraph:
    """The traced program IR."""
    inputs: tuple[Signal, ...]
    outputs: tuple[Signal, ...]
    equations: tuple[Equation, ...]
    precision: Precision = Precision.FLOAT32

    def __repr__(self) -> str:
        lines: list[str] = []
        in_ids = ", ".join(f"s{s.id}" for s in self.inputs)
        out_ids = ", ".join(f"s{s.id}" for s in self.outputs)
        lines.append(f"{{ lambda ; {in_ids} . let")
        for eqn in self.equations:
            out_names = ", ".join(f"s{s.id}" for s in eqn.outputs)
            in_names = " ".join(f"s{s.id}" for s in eqn.inputs)
            param_str = ""
            if not isinstance(eqn.params, NoParams):
                param_str = f" [{eqn.params}]"
            lines.append(
                f"    {out_names} = {eqn.primitive.name} {in_names}{param_str}"
            )
        lines.append(f"  in ({out_ids}) }}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Callback types for abstract_eval and lowering
# ---------------------------------------------------------------------------

type AbstractEvalRule = Callable[..., SignalType]
type LoweringRule = Callable[[FaustLoweringContext, Equation], str]


# ---------------------------------------------------------------------------
# Primitive — registered operation
# ---------------------------------------------------------------------------


class Primitive:
    """A registered operation in the Signal IR.

    Equality and hashing are structural, based on (name, stateful).
    This is required for DspGraph canonicalization and caching.
    """

    __slots__ = ("name", "stateful", "_abstract_eval", "_lowering_rule")

    def __init__(self, name: str, *, stateful: bool = False) -> None:
        self.name = name
        self.stateful = stateful
        self._abstract_eval: AbstractEvalRule | None = None
        self._lowering_rule: LoweringRule | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Primitive):
            return NotImplemented
        return self.name == other.name and self.stateful == other.stateful

    def __hash__(self) -> int:
        return hash((self.name, self.stateful))

    def def_abstract_eval[F: AbstractEvalRule](self, fn: F) -> F:
        self._abstract_eval = fn
        return fn

    def def_lowering[F: LoweringRule](self, fn: F) -> F:
        self._lowering_rule = fn
        return fn

    def bind(self, *args: SignalLike, params: PrimitiveParams | None = None) -> Signal:
        ctx = current_trace()
        if params is None:
            params = NoParams()

        coerced = tuple(coerce_to_signal(a) for a in args)
        avals = tuple(s.aval for s in coerced)

        if self._abstract_eval is None:
            raise RuntimeError(f"No abstract_eval rule for primitive {self.name!r}")
        out_aval = self._abstract_eval(*avals, params=params)

        out_signal = ctx.new_signal(out_aval)
        eqn = Equation(
            primitive=self,
            inputs=coerced,
            outputs=(out_signal,),
            params=params,
        )
        ctx.record(eqn)
        return out_signal

    def lower(self, ctx: FaustLoweringContext, eqn: Equation) -> str:
        if self._lowering_rule is None:
            raise RuntimeError(f"No lowering rule for primitive {self.name!r}")
        return self._lowering_rule(ctx, eqn)

    def __repr__(self) -> str:
        return f"Primitive({self.name!r})"


# ---------------------------------------------------------------------------
# TraceContext — thread-safe tracing state
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
# Coerce scalars to const Signals
# ---------------------------------------------------------------------------


def coerce_to_signal(val: SignalLike) -> Signal:
    """Convert a scalar to a const signal, or pass through a Signal."""
    if isinstance(val, Signal):
        return val
    from krach.signal.primitives import const_p
    return const_p.bind(params=ConstParams(value=float(val)))
