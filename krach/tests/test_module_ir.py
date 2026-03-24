"""Tests for Module IR — frozen specification types."""

from __future__ import annotations

import pytest

from krach._module_ir import (
    AutomationDef,
    ControlDef,
    ModuleIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
)
from krach.patterns.pattern import ctrl, freeze


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
    ir = ModuleIr()
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
    ir = ModuleIr()
    assert ir.nodes == ()
    assert ir.routing == ()
    assert ir.patterns == ()
    assert ir.controls == ()
    assert ir.automations == ()
    assert ir.muted == ()
    assert ir.tempo is None
    assert ir.master is None
    assert ir.sub_modules == ()


def test_module_ir_with_nodes_and_routing() -> None:
    ir = ModuleIr(
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
    a = ModuleIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        tempo=128.0,
    )
    b = ModuleIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        tempo=128.0,
    )
    assert a == b


def test_module_ir_inequality() -> None:
    a = ModuleIr(tempo=120.0)
    b = ModuleIr(tempo=128.0)
    assert a != b


# ── Sub-modules ──────────────────────────────────────────────────────────


def test_sub_modules() -> None:
    child = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
    )
    parent = ModuleIr(
        sub_modules=(("synth", child),),
    )
    assert len(parent.sub_modules) == 1
    prefix, child_ir = parent.sub_modules[0]
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
