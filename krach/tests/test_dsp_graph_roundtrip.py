"""Tests for DspGraph serialization round-trip."""

from __future__ import annotations

from krach.signal.types import (
    ConstParams,
    DspGraph,
    Equation,
    FeedbackParams,
    NoParams,
    Signal,
    SignalType,
)
from krach.ir.primitive import Primitive
from krach.ir.canonicalize import canonicalize


def _sig(id: int) -> Signal:
    return Signal(aval=SignalType(), id=id, owner_id=0)


add_p = Primitive("add")
mul_p = Primitive("mul")
const_p = Primitive("const")
feedback_p = Primitive("feedback", stateful=True)


def test_roundtrip_simple_add() -> None:
    """Two inputs, one add, one output."""
    from krach.ir.module import dsp_graph_to_dict, dict_to_dsp_graph

    s0, s1 = _sig(0), _sig(1)
    s2 = _sig(2)
    graph = DspGraph(
        inputs=(s0, s1),
        outputs=(s2,),
        equations=(
            Equation(primitive=add_p, inputs=(s0, s1), outputs=(s2,), params=NoParams()),
        ),
    )
    d = dsp_graph_to_dict(graph)
    reconstructed = dict_to_dsp_graph(d)
    assert canonicalize(graph) == canonicalize(reconstructed)


def test_roundtrip_chain() -> None:
    """Serial chain: add → mul."""
    from krach.ir.module import dsp_graph_to_dict, dict_to_dsp_graph

    s0, s1, s2, s3 = _sig(0), _sig(1), _sig(2), _sig(3)
    s4 = _sig(4)
    graph = DspGraph(
        inputs=(s0, s1, s2),
        outputs=(s4,),
        equations=(
            Equation(primitive=add_p, inputs=(s0, s1), outputs=(s3,), params=NoParams()),
            Equation(primitive=mul_p, inputs=(s3, s2), outputs=(s4,), params=NoParams()),
        ),
    )
    d = dsp_graph_to_dict(graph)
    reconstructed = dict_to_dsp_graph(d)
    assert canonicalize(graph) == canonicalize(reconstructed)


def test_roundtrip_nested_feedback() -> None:
    """DspGraph with FeedbackParams containing body_graph."""
    from krach.ir.module import dsp_graph_to_dict, dict_to_dsp_graph

    # Body graph: fb_in -> fb_in * 0.5
    fb_in = _sig(100)
    c = _sig(101)
    fb_out = _sig(102)
    body = DspGraph(
        inputs=(fb_in,),
        outputs=(fb_out,),
        equations=(
            Equation(primitive=const_p, inputs=(), outputs=(c,), params=ConstParams(value=0.5)),
            Equation(primitive=mul_p, inputs=(fb_in, c), outputs=(fb_out,), params=NoParams()),
        ),
    )

    # Outer graph: feedback(body)
    outer_out = _sig(200)
    graph = DspGraph(
        inputs=(),
        outputs=(outer_out,),
        equations=(
            Equation(
                primitive=feedback_p, inputs=(), outputs=(outer_out,),
                params=FeedbackParams(body_graph=body, feedback_input_index=0, free_var_signals=()),
            ),
        ),
    )
    d = dsp_graph_to_dict(graph)
    reconstructed = dict_to_dsp_graph(d)
    assert canonicalize(graph) == canonicalize(reconstructed)
