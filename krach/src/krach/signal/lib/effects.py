"""DSP effects: identity passthrough and utility effects."""

from __future__ import annotations

from krach.ir.signal import Signal


def passthrough(inp: Signal) -> Signal:
    """Identity effect: 1 input, 1 output, passes signal through unchanged."""
    return inp
