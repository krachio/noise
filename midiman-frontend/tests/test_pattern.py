from __future__ import annotations

from midiman_frontend.ir import (
    Atom,
    Cat,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Late,
    Note,
    Rev,
    Silence,
    Slow,
    Stack,
)
from midiman_frontend.pattern import cc, note, rest


class TestAtomConstructors:
    def test_note_defaults(self) -> None:
        p = note(60)
        assert p.node == Atom(Note(channel=0, note=60, velocity=100, dur=1.0))

    def test_note_custom(self) -> None:
        p = note(36, velocity=80, channel=9, duration=0.5)
        assert p.node == Atom(Note(channel=9, note=36, velocity=80, dur=0.5))

    def test_rest(self) -> None:
        p = rest()
        assert p.node == Silence()

    def test_cc(self) -> None:
        from midiman_frontend.ir import Cc

        p = cc(74, 127, channel=1)
        assert p.node == Atom(Cc(channel=1, controller=74, value=127))


class TestSequenceOperator:
    def test_add_two(self) -> None:
        a, b = note(60), note(64)
        result = a + b
        assert isinstance(result.node, Cat)
        assert len(result.node.children) == 2

    def test_add_three_flattens(self) -> None:
        a, b, c = note(60), note(64), note(67)
        result = (a + b) + c
        assert isinstance(result.node, Cat)
        assert len(result.node.children) == 3

    def test_add_left_and_right_flatten(self) -> None:
        a, b, c, d = note(60), note(64), note(67), note(72)
        result = (a + b) + (c + d)
        assert isinstance(result.node, Cat)
        assert len(result.node.children) == 4


class TestLayerOperator:
    def test_or_two(self) -> None:
        a, b = note(60), note(64)
        result = a | b
        assert isinstance(result.node, Stack)
        assert len(result.node.children) == 2

    def test_or_three_flattens(self) -> None:
        a, b, c = note(60), note(64), note(67)
        result = (a | b) | c
        assert isinstance(result.node, Stack)
        assert len(result.node.children) == 3


class TestRepeatOperator:
    def test_mul(self) -> None:
        p = note(42) * 4
        assert isinstance(p.node, Cat)
        assert len(p.node.children) == 4
        assert all(c == Atom(Note(0, 42, 100, 1.0)) for c in p.node.children)


class TestOverMethod:
    def test_over_gt_1_produces_slow(self) -> None:
        p = note(60).over(2)
        assert isinstance(p.node, Slow)
        assert p.node.factor == (2, 1)

    def test_over_lt_1_produces_fast(self) -> None:
        p = note(60).over(0.5)
        assert isinstance(p.node, Fast)
        assert p.node.factor == (2, 1)

    def test_over_float_rational(self) -> None:
        p = note(60).over(1.5)
        assert isinstance(p.node, Slow)
        assert p.node.factor == (3, 2)


class TestScaleMethod:
    def test_scale_gt_1_produces_fast(self) -> None:
        p = note(60).scale(2)
        assert isinstance(p.node, Fast)
        assert p.node.factor == (2, 1)

    def test_scale_lt_1_produces_slow(self) -> None:
        p = note(60).scale(0.5)
        assert isinstance(p.node, Slow)
        assert p.node.factor == (2, 1)

    def test_scale_float(self) -> None:
        p = note(60).scale(1.5)
        assert isinstance(p.node, Fast)
        assert p.node.factor == (3, 2)


class TestShiftMethod:
    def test_positive_shift_late(self) -> None:
        p = note(60).shift(0.25)
        assert isinstance(p.node, Late)
        assert p.node.offset == (1, 4)

    def test_negative_shift_early(self) -> None:
        p = note(60).shift(-0.25)
        assert isinstance(p.node, Early)
        assert p.node.offset == (1, 4)


class TestTransformMethods:
    def test_reverse(self) -> None:
        p = note(60).reverse()
        assert isinstance(p.node, Rev)

    def test_every(self) -> None:
        p = note(60)
        result = p.every(4, lambda x: x.reverse())
        assert isinstance(result.node, Every)
        assert result.node.n == 4
        assert isinstance(result.node.transform, Rev)
        assert result.node.child == p.node

    def test_spread(self) -> None:
        p = note(36).spread(3, 8)
        assert isinstance(p.node, Euclid)
        assert p.node.pulses == 3
        assert p.node.steps == 8
        assert p.node.rotation == 0

    def test_spread_with_rotation(self) -> None:
        p = note(36).spread(3, 8, rotation=2)
        assert isinstance(p.node, Euclid)
        assert p.node.rotation == 2

    def test_thin(self) -> None:
        p = note(60).thin(0.3)
        assert isinstance(p.node, Degrade)
        assert p.node.prob == 0.3


class TestImmutability:
    def test_scale_does_not_mutate(self) -> None:
        p = note(60)
        original_node = p.node
        _ = p.scale(2)
        assert p.node is original_node

    def test_add_does_not_mutate(self) -> None:
        a = note(60)
        b = note(64)
        original = a.node
        _ = a + b
        assert a.node is original


class TestChaining:
    def test_chain_builds_nested_tree(self) -> None:
        p = note(60).scale(2).reverse().thin(0.1)
        assert isinstance(p.node, Degrade)
        assert isinstance(p.node.child, Rev)
        rev_child = p.node.child
        assert isinstance(rev_child, Rev)
        assert isinstance(rev_child.child, Fast)
