"""Pure pattern builders — voice-free, stateless, no I/O.

All functions return Pattern objects with bare param names (e.g. "gate", "freq").
Binding to a specific voice happens at play time via bind_voice/bind_ctrl.
"""

from __future__ import annotations

import math
from typing import Callable

from krach._pitch import mtof as _mtof
from krach._pitch import parse_note as _parse_note
from krach.patterns.pattern import Pattern
from krach.patterns.pattern import ctrl as _ctrl
from krach.patterns.pattern import freeze as _freeze
from krach.patterns.pattern import rest as _rest


# ── Finite check ──────────────────────────────────────────────────────────────


def check_finite(value: float, label: str) -> None:
    """Raise ValueError if value is NaN or Inf."""
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{label} must be finite, got {value}")


# ── Control modulation shapes ─────────────────────────────────────────────────


def _build_mod(shape: Callable[[float], float], lo: float, hi: float, steps: int) -> Pattern:
    """Build a control pattern from a shape function [0,1) → [0,1]."""
    atoms: list[Pattern] = []
    for i in range(steps):
        t = i / steps
        val = lo + (hi - lo) * shape(t)
        atoms.append(_ctrl("ctrl", val))
    result = atoms[0]
    for a in atoms[1:]:
        result = result + a
    return result


def ramp(start: float, end: float, steps: int = 64) -> Pattern:
    """Linear ramp from start to end. Returns a 1-cycle pattern."""
    return _build_mod(lambda t: t, start, end, steps)


def mod_sine(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Sine LFO from lo to hi. Returns a 1-cycle pattern."""
    return _build_mod(lambda t: 0.5 + 0.5 * math.sin(2 * math.pi * t), lo, hi, steps)


def mod_tri(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Triangle shape: lo→hi→lo over one period."""
    return _build_mod(lambda t: 1.0 - abs(2.0 * t - 1.0), lo, hi, steps)


def mod_ramp(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Ramp up: lo→hi."""
    return ramp(lo, hi, steps)


def mod_ramp_down(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Ramp down: hi→lo."""
    return _build_mod(lambda t: 1.0 - t, lo, hi, steps)


def mod_square(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Square wave: hi for first half, lo for second half."""
    return _build_mod(lambda t: 1.0 if t < 0.5 else 0.0, lo, hi, steps)


def mod_exp(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Exponential curve: lo→hi following t^2."""
    return _build_mod(lambda t: t * t, lo, hi, steps)


# ── Continuous pattern values ─────────────────────────────────────────────────


def sine(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Sine sweep from lo to hi over one cycle. Use ``.over(N)`` for longer."""
    return mod_sine(lo, hi, steps)


def saw(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Sawtooth ramp from lo to hi over one cycle."""
    return ramp(lo, hi, steps)


def rand(lo: float, hi: float, steps: int = 64) -> Pattern:
    """Random values between lo and hi. Different each cycle."""
    import random as _rng
    atoms = [_ctrl("ctrl", lo + _rng.random() * (hi - lo)) for _ in range(steps)]
    result = atoms[0]
    for a in atoms[1:]:
        result = result + a
    return result


# ── Multi-pattern combinators ─────────────────────────────────────────────────


def cat(*patterns: Pattern) -> Pattern:
    """Concatenate patterns: play each for one cycle, then loop."""
    if not patterns:
        raise ValueError("cat() requires at least one pattern")
    result = patterns[0]
    for p in patterns[1:]:
        result = result + p
    return result.over(len(patterns))


def stack(*patterns: Pattern) -> Pattern:
    """Layer patterns simultaneously."""
    if not patterns:
        raise ValueError("stack() requires at least one pattern")
    result = patterns[0]
    for p in patterns[1:]:
        result = result | p
    return result


def struct(rhythm: Pattern, melody: Pattern) -> Pattern:
    """Impose rhythm's onset structure onto melody's values."""
    from krach.ir.pattern import PatternNode

    melody_atoms: list[PatternNode] = []

    def _extract_atoms(node: PatternNode) -> None:
        if node.primitive.name == "freeze":
            melody_atoms.append(node)
        else:
            for c in node.children:
                _extract_atoms(c)

    _extract_atoms(melody.node)
    if not melody_atoms:
        return rhythm

    idx = 0

    def _replace(node: PatternNode) -> PatternNode:
        nonlocal idx
        if node.primitive.name == "freeze":
            result = melody_atoms[idx % len(melody_atoms)]
            idx += 1
            return result
        if node.primitive.name == "silence":
            return node
        new_children = tuple(_replace(c) for c in node.children)
        return PatternNode(node.primitive, new_children, node.params)

    return Pattern(_replace(rhythm.node))


# ── Voice-bound builders (used by Mixer internally) ──────────────────────


def build_note(
    node_name: str,
    controls: tuple[str, ...],
    pitch: float | None = None,
    vel: float = 1.0,
    **params: float,
) -> Pattern:
    """Build a frozen trigger compound for a specific voice."""
    if pitch is not None and "freq" not in controls:
        raise ValueError(f"voice '{node_name}' has no 'freq' control — pitch argument ignored")
    if pitch is not None:
        check_finite(pitch, f"pitch for '{node_name}'")
    if vel != 1.0:
        check_finite(vel, f"vel for '{node_name}'")

    onset_atoms: list[Pattern] = []
    if pitch is not None and "freq" in controls:
        onset_atoms.append(_ctrl(f"{node_name}/freq", pitch))
    if vel != 1.0 and "vel" in controls:
        onset_atoms.append(_ctrl(f"{node_name}/vel", vel))
    for param, value in params.items():
        if param in controls:
            onset_atoms.append(_ctrl(f"{node_name}/{param}", value))
    if "gate" in controls:
        onset_atoms.append(_ctrl(f"{node_name}/gate", 1.0))
    if not onset_atoms:
        raise ValueError(f"voice '{node_name}' has no triggerable controls")

    onset = onset_atoms[0]
    for a in onset_atoms[1:]:
        onset = onset | a

    if "gate" in controls:
        reset = _ctrl(f"{node_name}/gate", 0.0)
        return _freeze(onset + reset)
    return _freeze(onset)


def build_hit(node_name: str, param: str) -> Pattern:
    """Build a frozen trigger compound: trig + reset with guaranteed gap."""
    label = f"{node_name}/{param}"
    trig = _ctrl(label, 1.0)
    reset = _ctrl(label, 0.0)
    return _freeze(trig + reset)


# ── Free pattern builders (voice-free, bare param names) ──────────────────────


def _resolve_pitch(p: str | int | float) -> float:
    """Convert a pitch value to Hz."""
    if isinstance(p, str):
        return _parse_note(p)
    if isinstance(p, int):
        return _mtof(p)
    return p


def note(*pitches: str | int | float, vel: float = 1.0, **params: float) -> Pattern:
    """Build a note trigger pattern with bare param names."""
    if not pitches:
        onset: Pattern = _ctrl("gate", 1.0)
        reset = _ctrl("gate", 0.0)
        return _freeze(onset + reset)

    atoms: list[Pattern] = []
    for p in pitches:
        hz = _resolve_pitch(p)
        onset_parts: list[Pattern] = [_ctrl("freq", hz)]
        if vel != 1.0:
            onset_parts.append(_ctrl("vel", vel))
        for param, value in params.items():
            onset_parts.append(_ctrl(param, value))
        onset_parts.append(_ctrl("gate", 1.0))

        onset_stack = onset_parts[0]
        for a in onset_parts[1:]:
            onset_stack = onset_stack | a

        reset = _ctrl("gate", 0.0)
        atoms.append(_freeze(onset_stack + reset))

    if len(atoms) == 1:
        return atoms[0]
    result = atoms[0]
    for a in atoms[1:]:
        result = result | a
    return _freeze(result)


def hit(param: str = "gate", **kwargs: float) -> Pattern:
    """Build a trigger pattern with bare param name."""
    onset_parts: list[Pattern] = [_ctrl(param, 1.0)]
    for k, v in kwargs.items():
        onset_parts.append(_ctrl(k, v))
    onset = onset_parts[0]
    for a in onset_parts[1:]:
        onset = onset | a
    reset = _ctrl(param, 0.0)
    return _freeze(onset + reset)


def seq(*notes: str | int | float | None, vel: float = 1.0, **params: float) -> Pattern:
    """Build a sequence of notes/rests with bare param names."""
    if not notes:
        raise ValueError("seq requires at least one note")
    atoms: list[Pattern] = []
    for n in notes:
        if isinstance(n, Pattern):
            atoms.append(n)
        elif n is None:
            atoms.append(_rest())
        else:
            atoms.append(note(n, vel=vel, **params))
    result = atoms[0]
    for a in atoms[1:]:
        result = result + a
    return result
