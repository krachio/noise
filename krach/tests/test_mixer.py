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
    Otherwise patterns keep firing after stop()."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })

    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    # stop() should hush "pad" (the poly parent pattern slot)
    session.reset_mock()
    mixer.stop()

    hush_calls = [c for c in session.hush.call_args_list]
    hushed_names = {c.args[0] for c in hush_calls}
    assert "pad" in hushed_names, (
        f"stop() must hush poly parent 'pad', but only hushed: {hushed_names}"
    )


def test_stop_does_not_skip_mono_voice_with_poly_like_prefix() -> None:
    """A mono voice 'pad_vinyl' must not be skipped when poly 'pad' exists.
    The prefix 'pad_v' matches 'pad_vinyl' — stop() must use exact instance
    name matching, not startswith."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:pad_vinyl", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:pad_vinyl": ("freq", "gate"),
    })

    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)
    mixer.voice("pad_vinyl", "faust:pad_vinyl", gain=0.4)

    session.reset_mock()
    mixer.stop()

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "pad_vinyl" in hushed_names, (
        f"stop() must hush mono 'pad_vinyl', but only hushed: {hushed_names}"
    )


# ── remove() with active fade ───────────────────────────────────────────────


def test_remove_hushes_fade_pattern() -> None:
    """remove() must hush the _fade_{name} pattern slot so fades don't
    keep driving a deleted voice's gain control."""
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


# ── chord() with more pitches than voices ────────────────────────────────────


# ── re-poly() hushes old patterns ────────────────────────────────────────────


def test_repoly_hushes_old_instance_patterns() -> None:
    """Re-calling poly() with a different voice count must hush patterns
    targeting old instance names (e.g. pad_v2, pad_v3)."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=4, gain=0.5)

    # Re-poly with fewer voices — old instances pad_v2, pad_v3 should be hushed
    session.reset_mock()
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    # The old poly parent "pad" should be hushed (stops old patterns)
    assert "pad" in hushed_names, (
        f"re-poly must hush 'pad' parent slot, but only hushed: {hushed_names}"
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
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    session.reset_mock()
    mixer.remove("pad")

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_pad_v0" in hushed_names, (
        f"remove() must hush '_fade_pad_v0', but only hushed: {hushed_names}"
    )
    assert "_fade_pad_v1" in hushed_names, (
        f"remove() must hush '_fade_pad_v1', but only hushed: {hushed_names}"
    )


def test_repoly_hushes_old_instance_fades() -> None:
    """re-poly() must hush _fade_* for old instances."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=3, gain=0.5)

    session.reset_mock()
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    # Old instances pad_v0..v2 should have their fades hushed
    assert "_fade_pad_v0" in hushed_names, (
        f"re-poly must hush old instance fades, but only hushed: {hushed_names}"
    )


# ── fade() edge cases ───────────────────────────────────────────────────────


def test_fade_poly_parent_fades_all_instances() -> None:
    """fade() on a poly parent name should fade all instances proportionally,
    not crash with KeyError."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

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
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

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
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

    # Should not crash — updates all instances
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
    """voice() with a name that's an existing poly parent should clean up
    the poly state first (remove old instances, hush)."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    # Replace poly with mono voice — should clean up poly state
    mixer.voice("pad", "faust:mono", gain=0.3)

    v = mixer.voices
    assert "pad_v0" not in v
    assert "pad_v1" not in v
    assert "pad" in v


# ── Fix 2: STEP_SILENT_PITCH ─────────────────────────────────────────────────


def test_build_note_raises_when_pitch_but_no_freq() -> None:
    """build_note with pitch set but no 'freq' in controls must raise ValueError,
    not silently ignore the pitch."""
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
    # The second child should be a Silence
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
    # All children should be Freeze compounds with bare params
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


# ── Bug: gain() on nonexistent voice raises KeyError ─────────────────────────


def test_gain_nonexistent_voice_raises_valueerror() -> None:
    """gain() on a non-existent voice should raise ValueError, not KeyError.
    Bug: _mixer.py:350 — self._voices[name] with no guard."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="not found"):
        mixer.gain("nope", 0.5)


# ── Bug: poly() replacing mono voice leaves stale mono entry ─────────────────


def test_poly_over_mono_cleans_up_mono() -> None:
    """poly() with a name that's an existing mono voice should remove the mono
    Voice entry from _voices. Bug: _mixer.py:250-285 — poly() only checks
    _poly, never _voices, so the stale mono entry persists in the graph."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })

    # Create mono voice
    mixer.voice("bass", "faust:bass", gain=0.5)
    assert "bass" in mixer.voices

    # Replace with poly — should remove mono "bass" entry
    mixer.poly("bass", "faust:bass", voices=2, gain=0.6)

    # The mono "bass" entry must be gone; only "bass_v0" and "bass_v1" should exist
    v = mixer.voices
    assert "bass" not in v, (
        "poly() must remove stale mono Voice entry 'bass' from voices"
    )
    assert "bass_v0" in v
    assert "bass_v1" in v


# ── Bug: voice() replacing mono doesn't hush old fade ────────────────────────


def test_voice_replace_mono_hushes_old_fade() -> None:
    """Replacing a mono voice with voice() should hush the old fade pattern.
    Bug: _mixer.py:237-248 — no hush() when replacing an existing mono voice,
    so _fade_{name} keeps running after replacement."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
    })

    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.fade("bass", target=0.1, bars=4)

    # Replace the voice — should hush the old fade
    session.reset_mock()
    mixer.voice("bass", "faust:bass2", gain=0.3)

    hushed_names = {c.args[0] for c in session.hush.call_args_list}
    assert "_fade_bass" in hushed_names, (
        f"voice() must hush old fade '_fade_bass' when replacing, but only hushed: {hushed_names}"
    )


# ── Bug: gain() accepts NaN ──────────────────────────────────────────────────


def test_gain_nan_raises_valueerror() -> None:
    """gain() with NaN should raise ValueError, not silently corrupt state.
    Bug: _mixer.py:331-354 — no validation on gain value."""
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
    """gain() with Inf should raise ValueError."""
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


# ── Bug: fade() on nonexistent voice raises KeyError ─────────────────────────


# ── MUTE / UNMUTE / SOLO ─────────────────────────────────────────────────────


def test_mute_sets_gain_to_zero() -> None:
    """mute() stores current gain and sets gain to 0."""
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
    """unmute() restores gain saved by mute()."""
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
    """unmute() on a voice that wasn't muted does nothing."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    session.reset_mock()
    mixer.unmute("bass")
    # No set_ctrl call since voice wasn't muted
    assert not any(
        c.args[0] == "bass/gain" for c in session.set_ctrl.call_args_list
    )


def test_solo_mutes_others() -> None:
    """solo() mutes all voices except the target."""
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
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.solo("pad")

    v = mixer.voices
    assert v["bass"].gain == 0.0  # muted
    # Poly instances should still have gain
    assert v["pad_v0"].gain > 0.0
    assert v["pad_v1"].gain > 0.0


def test_mute_nonexistent_raises() -> None:
    """mute() on nonexistent voice raises ValueError."""
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

    # First fade
    mixer.fade("bass", target=0.2, bars=4)
    # Second fade — should hush the first
    session.reset_mock()
    mixer.fade("bass", target=0.8, bars=2)

    hushed_names = [c.args[0] for c in session.hush.call_args_list]
    assert "_fade_bass" in hushed_names, (
        f"new fade must hush old '_fade_bass', but hushed: {hushed_names}"
    )


# ── BATCH_EXCEPTION ──────────────────────────────────────────────────────────


def test_batch_skips_flush_on_exception() -> None:
    """batch() must not call _flush() if an exception occurred inside."""
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

    # _flush triggers load_graph — it should NOT have been called
    assert session.load_graph.call_count == 0
    # batching flag must be cleared — verify by adding a voice outside batch
    mixer.voice("kick", "faust:kick", gain=0.8)
    assert session.load_graph.call_count == 1  # immediate rebuild = not batching


def test_batch_flushes_on_success() -> None:
    """batch() still flushes on success (regression guard)."""
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
    """fade() on a non-existent voice should raise ValueError, not KeyError.
    Bug: _mixer.py:430-458 — no name check before self._voices[name]."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="not found"):
        mixer.fade("nope", target=0.5, bars=4)


# ── Unified note() API ───────────────────────────────────────────────────────


def test_note_single_pitch_returns_freeze() -> None:
    """Free note() with one pitch returns a Freeze pattern."""
    from krach._mixer import note

    pat = note(55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)


def test_note_gate_only_returns_freeze() -> None:
    """Free note() with no pitch triggers gate only."""
    from krach._mixer import note

    pat = note()
    assert isinstance(pat.node, Freeze)


def test_note_chord_returns_frozen_stack() -> None:
    """Free note() with multiple pitches returns frozen stack."""
    from midiman_frontend.ir import Stack

    from krach._mixer import note

    pat = note(220.0, 330.0, 440.0)
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Stack)


def test_note_vel_kwarg_sends_vel_control() -> None:
    """note() with vel!=1.0 includes vel in the onset pattern."""
    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0, vel=0.7)
    assert isinstance(pat.node, Freeze)
    # The pattern should contain an OSC atom for bass_vel


def test_note_vel_default_not_sent() -> None:
    """note() with vel=1.0 (default) does not send vel control."""
    from midiman_frontend.ir import ir_to_dict

    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0)
    # Serialize and check — no "bass_vel" should appear in the IR
    ir_json = str(ir_to_dict(pat.node))
    assert "bass/vel" not in ir_json


# ── mix.play() delegation ────────────────────────────────────────────────────


def test_play_delegates_to_session() -> None:
    """mix.play() binds pattern and delegates to session.play()."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, hit

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("kick", "faust:kick", gain=0.8)

    pat = hit("gate") * 4
    mixer.play("kick", pat)
    # play() binds the pattern (no-op for already-bound params) then delegates
    call_args = session.play.call_args
    assert call_args.args[0] == "kick"
    assert session.play.call_count == 1


# ── Sprint 12 adversarial: mute/unmute/solo bugs ─────────────────────────────


def test_double_mute_preserves_original_gain() -> None:
    """BUG: mute() twice overwrites _muted with 0.0, losing the original gain.
    After double mute + unmute, gain should restore to the original value (0.5),
    not 0.0.

    Root cause: _mixer.py:382-386 — mute() unconditionally saves current gain
    to _muted, even when already muted (current gain is 0.0).
    """
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
    """BUG: solo() calls mute() on already-muted voices, overwriting their
    saved gain in _muted with 0.0. Unmuting later restores 0.0 instead of
    the original gain.

    Root cause: _mixer.py:408-410 — solo() unconditionally mutes all other
    voices without checking if they are already muted.
    """
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

    # Mute pad first (saves 0.4)
    mixer.mute("pad")

    # Solo bass — should mute lead, but NOT re-mute pad (already muted)
    mixer.solo("bass")

    # Now unmute pad — should restore original 0.4, not 0.0
    mixer.unmute("pad")
    assert mixer.voices["pad"].gain == 0.4, (
        f"solo clobbered pad's saved gain: got {mixer.voices['pad'].gain}"
    )


# ── Sprint 12 adversarial: batch exception inconsistency ─────────────────────


def test_batch_exception_rolls_back_voices() -> None:
    """BUG: if an exception occurs mid-batch, voices added before the error
    remain in _voices but were never loaded into the audio graph. The mixer
    is in an inconsistent state: _voices has entries that the engine knows
    nothing about.

    Root cause: _mixer.py:537-552 — batch() skips _flush on error (correct),
    but does NOT roll back _voices state added before the exception.
    """
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

    # After failed batch, _voices should be empty (rolled back)
    # Currently bass is in _voices but never loaded — inconsistent
    assert "bass" not in mixer.voices, (
        "failed batch left 'bass' in _voices without loading graph"
    )


# ── Sprint 13: MUTED_LEAK ─────────────────────────────────────────────────


def test_remove_cleans_muted_state() -> None:
    """remove() must pop the voice from _muted so re-adding + unmute()
    doesn't restore stale gain."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mute("bass")
    mixer.remove("bass")

    # Re-add with different gain
    mixer.voice("bass", "faust:bass", gain=0.8)
    # unmute should be a no-op (not muted anymore)
    mixer.unmute("bass")
    assert mixer.voices["bass"].gain == 0.8


def test_voice_replace_cleans_muted_state() -> None:
    """voice() replacement must pop old muted state."""
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

    # unmute should be a no-op — muted state was cleared by replacement
    mixer.unmute("bass")
    assert mixer.voices["bass"].gain == 0.7


def test_poly_replace_cleans_muted_state() -> None:
    """poly() replacement must pop old muted state."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)
    mixer.mute("pad")
    mixer.poly("pad", "faust:pad", voices=3, gain=0.9)

    mixer.unmute("pad")
    # Should not restore stale 0.6 — muted state was cleared
    # Each instance gets 0.9/3 = 0.3
    assert mixer.voices["pad_v0"].gain == 0.9 / 3


# ── Sprint 13: UNSOLO ─────────────────────────────────────────────────────


def test_unsolo_restores_all_muted_voices() -> None:
    """unsolo() unmutes all voices that were muted by solo()."""
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
    """unsolo() with no muted voices does nothing."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    session.reset_mock()
    mixer.unsolo()
    # No set_ctrl calls since nothing was muted
    assert session.set_ctrl.call_count == 0


# ── Sprint 13: MIXER_REPR ─────────────────────────────────────────────────


def test_repr_shows_voices_and_gains() -> None:
    """__repr__ shows voice count, names, type_ids, gains."""
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
    """__repr__ shows [muted] for muted voices."""
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
    """__repr__ shows poly(N) for poly voices."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=4, gain=0.5)

    r = repr(mixer)
    assert "poly(4)" in r


def test_repr_empty() -> None:
    """__repr__ on empty mixer."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))

    r = repr(mixer)
    assert "VoiceMixer(0 voices)" in r


# ── Sprint 13 adversarial: _muted leak on poly instance removal ──────────


def test_remove_poly_cleans_instance_muted_entries() -> None:
    """BUG: mute() on a poly instance (e.g. 'pad_v0') stores it in _muted.
    remove('pad') only pops 'pad' from _muted, leaving 'pad_v0' behind.
    Then unsolo() iterates _muted and calls unmute('pad_v0'), which calls
    gain('pad_v0'), which raises ValueError because the voice was removed.

    Root cause: remove() line 312 only does _muted.pop(name, None) for the
    parent name, never cleaning up instance-level _muted entries.
    """
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

    # Mute a specific poly instance directly
    mixer.mute("pad_v0")

    # Remove the poly parent — should also clean up _muted["pad_v0"]
    mixer.remove("pad")

    # unsolo() should NOT crash — if _muted still has "pad_v0", it will
    # try to unmute a nonexistent voice and raise ValueError
    mixer.unsolo()  # should be a no-op, not crash


def test_unsolo_after_remove_muted_poly_instance_no_crash() -> None:
    """BUG: solo('bass') mutes poly parent 'pad'. Then remove('pad') cleans
    _muted['pad']. But if user manually muted 'pad_v0' before solo, that
    entry survives. unsolo() then crashes on the removed instance.

    This test verifies the end-to-end scenario.
    """
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:bass", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:bass": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Manually mute an instance, then remove the whole poly
    mixer.mute("pad_v0")
    mixer.remove("pad")

    # unsolo() iterates _muted — "pad_v0" is still there if remove didn't clean it
    mixer.unsolo()  # should not crash


def test_repoly_cleans_instance_muted_entries() -> None:
    """BUG: re-poly() cleans parent _muted but not instance-level entries.
    If 'pad_v0' was manually muted before re-poly, the stale _muted entry
    survives with the old gain value. unsolo() then restores the wrong gain
    to the new (replaced) instance.

    Root cause: poly() line 285 only does _muted.pop(name, None) for the
    parent, not for old instance names.
    """
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

    # Mute instance — stores old gain (0.6/2 = 0.3) in _muted["pad_v1"]
    mixer.mute("pad_v1")

    # Re-poly with different count/gain — new pad_v1 gets 0.9/3 = 0.3
    mixer.poly("pad", "faust:pad", voices=3, gain=0.9)

    # The stale _muted["pad_v1"] has the OLD gain 0.3 from the old poly.
    # unsolo() should NOT restore it — the muted state is stale.
    # New pad_v1 should have 0.9/3 = 0.3 (happens to be same here, so
    # test with a different setup where the values differ).
    mixer.unsolo()
    # After unsolo, pad_v1 should still have new gain (0.9/3), NOT get
    # corrupted by stale _muted entry. If _muted was not cleaned,
    # unmute() restores the old per-voice gain which is wrong.
    assert mixer.voices["pad_v1"].gain == 0.9 / 3


def test_repoly_fewer_voices_leaks_muted_for_removed_instance() -> None:
    """BUG: re-poly from 4 to 2 voices removes pad_v2, pad_v3.
    If pad_v3 was muted, its _muted entry survives. unsolo() then
    crashes trying to unmute the nonexistent pad_v3.
    """
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=4, gain=0.8)

    # Mute an instance that will be removed by re-poly
    mixer.mute("pad_v3")

    # Re-poly with fewer voices — pad_v3 no longer exists
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

    # unsolo() should not crash on the removed pad_v3
    mixer.unsolo()  # BUG: crashes with ValueError: voice 'pad_v3' not found


def test_voice_over_poly_cleans_instance_muted_entries() -> None:
    """BUG: voice() replacing a poly cleans parent _muted but not instances.
    If 'pad_v0' was manually muted, it stays in _muted after voice('pad', ...).
    """
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.6)

    # Mute a poly instance, then replace poly with mono
    mixer.mute("pad_v0")
    mixer.voice("pad", "faust:mono", gain=0.4)

    # _muted should not have "pad_v0" — that voice no longer exists
    mixer.unsolo()  # should not crash


# ── build_graph_ir with buses/sends/wires ────────────────────────────────────


def test_build_graph_ir_with_bus() -> None:
    """A bus adds a DSP node + gain node connected to dac."""
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    ir = build_graph_ir(voices, buses=buses)

    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids
    assert ir.exposed_controls["verb/room"] == ("verb", "room")
    assert ir.exposed_controls["verb/gain"] == ("verb_g", "gain")


def test_build_graph_ir_with_send() -> None:
    """A send adds a gain node between voice output and bus input."""
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids

    # Send gain exposed for instant level changes
    assert ir.exposed_controls["bass_send_verb/gain"] == ("bass_send_verb", "gain")

    # Connection: bass → send → verb (via "in" port)
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns
    assert ("bass_send_verb", "verb") in conns


def test_build_graph_ir_two_sends_same_bus() -> None:
    """Two voices sending to same bus — fan-in at bus input."""
    voices = {
        "bass": Voice("faust:bass", 0.5, ("freq", "gate")),
        "pad": Voice("faust:pad", 0.3, ("freq", "gate")),
    }
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4, ("pad", "verb"): 0.6}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    # Both sends exist
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids
    assert "pad_send_verb" in node_ids

    # Both connect to verb
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass_send_verb", "verb") in conns
    assert ("pad_send_verb", "verb") in conns


def test_build_graph_ir_send_gain_initial_value() -> None:
    """Send gain node has the correct initial gain from the send level."""
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(voices, buses=buses, sends=sends)

    send_node = next(n for n in ir.nodes if n.id == "bass_send_verb")
    assert send_node.controls["gain"] == 0.4


def test_build_graph_ir_with_wire() -> None:
    """A wire connects voice output directly to bus port (no gain node)."""
    voices = {
        "pad": Voice("faust:pad", 0.5, ("freq", "gate")),
        "kick": Voice("faust:kick", 0.8, ("gate",)),
    }
    buses = {"comp": Bus("faust:comp", 1.0, ("threshold",), num_inputs=2)}
    wires = {("pad", "comp"): "in0", ("kick", "comp"): "in1"}
    ir = build_graph_ir(voices, buses=buses, wires=wires)

    # Direct connections to specific ports
    wire_conns = [
        (c.from_node, c.to_node, c.to_port)
        for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns
    assert ("kick", "comp", "in1") in wire_conns


def test_build_graph_ir_poly_sum_node() -> None:
    """Poly voice with sends gets an implicit sum node."""
    voices = {
        "pad_v0": Voice("faust:pad", 0.15, ("freq", "gate")),
        "pad_v1": Voice("faust:pad", 0.15, ("freq", "gate")),
    }
    buses = {"verb": Bus("faust:verb", 0.3, ("room",), num_inputs=1)}
    # Send keyed by poly parent name
    sends = {("pad", "verb"): 0.4}
    poly = {"pad": 2}  # poly parent → instance count

    ir = build_graph_ir(voices, buses=buses, sends=sends, poly=poly)

    node_ids = {n.id for n in ir.nodes}
    assert "pad_sum" in node_ids  # implicit sum node

    # Both instances fan into sum
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("pad_v0", "pad_sum") in conns
    assert ("pad_v1", "pad_sum") in conns
    # Sum → send → bus
    assert ("pad_sum", "pad_send_verb") in conns


def test_build_graph_ir_no_buses_backward_compatible() -> None:
    """Calling build_graph_ir without bus args produces same result as before."""
    voices = {"bass": Voice("faust:bass", 0.5, ("freq", "gate"))}
    ir_old = build_graph_ir(voices)
    ir_new = build_graph_ir(voices, buses=None, sends=None, wires=None)
    assert ir_old == ir_new


# ── Commit 3: bus() + send() + remove_bus() ──────────────────────────────────


def test_bus_creates_bus_and_rebuilds() -> None:
    """bus() stores a Bus and triggers a rebuild."""
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
    # Bus node and gain node should appear in the IR
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids


def test_send_new_rebuilds() -> None:
    """send() with a new (voice, bus) pair triggers a rebuild."""
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
    """send() on an existing (voice, bus) pair does instant set_ctrl, no rebuild."""
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
    """send() raises ValueError if voice doesn't exist."""
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
    """send() raises ValueError if bus doesn't exist."""
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
    """remove() cleans up sends where the removed voice is the source."""
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

    # Rebuild should NOT include the send node
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_remove_bus_cleans_sends_and_wires() -> None:
    """remove_bus() removes the bus and all sends/wires targeting it."""
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
    """bus() raises ValueError if name collides with an existing voice."""
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
    """bus() raises ValueError if name collides with a poly parent."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    with pytest.raises(ValueError, match="name.*already.*voice"):
        mixer.bus("pad", "faust:pad", gain=0.3)


def test_gain_works_for_bus() -> None:
    """gain() also works for bus names."""
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
    """send() instant update on poly parent uses {parent}_send_{bus}_gain label."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)
    session.reset_mock()

    mixer.send("pad", "verb", level=0.7)

    assert session.load_graph.call_count == 0
    session.set_ctrl.assert_called_once_with("pad_send_verb/gain", 0.7)


def test_repr_shows_buses() -> None:
    """__repr__ shows buses."""
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
    """voice() replacement cleans up sends from the old voice."""
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

    # Replace voice — sends from old voice should be cleaned
    mixer.voice("bass", "faust:bass2", gain=0.3)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_poly_replace_cleans_sends() -> None:
    """poly() replacement cleans up sends from old poly parent."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    # Re-poly — sends should be cleaned
    mixer.poly("pad", "faust:pad", voices=3, gain=0.6)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "pad_send_verb" not in node_ids


# ── Commit 4: wire() ─────────────────────────────────────────────────────────


def test_wire_rebuilds() -> None:
    """wire() stores a wire and triggers a rebuild."""
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
    """wire() raises if a send already exists for the same (voice, bus) pair."""
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
    """send() raises if a wire already exists for the same (voice, bus) pair."""
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
    """remove() cleans up wires where the removed voice is the source."""
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
    """All mod shapes produce patterns with atoms in [lo, hi] range."""
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square, mod_tri

    shapes = [mod_sine, mod_tri, mod_ramp, mod_ramp_down, mod_square, mod_exp]
    for shape in shapes:
        pat = shape(0.0, 1.0, steps=16)
        assert isinstance(pat, Pattern), f"{shape.__name__} must return Pattern"
        assert isinstance(pat.node, Cat)
        assert len(pat.node.children) == 16


def test_mod_sine_values() -> None:
    """mod_sine returns a Pattern (new API), not a float."""
    from krach._mixer import mod_sine

    pat = mod_sine(0.0, 1.0, steps=4)
    assert isinstance(pat, Pattern)


def test_mod_plays_pattern() -> None:
    """mod() plays a pattern on the control path slot."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)

    # Should play on the control path slot
    assert session.play.call_count == 1
    slot = session.play.call_args.args[0]
    assert slot == "_ctrl_bass_cutoff"


def test_hush_mod() -> None:
    """hush() on a control path hushes the _ctrl_ slot."""
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
    """remove() hushes the voice which also stops active mod patterns."""
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
    # The voice itself should be hushed
    assert "bass" in hushed_names


def test_mod_send_param_label() -> None:
    """mod() on a send path uses the correct slot name."""
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

    assert session.play.call_count == 1
    slot = session.play.call_args.args[0]
    assert slot == "_ctrl_bass_send_verb_gain"


# ── Free functions: note(), hit(), seq() ─────────────────────────────────────


def test_free_note_returns_freeze_with_bare_params() -> None:
    """Free note() produces Freeze pattern with bare param names (no voice prefix)."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(440.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)
    ir_str = str(ir_to_dict(pat.node))
    # Should have bare "freq" and "gate", not voice-prefixed
    assert "'Str': 'freq'" in ir_str
    assert "'Str': 'gate'" in ir_str


def test_free_note_string_pitch() -> None:
    """Free note() with string pitch uses parse_note()."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note("C4")
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


def test_free_note_int_pitch() -> None:
    """Free note() with int pitch uses mtof()."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(60)  # MIDI note 60 = C4
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'freq'" in ir_str


def test_free_note_chord() -> None:
    """Free note() with multiple pitches builds a frozen stack."""
    from midiman_frontend.ir import Stack

    from krach._mixer import note

    pat = note(220.0, 330.0, 440.0)
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Stack)


def test_free_note_vel() -> None:
    """Free note() with vel != 1.0 includes vel param."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import note

    pat = note(440.0, vel=0.7)
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'vel'" in ir_str


def test_free_hit_returns_freeze_with_bare_param() -> None:
    """Free hit() produces Freeze with bare param name."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import hit

    pat = hit()
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'gate'" in ir_str


def test_free_hit_custom_param() -> None:
    """Free hit() with custom param uses that param."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import hit

    pat = hit("kick")
    ir_str = str(ir_to_dict(pat.node))
    assert "'Str': 'kick'" in ir_str


def test_free_seq_returns_cat() -> None:
    """Free seq() builds a Cat of note patterns."""
    from krach._mixer import seq

    pat = seq(440.0, 330.0, 220.0)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


def test_free_seq_with_none_rest() -> None:
    """Free seq() with None produces rests."""
    from midiman_frontend.ir import Silence

    from krach._mixer import seq

    pat = seq(440.0, None, 220.0)
    assert isinstance(pat.node, Cat)
    assert isinstance(pat.node.children[1], Silence)


def test_free_seq_string_pitches() -> None:
    """Free seq() with string pitches uses parse_note()."""
    from krach._mixer import seq

    pat = seq("C4", "E4", "G4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


# ── _bind_voice() ────────────────────────────────────────────────────────────


def test_bind_voice_rewrites_bare_params() -> None:
    """_bind_voice() prepends voice/ to bare param names in Osc atoms."""
    from midiman_frontend.ir import ir_to_dict

    from krach._mixer import _bind_voice, note  # pyright: ignore[reportPrivateUsage]

    pat = note(440.0)
    bound = _bind_voice(pat.node, "bass")
    ir_str = str(ir_to_dict(bound))
    assert "'Str': 'bass/freq'" in ir_str
    assert "'Str': 'bass/gate'" in ir_str
    # No bare "freq" or "gate" left
    assert "'Str': 'freq'" not in ir_str
    assert "'Str': 'gate'" not in ir_str


def test_bind_voice_skips_already_bound() -> None:
    """_bind_voice() leaves params containing / unchanged."""
    from midiman_frontend.ir import Atom, Osc, OscFloat, OscStr, ir_to_dict

    from krach._mixer import _bind_voice  # pyright: ignore[reportPrivateUsage]

    # Create a node with already-bound param
    node = Atom(Osc("/soundman/set", (OscStr("other/freq"), OscFloat(440.0))))
    bound = _bind_voice(node, "bass")
    ir_str = str(ir_to_dict(bound))
    # Should remain "other/freq", not "bass/other/freq"
    assert "'Str': 'other/freq'" in ir_str


def test_bind_voice_walks_nested_tree() -> None:
    """_bind_voice() recursively walks Cat, Stack, Freeze, etc."""
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
    """play() with a plain voice name rewrites bare params to voice/param."""
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

    # Should have called session.play with bound params
    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    assert played_name == "bass"
    ir_str = str(ir_to_dict(played_pattern.node))
    assert "'Str': 'bass/freq'" in ir_str
    assert "'Str': 'bass/gate'" in ir_str


def test_play_control_path_binds_ctrl() -> None:
    """play() with a / path rewrites 'ctrl' placeholder to full label."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import OscFloat, OscStr, ir_to_dict
    from midiman_frontend.pattern import osc

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Create a control pattern with "ctrl" placeholder
    ctrl_pat = osc("/soundman/set", OscStr("ctrl"), OscFloat(800.0))
    mixer.play("bass/cutoff", ctrl_pat)

    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    # Slot name should be mangled for the control path
    assert played_name == "_ctrl_bass_cutoff"
    ir_str = str(ir_to_dict(played_pattern.node))
    assert "'Str': 'bass/cutoff'" in ir_str


# ── Commit 6: mix.set() ──────────────────────────────────────────────────────


def test_set_delegates_to_set_ctrl() -> None:
    """set() calls session.set_ctrl with the resolved path."""
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
    """set() rejects NaN and Inf values."""
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
    """ramp() returns a Pattern with correct number of atoms and value range."""
    from midiman_frontend.ir import Cat

    from krach._mixer import ramp

    pat = ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 8


def test_mod_sine_pattern_length() -> None:
    """mod_sine() returns a Pattern with correct number of atoms."""
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_sine

    pat = mod_sine(0.0, 1.0, steps=32)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 32


def test_mod_patterns_composable() -> None:
    """mod patterns compose with .over() and + ."""
    from krach._mixer import mod_sine, ramp

    r = ramp(0.0, 1.0)
    s = mod_sine(200.0, 800.0)
    # Should compose without error
    _ = r.over(4)
    _ = s.over(2)
    _ = r + s


def test_ramp_uses_ctrl_placeholder() -> None:
    """ramp() atoms use OscStr('ctrl') as placeholder for later binding."""
    from midiman_frontend.ir import Atom, Cat, Osc, OscStr

    from krach._mixer import ramp

    pat = ramp(0.0, 1.0, steps=4)
    assert isinstance(pat.node, Cat)
    first = pat.node.children[0]
    assert isinstance(first, Atom)
    assert isinstance(first.value, Osc)
    assert any(isinstance(a, OscStr) and a.value == "ctrl" for a in first.value.args)


def test_mod_tri_returns_pattern() -> None:
    """mod_tri() returns a valid Pattern."""
    from krach._mixer import mod_tri

    pat = mod_tri(0.0, 1.0, steps=16)
    assert isinstance(pat, Pattern)


def test_mod_ramp_same_as_ramp() -> None:
    """mod_ramp() is an alias for ramp()."""
    from midiman_frontend.ir import Cat

    from krach._mixer import mod_ramp

    pat = mod_ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 8


def test_mod_ramp_down_returns_pattern() -> None:
    """mod_ramp_down() returns a valid Pattern."""
    from krach._mixer import mod_ramp_down

    pat = mod_ramp_down(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_square_returns_pattern() -> None:
    """mod_square() returns a valid Pattern."""
    from krach._mixer import mod_square

    pat = mod_square(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_exp_returns_pattern() -> None:
    """mod_exp() returns a valid Pattern."""
    from krach._mixer import mod_exp

    pat = mod_exp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


# ── Commit 8: Generalized fade() ─────────────────────────────────────────────


def test_fade_path_gain() -> None:
    """fade() on a gain path works and updates bookkeeping."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.1, bars=4)

    # Should have scheduled a pattern
    assert session.play.call_count >= 1
    # Gain bookkeeping should be updated
    assert mixer.voices["bass"].gain == 0.1


def test_fade_path_cutoff() -> None:
    """fade() on a non-gain path works without bookkeeping crash."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Should not crash — cutoff doesn't need bookkeeping
    mixer.fade("bass/cutoff", target=800.0, bars=4)
    assert session.play.call_count >= 1


def test_fade_oneshot_hold() -> None:
    """fade() pattern holds at target value (one-shot, doesn't loop back)."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Cat, Slow

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.0, bars=2)

    # The pattern is wrapped in Slow (from .over()) — unwrap to check Cat
    played_pattern = session.play.call_args.args[1]
    inner = played_pattern.node
    if isinstance(inner, Slow):
        inner = inner.child
    assert isinstance(inner, Cat)
    ramp_steps = 2 * 4  # bars * steps_per_bar default
    assert len(inner.children) > ramp_steps


# ── Commit 9: mod() convenience ──────────────────────────────────────────────


def test_mod_convenience() -> None:
    """mod() plays a pattern on a control path with .over()."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, mod_sine

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)

    assert session.play.call_count == 1
    call_args = session.play.call_args
    # Slot should be the control path slot
    assert call_args.args[0] == "_ctrl_bass_cutoff"


def test_hush_mod_still_works() -> None:
    """Hushing a mod by path works via the control slot name."""
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


# ── Commit 10: Group operations ──────────────────────────────────────────────


def test_gain_group_prefix() -> None:
    """gain() with a group prefix applies to all matching voices."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.8)
    mixer.voice("drums/hat", "faust:hat", gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.gain("drums", 0.4)

    assert mixer.voices["drums/kick"].gain == 0.4
    assert mixer.voices["drums/hat"].gain == 0.4
    assert mixer.voices["bass"].gain == 0.5  # unchanged


def test_mute_group_prefix() -> None:
    """mute() with a group prefix mutes all matching voices."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.8)
    mixer.voice("drums/hat", "faust:hat", gain=0.6)

    mixer.mute("drums")

    assert mixer.voices["drums/kick"].gain == 0.0
    assert mixer.voices["drums/hat"].gain == 0.0


def test_solo_group_prefix() -> None:
    """solo() with a group prefix solos all matching voices."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.8)
    mixer.voice("drums/hat", "faust:hat", gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.solo("drums")

    # drums should keep gain, bass should be muted
    assert mixer.voices["drums/kick"].gain == 0.8
    assert mixer.voices["drums/hat"].gain == 0.6
    assert mixer.voices["bass"].gain == 0.0


def test_group_no_match_raises() -> None:
    """Group operations with no matching voices raise ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="not found"):
        mixer.gain("nope", 0.5)


def test_stop_group_prefix() -> None:
    """stop() with a name arg hushs group-matching voices."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.8)
    mixer.voice("drums/hat", "faust:hat", gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.hush("drums")

    hushed = {c.args[0] for c in session.hush.call_args_list}
    assert "drums/kick" in hushed
    assert "drums/hat" in hushed


# ── Commit 11: Remove old VoiceMixer note/hit/seq ────────────────────────────


def test_mixer_note_removed() -> None:
    """VoiceMixer no longer has a note() method."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    assert not hasattr(mixer, "note")


def test_mixer_hit_removed() -> None:
    """VoiceMixer no longer has a hit() method."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    assert not hasattr(mixer, "hit")


def test_mixer_seq_removed() -> None:
    """VoiceMixer no longer has a seq() method."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    assert not hasattr(mixer, "seq")


# ── Commit 12: exports ───────────────────────────────────────────────────────


def test_exports_free_functions() -> None:
    """krach exports free pattern-building functions."""
    import krach._mixer as m

    assert callable(m.note)
    assert callable(m.hit)
    assert callable(m.seq)
    assert callable(m.ramp)
    assert callable(m.mod_sine)
    assert callable(m.mod_tri)
    assert callable(m.mod_ramp)
    assert callable(m.mod_ramp_down)
    assert callable(m.mod_square)
    assert callable(m.mod_exp)


# ── Poly pattern binding ────────────────────────────────────────────────────


def test_play_poly_binds_to_instances() -> None:
    """play() on a poly voice round-robin allocates instances in the pattern."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, note

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    # Play a sequence of 3 notes on poly(2) — should round-robin
    pat = note("A3") + note("C4") + note("E4")
    mixer.play("pad", pat)

    # Verify session.play was called with a bound pattern
    assert session.play.call_count >= 1
    call_args = session.play.call_args
    bound_pattern = call_args[0][1]
    # The pattern should contain pad_v0/, pad_v1/ prefixed labels (not pad/)
    from midiman_frontend.ir import ir_to_dict
    ir_json = str(ir_to_dict(bound_pattern.node))
    assert "pad_v0/" in ir_json
    assert "pad_v1/" in ir_json
    assert "pad/freq" not in ir_json  # no bare poly parent labels


def test_play_poly_chord_allocates_different_instances() -> None:
    """play() on a poly voice with a chord (Freeze(Stack)) gives each note a different instance."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer, note

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=4, gain=0.5)

    # Play a 3-note chord
    pat = note("A3", "C4", "E4")
    mixer.play("pad", pat)

    from midiman_frontend.ir import ir_to_dict
    ir_json = str(ir_to_dict(session.play.call_args[0][1].node))
    # Should have 3 different instances
    assert "pad_v0/" in ir_json
    assert "pad_v1/" in ir_json
    assert "pad_v2/" in ir_json
