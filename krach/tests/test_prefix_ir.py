"""Tests for prefix_ir — pure namespace prefixing of GraphIr."""

from __future__ import annotations

from krach.ir.module import (
    AutomationDef,
    ControlDef,
    GraphIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
    prefix_ir,
)
from krach.pattern.pattern import ctrl, freeze


# ── Basic node prefixing ────────────────────────────────────────────────


def test_prefix_node_names() -> None:
    ir = GraphIr(nodes=(
        NodeDef(name="kick", source="faust:kick"),
        NodeDef(name="snare", source="faust:snare"),
    ))
    result = prefix_ir(ir, "drums")
    assert result.nodes[0].name == "drums/kick"
    assert result.nodes[1].name == "drums/snare"


def test_prefix_route_source_and_target() -> None:
    ir = GraphIr(routing=(
        RouteDef(source="bass", target="verb", kind="send", level=0.4),
    ))
    result = prefix_ir(ir, "mix")
    assert result.routing[0].source == "mix/bass"
    assert result.routing[0].target == "mix/verb"


def test_prefix_route_port_untouched() -> None:
    """RouteDef.port is a DSP input name, NOT a node name — must not be prefixed."""
    ir = GraphIr(routing=(
        RouteDef(source="kick", target="comp", kind="wire", port="sidechain"),
    ))
    result = prefix_ir(ir, "drums")
    assert result.routing[0].port == "sidechain"


def test_prefix_pattern_target() -> None:
    pat = freeze(ctrl("gate", 1.0) + ctrl("gate", 0.0))
    ir = GraphIr(patterns=(PatternDef(target="kick", pattern=pat.node),))
    result = prefix_ir(ir, "drums")
    assert result.patterns[0].target == "drums/kick"


def test_prefix_muted_name() -> None:
    ir = GraphIr(muted=(MutedDef(name="bass", saved_gain=0.3),))
    result = prefix_ir(ir, "mix")
    assert result.muted[0].name == "mix/bass"


def test_prefix_control_path_node_portion() -> None:
    """ControlDef.path: prefix node portion (before first /), leave param portion."""
    ir = GraphIr(controls=(ControlDef(path="bass/cutoff", value=1200.0),))
    result = prefix_ir(ir, "mix")
    assert result.controls[0].path == "mix/bass/cutoff"


def test_prefix_automation_path_node_portion() -> None:
    """AutomationDef.path: prefix node portion only."""
    ir = GraphIr(automations=(
        AutomationDef(path="bass/cutoff", shape="sine", lo=200.0, hi=2000.0, bars=8),
    ))
    result = prefix_ir(ir, "mix")
    assert result.automations[0].path == "mix/bass/cutoff"


def test_prefix_inputs_outputs() -> None:
    ir = GraphIr(inputs=("kick",), outputs=("bus",))
    result = prefix_ir(ir, "drums")
    assert result.inputs == ("drums/kick",)
    assert result.outputs == ("drums/bus",)


def test_prefix_inputs_none_stays_none() -> None:
    ir = GraphIr()
    result = prefix_ir(ir, "x")
    assert result.inputs is None
    assert result.outputs is None


def test_prefix_inputs_empty_stays_empty() -> None:
    ir = GraphIr(inputs=(), outputs=())
    result = prefix_ir(ir, "x")
    assert result.inputs == ()
    assert result.outputs == ()


# ── Recursive sub_module prefixing ──────────────────────────────────────


def test_prefix_sub_module_prefixes() -> None:
    """Sub-module prefixes get composed: prefix + child prefix."""
    child = GraphIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    ir = GraphIr(sub_graphs=(("synth", child),))
    result = prefix_ir(ir, "rack")
    assert result.sub_graphs[0][0] == "rack/synth"


# ── Empty IR identity ──────────────────────────────────────────────────


def test_prefix_empty_ir() -> None:
    ir = GraphIr()
    result = prefix_ir(ir, "x")
    assert result.nodes == ()
    assert result.routing == ()
    assert result.patterns == ()
    assert result.controls == ()
    assert result.automations == ()
    assert result.muted == ()


# ── Transport preserved ────────────────────────────────────────────────


def test_prefix_preserves_transport() -> None:
    ir = GraphIr(tempo=128.0, meter=3.0, master=0.8)
    result = prefix_ir(ir, "x")
    assert result.tempo == 128.0
    assert result.meter == 3.0
    assert result.master == 0.8
