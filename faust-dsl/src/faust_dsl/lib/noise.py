"""Noise generators."""

from __future__ import annotations

from faust_dsl._core import Signal
from faust_dsl._dsp import faust_expr


def white_noise() -> Signal:
    """White noise generator (uniform spectral density)."""
    return faust_expr("no.noise")


def pink_noise() -> Signal:
    """Pink noise generator (1/f spectral density)."""
    return faust_expr("no.pink_noise")
