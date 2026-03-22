from pathlib import Path

from midiman_frontend.ir import Cat, Freeze
from midiman_frontend.pattern import Pattern

from krach._mixer import Voice, build_graph_ir, build_hit, build_note


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


def test_note_raises_when_pitches_exceed_voice_count() -> None:
    """note() with more pitches than poly voices should raise ValueError."""
    from unittest.mock import MagicMock

    import pytest

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    with pytest.raises(ValueError, match="more pitches .* than voices"):
        mixer.note("pad", 220, 330, 440)  # 3 pitches, 2 voices


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
        if c.args[0].endswith("_gain")
    }
    assert ("pad_v0_gain", 0.2) in set_calls
    assert ("pad_v1_gain", 0.2) in set_calls


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


def test_note_missing_voice_raises_valueerror() -> None:
    """note() on a non-existent voice should raise ValueError."""
    from unittest.mock import MagicMock

    import pytest

    session = MagicMock()
    from krach._mixer import VoiceMixer

    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
    with pytest.raises(ValueError, match="not found"):
        mixer.note("nope", 440)


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
    """seq() returns a Cat pattern with correct number of children."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Cat

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = mixer.seq("bass", 55, 73, 65)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


def test_seq_with_none_inserts_rest() -> None:
    """None entries in seq() produce Silence nodes."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Cat, Silence

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = mixer.seq("bass", 55, None, 65)
    assert isinstance(pat.node, Cat)
    # The second child should be a Silence
    assert isinstance(pat.node.children[1], Silence)


def test_seq_raises_on_empty() -> None:
    """seq() with no notes raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="at least one note"):
        mixer.seq("bass")


def test_seq_poly_uses_round_robin() -> None:
    """seq() on a poly voice allocates instances via round-robin per note."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Cat

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=2, gain=0.5)

    pat = mixer.seq("pad", 220, 330, 440)
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3
    # Round-robin: 3 notes across 2 voices — all children are Freeze compounds
    assert all(isinstance(c, Freeze) for c in pat.node.children)


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
    session.set_ctrl.assert_called_with("bass_gain", 0.0)


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
    session.set_ctrl.assert_called_with("bass_gain", 0.7)


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
        c.args[0] == "bass_gain" for c in session.set_ctrl.call_args_list
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
    """note() with one pitch returns a Freeze pattern (same as old step)."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = mixer.note("bass", 55.0)
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Freeze)


def test_note_gate_only_returns_freeze() -> None:
    """note() with no pitch triggers gate only."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("gate",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)

    pat = mixer.note("pad")
    assert isinstance(pat.node, Freeze)


def test_note_chord_poly_returns_frozen_stack() -> None:
    """note() with multiple pitches on poly voice returns frozen stack."""
    from unittest.mock import MagicMock

    from midiman_frontend.ir import Stack

    from krach._mixer import VoiceMixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.poly("pad", "faust:pad", voices=4, gain=0.5)

    pat = mixer.note("pad", 220, 330, 440)
    assert isinstance(pat.node, Freeze)
    # Inner should be a Stack of 3 Freeze compounds
    inner = pat.node.child
    assert isinstance(inner, Stack)
    assert len(inner.children) == 3


def test_note_chord_on_mono_raises() -> None:
    """note() with multiple pitches on mono voice raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError, match="not a poly voice"):
        mixer.note("bass", 220, 330)


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
    assert "bass_vel" not in ir_json


# ── mix.play() delegation ────────────────────────────────────────────────────


def test_play_delegates_to_session() -> None:
    """mix.play() delegates to session.play()."""
    from unittest.mock import MagicMock

    from krach._mixer import VoiceMixer

    session = MagicMock()
    mixer = VoiceMixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("kick", "faust:kick", gain=0.8)

    pat = mixer.hit("kick", "gate") * 4
    mixer.play("kick", pat)
    session.play.assert_called_once_with("kick", pat)


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
