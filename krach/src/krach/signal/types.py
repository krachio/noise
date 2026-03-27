"""Signal IR — pure data types for the DSP computation graph.

Signal, Equation, DspGraph, and typed params. No runtime logic,
no tracing, no threading. Those live in signal/trace.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from krach.ir.primitive import Primitive as Primitive  # re-export

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
    dispatch to bind() via deferred imports from signal/trace.py.

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
        from krach.signal.trace import bind
        from krach.signal.primitives import add_p
        return bind(add_p, self, other)

    def __radd__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import add_p
        return bind(add_p, other, self)

    def __sub__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import sub_p
        return bind(sub_p, self, other)

    def __rsub__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import sub_p
        return bind(sub_p, other, self)

    def __mul__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import mul_p
        return bind(mul_p, self, other)

    def __rmul__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import mul_p
        return bind(mul_p, other, self)

    def __truediv__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import div_p
        return bind(div_p, self, other)

    def __rtruediv__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import div_p
        return bind(div_p, other, self)

    def __mod__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import mod_p
        return bind(mod_p, self, other)

    def __rmod__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import mod_p
        return bind(mod_p, other, self)

    def __pow__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import pow_p
        return bind(pow_p, self, other)

    def __rpow__(self, other: SignalLike) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import pow_p
        return bind(pow_p, other, self)

    def __abs__(self) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import abs_p
        return bind(abs_p, self)

    def __neg__(self) -> Signal:
        from krach.signal.trace import bind
        from krach.signal.primitives import mul_p
        return bind(mul_p, self, -1.0)

    def __gt__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.trace import bind
        from krach.signal.primitives import gt_p
        return bind(gt_p, self, other)

    def __lt__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.trace import bind
        from krach.signal.primitives import lt_p
        return bind(lt_p, self, other)

    def __ge__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.trace import bind
        from krach.signal.primitives import ge_p
        return bind(ge_p, self, other)

    def __le__(self, other: SignalLike) -> Signal:  # type: ignore[override]
        from krach.signal.trace import bind
        from krach.signal.primitives import le_p
        return bind(le_p, self, other)

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
