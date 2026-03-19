"""Spatial audio: panning and stereo width."""

from __future__ import annotations

import math

from faust_dsl._core import Signal, coerce_to_signal
from faust_dsl._dsp import cos, sin


def pan(sig: Signal | float | int, pos: Signal | float | int) -> tuple[Signal, Signal]:
    """Equal-power panning.

    L = sig * cos(pos * pi/2), R = sig * sin(pos * pi/2).

    Args:
        sig: Mono input signal.
        pos: Pan position from 0.0 (full left) to 1.0 (full right).

    Returns:
        A (left, right) tuple of signals.
    """
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
    l = coerce_to_signal(left)
    r = coerce_to_signal(right)
    w = coerce_to_signal(width)

    mid = (l + r) * 0.5
    side = (l - r) * 0.5

    out_l = mid + side * w
    out_r = mid - side * w
    return out_l, out_r
