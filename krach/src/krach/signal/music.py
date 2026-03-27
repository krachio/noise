"""krach DSP music library: envelopes, effects, scales, spatial."""

from __future__ import annotations

import math

from krach.signal.trace import coerce_to_signal
from krach.signal.types import Signal, SignalLike
from krach.signal.core import (
    cos,
    delay,
    faust_expr,
    feedback,
    log10,
    mem,
    pow_,
    select2,
    sin,
    sr,
)
from krach.signal.lib import sine_osc

# ── Envelopes ────────────────────────────────────────────────────────────


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


# ── Effects ──────────────────────────────────────────────────────────────


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


# ── Scales ───────────────────────────────────────────────────────────────


def midi_to_freq(note: SignalLike) -> Signal:
    """Convert MIDI note number to frequency: 440 * 2^((note - 69) / 12)."""
    n = coerce_to_signal(note)
    return pow_(2.0, (n - 69.0) / 12.0) * 440.0


def freq_to_midi(freq: SignalLike) -> Signal:
    """Convert frequency to MIDI note number: 69 + 12 * log2(freq / 440)."""
    from krach.signal.core import max_
    f = max_(freq, 1e-30)
    return log10(f / 440.0) / log10(coerce_to_signal(2.0)) * 12.0 + 69.0


# ── Spatial ──────────────────────────────────────────────────────────────


def pan(sig: Signal | float | int, pos: Signal | float | int) -> tuple[Signal, Signal]:
    """Equal-power panning. L = sig * cos(pos * pi/2), R = sig * sin(pos * pi/2)."""
    s = coerce_to_signal(sig)
    p = coerce_to_signal(pos)
    angle = p * (math.pi / 2.0)
    left = s * cos(angle)
    right = s * sin(angle)
    return left, right


def stereo_width(
    left: Signal | float | int,
    right: Signal | float | int,
    width: Signal | float | int,
) -> tuple[Signal, Signal]:
    """Mid/side stereo width control."""
    left_sig = coerce_to_signal(left)
    r = coerce_to_signal(right)
    w = coerce_to_signal(width)

    mid = (left_sig + r) * 0.5
    side = (left_sig - r) * 0.5

    out_l = mid + side * w
    out_r = mid - side * w
    return out_l, out_r
