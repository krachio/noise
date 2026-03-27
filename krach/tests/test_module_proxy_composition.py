"""Tests for GraphProxy composition: inputs, outputs, sub, freeze."""

from __future__ import annotations

import pytest

from krach.ir.graph import GraphIr, NodeDef
from krach.graph.proxy import GraphProxy


# ── inputs/outputs ──────────────────────────────────────────────────────


def test_proxy_inputs_outputs() -> None:
    proxy = GraphProxy()
    proxy.node("osc", "faust:osc")
    proxy.inputs("osc")
    proxy.outputs("osc")
    ir = proxy.build()
    assert ir.inputs == ("osc",)
    assert ir.outputs == ("osc",)


def test_proxy_inputs_empty() -> None:
    proxy = GraphProxy()
    proxy.inputs()
    ir = proxy.build()
    assert ir.inputs == ()


def test_proxy_inputs_double_call_error() -> None:
    proxy = GraphProxy()
    proxy.inputs("a")
    with pytest.raises(RuntimeError, match="inputs"):
        proxy.inputs("b")


def test_proxy_outputs_double_call_error() -> None:
    proxy = GraphProxy()
    proxy.outputs("a")
    with pytest.raises(RuntimeError, match="outputs"):
        proxy.outputs("b")


# ── sub() ───────────────────────────────────────────────────────────────


def test_proxy_sub_records_sub_module() -> None:
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    proxy = GraphProxy()
    proxy.sub("synth", child_ir)
    ir = proxy.build()
    assert len(ir.sub_graphs) == 1
    assert ir.sub_graphs[0][0] == "synth"


def test_sub_module_ref_input_output() -> None:
    """SubGraphRef.input/output return validated prefixed paths."""
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    proxy = GraphProxy()
    ref = proxy.sub("synth", child_ir)
    assert ref.input("osc") == "synth/osc"
    assert ref.output("osc") == "synth/osc"


def test_sub_module_ref_invalid_input() -> None:
    """SubGraphRef.input raises ValueError for non-existent port."""
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
    )
    proxy = GraphProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="missing"):
        ref.input("missing")


def test_sub_module_ref_invalid_output() -> None:
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    proxy = GraphProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="missing"):
        ref.output("missing")


def test_sub_module_ref_no_inputs_declared() -> None:
    """SubGraphRef.input raises ValueError when child has no declared inputs."""
    child_ir = GraphIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    proxy = GraphProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="no declared inputs"):
        ref.input("osc")


# ── Route validation at build() ─────────────────────────────────────────


def test_build_validates_route_targets() -> None:
    """Route targets must reference local nodes or prefixed sub_module nodes."""
    proxy = GraphProxy()
    proxy.node("a", "faust:a")
    proxy.send("a", "nonexistent")
    with pytest.raises(ValueError, match="nonexistent"):
        proxy.build()


def test_build_allows_routes_to_sub_module_nodes() -> None:
    """Routes can target prefixed sub_module nodes."""
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
    )
    proxy = GraphProxy()
    proxy.node("src", "faust:src")
    proxy.sub("synth", child_ir)
    proxy.send("src", "synth/osc")
    ir = proxy.build()
    assert ir.routing[0].target == "synth/osc"


# ── Proxy freeze after build() ──────────────────────────────────────────


def test_proxy_freeze_after_build() -> None:
    """Further calls after build() raise RuntimeError."""
    proxy = GraphProxy()
    proxy.build()
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.node("x", "faust:x")


def test_proxy_freeze_all_methods() -> None:
    proxy = GraphProxy()
    proxy.build()
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.send("a", "b")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.inputs("a")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.outputs("a")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.sub("x", GraphIr())


# ── SubGraphRef __repr__ ───────────────────────────────────────────────


def test_sub_module_ref_repr() -> None:
    child_ir = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    proxy = GraphProxy()
    ref = proxy.sub("synth", child_ir)
    r = repr(ref)
    assert "synth" in r
    assert "osc" in r
