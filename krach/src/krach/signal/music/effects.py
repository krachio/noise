"""Audio effects: echo, reverb, chorus, flanger."""

from __future__ import annotations

from krach.ir.signal import Signal, SignalLike, coerce_to_signal
from krach.signal.core import delay, faust_expr, feedback, sr
from krach.signal.lib.oscillators import sine_osc


def echo(
    sig: SignalLike,
    delay_ms: SignalLike,
    feedback_amt: SignalLike = 0.5,
) -> Signal:
    """Echo effect: delay line with feedback."""
    s = coerce_to_signal(sig)
    d = coerce_to_signal(delay_ms)
    fb_amt = coerce_to_signal(feedback_amt)
    delay_samples = d * sr() / 1000.0
    return feedback(lambda fb: s + delay(fb, delay_samples) * fb_amt)


def reverb(
    sig: SignalLike,
    room_size: SignalLike = 0.5,
    damping: SignalLike = 0.5,
) -> Signal:
    """Mono Freeverb reverb."""
    return faust_expr(
        "{0} : re.mono_freeverb({1}, {1}, {2}, 0.5)",
        coerce_to_signal(sig),
        coerce_to_signal(room_size),
        coerce_to_signal(damping),
    )


def chorus(
    sig: SignalLike,
    rate: SignalLike = 1.0,
    depth: SignalLike = 0.002,
) -> Signal:
    """Chorus effect via modulated delay."""
    s = coerce_to_signal(sig)
    r = coerce_to_signal(rate)
    d = coerce_to_signal(depth)
    mod = (sine_osc(r) + 1.0) * 0.5 * d * sr()
    base_delay = d * sr()
    return (s + delay(s, base_delay + mod)) * 0.5


def flanger(
    sig: SignalLike,
    rate: SignalLike = 0.2,
    depth: SignalLike = 0.005,
    feedback_amt: SignalLike = 0.7,
) -> Signal:
    """Flanger effect via modulated delay with feedback."""
    s = coerce_to_signal(sig)
    r = coerce_to_signal(rate)
    d = coerce_to_signal(depth)
    fb_amt = coerce_to_signal(feedback_amt)
    mod = (sine_osc(r) + 1.0) * 0.5 * d * sr()
    return feedback(lambda fb: s + delay(fb, mod) * fb_amt)
