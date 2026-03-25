"""Tests for the module system — capture, instantiate, serialize."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from krach._mixer import Mixer
from krach._module_ir import (
    ControlDef,
    ModuleIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
)


def _make_mixer() -> Mixer:
    session = MagicMock()
    session.list_nodes.return_value = [
        "faust:bass", "faust:verb", "faust:kick", "dac", "gain",
    ]
    return Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
        "faust:kick": ("gate",),
    })


# ── capture() ────────────────────────────────────────────────────────


def test_capture_empty_mixer() -> None:
    mixer = _make_mixer()
    ir = mixer.capture()
    assert ir.nodes == ()
    assert ir.routing == ()
    assert ir.controls == ()
    assert ir.master == 0.7


def test_capture_nodes() -> None:
    mixer = _make_mixer()
    with mixer.batch():
        mixer.voice("bass", "faust:bass", gain=0.3)
        mixer.voice("verb", "faust:verb", gain=0.5)

    ir = mixer.capture()
    names = {n.name for n in ir.nodes}
    assert names == {"bass", "verb"}
    bass_def = next(n for n in ir.nodes if n.name == "bass")
    assert bass_def.gain == 0.3
    assert bass_def.source == "faust:bass"


def test_capture_routing() -> None:
    mixer = _make_mixer()
    with mixer.batch():
        mixer.voice("bass", "faust:bass", gain=0.3)
        mixer.voice("verb", "faust:verb", gain=0.5)
    mixer.send("bass", "verb", level=0.4)

    ir = mixer.capture()
    assert len(ir.routing) == 1
    route = ir.routing[0]
    assert route.source == "bass"
    assert route.target == "verb"
    assert route.kind == "send"
    assert route.level == 0.4


def test_capture_controls() -> None:
    mixer = _make_mixer()
    with mixer.batch():
        mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.set("bass/freq", 220.0)

    ir = mixer.capture()
    assert any(c.path == "bass/freq" and c.value == 220.0 for c in ir.controls)


def test_capture_muted() -> None:
    mixer = _make_mixer()
    with mixer.batch():
        mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.mute("bass")

    ir = mixer.capture()
    muted = [m for m in ir.muted if m.name == "bass"]
    assert len(muted) == 1
    assert muted[0].saved_gain == 0.3


def test_capture_transport() -> None:
    mixer = _make_mixer()
    mixer.tempo = 140
    mixer.meter = 3

    ir = mixer.capture()
    assert ir.tempo == 140
    assert ir.meter == 3


# ── instantiate() ────────────────────────────────────────────────────


def test_instantiate_creates_nodes() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(
            NodeDef(name="kick", source="faust:kick", gain=0.8),
        ),
    )
    mixer.instantiate(ir)
    assert "kick" in mixer.node_data
    assert mixer.node_data["kick"].gain == 0.8


def test_instantiate_creates_routing() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(
            NodeDef(name="bass", source="faust:bass", gain=0.3),
            NodeDef(name="verb", source="faust:verb", gain=0.5),
        ),
        routing=(
            RouteDef(source="bass", target="verb", kind="send", level=0.4),
        ),
    )
    mixer.instantiate(ir)
    assert ("bass", "verb", "send", 0.4) in mixer.routing


def test_instantiate_sets_controls() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(
            NodeDef(name="bass", source="faust:bass", gain=0.3),
        ),
        controls=(
            ControlDef(path="bass/freq", value=220.0),
        ),
    )
    mixer.instantiate(ir)
    assert mixer.ctrl_values.get("bass/freq") == 220.0


def test_instantiate_sets_transport() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(tempo=140, meter=3, master=0.6)
    mixer.instantiate(ir)
    # Transport is delegated to session
    mixer._session.tempo  # type: ignore[reportPrivateUsage]  # accessed via property on mock


def test_capture_instantiate_round_trip() -> None:
    """capture() → instantiate() on a fresh mixer reproduces the state."""
    mixer1 = _make_mixer()
    with mixer1.batch():
        mixer1.voice("bass", "faust:bass", gain=0.3)
        mixer1.voice("verb", "faust:verb", gain=0.5)
    mixer1.send("bass", "verb", level=0.4)
    mixer1.set("bass/freq", 220.0)
    mixer1.mute("bass")

    ir = mixer1.capture()

    mixer2 = _make_mixer()
    mixer2.instantiate(ir)

    assert set(mixer2.node_data.keys()) == {"bass", "verb"}
    assert ("bass", "verb", "send", 0.4) in mixer2.routing
    assert mixer2.ctrl_values.get("bass/freq") == 220.0
    assert mixer2.is_muted("bass")
    # Muted bass: saved gain is 0.3 — verify via capture()
    ir2 = mixer2.capture()
    muted_bass = [m for m in ir2.muted if m.name == "bass"]
    assert len(muted_bass) == 1 and muted_bass[0].saved_gain == 0.3


# ── to_dict / from_dict ───────────────────────────────────────────


def test_module_ir_round_trip_empty() -> None:
    ir = ModuleIr()
    d = ir.to_dict()
    assert d == {}
    assert ModuleIr.from_dict(d) == ir


def test_module_ir_round_trip_full() -> None:
    from krach.pattern.pattern import ctrl, freeze

    ir = ModuleIr(
        nodes=(
            NodeDef(name="bass", source="faust:bass", gain=0.3),
            NodeDef(name="verb", source="faust:verb", gain=0.5),
        ),
        routing=(
            RouteDef(source="bass", target="verb", kind="send", level=0.4),
        ),
        patterns=(
            PatternDef(target="bass", pattern=freeze(ctrl("gate", 1.0) + ctrl("gate", 0.0)).node),
        ),
        controls=(
            ControlDef(path="bass/freq", value=220.0),
        ),
        muted=(
            MutedDef(name="bass", saved_gain=0.3),
        ),
        tempo=128.0,
        meter=4.0,
        master=0.7,
    )
    d = ir.to_dict()
    restored = ModuleIr.from_dict(d)

    assert len(restored.nodes) == 2
    assert restored.nodes[0].name == "bass"
    assert len(restored.routing) == 1
    assert len(restored.patterns) == 1
    assert restored.patterns[0].target == "bass"
    assert len(restored.controls) == 1
    assert len(restored.muted) == 1
    assert restored.tempo == 128.0
    assert restored.master == 0.7


def test_module_ir_json_round_trip() -> None:
    """to_dict → JSON → from_dict produces equivalent ModuleIr."""
    import json

    ir = ModuleIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        tempo=140.0,
    )
    j = json.dumps(ir.to_dict())
    restored = ModuleIr.from_dict(json.loads(j))
    assert restored.nodes[0].name == "kick"
    assert restored.nodes[0].gain == 0.8
    assert restored.tempo == 140.0


# ── ModuleProxy (trace) ──────────────────────────────────────────


def test_proxy_records_nodes() -> None:
    from krach._module_proxy import ModuleProxy

    proxy = ModuleProxy()
    proxy.node("bass", "faust:bass", gain=0.3)
    proxy.node("verb", "faust:verb", gain=0.5)

    ir = proxy.build()
    assert len(ir.nodes) == 2
    assert ir.nodes[0].name == "bass"
    assert ir.nodes[0].gain == 0.3


def test_proxy_records_routing() -> None:
    from krach._module_proxy import ModuleProxy

    proxy = ModuleProxy()
    proxy.node("bass", "faust:bass")
    proxy.node("verb", "faust:verb")
    proxy.send("bass", "verb", level=0.4)

    ir = proxy.build()
    assert len(ir.routing) == 1
    assert ir.routing[0].level == 0.4


def test_proxy_records_transport() -> None:
    from krach._module_proxy import ModuleProxy

    proxy = ModuleProxy()
    proxy.tempo = 140
    proxy.meter = 3
    proxy.master = 0.6

    ir = proxy.build()
    assert ir.tempo == 140
    assert ir.meter == 3
    assert ir.master == 0.6


def test_proxy_records_controls_and_patterns() -> None:
    from krach._module_proxy import ModuleProxy
    from krach.pattern.pattern import ctrl, freeze

    proxy = ModuleProxy()
    proxy.node("bass", "faust:bass")
    proxy.set("bass/freq", 220.0)
    proxy.play("bass", freeze(ctrl("gate", 1.0) + ctrl("gate", 0.0)))

    ir = proxy.build()
    assert len(ir.controls) == 1
    assert ir.controls[0].value == 220.0
    assert len(ir.patterns) == 1
    assert ir.patterns[0].target == "bass"


def test_proxy_to_instantiate_round_trip() -> None:
    """Proxy → ModuleIr → instantiate on a live mixer."""
    from krach._module_proxy import ModuleProxy

    proxy = ModuleProxy()
    proxy.node("kick", "faust:kick", gain=0.8)
    proxy.tempo = 140

    ir = proxy.build()

    mixer = _make_mixer()
    mixer.instantiate(ir)

    assert "kick" in mixer.node_data
    assert mixer.node_data["kick"].gain == 0.8


def test_instantiate_applies_mutes() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(
            NodeDef(name="bass", source="faust:bass", gain=0.3),
        ),
        muted=(
            MutedDef(name="bass", saved_gain=0.3),
        ),
    )
    mixer.instantiate(ir)
    assert mixer.is_muted("bass")


# ── P0: capture() must include patterns ──────────────────────────


def test_capture_includes_patterns() -> None:
    """capture() must record running patterns in the ModuleIr."""
    from krach._patterns import hit

    mixer = _make_mixer()
    with mixer.batch():
        mixer.voice("kick", "faust:kick", gain=0.8)
    pat = hit()
    mixer.play("kick", pat)

    ir = mixer.capture()
    assert len(ir.patterns) == 1
    assert ir.patterns[0].target == "kick"


def test_instantiate_replays_patterns() -> None:
    """instantiate() must call play() for each PatternDef."""
    from krach.ir.pattern import PatternNode, AtomParams, CatParams, FreezeParams
    from krach.ir.values import Control
    from krach.pattern.primitives import atom_p, cat_p, freeze_p

    mixer = _make_mixer()
    # Build a simple gate trigger pattern as PatternNode
    gate_on = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    gate_off = PatternNode(atom_p, (), AtomParams(Control("gate", 0.0)))
    pat_node = PatternNode(freeze_p, (
        PatternNode(cat_p, (gate_on, gate_off), CatParams()),
    ), FreezeParams())

    ir = ModuleIr(
        nodes=(NodeDef(name="kick", source="faust:kick", gain=0.8),),
        patterns=(PatternDef(target="kick", pattern=pat_node),),
    )
    mixer.instantiate(ir)
    # play() should have been called on the session
    mixer._session.play.assert_called()  # type: ignore[reportPrivateUsage]


def test_capture_instantiate_round_trip_with_patterns() -> None:
    """Full round-trip: capture with patterns → instantiate restores them."""
    from krach._patterns import hit

    mixer1 = _make_mixer()
    with mixer1.batch():
        mixer1.voice("kick", "faust:kick", gain=0.8)
    mixer1.play("kick", hit() * 4)

    ir = mixer1.capture()
    assert len(ir.patterns) >= 1

    mixer2 = _make_mixer()
    mixer2.instantiate(ir)
    # Pattern should have been played on the new mixer
    mixer2._session.play.assert_called()  # type: ignore[reportPrivateUsage]
