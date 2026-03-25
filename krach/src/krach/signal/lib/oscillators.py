"""Core oscillators using sr() — never hardcoded sample rates."""

from __future__ import annotations

import math

from krach.signal.trace import coerce_to_signal
from krach.ir.signal import Signal, SignalLike
from krach.signal.core import faust_expr, feedback, fmod, select2, sin, sr

TAU = 2.0 * math.pi


def phasor(freq: SignalLike) -> Signal:
    """Ramp oscillator cycling 0 to 1 at freq Hz."""
    f = coerce_to_signal(freq)
    return feedback(lambda ph: fmod(fmod(ph + f / sr(), 1.0) + 1.0, 1.0))


def sine_osc(freq: SignalLike) -> Signal:
    """Sine oscillator: sin(phasor * 2pi)."""
    return sin(phasor(freq) * TAU)


def saw(freq: SignalLike) -> Signal:
    """Sawtooth oscillator: bipolar -1 to 1."""
    return phasor(freq) * 2.0 - 1.0


def square(freq: SignalLike, duty: SignalLike = 0.5) -> Signal:
    """Square/pulse wave: +1 when phasor < duty, else -1."""
    ph = phasor(freq)
    d = coerce_to_signal(duty)
    return select2(ph < d, coerce_to_signal(-1.0), coerce_to_signal(1.0))


def triangle(freq: SignalLike) -> Signal:
    """Triangle oscillator: piecewise linear from phasor."""
    ph = phasor(freq)
    rising = ph * 4.0 - 1.0
    falling = coerce_to_signal(3.0) - ph * 4.0
    return select2(ph < 0.5, falling, rising)


def pulse(freq: SignalLike, width: SignalLike) -> Signal:
    """Pulse wave (alias for square with explicit width)."""
    return square(freq, duty=width)


def lfo(freq: SignalLike, lo: SignalLike = 0.0, hi: SignalLike = 1.0) -> Signal:
    """Low-frequency oscillator: sine scaled to [lo, hi]."""
    lo_sig = coerce_to_signal(lo)
    hi_sig = coerce_to_signal(hi)
    normalized = (sine_osc(freq) + 1.0) * 0.5
    return lo_sig + normalized * (hi_sig - lo_sig)


def wavetable(data: list[float], index: SignalLike) -> Signal:
    """Read from a compile-time wavetable by index."""
    if len(data) == 0:
        raise ValueError("wavetable data must not be empty")
    values_str = ", ".join(str(float(v)) for v in data)
    template = f"rdtable(waveform{{{values_str}}}, int({{0}}))"
    return faust_expr(template, coerce_to_signal(index))
