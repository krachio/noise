from __future__ import annotations

from krach.ir.pattern import (
    AtomParams,
    DegradeParams,
    EarlyParams,
    EuclidParams,
    EveryParams,
    FastParams,
    LateParams,
    SilenceParams,
    SlowParams,
    WarpParams,
)
from krach.patterns.values import Note
from krach.patterns.pattern import cc, note, rest


class TestAtomConstructors:
    def test_note_defaults(self) -> None:
        p = note(60)
        assert p.node.primitive.name == "atom"
        assert p.node.params == AtomParams(Note(channel=0, note=60, velocity=100, dur=1.0))

    def test_note_custom(self) -> None:
        p = note(36, velocity=80, channel=9, duration=0.5)
        assert p.node.primitive.name == "atom"
        assert p.node.params == AtomParams(Note(channel=9, note=36, velocity=80, dur=0.5))

    def test_rest(self) -> None:
        p = rest()
        assert p.node.primitive.name == "silence"
        assert isinstance(p.node.params, SilenceParams)

    def test_cc(self) -> None:
        from krach.patterns.values import Cc

        p = cc(74, 127, channel=1)
        assert p.node.primitive.name == "atom"
        assert p.node.params == AtomParams(Cc(channel=1, controller=74, value=127))


class TestSequenceOperator:
    def test_add_two(self) -> None:
        a, b = note(60), note(64)
        result = a + b
        assert result.node.primitive.name == "cat"
        assert len(result.node.children) == 2

    def test_add_three_flattens(self) -> None:
        a, b, c = note(60), note(64), note(67)
        result = (a + b) + c
        assert result.node.primitive.name == "cat"
        assert len(result.node.children) == 3

    def test_add_left_and_right_flatten(self) -> None:
        a, b, c, d = note(60), note(64), note(67), note(72)
        result = (a + b) + (c + d)
        assert result.node.primitive.name == "cat"
        assert len(result.node.children) == 4


class TestLayerOperator:
    def test_or_two(self) -> None:
        a, b = note(60), note(64)
        result = a | b
        assert result.node.primitive.name == "stack"
        assert len(result.node.children) == 2

    def test_or_three_flattens(self) -> None:
        a, b, c = note(60), note(64), note(67)
        result = (a | b) | c
        assert result.node.primitive.name == "stack"
        assert len(result.node.children) == 3


class TestRepeatOperator:
    def test_mul(self) -> None:
        p = note(42) * 4
        assert p.node.primitive.name == "cat"
        assert len(p.node.children) == 4
        expected = AtomParams(Note(0, 42, 100, 1.0))
        assert all(c.primitive.name == "atom" and c.params == expected for c in p.node.children)


class TestOverMethod:
    def test_over_gt_1_produces_slow(self) -> None:
        p = note(60).over(2)
        assert p.node.primitive.name == "slow"
        assert isinstance(p.node.params, SlowParams)
        assert p.node.params.factor == (2, 1)

    def test_over_lt_1_produces_fast(self) -> None:
        p = note(60).over(0.5)
        assert p.node.primitive.name == "fast"
        assert isinstance(p.node.params, FastParams)
        assert p.node.params.factor == (2, 1)

    def test_over_float_rational(self) -> None:
        p = note(60).over(1.5)
        assert p.node.primitive.name == "slow"
        assert isinstance(p.node.params, SlowParams)
        assert p.node.params.factor == (3, 2)

    def test_over_non_dyadic_float_produces_bounded_rational(self) -> None:
        """0.9 must produce (9, 10), not a huge binary fraction."""
        p = note(60).over(0.9)
        assert p.node.primitive.name == "fast"
        assert isinstance(p.node.params, FastParams)
        # Inverted: over(0.9) -> Fast(10/9) because 0.9 < 1
        assert p.node.params.factor == (10, 9)

    def test_over_third_produces_bounded_rational(self) -> None:
        p = note(60).over(1 / 3)
        assert p.node.primitive.name == "fast"
        assert isinstance(p.node.params, FastParams)
        assert p.node.params.factor == (3, 1)


class TestFastMethod:
    def test_fast_gt_1_produces_fast(self) -> None:
        p = note(60).fast(2)
        assert p.node.primitive.name == "fast"
        assert isinstance(p.node.params, FastParams)
        assert p.node.params.factor == (2, 1)

    def test_fast_lt_1_produces_slow(self) -> None:
        p = note(60).fast(0.5)
        assert p.node.primitive.name == "slow"
        assert isinstance(p.node.params, SlowParams)
        assert p.node.params.factor == (2, 1)

    def test_fast_float(self) -> None:
        p = note(60).fast(1.5)
        assert p.node.primitive.name == "fast"
        assert isinstance(p.node.params, FastParams)
        assert p.node.params.factor == (3, 2)


class TestShiftMethod:
    def test_positive_shift_late(self) -> None:
        p = note(60).shift(0.25)
        assert p.node.primitive.name == "late"
        assert isinstance(p.node.params, LateParams)
        assert p.node.params.offset == (1, 4)

    def test_negative_shift_early(self) -> None:
        p = note(60).shift(-0.25)
        assert p.node.primitive.name == "early"
        assert isinstance(p.node.params, EarlyParams)
        assert p.node.params.offset == (1, 4)


class TestTransformMethods:
    def test_reverse(self) -> None:
        p = note(60).reverse()
        assert p.node.primitive.name == "rev"

    def test_every(self) -> None:
        p = note(60)
        result = p.every(4, lambda x: x.reverse())
        assert result.node.primitive.name == "every"
        assert isinstance(result.node.params, EveryParams)
        assert result.node.params.n == 4
        assert result.node.children[0].primitive.name == "rev"
        assert result.node.children[1] == p.node

    def test_spread(self) -> None:
        p = note(36).spread(3, 8)
        assert p.node.primitive.name == "euclid"
        assert isinstance(p.node.params, EuclidParams)
        assert p.node.params.pulses == 3
        assert p.node.params.steps == 8
        assert p.node.params.rotation == 0

    def test_spread_with_rotation(self) -> None:
        p = note(36).spread(3, 8, rotation=2)
        assert p.node.primitive.name == "euclid"
        assert isinstance(p.node.params, EuclidParams)
        assert p.node.params.rotation == 2

    def test_thin(self) -> None:
        p = note(60).thin(0.3)
        assert p.node.primitive.name == "degrade"
        assert isinstance(p.node.params, DegradeParams)
        assert p.node.params.prob == 0.3


class TestImmutability:
    def test_fast_does_not_mutate(self) -> None:
        p = note(60)
        original_node = p.node
        _ = p.fast(2)
        assert p.node is original_node

    def test_add_does_not_mutate(self) -> None:
        a = note(60)
        b = note(64)
        original = a.node
        _ = a + b
        assert a.node is original


class TestOverZeroValidation:
    def test_over_zero_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="positive cycles"):
            note(60).over(0)

    def test_over_negative_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="positive cycles"):
            note(60).over(-1)

    def test_fast_zero_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="positive factor"):
            note(60).fast(0)

    def test_fast_negative_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="positive factor"):
            note(60).fast(-0.5)


class TestChaining:
    def test_chain_builds_nested_tree(self) -> None:
        p = note(60).fast(2).reverse().thin(0.1)
        assert p.node.primitive.name == "degrade"
        assert p.node.children[0].primitive.name == "rev"
        rev_child = p.node.children[0]
        assert rev_child.primitive.name == "rev"
        assert rev_child.children[0].primitive.name == "fast"


# -- Sprint 12 adversarial: fast()/over() with inf/nan --------------------


class TestFastInfNan:
    """BUG: fast(float('inf')) raises OverflowError and fast(float('nan'))
    raises ValueError with confusing Fraction internals messages. These should
    raise ValueError with a clear message before reaching _to_rational().

    Root cause: pattern.py:76-82 -- fast() checks `factor <= 0` which passes
    for inf and nan, then Fraction(value) crashes with internal errors.
    """

    def test_fast_inf_raises_valueerror(self) -> None:
        """fast(inf) should raise ValueError, not OverflowError."""
        import pytest
        with pytest.raises(ValueError, match="positive factor"):
            note(60).fast(float("inf"))

    def test_fast_nan_raises_valueerror_with_clear_message(self) -> None:
        """fast(nan) should raise ValueError with 'positive factor' message."""
        import pytest
        with pytest.raises(ValueError, match="positive factor"):
            note(60).fast(float("nan"))

    def test_over_inf_raises_valueerror(self) -> None:
        """over(inf) should raise ValueError, not OverflowError."""
        import pytest
        with pytest.raises(ValueError, match="positive cycles"):
            note(60).over(float("inf"))

    def test_over_nan_raises_valueerror_with_clear_message(self) -> None:
        """over(nan) should raise ValueError with 'positive cycles' message."""
        import pytest
        with pytest.raises(ValueError, match="positive cycles"):
            note(60).over(float("nan"))


# -- Swing -----------------------------------------------------------------


class TestSwing:
    def test_swing_produces_warp_node(self) -> None:
        pat = note(60).swing(0.67)
        assert pat.node.primitive.name == "warp"
        assert isinstance(pat.node.params, WarpParams)
        assert pat.node.params.kind == "swing"
        assert pat.node.params.amount == 0.67
        assert pat.node.params.grid == 8

    def test_swing_default_args(self) -> None:
        pat = note(60).swing()
        assert pat.node.primitive.name == "warp"
        assert isinstance(pat.node.params, WarpParams)
        assert pat.node.params.amount == 0.67
        assert pat.node.params.grid == 8

    def test_swing_custom_grid(self) -> None:
        pat = note(60).swing(0.6, grid=4)
        assert pat.node.primitive.name == "warp"
        assert isinstance(pat.node.params, WarpParams)
        assert pat.node.params.grid == 4

    def test_swing_invalid_amount_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="amount must be in"):
            note(60).swing(0.0)
        with pytest.raises(ValueError, match="amount must be in"):
            note(60).swing(1.0)

    def test_swing_invalid_grid_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="grid must be even"):
            note(60).swing(0.67, grid=7)
        with pytest.raises(ValueError, match="grid must be even"):
            note(60).swing(0.67, grid=0)


class TestRepr:
    def test_note_repr(self) -> None:
        p = note(60)
        assert repr(p) == "Pattern(C4)"

    def test_rest_repr(self) -> None:
        p = rest()
        assert repr(p) == "Pattern(~)"

    def test_sequence_repr(self) -> None:
        p = note(60) + note(64) + note(67)
        r = repr(p)
        assert r.startswith("Pattern(")
        assert "C4" in r
        assert "E4" in r
        assert "G4" in r

    def test_fast_repr(self) -> None:
        p = note(60).fast(2)
        assert "*2" in repr(p)

    def test_over_repr(self) -> None:
        p = note(60).over(2)
        assert "/2" in repr(p)
