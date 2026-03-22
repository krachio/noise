from pathlib import Path

from midiman_frontend.ir import Cat, Freeze
from midiman_frontend.pattern import Pattern

from krach._mixer import Voice, build_graph_ir, build_hit, build_step


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


def test_build_step_returns_frozen_compound() -> None:
    """build_step returns Freeze(Fast(2, Cat([Stack(onset), reset])))."""
    pat = build_step("bass", ("freq", "gate"), pitch=55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze), f"expected Freeze, got {type(pat.node).__name__}"


def test_build_step_with_extra_params() -> None:
    pat = build_step("bass", ("freq", "gate", "cutoff"), pitch=55.0, cutoff=800.0)
    assert isinstance(pat.node, Freeze)


def test_build_step_skips_unknown_controls() -> None:
    pat = build_step("bass", ("freq", "gate"), pitch=55.0, reverb=0.8)
    assert isinstance(pat.node, Freeze)


def test_build_step_gate_only_voice() -> None:
    pat = build_step("pad", ("gate",), pitch=440.0)
    assert isinstance(pat.node, Freeze)


def test_build_step_no_triggerable_controls_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="no triggerable controls"):
        build_step("osc", ("waveform",), pitch=440.0)


# ── build_hit ─────────────────────────────────────────────────────────────────


def test_build_hit_returns_frozen_compound() -> None:
    """build_hit returns Freeze(Fast(2, Cat([trig, reset])))."""
    pat = build_hit("kit", "kick")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)


# ── Pattern algebra compatibility ─────────────────────────────────────────────


def test_step_combinable_with_add() -> None:
    """Two steps combined = Cat of 2 Freeze compounds (not flat atoms)."""
    s1 = build_step("bass", ("freq", "gate"), pitch=55.0)
    s2 = build_step("bass", ("freq", "gate"), pitch=73.0)
    combined = s1 + s2
    assert isinstance(combined, Pattern)
    assert isinstance(combined.node, Cat)
    assert len(combined.node.children) == 2  # 2 Freeze compounds


def test_rest_plus_hit_is_two_atoms() -> None:
    """rest() + hit() should be 2 atoms — hit fires at 1/2, not 1/3."""
    from midiman_frontend.pattern import rest
    pat = rest() + build_hit("kit", "kick")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 2  # Silence + Freeze


def test_hit_usable_with_over() -> None:
    h = build_hit("kit", "kick")
    stretched = (h * 4).over(2)
    assert isinstance(stretched, Pattern)


# ── @dsp decorator ────────────────────────────────────────────────────────────


def test_dsp_decorator_captures_source_and_transpiles() -> None:
    from faust_dsl import Signal, control
    from faust_dsl.lib.oscillators import sine_osc
    from faust_dsl.music.envelopes import adsr

    from krach._mixer import DspDef, dsp

    @dsp
    def my_synth() -> Signal:
        freq = control("freq", 440.0, 20.0, 4000.0)
        gate = control("gate", 0.0, 0.0, 1.0)
        return sine_osc(freq) * adsr(0.01, 0.1, 0.5, 0.2, gate) * 0.5

    assert isinstance(my_synth, DspDef)
    assert "def my_synth" in my_synth.source
    assert "freq" in my_synth.controls
    assert "gate" in my_synth.controls
    assert 'import("stdfaust.lib")' in my_synth.faust


# ── VoiceMixer.batch ─────────────────────────────────────────────────────────


def test_batch_defers_rebuild() -> None:
    """Inside batch(), voice() updates state but does not rebuild.
    After batch exits, all voices are present."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:kick", "faust:bass", "dac", "gain"]
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
