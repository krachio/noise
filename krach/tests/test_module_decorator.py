"""Tests for @kr.module decorator and scene() rename."""

from __future__ import annotations

import inspect

from krach.ir.module import ModuleIr
from krach.module_proxy import ModuleProxy, module_decorator


# ── @module_decorator ───────────────────────────────────────────────────


def test_decorator_returns_module_ir() -> None:
    @module_decorator
    def my_mod(m: ModuleProxy) -> None:
        m.node("osc", "faust:osc")

    result = my_mod()
    assert isinstance(result, ModuleIr)
    assert result.nodes[0].name == "osc"


def test_decorator_with_params() -> None:
    @module_decorator
    def my_mod(m: ModuleProxy, freq: float = 440.0) -> None:
        m.node("osc", "faust:osc")
        m.set("osc/freq", freq)

    result = my_mod(freq=220.0)
    assert result.controls[0].value == 220.0


def test_decorator_signature_strips_proxy() -> None:
    """Decorated function signature should not include the proxy parameter."""
    @module_decorator
    def my_mod(m: ModuleProxy, gain: float = 0.5) -> None:
        pass

    sig = inspect.signature(my_mod)
    params = list(sig.parameters.keys())
    assert "m" not in params
    assert "gain" in params


def test_decorator_preserves_name() -> None:
    @module_decorator
    def my_cool_module(m: ModuleProxy) -> None:
        pass

    assert my_cool_module.__name__ == "my_cool_module"


def test_decorator_with_inputs_outputs() -> None:
    @module_decorator
    def fx_chain(m: ModuleProxy) -> None:
        m.node("verb", "faust:verb")
        m.inputs("verb")
        m.outputs("verb")

    ir = fx_chain()
    assert ir.inputs == ("verb",)
    assert ir.outputs == ("verb",)


def test_decorator_with_sub_modules() -> None:
    child = ModuleIr(
        nodes=(ModuleIr.__dataclass_fields__["nodes"].default,),  # type: ignore[arg-type]
    )
    # Actually construct a real child
    from krach.ir.module import NodeDef
    child = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )

    @module_decorator
    def composed(m: ModuleProxy) -> None:
        ref = m.sub("synth", child)
        m.node("bus", "faust:bus")
        m.send(ref.output("osc"), "bus")

    ir = composed()
    assert len(ir.sub_modules) == 1
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
    assert isinstance(ir, ModuleIr)


def test_mixer_no_module_method() -> None:
    """Mixer.module() should not exist — renamed to scene()."""
    from krach.mixer import Mixer
    assert not hasattr(Mixer, "module") or not callable(getattr(Mixer, "module", None))
