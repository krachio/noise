import pytest
from krach.patterns.ir import Atom, Cat, Control, Freeze, IrNode, Silence, Slow, Stack

from krach._mininotation import p


def test_single_hit() -> None:
    pat = p("x")
    # hit() produces Freeze(Cat([Control(gate, 1), Control(gate, 0)]))
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Cat)
    assert any(
        isinstance(c, Atom) and isinstance(c.value, Control) and c.value.label == "gate"
        for c in inner.children
    )


def test_single_note() -> None:
    pat = p("C4")
    # note("C4") -> Freeze(Cat([Stack(freq, gate=1), gate=0]))
    assert isinstance(pat.node, Freeze)
    inner = pat.node.child
    assert isinstance(inner, Cat)
    # Collect all Control labels recursively
    labels = _collect_labels(inner)
    assert "freq" in labels
    assert "gate" in labels


def _collect_labels(node: IrNode) -> set[str]:
    """Recursively collect Control labels from an IR tree."""
    labels: set[str] = set()
    match node:
        case Atom(value=Control(label=label)):
            labels.add(label)
        case Freeze(child=child):
            labels |= _collect_labels(child)
        case Cat(children=children) | Stack(children=children):
            for c in children:
                labels |= _collect_labels(c)
        case _:
            pass
    return labels


def test_rest_dot() -> None:
    pat = p(".")
    assert isinstance(pat.node, Silence)


def test_rest_tilde() -> None:
    pat = p("~")
    assert isinstance(pat.node, Silence)


def test_rest_dash() -> None:
    pat = p("-")
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
    pat = p("C4 E4", vel=0.5)
    # vel kwarg should appear as a Control in the IR
    assert isinstance(pat.node, Cat)
    labels = _collect_labels(pat.node.children[0])
    assert "vel" in labels


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty pattern"):
        p("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="empty pattern"):
        p("   ")


def test_composable_with_over() -> None:
    pat = p("C4 E4 G4").over(2)
    assert isinstance(pat.node, Slow)


def test_repeat_note() -> None:
    pat = p("C4*2 E4 G4")
    assert isinstance(pat.node, Cat)
    assert len(pat.node.children) == 4  # C4 C4 E4 G4 flattened


def test_sharp_note() -> None:
    pat = p("C#4")
    assert isinstance(pat.node, Freeze)
    labels = _collect_labels(pat.node)
    assert "freq" in labels
    # C#4 = MIDI 61, verify the freq value is correct (≈ 277.18 Hz)
    freq_val = _find_control_value(pat.node, "freq")
    assert freq_val is not None
    assert abs(freq_val - 277.18) < 1.0


def _find_control_value(node: IrNode, target: str) -> float | None:
    """Find the value of a specific Control label in an IR tree."""
    match node:
        case Atom(value=Control(label=label, value=value)) if label == target:
            return value
        case Freeze(child=child):
            return _find_control_value(child, target)
        case Cat(children=children) | Stack(children=children):
            for c in children:
                result = _find_control_value(c, target)
                if result is not None:
                    return result
        case _:
            pass
    return None


def test_single_rest_no_cat() -> None:
    """A single token should not be wrapped in Cat."""
    pat = p("~")
    assert isinstance(pat.node, Silence)
    assert not isinstance(pat.node, Cat)
