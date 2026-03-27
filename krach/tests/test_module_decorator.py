"""Tests for @kr.graph decorator and scene() rename."""

from __future__ import annotations

import inspect

from krach.ir.module import GraphIr
from krach.module_proxy import GraphProxy, graph


# ── @graph ───────────────────────────────────────────────────


def test_decorator_returns_module_ir() -> None:
    @graph
    def my_mod(g: GraphProxy) -> None:
        g.node("osc", "faust:osc")

    result = my_mod()
    assert isinstance(result, GraphIr)
    assert result.nodes[0].name == "osc"


def test_decorator_with_params() -> None:
    @graph
    def my_mod(g: GraphProxy, freq: float = 440.0) -> None:
        g.node("osc", "faust:osc")
        g.set("osc/freq", freq)

    result = my_mod(freq=220.0)
    assert result.controls[0].value == 220.0


def test_decorator_signature_strips_proxy() -> None:
    """Decorated function signature should not include the proxy parameter."""
    @graph
    def my_mod(g: GraphProxy, gain: float = 0.5) -> None:
        pass

    sig = inspect.signature(my_mod)
    params = list(sig.parameters.keys())
    assert "g" not in params
    assert "gain" in params


def test_decorator_preserves_name() -> None:
    @graph
    def my_cool_module(g: GraphProxy) -> None:
        pass

    assert my_cool_module.__name__ == "my_cool_module"


def test_decorator_with_inputs_outputs() -> None:
    @graph
    def fx_chain(g: GraphProxy) -> None:
        g.node("verb", "faust:verb")
        g.inputs("verb")
        g.outputs("verb")

    ir = fx_chain()
    assert ir.inputs == ("verb",)
    assert ir.outputs == ("verb",)


def test_decorator_with_sub_graphs() -> None:
    child = GraphIr(
        nodes=(GraphIr.__dataclass_fields__["nodes"].default,),  # type: ignore[arg-type]
    )
    # Actually construct a real child
    from krach.ir.module import NodeDef
    child = GraphIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )

    @graph
    def composed(g: GraphProxy) -> None:
        ref = g.sub("synth", child)
        g.node("bus", "faust:bus")
        g.send(ref.output("osc"), "bus")

    ir = composed()
    assert len(ir.sub_graphs) == 1
    assert ir.routing[0].source == "synth/osc"


# ── Mixer.scene() rename ───────────────────────────────────────────────


def test_mixer_scene_method_exists() -> None:
    """Mixer.scene() should exist (renamed from module())."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from krach.mixer import Mixer
    session = MagicMock()
    session.list_nodes.return_value = ["faust:osc", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={})
    mixer.save("test_scene")
    ir = mixer.scene("test_scene")
    assert isinstance(ir, GraphIr)


def test_mixer_no_module_method() -> None:
    """Mixer.module() should not exist — renamed to scene()."""
    from krach.mixer import Mixer
    assert not hasattr(Mixer, "module") or not callable(getattr(Mixer, "module", None))
