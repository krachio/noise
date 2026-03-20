from pathlib import Path

from midiman_frontend.ir import Atom, Cat, IrNode, Osc, OscFloat, OscStr
from midiman_frontend.pattern import Pattern

from krach._mixer import Voice, build_graph_ir, build_hit, build_step


def _osc_args(node: IrNode) -> tuple[str, float]:
    """Extract (label, value) from an Osc atom for concise assertions."""
    assert isinstance(node, Atom)
    assert isinstance(node.value, Osc)
    assert isinstance(node.value.args[0], OscStr)
    assert isinstance(node.value.args[1], OscFloat)
    return (node.value.args[0].value, node.value.args[1].value)


# ── build_graph_ir ────────────────────────────────────────────────────────────


def test_build_graph_ir_single_voice() -> None:
    voices = {
        "bass": Voice("faust:acid_bass", 0.3, ("freq", "gate", "cutoff")),
    }
    ir = build_graph_ir(voices)

    node_ids = {n.id for n in ir.nodes}
    assert node_ids == {"bass", "bass_g", "out"}
    assert len(ir.connections) == 2

    # Controls exposed as {voice}_{param}
    assert ir.exposed_controls["bass_freq"] == ("bass", "freq")
    assert ir.exposed_controls["bass_gate"] == ("bass", "gate")
    assert ir.exposed_controls["bass_cutoff"] == ("bass", "cutoff")
    assert ir.exposed_controls["bass_gain"] == ("bass_g", "gain")


def test_build_graph_ir_two_voices() -> None:
    voices = {
        "kit": Voice("faust:kit", 0.8, ("kick", "hat", "snare")),
        "bass": Voice("faust:acid_bass", 0.3, ("freq", "gate")),
    }
    ir = build_graph_ir(voices)

    assert len(ir.nodes) == 5  # kit, kit_g, bass, bass_g, out
    assert len(ir.connections) == 4

    assert ir.exposed_controls["kit_kick"] == ("kit", "kick")
    assert ir.exposed_controls["bass_freq"] == ("bass", "freq")
    assert ir.exposed_controls["kit_gain"] == ("kit_g", "gain")
    assert ir.exposed_controls["bass_gain"] == ("bass_g", "gain")


def test_build_graph_ir_empty_produces_dac_only() -> None:
    ir = build_graph_ir({})
    assert len(ir.nodes) == 1
    assert ir.nodes[0].id == "out"
    assert len(ir.connections) == 0
    assert len(ir.exposed_controls) == 0


def test_build_graph_ir_gain_node_has_initial_value() -> None:
    voices = {"bass": Voice("faust:acid_bass", 0.35, ("freq", "gate"))}
    ir = build_graph_ir(voices)

    gain_node = next(n for n in ir.nodes if n.id == "bass_g")
    assert gain_node.type_id == "gain"
    assert gain_node.controls["gain"] == 0.35


def test_build_graph_ir_with_init_values() -> None:
    voices = {
        "bass": Voice("faust:acid_bass", 0.3, ("freq", "gate"),
                       init=(("freq", 55.0), ("gate", 0.0))),
    }
    ir = build_graph_ir(voices)

    bass_node = next(n for n in ir.nodes if n.id == "bass")
    assert bass_node.controls["freq"] == 55.0
    assert bass_node.controls["gate"] == 0.0


# ── build_step ────────────────────────────────────────────────────────────────


def test_build_step_melodic() -> None:
    pat = build_step("bass", ("freq", "gate"), pitch=55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    children = pat.node.children
    assert len(children) == 3  # freq, gate_on, gate_off

    assert _osc_args(children[0]) == ("bass_freq", 55.0)
    assert _osc_args(children[1]) == ("bass_gate", 1.0)
    assert _osc_args(children[2]) == ("bass_gate", 0.0)


def test_build_step_with_extra_params() -> None:
    pat = build_step("bass", ("freq", "gate", "cutoff"), pitch=55.0, cutoff=800.0)
    assert isinstance(pat.node, Cat)
    children = pat.node.children
    assert len(children) == 4  # freq, cutoff, gate_on, gate_off

    assert _osc_args(children[0]) == ("bass_freq", 55.0)
    assert _osc_args(children[1]) == ("bass_cutoff", 800.0)
    assert _osc_args(children[2]) == ("bass_gate", 1.0)
    assert _osc_args(children[3]) == ("bass_gate", 0.0)


def test_build_step_skips_unknown_controls() -> None:
    """Extra params not in voice controls are silently ignored."""
    pat = build_step("bass", ("freq", "gate"), pitch=55.0, reverb=0.8)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3  # freq, gate_on, gate_off — no reverb


def test_build_step_gate_only_voice() -> None:
    """Voice with gate but no freq — pitch is ignored."""
    pat = build_step("pad", ("gate",), pitch=440.0)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 2  # gate_on, gate_off only


def test_build_step_no_triggerable_controls_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="no triggerable controls"):
        build_step("osc", ("waveform",), pitch=440.0)


# ── build_hit ─────────────────────────────────────────────────────────────────


def test_build_hit() -> None:
    pat = build_hit("kit", "kick")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    children = pat.node.children
    assert len(children) == 2

    assert _osc_args(children[0]) == ("kit_kick", 1.0)
    assert _osc_args(children[1]) == ("kit_kick", 0.0)


# ── Pattern algebra compatibility ─────────────────────────────────────────────


def test_step_combinable_with_add() -> None:
    s1 = build_step("bass", ("freq", "gate"), pitch=55.0)
    s2 = build_step("bass", ("freq", "gate"), pitch=73.0)
    combined = s1 + s2
    assert isinstance(combined, Pattern)
    assert isinstance(combined.node, Cat)
    # 3 atoms + 3 atoms, flattened to 6
    assert len(combined.node.children) == 6


def test_hit_usable_with_over() -> None:
    h = build_hit("kit", "kick")
    stretched = (h * 4).over(2)
    assert isinstance(stretched, Pattern)


# ── VoiceMixer.batch ─────────────────────────────────────────────────────────


def test_batch_defers_rebuild() -> None:
    """Inside batch(), voice() updates state but does not rebuild.
    After batch exits, all voices are present."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:bass": ("freq", "gate"),
    })

    with mixer.batch():
        mixer.voice("kick", "faust:kick", gain=0.8)
        mixer.voice("bass", "faust:bass", gain=0.3)
        # Inside batch: voices registered but load_graph not yet called
        assert "kick" in mixer.voices
        assert "bass" in mixer.voices
        assert session.load_graph.call_count == 0

    # After batch: exactly one load_graph call
    assert session.load_graph.call_count == 1


def test_voice_outside_batch_rebuilds_immediately() -> None:
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })

    mixer.voice("kick", "faust:kick", gain=0.8)
    assert session.load_graph.call_count == 1  # immediate rebuild
