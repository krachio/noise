"""faust_dsl — Python DSL for writing DSP signal graphs that compile to Faust .dsp source."""

from __future__ import annotations

from faust_dsl._core import (
    DspGraph,
    Precision,
    Signal,
    SignalLike,
    SignalType,
    TraceContext,
    pop_trace,
    push_trace,
)
from faust_dsl._dsp import (
    abs_,
    acos,
    asin,
    atan,
    atan2,
    ceil,
    cos,
    delay,
    eq,
    exp,
    faust_expr,
    feedback,
    floor,
    fmod,
    ge,
    gt,
    le,
    log,
    log10,
    lt,
    max_,
    mem,
    min_,
    ne,
    pow_,
    remainder,
    round_,
    sample_rate,
    select2,
    sin,
    sqrt,
    sr,
    tan,
    unit_delay,
)
from faust_dsl._codegen import emit_faust
from faust_dsl.ad import ZeroTangent, jvp, register_jvp
from faust_dsl._optimize import optimize_graph
from faust_dsl.compose import DspFunc, bus, chain, merge, parallel, route, split
from faust_dsl.transpile import (
    ControlSchema,
    ControlSpec,
    TranspiledDsp,
    control,
    make_graph,
    transpile,
)

__all__ = [
    # Core types
    "DspFunc",
    "DspGraph",
    "Precision",
    "Signal",
    "SignalLike",
    "SignalType",
    # Entry points
    "control",
    "emit_faust",
    "make_graph",
    "transpile",
    # Output types
    "ControlSchema",
    "ControlSpec",
    "TranspiledDsp",
    # DSP primitives
    "delay",
    "faust_expr",
    "feedback",
    "mem",
    "sr",
    # Math intrinsics (unary)
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "exp",
    "log",
    "log10",
    "sqrt",
    "abs_",
    "floor",
    "ceil",
    # Math intrinsics (binary)
    "min_",
    "max_",
    "pow_",
    "fmod",
    "remainder",
    "atan2",
    "round_",
    # Comparison
    "gt",
    "lt",
    "ge",
    "le",
    "eq",
    "ne",
    # Conditional
    "select2",
    # Automatic differentiation
    "ZeroTangent",
    "jvp",
    "register_jvp",
    # Optimization
    "optimize_graph",
    # Composition
    "split",
    "merge",
    "bus",
    "chain",
    "parallel",
    "route",
    # Aliases
    "sample_rate",
    "unit_delay",
    # Internals exposed for advanced use
    "TraceContext",
    "pop_trace",
    "push_trace",
]
