from pathlib import Path

from midiman_frontend.ir import Cat, Freeze
from midiman_frontend.pattern import Pattern

from krach._mixer import Bus, Voice, build_graph_ir, build_hit, build_note


# ── build_graph_ir ────────────────────────────────────────────────────────────


def test_build_graph_ir_single_voice() -> None:
    voices = {
        "bass": Voice("faust:acid_bass", 0.3, ("freq", "gate", "cutoff")),
    }
    ir = build_graph_ir(voices)

    node_ids = {n.id for n in ir.nodes}
    assert node_ids == {"bass", "bass_g", "out"}
    assert len(ir.connections) == 2

    # Controls exposed as {voice}/{param}
    assert ir.exposed_controls["bass/freq"] == ("bass", "freq")
    assert ir.exposed_controls["bass/gate"] == ("bass", "gate")
    assert ir.exposed_controls["bass/cutoff"] == ("bass", "cutoff")
    assert ir.exposed_controls["bass/gain"] == ("bass_g", "gain")


def test_build_graph_ir_two_voices() -> None:
    voices = {
        "kit": Voice("faust:kit", 0.8, ("kick", "hat", "snare")),
        "bass": Voice("faust:acid_bass", 0.3, ("freq", "gate")),
    }
    ir = build_graph_ir(voices)

    assert len(ir.nodes) == 5  # kit, kit_g, bass, bass_g, out
    assert len(ir.connections) == 4

    assert ir.exposed_controls["kit/kick"] == ("kit", "kick")
    assert ir.exposed_controls["bass/freq"] == ("bass", "freq")
    assert ir.exposed_controls["kit/gain"] == ("kit_g", "gain")
    assert ir.exposed_controls["bass/gain"] == ("bass_g", "gain")


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


def test_build_graph_ir_poly_voice_expands_instances() -> None:
    """A voice with count>1 expands to N instances in the IR."""
    voices = {
        "pad": Voice("faust:pad", 0.6, ("freq", "gate"), count=2),
    }
    ir = build_graph_ir(voices)

    node_ids = {n.id for n in ir.nodes}
    assert "pad_v0" in node_ids
    assert "pad_v1" in node_ids
    assert "pad_v0_g" in node_ids
    assert "pad_v1_g" in node_ids
    # No bare "pad" node — instances only
    assert "pad" not in node_ids

    # Each instance gain = total gain / count
    g0 = next(n for n in ir.nodes if n.id == "pad_v0_g")
    assert g0.controls["gain"] == 0.3  # 0.6 / 2

    # Controls exposed per instance
    assert ir.exposed_controls["pad_v0/freq"] == ("pad_v0", "freq")
    assert ir.exposed_controls["pad_v1/gate"] == ("pad_v1", "gate")


def test_build_graph_ir_mono_voice_no_suffix() -> None:
    """A voice with count=1 uses name directly (no _v0 suffix)."""
    voices = {
        "bass": Voice("faust:bass", 0.5, ("freq", "gate"), count=1),
    }
    ir = build_graph_ir(voices)

    node_ids = {n.id for n in ir.nodes}
    assert "bass" in node_ids
    assert "bass_v0" not in node_ids


def test_build_graph_ir_poly_sum_node() -> None:
    """Poly voice with sends gets an implicit sum node."""
    voices = {
        "pad": Voice("faust:pad", 0.6, ("freq", "gate"), count=2),
    }
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("pad", "verb"): 0.4}

    ir = build_graph_ir(voices, buses=buses, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "pad_sum" in node_ids  # implicit sum node

    # Both instances fan into sum
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("pad_v0", "pad_sum") in conns
    assert ("pad_v1", "pad_sum") in conns
    # Sum → send → bus
    assert ("pad_sum", "pad_send_verb") in conns


def test_build_graph_ir_mono_no_sum_node() -> None:
    """Mono voice with sends does NOT get a sum node."""
    voices = {
        "bass": Voice("faust:bass", 0.5, ("freq", "gate"), count=1),
    }
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4}

    ir = build_graph_ir(voices, buses=buses, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_sum" not in node_ids
    # Direct: bass → send → verb
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns


# ── build_note ────────────────────────────────────────────────────────────────


def test_build_note_returns_frozen_compound() -> None:
    """build_note returns Freeze(Fast(2, Cat([Stack(onset), reset])))."""
    pat = build_note("bass", ("freq", "gate"), pitch=55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze), f"expected Freeze, got {type(pat.node).__name__}"


def test_build_note_with_extra_params() -> None:
    pat = build_note("bass", ("freq", "gate", "cutoff"), pitch=55.0, cutoff=800.0)
    assert isinstance(pat.node, Freeze)


def test_build_note_skips_unknown_controls() -> None:
    pat = build_note("bass", ("freq", "gate"), pitch=55.0, reverb=0.8)
    assert isinstance(pat.node, Freeze)


def test_build_note_gate_only_voice() -> None:
    pat = build_note("pad", ("gate",))
    assert isinstance(pat.node, Freeze)


def test_build_note_no_triggerable_controls_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="no triggerable controls"):
        build_note("osc", ("waveform",))


# ── build_hit ─────────────────────────────────────────────────────────────────


def test_build_hit_returns_frozen_compound() -> None:
    """build_hit returns Freeze(Fast(2, Cat([trig, reset])))."""
    pat = build_hit("kit", "kick")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)


# ── Pattern algebra compatibility ─────────────────────────────────────────────


def test_step_combinable_with_add() -> None:
    """Two steps combined = Cat of 2 Freeze compounds (not flat atoms)."""
    s1 = build_note("bass", ("freq", "gate"), pitch=55.0)
    s2 = build_note("bass", ("freq", "gate"), pitch=73.0)
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


# ── stop() with poly voices ─────────────────────────────────────────────────


def test_stop_hushes_poly_parent_slots() -> None:
    """stop() must hush the poly parent pattern slots (e.g. 'pad'),
    not just the individual instances ('pad_v0', 'pad_v1').
    """
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })

    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    session.reset_mock()
    mixer.stop()

    hush_calls = [c for c in session.hush.call_args_list]
    hushed_names = {c.args[0] for c in hush_calls}
    assert "pad" in hushed_names, (
        f"stop() must hush poly parent 'pad', but only hushed: {hushed_names}"
    )


def test_stop_does_not_skip_mono_voice_with_poly_like_prefix() -> None:
    """A mono voice 'pad_vinyl' must not be skipped when poly 'pad' exists."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:pad_vinyl", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:pad_vinyl": ("freq", "gate"),
    })

    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.voice("pad_vinyl", "faust:pad_vinyl", gain=0.4)

    session.reset_mock()
    mixer.stop()

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "pad_vinyl" in hushed_names, (
        f"stop() must hush mono 'pad_vinyl', but only hushed: {hushed_names}"
    )


# ── remove() with active fade ───────────────────────────────────────────────


def test_remove_hushes_fade_pattern() -> None:
    """remove() must hush the _fade_{name} pattern slot."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Start a fade — schedules _fade_bass pattern
    mixer.fade("bass", target=0.1, bars=4)
    assert session.play.call_count == 1

    # Remove the voice — must also hush _fade_bass
    session.reset_mock()
    mixer.remove("bass")

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_bass" in hushed_names, (
        f"remove() must hush '_fade_bass', but only hushed: {hushed_names}"
    )


# ── re-voice() with count change hushes old patterns ─────────────────────────


def test_revoice_hushes_old_instance_patterns() -> None:
    """Re-calling voice() with a different count must hush patterns
    targeting old instance names."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    # Re-voice with fewer count — old instances should be hushed
    session.reset_mock()
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "pad" in hushed_names, (
        f"re-voice must hush 'pad' parent slot, but only hushed: {hushed_names}"
    )


# ── fade lifecycle: hush/stop/remove must cancel fades ───────────────────────


def test_stop_hushes_fade_patterns() -> None:
    """stop() must hush _fade_* patterns so fades don't keep running."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.fade("bass", target=0.1, bars=4)

    session.reset_mock()
    mixer.stop()

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_bass" in hushed_names, (
        f"stop() must hush '_fade_bass', but only hushed: {hushed_names}"
    )


def test_remove_poly_hushes_instance_fades() -> None:
    """remove() on a poly voice must hush _fade_* for each instance."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    session.reset_mock()
    mixer.remove("pad")

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_pad_v0" in hushed_names, (
        f"remove() must hush '_fade_pad_v0', but only hushed: {hushed_names}"
    )
    assert "_fade_pad_v1" in hushed_names, (
        f"remove() must hush '_fade_pad_v1', but only hushed: {hushed_names}"
    )


def test_revoice_hushes_old_instance_fades() -> None:
    """re-voice() must hush _fade_* for old instances."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=3, gain=0.5)

    session.reset_mock()
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_pad_v0" in hushed_names, (
        f"re-voice must hush old instance fades, but only hushed: {hushed_names}"
    )


# ── fade() edge cases ───────────────────────────────────────────────────────


def test_fade_poly_parent_fades_all_instances() -> None:
    """fade() on a poly parent name should fade all instances proportionally."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    # Should not crash — fades all instances
    mixer.fade("pad", target=0.2, bars=4)


def test_fade_zero_bars_raises() -> None:
    """fade() with bars=0 should raise ValueError, not divide by zero."""
    from unittest.mock import MagicMock

    import pytest

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="bars.*must be"):
        mixer.fade("bass", target=0.1, bars=0)


# ── hush() completeness for poly instances ───────────────────────────────────


def test_hush_poly_stops_instance_patterns() -> None:
    """hush() on a poly parent must also hush individual instance pattern slots."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    session.reset_mock()
    mixer.hush("pad")

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "pad_v0" in hushed_names, (
        f"hush('pad') must hush instance 'pad_v0', but only hushed: {hushed_names}"
    )
    assert "pad_v1" in hushed_names, (
        f"hush('pad') must hush instance 'pad_v1', but only hushed: {hushed_names}"
    )


# ── gain() on poly parent ───────────────────────────────────────────────────


def test_gain_poly_parent_updates_all_instances() -> None:
    """gain() on a poly parent should update all instances proportionally."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    mixer.gain("pad", 0.4)

    # Each instance should get 0.4/2 = 0.2
    set_calls = {
        (c.args[0], c.args[1])
        for c in session.set_ctrl.call_args_list
        if c.args[0].endswith("/gain")
    }
    assert ("pad_v0/gain", 0.2) in set_calls
    assert ("pad_v1/gain", 0.2) in set_calls


# ── remove/step on missing name ─────────────────────────────────────────────


def test_remove_missing_voice_raises_valueerror() -> None:
    """remove() on a non-existent voice should raise ValueError, not KeyError."""
    from unittest.mock import MagicMock

    import pytest

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    with pytest.raises(ValueError, match="not found"):
        mixer.remove("nope")


def test_note_free_function_exists() -> None:
    """note() is now a free function, not a mixer method."""
    from krach._mixer import note

    pat = note(440.0)
    assert isinstance(pat, Pattern)


# ── voice/poly name collision ────────────────────────────────────────────────


def test_voice_over_poly_cleans_up_poly() -> None:
    """voice() replacing a poly voice with mono should clean up."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    # Replace poly with mono voice
    mixer.voice("pad", "faust:mono", gain=0.3)

    v = mixer.voices
    assert "pad" in v
    assert v["pad"].count == 1


# ── Fix 2: STEP_SILENT_PITCH ─────────────────────────────────────────────────


def test_build_note_raises_when_pitch_but_no_freq() -> None:
    """build_note with pitch set but no 'freq' in controls must raise ValueError."""
    import pytest

    with pytest.raises(ValueError, match="no 'freq' control"):
        build_note("pad", ("gate",), pitch=440.0)


# ── Fix 4: SEQ_SHORTHAND ─────────────────────────────────────────────────────


def test_seq_builds_cat_of_steps() -> None:
    """Free seq() returns a Cat pattern with correct number of children."""
    from midiman_frontend.ir import Cat

    from krach._mixer import seq

    pat = seq(55, 73, 65)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


def test_seq_with_none_inserts_rest() -> None:
    """None entries in free seq() produce Silence nodes."""
    from midiman_frontend.ir import Cat, Silence

    from krach._mixer import seq

    pat = seq(55, None, 65)
    assert isinstance(pat.node, Cat)
    assert isinstance(pat.node.children[1], Silence)


def test_seq_raises_on_empty() -> None:
    """Free seq() with no notes raises ValueError."""
    import pytest

    from krach._mixer import seq

    with pytest.raises(ValueError, match="at least one note"):
        seq()


def test_seq_produces_bare_params() -> None:
    """Free seq() produces notes with bare param names for later binding."""
    from midiman_frontend.ir import Cat, ir_to_dict

    from krach._mixer import seq

    pat = seq(220.0, 330.0, 440.0)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


# ── Bug: gain() on nonexistent voice raises KeyError ─────────────────────────


def test_gain_nonexistent_voice_raises_valueerror() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="not found"):
        mixer.gain("nope", 0.5)


# ── Bug: voice() replacing mono doesn't hush old fade ────────────────────────


def test_voice_replace_mono_hushes_old_fade() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
    })

    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.fade("bass", target=0.1, bars=4)

    session.reset_mock()
    mixer.voice("bass", "faust:bass2", gain=0.3)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_bass" in hushed_names, (
        f"voice() must hush old fade '_fade_bass' when replacing, but only hushed: {hushed_names}"
    )


# ── Bug: gain() accepts NaN ──────────────────────────────────────────────────


def test_gain_nan_raises_valueerror() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError):
        mixer.gain("bass", float("nan"))


def test_gain_inf_raises_valueerror() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError):
        mixer.gain("bass", float("inf"))


# ── MUTE / UNMUTE / SOLO ─────────────────────────────────────────────────────


def test_mute_sets_gain_to_zero() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mute("bass")

    assert mixer.voices["bass"].gain == 0.0
    session.set_ctrl.assert_called_with("bass/gain", 0.0)


def test_unmute_restores_gain() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.7)

    mixer.mute("bass")
    mixer.unmute("bass")

    assert mixer.voices["bass"].gain == 0.7
    session.set_ctrl.assert_called_with("bass/gain", 0.7)


def test_unmute_without_mute_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    session.reset_mock()
    mixer.unmute("bass")
    assert not any(
        c.args[0] == "bass/gain" for c in session.set_ctrl.call_args_list
    )


def test_solo_mutes_others() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:kit": ("gate",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.voice("pad", "faust:pad", gain=0.3)
    mixer.voice("kit", "faust:kit", gain=0.8)

    mixer.solo("bass")

    v = mixer.voices
    assert v["bass"].gain == 0.5  # unchanged
    assert v["pad"].gain == 0.0   # muted
    assert v["kit"].gain == 0.0   # muted


def test_solo_poly_voice() -> None:
    """solo() on a poly voice mutes all others, keeps target unmuted."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:bass", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.solo("pad")

    v = mixer.voices
    assert v["bass"].gain == 0.0  # muted
    # Poly parent gain should remain
    assert v["pad"].gain > 0.0


def test_mute_nonexistent_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="not found"):
        mixer.mute("nope")


# ── FADE_CANCEL_OLD ──────────────────────────────────────────────────────────


def test_fade_cancels_existing_fade() -> None:
    """Starting a new fade must hush the existing fade pattern first."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass", target=0.2, bars=4)
    session.reset_mock()
    mixer.fade("bass", target=0.8, bars=2)

    hushed_names = [c.args[0] for c in session.hush.call_args_list]
    assert "_fade_bass" in hushed_names, (
        f"new fade must hush old '_fade_bass', but hushed: {hushed_names}"
    )


# ── BATCH_EXCEPTION ──────────────────────────────────────────────────────────


def test_batch_skips_flush_on_exception() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })

    with pytest.raises(ValueError):
        with mixer.batch():
            mixer.voice("kick", "faust:kick", gain=0.8)
            raise ValueError("user error")

    assert session.load_graph.call_count == 0
    mixer.voice("kick", "faust:kick", gain=0.8)
    assert session.load_graph.call_count == 1


def test_batch_flushes_on_success() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:kick", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })

    with mixer.batch():
        mixer.voice("kick", "faust:kick", gain=0.8)

    assert session.load_graph.call_count == 1


def test_fade_nonexistent_voice_raises_valueerror() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="not found"):
        mixer.fade("nope", target=0.5, bars=4)


# ── Unified note() API ───────────────────────────────────────────────────────


def test_note_single_pitch_returns_freeze() -> None:
    from krach._mixer import note

    pat = note(55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)


def test_note_gate_only_returns_freeze() -> None:
    from krach._mixer import note

    pat = note()
    assert isinstance(pat.node, Freeze)


def test_note_chord_returns_frozen_stack() -> None:
    from midiman_frontend.ir import Stack

    from krach._mixer import note

    pat = note(220.0, 330.0, 440.0)
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Stack)


def test_note_vel_kwarg_sends_vel_control() -> None:
    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0, vel=0.7)
    assert isinstance(pat.node, Freeze)


def test_note_vel_default_not_sent() -> None:
    from midiman_frontend.ir import ir_to_dict

    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0)
    ir_json = str(ir_to_dict(pat.node))
    assert "bass/vel" not in ir_json


# ── mix.play() delegation ────────────────────────────────────────────────────


def test_play_delegates_to_session() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, hit

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("kick", "faust:kick", gain=0.8)

    pat = hit("gate") * 4
    mixer.play("kick", pat)
    call_args = session.play.call_args
    assert call_args.args[0] == "kick"
    assert session.play.call_count == 1


# ── Sprint 12 adversarial: mute/unmute/solo bugs ─────────────────────────────


def test_double_mute_preserves_original_gain() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mute("bass")
    mixer.mute("bass")  # second mute should be no-op
    mixer.unmute("bass")

    assert mixer.voices["bass"].gain == 0.5, (
        f"double mute lost original gain: got {mixer.voices['bass'].gain}"
    )


def test_solo_does_not_clobber_previously_muted_voice() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:lead": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.voice("pad", "faust:pad", gain=0.4)
    mixer.voice("lead", "faust:lead", gain=0.3)

    mixer.mute("pad")
    mixer.solo("bass")
    mixer.unmute("pad")
    assert mixer.voices["pad"].gain == 0.4, (
        f"solo clobbered pad's saved gain: got {mixer.voices['pad'].gain}"
    )


# ── Sprint 12 adversarial: batch exception inconsistency ─────────────────────


def test_batch_exception_rolls_back_voices() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
    })

    try:
        with mixer.batch():
            mixer.voice("bass", "faust:bass", gain=0.5)
            raise RuntimeError("simulated error")
    except RuntimeError:
        pass

    assert "bass" not in mixer.voices, (
        "failed batch left 'bass' in _voices without loading graph"
    )


# ── Sprint 13: MUTED_LEAK ─────────────────────────────────────────────────


def test_remove_cleans_muted_state() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mute("bass")
    mixer.remove("bass")

    mixer.voice("bass", "faust:bass", gain=0.8)
    mixer.unmute("bass")
    assert mixer.voices["bass"].gain == 0.8


def test_voice_replace_cleans_muted_state() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mute("bass")
    mixer.voice("bass", "faust:bass2", gain=0.7)

    mixer.unmute("bass")
    assert mixer.voices["bass"].gain == 0.7


def test_poly_replace_cleans_muted_state() -> None:
    """voice() replacement with count changes must pop old muted state."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.mute("pad")
    mixer.voice("pad", "faust:pad", count=3, gain=0.9)

    mixer.unmute("pad")
    assert mixer.voices["pad"].gain == 0.9


# ── Sprint 13: UNSOLO ─────────────────────────────────────────────────────


def test_unsolo_restores_all_muted_voices() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:kit": ("gate",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.voice("pad", "faust:pad", gain=0.3)
    mixer.voice("kit", "faust:kit", gain=0.8)

    mixer.solo("bass")
    mixer.unsolo()

    v = mixer.voices
    assert v["bass"].gain == 0.5
    assert v["pad"].gain == 0.3
    assert v["kit"].gain == 0.8


def test_unsolo_with_nothing_muted_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    session.reset_mock()
    mixer.unsolo()
    assert session.set_ctrl.call_count == 0


# ── Sprint 13: MIXER_REPR ─────────────────────────────────────────────────


def test_repr_shows_voices_and_gains() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("kick", "faust:kick", gain=0.8)
    mixer.voice("bass", "faust:bass", gain=0.3)

    r = repr(mixer)
    assert "VoiceMixer(2 voices)" in r
    assert "kick" in r
    assert "faust:kick" in r
    assert "0.80" in r
    assert "bass" in r
    assert "faust:bass" in r
    assert "0.30" in r


def test_repr_shows_muted() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.mute("bass")

    r = repr(mixer)
    assert "[muted]" in r


def test_repr_shows_poly() -> None:
    """__repr__ shows poly(N) for voices with count>1."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    r = repr(mixer)
    assert "poly(4)" in r


def test_repr_empty() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    r = repr(mixer)
    assert "VoiceMixer(0 voices)" in r


# ── Sprint 13 adversarial: _muted leak on poly instance removal ──────────


def test_remove_poly_cleans_instance_muted_entries() -> None:
    """remove() on a poly voice must clean up instance-level _muted entries."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    # Mute a specific instance name directly via the instance naming convention
    # In new model, _inst_name("pad", 0, 2) = "pad_v0"
    # We mute "pad" parent instead (instances aren't directly exposed)
    mixer.mute("pad")

    mixer.remove("pad")

    # unsolo() should NOT crash
    mixer.unsolo()


def test_unsolo_after_remove_muted_poly_no_crash() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:bass", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mute("pad")
    mixer.remove("pad")

    # unsolo() iterates _muted — should not crash
    mixer.unsolo()


def test_revoice_cleans_instance_muted_entries() -> None:
    """re-voice with count change cleans old muted state."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    mixer.mute("pad")

    # Re-voice with different count/gain
    mixer.voice("pad", "faust:pad", count=3, gain=0.9)

    # unsolo() should NOT restore stale muted state
    mixer.unsolo()
    assert mixer.voices["pad"].gain == 0.9


def test_revoice_fewer_voices_no_crash() -> None:
    """re-voice from count=4 to count=2 should not crash on unsolo."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.8)

    mixer.mute("pad")

    # Re-voice with fewer count
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    # unsolo() should not crash
    mixer.unsolo()


def test_voice_over_poly_cleans_instance_muted_entries() -> None:
    """voice() replacing a poly cleans muted state."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    mixer.mute("pad")
    mixer.voice("pad", "faust:mono", gain=0.4)

    mixer.unsolo()  # should not crash


# ── build_graph_ir with buses/sends/wires ────────────────────────────────────


def test_build_graph_ir_with_bus() -> None:
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    ir = build_graph_ir(voices, buses=buses)

    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids
    assert ir.exposed_controls["verb/room"] == ("verb", "room")
    assert ir.exposed_controls["verb/gain"] == ("verb_g", "gain")


def test_build_graph_ir_with_send() -> None:
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids

    assert ir.exposed_controls["bass_send_verb/gain"] == ("bass_send_verb", "gain")

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns
    assert ("bass_send_verb", "verb") in conns


def test_build_graph_ir_two_sends_same_bus() -> None:
    voices = {
        "bass": Voice("faust:bass", 0.5, ("freq", "gate")),
        "pad": Voice("faust:pad", 0.3, ("freq", "gate")),
    }
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4, ("pad", "verb"): 0.6}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids
    assert "pad_send_verb" in node_ids

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass_send_verb", "verb") in conns
    assert ("pad_send_verb", "verb") in conns


def test_build_graph_ir_send_gain_initial_value() -> None:
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    send_node = next(n for n in ir.nodes if n.id == "bass_send_verb")
    assert send_node.controls["gain"] == 0.4


def test_build_graph_ir_with_wire() -> None:
    voices = {
        "pad": Voice("faust:pad", 0.5, ("freq", "gate")),
        "kick": Voice("faust:kick", 0.8, ("gate",)),
    }
    buses = {"comp": Bus("faust:comp", 1.0, ("threshold",), num_inputs=2)}
    wires = {("pad", "comp"): "in0", ("kick", "comp"): "in1"}
    ir = build_graph_ir(voices, buses=buses, wires=wires)

    wire_conns = [
        (c.from_node, c.to_node, c.to_port)
        for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns
    assert ("kick", "comp", "in1") in wire_conns


def test_build_graph_ir_no_buses_backward_compatible() -> None:
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    ir_old = build_graph_ir(voices)
    ir_new = build_graph_ir(voices, buses=None, sends=None, wires=None)
    assert ir_old == ir_new


# ── Commit 3: bus() + send() + remove_bus() ──────────────────────────────────


def test_bus_creates_bus_and_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.bus("verb", "faust:verb", gain=0.3)

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids


def test_send_new_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    session.reset_mock()

    mixer.send("bass", "verb", level=0.4)

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids


def test_send_update_instant() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)
    session.reset_mock()

    mixer.send("bass", "verb", level=0.7)

    assert session.load_graph.call_count == 0
    session.set_ctrl.assert_called_once_with("bass_send_verb/gain", 0.7)


def test_send_validates_voice_exists() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)

    with pytest.raises(ValueError, match="voice.*not found"):
        mixer.send("nope", "verb", level=0.4)


def test_send_validates_bus_exists() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="bus.*not found"):
        mixer.send("bass", "nope", level=0.4)


def test_remove_voice_cleans_sends() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.remove("bass")

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_remove_bus_cleans_sends_and_wires() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.remove_bus("verb")

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "verb" not in node_ids
    assert "bass_send_verb" not in node_ids


def test_bus_name_collision_with_voice_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="name.*already.*voice"):
        mixer.bus("bass", "faust:bass", gain=0.3)


def test_bus_name_collision_with_poly_raises() -> None:
    """bus() raises ValueError if name collides with a poly voice."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    with pytest.raises(ValueError, match="name.*already.*voice"):
        mixer.bus("pad", "faust:pad", gain=0.3)


def test_gain_works_for_bus() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    session.reset_mock()

    mixer.gain("verb", 0.8)

    session.set_ctrl.assert_called_once_with("verb/gain", 0.8)


def test_send_poly_parent_instant_update() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)
    session.reset_mock()

    mixer.send("pad", "verb", level=0.7)

    assert session.load_graph.call_count == 0
    session.set_ctrl.assert_called_once_with("pad_send_verb/gain", 0.7)


def test_repr_shows_buses() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)

    r = repr(mixer)
    assert "verb" in r
    assert "bus" in r.lower() or "faust:verb" in r


def test_voice_replace_cleans_sends() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.voice("bass", "faust:bass2", gain=0.3)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_poly_replace_cleans_sends() -> None:
    """voice() replacement with count change cleans up sends."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    # Re-voice — sends should be cleaned
    mixer.voice("pad", "faust:pad", count=3, gain=0.6)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "pad_send_verb" not in node_ids


# ── Commit 4: wire() ─────────────────────────────────────────────────────────


def test_wire_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:comp": ("threshold",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("comp", "faust:comp", gain=1.0)
    session.reset_mock()

    mixer.wire("pad", "comp", port="in0")

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    wire_conns = [
        (c.from_node, c.to_node, c.to_port) for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns


def test_wire_and_send_same_pair_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    with pytest.raises(ValueError, match="send already exists"):
        mixer.wire("pad", "verb", port="in0")


def test_send_and_wire_same_pair_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.wire("pad", "verb", port="in0")

    with pytest.raises(ValueError, match="wire already exists"):
        mixer.send("pad", "verb", level=0.4)


def test_remove_voice_cleans_wires() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:comp": ("threshold",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("comp", "faust:comp", gain=1.0)
    mixer.wire("pad", "comp", port="in0")

    mixer.remove("pad")

    ir = session.load_graph.call_args.args[0]
    wire_conns = [(c.from_node, c.to_node, c.to_port) for c in ir.connections]
    assert ("pad", "comp", "in0") not in wire_conns


# ── Commit 5: mod() + shapes ─────────────────────────────────────────────────


def test_mod_shapes_range() -> None:
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square, mod_tri

    shapes = [mod_sine, mod_tri, mod_ramp, mod_ramp_down, mod_square, mod_exp]
    for shape in shapes:
        pat = shape(0.0, 1.0, steps=16)
        assert isinstance(pat, Pattern), f"{shape.__name__} must return Pattern"
        assert isinstance(pat.node, Cat)
        assert len(pat.node.children) == 16


def test_mod_sine_values() -> None:
    from krach._mixer import mod_sine

    pat = mod_sine(0.0, 1.0, steps=4)
    assert isinstance(pat, Pattern)


def test_mod_plays_pattern() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)

    assert session.play_from_zero.call_count == 1
    slot = session.play_from_zero.call_args.args[0]
    assert slot == "_ctrl_bass_cutoff"


def test_hush_mod() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)
    session.reset_mock()

    mixer.hush("bass/cutoff")

    hushed = {c.args[0] for c in session.hush.call_args_list}
    assert "_ctrl_bass_cutoff" in hushed


def test_remove_voice_hushes_mods() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)
    session.reset_mock()

    mixer.remove("bass")

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "bass" in hushed_names


def test_mod_send_param_label() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)
    session.reset_mock()

    mixer.mod("bass_send_verb/gain", mod_sine(0.0, 1.0), bars=4)

    assert session.play_from_zero.call_count == 1
    slot = session.play_from_zero.call_args.args[0]
    assert slot == "_ctrl_bass_send_verb_gain"


# ── Free functions: note(), hit(), seq() ─────────────────────────────────────


def test_free_note_returns_freeze_with_bare_params() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(440.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str
    assert "'Str': 'gate'" in ir_str


def test_free_note_string_pitch() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note("C4")
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


def test_free_note_int_pitch() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(60)  # MIDI note 60 = C4
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


def test_free_note_chord() -> None:
    from midiman_frontend.ir import Stack

    from krach._mixer import note

    pat = note(220.0, 330.0, 440.0)
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Stack)


def test_free_note_vel() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(440.0, vel=0.7)
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'vel'" in ir_str


def test_free_hit_returns_freeze_with_bare_param() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import hit

    pat = hit()
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'gate'" in ir_str


def test_free_hit_custom_param() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import hit

    pat = hit("kick")
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'kick'" in ir_str


def test_free_seq_returns_cat() -> None:
    from krach._mixer import seq

    pat = seq(440.0, 330.0, 220.0)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


def test_free_seq_with_none_rest() -> None:
    from midiman_frontend.ir import Silence

    from krach._mixer import seq

    pat = seq(440.0, None, 220.0)
    assert isinstance(pat.node, Cat)
    assert isinstance(pat.node.children[1], Silence)


def test_free_seq_string_pitches() -> None:
    from krach._mixer import seq

    pat = seq("C4", "E4", "G4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


# ── _bind_voice() ────────────────────────────────────────────────────────────


def test_bind_voice_rewrites_bare_params() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import _bind_voice, note  # pyright: ignore[reportPrivateUsage]

    pat = note(440.0)
    bound = _bind_voice(pat.node, "bass")
    ir_str = str(ir_to_dict(bound))
    assert "'Str': 'bass/freq'" in ir_str
    assert "'Str': 'bass/gate'" in ir_str
    assert "'Str': 'freq'" not in ir_str
    assert "'Str': 'gate'" not in ir_str


def test_bind_voice_skips_already_bound() -> None:
    from midiman_frontend.ir import Atom, Osc, OscFloat, OscStr, ir_to_dict

    from krach._mixer import _bind_voice  # pyright: ignore[reportPrivateUsage]

    node = Atom(Osc("/soundman/set", (OscStr("other/freq"), OscFloat(440.0))))
    bound = _bind_voice(node, "bass")
    ir_str = str(ir_to_dict(bound))
    assert "'Str': 'other/freq'" in ir_str


def test_bind_voice_walks_nested_tree() -> None:
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import _bind_voice, seq  # pyright: ignore[reportPrivateUsage]

    pat = seq(440.0, 330.0)
    bound = _bind_voice(pat.node, "pad")
    ir_str = str(ir_to_dict(bound))
    assert "'Str': 'pad/freq'" in ir_str
    assert "'Str': 'pad/gate'" in ir_str
    assert "'Str': 'freq'" not in ir_str


# ── mix.play() path dispatch ─────────────────────────────────────────────────


def test_play_voice_binds_pattern() -> None:
    from unittest.mock import MagicMock

    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import VoiceMixer, note

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = note(440.0)
    mixer.play("bass", pat)

    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    assert played_name == "bass"
    ir_str = str(ir_to_dict(played_pattern.node))
    assert "'Str': 'bass/freq'" in ir_str
    assert "'Str': 'bass/gate'" in ir_str


def test_play_control_path_binds_ctrl() -> None:
    from unittest.mock import MagicMock

    from midiman_frontend.ir import OscFloat, OscStr, ir_to_dict
    from midiman_frontend.pattern import osc

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    ctrl_pat = osc("/soundman/set", OscStr("ctrl"), OscFloat(800.0))
    mixer.play("bass/cutoff", ctrl_pat)

    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    assert played_name == "_ctrl_bass_cutoff"
    ir_str = str(ir_to_dict(played_pattern.node))
    assert "'Str': 'bass/cutoff'" in ir_str


# ── Commit 6: mix.set() ──────────────────────────────────────────────────────


def test_set_delegates_to_set_ctrl() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.set("bass/cutoff", 1200.0)

    session.set_ctrl.assert_called_with("bass/cutoff", 1200.0)


def test_set_validates_finite() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="finite"):
        mixer.set("bass/cutoff", float("nan"))

    with pytest.raises(ValueError, match="finite"):
        mixer.set("bass/cutoff", float("inf"))


# ── Commit 7: Control patterns — ramp(), mod_sine(), etc. ────────────────────


def test_ramp_pattern_values() -> None:
    from midiman_frontend.ir import Cat

    from krach._mixer import ramp

    pat = ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 8


def test_mod_sine_pattern_length() -> None:
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_sine

    pat = mod_sine(0.0, 1.0, steps=32)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 32


def test_mod_patterns_composable() -> None:
    from krach._mixer import mod_sine, ramp

    r = ramp(0.0, 1.0)
    s = mod_sine(200.0, 800.0)
    _ = r.over(4)
    _ = s.over(2)
    _ = r + s


def test_ramp_uses_ctrl_placeholder() -> None:
    from midiman_frontend.ir import Atom, Cat, Osc, OscStr

    from krach._mixer import ramp

    pat = ramp(0.0, 1.0, steps=4)
    assert isinstance(pat.node, Cat)
    first = pat.node.children[0]
    assert isinstance(first, Atom)
    assert isinstance(first.value, Osc)
    assert any(isinstance(a, OscStr) and a.value == "ctrl" for a in first.value.args)


def test_mod_tri_returns_pattern() -> None:
    from krach._mixer import mod_tri

    pat = mod_tri(0.0, 1.0, steps=16)
    assert isinstance(pat, Pattern)


def test_mod_ramp_same_as_ramp() -> None:
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_ramp

    pat = mod_ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 8


def test_mod_ramp_down_returns_pattern() -> None:
    from krach._mixer import mod_ramp_down

    pat = mod_ramp_down(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_square_returns_pattern() -> None:
    from krach._mixer import mod_square

    pat = mod_square(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_exp_returns_pattern() -> None:
    from krach._mixer import mod_exp

    pat = mod_exp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


# ── Commit 8: Generalized fade() ─────────────────────────────────────────────


def test_fade_path_gain() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.1, bars=4)

    assert session.play_from_zero.call_count >= 1
    assert mixer.voices["bass"].gain == 0.1


def test_fade_path_cutoff() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/cutoff", target=800.0, bars=4)
    assert session.play_from_zero.call_count >= 1


def test_fade_oneshot_hold() -> None:
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Cat, Slow

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.0, bars=2)

    played_pattern = session.play_from_zero.call_args.args[1]
    inner = played_pattern.node
    if isinstance(inner, Slow):
        inner = inner.child
    assert isinstance(inner, Cat)
    ramp_steps = 2 * 4  # bars * steps_per_bar default
    assert len(inner.children) > ramp_steps


# ── voice() with count parameter ─────────────────────────────────────────────


def test_voice_count_1_is_mono() -> None:
    """voice() with count=1 (default) creates a mono voice."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    v = mixer.voices
    assert "bass" in v
    assert v["bass"].count == 1


def test_voice_count_gt1_is_poly() -> None:
    """voice() with count>1 creates a polyphonic voice."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    v = mixer.voices
    assert "pad" in v
    assert v["pad"].count == 4


def test_voice_count_lt1_raises() -> None:
    """voice() with count<1 raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })

    with pytest.raises(ValueError, match="at least 1"):
        mixer.voice("pad", "faust:pad", count=0, gain=0.5)


def test_no_poly_method() -> None:
    """poly() method no longer exists."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    assert not hasattr(mixer, "poly")


def test_no_polyvoice_class() -> None:
    """PolyVoice class no longer exists."""
    import krach._mixer as m
    assert not hasattr(m, "PolyVoice")


def test_voice_dict_has_no_instances() -> None:
    """The voices dict stores parent names, not instance names."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    v = mixer.voices
    # Only "pad" — no "pad_v0", "pad_v1", etc.
    assert "pad" in v
    assert "pad_v0" not in v
    assert "pad_v1" not in v


def test_play_poly_voice_round_robin() -> None:
    """play() on a poly voice does round-robin allocation."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, note

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    pat = note(440.0)
    mixer.play("pad", pat)

    # Should have called session.play with "pad" as the slot
    assert session.play.call_count == 1
    call_args = session.play.call_args
    assert call_args.args[0] == "pad"


# ── Commit 5: tempo/slots properties on VoiceMixer ──────────────────────────


def test_tempo_property_read() -> None:
    """mix.tempo reads from session.tempo."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.tempo = 140.0
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    assert mixer.tempo == 140.0


def test_tempo_property_write() -> None:
    """mix.tempo = X sets session.tempo and sends command."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    mixer.tempo = 180.0
    assert session.tempo == 180.0


# ── Commit 6: VoiceHandle / BusHandle ────────────────────────────────────────


def test_voice_returns_handle() -> None:
    """voice() returns a VoiceHandle."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceHandle, VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)
    assert isinstance(h, VoiceHandle)
    assert h.name == "bass"


def test_handle_play_delegates_to_mixer() -> None:
    """handle.play(pattern) delegates to mixer.play(name, pattern)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer, hit

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    h = mixer.voice("kick", "faust:kick", gain=0.8)

    pat = hit()
    with patch.object(mixer, "play") as mock_play:
        h.play(pat)
        mock_play.assert_called_once_with("kick", pat)


def test_handle_play_control_path() -> None:
    """handle.play('cutoff', pattern) delegates to mixer.play('name/cutoff', pattern)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    pat = mod_sine(200.0, 800.0)
    with patch.object(mixer, "play") as mock_play:
        h.play("cutoff", pat)
        mock_play.assert_called_once_with("bass/cutoff", pat)


def test_handle_set_delegates() -> None:
    """handle.set('cutoff', 800.0) delegates to mixer.set('name/cutoff', 800.0)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "set") as mock_set:
        h.set("cutoff", 800.0)
        mock_set.assert_called_once_with("bass/cutoff", 800.0)


def test_handle_fade_delegates() -> None:
    """handle.fade('cutoff', 200.0, bars=8) delegates to mixer.fade(...)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "fade") as mock_fade:
        h.fade("cutoff", 200.0, bars=8)
        mock_fade.assert_called_once_with("bass/cutoff", 200.0, bars=8)


def test_handle_send_with_bus_handle() -> None:
    """handle.send(bus_handle, 0.3) delegates to mixer.send(name, bus_name, 0.3)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    with patch.object(mixer, "send") as mock_send:
        h.send(bh, 0.3)
        mock_send.assert_called_once_with("bass", "verb", 0.3)


def test_handle_mute_unmute() -> None:
    """handle.mute() / handle.unmute() delegate to mixer."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "mute") as mock_mute:
        h.mute()
        mock_mute.assert_called_once_with("bass")

    with patch.object(mixer, "unmute") as mock_unmute:
        h.unmute()
        mock_unmute.assert_called_once_with("bass")


def test_handle_hush() -> None:
    """handle.hush() delegates to mixer.hush(name)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "hush") as mock_hush:
        h.hush()
        mock_hush.assert_called_once_with("bass")


def test_handle_repr() -> None:
    """VoiceHandle repr shows voice info."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    r = repr(h)
    assert "VoiceHandle" in r
    assert "bass" in r
    assert "faust:bass" in r
    assert "gain=0.30" in r


def test_bus_returns_handle() -> None:
    """bus() returns a BusHandle."""
    from unittest.mock import MagicMock

    from krach._mixer import BusHandle, VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)
    assert isinstance(bh, BusHandle)
    assert bh.name == "verb"


def test_bus_handle_set() -> None:
    """bus_handle.set('room', 0.8) delegates to mixer.set('verb/room', 0.8)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    with patch.object(mixer, "set") as mock_set:
        bh.set("room", 0.8)
        mock_set.assert_called_once_with("verb/room", 0.8)


def test_bus_handle_repr() -> None:
    """BusHandle repr shows bus info."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    r = repr(bh)
    assert "BusHandle" in r
    assert "verb" in r
    assert "faust:verb" in r
    assert "gain=0.50" in r


# ── Meter ─────────────────────────────────────────────────────────────────


def test_meter_property() -> None:
    """VoiceMixer.meter delegates to session meter."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.meter = 4.0
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    # Read: delegates to session.meter
    assert mixer.meter == 4.0

    # Write: sets session.meter
    mixer.meter = 3.0
    assert session.meter == 3.0


# ── Phase-Reset: fade/mod use play_from_zero ──────────────────────────────


def test_fade_uses_play_from_zero() -> None:
    """fade() should use play_from_zero for control path patterns so they start from phase 0."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.fade("bass/cutoff", target=2000.0, bars=4)

    # The fade control path should use play_from_zero, not play
    assert session.play_from_zero.call_count == 1
    assert session.play.call_count == 0
    slot = session.play_from_zero.call_args.args[0]
    assert slot == "_ctrl_bass_cutoff"


def test_mod_uses_play_from_zero() -> None:
    """mod() should use play_from_zero so modulations start from phase 0."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)

    assert session.play_from_zero.call_count == 1
    assert session.play.call_count == 0
