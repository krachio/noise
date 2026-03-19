"""Tests for Commit 6 — music/."""

from __future__ import annotations

from faust_dsl._core import Signal
from faust_dsl.music.effects import reverb
from faust_dsl.music.envelopes import adsr
from faust_dsl.music.scales import midi_to_freq
from faust_dsl.music.spatial import pan
from faust_dsl.transpile import transpile


def test_adsr_in_source() -> None:
    def dsp() -> Signal:
        gate = 1.0  # type: ignore[assignment]
        return adsr(0.01, 0.1, 0.7, 0.2, gate)  # type: ignore[arg-type]

    result = transpile(dsp)
    assert "en.adsr" in result.source


def test_midi_to_freq_formula() -> None:
    # midi_to_freq(69) should produce a graph that transpiles without error
    result = transpile(lambda: midi_to_freq(69.0))  # type: ignore[arg-type]
    assert "process" in result.source


def test_reverb_uses_re() -> None:
    def dsp(a: Signal) -> Signal:
        return reverb(a)

    result = transpile(dsp)
    assert "re." in result.source


def test_pan_returns_two_outputs() -> None:
    def dsp(a: Signal) -> tuple[Signal, Signal]:
        return pan(a, 0.5)

    result = transpile(dsp)
    assert result.num_outputs == 2
