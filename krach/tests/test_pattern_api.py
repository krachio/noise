"""Tests for Pattern API — mask(), sometimes(), struct(), and end-to-end integration."""

from __future__ import annotations

from krach.ir.pattern import AtomParams, DegradeParams
from krach.pattern.pattern import midi_note as note, rest
from krach.ir.values import Control
from krach.pattern.builders import hit, seq, note as mixer_note, struct, ramp, cat, stack


# ── mask() ───────────────────────────────────────────────────────────


def test_mask_silences_zeroed_positions() -> None:
    pat = (note(60) + note(64) + note(67)).mask("1 0 1")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3
    assert pat.node.children[1].primitive.name == "silence"
    assert pat.node.children[0].primitive.name != "silence"
    assert pat.node.children[2].primitive.name != "silence"


def test_mask_x_keeps_position() -> None:
    pat = (note(60) + note(64)).mask("x 0")
    assert pat.node.children[0].primitive.name != "silence"
    assert pat.node.children[1].primitive.name == "silence"


def test_mask_shorter_than_children_preserves_tail() -> None:
    pat = (note(60) + note(64) + note(67)).mask("0")
    assert pat.node.children[0].primitive.name == "silence"
    assert pat.node.children[1].primitive.name != "silence"
    assert pat.node.children[2].primitive.name != "silence"


def test_mask_on_non_cat_returns_self() -> None:
    pat = note(60)
    masked = pat.mask("0 1")
    assert masked.node == pat.node


# ── sometimes() ──────────────────────────────────────────────────────


def test_sometimes_produces_stack_of_degrades() -> None:
    pat = note(60)
    result = pat.sometimes(0.3, lambda p: p.reverse())
    assert result.node.primitive.name == "stack"
    assert len(result.node.children) == 2
    # Both children should be degrade nodes
    assert result.node.children[0].primitive.name == "degrade"
    assert result.node.children[1].primitive.name == "degrade"


def test_sometimes_complementary_probabilities() -> None:
    pat = note(60)
    result = pat.sometimes(0.3, lambda p: p.reverse())
    d0 = result.node.children[0].params
    d1 = result.node.children[1].params
    assert isinstance(d0, DegradeParams)
    assert isinstance(d1, DegradeParams)
    assert abs(d0.prob + d1.prob - 1.0) < 1e-10


def test_sometimes_transformed_child_is_reversed() -> None:
    pat = note(60)
    result = pat.sometimes(0.5, lambda p: p.reverse())
    # children[0] = degrade(transformed), children[1] = degrade(original)
    inner_0 = result.node.children[0].children[0]  # the reversed version
    assert inner_0.primitive.name == "rev"


# ── struct() ─────────────────────────────────────────────────────────


def test_struct_replaces_rhythm_onsets_with_melody() -> None:
    rhythm = hit() + rest() + hit() + rest()
    melody = mixer_note("C4") + mixer_note("E4")
    result = struct(rhythm, melody)
    assert result.node.primitive.name == "cat"
    assert len(result.node.children) == 4
    # Positions 0 and 2 should have melody atoms (freeze nodes)
    assert result.node.children[0].primitive.name == "freeze"
    assert result.node.children[1].primitive.name == "silence"
    assert result.node.children[2].primitive.name == "freeze"
    assert result.node.children[3].primitive.name == "silence"


def test_struct_melody_wraps_when_shorter() -> None:
    rhythm = hit() + hit() + hit()  # 3 onsets
    melody = mixer_note("C4")  # 1 melody atom
    result = struct(rhythm, melody)
    # All 3 onsets should use the same melody atom (wraps via modulo)
    assert result.node.children[0] == result.node.children[1]
    assert result.node.children[1] == result.node.children[2]


def test_struct_no_melody_atoms_returns_rhythm() -> None:
    rhythm = hit() + rest()
    melody = rest() + rest()  # no freeze nodes
    result = struct(rhythm, melody)
    assert result.node == rhythm.node


# ── ramp / modulation builders ───────────────────────────────────────


def test_ramp_produces_cat_of_controls() -> None:
    pat = ramp(0.0, 1.0, steps=4)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 4
    # First should be 0.0, last should be ~0.75 (not 1.0 — t = i/steps)
    first = pat.node.children[0]
    assert isinstance(first.params, AtomParams)
    assert isinstance(first.params.value, Control)
    assert first.params.value.value == 0.0
    assert first.params.value.label == "ctrl"


# ── cat() / stack() combinators ──────────────────────────────────────


def test_cat_combinator_applies_over() -> None:
    result = cat(mixer_note("C4"), mixer_note("E4"))
    # cat() with 2 patterns → .over(2) → slow(2,1)
    assert result.node.primitive.name == "slow"


def test_stack_combinator_layers() -> None:
    result = stack(mixer_note("C4"), mixer_note("E4"))
    assert result.node.primitive.name == "stack"


# ── seq() edge cases ────────────────────────────────────────────────


def test_seq_with_none_produces_rest() -> None:
    pat = seq("C4", None, "E4")
    assert pat.node.primitive.name == "cat"
    assert pat.node.children[1].primitive.name == "silence"


# ── End-to-end integration ──────────────────────────────────────────


def test_end_to_end_mininotation_to_engine_json() -> None:
    """Full path: mini-notation → bind → serialize → JSON → deserialize."""
    import json
    from krach.pattern.mininotation import p
    from krach.pattern.bind import bind_voice
    from krach.pattern.serialize import pattern_node_to_dict, dict_to_pattern_node
    from krach.pattern.bind import collect_control_labels

    pat = p("C4 E4 G4").swing(0.67)
    bound = bind_voice(pat.node, "lead")
    labels = collect_control_labels(bound)
    assert "lead/freq" in labels
    assert "lead/gate" in labels

    # Serialize → JSON string → deserialize
    d = pattern_node_to_dict(bound)
    j = json.dumps(d)
    restored = dict_to_pattern_node(json.loads(j))
    assert restored == bound

    # Final: command_to_json (what actually goes to the engine)
    from krach.backends.pattern import SetPattern, command_to_json
    cmd_json = command_to_json(SetPattern(slot="lead", pattern=bound))
    parsed = json.loads(cmd_json)
    assert parsed["cmd"] == "SetPattern"
    assert parsed["slot"] == "lead"
    assert parsed["pattern"]["op"] == "Warp"


# ── Builder edge cases (Maria) ───────────────────────────────────────


def test_ramp_steps_1() -> None:
    pat = ramp(0.0, 1.0, steps=1)
    assert pat.node.primitive.name == "atom"  # single step, no cat


def test_ramp_lo_equals_hi() -> None:
    pat = ramp(0.5, 0.5, steps=4)
    assert pat.node.primitive.name == "cat"
    # All values should be 0.5
    from krach.pattern.bind import collect_control_values
    vals = collect_control_values(pat.node)
    assert all(v == 0.5 for v in vals)


def test_mod_sine_returns_pattern() -> None:
    from krach.pattern.builders import mod_sine
    pat = mod_sine(0.0, 1.0, steps=8)
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 8


def test_mod_tri_returns_pattern() -> None:
    from krach.pattern.builders import mod_tri
    pat = mod_tri(0.0, 1.0, steps=8)
    assert pat.node.primitive.name == "cat"


def test_mod_ramp_down_first_is_hi() -> None:
    from krach.pattern.builders import mod_ramp_down
    pat = mod_ramp_down(0.0, 1.0, steps=4)
    # First value should be 1.0 (starts at hi, ramps to lo)
    first = pat.node.children[0]
    assert isinstance(first.params, AtomParams)
    assert isinstance(first.params.value, Control)
    assert first.params.value.value == 1.0


def test_mod_square_two_levels() -> None:
    from krach.pattern.builders import mod_square
    pat = mod_square(0.0, 1.0, steps=4)
    from krach.pattern.bind import collect_control_values
    vals = collect_control_values(pat.node)
    # First half should be hi (1.0), second half lo (0.0)
    assert vals[:2] == [1.0, 1.0]
    assert vals[2:] == [0.0, 0.0]


def test_mod_exp_starts_at_lo() -> None:
    from krach.pattern.builders import mod_exp
    pat = mod_exp(0.0, 1.0, steps=4)
    first = pat.node.children[0]
    assert isinstance(first.params, AtomParams)
    assert isinstance(first.params.value, Control)
    assert first.params.value.value == 0.0  # t^2 at t=0


def test_rand_values_in_range() -> None:
    from krach.pattern.builders import rand as rand_pat
    pat = rand_pat(10.0, 20.0, steps=16)
    from krach.pattern.bind import collect_control_values
    vals = collect_control_values(pat.node)
    assert len(vals) == 16
    assert all(10.0 <= v <= 20.0 for v in vals)


def test_struct_single_hit_rhythm() -> None:
    rhythm = hit()
    melody = mixer_note("C4")
    result = struct(rhythm, melody)
    assert result.node.primitive.name == "freeze"  # single onset replaced
