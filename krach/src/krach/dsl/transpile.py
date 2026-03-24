"""transpile() entry point, TranspiledDsp, ControlSchema, control()."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from krach.backends.faust_codegen import emit_faust
from krach.ir.signal import (
    ControlParams,
    DspGraph,
    Precision,
    Signal,
    TraceContext,
    pop_trace,
    push_trace,
)
from krach.dsl.primitives import control_p
from krach.dsl.compose import DspFunc, get_num_inputs

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlSpec:
    """Describes one control parameter exposed by a DSP function."""
    name: str
    init: float
    lo: float
    hi: float
    step: float


@dataclass(frozen=True)
class ControlSchema:
    """All control() calls found during tracing."""
    controls: tuple[ControlSpec, ...]


@dataclass(frozen=True)
class TranspiledDsp:
    """Result of transpile()."""
    source: str
    schema: ControlSchema
    num_inputs: int
    num_outputs: int


# ---------------------------------------------------------------------------
# control() — new primitive
# ---------------------------------------------------------------------------


def control(
    name: str,
    init: float,
    lo: float,
    hi: float,
    step: float = 0.001,
) -> Signal:
    """Create a control parameter that lowers to hslider(...).

    Args:
        name: Parameter name (used in hslider and ControlSchema).
        init: Default value.
        lo: Minimum value.
        hi: Maximum value.
        step: Step size (default 0.001).

    Returns:
        A Signal representing the control input.
    """
    return control_p.bind(params=ControlParams(name=name, init=init, lo=lo, hi=hi, step=step))


# ---------------------------------------------------------------------------
# make_graph — trace a Python DSP function into a DspGraph
# ---------------------------------------------------------------------------


def make_graph(
    fn: Callable[..., Signal | tuple[Signal, ...]] | DspFunc,
    *,
    num_inputs: int | None = None,
    precision: Precision = Precision.FLOAT32,
) -> DspGraph:
    """Trace a Python DSP function into a DspGraph."""
    if num_inputs is None:
        num_inputs = get_num_inputs(fn)

    ctx = TraceContext(precision=precision)
    inputs = [ctx.new_input() for _ in range(num_inputs)]

    from krach.ir.signal import coerce_to_signal as _coerce

    token = push_trace(ctx)
    try:
        raw = fn(*inputs)
        if isinstance(raw, (float, int)):
            result: Signal | tuple[Signal, ...] = _coerce(raw)
        else:
            result = raw
    finally:
        pop_trace(token)

    if isinstance(result, Signal):
        outputs = (result,)
    else:
        outputs = tuple(result)

    return ctx.to_graph(outputs)


# ---------------------------------------------------------------------------
# _collect_controls — scan graph for control_p equations
# ---------------------------------------------------------------------------


def _collect_controls(graph: DspGraph) -> tuple[ControlSpec, ...]:
    """Walk equations and collect all control_p params."""
    specs: list[ControlSpec] = []
    _collect_controls_recursive(graph, specs)
    return tuple(specs)


def _collect_controls_recursive(graph: DspGraph, specs: list[ControlSpec]) -> None:
    from krach.ir.signal import FeedbackParams
    for eqn in graph.equations:
        if isinstance(eqn.params, ControlParams):
            specs.append(ControlSpec(
                name=eqn.params.name,
                init=eqn.params.init,
                lo=eqn.params.lo,
                hi=eqn.params.hi,
                step=eqn.params.step,
            ))
        elif isinstance(eqn.params, FeedbackParams):
            _collect_controls_recursive(eqn.params.body_graph, specs)


# ---------------------------------------------------------------------------
# transpile() — main entry point
# ---------------------------------------------------------------------------


def transpile(
    fn: Callable[..., Signal | tuple[Signal, ...]] | DspFunc,
    *,
    num_inputs: int | None = None,
    precision: Precision = Precision.FLOAT32,
    optimize: bool = False,
) -> TranspiledDsp:
    """Transpile a Python DSP function to Faust source code.

    Args:
        fn: A DSP function accepting Signal arguments, returning one or more Signals.
        num_inputs: Number of audio inputs. If None, auto-detected from fn's signature.
        precision: Floating-point precision (default FLOAT32).
        optimize: If True, run optimization passes before code generation.

    Returns:
        A TranspiledDsp with source code, control schema, and I/O counts.

    Example::

        from krach.dsl import transpile, control
        from krach.dsl.lib import sine_osc

        def synth() -> Signal:
            freq = control("freq", init=440.0, lo=20.0, hi=20000.0)
            return sine_osc(freq)

        result = transpile(synth)
        # result.source contains the .dsp string
        # result.schema.controls[0].name == "freq"
    """
    graph = make_graph(fn, num_inputs=num_inputs, precision=precision)
    source = emit_faust(graph, optimize=optimize)
    controls = _collect_controls(graph)
    schema = ControlSchema(controls=controls)

    return TranspiledDsp(
        source=source,
        schema=schema,
        num_inputs=len(graph.inputs),
        num_outputs=len(graph.outputs),
    )
