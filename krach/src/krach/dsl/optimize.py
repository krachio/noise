"""Graph optimization passes: constant folding, CSE, DCE."""

from __future__ import annotations

import math
import operator
from collections.abc import Callable

from krach.ir.signal import (
    ConstParams,
    Equation,
    DspGraph,
    PrimitiveParams,
    Signal,
)
from krach.dsl.primitives import const_p

# ---------------------------------------------------------------------------
# Constant folding
# ---------------------------------------------------------------------------

_FOLDABLE_OPS: dict[str, Callable[..., float]] = {
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.truediv,
    "mod": operator.mod,
    "min": min,
    "max": max,
    "pow": operator.pow,
    "round": round,
    "remainder": math.remainder,
    "fmod": math.fmod,
}


def constant_fold(graph: DspGraph) -> DspGraph:
    """Fold equations whose inputs are all constants into a single const equation."""
    const_values: dict[int, float] = {}
    new_equations: list[Equation] = []

    for eqn in graph.equations:
        if eqn.primitive is const_p and isinstance(eqn.params, ConstParams):
            const_values[eqn.outputs[0].id] = eqn.params.value
            new_equations.append(eqn)
            continue

        op_fn = _FOLDABLE_OPS.get(eqn.primitive.name)
        if op_fn is not None and len(eqn.inputs) >= 2:
            input_vals = [const_values.get(s.id) for s in eqn.inputs]
            if all(v is not None for v in input_vals):
                try:
                    result = op_fn(*input_vals)  # type: ignore[arg-type]
                    if not math.isfinite(result):
                        new_equations.append(eqn)
                        continue
                    new_eqn = Equation(
                        primitive=const_p,
                        inputs=(),
                        outputs=eqn.outputs,
                        params=ConstParams(value=float(result)),
                    )
                    const_values[eqn.outputs[0].id] = float(result)
                    new_equations.append(new_eqn)
                    continue
                except (ZeroDivisionError, ValueError, OverflowError):
                    pass

        new_equations.append(eqn)

    return DspGraph(
        inputs=graph.inputs,
        outputs=graph.outputs,
        equations=tuple(new_equations),
        precision=graph.precision,
    )


# ---------------------------------------------------------------------------
# Common Subexpression Elimination
# ---------------------------------------------------------------------------


def common_subexpression_elimination(graph: DspGraph) -> DspGraph:
    """Deduplicate equations with identical (primitive, inputs, params) tuples."""
    seen: dict[tuple[str, tuple[int, ...], PrimitiveParams], Signal] = {}
    remap: dict[int, Signal] = {}
    new_equations: list[Equation] = []

    for eqn in graph.equations:
        if eqn.primitive.stateful:
            new_equations.append(eqn)
            continue

        remapped_inputs = tuple(remap.get(s.id, s) for s in eqn.inputs)

        key = (
            eqn.primitive.name,
            tuple(s.id for s in remapped_inputs),
            eqn.params,
        )

        if key in seen:
            remap[eqn.outputs[0].id] = seen[key]
        else:
            if remapped_inputs != eqn.inputs:
                new_eqn = Equation(
                    primitive=eqn.primitive,
                    inputs=remapped_inputs,
                    outputs=eqn.outputs,
                    params=eqn.params,
                )
                new_equations.append(new_eqn)
            else:
                new_equations.append(eqn)
            seen[key] = eqn.outputs[0]

    new_outputs = tuple(remap.get(s.id, s) for s in graph.outputs)

    return DspGraph(
        inputs=graph.inputs,
        outputs=new_outputs,
        equations=tuple(new_equations),
        precision=graph.precision,
    )


# ---------------------------------------------------------------------------
# Dead Code Elimination
# ---------------------------------------------------------------------------


def dead_code_elimination(graph: DspGraph) -> DspGraph:
    """Remove equations whose outputs are not reachable from the graph outputs."""
    live: set[int] = set()
    for s in graph.outputs:
        live.add(s.id)

    for eqn in reversed(graph.equations):
        if any(s.id in live for s in eqn.outputs):
            for s in eqn.inputs:
                live.add(s.id)

    new_equations = [
        eqn for eqn in graph.equations if any(s.id in live for s in eqn.outputs)
    ]

    return DspGraph(
        inputs=graph.inputs,
        outputs=graph.outputs,
        equations=tuple(new_equations),
        precision=graph.precision,
    )


# ---------------------------------------------------------------------------
# Full optimization pipeline
# ---------------------------------------------------------------------------


def optimize_graph(graph: DspGraph, *, max_iterations: int = 3) -> DspGraph:
    """Run the full optimization pipeline: constant folding, CSE, then DCE."""
    for _ in range(max_iterations):
        prev = graph
        graph = constant_fold(graph)
        graph = common_subexpression_elimination(graph)
        graph = dead_code_elimination(graph)
        if graph.equations == prev.equations and graph.outputs == prev.outputs:
            break
    return graph
