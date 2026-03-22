from __future__ import annotations

import pytest

from midiman_frontend.ir import (
    Atom,
    Batch,
    Cat,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Late,
    Note,
    Ping,
    SetBpm,
    Slow,
    Stack,
)
from midiman_frontend.pattern import note


_ATOM = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))


class TestCatValidation:
    def test_empty_children_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one child"):
            Cat(children=())


class TestStackValidation:
    def test_empty_children_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one child"):
            Stack(children=())


class TestFastValidation:
    def test_zero_numerator_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Fast(factor=(0, 1), child=_ATOM)

    def test_negative_numerator_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Fast(factor=(-1, 1), child=_ATOM)

    def test_zero_denominator_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Fast(factor=(1, 0), child=_ATOM)

    def test_valid_factor_ok(self) -> None:
        node = Fast(factor=(2, 1), child=_ATOM)
        assert node.factor == (2, 1)


class TestSlowValidation:
    def test_zero_numerator_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Slow(factor=(0, 1), child=_ATOM)

    def test_zero_denominator_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Slow(factor=(1, 0), child=_ATOM)


class TestEarlyLateValidation:
    def test_early_zero_denominator_raises(self) -> None:
        with pytest.raises(ValueError, match="denominator"):
            Early(offset=(1, 0), child=_ATOM)

    def test_late_zero_denominator_raises(self) -> None:
        with pytest.raises(ValueError, match="denominator"):
            Late(offset=(1, 0), child=_ATOM)

    def test_valid_offset_ok(self) -> None:
        node = Late(offset=(1, 4), child=_ATOM)
        assert node.offset == (1, 4)


class TestEveryValidation:
    def test_zero_n_raises(self) -> None:
        with pytest.raises(ValueError, match="n must be > 0"):
            Every(n=0, transform=_ATOM, child=_ATOM)


class TestEuclidValidation:
    def test_zero_steps_raises(self) -> None:
        with pytest.raises(ValueError, match="steps must be > 0"):
            Euclid(pulses=3, steps=0, rotation=0, child=_ATOM)

    def test_pulses_exceed_steps_raises(self) -> None:
        with pytest.raises(ValueError, match="pulses must be <= steps"):
            Euclid(pulses=9, steps=8, rotation=0, child=_ATOM)

    def test_valid_euclid_ok(self) -> None:
        node = Euclid(pulses=3, steps=8, rotation=0, child=_ATOM)
        assert node.pulses == 3


class TestDegradeValidation:
    def test_prob_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="prob must be in"):
            Degrade(prob=-0.1, seed=0, child=_ATOM)

    def test_prob_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="prob must be in"):
            Degrade(prob=1.1, seed=0, child=_ATOM)

    def test_boundary_values_ok(self) -> None:
        Degrade(prob=0.0, seed=0, child=_ATOM)
        Degrade(prob=1.0, seed=0, child=_ATOM)


class TestBatchValidation:
    def test_empty_batch_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one command"):
            Batch(commands=())

    def test_valid_batch_ok(self) -> None:
        batch = Batch(commands=(Ping(), SetBpm(bpm=120.0)))
        assert len(batch.commands) == 2


class TestPatternMethodValidation:
    def test_fast_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            note(60).fast(0)

    def test_spread_pulses_exceed_steps_raises(self) -> None:
        with pytest.raises(ValueError):
            note(60).spread(9, 8)

    def test_thin_invalid_prob_raises(self) -> None:
        with pytest.raises(ValueError):
            note(60).thin(1.5)
