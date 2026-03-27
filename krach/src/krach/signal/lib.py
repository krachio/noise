"""krach DSP standard library: oscillators, filters, noise, effects, utilities."""

from __future__ import annotations

import math

from krach.signal.trace import coerce_to_signal
from krach.signal.types import Signal, SignalLike
from krach.signal.core import (
    exp,
    faust_expr,
    feedback,
    fmod,
    log10,
    max_,
    mem,
    min_,
    pow_,
    rdtable,
    select2,
    sin,
    sr,
)

TAU = 2.0 * math.pi

# ── Oscillators ──────────────────────────────────────────────────────────


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
    return rdtable(tuple(float(v) for v in data), index)


# ── Filters ──────────────────────────────────────────────────────────────


def onepole(sig: SignalLike, cutoff: SignalLike) -> Signal:
    """Simple lowpass filter with exponential smoothing (one-pole IIR)."""
    s = coerce_to_signal(sig)
    c = coerce_to_signal(cutoff)
    alpha = exp(c * (-TAU) / sr())
    return feedback(lambda fb: s * (1.0 - alpha) + fb * alpha)


def dcblock(sig: SignalLike, coeff: float = 0.995) -> Signal:
    """Remove DC offset from a signal using a first-order highpass."""
    s = coerce_to_signal(sig)
    return feedback(lambda fb: s - mem(s) + fb * coeff)


def lowpass(sig: SignalLike, freq: SignalLike, order: int = 2) -> Signal:
    """Butterworth lowpass filter via Faust fi.lowpass."""
    return faust_expr(
        f"{{1}} : fi.lowpass({order}, {{0}})",
        coerce_to_signal(freq),
        coerce_to_signal(sig),
    )


def highpass(sig: SignalLike, freq: SignalLike, order: int = 2) -> Signal:
    """Butterworth highpass filter via Faust fi.highpass."""
    return faust_expr(
        f"{{1}} : fi.highpass({order}, {{0}})",
        coerce_to_signal(freq),
        coerce_to_signal(sig),
    )


def bandpass(sig: SignalLike, freq: SignalLike, q: SignalLike) -> Signal:
    """Bandpass filter via Faust fi.resonbp."""
    return faust_expr(
        "{2} : fi.resonbp({0}, {1}, 1)",
        coerce_to_signal(freq),
        coerce_to_signal(q),
        coerce_to_signal(sig),
    )


def resonant(sig: SignalLike, freq: SignalLike, q: SignalLike) -> Signal:
    """Resonant lowpass filter via Faust fi.resonlp."""
    return faust_expr(
        "{2} : fi.resonlp({0}, {1}, 1)",
        coerce_to_signal(freq),
        coerce_to_signal(q),
        coerce_to_signal(sig),
    )


# ── Noise ────────────────────────────────────────────────────────────────


def white_noise() -> Signal:
    """White noise generator (uniform spectral density)."""
    return faust_expr("no.noise")


def pink_noise() -> Signal:
    """Pink noise generator (1/f spectral density)."""
    return faust_expr("no.pink_noise")


# ── Effects ──────────────────────────────────────────────────────────────


def passthrough(inp: Signal) -> Signal:
    """Identity effect: 1 input, 1 output, passes signal through unchanged."""
    return inp


# ── Utilities ────────────────────────────────────────────────────────────


def db_to_linear(db: SignalLike) -> Signal:
    """Convert decibels to linear amplitude: 10^(db/20)."""
    return pow_(10.0, coerce_to_signal(db) / 20.0)


def linear_to_db(amp: SignalLike) -> Signal:
    """Convert linear amplitude to decibels: 20 * log10(amp)."""
    return log10(max_(amp, 1e-30)) * 20.0


def clip(sig: SignalLike, lo: SignalLike, hi: SignalLike) -> Signal:
    """Clip signal to [lo, hi]."""
    return min_(max_(sig, lo), hi)


def lerp(a: SignalLike, b: SignalLike, t: SignalLike) -> Signal:
    """Linear interpolation: a * (1 - t) + b * t."""
    a_sig = coerce_to_signal(a)
    b_sig = coerce_to_signal(b)
    t_sig = coerce_to_signal(t)
    return a_sig * (1.0 - t_sig) + b_sig * t_sig


def wrap(sig: SignalLike, lo: SignalLike, hi: SignalLike) -> Signal:
    """Wrap signal into [lo, hi) using modular arithmetic."""
    s = coerce_to_signal(sig)
    lo_sig = coerce_to_signal(lo)
    hi_sig = coerce_to_signal(hi)
    range_ = max_(hi_sig - lo_sig, 1e-30)
    return faust_expr(
        "({0} - {1}) - floor(({0} - {1}) / {2}) * {2} + {1}",
        s,
        lo_sig,
        range_,
    )


def smooth(sig: SignalLike, time_ms: float = 10.0) -> Signal:
    """One-pole smoothing filter for control signal dezipper."""
    if time_ms <= 0.0:
        return coerce_to_signal(sig)
    s = coerce_to_signal(sig)
    tau = time_ms / 1000.0
    coeff = exp(coerce_to_signal(-1.0) / (tau * sr()))
    return feedback(lambda fb: s * (1.0 - coeff) + fb * coeff)
