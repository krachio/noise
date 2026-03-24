"""Pure math utilities."""

from __future__ import annotations

from krach.ir.signal import Signal, SignalLike, coerce_to_signal
from krach.dsl.core import exp, faust_expr, feedback, log10, max_, min_, pow_, sr


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
