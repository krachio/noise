"""DspGraph canonicalization — alpha-rename Signal IDs to sequential integers.

Two traces of the same function produce DspGraphs with different Signal IDs
(auto-incrementing counters). Canonicalization renumbers them sequentially
in walk order, making structurally identical graphs hash identically.

This is the krach equivalent of JAX's jaxpr canonicalization.
"""

from __future__ import annotations

from typing import Callable

from krach.ir.signal import (
    ConstParams,
    ControlParams,
    DelayParams,
    DspGraph,
    Equation,
    FaustExprParams,
    FeedbackParams,
    NoParams,
    PrimitiveParams,
    Signal,
)


def canonicalize(graph: DspGraph) -> DspGraph:
    """Renumber all Signal IDs sequentially starting from 0.

    Walk order: inputs first, then equations (inputs before outputs per equation).
    Structurally identical graphs get identical canonical forms regardless of
    original trace-time IDs. Recurses into FeedbackParams.body_graph.
    """
    remap: dict[int, int] = {}
    counter = 0

    def assign(sig: Signal) -> Signal:
        nonlocal counter
        if sig.id not in remap:
            remap[sig.id] = counter
            counter += 1
        return Signal(aval=sig.aval, id=remap[sig.id], owner_id=0)

    new_inputs = tuple(assign(s) for s in graph.inputs)

    new_eqns: list[Equation] = []
    for eqn in graph.equations:
        new_in = tuple(assign(s) for s in eqn.inputs)
        new_out = tuple(assign(s) for s in eqn.outputs)
        new_params = _canonicalize_params(eqn.params, assign)
        new_eqns.append(Equation(
            primitive=eqn.primitive,
            inputs=new_in,
            outputs=new_out,
            params=new_params,
        ))

    new_outputs = tuple(assign(s) for s in graph.outputs)

    return DspGraph(
        inputs=new_inputs,
        outputs=new_outputs,
        equations=tuple(new_eqns),
        precision=graph.precision,
    )


def _canonicalize_params(
    params: PrimitiveParams,
    parent_assign: Callable[[Signal], Signal],
) -> PrimitiveParams:
    """Canonicalize params. Only FeedbackParams has nested state."""
    match params:
        case FeedbackParams(body_graph=bg, feedback_input_index=idx, free_var_signals=fvs):
            canon_bg = canonicalize(bg)
            canon_fvs = tuple(parent_assign(s) for s in fvs)
            return FeedbackParams(
                body_graph=canon_bg,
                feedback_input_index=idx,
                free_var_signals=canon_fvs,
            )
        case _:
            return params


def graph_key(graph: DspGraph) -> int:
    """Structural hash of a DspGraph, invariant to Signal ID numbering."""
    canon = canonicalize(graph)
    return hash(_structural_key(canon))


def _structural_key(graph: DspGraph) -> tuple[object, ...]:
    """Hashable structural encoding of a canonicalized graph."""
    return (
        tuple((s.id, s.aval.channels, s.aval.precision) for s in graph.inputs),
        tuple((s.id, s.aval.channels, s.aval.precision) for s in graph.outputs),
        tuple(_eqn_key(e) for e in graph.equations),
        graph.precision,
    )


def _eqn_key(eqn: Equation) -> tuple[object, ...]:
    """Hashable encoding of one equation."""
    return (
        eqn.primitive.name,
        eqn.primitive.stateful,
        tuple(s.id for s in eqn.inputs),
        tuple(s.id for s in eqn.outputs),
        _params_key(eqn.params),
    )


def _params_key(params: PrimitiveParams) -> tuple[object, ...]:
    """Hashable encoding of primitive params."""
    match params:
        case NoParams():
            return ("no",)
        case ConstParams(value=v):
            return ("const", v)
        case DelayParams():
            return ("delay",)
        case ControlParams(name=n, init=i, lo=lo, hi=hi, step=s):
            return ("control", n, i, lo, hi, s)
        case FaustExprParams(template=t):
            return ("faust_expr", t)
        case FeedbackParams(body_graph=bg, feedback_input_index=idx, free_var_signals=fvs):
            return ("feedback", _structural_key(bg), idx, tuple(s.id for s in fvs))
        case _:
            raise TypeError(f"unhandled PrimitiveParams in _params_key: {type(params).__name__}")


def graph_ir_key(ir: object) -> int:
    """Structural hash of a GraphIr (including embedded DspGraphs).

    Lazy import to avoid circular dependency with ir/module.py.
    """
    from krach.ir.module import GraphIr
    assert isinstance(ir, GraphIr)
    parts: list[object] = []
    for nd in ir.nodes:
        if isinstance(nd.source, DspGraph):
            parts.append(("node", nd.name, graph_key(nd.source), nd.gain, nd.count))
        else:
            parts.append(("node", nd.name, nd.source, nd.gain, nd.count))
    for rd in ir.routing:
        parts.append(("route", rd.source, rd.target, rd.kind, rd.level, rd.port))
    if ir.tempo is not None:
        parts.append(("tempo", ir.tempo))
    if ir.meter is not None:
        parts.append(("meter", ir.meter))
    parts.append(("inputs", ir.inputs))
    parts.append(("outputs", ir.outputs))
    for prefix, sub in ir.sub_graphs:
        parts.append(("sub", prefix, graph_ir_key(sub)))
    return hash(tuple(parts))
