import pytest
from krach.patterns.ir import Cat, Silence, Stack
from krach.patterns.pattern import Pattern

from krach._mininotation import p


def test_single_hit() -> None:
    pat = p("x")
    assert isinstance(pat, Pattern)


def test_single_note() -> None:
    pat = p("C4")
    assert isinstance(pat, Pattern)


def test_rest_dot() -> None:
    pat = p(".")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Silence)


def test_rest_tilde() -> None:
    pat = p("~")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Silence)


def test_rest_dash() -> None:
    pat = p("-")
    assert isinstance(pat, Pattern)
    assert isinstance(pat.node, Silence)


def test_sequence() -> None:
    pat = p("C4 E4 G4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3


def test_mixed_hits_and_rests() -> None:
    pat = p("x . x . x . . x")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 8


def test_repeat() -> None:
    pat = p("x*4")
    # hit() * 4 produces a Cat with 4 children
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 4


def test_stack() -> None:
    pat = p("[C4 E4 G4]")
    assert isinstance(pat.node, Stack)
    assert len(pat.node.children) == 3


def test_stack_in_sequence() -> None:
    pat = p("[C4 E4] G4 B4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 3
    assert isinstance(pat.node.children[0], Stack)


def test_kwargs_passed_to_notes() -> None:
    # Should not raise — vel is a valid kwarg for note()
    pat = p("C4 E4", vel=0.5)
    assert isinstance(pat, Pattern)


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty pattern"):
        p("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="empty pattern"):
        p("   ")


def test_composable_with_over() -> None:
    pat = p("C4 E4 G4").over(2)
    assert isinstance(pat, Pattern)


def test_repeat_note() -> None:
    pat = p("C4*2 E4 G4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 4  # C4 C4 E4 G4 flattened


def test_sharp_note() -> None:
    pat = p("C#4")
    assert isinstance(pat, Pattern)


def test_single_rest_no_cat() -> None:
    """A single token should not be wrapped in Cat."""
    pat = p("~")
    assert isinstance(pat.node, Silence)
    assert not isinstance(pat.node, Cat)
