"""Tests for ModuleProxy composition: inputs, outputs, sub, freeze."""

from __future__ import annotations

import pytest

from krach.ir.module import ModuleIr, NodeDef
from krach.module_proxy import ModuleProxy


# ── inputs/outputs ──────────────────────────────────────────────────────


def test_proxy_inputs_outputs() -> None:
    proxy = ModuleProxy()
    proxy.node("osc", "faust:osc")
    proxy.inputs("osc")
    proxy.outputs("osc")
    ir = proxy.build()
    assert ir.inputs == ("osc",)
    assert ir.outputs == ("osc",)


def test_proxy_inputs_empty() -> None:
    proxy = ModuleProxy()
    proxy.inputs()
    ir = proxy.build()
    assert ir.inputs == ()


def test_proxy_inputs_double_call_error() -> None:
    proxy = ModuleProxy()
    proxy.inputs("a")
    with pytest.raises(RuntimeError, match="inputs"):
        proxy.inputs("b")


def test_proxy_outputs_double_call_error() -> None:
    proxy = ModuleProxy()
    proxy.outputs("a")
    with pytest.raises(RuntimeError, match="outputs"):
        proxy.outputs("b")


# ── sub() ───────────────────────────────────────────────────────────────


def test_proxy_sub_records_sub_module() -> None:
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    proxy = ModuleProxy()
    proxy.sub("synth", child_ir)
    ir = proxy.build()
    assert len(ir.sub_modules) == 1
    assert ir.sub_modules[0][0] == "synth"


def test_sub_module_ref_input_output() -> None:
    """SubModuleRef.input/output return validated prefixed paths."""
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    proxy = ModuleProxy()
    ref = proxy.sub("synth", child_ir)
    assert ref.input("osc") == "synth/osc"
    assert ref.output("osc") == "synth/osc"


def test_sub_module_ref_invalid_input() -> None:
    """SubModuleRef.input raises ValueError for non-existent port."""
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
    )
    proxy = ModuleProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="missing"):
        ref.input("missing")


def test_sub_module_ref_invalid_output() -> None:
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    proxy = ModuleProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="missing"):
        ref.output("missing")


def test_sub_module_ref_no_inputs_declared() -> None:
    """SubModuleRef.input raises ValueError when child has no declared inputs."""
    child_ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    proxy = ModuleProxy()
    ref = proxy.sub("synth", child_ir)
    with pytest.raises(ValueError, match="no declared inputs"):
        ref.input("osc")


# ── Route validation at build() ─────────────────────────────────────────


def test_build_validates_route_targets() -> None:
    """Route targets must reference local nodes or prefixed sub_module nodes."""
    proxy = ModuleProxy()
    proxy.node("a", "faust:a")
    proxy.send("a", "nonexistent")
    with pytest.raises(ValueError, match="nonexistent"):
        proxy.build()


def test_build_allows_routes_to_sub_module_nodes() -> None:
    """Routes can target prefixed sub_module nodes."""
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
    )
    proxy = ModuleProxy()
    proxy.node("src", "faust:src")
    proxy.sub("synth", child_ir)
    proxy.send("src", "synth/osc")
    ir = proxy.build()
    assert ir.routing[0].target == "synth/osc"


# ── Proxy freeze after build() ──────────────────────────────────────────


def test_proxy_freeze_after_build() -> None:
    """Further calls after build() raise RuntimeError."""
    proxy = ModuleProxy()
    proxy.build()
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.node("x", "faust:x")


def test_proxy_freeze_all_methods() -> None:
    proxy = ModuleProxy()
    proxy.build()
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.send("a", "b")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.inputs("a")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.outputs("a")
    with pytest.raises(RuntimeError, match="frozen"):
        proxy.sub("x", ModuleIr())


# ── SubModuleRef __repr__ ───────────────────────────────────────────────


def test_sub_module_ref_repr() -> None:
    child_ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    proxy = ModuleProxy()
    ref = proxy.sub("synth", child_ir)
    r = repr(ref)
    assert "synth" in r
    assert "osc" in r
