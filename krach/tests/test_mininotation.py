import pytest
from krach.ir.pattern import AtomParams
from krach.pattern.values import Control

from krach._mininotation import p


def test_single_hit() -> None:
    pat = p("x")
    # hit() produces Freeze(Cat([Control(gate, 1), Control(gate, 0)]))
    assert pat.node.primitive.name == "freeze"
    inner = pat.node.children[0]
    assert inner.primitive.name == "cat"
    assert any(
        c.primitive.name == "atom" and isinstance(c.params, AtomParams) and isinstance(c.params.value, Control) and c.params.value.label == "gate"
        for c in inner.children
    )


def test_single_note() -> None:
    pat = p("C4")
    # note("C4") -> Freeze(Cat([Stack(freq, gate=1), gate=0]))
    assert pat.node.primitive.name == "freeze"
    inner = pat.node.children[0]
    assert inner.primitive.name == "cat"
    # Collect all Control labels recursively
    labels = _collect_labels(inner)
    assert "freq" in labels
    assert "gate" in labels


def _collect_labels(node: object) -> set[str]:
    """Recursively collect Control labels from a PatternNode tree."""
    from krach.ir.pattern import PatternNode, AtomParams
    from krach.pattern.values import Control
    labels: set[str] = set()
    if not isinstance(node, PatternNode):
        return labels
    if isinstance(node.params, AtomParams) and isinstance(node.params.value, Control):
        labels.add(node.params.value.label)
    for child in node.children:
        labels |= _collect_labels(child)
    return labels


def test_rest_dot() -> None:
    pat = p(".")
    assert pat.node.primitive.name == "silence"


def test_rest_tilde() -> None:
    pat = p("~")
    assert pat.node.primitive.name == "silence"


def test_rest_dash() -> None:
    pat = p("-")
    assert pat.node.primitive.name == "silence"


def test_sequence() -> None:
    pat = p("C4 E4 G4")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3


def test_mixed_hits_and_rests() -> None:
    pat = p("x . x . x . . x")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 8


def test_repeat() -> None:
    pat = p("x*4")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 4


def test_stack() -> None:
    pat = p("[C4 E4 G4]")
    assert pat.node.primitive.name == "stack"
    assert len(pat.node.children) == 3


def test_stack_in_sequence() -> None:
    pat = p("[C4 E4] G4 B4")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 3
    assert pat.node.children[0].primitive.name == "stack"


def test_kwargs_passed_to_notes() -> None:
    pat = p("C4 E4", vel=0.5)
    # vel kwarg should appear as a Control in the IR
    assert pat.node.primitive.name == "cat"
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
    assert pat.node.primitive.name == "slow"


def test_repeat_note() -> None:
    pat = p("C4*2 E4 G4")
    assert pat.node.primitive.name == "cat"
    assert len(pat.node.children) == 4  # C4 C4 E4 G4 flattened


def test_sharp_note() -> None:
    pat = p("C#4")
    assert pat.node.primitive.name == "freeze"
    labels = _collect_labels(pat.node)
    assert "freq" in labels
    # C#4 = MIDI 61, verify the freq value is correct (≈ 277.18 Hz)
    freq_val = _find_control_value(pat.node, "freq")
    assert freq_val is not None
    assert abs(freq_val - 277.18) < 1.0


def _find_control_value(node: object, target: str) -> float | None:
    """Find the value of a specific Control label in a PatternNode tree."""
    from krach.ir.pattern import PatternNode, AtomParams
    from krach.pattern.values import Control
    if not isinstance(node, PatternNode):
        return None
    if isinstance(node.params, AtomParams) and isinstance(node.params.value, Control):
        if node.params.value.label == target:
            return node.params.value.value
    for child in node.children:
        result = _find_control_value(child, target)
        if result is not None:
            return result
    return None


def test_single_rest_no_cat() -> None:
    """A single token should not be wrapped in Cat."""
    pat = p("~")
    assert pat.node.primitive.name == "silence"
    assert not pat.node.primitive.name == "cat"


def test_unmatched_bracket_raises() -> None:
    with pytest.raises(ValueError, match="unmatched '\\['"):
        p("[C4 E4")


def test_invalid_repeat_count_raises() -> None:
    with pytest.raises(ValueError, match="invalid repeat count"):
        p("C4*abc")


def test_repeat_zero_raises() -> None:
    with pytest.raises(ValueError, match="repeat count must be >= 1"):
        p("C4*0")


def test_invalid_note_token_raises() -> None:
    with pytest.raises(ValueError, match="invalid token"):
        p("G$4")


def test_invalid_token_gibberish_raises() -> None:
    with pytest.raises(ValueError, match="invalid token"):
        p("hello")
