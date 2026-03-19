"""Tests for Commit 4 — control() primitive + transpile() entry point."""

from __future__ import annotations

from faust_dsl._core import Signal
from faust_dsl.transpile import control, transpile


def test_control_emits_hslider() -> None:
    def dsp() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    result = transpile(dsp)
    assert 'hslider("freq", 440' in result.source


def test_control_schema_populated() -> None:
    def dsp() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    result = transpile(dsp)
    assert len(result.schema.controls) == 1
    spec = result.schema.controls[0]
    assert spec.name == "freq"
    assert spec.init == 440.0
    assert spec.lo == 20.0
    assert spec.hi == 20000.0


def test_control_step_default() -> None:
    def dsp() -> Signal:
        return control("gain", 0.5, 0.0, 1.0)

    result = transpile(dsp)
    assert result.schema.controls[0].step == 0.001


def test_multiple_controls_all_in_schema() -> None:
    def dsp() -> Signal:
        freq = control("freq", 440.0, 20.0, 20000.0)
        gate = control("gate", 0.0, 0.0, 1.0)
        return freq * gate

    result = transpile(dsp)
    assert len(result.schema.controls) == 2
    names = {s.name for s in result.schema.controls}
    assert names == {"freq", "gate"}


def test_transpile_no_inputs() -> None:
    def dsp() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    result = transpile(dsp)
    assert result.num_inputs == 0


def test_transpile_with_inputs() -> None:
    def dsp(audio: Signal) -> Signal:
        gain = control("gain", 0.5, 0.0, 1.0)
        return audio * gain

    result = transpile(dsp)
    assert result.num_inputs == 1


def test_transpile_returns_source_string() -> None:
    def dsp() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    result = transpile(dsp)
    assert isinstance(result.source, str)
    assert len(result.source) > 0
    assert "process" in result.source
