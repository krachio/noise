"""Envelope generators: ADSR, AR, decay, trigger, latch."""

from __future__ import annotations

from krach.ir.signal import Signal, SignalLike, coerce_to_signal
from krach.signal.core import faust_expr, feedback, mem, select2


def decay(rate: SignalLike) -> Signal:
    """Exponential decay: starts at 1.0, multiplies by rate each sample."""
    r = coerce_to_signal(rate)
    impulse = coerce_to_signal(1.0) - mem(coerce_to_signal(1.0))
    return feedback(lambda fb: fb * r + impulse)


def trigger(sig: SignalLike) -> Signal:
    """Rising edge detection: 1 when sig > 0 and previous sample was <= 0."""
    s = coerce_to_signal(sig)
    prev = mem(s)
    is_positive = s > 0.0
    was_nonpositive = prev <= 0.0
    return is_positive * was_nonpositive


def latch(sig: SignalLike, trig: SignalLike) -> Signal:
    """Sample-and-hold: captures sig when trig is non-zero."""
    s = coerce_to_signal(sig)
    t = coerce_to_signal(trig)
    return feedback(lambda fb: select2(t, fb, s))


def adsr(
    attack: SignalLike,
    decay_time: SignalLike,
    sustain: SignalLike,
    release: SignalLike,
    gate: SignalLike,
) -> Signal:
    """ADSR envelope generator."""
    return faust_expr(
        "en.adsr({0}, {1}, {2}, {3}, {4})",
        coerce_to_signal(attack),
        coerce_to_signal(decay_time),
        coerce_to_signal(sustain),
        coerce_to_signal(release),
        coerce_to_signal(gate),
    )


def ar(
    attack: SignalLike,
    release: SignalLike,
    gate: SignalLike,
) -> Signal:
    """Attack-release envelope generator."""
    return faust_expr(
        "en.ar({0}, {1}, {2})",
        coerce_to_signal(attack),
        coerce_to_signal(release),
        coerce_to_signal(gate),
    )


edge_trigger = trigger
