"""Tests for the unified Pattern IR — PatternPrimitive + PatternNode."""

from __future__ import annotations

import pytest

from krach.ir.pattern import (
    PatternNode,
    PatternPrimitive,
    AtomParams,
    CatParams,
    FastParams,
    SilenceParams,
    StackParams,
)
from krach.patterns.ir import Control, Note


# ── PatternPrimitive ─────────────────────────────────────────────────────


def test_primitive_equality() -> None:
    a = PatternPrimitive("cat")
    b = PatternPrimitive("cat")
    assert a == b
    assert hash(a) == hash(b)


def test_primitive_inequality() -> None:
    assert PatternPrimitive("cat") != PatternPrimitive("stack")


# ── PatternNode construction ─────────────────────────────────────────────


def test_atom_node() -> None:
    atom_p = PatternPrimitive("atom")
    node = PatternNode(
        primitive=atom_p,
        children=(),
        params=AtomParams(value=Control(label="gate", value=1.0)),
    )
    assert node.primitive.name == "atom"
    assert isinstance(node.params, AtomParams)
    assert node.params.value == Control(label="gate", value=1.0)


def test_silence_node() -> None:
    silence_p = PatternPrimitive("silence")
    node = PatternNode(primitive=silence_p, children=(), params=SilenceParams())
    assert node.primitive.name == "silence"
    assert node.children == ()


def test_cat_node() -> None:
    atom_p = PatternPrimitive("atom")
    cat_p = PatternPrimitive("cat")
    a = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Note(0, 60, 100, 1.0)))
    b = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Note(0, 64, 100, 1.0)))
    cat = PatternNode(primitive=cat_p, children=(a, b), params=CatParams())
    assert len(cat.children) == 2
    assert cat.children[0].params.value.note == 60  # type: ignore[union-attr]
    assert cat.children[1].params.value.note == 64  # type: ignore[union-attr]


def test_fast_node() -> None:
    atom_p = PatternPrimitive("atom")
    fast_p = PatternPrimitive("fast")
    child = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("gate", 1.0)))
    fast = PatternNode(primitive=fast_p, children=(child,), params=FastParams(factor=(4, 1)))
    assert fast.params.factor == (4, 1)  # type: ignore[union-attr]
    assert len(fast.children) == 1


def test_stack_node() -> None:
    atom_p = PatternPrimitive("atom")
    stack_p = PatternPrimitive("stack")
    a = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("freq", 440.0)))
    b = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("gate", 1.0)))
    stack = PatternNode(primitive=stack_p, children=(a, b), params=StackParams())
    assert len(stack.children) == 2


# ── Frozen immutability ──────────────────────────────────────────────────


def test_pattern_node_frozen() -> None:
    atom_p = PatternPrimitive("atom")
    node = PatternNode(primitive=atom_p, children=(), params=AtomParams(value=Control("gate", 1.0)))
    with pytest.raises(AttributeError):
        node.children = ()  # type: ignore[misc]


def test_pattern_primitive_frozen() -> None:
    p = PatternPrimitive("cat")
    with pytest.raises(AttributeError):
        p.name = "stack"  # type: ignore[misc]
