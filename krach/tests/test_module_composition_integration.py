"""Integration test: full module composition workflow.

End-to-end: @graph define, sub() compose, instantiate with
prefix, >> route, [] control, remove.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from krach.ir.module import GraphIr, NodeDef
from krach.mixer import Mixer
from krach.module_proxy import GraphProxy, graph


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
    @graph
    def synth(g: GraphProxy, gain: float = 0.5) -> None:
        g.node("osc", "faust:osc", gain=gain)
        g.inputs("osc")
        g.outputs("osc")

    # 2. Define a drums module
    @graph
    def drums(g: GraphProxy) -> None:
        g.node("kick", "faust:kick", gain=0.8)
        g.node("hat", "faust:hat", gain=0.3)
        g.outputs("kick")

    # 3. Compose into a scene module
    synth_ir = synth(gain=0.4)
    drums_ir = drums()

    @graph
    def scene(g: GraphProxy) -> None:
        s = g.sub("synth", synth_ir)
        d = g.sub("drums", drums_ir)
        g.node("bus", "faust:bus")
        g.send(s.output("osc"), "bus")
        g.send(d.output("kick"), "bus")
        g.outputs("bus")

    scene_ir = scene()

    # Verify IR structure
    assert len(scene_ir.sub_graphs) == 2
    assert scene_ir.sub_graphs[0][0] == "synth"
    assert scene_ir.sub_graphs[1][0] == "drums"
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
    _ = handle >> verb
    assert ("live/bus", "verb") in mixer._sends

    # 6. Control via [] operator
    handle["synth/osc/freq"] = 440.0
    assert mixer._ctrl_values.get("live/synth/osc/freq") == 440.0

    # 7. Capture includes shadow sub_graphs
    captured = mixer.capture()
    assert len(captured.sub_graphs) == 1
    assert captured.sub_graphs[0][0] == "live"

    # 8. Remove cleans everything
    mixer.remove("live")
    assert "live/bus" not in mixer._nodes
    assert "live/synth/osc" not in mixer._nodes
    captured2 = mixer.capture()
    assert captured2.sub_graphs == ()


def test_instantiate_then_load_round_trip() -> None:
    """instantiate + capture + load round-trip."""
    mixer1 = _make_mixer()

    ir = GraphIr(
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
    """@graph → to_dict → from_dict → load."""
    @graph
    def my_mod(g: GraphProxy) -> None:
        g.node("osc", "faust:osc", gain=0.5)
        g.outputs("osc")

    ir = my_mod()
    d = ir.to_dict()
    restored = GraphIr.from_dict(d)
    assert restored == ir
    assert restored.outputs == ("osc",)
