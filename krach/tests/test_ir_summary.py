"""Tests for pattern summary — human-readable compact output via PatternNode."""

from krach.pattern.summary import summarize
from krach.pattern.types import (
    AtomParams, CatParams, DegradeParams, EuclidParams, FastParams,
    FreezeParams, PatternNode, SilenceParams, SlowParams, StackParams,
    WarpParams,
)
from krach.ir.values import Control, Note
from krach.pattern.primitives import (
    atom_p, cat_p, degrade_p, euclid_p, fast_p, freeze_p,
    silence_p, slow_p, stack_p, warp_p,
)


def _note(midi: int) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Note(0, midi, 100, 1.0)))


def _ctrl(label: str, value: float) -> PatternNode:
    return PatternNode(atom_p, (), AtomParams(Control(label, value)))


def _silence() -> PatternNode:
    return PatternNode(silence_p, (), SilenceParams())


def test_note_renders_pitch_name() -> None:
    assert summarize(_note(60)) == "C4"


def test_note_with_velocity() -> None:
    assert "A4" in summarize(_note(69))


def test_control_renders_label_value() -> None:
    assert summarize(_ctrl("cutoff", 1200.0)) == "cutoff=1200"


def test_control_renders_float_precision() -> None:
    assert "0.35" in summarize(_ctrl("gain", 0.35))


def test_silence_renders_tilde() -> None:
    assert summarize(_silence()) == "~"


def test_cat_joins_children() -> None:
    node = PatternNode(cat_p, (_note(45), _silence(), _note(50)), CatParams())
    result = summarize(node)
    assert "A2" in result
    assert "~" in result
    assert "D3" in result


def test_cat_truncates_long_sequences() -> None:
    children = tuple(_note(60 + i) for i in range(20))
    node = PatternNode(cat_p, children, CatParams())
    result = summarize(node, max_items=8)
    assert "..." in result
    assert "12 more" in result


def test_stack_joins_with_pipe() -> None:
    node = PatternNode(stack_p, (_note(69), _note(72)), StackParams())
    result = summarize(node)
    assert "A4" in result
    assert "|" in result
    assert "C5" in result


def test_freeze_is_transparent() -> None:
    inner = _note(60)
    frozen = PatternNode(freeze_p, (inner,), FreezeParams())
    assert summarize(frozen) == summarize(inner)


def test_fast_shows_multiplier() -> None:
    node = PatternNode(fast_p, (_note(60),), FastParams((4, 1)))
    result = summarize(node)
    assert "C4" in result
    assert "*4" in result


def test_slow_shows_divisor() -> None:
    node = PatternNode(slow_p, (_note(60),), SlowParams((2, 1)))
    result = summarize(node)
    assert "C4" in result
    assert "/2" in result


def test_euclid_shows_spread() -> None:
    node = PatternNode(euclid_p, (_note(60),), EuclidParams(3, 8, 0))
    result = summarize(node)
    assert "3" in result
    assert "8" in result


def test_warp_shows_swing() -> None:
    node = PatternNode(warp_p, (_note(60),), WarpParams("swing", 0.67, 2))
    result = summarize(node)
    assert "swing" in result


def test_nested_freeze_cat() -> None:
    """Typical note() output: Freeze(Cat([Stack([freq, gate=1]), gate=0]))."""
    inner = PatternNode(cat_p, (
        PatternNode(stack_p, (
            _ctrl("freq", 220.0),
            _ctrl("gate", 1.0),
        ), StackParams()),
        _ctrl("gate", 0.0),
    ), CatParams())
    result = summarize(PatternNode(freeze_p, (inner,), FreezeParams()))
    assert "freq=220" in result


def test_degrade_shows_thin() -> None:
    node = PatternNode(degrade_p, (_note(60),), DegradeParams(0.5, 0))
    result = summarize(node)
    assert "thin" in result
    assert "50%" in result
