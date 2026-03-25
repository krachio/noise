"""Filters: simple ones from primitives, biquad variants via faust_expr."""

from __future__ import annotations

import math

from krach.signal.trace import coerce_to_signal
from krach.ir.signal import Signal, SignalLike
from krach.signal.core import exp, faust_expr, feedback, mem, sr

TAU = 2.0 * math.pi


def onepole(sig: SignalLike, cutoff: SignalLike) -> Signal:
    """Simple lowpass filter with exponential smoothing (one-pole IIR)."""
    s = coerce_to_signal(sig)
    c = coerce_to_signal(cutoff)
    alpha = exp(c * (-TAU) / sr())
    return feedback(lambda fb: s * (1.0 - alpha) + fb * alpha)


def highpass1(sig: SignalLike, cutoff: SignalLike) -> Signal:
    """First-order highpass: sig - onepole(sig, cutoff)."""
    s = coerce_to_signal(sig)
    return s - onepole(s, cutoff)


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
