"""Tests for pattern backend — PatternNode → IrNode lowering."""

from __future__ import annotations

from krach.backends.pattern_backend import to_ir_node
from krach.ir.pattern import (
    AtomParams, CatParams, DegradeParams, EarlyParams, EuclidParams,
    EveryParams, FastParams, FreezeParams, LateParams, PatternNode,
    RevParams, SilenceParams, SlowParams, StackParams, WarpParams,
)
from krach.patterns.ir import (
    Atom, Cat, Control, Degrade, Early, Euclid, Every,
    Fast, Freeze, Late, Note, Rev, Silence, Slow, Stack, Warp,
)
from krach.patterns.primitives import (
    atom_p, cat_p, degrade_p, early_p, euclid_p, every_p,
    fast_p, freeze_p, late_p, rev_p, silence_p, slow_p, stack_p, warp_p,
)


def test_atom_lowering() -> None:
    pn = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    assert to_ir_node(pn) == Atom(Control("gate", 1.0))


def test_silence_lowering() -> None:
    pn = PatternNode(silence_p, (), SilenceParams())
    assert to_ir_node(pn) == Silence()


def test_cat_lowering() -> None:
    a = PatternNode(atom_p, (), AtomParams(Note(0, 60, 100, 1.0)))
    b = PatternNode(silence_p, (), SilenceParams())
    c = PatternNode(atom_p, (), AtomParams(Note(0, 64, 100, 1.0)))
    cat = PatternNode(cat_p, (a, b, c), CatParams())
    assert to_ir_node(cat) == Cat((Atom(Note(0, 60, 100, 1.0)), Silence(), Atom(Note(0, 64, 100, 1.0))))


def test_stack_lowering() -> None:
    a = PatternNode(atom_p, (), AtomParams(Control("freq", 440.0)))
    b = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    stk = PatternNode(stack_p, (a, b), StackParams())
    assert to_ir_node(stk) == Stack((Atom(Control("freq", 440.0)), Atom(Control("gate", 1.0))))


def test_freeze_lowering() -> None:
    inner = PatternNode(cat_p, (
        PatternNode(atom_p, (), AtomParams(Control("gate", 1.0))),
        PatternNode(atom_p, (), AtomParams(Control("gate", 0.0))),
    ), CatParams())
    frz = PatternNode(freeze_p, (inner,), FreezeParams())
    expected = Freeze(Cat((Atom(Control("gate", 1.0)), Atom(Control("gate", 0.0)))))
    assert to_ir_node(frz) == expected


def test_fast_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    fast = PatternNode(fast_p, (child,), FastParams((4, 1)))
    assert to_ir_node(fast) == Fast((4, 1), Atom(Control("gate", 1.0)))


def test_slow_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    slow = PatternNode(slow_p, (child,), SlowParams((2, 1)))
    assert to_ir_node(slow) == Slow((2, 1), Atom(Control("gate", 1.0)))


def test_euclid_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    euc = PatternNode(euclid_p, (child,), EuclidParams(3, 8, 0))
    assert to_ir_node(euc) == Euclid(3, 8, 0, Atom(Control("gate", 1.0)))


def test_every_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    transform = PatternNode(rev_p, (child,), RevParams())
    evry = PatternNode(every_p, (transform, child), EveryParams(4))
    expected = Every(4, Rev(Atom(Control("gate", 1.0))), Atom(Control("gate", 1.0)))
    assert to_ir_node(evry) == expected


def test_degrade_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    deg = PatternNode(degrade_p, (child,), DegradeParams(0.3, 42))
    assert to_ir_node(deg) == Degrade(0.3, 42, Atom(Control("gate", 1.0)))


def test_warp_lowering() -> None:
    child = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    wrp = PatternNode(warp_p, (child,), WarpParams("swing", 0.67, 2))
    assert to_ir_node(wrp) == Warp("swing", 0.67, 2, Atom(Control("gate", 1.0)))


def test_early_late_rev_lowering() -> None:
    leaf = PatternNode(atom_p, (), AtomParams(Control("gate", 1.0)))
    revd = PatternNode(rev_p, (leaf,), RevParams())
    lated = PatternNode(late_p, (revd,), LateParams((1, 8)))
    earlyd = PatternNode(early_p, (lated,), EarlyParams((1, 4)))
    expected = Early((1, 4), Late((1, 8), Rev(Atom(Control("gate", 1.0)))))
    assert to_ir_node(earlyd) == expected


def test_complex_chord_lowering() -> None:
    """Full chord: Freeze(Stack([Freeze(Cat([Stack([freq, gate]), gate_off])), ...]))."""
    def make_note(freq: float) -> PatternNode:
        onset = PatternNode(stack_p, (
            PatternNode(atom_p, (), AtomParams(Control("freq", freq))),
            PatternNode(atom_p, (), AtomParams(Control("gate", 1.0))),
        ), StackParams())
        release = PatternNode(atom_p, (), AtomParams(Control("gate", 0.0)))
        return PatternNode(freeze_p, (
            PatternNode(cat_p, (onset, release), CatParams()),
        ), FreezeParams())

    chord = PatternNode(freeze_p, (
        PatternNode(stack_p, (make_note(440.0), make_note(523.0)), StackParams()),
    ), FreezeParams())

    fast_chord = PatternNode(fast_p, (chord,), FastParams((2, 1)))

    ir = to_ir_node(fast_chord)
    assert isinstance(ir, Fast)
    assert ir.factor == (2, 1)
    assert isinstance(ir.child, Freeze)
