"""Tests for IR pattern summary — human-readable compact output."""

from krach._ir_summary import summarize
from krach.patterns.ir import (
    Atom, Cat, Control, Euclid, Fast, Freeze, Note, Silence, Slow, Stack, Warp,
)


def test_note_renders_pitch_name() -> None:
    node = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
    assert summarize(node) == "C4"


def test_note_with_velocity() -> None:
    node = Atom(Note(channel=0, note=69, velocity=80, dur=1.0))
    assert "A4" in summarize(node)


def test_control_renders_label_value() -> None:
    node = Atom(Control(label="cutoff", value=1200.0))
    assert summarize(node) == "cutoff=1200"


def test_control_renders_float_precision() -> None:
    node = Atom(Control(label="gain", value=0.35))
    assert "0.35" in summarize(node)


def test_silence_renders_tilde() -> None:
    assert summarize(Silence()) == "~"


def test_cat_joins_children() -> None:
    node = Cat((
        Atom(Note(0, 45, 100, 1.0)),  # A2
        Silence(),
        Atom(Note(0, 50, 100, 1.0)),  # D3
    ))
    result = summarize(node)
    assert "A2" in result
    assert "~" in result
    assert "D3" in result


def test_cat_truncates_long_sequences() -> None:
    children = tuple(Atom(Note(0, 60 + i, 100, 1.0)) for i in range(20))
    node = Cat(children)
    result = summarize(node, max_items=8)
    assert "..." in result
    assert "12 more" in result


def test_stack_joins_with_pipe() -> None:
    node = Stack((
        Atom(Note(0, 69, 100, 1.0)),  # A4
        Atom(Note(0, 72, 100, 1.0)),  # C5
    ))
    result = summarize(node)
    assert "A4" in result
    assert "|" in result
    assert "C5" in result


def test_freeze_is_transparent() -> None:
    inner = Atom(Note(0, 60, 100, 1.0))
    assert summarize(Freeze(inner)) == summarize(inner)


def test_fast_shows_multiplier() -> None:
    node = Fast((4, 1), Atom(Note(0, 60, 100, 1.0)))
    result = summarize(node)
    assert "C4" in result
    assert "*4" in result


def test_slow_shows_divisor() -> None:
    node = Slow((2, 1), Atom(Note(0, 60, 100, 1.0)))
    result = summarize(node)
    assert "C4" in result
    assert "/2" in result


def test_euclid_shows_spread() -> None:
    node = Euclid(3, 8, 0, Atom(Note(0, 60, 100, 1.0)))
    result = summarize(node)
    assert "3" in result
    assert "8" in result


def test_warp_shows_swing() -> None:
    node = Warp("swing", 0.67, 2, Atom(Note(0, 60, 100, 1.0)))
    result = summarize(node)
    assert "swing" in result


def test_nested_freeze_cat() -> None:
    """Typical note() output: Freeze(Cat([Stack([freq, gate=1]), gate=0]))."""
    inner = Cat((
        Stack((
            Atom(Control("freq", 220.0)),
            Atom(Control("gate", 1.0)),
        )),
        Atom(Control("gate", 0.0)),
    ))
    result = summarize(Freeze(inner))
    assert "freq=220" in result
