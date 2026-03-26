"""Integration test: full module composition workflow.

End-to-end: @module_decorator define, sub() compose, instantiate with
prefix, >> route, [] control, remove.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from krach.ir.module import ModuleIr, NodeDef
from krach.mixer import Mixer
from krach.module_proxy import ModuleProxy, module_decorator


def _make_mixer() -> Mixer:
    session = MagicMock()
    session.list_nodes.return_value = [
        "faust:osc", "faust:verb", "faust:bus", "faust:kick",
        "faust:hat", "dac", "gain",
    ]
    return Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:osc": ("freq", "gate"),
        "faust:verb": ("room",),
        "faust:bus": (),
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
    })


def test_full_composition_workflow() -> None:
    """End-to-end: define, compose, instantiate, route, control, remove."""
    # 1. Define a synth module
    @module_decorator
    def synth(m: ModuleProxy, gain: float = 0.5) -> None:
        m.node("osc", "faust:osc", gain=gain)
        m.inputs("osc")
        m.outputs("osc")

    # 2. Define a drums module
    @module_decorator
    def drums(m: ModuleProxy) -> None:
        m.node("kick", "faust:kick", gain=0.8)
        m.node("hat", "faust:hat", gain=0.3)
        m.outputs("kick")

    # 3. Compose into a scene module
    synth_ir = synth(gain=0.4)
    drums_ir = drums()

    @module_decorator
    def scene(m: ModuleProxy) -> None:
        s = m.sub("synth", synth_ir)
        d = m.sub("drums", drums_ir)
        m.node("bus", "faust:bus")
        m.send(s.output("osc"), "bus")
        m.send(d.output("kick"), "bus")
        m.outputs("bus")

    scene_ir = scene()

    # Verify IR structure
    assert len(scene_ir.sub_modules) == 2
    assert scene_ir.sub_modules[0][0] == "synth"
    assert scene_ir.sub_modules[1][0] == "drums"
    assert scene_ir.outputs == ("bus",)

    # 4. Instantiate on mixer
    mixer = _make_mixer()
    handle = mixer.instantiate(scene_ir, "live")

    # Verify all nodes exist
    assert "live/bus" in mixer._nodes
    assert "live/synth/osc" in mixer._nodes
    assert "live/drums/kick" in mixer._nodes
    assert "live/drums/hat" in mixer._nodes

    # 5. Route via >> operator
    verb = mixer.voice("verb", "faust:verb", gain=0.3)
    handle >> verb
    assert ("live/bus", "verb") in mixer._sends

    # 6. Control via [] operator
    handle["synth/osc/freq"] = 440.0
    assert mixer._ctrl_values.get("live/synth/osc/freq") == 440.0

    # 7. Capture includes shadow sub_modules
    captured = mixer.capture()
    assert len(captured.sub_modules) == 1
    assert captured.sub_modules[0][0] == "live"

    # 8. Remove cleans everything
    mixer.remove("live")
    assert "live/bus" not in mixer._nodes
    assert "live/synth/osc" not in mixer._nodes
    captured2 = mixer.capture()
    assert captured2.sub_modules == ()


def test_instantiate_then_load_round_trip() -> None:
    """instantiate + capture + load round-trip."""
    mixer1 = _make_mixer()

    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    mixer1.instantiate(ir, "synth")
    captured = mixer1.capture()

    # Load on fresh mixer (session replay path)
    mixer2 = _make_mixer()
    mixer2.load(captured)
    assert "synth/osc" in mixer2._nodes


def test_module_serialization_round_trip() -> None:
    """@module_decorator → to_dict → from_dict → load."""
    @module_decorator
    def my_mod(m: ModuleProxy) -> None:
        m.node("osc", "faust:osc", gain=0.5)
        m.outputs("osc")

    ir = my_mod()
    d = ir.to_dict()
    restored = ModuleIr.from_dict(d)
    assert restored == ir
    assert restored.outputs == ("osc",)
