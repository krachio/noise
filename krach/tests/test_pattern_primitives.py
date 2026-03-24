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
from krach.patterns.values import Control
from krach.patterns.primitives import (
    atom_p,
    cat_p,
    fold,
    fold_with_state,
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


def test_fold_with_state_counts_atoms() -> None:
    """fold_with_state threads a counter through the tree."""
    a = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("a", 1.0)))
    b = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("b", 2.0)))
    cat = PatternNode(primitive=cat_p, children=(a, b), params=CatParams())

    def count_atoms(
        node: PatternNode,
        child_results: tuple[tuple[PatternNode, int], ...],
        state: int,
    ) -> tuple[PatternNode, int]:
        if node.primitive == atom_p:
            return node, state + 1
        new_children = tuple(cr[0] for cr in child_results)
        return PatternNode(node.primitive, new_children, node.params), state

    result_node, count = fold_with_state(cat, 0, count_atoms)
    assert count == 2
    assert result_node.primitive == cat_p


def test_fold_with_state_threads_left_to_right() -> None:
    """State threads through children in order: a gets state=0, b gets state=1."""
    a = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("a", 0.0)))
    b = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("b", 0.0)))
    cat = PatternNode(primitive=cat_p, children=(a, b), params=CatParams())

    labels: list[tuple[str, int]] = []

    def label_with_index(
        node: PatternNode,
        child_results: tuple[tuple[PatternNode, int], ...],
        state: int,
    ) -> tuple[PatternNode, int]:
        if node.primitive == atom_p:
            assert isinstance(node.params, AtomParams)
            assert isinstance(node.params.value, Control)
            labels.append((node.params.value.label, state))
            return node, state + 1
        new_children = tuple(cr[0] for cr in child_results)
        return PatternNode(node.primitive, new_children, node.params), state

    fold_with_state(cat, 0, label_with_index)
    assert labels == [("a", 0), ("b", 1)]


def test_missing_serialize_rule_raises() -> None:
    """Accessing an unregistered serialize rule raises RuntimeError."""
    from krach.patterns.primitives import get_serialize_rule
    fake_p = PatternPrimitive("nonexistent_op")
    with pytest.raises(RuntimeError, match="No serialize rule"):
        get_serialize_rule(fake_p)


# ── Freeze(Stack) acceptance test (behavioral pin) ───────────────────────
# This tests the EXISTING bind_voice_poly behavior that must survive
# the migration to the new PatternNode + fold system.


def test_freeze_stack_allocates_separate_voices() -> None:
    """Freeze(Stack([note_A, note_C, note_E])) allocates one voice per note.

    A chord like kr.note("A4", "C5", "E5") produces Freeze(Stack([Freeze(note_A), ...])).
    Each inner Freeze gets its own voice instance. The outer Freeze does NOT allocate.
    """
    from krach.ir.pattern import (
        AtomParams, CatParams, FreezeParams, PatternNode, StackParams,
    )
    from krach.patterns.bind import bind_voice_poly, collect_control_labels
    from krach.patterns.values import Control
    from krach.patterns.primitives import atom_p, cat_p, freeze_p, stack_p

    def _ctrl(label: str, value: float) -> PatternNode:
        return PatternNode(atom_p, (), AtomParams(Control(label, value)))

    # Simulate kr.note("A4", "C5", "E5") → Freeze(Stack([3 inner Freezes]))
    note_a = PatternNode(freeze_p, (PatternNode(cat_p, (
        PatternNode(stack_p, (_ctrl("freq", 440.0), _ctrl("gate", 1.0)), StackParams()),
        _ctrl("gate", 0.0),
    ), CatParams()),), FreezeParams())
    note_c = PatternNode(freeze_p, (PatternNode(cat_p, (
        PatternNode(stack_p, (_ctrl("freq", 523.25), _ctrl("gate", 1.0)), StackParams()),
        _ctrl("gate", 0.0),
    ), CatParams()),), FreezeParams())
    note_e = PatternNode(freeze_p, (PatternNode(cat_p, (
        PatternNode(stack_p, (_ctrl("freq", 659.25), _ctrl("gate", 1.0)), StackParams()),
        _ctrl("gate", 0.0),
    ), CatParams()),), FreezeParams())
    chord = PatternNode(freeze_p, (
        PatternNode(stack_p, (note_a, note_c, note_e), StackParams()),
    ), FreezeParams())

    bound, alloc = bind_voice_poly(chord, "pad", count=4, alloc=0)

    # Each note should be bound to a different voice: pad_v0, pad_v1, pad_v2
    assert alloc == 3  # 3 voices allocated

    # Verify the bound tree has the right voice labels
    labels = collect_control_labels(bound)
    # Should have pad_v0/freq, pad_v0/gate, pad_v1/freq, pad_v1/gate, pad_v2/freq, pad_v2/gate
    freq_labels = sorted(lab for lab in labels if "freq" in lab)
    assert freq_labels == ["pad_v0/freq", "pad_v1/freq", "pad_v2/freq"]
