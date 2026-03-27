"""Musical scale conversions."""

from __future__ import annotations

from krach.signal.trace import coerce_to_signal
from krach.signal.types import Signal, SignalLike
from krach.signal.core import log10, pow_


def midi_to_freq(note: SignalLike) -> Signal:
    """Convert MIDI note number to frequency: 440 * 2^((note - 69) / 12)."""
    n = coerce_to_signal(note)
    return pow_(2.0, (n - 69.0) / 12.0) * 440.0


def freq_to_midi(freq: SignalLike) -> Signal:
    """Convert frequency to MIDI note number: 69 + 12 * log2(freq / 440)."""
    from krach.signal.core import max_
    f = max_(freq, 1e-30)
    return log10(f / 440.0) / log10(coerce_to_signal(2.0)) * 12.0 + 69.0
