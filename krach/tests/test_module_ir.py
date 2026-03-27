"""Tests for Module IR — frozen specification types."""

from __future__ import annotations

import pytest

from krach.ir.module import (
    AutomationDef,
    ControlDef,
    GraphIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
)
from krach.pattern.pattern import ctrl, freeze


# ── Frozen immutability ──────────────────────────────────────────────────


def test_node_def_frozen() -> None:
    nd = NodeDef(name="bass", source="faust:bass", gain=0.3)
    with pytest.raises(AttributeError):
        nd.gain = 0.5  # type: ignore[misc]


def test_route_def_frozen() -> None:
    rd = RouteDef(source="bass", target="verb", kind="send", level=0.4)
    with pytest.raises(AttributeError):
        rd.level = 0.8  # type: ignore[misc]


def test_module_ir_frozen() -> None:
    ir = GraphIr()
    with pytest.raises(AttributeError):
        ir.tempo = 140.0  # type: ignore[misc]


# ── Construction + equality ──────────────────────────────────────────────


def test_node_def_defaults() -> None:
    nd = NodeDef(name="kick", source="faust:kick")
    assert nd.gain == 0.5
    assert nd.count == 1
    assert nd.init == ()


def test_route_def_send() -> None:
    rd = RouteDef(source="bass", target="verb", kind="send", level=0.4)
    assert rd.kind == "send"
    assert rd.level == 0.4
    assert rd.port == "in0"


def test_route_def_wire() -> None:
    rd = RouteDef(source="kick", target="comp", kind="wire", port="sidechain")
    assert rd.kind == "wire"
    assert rd.port == "sidechain"


def test_pattern_def_with_pattern_node() -> None:
    pat = freeze(ctrl("gate", 1.0) + ctrl("gate", 0.0))
    pd = PatternDef(target="kick", pattern=pat.node)
    assert pd.swing is None


def test_module_ir_empty() -> None:
    ir = GraphIr()
    assert ir.nodes == ()
    assert ir.routing == ()
    assert ir.patterns == ()
    assert ir.controls == ()
    assert ir.automations == ()
    assert ir.muted == ()
    assert ir.tempo is None
    assert ir.master is None
    assert ir.sub_graphs == ()


def test_module_ir_with_nodes_and_routing() -> None:
    ir = GraphIr(
        nodes=(
            NodeDef(name="bass", source="faust:bass", gain=0.3),
            NodeDef(name="verb", source="faust:verb", gain=0.4),
        ),
        routing=(
            RouteDef(source="bass", target="verb", kind="send", level=0.4),
        ),
        tempo=120.0,
        master=0.7,
    )
    assert len(ir.nodes) == 2
    assert len(ir.routing) == 1
    assert ir.tempo == 120.0


def test_module_ir_equality() -> None:
    a = GraphIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        tempo=128.0,
    )
    b = GraphIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        tempo=128.0,
    )
    assert a == b


def test_module_ir_inequality() -> None:
    a = GraphIr(tempo=120.0)
    b = GraphIr(tempo=128.0)
    assert a != b


# ── Sub-modules ──────────────────────────────────────────────────────────


def test_sub_graphs() -> None:
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
    )
    parent = GraphIr(
        sub_graphs=(("synth", child),),
    )
    assert len(parent.sub_graphs) == 1
    prefix, child_ir = parent.sub_graphs[0]
    assert prefix == "synth"
    assert len(child_ir.nodes) == 1


# ── Automation + mute ────────────────────────────────────────────────────


def test_automation_def() -> None:
    ad = AutomationDef(path="bass/cutoff", shape="sine", lo=200.0, hi=2000.0, bars=8)
    assert ad.shape == "sine"
    assert ad.bars == 8


def test_muted_def() -> None:
    md = MutedDef(name="bass", saved_gain=0.3)
    assert md.saved_gain == 0.3


def test_control_def() -> None:
    cd = ControlDef(path="bass/cutoff", value=1200.0)
    assert cd.value == 1200.0


def test_module_ir_roundtrip_with_dsp_graph() -> None:
    """GraphIr round-trip preserves embedded DspGraph sources."""
    from krach.signal.types import (
        DspGraph, Equation, NoParams, Signal, SignalType,
    )
    from krach.ir.primitive import Primitive
    from krach.ir.canonicalize import canonicalize

    s0 = Signal(aval=SignalType(), id=0, owner_id=0)
    s1 = Signal(aval=SignalType(), id=1, owner_id=0)
    graph = DspGraph(
        inputs=(s0,),
        outputs=(s1,),
        equations=(
            Equation(
                primitive=Primitive("mul"),
                inputs=(s0, s0),
                outputs=(s1,),
                params=NoParams(),
            ),
        ),
    )
    nd = NodeDef(name="bass", source=graph, gain=0.3)
    assert nd.num_inputs == 1  # derived from DspGraph.inputs

    ir = GraphIr(nodes=(nd,))
    d = ir.to_dict()
    assert isinstance(d["nodes"][0]["source"], dict)
    assert d["nodes"][0]["source"]["type"] == "dsp_graph"

    restored = GraphIr.from_dict(d)
    assert isinstance(restored.nodes[0].source, DspGraph)
    assert canonicalize(graph) == canonicalize(restored.nodes[0].source)


# ── inputs/outputs ──────────────────────────────────────────────────────


def test_module_ir_inputs_outputs_default_none() -> None:
    """Default inputs/outputs is None (undeclared)."""
    ir = GraphIr()
    assert ir.inputs is None
    assert ir.outputs is None


def test_module_ir_inputs_outputs_explicit_empty() -> None:
    """Explicit empty tuple means 'no ports' (distinct from None)."""
    ir = GraphIr(inputs=(), outputs=())
    assert ir.inputs == ()
    assert ir.outputs == ()


def test_module_ir_inputs_outputs_populated() -> None:
    """Named ports."""
    ir = GraphIr(inputs=("in_l", "in_r"), outputs=("out",))
    assert ir.inputs == ("in_l", "in_r")
    assert ir.outputs == ("out",)


# ── inputs/outputs serialization ────────────────────────────────────────


def test_to_dict_inputs_none_omitted() -> None:
    """None inputs/outputs should NOT appear in serialized dict."""
    ir = GraphIr()
    d = ir.to_dict()
    assert "inputs" not in d
    assert "outputs" not in d


def test_to_dict_inputs_empty_tuple() -> None:
    """Empty tuple serializes as empty list."""
    ir = GraphIr(inputs=(), outputs=())
    d = ir.to_dict()
    assert d["inputs"] == []
    assert d["outputs"] == []


def test_to_dict_inputs_populated() -> None:
    """Populated tuple serializes as list of strings."""
    ir = GraphIr(inputs=("kick",), outputs=("bus",))
    d = ir.to_dict()
    assert d["inputs"] == ["kick"]
    assert d["outputs"] == ["bus"]


def test_roundtrip_inputs_none() -> None:
    """Round-trip preserves None (undeclared)."""
    ir = GraphIr()
    restored = GraphIr.from_dict(ir.to_dict())
    assert restored.inputs is None
    assert restored.outputs is None
    assert restored == ir


def test_roundtrip_inputs_empty() -> None:
    """Round-trip preserves empty tuple (explicitly no ports)."""
    ir = GraphIr(inputs=(), outputs=())
    restored = GraphIr.from_dict(ir.to_dict())
    assert restored.inputs == ()
    assert restored.outputs == ()
    assert restored == ir


def test_roundtrip_inputs_populated() -> None:
    """Round-trip preserves named ports."""
    ir = GraphIr(inputs=("in",), outputs=("out_l", "out_r"))
    restored = GraphIr.from_dict(ir.to_dict())
    assert restored.inputs == ("in",)
    assert restored.outputs == ("out_l", "out_r")
    assert restored == ir


# ── graph_ir_key includes inputs/outputs ──────────────────────────────────


def test_graph_ir_key_differs_with_inputs() -> None:
    """graph_ir_key must distinguish modules with different inputs/outputs."""
    from krach.ir.canonicalize import graph_ir_key

    base = GraphIr(nodes=(NodeDef(name="a", source="faust:a"),))
    with_inputs = GraphIr(
        nodes=(NodeDef(name="a", source="faust:a"),),
        inputs=("a",),
    )
    with_outputs = GraphIr(
        nodes=(NodeDef(name="a", source="faust:a"),),
        outputs=("a",),
    )
    keys = {graph_ir_key(base), graph_ir_key(with_inputs), graph_ir_key(with_outputs)}
    assert len(keys) == 3, "graph_ir_key must differ for different inputs/outputs"


def test_graph_ir_key_none_vs_empty_inputs() -> None:
    """graph_ir_key distinguishes None from () for inputs/outputs."""
    from krach.ir.canonicalize import graph_ir_key

    none_inputs = GraphIr()
    empty_inputs = GraphIr(inputs=(), outputs=())
    assert graph_ir_key(none_inputs) != graph_ir_key(empty_inputs)


# ── passthrough DSP function ────────────────────────────────────────────


def test_passthrough_traces_valid_graph() -> None:
    """passthrough is a 1-in-1-out identity DSP function."""
    from krach.signal.lib.effects import passthrough
    from krach.signal.transpile import transpile

    result = transpile(passthrough)
    assert result.num_inputs == 1
    assert result.num_outputs == 1
