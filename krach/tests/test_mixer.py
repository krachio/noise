from pathlib import Path

from krach.ir.pattern import AtomParams, PatternNode
from krach.ir.values import Control, Osc, Value
from krach.pattern.pattern import Pattern
from krach.pattern.primitives import atom_p, fold

from krach._types import Node
from krach._graph import build_graph_ir
from krach.pattern.builders import build_hit, build_note


def _collect_values(node: PatternNode) -> list[Value]:
    """Walk a PatternNode tree and collect all Atom values."""
    values: list[Value] = []

    def _visit(nd: PatternNode, _children: tuple[object, ...]) -> None:
        if nd.primitive == atom_p and isinstance(nd.params, AtomParams):
            values.append(nd.params.value)

    fold(node, _visit)
    return values


def _collect_control_labels(node: PatternNode) -> set[str]:
    """Walk a PatternNode tree and collect all Control labels."""
    return {v.label for v in _collect_values(node) if isinstance(v, Control)}


# ── build_graph_ir ────────────────────────────────────────────────────────────


def test_build_graph_ir_single_voice() -> None:
    nodes = {
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate", "cutoff")),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert node_ids == {"bass", "bass_g", "out"}
    assert len(ir.connections) == 2

    # Controls exposed as {voice}/{param}
    assert ir.exposed_controls["bass/freq"] == ("bass", "freq")
    assert ir.exposed_controls["bass/gate"] == ("bass", "gate")
    assert ir.exposed_controls["bass/cutoff"] == ("bass", "cutoff")
    assert ir.exposed_controls["bass/gain"] == ("bass_g", "gain")


def test_build_graph_ir_two_voices() -> None:
    nodes = {
        "kit": Node("faust:kit", 0.8, ("kick", "hat", "snare")),
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate")),
    }
    ir = build_graph_ir(nodes)

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
    nodes = {"bass": Node("faust:acid_bass", 0.35, ("freq", "gate"))}
    ir = build_graph_ir(nodes)

    gain_node = next(n for n in ir.nodes if n.id == "bass_g")
    assert gain_node.type_id == "gain"
    assert gain_node.controls["gain"] == 0.35


def test_build_graph_ir_with_init_values() -> None:
    nodes = {
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate"),
                       init=(("freq", 55.0), ("gate", 0.0))),
    }
    ir = build_graph_ir(nodes)

    bass_node = next(n for n in ir.nodes if n.id == "bass")
    assert bass_node.controls["freq"] == 55.0
    assert bass_node.controls["gate"] == 0.0


def test_build_graph_ir_poly_voice_expands_instances() -> None:
    """A voice with count>1 expands to N instances in the IR."""
    nodes = {
        "pad": Node("faust:pad", 0.6, ("freq", "gate"), count=2),
    }
    ir = build_graph_ir(nodes)

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
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate"), count=1),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "bass" in node_ids
    assert "bass_v0" not in node_ids


def test_build_graph_ir_poly_sum_node() -> None:
    """Poly voice with sends gets an implicit sum node."""
    nodes = {
        "pad": Node("faust:pad", 0.6, ("freq", "gate"), count=2),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("pad", "verb"): 0.4}

    ir = build_graph_ir(nodes, sends=sends)

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
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate"), count=1),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}

    ir = build_graph_ir(nodes, sends=sends)

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
    assert pat.node.primitive.name == "freeze", f"expected Freeze, got {type(pat.node).__name__}"


def test_build_note_with_extra_params() -> None:
    pat = build_note("bass", ("freq", "gate", "cutoff"), pitch=55.0, cutoff=800.0)
    assert pat.node.primitive.name == "freeze"
    labels = _collect_control_labels(pat.node)
    assert "bass/cutoff" in labels, "cutoff kwarg should appear as bass/cutoff in IR"


def test_build_note_skips_unknown_controls() -> None:
    pat = build_note("bass", ("freq", "gate"), pitch=55.0, reverb=0.8)
    assert pat.node.primitive.name == "freeze"
    labels = _collect_control_labels(pat.node)
    assert not any("reverb" in l for l in labels), "unknown control should not appear in IR"


def test_build_note_gate_only_voice() -> None:
    pat = build_note("pad", ("gate",))
    assert pat.node.primitive.name == "freeze"


def test_build_note_no_triggerable_controls_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="no triggerable controls"):
        build_note("osc", ("waveform",))


# ── build_hit ─────────────────────────────────────────────────────────────────


def test_build_hit_returns_frozen_compound() -> None:
    """build_hit returns Freeze(Fast(2, Cat([trig, reset])))."""
    pat = build_hit("kit", "kick")
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "freeze"


# ── Pattern algebra compatibility ─────────────────────────────────────────────


def test_step_combinable_with_add() -> None:
    """Two steps combined = Cat of 2 Freeze compounds (not flat atoms)."""
    s1 = build_note("bass", ("freq", "gate"), pitch=55.0)
    s2 = build_note("bass", ("freq", "gate"), pitch=73.0)
    combined = s1 + s2
    assert isinstance(combined, Pattern)
    assert combined.node.primitive.name == "cat"
    assert len(combined.node.children) == 2  # 2 Freeze compounds


def test_rest_plus_hit_is_two_atoms() -> None:
    """rest() + hit() should be 2 atoms — hit fires at 1/2, not 1/3."""
    from krach.pattern.pattern import rest
    pat = rest() + build_hit("kit", "kick")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 2  # Silence + Freeze


def test_hit_usable_with_over() -> None:
    h = build_hit("kit", "kick")
    stretched = (h * 4).over(2)
    assert isinstance(stretched, Pattern)


# ── @dsp decorator ────────────────────────────────────────────────────────────


def test_dsp_decorator_captures_source_and_transpiles() -> None:
    from krach.ir.signal import Signal
    from krach.signal.transpile import control
    from krach.signal.lib.oscillators import sine_osc
    from krach.signal.music.envelopes import adsr

    from krach._types import DspDef, dsp

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


# ── Mixer.batch ─────────────────────────────────────────────────────────


def test_batch_defers_rebuild() -> None:
    """Inside batch(), voice() updates state but does not rebuild.
    After batch exits, all voices are present."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:kick", "faust:bass", "dac", "gain"]
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:bass": ("freq", "gate"),
    })

    with mixer.batch():
        mixer.voice("kick", "faust:kick", gain=0.8)
        mixer.voice("bass", "faust:bass", gain=0.3)
        # Inside batch: voices registered but load_graph not yet called
        assert "kick" in mixer.nodes
        assert "bass" in mixer.nodes
        assert session.load_graph.call_count == 0

    # After batch: exactly one load_graph call
    assert session.load_graph.call_count == 1


def test_voice_outside_batch_rebuilds_immediately() -> None:
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Start a fade — schedules native automation
    mixer.fade("bass", target=0.1, bars=4)
    assert session.set_automation.call_count >= 1

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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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


def test_remove_missing_voice_is_noop() -> None:
    """remove() on a non-existent voice is a no-op (idempotent)."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.remove("nope")  # must not raise


def test_remove_group_removes_all_prefixed() -> None:
    """remove('drums') removes drums/kick and drums/hat."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:kick", "faust:hat", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:hat": ("gate",),
    })
    with mixer.batch():
        mixer.voice("drums/kick", "faust:kick", gain=0.8)
        mixer.voice("drums/hat", "faust:hat", gain=0.5)

    assert "drums/kick" in mixer.nodes
    assert "drums/hat" in mixer.nodes

    mixer.remove("drums")

    assert "drums/kick" not in mixer.nodes
    assert "drums/hat" not in mixer.nodes


def test_note_free_function_exists() -> None:
    """note() is now a free function, not a mixer method."""
    from krach.pattern.builders import note

    pat = note(440.0)
    assert isinstance(pat, Pattern)


# ── voice/poly name collision ────────────────────────────────────────────────


def test_voice_over_poly_cleans_up_poly() -> None:
    """voice() replacing a poly voice with mono should clean up."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)

    # Replace poly with mono voice
    mixer.voice("pad", "faust:mono", gain=0.3)

    v = mixer.node_data
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

    from krach.pattern.builders import seq

    pat = seq(55, 73, 65)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3


def test_seq_with_none_inserts_rest() -> None:
    """None entries in free seq() produce Silence nodes."""

    from krach.pattern.builders import seq

    pat = seq(55, None, 65)
    assert pat.node.primitive.name == "cat"
    assert pat.node.children[1].primitive.name == "silence"


def test_seq_raises_on_empty() -> None:
    """Free seq() with no notes raises ValueError."""
    import pytest

    from krach.pattern.builders import seq

    with pytest.raises(ValueError, match="at least one note"):
        seq()


def test_seq_produces_bare_params() -> None:
    """Free seq() produces notes with bare param names for later binding."""
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import seq

    pat = seq(220.0, 330.0, 440.0)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'freq'" in ir_str


# ── Bug: gain() on nonexistent voice raises KeyError ─────────────────────────


def test_gain_nonexistent_voice_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.gain("nope", 0.5)  # must not raise


# ── Bug: voice() replacing mono doesn't hush old fade ────────────────────────


def test_voice_replace_mono_hushes_old_fade() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError):
        mixer.gain("bass", float("nan"))


def test_gain_inf_raises_valueerror() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with pytest.raises(ValueError):
        mixer.gain("bass", float("inf"))


# ── MUTE / UNMUTE / SOLO ─────────────────────────────────────────────────────


def test_mute_sets_gain_to_zero() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mute("bass")

    assert mixer.node_data["bass"].gain == 0.0
    session.set_ctrl.assert_called_with("bass/gain", 0.0)


def test_unmute_restores_gain() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.7)

    mixer.mute("bass")
    mixer.unmute("bass")

    assert mixer.node_data["bass"].gain == 0.7
    session.set_ctrl.assert_called_with("bass/gain", 0.7)


def test_unmute_without_mute_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:kit": ("gate",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.voice("pad", "faust:pad", gain=0.3)
    mixer.voice("kit", "faust:kit", gain=0.8)

    mixer.solo("bass")

    v = mixer.node_data
    assert v["bass"].gain == 0.5  # unchanged
    assert v["pad"].gain == 0.0   # muted
    assert v["kit"].gain == 0.0   # muted


def test_solo_poly_voice() -> None:
    """solo() on a poly voice mutes all others, keeps target unmuted."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:bass", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.solo("pad")

    v = mixer.node_data
    assert v["bass"].gain == 0.0  # muted
    # Poly parent gain should remain
    assert v["pad"].gain > 0.0


def test_mute_nonexistent_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.mute("nope")  # must not raise


# ── FADE_CANCEL_OLD ──────────────────────────────────────────────────────────


def test_fade_cancels_existing_fade() -> None:
    """Starting a new fade replaces the existing automation."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass", target=0.2, bars=4)
    first_count = session.set_automation.call_count
    mixer.fade("bass", target=0.8, bars=2)
    # Second fade should issue another set_automation (replaces the first)
    assert session.set_automation.call_count > first_count


# ── BATCH_EXCEPTION ──────────────────────────────────────────────────────────


def test_batch_skips_flush_on_exception() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:kick", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })

    with mixer.batch():
        mixer.voice("kick", "faust:kick", gain=0.8)

    assert session.load_graph.call_count == 1


def test_fade_nonexistent_voice_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.fade("nope", target=0.5, bars=4)  # must not raise


# ── Unified note() API ───────────────────────────────────────────────────────


def test_note_single_pitch_returns_freeze() -> None:
    from krach.pattern.builders import note

    pat = note(55.0)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "freeze"


def test_note_gate_only_returns_freeze() -> None:
    from krach.pattern.builders import note

    pat = note()
    assert pat.node.primitive.name == "freeze"


def test_note_chord_returns_frozen_stack() -> None:

    from krach.pattern.builders import note

    pat = note(220.0, 330.0, 440.0)
    assert pat.node.primitive.name == "freeze"
    inner = pat.node.children[0]
    assert inner.primitive.name == "stack"


def test_note_vel_kwarg_sends_vel_control() -> None:
    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0, vel=0.7)
    assert pat.node.primitive.name == "freeze"
    labels = _collect_control_labels(pat.node)
    assert "bass/vel" in labels, "vel kwarg should produce bass/vel Control in IR"


def test_note_vel_default_not_sent() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    pat = build_note("bass", ("freq", "gate", "vel"), pitch=55.0)
    ir_json = str(pattern_node_to_dict(pat.node))
    assert "bass/vel" not in ir_json


# ── mix.play() delegation ────────────────────────────────────────────────────


def test_play_delegates_to_session() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.mute("bass")
    mixer.mute("bass")  # second mute should be no-op
    mixer.unmute("bass")

    assert mixer.node_data["bass"].gain == 0.5, (
        f"double mute lost original gain: got {mixer.node_data['bass'].gain}"
    )


def test_solo_does_not_clobber_previously_muted_voice() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    assert mixer.node_data["pad"].gain == 0.4, (
        f"solo clobbered pad's saved gain: got {mixer.node_data['pad'].gain}"
    )


# ── Sprint 12 adversarial: batch exception inconsistency ─────────────────────


def test_batch_exception_rolls_back_voices() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
    })

    try:
        with mixer.batch():
            mixer.voice("bass", "faust:bass", gain=0.5)
            raise RuntimeError("simulated error")
    except RuntimeError:
        pass

    assert "bass" not in mixer.nodes, (
        "failed batch left 'bass' in _voices without loading graph"
    )


def test_batch_exception_rolls_back_sends() -> None:
    """Failed batch must restore sends, wires, patterns, ctrl_values, muted."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "faust:verb", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })

    # Set up initial state
    with mixer.batch():
        mixer.voice("bass", "faust:bass", gain=0.5)
        mixer.voice("verb", "faust:verb", gain=0.3)

    mixer.send("bass", "verb", level=0.4)
    mixer.mute("bass")
    mixer.set("bass/freq", 220.0)

    # Snapshot pre-batch state
    sends_before = list(mixer.routing)
    muted_before = mixer.is_muted("bass")
    ctrl_before = dict(mixer.ctrl_values)

    try:
        with mixer.batch():
            mixer.send("bass", "verb", level=0.9)  # modify send
            mixer.unmute("bass")  # modify muted
            mixer.set("bass/freq", 440.0)  # modify ctrl
            raise RuntimeError("simulated error")
    except RuntimeError:
        pass

    assert list(mixer.routing) == sends_before, "sends not rolled back"
    assert mixer.is_muted("bass") == muted_before, "muted not rolled back"
    assert dict(mixer.ctrl_values) == ctrl_before, "ctrl_values not rolled back"


# ── Sprint 13: MUTED_LEAK ─────────────────────────────────────────────────


def test_remove_cleans_muted_state() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mute("bass")
    mixer.remove("bass")

    mixer.voice("bass", "faust:bass", gain=0.8)
    mixer.unmute("bass")
    assert mixer.node_data["bass"].gain == 0.8


def test_voice_replace_cleans_muted_state() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.mute("bass")
    mixer.voice("bass", "faust:bass2", gain=0.7)

    mixer.unmute("bass")
    assert mixer.node_data["bass"].gain == 0.7


def test_poly_replace_cleans_muted_state() -> None:
    """voice() replacement with count changes must pop old muted state."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.mute("pad")
    mixer.voice("pad", "faust:pad", count=3, gain=0.9)

    mixer.unmute("pad")
    assert mixer.node_data["pad"].gain == 0.9


# ── Sprint 13: UNSOLO ─────────────────────────────────────────────────────


def test_unsolo_restores_all_muted_voices() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:kit": ("gate",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.voice("pad", "faust:pad", gain=0.3)
    mixer.voice("kit", "faust:kit", gain=0.8)

    mixer.solo("bass")
    mixer.unsolo()

    v = mixer.node_data
    assert v["bass"].gain == 0.5
    assert v["pad"].gain == 0.3
    assert v["kit"].gain == 0.8


def test_unsolo_with_nothing_muted_is_noop() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    session.reset_mock()
    mixer.unsolo()
    assert session.set_ctrl.call_count == 0


# ── Sprint 13: MIXER_REPR ─────────────────────────────────────────────────


def test_repr_shows_voices_and_gains() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("kick", "faust:kick", gain=0.8)
    mixer.voice("bass", "faust:bass", gain=0.3)

    r = repr(mixer)
    assert "Mixer(2 nodes)" in r
    assert "kick" in r
    assert "faust:kick" in r
    assert "0.80" in r
    assert "bass" in r
    assert "faust:bass" in r
    assert "0.30" in r


def test_repr_shows_muted() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.mute("bass")

    r = repr(mixer)
    assert "[muted]" in r


def test_repr_shows_poly() -> None:
    """__repr__ shows poly(N) for voices with count>1."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    r = repr(mixer)
    assert "poly(4)" in r


def test_repr_empty() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    r = repr(mixer)
    assert "Mixer(0 nodes)" in r


# ── Sprint 13 adversarial: _muted leak on poly instance removal ──────────


def test_remove_poly_cleans_instance_muted_entries() -> None:
    """remove() on a poly voice must clean up instance-level _muted entries."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:bass", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    mixer.mute("pad")

    # Re-voice with different count/gain
    mixer.voice("pad", "faust:pad", count=3, gain=0.9)

    # unsolo() should NOT restore stale muted state
    mixer.unsolo()
    assert mixer.node_data["pad"].gain == 0.9


def test_revoice_fewer_voices_no_crash() -> None:
    """re-voice from count=4 to count=2 should not crash on unsolo."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:mono", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:mono": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    mixer.mute("pad")
    mixer.voice("pad", "faust:mono", gain=0.4)

    mixer.unsolo()  # should not crash


# ── build_graph_ir with buses/sends/wires ────────────────────────────────────


def test_build_graph_ir_with_bus() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids
    assert ir.exposed_controls["verb/room"] == ("verb", "room")
    assert ir.exposed_controls["verb/gain"] == ("verb_g", "gain")


def test_build_graph_ir_with_send() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids

    assert ir.exposed_controls["bass_send_verb/gain"] == ("bass_send_verb", "gain")

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns
    assert ("bass_send_verb", "verb") in conns


def test_build_graph_ir_two_sends_same_bus() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "pad": Node("faust:pad", 0.3, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4, ("pad", "verb"): 0.6}
    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids
    assert "pad_send_verb" in node_ids

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass_send_verb", "verb") in conns
    assert ("pad_send_verb", "verb") in conns


def test_build_graph_ir_send_gain_initial_value() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(nodes, sends=sends)

    send_node = next(n for n in ir.nodes if n.id == "bass_send_verb")
    assert send_node.controls["gain"] == 0.4


def test_build_graph_ir_with_wire() -> None:
    nodes = {
        "pad": Node("faust:pad", 0.5, ("freq", "gate")),
        "kick": Node("faust:kick", 0.8, ("gate",)),
        "comp": Node("faust:comp", 1.0, ("threshold",), num_inputs=2),
    }
    wires = {("pad", "comp"): "in0", ("kick", "comp"): "in1"}
    ir = build_graph_ir(nodes, wires=wires)

    wire_conns = [
        (c.from_node, c.to_node, c.to_port)
        for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns
    assert ("kick", "comp", "in1") in wire_conns


def test_build_graph_ir_no_buses_backward_compatible() -> None:
    nodes = {"bass": Node("faust:bass", 0.5, ("freq", "gate"))}
    ir_old = build_graph_ir(nodes)
    ir_new = build_graph_ir(nodes, sends=None, wires=None)
    assert ir_old == ir_new


# ── Commit 3: bus() + send() + remove_bus() ──────────────────────────────────


def test_bus_creates_bus_and_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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


def test_send_missing_source_is_noop_old() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("nope", "verb", level=0.4)  # must not raise


def test_send_missing_target_is_noop_old() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.send("bass", "nope", level=0.4)  # must not raise


def test_remove_voice_cleans_sends() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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


def test_bus_replaces_voice_with_same_name() -> None:
    """bus() replaces a voice with an effect node (unified model)."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("bass", "faust:bass", gain=0.3)
    node = mixer.get_node("bass")
    assert node is not None
    assert node.gain == 0.3
    assert node.num_inputs > 0


def test_bus_replaces_poly_voice() -> None:
    """bus() replaces a poly voice, cleaning up instances."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("pad", "faust:pad", gain=0.3)
    node = mixer.get_node("pad")
    assert node is not None
    assert node.count == 1  # bus is always mono
    assert node.num_inputs > 0


def test_gain_works_for_bus() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    session.reset_mock()

    mixer.gain("verb", 0.8)

    session.set_ctrl.assert_called_once_with("verb/gain", 0.8)


def test_send_poly_parent_instant_update() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach.pattern.builders import mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square, mod_tri

    shapes = [mod_sine, mod_tri, mod_ramp, mod_ramp_down, mod_square, mod_exp]
    for shape in shapes:
        pat = shape(0.0, 1.0, steps=16)
        assert isinstance(pat, Pattern), f"{shape.__name__} must return Pattern"
        assert pat.node.primitive.name == "cat"
        assert len(pat.node.children) == 16


def test_mod_sine_values() -> None:
    from krach.pattern.builders import mod_sine

    pat = mod_sine(0.0, 1.0, steps=4)
    assert isinstance(pat, Pattern)


def test_mod_plays_pattern() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import note

    pat = note(440.0)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "freeze"
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'freq'" in ir_str
    assert "'label': 'gate'" in ir_str


def test_free_note_string_pitch() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import note

    pat = note("C4")
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'freq'" in ir_str


def test_free_note_int_pitch() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import note

    pat = note(60)  # MIDI note 60 = C4
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'freq'" in ir_str


def test_free_note_chord() -> None:

    from krach.pattern.builders import note

    pat = note(220.0, 330.0, 440.0)
    assert pat.node.primitive.name == "freeze"
    inner = pat.node.children[0]
    assert inner.primitive.name == "stack"


def test_free_note_vel() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import note

    pat = note(440.0, vel=0.7)
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'vel'" in ir_str


def test_free_hit_returns_freeze_with_bare_param() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import hit

    pat = hit()
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "freeze"
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'gate'" in ir_str


def test_free_hit_custom_param() -> None:
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import hit

    pat = hit("kick")
    ir_str = str(pattern_node_to_dict(pat.node))
    assert "'label': 'kick'" in ir_str


def test_free_seq_returns_cat() -> None:
    from krach.pattern.builders import seq

    pat = seq(440.0, 330.0, 220.0)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3


def test_free_seq_with_none_rest() -> None:

    from krach.pattern.builders import seq

    pat = seq(440.0, None, 220.0)
    assert pat.node.primitive.name == "cat"
    assert pat.node.children[1].primitive.name == "silence"


def test_free_seq_string_pitches() -> None:
    from krach.pattern.builders import seq

    pat = seq("C4", "E4", "G4")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3


# ── bind_voice() ────────────────────────────────────────────────────────────


def test_bind_voice_rewrites_bare_params() -> None:
    from krach.pattern.bind import bind_voice
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import note

    pat = note(440.0)
    bound = bind_voice(pat.node, "bass")
    d_str = str(pattern_node_to_dict(bound))
    assert "'label': 'bass/freq'" in d_str
    assert "'label': 'bass/gate'" in d_str
    assert "'label': 'freq'" not in d_str
    assert "'label': 'gate'" not in d_str


def test_bind_voice_skips_already_bound() -> None:
    from krach.ir.pattern import AtomParams, PatternNode
    from krach.pattern.bind import bind_voice
    from krach.ir.values import Osc, OscFloat, OscStr
    from krach.pattern.primitives import atom_p
    from krach.pattern.serialize import pattern_node_to_dict

    node = PatternNode(atom_p, (), AtomParams(Osc("/audio/set", (OscStr("other/freq"), OscFloat(440.0)))))
    bound = bind_voice(node, "bass")
    d_str = str(pattern_node_to_dict(bound))
    assert "'Str': 'other/freq'" in d_str


def test_bind_voice_walks_nested_tree() -> None:
    from krach.pattern.bind import bind_voice
    from krach.pattern.serialize import pattern_node_to_dict

    from krach.pattern.builders import seq

    pat = seq(440.0, 330.0)
    bound = bind_voice(pat.node, "pad")
    d_str = str(pattern_node_to_dict(bound))
    assert "'label': 'pad/freq'" in d_str
    assert "'label': 'pad/gate'" in d_str
    assert "'label': 'freq'" not in d_str


# ── mix.play() path dispatch ─────────────────────────────────────────────────


def test_play_voice_binds_pattern() -> None:
    from unittest.mock import MagicMock

    from krach.pattern.serialize import pattern_node_to_dict

    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = note(440.0)
    mixer.play("bass", pat)

    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    assert played_name == "bass"
    ir_str = str(pattern_node_to_dict(played_pattern.node))
    assert "'label': 'bass/freq'" in ir_str
    assert "'label': 'bass/gate'" in ir_str


def test_play_control_path_binds_ctrl() -> None:
    from unittest.mock import MagicMock

    from krach.ir.values import OscFloat, OscStr
    from krach.pattern.pattern import osc
    from krach.pattern.serialize import pattern_node_to_dict

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    ctrl_pat = osc("/audio/set", OscStr("ctrl"), OscFloat(800.0))
    mixer.play("bass/cutoff", ctrl_pat)

    call_args = session.play.call_args
    played_name = call_args.args[0]
    played_pattern = call_args.args[1]
    assert played_name == "_ctrl_bass_cutoff"
    ir_str = str(pattern_node_to_dict(played_pattern.node))
    assert "'Str': 'bass/cutoff'" in ir_str


# ── Commit 6: mix.set() ──────────────────────────────────────────────────────


def test_set_delegates_to_set_ctrl() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.set("bass/cutoff", 1200.0)

    session.set_ctrl.assert_called_with("bass/cutoff", 1200.0)


def test_set_validates_finite() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="finite"):
        mixer.set("bass/cutoff", float("nan"))

    with pytest.raises(ValueError, match="finite"):
        mixer.set("bass/cutoff", float("inf"))


# ── Commit 7: Control patterns — ramp(), mod_sine(), etc. ────────────────────


def test_ramp_pattern_values() -> None:

    from krach.pattern.builders import ramp

    pat = ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 8


def test_mod_sine_pattern_length() -> None:

    from krach.pattern.builders import mod_sine

    pat = mod_sine(0.0, 1.0, steps=32)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 32


def test_mod_patterns_composable() -> None:
    from krach.pattern.builders import mod_sine, ramp

    r = ramp(0.0, 1.0)
    s = mod_sine(200.0, 800.0)
    _ = r.over(4)
    _ = s.over(2)
    _ = r + s


def test_ramp_uses_ctrl_placeholder() -> None:
    from krach.pattern.builders import ramp

    pat = ramp(0.0, 1.0, steps=4)
    assert pat.node.primitive.name == "cat"
    first = pat.node.children[0]
    assert first.primitive.name == "atom"
    assert isinstance(first.params, AtomParams)
    assert isinstance(first.params.value, Control)
    assert first.params.value.label == "ctrl"


def test_mod_tri_returns_pattern() -> None:
    from krach.pattern.builders import mod_tri

    pat = mod_tri(0.0, 1.0, steps=16)
    assert isinstance(pat, Pattern)


def test_mod_ramp_same_as_ramp() -> None:

    from krach.pattern.builders import mod_ramp

    pat = mod_ramp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 8


def test_mod_ramp_down_returns_pattern() -> None:
    from krach.pattern.builders import mod_ramp_down

    pat = mod_ramp_down(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_square_returns_pattern() -> None:
    from krach.pattern.builders import mod_square

    pat = mod_square(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


def test_mod_exp_returns_pattern() -> None:
    from krach.pattern.builders import mod_exp

    pat = mod_exp(0.0, 1.0, steps=8)
    assert isinstance(pat, Pattern)


# ── Commit 8: Generalized fade() ─────────────────────────────────────────────


def test_fade_path_gain() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.1, bars=4)

    session.set_automation.assert_called_once()
    args = session.set_automation.call_args
    assert args[0][1] == "ramp"  # shape
    assert args[1]["one_shot"] is True
    assert mixer.node_data["bass"].gain == 0.1


def test_fade_path_cutoff() -> None:
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/cutoff", target=800.0, bars=4)
    session.set_automation.assert_called_once()


def test_fade_oneshot_hold() -> None:
    """fade() sends a one-shot ramp automation (holds at target)."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", target=0.0, bars=2)

    session.set_automation.assert_called_once()
    args = session.set_automation.call_args
    assert args[0][0] == "bass/gain"  # label
    assert args[0][1] == "ramp"  # shape
    assert args[0][2] == 0.5  # lo (current gain)
    assert args[0][3] == 0.0  # hi (target)
    assert args[1]["one_shot"] is True


# ── voice() with count parameter ─────────────────────────────────────────────


def test_voice_count_1_is_mono() -> None:
    """voice() with count=1 (default) creates a mono voice."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    v = mixer.node_data
    assert "bass" in v
    assert v["bass"].count == 1


def test_voice_count_gt1_is_poly() -> None:
    """voice() with count>1 creates a polyphonic voice."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    v = mixer.node_data
    assert "pad" in v
    assert v["pad"].count == 4


def test_voice_count_lt1_raises() -> None:
    """voice() with count<1 raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })

    with pytest.raises(ValueError, match="at least 1"):
        mixer.voice("pad", "faust:pad", count=0, gain=0.5)


def test_no_poly_method() -> None:
    """poly() method no longer exists."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    assert not hasattr(mixer, "poly")


def test_no_polyvoice_class() -> None:
    """PolyVoice class no longer exists."""
    import krach._mixer as m
    assert not hasattr(m, "PolyVoice")


def test_voice_dict_has_no_instances() -> None:
    """The voices dict stores parent names, not instance names."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)

    v = mixer.node_data
    # Only "pad" — no "pad_v0", "pad_v1", etc.
    assert "pad" in v
    assert "pad_v0" not in v
    assert "pad_v1" not in v


def test_play_poly_voice_round_robin() -> None:
    """play() on a poly voice does round-robin allocation."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)

    pat = note(440.0)
    mixer.play("pad", pat)

    # Should have called session.play with "pad" as the slot
    assert session.play.call_count == 1
    call_args = session.play.call_args
    assert call_args.args[0] == "pad"


# ── Commit 5: tempo/slots properties on Mixer ──────────────────────────


def test_tempo_property_read() -> None:
    """mix.tempo reads from session.tempo."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 140.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    assert mixer.tempo == 140.0


def test_tempo_property_write() -> None:
    """mix.tempo = X sets session.tempo and sends command."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    mixer.tempo = 180.0
    assert session.tempo == 180.0


# ── Commit 6: NodeHandle / NodeHandle ────────────────────────────────────────


def test_voice_returns_handle() -> None:
    """voice() returns a NodeHandle."""
    from unittest.mock import MagicMock

    from krach._mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)
    assert isinstance(h, NodeHandle)
    assert h.name == "bass"


def test_handle_play_delegates_to_mixer() -> None:
    """handle.play(pattern) delegates to mixer.play(name, pattern)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "set") as mock_set:
        h.set("cutoff", 800.0)
        mock_set.assert_called_once_with("bass/cutoff", 800.0)


def test_handle_fade_delegates() -> None:
    """handle.fade('cutoff', 200.0, bars=8) delegates to mixer.fade(...)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "fade") as mock_fade:
        h.fade("cutoff", 200.0, bars=8)
        mock_fade.assert_called_once_with("bass/cutoff", 200.0, bars=8)


def test_handle_send_with_bus_handle() -> None:
    """handle.send(bus_handle, 0.3) delegates to mixer.send(name, bus_name, 0.3)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
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

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "hush") as mock_hush:
        h.hush()
        mock_hush.assert_called_once_with("bass")


def test_handle_repr() -> None:
    """NodeHandle repr shows voice info."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    r = repr(h)
    assert "Node" in r
    assert "bass" in r
    assert "faust:bass" in r
    assert "gain=0.30" in r


def test_bus_returns_handle() -> None:
    """bus() returns a NodeHandle."""
    from unittest.mock import MagicMock

    from krach._mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)
    assert isinstance(bh, NodeHandle)
    assert bh.name == "verb"


def test_bus_handle_set() -> None:
    """bus_handle.set('room', 0.8) delegates to mixer.set('verb/room', 0.8)."""
    from unittest.mock import MagicMock, patch

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    with patch.object(mixer, "set") as mock_set:
        bh.set("room", 0.8)
        mock_set.assert_called_once_with("verb/room", 0.8)


def test_bus_handle_repr() -> None:
    """NodeHandle repr shows bus info."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    r = repr(bh)
    assert "Node" in r
    assert "verb" in r
    assert "faust:verb" in r
    assert "gain=0.50" in r


# ── Meter ─────────────────────────────────────────────────────────────────


def test_meter_property() -> None:
    """Mixer.meter delegates to session meter."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    # Read: delegates to session.meter
    assert mixer.meter == 4.0

    # Write: sets session.meter
    mixer.meter = 3.0
    assert session.meter == 3.0


# ── Phase-Reset: fade/mod use play_from_zero ──────────────────────────────


def test_fade_uses_native_automation() -> None:
    """fade() with a path sends a native one-shot ramp automation."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.fade("bass/cutoff", target=2000.0, bars=4)

    # Should use native automation, not pattern-based play
    session.set_automation.assert_called_once()
    args = session.set_automation.call_args
    assert args[0][0] == "bass/cutoff"  # label
    assert args[0][1] == "ramp"  # shape
    assert args[1]["one_shot"] is True
    session.play_from_zero.assert_not_called()
    session.play.assert_not_called()


def test_mod_uses_play_from_zero() -> None:
    """mod() should use play_from_zero so modulations start from phase 0."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.mod("bass/cutoff", mod_sine(200.0, 2000.0), bars=4)

    assert session.play_from_zero.call_count == 1
    assert session.play.call_count == 0


# ── Pattern retrieval ─────────────────────────────────────────────────────


def test_pattern_retrieval() -> None:
    """play() stores the unbound pattern and pattern() retrieves it."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    pat = note(440.0)
    mixer.play("bass", pat)

    assert mixer.pattern("bass") is pat


def test_pattern_retrieval_unknown_returns_none() -> None:
    """pattern() returns None for unknown names."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    assert mixer.pattern("nope") is None


def test_handle_pattern_retrieval() -> None:
    """NodeHandle.pattern() delegates to mixer.pattern()."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    handle = mixer.voice("bass", "faust:bass", gain=0.5)

    pat = note(440.0)
    handle.play(pat)

    assert handle.pattern() is pat


# ── Stage 1: add_voice slash labels (1.1) ────────────────────────────────────


def test_add_voice_uses_slash_labels() -> None:
    """Incremental add_voice sends /‑separated exposed control labels."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
        "faust:bass": ("freq", "gate"),
    })

    # Load initial graph so graph is loaded (enables incremental add_voice)
    mixer.voice("kick", "faust:kick", gain=0.8)
    assert session.load_graph.call_count == 1

    # Adding a second mono voice triggers add_voice (incremental path)
    session.reset_mock()
    mixer.voice("bass", "faust:bass", gain=0.3)

    session.add_voice.assert_called_once_with(
        "bass", "faust:bass", ("freq", "gate"), 0.3,
    )


# ── Stage 1: master gain (1.2) ───────────────────────────────────────────────


def test_master_property_delegates_to_session() -> None:
    """mix.master = X calls session.master_gain(X)."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    session.reset_mock()
    mixer.master = 0.6
    session.master_gain.assert_called_once_with(0.6)


def test_master_default_value() -> None:
    """Mixer starts with master=0.7 and sends it on construction."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    assert mixer.master == 0.7
    session.master_gain.assert_called_once_with(0.7)


def test_master_nan_raises() -> None:
    """Setting master to NaN raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="finite"):
        mixer.master = float("nan")


def test_master_inf_raises() -> None:
    """Setting master to Inf raises ValueError."""
    from unittest.mock import MagicMock

    import pytest

    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="finite"):
        mixer.master = float("inf")


# ── Stage 1: convenience properties (1.3) ────────────────────────────────────


def test_bpm_alias_for_tempo() -> None:
    """bpm property reads and writes tempo."""
    from unittest.mock import MagicMock, PropertyMock

    from krach._mixer import Mixer

    session = MagicMock()
    type(session).tempo = PropertyMock(return_value=128.0)

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    assert mixer.bpm == 128.0
    mixer.bpm = 140.0
    type(session).tempo = PropertyMock(return_value=140.0)
    assert mixer.bpm == 140.0


def test_voices_returns_handles() -> None:
    """voices property returns dict of NodeHandles."""
    from unittest.mock import MagicMock

    from krach._mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    result = mixer.nodes
    assert isinstance(result, dict)
    assert "bass" in result
    assert isinstance(result["bass"], NodeHandle)


def test_buses_returns_handles() -> None:
    """buses property returns dict of NodeHandles."""
    from unittest.mock import MagicMock

    from krach._mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)

    result = mixer.effects
    assert isinstance(result, dict)
    assert "verb" in result
    assert isinstance(result["verb"], NodeHandle)


# ── mod() with native automation ─────────────────────────────────────────────


def test_mod_string_shape_sends_automation() -> None:
    """mod() with a string shape sends set_automation to the session."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)

    mixer.mod("bass/cutoff", "sine", lo=200.0, hi=2000.0, bars=2)

    session.set_automation.assert_called_once()
    args = session.set_automation.call_args
    assert args[0][0] == "bass/cutoff"  # label
    assert args[0][1] == "sine"  # shape
    assert args[0][2] == 200.0  # lo
    assert args[0][3] == 2000.0  # hi
    # period_secs = 2 bars * 4 beats * 60 / 120 = 4.0
    assert abs(args[0][4] - 4.0) < 1e-6  # period_secs


def test_mod_pattern_still_works() -> None:
    """mod() with a Pattern still uses the legacy play path."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)

    pat = mod_sine(200.0, 2000.0)
    mixer.mod("bass/cutoff", pat, bars=2)

    # Should NOT call set_automation (uses play path instead)
    session.set_automation.assert_not_called()
    # Should call play_from_zero (the from_zero path in play())
    session.play_from_zero.assert_called_once()


def test_fade_path_sends_automation() -> None:
    """fade() with a path sends a one-shot ramp automation."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)

    mixer.fade("bass/cutoff", 1000.0, bars=4)

    session.set_automation.assert_called_once()
    args = session.set_automation.call_args
    assert args[0][0] == "bass/cutoff"  # label
    assert args[0][1] == "ramp"  # shape
    assert args[0][2] == 0.0  # lo (default start)
    assert args[0][3] == 1000.0  # hi (target)
    # period_secs = 4 bars * 4 beats * 60 / 120 = 8.0
    assert abs(args[0][4] - 8.0) < 1e-6  # period_secs
    assert args[1]["one_shot"] is True


def test_fade_gain_path_updates_bookkeeping() -> None:
    """fade() on gain path updates Voice.gain."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.fade("bass/gain", 0.8, bars=2)

    assert mixer.get_node("bass") is not None
    assert mixer.get_node("bass").gain == 0.8  # type: ignore[union-attr]


# ── Scene save/recall ─────────────────────────────────────────────────────────


def test_save_captures_state() -> None:
    """save() snapshots voices, buses, sends, patterns, tempo, master."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 130.0
    session.meter = 4.0
    session.list_nodes.return_value = ["faust:bass", "faust:verb", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.4)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", 0.5)
    mixer.master = 0.8

    mixer.save("drop")

    assert "drop" in mixer.scenes

    # Verify by recalling into a clean state and checking results
    mixer.voice("pad", "faust:bass", gain=0.9)  # add extra voice
    mixer.master = 0.1
    mixer.recall("drop")

    # After recall, only original voices should exist
    assert "bass" in mixer.node_data
    assert "pad" not in mixer.node_data
    assert mixer.node_data["bass"].gain == 0.4
    assert mixer.node_data["bass"].type_id == "faust:bass"
    assert mixer.node_data["bass"].controls == ("freq", "gate")
    assert mixer.get_node("verb") is not None
    assert mixer.master == 0.8


def test_recall_restores_state() -> None:
    """save, modify, recall — should restore voices/buses/sends/tempo/master."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0
    session.list_nodes.return_value = ["faust:bass", "faust:pad", "faust:verb", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.4)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", 0.5)
    mixer.master = 0.8
    mixer.save("intro")

    # Modify state
    mixer.voice("pad", "faust:pad", gain=0.6)
    mixer.master = 0.5
    session.tempo = 140.0

    # Recall
    mixer.recall("intro")

    # Voices restored
    assert "bass" in mixer.node_data
    assert "pad" not in mixer.node_data
    assert mixer.node_data["bass"].gain == 0.4
    # Buses restored
    assert mixer.get_node("verb") is not None
    # Master restored
    assert mixer.master == 0.8


def test_recall_unknown_raises() -> None:
    """recall() on unknown scene name raises ValueError."""
    import pytest
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="scene 'nope' not found"):
        mixer.recall("nope")


def test_scenes_lists_names() -> None:
    """scenes property returns list of saved scene names."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    assert mixer.scenes == []
    mixer.save("a")
    mixer.save("b")
    assert mixer.scenes == ["a", "b"]


# ── load() — music as Python modules ─────────────────────────────────────────


def test_load_executes_file(tmp_path: Path) -> None:
    """load() execs a Python file with `mix` in scope."""
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    # Write a temp file that sets master gain via mix
    scene_file = tmp_path / "my_scene.py"
    scene_file.write_text("mix.master = 0.42\n")

    mixer.load(str(scene_file))
    assert mixer.master == 0.42


def test_load_missing_file_raises() -> None:
    """load() raises FileNotFoundError for missing path."""
    import pytest
    from unittest.mock import MagicMock

    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(FileNotFoundError, match="scene file not found"):
        mixer.load("/nonexistent/nope.py")


# ── Control IR value ─────────────────────────────────────────────────────────


def test_note_uses_control_not_osc() -> None:
    """note() should produce Control atoms, not Osc atoms."""
    from krach.pattern.builders import note

    pat = note("C4")
    values = _collect_values(pat.node)
    # Every value should be Control, not Osc
    for v in values:
        assert isinstance(v, Control), f"expected Control, got {type(v).__name__}: {v}"
        assert not isinstance(v, Osc), f"found Osc atom in note() output: {v}"


def test_hit_uses_control_not_osc() -> None:
    """hit() should produce Control atoms, not Osc atoms."""
    from krach.pattern.builders import hit

    pat = hit("gate")
    values = _collect_values(pat.node)
    for v in values:
        assert isinstance(v, Control), f"expected Control, got {type(v).__name__}: {v}"


def test_build_note_uses_control_not_osc() -> None:
    """build_note() should produce Control atoms, not Osc atoms."""
    pat = build_note("bass", ("freq", "gate"), pitch=55.0)
    values = _collect_values(pat.node)
    for v in values:
        assert isinstance(v, Control), f"expected Control, got {type(v).__name__}: {v}"


def test_build_hit_uses_control_not_osc() -> None:
    """build_hit() should produce Control atoms, not Osc atoms."""
    pat = build_hit("kit", "kick")
    values = _collect_values(pat.node)
    for v in values:
        assert isinstance(v, Control), f"expected Control, got {type(v).__name__}: {v}"


# ── Mixer.input() ──────────────────────────────────────────────────────


def test_input_calls_start_input_and_creates_voice() -> None:
    """input() starts the audio input stream and creates an adc_input voice."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["adc_input", "dac", "gain"]
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={})

    handle = mixer.input("mic", channel=1, gain=0.4)

    # start_input was called with the right channel
    session.start_input.assert_called_once_with(1)

    # A voice named "mic" exists with type_id "adc_input"
    voice = mixer.get_node("mic")
    assert voice is not None
    assert voice.type_id == "adc_input"
    assert voice.gain == 0.4

    # Graph was rebuilt
    assert session.load_graph.call_count >= 1

    assert handle.name == "mic"


def test_input_default_name_and_channel() -> None:
    """input() defaults to name='mic' and channel=0."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.list_nodes.return_value = ["adc_input", "dac", "gain"]
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={})

    mixer.input()

    session.start_input.assert_called_once_with(0)
    assert mixer.get_node("mic") is not None


def test_input_appears_in_graph_ir() -> None:
    """The adc_input node appears in the built graph IR."""
    from krach._graph import build_graph_ir

    nodes = {
        "mic": Node("adc_input", 0.5, ()),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "mic" in node_ids
    mic_node = next(n for n in ir.nodes if n.id == "mic")
    assert mic_node.type_id == "adc_input"


# ── Mixer.midi_map() ───────────────────────────────────────────────────


def test_midi_map_sends_to_session() -> None:
    """midi_map() sends the mapping to the session."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.midi_map(cc=74, path="bass/cutoff", lo=200.0, hi=4000.0)

    session.midi_map.assert_called_once_with(0, 74, "bass/cutoff", 200.0, 4000.0)


def test_midi_map_custom_channel() -> None:
    """midi_map() passes channel parameter to session."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    mixer.midi_map(cc=1, path="bass/gain", lo=0.0, hi=1.0, channel=5)

    session.midi_map.assert_called_once_with(5, 1, "bass/gain", 0.0, 1.0)


def test_midi_map_resolves_send_path() -> None:
    """midi_map() resolves send-level shorthand paths."""
    from unittest.mock import MagicMock

    session = MagicMock()
    from krach._mixer import Mixer

    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    # "bass/verb_send" should resolve to "bass_send_verb/gain"
    mixer.midi_map(cc=20, path="bass/verb_send", lo=0.0, hi=1.0)

    session.midi_map.assert_called_once_with(0, 20, "bass_send_verb/gain", 0.0, 1.0)


# ── Export ──────────────────────────────────────────────────────────────────


def test_export_generates_valid_python() -> None:
    """export() produces a file that passes ast.parse."""
    import ast
    import tempfile
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir), node_controls={
            "faust:kick": ("gate",),
        })
        mixer.voice("kick", "faust:kick", gain=0.8)
        mixer.play("kick", hit() * 4)

        out = Path(tmpdir) / "session.py"
        mixer.export(str(out))

        code = out.read_text()
        ast.parse(code)  # must not raise


def test_export_contains_voice_and_tempo() -> None:
    """export() includes voice definitions and transport."""
    import tempfile
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    session.tempo = 140.0
    session.meter = 4.0
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir), node_controls={
            "faust:kick": ("gate",),
        })
        mixer.voice("kick", "faust:kick", gain=0.8)
        mixer.play("kick", hit() * 4)
        mixer.master = 0.6

        out = Path(tmpdir) / "session.py"
        mixer.export(str(out))

        code = out.read_text()
        assert 'kr.node("kick"' in code
        assert "kr.tempo = 140.0" in code
        assert "kr.master = 0.6" in code


def test_export_contains_pattern_json() -> None:
    """export() serializes patterns as JSON for dict_to_pattern_node round-trip."""
    import tempfile
    from unittest.mock import MagicMock

    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir), node_controls={
            "faust:kick": ("gate",),
        })
        mixer.voice("kick", "faust:kick", gain=0.8)
        mixer.play("kick", hit() * 4)

        out = Path(tmpdir) / "session.py"
        mixer.export(str(out))

        code = out.read_text()
        assert "_patterns = json.loads(" in code
        assert "dict_to_pattern_node" in code


def test_export_inlines_dsp_function() -> None:
    """export() inlines DSP source text and references function by name."""
    import tempfile
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0

    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir), node_controls={})

        mixer.voice("synth", "faust:synth", gain=0.5)
        mixer.node_data["synth"].source_text = (
            "def synth() -> krs.Signal:\n"
            "    freq = krs.control('freq', 220.0, 20.0, 2000.0)\n"
            "    return krs.saw(freq)\n"
        )
        mixer.play("synth", hit() * 4)

        out = Path(tmpdir) / "session.py"
        mixer.export(str(out))
        code = out.read_text()

        # Inlined function present
        assert "def synth()" in code
        # Node references function, not string
        assert 'kr.node("synth", synth' in code


def test_export_string_source_uses_string() -> None:
    """export() uses string type_id for nodes without source_text."""
    import tempfile
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    session.tempo = 120.0
    session.meter = 4.0

    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir), node_controls={
            "faust:kick": ("gate",),
        })
        mixer.voice("kick", "faust:kick", gain=0.8)

        out = Path(tmpdir) / "session.py"
        mixer.export(str(out))
        code = out.read_text()

        # String source — uses quoted type_id
        assert '"faust:kick"' in code


# ── node() auto-detection ───────────────────────────────────────────────


def test_node_creates_entry_in_nodes() -> None:
    """node() creates an entry in the unified _nodes dict."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.node("bass", "faust:bass", gain=0.3)
    assert mixer.get_node("bass") is not None
    assert mixer.get_node("bass").num_inputs == 0  # type: ignore[union-attr]


def test_connect_voice_to_voice_as_send() -> None:
    """>> between two voices should work as a send (voice used as effect)."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("in", "room"),
    })
    bass = mixer.node("bass", "faust:bass", gain=0.3)
    verb = mixer.node("verb", "faust:verb", gain=0.3)

    # This should not raise — connect should work even when target is a voice
    # (the DSP might have control-based inputs, which is a valid pattern)
    _ = bass >> verb


# ── Unified Node model (replaces Voice/Bus split) ───────────────────────


def test_unified_node_source_and_effect_in_same_dict() -> None:
    """All nodes live in one dict, regardless of num_inputs."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("in", "room"),
    })
    mixer.node("bass", "faust:bass", gain=0.3)
    mixer.node("verb", "faust:verb", gain=0.3)

    # Both should be findable as nodes
    assert mixer.get_node("bass") is not None or mixer.get_node("bass") is not None
    assert mixer.get_node("verb") is not None or mixer.get_node("verb") is not None


def test_connect_any_node_to_any_node() -> None:
    """>> works between any two nodes, regardless of type."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("in", "room"),
    })
    bass = mixer.node("bass", "faust:bass", gain=0.3)
    verb = mixer.node("verb", "faust:verb", gain=0.3)
    _ = bass >> verb  # must not raise


def test_remove_works_for_any_node() -> None:
    """remove() works regardless of whether node was source or effect."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.node("bass", "faust:bass", gain=0.3)
    mixer.remove("bass")  # must not raise


def test_gain_works_for_any_node() -> None:
    """gain() works on any node."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("in", "room"),
    })
    mixer.node("verb", "faust:verb", gain=0.3)
    mixer.gain("verb", 0.5)  # must not raise


def test_mute_unmute_any_node() -> None:
    """mute/unmute works on any node."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("in", "room"),
    })
    mixer.node("verb", "faust:verb", gain=0.3)
    mixer.mute("verb")
    assert mixer.is_muted("verb")
    mixer.unmute("verb")
    assert not mixer.is_muted("verb")


def test_replace_node_cleans_up_connections() -> None:
    """Re-creating a node with the same name cleans up old sends."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("in", "room"),
    })
    bass = mixer.node("bass", "faust:bass", gain=0.3)
    verb = mixer.node("verb", "faust:verb", gain=0.3)
    _ = bass >> verb

    # Replace verb — should not crash on rebuild
    verb2 = mixer.node("verb", "faust:verb", gain=0.5)
    _ = bass >> verb2  # re-route, must not raise


def test_bus_replace_existing_bus() -> None:
    """bus() should allow replacing an existing bus (effect node)."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("in", "room"),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    # Re-creating should replace, not crash
    mixer.bus("verb", "faust:verb", gain=0.5)
    assert mixer.get_node("verb") is not None
    assert mixer.get_node("verb").gain == 0.5  # type: ignore[union-attr]


def test_bus_replace_voice_with_bus() -> None:
    """bus() should allow replacing a voice with a bus (effect node)."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    # Replace voice with bus — should work (unified node model)
    mixer.bus("bass", "faust:bass", gain=0.5)
    node = mixer.get_node("bass")
    assert node is not None
    assert node.num_inputs > 0  # type: ignore[union-attr]


# ── Stale merge artifact fixes ───────────────────────────────────────────


def test_mute_single_stores_gain_for_any_node() -> None:
    """_mute_single stores gain for nodes (no stale elif branch)."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.mute("verb")
    assert mixer.is_muted("verb")
    # Unmute should restore gain
    mixer.unmute("verb")
    assert not mixer.is_muted("verb")


def test_resolve_targets_no_duplicates() -> None:
    """Group resolution returns each match once."""
    from krach._types import GroupPath, resolve_path, Node

    nodes = {
        "drums/kick": Node(type_id="faust:kick", gain=0.5, controls=("gate",)),
        "drums/snare": Node(type_id="faust:snare", gain=0.5, controls=("gate",)),
    }
    result = resolve_path("drums", nodes)
    assert isinstance(result, GroupPath)
    assert len(result.members) == 2


# ── Forgiving UX (no crash on typos/missing nodes) ─────────────────────


def test_remove_missing_node_is_noop() -> None:
    """remove() on non-existent node is a no-op, not a crash."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.remove("nonexistent")  # must not raise


def test_remove_bus_missing_is_noop() -> None:
    """remove_bus() on non-existent bus is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.remove_bus("nonexistent")  # must not raise


def test_gain_missing_node_is_noop() -> None:
    """gain() on non-existent node is a no-op, not a crash."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.gain("nonexistent", 0.5)  # must not raise


def test_mute_missing_node_is_noop() -> None:
    """mute() on non-existent node is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.mute("nonexistent")  # must not raise


def test_unmute_missing_node_is_noop() -> None:
    """unmute() on non-existent node is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.unmute("nonexistent")  # must not raise


def test_fade_missing_node_is_noop() -> None:
    """fade() on non-existent node is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    mixer.fade("nonexistent", 0.5)  # must not raise


def test_send_missing_source_is_noop() -> None:
    """send() with missing source is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("nonexistent", "verb")  # must not raise


def test_send_missing_target_is_noop() -> None:
    """send() with missing target is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.send("bass", "nonexistent")  # must not raise


def test_wire_missing_source_is_noop() -> None:
    """wire() with missing source is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.wire("nonexistent", "verb")  # must not raise


def test_wire_missing_target_is_noop() -> None:
    """wire() with missing target is a no-op."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    mixer.wire("bass", "nonexistent")  # must not raise


def test_getitem_slashed_node_name_returns_handle() -> None:
    """kr['drums/kick'] returns NodeHandle when a node is named 'drums/kick'."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach._handle import NodeHandle

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.5)
    result = mixer["drums/kick"]
    assert isinstance(result, NodeHandle)
    assert result.name == "drums/kick"


def test_setitem_slashed_node_name_sets_gain() -> None:
    """kr['drums/kick'] = 0.3 sets gain, not control value."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.5)
    mixer["drums/kick"] = 0.3
    assert mixer.get_node("drums/kick").gain == 0.3  # type: ignore[union-attr]


def test_hush_slashed_node_name() -> None:
    """hush('drums/kick') hushed the node, not treated as control path."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    mixer.voice("drums/kick", "faust:kick", gain=0.5)
    mixer.hush("drums/kick")
    # Should have hushed via session.hush("drums/kick"), not _ctrl_ path
    session.hush.assert_any_call("drums/kick")


def test_pattern_missing_returns_none() -> None:
    """pattern() on unplayed slot returns None."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))
    result = mixer.pattern("nonexistent")
    assert result is None


# ── Bus validation: effects must have audio inputs ───────────────────────


def test_bus_callable_with_no_audio_inputs_raises() -> None:
    """bus() with a DspDef that has num_inputs=0 raises ValueError."""
    from unittest.mock import MagicMock
    import pytest
    from krach._mixer import Mixer
    from krach._types import DspDef

    from krach.ir.signal import DspGraph

    # A generator (0 audio inputs) should not be used as a bus
    source_dsp = DspDef(
        fn=lambda: None,
        source="def f(): pass",
        faust="process = 0;",
        graph=DspGraph(inputs=(), outputs=(), equations=()),
        controls=("in", "room"),
        num_inputs=0,
    )

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"))

    with pytest.raises(ValueError, match="no audio inputs"):
        mixer.bus("verb", source_dsp, gain=0.3)


def test_node_with_effect_dspdef_routes_to_bus() -> None:
    """node() with a DspDef that has audio inputs creates an effect node."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach._types import DspDef
    import tempfile

    session = MagicMock()
    session.list_nodes.return_value = ["faust:verb", "dac", "gain"]
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = Mixer(session=session, dsp_dir=Path(tmpdir))

        from krach.ir.signal import DspGraph, Signal, SignalType
        s0 = Signal(aval=SignalType(), id=0, owner_id=0)
        s1 = Signal(aval=SignalType(), id=1, owner_id=0)
        effect = DspDef(
            fn=lambda x: x,  # type: ignore[reportUnknownLambdaType]
            source="def f(x): return x",
            faust='import("stdfaust.lib");\nprocess(input0) = input0;',
            graph=DspGraph(inputs=(s0,), outputs=(s1,), equations=()),
            controls=("room",),
            num_inputs=1,
        )
        mixer.node("verb", effect, gain=0.3)
        node = mixer.get_node("verb")
        assert node is not None
        assert node.num_inputs == 1


# ── No-op warnings: operations print warning, don't crash ────────────────


def test_send_missing_node_warns() -> None:
    """send() with missing node emits a warning."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.send("bass", "nonexistent")
        assert len(w) == 1
        assert "nonexistent" in str(w[0].message)


def test_wire_missing_node_warns() -> None:
    """wire() with missing node emits a warning."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.wire("bass", "nonexistent")
        assert len(w) == 1
        assert "nonexistent" in str(w[0].message)


# ── save/recall round-trip preserves full Node state ─────────────────────


def test_save_recall_preserves_poly_count() -> None:
    """save/recall round-trip must preserve count for poly voices."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)
    mixer.save("test")

    # Destroy state
    mixer.remove("pad")
    assert mixer.get_node("pad") is None

    # Recall
    mixer.recall("test")
    node = mixer.get_node("pad")
    assert node is not None
    assert node.count == 4  # must survive round-trip


# ── Poly node control fan-out ──────────────────────────────────────────


def test_set_poly_fans_out_to_instances() -> None:
    """kr.set('pad/cutoff', 1200) must send to pad_v0/cutoff .. pad_v3/cutoff."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate", "cutoff"),
    })
    mixer.voice("pad", "faust:pad", count=4, gain=0.5)
    session.reset_mock()

    mixer.set("pad/cutoff", 1200.0)

    # Must have sent to all 4 instances
    calls = [c for c in session.set_ctrl.call_args_list if "cutoff" in str(c)]
    labels = sorted(c.args[0] for c in calls)
    assert labels == ["pad_v0/cutoff", "pad_v1/cutoff", "pad_v2/cutoff", "pad_v3/cutoff"]


def test_set_mono_sends_direct() -> None:
    """kr.set('bass/cutoff', 1200) sends directly — no fan-out for count=1."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.set("bass/cutoff", 1200.0)

    session.set_ctrl.assert_called_once_with("bass/cutoff", 1200.0)


def test_callable_with_default_none_is_source() -> None:
    """def f(inp=None) should count as 0 audio inputs — routed to voice, not bus."""
    from unittest.mock import MagicMock, patch
    from krach._mixer import Mixer

    session = MagicMock()

    def fake_synth(inp: object = None) -> None:
        pass

    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]

    from krach.ir.signal import DspGraph

    mock_graph = DspGraph(inputs=(), outputs=(), equations=())
    with (
        patch("krach.signal.transpile.make_graph", return_value=mock_graph),
        patch("krach.backends.faust_codegen.emit_faust", return_value="process = 0;\n"),
        patch("krach.signal.transpile.collect_controls", return_value=()),
    ):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mixer = Mixer(session=session, dsp_dir=Path(tmpdir))
            mixer.node("pad", fake_synth, gain=0.5, count=4)
            node = mixer.get_node("pad")
            assert node is not None
            assert node.count == 4  # voice, not bus


def test_play_poly_control_fans_out() -> None:
    """kr.play('pad/cutoff', pattern) must fan out to per-instance control slots."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate", "cutoff"),
    })
    mixer.voice("pad", "faust:pad", count=3, gain=0.5)
    session.reset_mock()

    mixer.play("pad/cutoff", mod_sine(100.0, 2000.0))

    # Should have called session.play for each instance
    assert session.play.call_count == 3
    slots = sorted(c.args[0] for c in session.play.call_args_list)
    assert slots == ["_ctrl_pad_v0_cutoff", "_ctrl_pad_v1_cutoff", "_ctrl_pad_v2_cutoff"]


def test_set_poly_gain_fans_out() -> None:
    """kr.set('pad/gain', 0.8) must fan out to per-instance gain labels."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=3, gain=0.5)
    session.reset_mock()

    mixer.set("pad/gain", 0.9)

    calls = [c for c in session.set_ctrl.call_args_list if "gain" in str(c)]
    labels = sorted(c.args[0] for c in calls)
    assert labels == ["pad_v0/gain", "pad_v1/gain", "pad_v2/gain"]


# ── Control range validation ───────────────────────────────────────────


def test_set_warns_value_outside_control_range() -> None:
    """kr.set('bass/cutoff', 0.5) warns when cutoff range is [100, 6000]."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    # Manually set control ranges (normally comes from transpiler)
    mixer.node_data["bass"].control_ranges = {"cutoff": (100.0, 6000.0), "freq": (20.0, 2000.0)}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.set("bass/cutoff", 0.5)  # way below min of 100
        assert len(w) == 1
        assert "outside" in str(w[0].message).lower()
        assert "cutoff" in str(w[0].message)


def test_set_no_warning_when_in_range() -> None:
    """kr.set('bass/cutoff', 1200) should NOT warn when in range."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.node_data["bass"].control_ranges = {"cutoff": (100.0, 6000.0)}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.set("bass/cutoff", 1200.0)
        range_warnings = [x for x in w if "outside" in str(x.message).lower()]
        assert len(range_warnings) == 0


def test_set_no_warning_without_ranges() -> None:
    """kr.set() should not warn when control ranges are not available."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    # No control_ranges set — should not crash or warn

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.set("bass/freq", 0.5)
        range_warnings = [x for x in w if "outside" in str(x.message).lower()]
        assert len(range_warnings) == 0


# ── Public routing/ctrl_values properties ──────────────────────────────


def test_routing_property_returns_sends_and_wires() -> None:
    """kr.routing returns list of (src, tgt, kind, level_or_port) tuples."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    routes = mixer.routing
    assert len(routes) == 1
    src, tgt, kind, lvl = routes[0]
    assert src == "bass"
    assert tgt == "verb"
    assert kind == "send"
    assert lvl == 0.4


def test_routing_is_snapshot() -> None:
    """Mutating routing return value doesn't affect internal state."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq",),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    routes = mixer.routing
    routes.clear()
    assert len(mixer.routing) == 1  # internal unchanged


def test_ctrl_values_property() -> None:
    """kr.ctrl_values returns snapshot of set control values."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.set("bass/cutoff", 1200.0)

    vals = mixer.ctrl_values
    assert vals["bass/cutoff"] == 1200.0

    # Mutation doesn't affect internal
    vals["bass/cutoff"] = 9999.0
    assert mixer.ctrl_values["bass/cutoff"] == 1200.0


# ── disconnect ─────────────────────────────────────────────────────────


def test_disconnect_removes_send() -> None:
    """disconnect() removes a send and rebuilds the graph."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq",),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)
    assert len(mixer.routing) == 1

    mixer.unsend("bass", "verb")
    assert len(mixer.routing) == 0


def test_disconnect_noop_if_not_connected() -> None:
    """disconnect() is a no-op (no rebuild) if no connection exists."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    rebuild_count = session.load_graph.call_count

    mixer.unsend("bass", "nonexistent")
    assert session.load_graph.call_count == rebuild_count  # no extra rebuild


def test_play_control_path_warns_mod_outside_range() -> None:
    """kr.play('bass/freq', mod_sine(0.5, 1.5)) warns when freq range is [20, 2000]."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.node_data["bass"].control_ranges = {"freq": (20.0, 2000.0), "gate": (0.0, 1.0)}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.play("bass/freq", mod_sine(0.5, 1.5))
        range_warnings = [x for x in w if "outside" in str(x.message).lower()]
        assert len(range_warnings) == 1
        assert "freq" in str(range_warnings[0].message)
        assert "[20.0, 2000.0]" in str(range_warnings[0].message)


def test_play_warns_unknown_control_name() -> None:
    """kr.play('bass', note('C4', volume=1.0)) warns when bass has no 'volume' control."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.play("bass", note("C4", volume=1.0))
        ctrl_warnings = [x for x in w if "unknown control" in str(x.message).lower()]
        assert len(ctrl_warnings) == 1
        assert "volume" in str(ctrl_warnings[0].message)
        assert "freq" in str(ctrl_warnings[0].message) or "available" in str(ctrl_warnings[0].message).lower()


def test_play_no_warn_known_controls() -> None:
    """kr.play('bass', note('C4')) should not warn — freq and gate are known."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import note

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.play("bass", note("C4"))
        ctrl_warnings = [x for x in w if "unknown control" in str(x.message).lower()]
        assert len(ctrl_warnings) == 0


def test_play_control_path_no_warn_when_in_range() -> None:
    """kr.play('bass/freq', mod_sine(100, 800)) should not warn."""
    import warnings
    from unittest.mock import MagicMock
    from krach._mixer import Mixer
    from krach.pattern.builders import mod_sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.node_data["bass"].control_ranges = {"freq": (20.0, 2000.0)}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.play("bass/freq", mod_sine(100.0, 800.0))
        range_warnings = [x for x in w if "outside" in str(x.message).lower()]
        assert len(range_warnings) == 0


def test_save_recall_preserves_source_text() -> None:
    """save/recall round-trip must preserve source_text."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.3)
    # Manually set source_text to simulate transpiled DSP
    mixer.node_data["bass"].source_text = "def bass(): pass"
    mixer.save("test")

    mixer.remove("bass")
    mixer.recall("test")
    node = mixer.get_node("bass")
    assert node is not None
    assert node.source_text == "def bass(): pass"


def test_save_recall_preserves_num_inputs() -> None:
    """save/recall round-trip must preserve num_inputs for effects."""
    from unittest.mock import MagicMock
    from krach._mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:verb", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    assert mixer.get_node("verb") is not None
    assert mixer.get_node("verb").num_inputs > 0  # type: ignore[union-attr]
    mixer.save("test")

    mixer.remove("verb")
    mixer.recall("test")
    node = mixer.get_node("verb")
    assert node is not None
    assert node.num_inputs > 0  # must survive round-trip
