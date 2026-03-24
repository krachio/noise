"""Tests for PatternNode serialization — round-trip every primitive and value type."""

from __future__ import annotations

import pytest

from krach.ir.pattern import (
    AtomParams, CatParams, DegradeParams, EarlyParams, EuclidParams,
    EveryParams, FastParams, FreezeParams, LateParams, PatternNode,
    RevParams, SilenceParams, SlowParams, StackParams, WarpParams,
)
from krach.patterns.values import Cc, Control, Note, Osc, OscFloat, OscInt, OscStr
from krach.patterns.primitives import (
    atom_p, cat_p, degrade_p, early_p, euclid_p, every_p,
    fast_p, freeze_p, late_p, rev_p, silence_p, slow_p, stack_p, warp_p,
)
from krach.patterns.serialize import (
    dict_to_pattern_node, pattern_node_to_dict,
)


def _ctrl(label: str, value: float) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Control(label, value)))


def _note(midi: int) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Note(0, midi, 100, 1.0)))


def _silence() -> PatternNode:
    return PatternNode(silence_p, (), SilenceParams())


def _round_trip(node: PatternNode) -> None:
    """Serialize → deserialize and assert equality."""
    d = pattern_node_to_dict(node)
    restored = dict_to_pattern_node(d)
    assert restored == node, f"Round-trip failed:\n  orig: {node}\n  rest: {restored}"


# ── Value type round-trips ───────────────────────────────────────────


def test_round_trip_atom_note() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(Note(1, 60, 80, 0.5))))


def test_round_trip_atom_control() -> None:
    _round_trip(_ctrl("freq", 440.0))


def test_round_trip_atom_cc() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(Cc(1, 74, 127))))


def test_round_trip_atom_osc_float() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(
        Osc("/audio/set", (OscFloat(440.0),)))))


def test_round_trip_atom_osc_int() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(
        Osc("/midi/note", (OscInt(60),)))))


def test_round_trip_atom_osc_str() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(
        Osc("/set", (OscStr("bass/freq"),)))))


def test_round_trip_atom_osc_mixed_args() -> None:
    _round_trip(PatternNode(atom_p, (), AtomParams(
        Osc("/multi", (OscStr("path"), OscFloat(1.5), OscInt(42))))))


# ── Primitive round-trips (all 14) ───────────────────────────────────


def test_round_trip_silence() -> None:
    _round_trip(_silence())


def test_round_trip_cat() -> None:
    _round_trip(PatternNode(cat_p, (_note(60), _silence(), _note(64)), CatParams()))


def test_round_trip_stack() -> None:
    _round_trip(PatternNode(stack_p, (_note(60), _note(64)), StackParams()))


def test_round_trip_freeze() -> None:
    _round_trip(PatternNode(freeze_p, (_ctrl("gate", 1.0),), FreezeParams()))


def test_round_trip_fast() -> None:
    _round_trip(PatternNode(fast_p, (_note(60),), FastParams((3, 2))))


def test_round_trip_slow() -> None:
    _round_trip(PatternNode(slow_p, (_note(60),), SlowParams((2, 1))))


def test_round_trip_early() -> None:
    _round_trip(PatternNode(early_p, (_note(60),), EarlyParams((1, 4))))


def test_round_trip_late() -> None:
    _round_trip(PatternNode(late_p, (_note(60),), LateParams((1, 8))))


def test_round_trip_rev() -> None:
    _round_trip(PatternNode(rev_p, (_note(60),), RevParams()))


def test_round_trip_every() -> None:
    transform = PatternNode(rev_p, (_note(60),), RevParams())
    source = _note(60)
    _round_trip(PatternNode(every_p, (transform, source), EveryParams(n=4)))


def test_round_trip_euclid() -> None:
    _round_trip(PatternNode(euclid_p, (_note(60),), EuclidParams(3, 8, 1)))


def test_round_trip_degrade() -> None:
    _round_trip(PatternNode(degrade_p, (_note(60),), DegradeParams(0.3, 42)))


def test_round_trip_warp() -> None:
    _round_trip(PatternNode(warp_p, (_note(60),), WarpParams("swing", 0.67, 8)))


# ── Deep nesting ─────────────────────────────────────────────────────


def test_round_trip_deep_nesting() -> None:
    inner = PatternNode(cat_p, (_note(60), _note(64), _silence()), CatParams())
    spread = PatternNode(euclid_p, (inner,), EuclidParams(3, 8, 0))
    degraded = PatternNode(degrade_p, (spread,), DegradeParams(0.5, 0))
    fast = PatternNode(fast_p, (degraded,), FastParams((2, 1)))
    frozen = PatternNode(freeze_p, (fast,), FreezeParams())
    _round_trip(frozen)


# ── Error paths ──────────────────────────────────────────────────────


def test_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="unknown PatternNode op"):
        dict_to_pattern_node({"op": "Bogus"})


def test_unknown_value_type_raises() -> None:
    from krach.patterns.values import dict_to_value
    with pytest.raises(ValueError, match="unknown value type"):
        dict_to_value({"type": "Bogus"})


def test_unknown_osc_arg_raises() -> None:
    from krach.patterns.values import dict_to_osc_arg
    with pytest.raises(ValueError, match="unknown OscArg"):
        dict_to_osc_arg({"Bogus": 1})


# ── JSON round-trip ──────────────────────────────────────────────────


def test_json_round_trip() -> None:
    """Serialize → JSON string → deserialize preserves equality."""
    import json
    node = PatternNode(warp_p, (
        PatternNode(cat_p, (_note(60), _ctrl("gate", 1.0), _silence()), CatParams()),
    ), WarpParams("swing", 0.67, 8))
    j = json.dumps(pattern_node_to_dict(node))
    restored = dict_to_pattern_node(json.loads(j))
    assert restored == node
