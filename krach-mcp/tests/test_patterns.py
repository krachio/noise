"""Tests for pattern parsing — mini-notation and builder expressions."""

import pytest
from krach.pattern.pattern import Pattern
from krach_mcp._patterns import parse_pattern


def test_mini_notation_hits() -> None:
    pat = parse_pattern("x . x .")
    assert isinstance(pat, Pattern)


def test_mini_notation_notes() -> None:
    pat = parse_pattern("C4 E4 G4")
    assert isinstance(pat, Pattern)


def test_builder_hit_repeat() -> None:
    pat = parse_pattern("hit() * 4")
    assert isinstance(pat, Pattern)


def test_builder_note_over() -> None:
    pat = parse_pattern("note('C4', 'E4').over(2)")
    assert isinstance(pat, Pattern)


def test_builder_sequence() -> None:
    pat = parse_pattern("seq('A2', 'D3', None, 'E2').over(2)")
    assert isinstance(pat, Pattern)


def test_builder_mod_sine() -> None:
    pat = parse_pattern("mod_sine(200.0, 2000.0).over(4)")
    assert isinstance(pat, Pattern)


def test_builder_composition() -> None:
    pat = parse_pattern("note('C4') + rest() + note('E4')")
    assert isinstance(pat, Pattern)


def test_single_note() -> None:
    pat = parse_pattern("C4")
    assert isinstance(pat, Pattern)


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_pattern("")


def test_garbage_raises() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        parse_pattern("$$$not_a_pattern$$$")


def test_eval_no_builtins() -> None:
    """Builder eval must not have access to builtins like open(), exec(), etc."""
    with pytest.raises(ValueError, match="cannot parse"):
        parse_pattern("__import__('os').system('echo pwned')")


# ── Issue #3: chord() and euclid() in MCP play ────────────────────────────


def test_builder_chord() -> None:
    """chord('D4', 'F4', 'A4') must produce a valid Pattern (Stack of notes)."""
    pat = parse_pattern("chord('D4', 'F4', 'A4')")
    assert isinstance(pat, Pattern)


def test_builder_euclid() -> None:
    """euclid(5, 16) must produce a valid Pattern (hit spread over steps)."""
    pat = parse_pattern("euclid(5, 16)")
    assert isinstance(pat, Pattern)


def test_builder_euclid_with_rotation() -> None:
    """euclid(3, 8, 2) must accept rotation parameter."""
    pat = parse_pattern("euclid(3, 8, 2)")
    assert isinstance(pat, Pattern)
