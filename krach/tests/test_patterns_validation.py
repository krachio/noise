from __future__ import annotations

import pytest

from krach.backends.pattern import (
    Batch,
    Ping,
    SetBpm,
)
from krach.ir.pattern import (
    DegradeParams,
    EuclidParams,
    WarpParams,
)
from krach.pattern.pattern import midi_note as note


class TestEuclidParamsValidation:
    def test_zero_steps_raises(self) -> None:
        with pytest.raises(ValueError, match="steps must be > 0"):
            EuclidParams(pulses=3, steps=0, rotation=0)

    def test_pulses_exceed_steps_raises(self) -> None:
        with pytest.raises(ValueError, match="pulses must be <= steps"):
            EuclidParams(pulses=9, steps=8, rotation=0)

    def test_valid_euclid_ok(self) -> None:
        p = EuclidParams(pulses=3, steps=8, rotation=0)
        assert p.pulses == 3


class TestDegradeParamsValidation:
    def test_prob_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="prob must be in"):
            DegradeParams(prob=-0.1, seed=0)

    def test_prob_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="prob must be in"):
            DegradeParams(prob=1.1, seed=0)

    def test_boundary_values_ok(self) -> None:
        DegradeParams(prob=0.0, seed=0)
        DegradeParams(prob=1.0, seed=0)


class TestWarpParamsValidation:
    def test_amount_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="amount must be in"):
            WarpParams(kind="swing", amount=0.0, grid=8)

    def test_amount_one_raises(self) -> None:
        with pytest.raises(ValueError, match="amount must be in"):
            WarpParams(kind="swing", amount=1.0, grid=8)

    def test_odd_grid_raises(self) -> None:
        with pytest.raises(ValueError, match="grid must be even"):
            WarpParams(kind="swing", amount=0.5, grid=3)

    def test_zero_grid_raises(self) -> None:
        with pytest.raises(ValueError, match="grid must be even"):
            WarpParams(kind="swing", amount=0.5, grid=0)

    def test_valid_warp_ok(self) -> None:
        p = WarpParams(kind="swing", amount=0.67, grid=8)
        assert p.amount == 0.67


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
