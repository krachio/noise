"""Tests for pattern backend — PatternNode ↔ IrNode conversion."""

from __future__ import annotations

from krach.backends.pattern_backend import from_ir_node, to_ir_node
from krach.patterns.ir import (
    Atom, Cat, Control, Degrade, Early, Euclid, Every,
    Fast, Freeze, Late, Note, Rev, Silence, Slow, Stack, Warp,
)


def test_atom_round_trip() -> None:
    ir = Atom(Control("gate", 1.0))
    pn = from_ir_node(ir)
    assert to_ir_node(pn) == ir


def test_silence_round_trip() -> None:
    ir = Silence()
    assert to_ir_node(from_ir_node(ir)) == ir


def test_cat_round_trip() -> None:
    ir = Cat((Atom(Note(0, 60, 100, 1.0)), Silence(), Atom(Note(0, 64, 100, 1.0))))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_stack_round_trip() -> None:
    ir = Stack((Atom(Control("freq", 440.0)), Atom(Control("gate", 1.0))))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_freeze_round_trip() -> None:
    ir = Freeze(Cat((Atom(Control("gate", 1.0)), Atom(Control("gate", 0.0)))))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_fast_round_trip() -> None:
    ir = Fast((4, 1), Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_slow_round_trip() -> None:
    ir = Slow((2, 1), Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_euclid_round_trip() -> None:
    ir = Euclid(3, 8, 0, Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_every_round_trip() -> None:
    ir = Every(4, Rev(Atom(Control("gate", 1.0))), Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_degrade_round_trip() -> None:
    ir = Degrade(0.3, 42, Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_warp_round_trip() -> None:
    ir = Warp("swing", 0.67, 2, Atom(Control("gate", 1.0)))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_early_late_rev_round_trip() -> None:
    ir = Early((1, 4), Late((1, 8), Rev(Atom(Control("gate", 1.0)))))
    assert to_ir_node(from_ir_node(ir)) == ir


def test_complex_nested_round_trip() -> None:
    """Full chord pattern: Freeze(Stack([Freeze(Cat([Stack([freq, gate]), gate_off])), ...]))."""
    note_a = Freeze(Cat((
        Stack((Atom(Control("freq", 440.0)), Atom(Control("gate", 1.0)))),
        Atom(Control("gate", 0.0)),
    )))
    note_c = Freeze(Cat((
        Stack((Atom(Control("freq", 523.0)), Atom(Control("gate", 1.0)))),
        Atom(Control("gate", 0.0)),
    )))
    chord = Freeze(Stack((note_a, note_c)))
    fast_chord = Fast((2, 1), chord)

    assert to_ir_node(from_ir_node(fast_chord)) == fast_chord
