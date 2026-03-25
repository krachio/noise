"""Tests for pattern binding — bind_voice, bind_ctrl, bind_voice_poly, collectors."""

from __future__ import annotations

from krach.ir.pattern import AtomParams, CatParams, FreezeParams, PatternNode, SilenceParams
from krach.pattern.bind import (
    bind_ctrl, bind_voice, bind_voice_poly,
    collect_control_labels, collect_control_values,
)
from krach.pattern.values import Control, Osc, OscFloat, OscInt, OscStr
from krach.pattern.primitives import atom_p, cat_p, freeze_p, silence_p


def _ctrl(label: str, value: float) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Control(label, value)))


def _silence() -> PatternNode:
    return PatternNode(silence_p, (), SilenceParams())


def _osc(addr: str, *args: OscFloat | OscInt | OscStr) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Osc(addr, tuple(args))))


# ── bind_ctrl ────────────────────────────────────────────────────────


def test_bind_ctrl_replaces_placeholder() -> None:
    node = _ctrl("ctrl", 0.5)
    bound = bind_ctrl(node, "bass/cutoff")
    labels = collect_control_labels(bound)
    assert "bass/cutoff" in labels
    assert "ctrl" not in labels


def test_bind_ctrl_preserves_non_ctrl_labels() -> None:
    node = PatternNode(cat_p, (_ctrl("freq", 220.0), _ctrl("ctrl", 0.5)), CatParams())
    bound = bind_ctrl(node, "bass/cutoff")
    labels = collect_control_labels(bound)
    assert "bass/cutoff" in labels
    assert "freq" in labels  # non-ctrl label preserved


def test_bind_ctrl_rewrites_osc_str() -> None:
    node = _osc("/audio/set", OscStr("ctrl"), OscFloat(800.0))
    bound = bind_ctrl(node, "bass/cutoff")
    # The OscStr("ctrl") should become OscStr("bass/cutoff")
    assert isinstance(bound.params, AtomParams)
    val = bound.params.value
    assert isinstance(val, Osc)
    assert any(isinstance(a, OscStr) and a.value == "bass/cutoff" for a in val.args)


# ── bind_voice ───────────────────────────────────────────────────────


def test_bind_voice_prefixes_bare_labels() -> None:
    node = PatternNode(cat_p, (_ctrl("freq", 440.0), _ctrl("gate", 1.0)), CatParams())
    bound = bind_voice(node, "bass")
    labels = collect_control_labels(bound)
    assert labels == {"bass/freq", "bass/gate"}


def test_bind_voice_skips_already_prefixed() -> None:
    node = _ctrl("other/freq", 440.0)
    bound = bind_voice(node, "bass")
    labels = collect_control_labels(bound)
    assert "other/freq" in labels  # not rewritten
    assert "bass/other/freq" not in labels


def test_bind_voice_osc_str_prefixed() -> None:
    node = _osc("/audio/set", OscStr("freq"), OscFloat(440.0))
    bound = bind_voice(node, "bass")
    assert isinstance(bound.params, AtomParams)
    val = bound.params.value
    assert isinstance(val, Osc)
    assert any(isinstance(a, OscStr) and a.value == "bass/freq" for a in val.args)


def test_bind_voice_passes_through_silence() -> None:
    bound = bind_voice(_silence(), "bass")
    assert bound.primitive == silence_p


# ── bind_voice_poly ──────────────────────────────────────────────────


def test_bind_voice_poly_wraps_around_count() -> None:
    """5 freeze nodes with count=3 should cycle: v0, v1, v2, v0, v1."""
    notes = [
        PatternNode(freeze_p, (_ctrl("gate", 1.0),), FreezeParams())
        for _ in range(5)
    ]
    tree = PatternNode(cat_p, tuple(notes), CatParams())
    bound, alloc = bind_voice_poly(tree, "pad", count=3, alloc=0)
    assert alloc == 5

    # Check each freeze got the right voice
    labels_per_child: list[set[str]] = []
    for child in bound.children:
        labels_per_child.append(collect_control_labels(child))
    assert "pad_v0/gate" in labels_per_child[0]
    assert "pad_v1/gate" in labels_per_child[1]
    assert "pad_v2/gate" in labels_per_child[2]
    assert "pad_v0/gate" in labels_per_child[3]  # wraps
    assert "pad_v1/gate" in labels_per_child[4]  # wraps


def test_bind_voice_poly_non_freeze_root_passthrough() -> None:
    """Non-freeze root passes through with state unchanged."""
    node = _ctrl("gate", 1.0)  # bare atom, not freeze
    bound, alloc = bind_voice_poly(node, "pad", count=4, alloc=0)
    assert alloc == 0  # no allocation happened
    labels = collect_control_labels(bound)
    assert "gate" in labels  # not prefixed (no freeze boundary)


def test_bind_voice_poly_count_1() -> None:
    """count=1: all notes go to the same voice."""
    notes = [
        PatternNode(freeze_p, (_ctrl("gate", 1.0),), FreezeParams())
        for _ in range(3)
    ]
    tree = PatternNode(cat_p, tuple(notes), CatParams())
    bound, alloc = bind_voice_poly(tree, "bass", count=1, alloc=0)
    assert alloc == 3
    # All should be bass_v0
    all_labels = collect_control_labels(bound)
    assert "bass_v0/gate" in all_labels
    assert "bass_v1/gate" not in all_labels


# ── collect_control_values ───────────────────────────────────────────


def test_collect_control_values() -> None:
    node = PatternNode(cat_p, (
        _ctrl("freq", 440.0),
        _ctrl("gate", 1.0),
        _silence(),
        _ctrl("gate", 0.0),
    ), CatParams())
    values = collect_control_values(node)
    assert values == [440.0, 1.0, 0.0]


def test_collect_control_labels_empty_tree() -> None:
    assert collect_control_labels(_silence()) == set()


def test_collect_control_values_empty_tree() -> None:
    assert collect_control_values(_silence()) == []
