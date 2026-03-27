"""Tests for Commit 5 — lib/."""

from __future__ import annotations

from krach.signal.lib.filters import lowpass
from krach.signal.lib.noise import white_noise
from krach.signal.lib.oscillators import phasor, sine_osc
from krach.signal.lib.utilities import smooth
from krach.signal.transpile import transpile
from krach.signal.primitives import feedback_p


def test_sine_osc_contains_sin() -> None:
    result = transpile(lambda: sine_osc(440.0))  # type: ignore[arg-type]
    assert "sin(" in result.source


def test_phasor_uses_feedback() -> None:
    from krach.signal.transpile import make_graph
    graph = make_graph(lambda: phasor(440.0))  # type: ignore[arg-type]
    fb_eqns = [e for e in graph.equations if e.primitive is feedback_p]
    assert len(fb_eqns) >= 1


def test_lowpass_uses_fi_lowpass() -> None:
    from krach.signal.types import Signal

    def dsp(a: Signal) -> Signal:
        return lowpass(a, 1000.0)

    result = transpile(dsp)
    assert "fi.lowpass" in result.source


def test_white_noise_present() -> None:
    result = transpile(lambda: white_noise())  # type: ignore[arg-type]
    assert "no.noise" in result.source


def test_smooth_uses_one_pole() -> None:
    from krach.signal.types import Signal

    def dsp(a: Signal) -> Signal:
        return smooth(a, 10.0)

    result = transpile(dsp)
    # smooth uses feedback internally, which lowers to ~
    assert "~" in result.source
