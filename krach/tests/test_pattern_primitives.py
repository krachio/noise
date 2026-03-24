"""Tests for pattern primitive registry + generic fold."""

from __future__ import annotations

import pytest

from krach.ir.pattern import (
    AtomParams,
    CatParams,
    PatternNode,
    PatternPrimitive,
    SilenceParams,
    StackParams,
)
from krach.patterns.ir import Control
from krach.patterns.primitives import (
    atom_p,
    cat_p,
    def_summary,
    fold,
    get_summary_rule,
    silence_p,
    stack_p,
)


def test_fold_leaf() -> None:
    """Fold on a leaf node passes empty child_results."""
    node = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("gate", 1.0)))
    result = fold(node, lambda n, children: f"leaf({n.primitive.name})")
    assert result == "leaf(atom)"


def test_fold_tree() -> None:
    """Fold processes children bottom-up."""
    a = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("a", 1.0)))
    b = PatternNode(primitive=silence_p, children=(), params=SilenceParams())
    cat = PatternNode(primitive=cat_p, children=(a, b), params=CatParams())

    def visitor(node: PatternNode, child_results: tuple[str, ...]) -> str:
        if node.primitive == atom_p:
            return "A"
        if node.primitive == silence_p:
            return "~"
        if node.primitive == cat_p:
            return ", ".join(child_results)
        return "?"

    result = fold(cat, visitor)
    assert result == "A, ~"


def test_fold_nested() -> None:
    """Fold handles deeply nested trees."""
    leaf = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("x", 1.0)))
    stack = PatternNode(primitive=stack_p, children=(leaf, leaf), params=StackParams())
    cat = PatternNode(primitive=cat_p, children=(stack, leaf), params=CatParams())

    def depth(node: PatternNode, child_results: tuple[int, ...]) -> int:
        if not child_results:
            return 0
        return max(child_results) + 1

    assert fold(cat, depth) == 2  # cat → stack → leaf


def test_summary_rule_registration() -> None:
    """Registered summary rules are retrievable."""
    test_p = PatternPrimitive("test_summary_op")
    def_summary(test_p, lambda node, children: "test")
    rule = get_summary_rule(test_p)
    assert rule(
        PatternNode(primitive=test_p, children=(), params=SilenceParams()),
        ()
    ) == "test"


def test_missing_rule_raises() -> None:
    """Accessing an unregistered rule raises RuntimeError."""
    fake_p = PatternPrimitive("nonexistent_op")
    with pytest.raises(RuntimeError, match="No summary rule"):
        get_summary_rule(fake_p)


# ── Freeze(Stack) acceptance test (behavioral pin) ───────────────────────
# This tests the EXISTING bind_voice_poly behavior that must survive
# the migration to the new PatternNode + fold system.


def test_freeze_stack_allocates_separate_voices() -> None:
    """Freeze(Stack([note_A, note_C, note_E])) allocates one voice per note.

    A chord like kr.note("A4", "C5", "E5") produces Freeze(Stack([Freeze(note_A), ...])).
    Each inner Freeze gets its own voice instance. The outer Freeze does NOT allocate.
    """
    from krach._bind import bind_voice_poly
    from krach.patterns.ir import Atom, Cat, Control, Freeze, Stack

    # Simulate kr.note("A4", "C5", "E5") → Freeze(Stack([3 inner Freezes]))
    note_a = Freeze(Cat((
        Stack((Atom(Control("freq", 440.0)), Atom(Control("gate", 1.0)))),
        Atom(Control("gate", 0.0)),
    )))
    note_c = Freeze(Cat((
        Stack((Atom(Control("freq", 523.25)), Atom(Control("gate", 1.0)))),
        Atom(Control("gate", 0.0)),
    )))
    note_e = Freeze(Cat((
        Stack((Atom(Control("freq", 659.25)), Atom(Control("gate", 1.0)))),
        Atom(Control("gate", 0.0)),
    )))
    chord = Freeze(Stack((note_a, note_c, note_e)))

    bound, alloc = bind_voice_poly(chord, "pad", count=4, alloc=0)

    # Each note should be bound to a different voice: pad_v0, pad_v1, pad_v2
    assert alloc == 3  # 3 voices allocated

    # Verify the bound tree has the right voice labels
    from krach._bind import collect_control_labels
    labels = collect_control_labels(bound)
    # Should have pad_v0/freq, pad_v0/gate, pad_v1/freq, pad_v1/gate, pad_v2/freq, pad_v2/gate
    freq_labels = sorted(lab for lab in labels if "freq" in lab)
    assert freq_labels == ["pad_v0/freq", "pad_v1/freq", "pad_v2/freq"]
