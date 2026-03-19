"""Tests for Commit 5 — lib/."""

from __future__ import annotations

from faust_dsl.lib.filters import lowpass
from faust_dsl.lib.noise import white_noise
from faust_dsl.lib.oscillators import phasor, sine_osc
from faust_dsl.lib.utilities import smooth
from faust_dsl.transpile import transpile
from faust_dsl._primitives import feedback_p


def test_sine_osc_contains_sin() -> None:
    result = transpile(lambda: sine_osc(440.0))  # type: ignore[arg-type]
    assert "sin(" in result.source


def test_phasor_uses_feedback() -> None:
    from faust_dsl.transpile import make_graph
    graph = make_graph(lambda: phasor(440.0))  # type: ignore[arg-type]
    fb_eqns = [e for e in graph.equations if e.primitive is feedback_p]
    assert len(fb_eqns) >= 1


def test_lowpass_uses_fi_lowpass() -> None:
    from faust_dsl._core import Signal

    def dsp(a: Signal) -> Signal:
        return lowpass(a, 1000.0)

    result = transpile(dsp)
    assert "fi.lowpass" in result.source


def test_white_noise_present() -> None:
    result = transpile(lambda: white_noise())  # type: ignore[arg-type]
    assert "no.noise" in result.source


def test_smooth_uses_one_pole() -> None:
    from faust_dsl._core import Signal

    def dsp(a: Signal) -> Signal:
        return smooth(a, 10.0)

    result = transpile(dsp)
    # smooth uses feedback internally, which lowers to ~
    assert "~" in result.source
