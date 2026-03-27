"""Tests for flatten — recursive sub_module resolution."""

from __future__ import annotations

import pytest

from krach.ir.graph import (
    ControlDef,
    GraphIr,
    NodeDef,
    RouteDef,
    flatten,
)


# ── Basic flattening ────────────────────────────────────────────────────


def test_flatten_single_child() -> None:
    child = GraphIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    parent = GraphIr(sub_graphs=(("synth", child),))
    flat = flatten(parent)
    assert any(n.name == "synth/osc" for n in flat.nodes)
    assert flat.sub_graphs == ()


def test_flatten_preserves_parent_nodes() -> None:
    child = GraphIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    parent = GraphIr(
        nodes=(NodeDef(name="bus", source="faust:bus"),),
        sub_graphs=(("synth", child),),
    )
    flat = flatten(parent)
    names = {n.name for n in flat.nodes}
    assert "bus" in names
    assert "synth/osc" in names


def test_flatten_merges_routing() -> None:
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        routing=(RouteDef(source="osc", target="osc", kind="send"),),
    )
    parent = GraphIr(
        routing=(RouteDef(source="x", target="y", kind="send"),),
        sub_graphs=(("s", child),),
    )
    flat = flatten(parent)
    sources = {r.source for r in flat.routing}
    assert "x" in sources
    assert "s/osc" in sources


# ── Nested 3-deep ──────────────────────────────────────────────────────


def test_flatten_nested_three_deep() -> None:
    """Three levels: grandchild -> child -> parent."""
    grandchild = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    child = GraphIr(
        nodes=(NodeDef(name="mix", source="faust:mix"),),
        sub_graphs=(("inner", grandchild),),
        outputs=("mix",),
    )
    parent = GraphIr(sub_graphs=(("outer", child),))
    flat = flatten(parent)
    names = {n.name for n in flat.nodes}
    assert "outer/mix" in names
    assert "outer/inner/osc" in names
    assert flat.sub_graphs == ()


# ── Double prefix ───────────────────────────────────────────────────────


def test_flatten_double_prefix() -> None:
    """Two sub_graphs with different prefixes both get flattened."""
    a = GraphIr(nodes=(NodeDef(name="n", source="faust:a"),))
    b = GraphIr(nodes=(NodeDef(name="n", source="faust:b"),))
    parent = GraphIr(sub_graphs=(("a", a), ("b", b)))
    flat = flatten(parent)
    names = {n.name for n in flat.nodes}
    assert "a/n" in names
    assert "b/n" in names


# ── Transport: parent wins ──────────────────────────────────────────────


def test_flatten_parent_wins_transport() -> None:
    """Child tempo/meter/master are ignored — parent's values win."""
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        tempo=90.0, meter=3.0, master=0.5,
    )
    parent = GraphIr(
        tempo=128.0, meter=4.0, master=0.7,
        sub_graphs=(("s", child),),
    )
    flat = flatten(parent)
    assert flat.tempo == 128.0
    assert flat.meter == 4.0
    assert flat.master == 0.7


def test_flatten_none_parent_transport_stays_none() -> None:
    """If parent has None transport, child transport still ignored."""
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        tempo=90.0,
    )
    parent = GraphIr(sub_graphs=(("s", child),))
    flat = flatten(parent)
    assert flat.tempo is None


# ── Validation: inputs/outputs ──────────────────────────────────────────


def test_flatten_validates_inputs_exist() -> None:
    """inputs referencing non-existent node names raise ValueError."""
    ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("missing",),
    )
    with pytest.raises(ValueError, match="missing"):
        flatten(ir)


def test_flatten_validates_outputs_exist() -> None:
    """outputs referencing non-existent node names raise ValueError."""
    ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("missing",),
    )
    with pytest.raises(ValueError, match="missing"):
        flatten(ir)


def test_flatten_valid_inputs_outputs() -> None:
    """Valid inputs/outputs pass validation."""
    ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",), outputs=("osc",),
    )
    flat = flatten(ir)
    assert flat.inputs == ("osc",)
    assert flat.outputs == ("osc",)


# ── Flat IR identity ───────────────────────────────────────────────────


def test_flatten_already_flat() -> None:
    """Flattening a flat IR (no sub_graphs) returns equivalent IR."""
    ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        routing=(RouteDef(source="osc", target="osc", kind="send"),),
        tempo=120.0,
    )
    flat = flatten(ir)
    assert flat.nodes == ir.nodes
    assert flat.routing == ir.routing
    assert flat.tempo == ir.tempo


# ── Merges controls and patterns from children ─────────────────────────


def test_flatten_merges_controls() -> None:
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        controls=(ControlDef(path="osc/freq", value=440.0),),
    )
    parent = GraphIr(
        controls=(ControlDef(path="bus/gain", value=0.5),),
        sub_graphs=(("s", child),),
    )
    flat = flatten(parent)
    paths = {c.path for c in flat.controls}
    assert "bus/gain" in paths
    assert "s/osc/freq" in paths
