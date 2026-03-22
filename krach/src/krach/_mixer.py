"""VoiceMixer — named voices with stable control labels.

Manages FAUST DSP voices, per-voice gain, and the underlying soundman graph.
Control labels follow a deterministic convention: ``{voice_name}/{param}``.
Adding or removing a voice rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

import inspect
import math
import textwrap
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable  # Any still used for DspDef.fn

from faust_dsl import transpile as _transpile
from midiman_frontend import Graph, GraphIr, Session
from midiman_frontend.ir import IrNode, OscFloat, OscStr
from midiman_frontend.pattern import Pattern
from midiman_frontend.pattern import freeze as _freeze
from midiman_frontend.pattern import osc as _osc
from midiman_frontend.pattern import rest as _rest

from krach._pitch import mtof as _mtof
from krach._pitch import parse_note as _parse_note


@dataclass(frozen=True)
class Voice:
    """A named audio voice in the mix."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    init: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class PolyVoice:
    """A polyphonic voice — N instances of the same FAUST type."""

    type_id: str
    count: int
    gain: float
    controls: tuple[str, ...]


@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    controls: tuple[str, ...]
    num_inputs: int = 0


@dataclass(frozen=True)
class Bus:
    """An effect bus — a FAUST DSP that takes audio input."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int


def dsp(fn: Callable[..., Any]) -> DspDef:
    """Decorator: captures Python source + pre-transpiles to FAUST.

    Usage::

        @dsp
        def acid_bass() -> Signal:
            freq = control("freq", 55.0, 20.0, 800.0)
            gate = control("gate", 0.0, 0.0, 1.0)
            return lowpass(saw(freq), 800.0) * adsr(...) * 0.55

        mix.voice("bass", acid_bass, gain=0.3)
    """
    source = textwrap.dedent(inspect.getsource(fn))
    result = _transpile(fn)  # type: ignore[arg-type]
    return DspDef(
        fn=fn,
        source=source,
        faust=result.source,
        controls=tuple(c.name for c in result.schema.controls),
        num_inputs=result.num_inputs,
    )


def _check_finite(value: float, label: str) -> None:
    """Raise ValueError if value is NaN or Inf."""
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{label} must be finite, got {value}")


# ── Control pattern builders ──────────────────────────────────────────────────


def _build_mod(shape: Callable[[float], float], lo: float, hi: float, steps: int) -> Pattern:
    """Build a control pattern from a shape function [0,1) → [0,1]."""
    atoms: list[Pattern] = []
    for i in range(steps):
        t = i / steps
        val = lo + (hi - lo) * shape(t)
        atoms.append(_osc("/soundman/set", OscStr("ctrl"), OscFloat(val)))
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


# ── Pure builders (testable without I/O) ──────────────────────────────────────


def build_graph_ir(
    voices: dict[str, Voice],
    buses: dict[str, Bus] | None = None,
    sends: dict[tuple[str, str], float] | None = None,
    wires: dict[tuple[str, str], str] | None = None,
    poly: dict[str, int] | None = None,
) -> GraphIr:
    """Build a complete soundman graph IR from voices, buses, sends, and wires.

    Each voice gets: DSP node → gain node → DAC.
    Each bus gets: DSP node → gain node → DAC.
    Sends: voice → send_gain → bus (fan-in at bus input).
    Wires: voice → bus:port (direct, no gain node).
    Poly sum: if a poly parent has sends/wires, an implicit sum node collects instances.
    """
    _buses = buses or {}
    _sends = sends or {}
    _wires = wires or {}
    _poly = poly or {}

    builder = Graph()
    builder.node("out", "dac")

    # Voices: DSP → gain → DAC
    for name, voice in voices.items():
        builder.node(name, voice.type_id, **dict(voice.init))
        builder.node(f"{name}_g", "gain", gain=voice.gain)
        builder.connect(name, "out", f"{name}_g", "in")
        builder.connect(f"{name}_g", "out", "out", "in")
        for param in voice.controls:
            builder.expose(f"{name}/{param}", name, param)
        builder.expose(f"{name}/gain", f"{name}_g", "gain")

    # Poly sum nodes: implicit summing point for poly parents with sends/wires
    poly_with_routing: set[str] = set()
    for voice, _bus in [*_sends.keys(), *_wires.keys()]:
        if voice in _poly:
            poly_with_routing.add(voice)

    for parent in poly_with_routing:
        count = _poly[parent]
        builder.node(f"{parent}_sum", "gain", gain=1.0)
        for i in range(count):
            builder.connect(f"{parent}_v{i}", "out", f"{parent}_sum", "in")

    # Buses: DSP → gain → DAC
    for name, bus in _buses.items():
        builder.node(name, bus.type_id)
        builder.node(f"{name}_g", "gain", gain=bus.gain)
        builder.connect(name, "out", f"{name}_g", "in")
        builder.connect(f"{name}_g", "out", "out", "in")
        for param in bus.controls:
            builder.expose(f"{name}/{param}", name, param)
        builder.expose(f"{name}/gain", f"{name}_g", "gain")

    # Sends: source → send_gain → bus:in
    for (voice, bus_name), level in _sends.items():
        source = f"{voice}_sum" if voice in poly_with_routing else voice
        send_id = f"{voice}_send_{bus_name}"
        builder.node(send_id, "gain", gain=level)
        builder.connect(source, "out", send_id, "in")
        builder.connect(send_id, "out", bus_name, "in")
        builder.expose(f"{send_id}/gain", send_id, "gain")

    # Wires: source → bus:port (direct, no gain node)
    for (voice, bus_name), port in _wires.items():
        source = f"{voice}_sum" if voice in poly_with_routing else voice
        builder.connect(source, "out", bus_name, port)

    return builder.build()


def build_note(
    voice_name: str,
    controls: tuple[str, ...],
    pitch: float | None = None,
    vel: float = 1.0,
    **params: float,
) -> Pattern:
    """Build a frozen trigger compound: onset values stacked + reset sequenced.

    Uses ``Freeze(Cat([onset_stack, reset]))`` so this counts as ONE atom
    for cycle division (Freeze prevents Cat flattening). The trigger fires
    at the first half, reset at the second half, leaving a gap before the
    next atom's onset for FAUST to detect the rising edge.
    """
    if pitch is not None and "freq" not in controls:
        raise ValueError(f"voice '{voice_name}' has no 'freq' control — pitch argument ignored")
    if pitch is not None:
        _check_finite(pitch, f"pitch for '{voice_name}'")
    if vel != 1.0:
        _check_finite(vel, f"vel for '{voice_name}'")

    onset_atoms: list[Pattern] = []

    if pitch is not None and "freq" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}/freq"), OscFloat(pitch)))

    if vel != 1.0 and "vel" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}/vel"), OscFloat(vel)))

    for param, value in params.items():
        if param in controls:
            onset_atoms.append(
                _osc("/soundman/set", OscStr(f"{voice_name}/{param}"), OscFloat(value))
            )

    if "gate" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}/gate"), OscFloat(1.0)))

    if not onset_atoms:
        raise ValueError(f"voice '{voice_name}' has no triggerable controls")

    # Stack all onset values (fire simultaneously)
    onset = onset_atoms[0]
    for a in onset_atoms[1:]:
        onset = onset | a  # Stack: fire simultaneously

    if "gate" in controls:
        reset = _osc("/soundman/set", OscStr(f"{voice_name}/gate"), OscFloat(0.0))
        return _freeze(onset + reset)
    return _freeze(onset)


def build_hit(voice_name: str, param: str) -> Pattern:
    """Build a frozen trigger compound: trig + reset with guaranteed gap.

    Uses ``Freeze(Cat([trig, reset]))`` so this counts as ONE atom.
    ``rest() + build_hit(...)`` is 2 top-level atoms (not 3). The trig fires
    at the first half of the slot, reset at the second half, leaving a gap
    before the next atom's onset for FAUST to detect the rising edge.
    """
    label = f"{voice_name}/{param}"
    trig = _osc("/soundman/set", OscStr(label), OscFloat(1.0))
    reset = _osc("/soundman/set", OscStr(label), OscFloat(0.0))
    return _freeze(trig + reset)


# ── Free pattern builders (voice-free, bare param names) ──────────────────────


def _resolve_pitch(p: str | int | float) -> float:
    """Convert a pitch value to Hz: str → parse_note, int → mtof, float → passthrough."""
    if isinstance(p, str):
        return _parse_note(p)
    if isinstance(p, int):
        return _mtof(p)
    return p


def note(*pitches: str | int | float, vel: float = 1.0, **params: float) -> Pattern:
    """Build a note trigger pattern with bare param names.

    Bind to a voice at play time via ``_bind_voice()``.

    - str pitch: parsed via ``parse_note()`` (e.g. ``"C4"``)
    - int pitch: converted via ``mtof()`` (MIDI note number)
    - float pitch: used directly as Hz

    Multiple pitches produce a frozen stack (chord).
    """
    if not pitches:
        # Gate-only trigger
        onset: Pattern = _osc("/soundman/set", OscStr("gate"), OscFloat(1.0))
        reset = _osc("/soundman/set", OscStr("gate"), OscFloat(0.0))
        return _freeze(onset + reset)

    atoms: list[Pattern] = []
    for p in pitches:
        hz = _resolve_pitch(p)
        onset_parts: list[Pattern] = []
        onset_parts.append(_osc("/soundman/set", OscStr("freq"), OscFloat(hz)))
        if vel != 1.0:
            onset_parts.append(_osc("/soundman/set", OscStr("vel"), OscFloat(vel)))
        for param, value in params.items():
            onset_parts.append(_osc("/soundman/set", OscStr(param), OscFloat(value)))
        onset_parts.append(_osc("/soundman/set", OscStr("gate"), OscFloat(1.0)))

        onset_stack = onset_parts[0]
        for a in onset_parts[1:]:
            onset_stack = onset_stack | a

        reset = _osc("/soundman/set", OscStr("gate"), OscFloat(0.0))
        atoms.append(_freeze(onset_stack + reset))

    if len(atoms) == 1:
        return atoms[0]

    # Chord: stack all notes, freeze the whole thing
    result = atoms[0]
    for a in atoms[1:]:
        result = result | a
    return _freeze(result)


def hit(param: str = "gate", **kwargs: float) -> Pattern:
    """Build a trigger pattern with bare param name.

    Bind to a voice at play time via ``_bind_voice()``.
    Default param is ``"gate"``.
    """
    onset_parts: list[Pattern] = [_osc("/soundman/set", OscStr(param), OscFloat(1.0))]
    for k, v in kwargs.items():
        onset_parts.append(_osc("/soundman/set", OscStr(k), OscFloat(v)))

    onset = onset_parts[0]
    for a in onset_parts[1:]:
        onset = onset | a

    reset = _osc("/soundman/set", OscStr(param), OscFloat(0.0))
    return _freeze(onset + reset)


def seq(*notes: str | int | float | None, vel: float = 1.0, **params: float) -> Pattern:
    """Build a sequence of notes/rests with bare param names.

    Bind to a voice at play time via ``_bind_voice()``.
    """
    if not notes:
        raise ValueError("seq requires at least one note")
    atoms: list[Pattern] = []
    for n in notes:
        if n is None:
            atoms.append(_rest())
        else:
            atoms.append(note(n, vel=vel, **params))
    result = atoms[0]
    for a in atoms[1:]:
        result = result + a
    return result


# ── Tree rewriters ────────────────────────────────────────────────────────────


def _bind_voice(node: IrNode, voice: str) -> IrNode:
    """Prepend ``voice/`` to bare param names in all Osc atoms.

    A param is "bare" if it does not contain ``/``.  Already-bound params
    (containing ``/``) are left unchanged.  Walks the full IR tree.
    """
    from midiman_frontend.ir import (
        Atom,
        Cat,
        Degrade,
        Early,
        Euclid,
        Every,
        Fast,
        Freeze,
        Late,
        Osc,
        Rev,
        Silence,
        Slow,
        Stack,
    )

    match node:
        case Atom(Osc(addr, args)):
            new_args = tuple(
                OscStr(f"{voice}/{a.value}") if isinstance(a, OscStr) and "/" not in a.value else a
                for a in args
            )
            return Atom(Osc(addr, new_args))
        case Atom():
            return node
        case Silence():
            return node
        case Freeze(child):
            return Freeze(_bind_voice(child, voice))
        case Cat(children):
            return Cat(tuple(_bind_voice(c, voice) for c in children))
        case Stack(children):
            return Stack(tuple(_bind_voice(c, voice) for c in children))
        case Fast(factor, child):
            return Fast(factor, _bind_voice(child, voice))
        case Slow(factor, child):
            return Slow(factor, _bind_voice(child, voice))
        case Early(offset, child):
            return Early(offset, _bind_voice(child, voice))
        case Late(offset, child):
            return Late(offset, _bind_voice(child, voice))
        case Rev(child):
            return Rev(_bind_voice(child, voice))
        case Every(n, transform, child):
            return Every(n, _bind_voice(transform, voice), _bind_voice(child, voice))
        case Euclid(pulses, steps, rotation, child):
            return Euclid(pulses, steps, rotation, _bind_voice(child, voice))
        case Degrade(prob, seed, child):
            return Degrade(prob, seed, _bind_voice(child, voice))


def _bind_voice_poly(
    node: IrNode, parent: str, count: int, alloc: int,
) -> tuple[IrNode, int]:
    """Bind a pattern to a poly voice, round-robin allocating instances.

    Each Freeze compound (note/hit event) binds to the next instance.
    Returns (rewritten_node, updated_alloc_counter).
    """
    from midiman_frontend.ir import (
        Cat,
        Degrade,
        Early,
        Euclid,
        Every,
        Fast,
        Freeze,
        Late,
        Rev,
        Silence,
        Slow,
        Stack,
    )

    match node:
        case Freeze(Stack(children)):
            # Freeze(Stack) = chord — each child gets a different instance
            new_children: list[IrNode] = []
            for c in children:
                bound_c, alloc = _bind_voice_poly(c, parent, count, alloc)
                new_children.append(bound_c)
            return Freeze(Stack(tuple(new_children))), alloc
        case Freeze(child):
            # A Freeze is one "event" (note/hit compound) — allocate one instance
            inst = f"{parent}_v{alloc % count}"
            alloc += 1
            return Freeze(_bind_voice(child, inst)), alloc
        case Cat(children):
            # Sequence: each child gets the next instance
            new_children: list[IrNode] = []
            for c in children:
                bound_c, alloc = _bind_voice_poly(c, parent, count, alloc)
                new_children.append(bound_c)
            return Cat(tuple(new_children)), alloc
        case Stack(children):
            # Simultaneous: each child gets a different instance (chord)
            new_children_s: list[IrNode] = []
            for c in children:
                bound_c, alloc = _bind_voice_poly(c, parent, count, alloc)
                new_children_s.append(bound_c)
            return Stack(tuple(new_children_s)), alloc
        case Silence():
            return node, alloc
        case Fast(factor, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Fast(factor, bound), alloc
        case Slow(factor, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Slow(factor, bound), alloc
        case Early(offset, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Early(offset, bound), alloc
        case Late(offset, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Late(offset, bound), alloc
        case Rev(child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Rev(bound), alloc
        case Every(n, transform, child):
            bt, alloc = _bind_voice_poly(transform, parent, count, alloc)
            bc, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Every(n, bt, bc), alloc
        case Euclid(pulses, steps, rotation, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Euclid(pulses, steps, rotation, bound), alloc
        case Degrade(prob, seed, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Degrade(prob, seed, bound), alloc
        case _:
            # Atom without Freeze — bind to current instance (non-compound event)
            inst = f"{parent}_v{alloc % count}"
            return _bind_voice(node, inst), alloc


def _bind_ctrl(node: IrNode, label: str) -> IrNode:
    """Replace the ``"ctrl"`` placeholder param in Osc atoms with ``label``.

    Similar to ``_bind_voice()`` but replaces the specific placeholder
    ``"ctrl"`` rather than prepending a prefix.
    """
    from midiman_frontend.ir import (
        Atom,
        Cat,
        Degrade,
        Early,
        Euclid,
        Every,
        Fast,
        Freeze,
        Late,
        Osc,
        Rev,
        Silence,
        Slow,
        Stack,
    )

    match node:
        case Atom(Osc(addr, args)):
            new_args = tuple(
                OscStr(label) if isinstance(a, OscStr) and a.value == "ctrl" else a
                for a in args
            )
            return Atom(Osc(addr, new_args))
        case Atom():
            return node
        case Silence():
            return node
        case Freeze(child):
            return Freeze(_bind_ctrl(child, label))
        case Cat(children):
            return Cat(tuple(_bind_ctrl(c, label) for c in children))
        case Stack(children):
            return Stack(tuple(_bind_ctrl(c, label) for c in children))
        case Fast(factor, child):
            return Fast(factor, _bind_ctrl(child, label))
        case Slow(factor, child):
            return Slow(factor, _bind_ctrl(child, label))
        case Early(offset, child):
            return Early(offset, _bind_ctrl(child, label))
        case Late(offset, child):
            return Late(offset, _bind_ctrl(child, label))
        case Rev(child):
            return Rev(_bind_ctrl(child, label))
        case Every(n, transform, child):
            return Every(n, _bind_ctrl(transform, label), _bind_ctrl(child, label))
        case Euclid(pulses, steps, rotation, child):
            return Euclid(pulses, steps, rotation, _bind_ctrl(child, label))
        case Degrade(prob, seed, child):
            return Degrade(prob, seed, _bind_ctrl(child, label))


# ── VoiceMixer ────────────────────────────────────────────────────────────────


class VoiceMixer:
    """Manages named audio voices with stable control labels.

    Each voice is a FAUST DSP node (string type_id or Python function) with
    an independent gain stage.  Adding/removing voices rebuilds the soundman
    graph transparently.  ``gain()`` updates are instant (no rebuild).
    """

    def __init__(
        self,
        session: Session,
        dsp_dir: Path,
        node_controls: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._session = session
        self._dsp_dir = dsp_dir
        self._node_controls: dict[str, tuple[str, ...]] = dict(node_controls or {})
        self._voices: dict[str, Voice] = {}
        self._poly: dict[str, PolyVoice] = {}
        self._poly_alloc: dict[str, int] = {}  # round-robin counter per poly name
        self._muted: dict[str, float] = {}  # name → gain before mute
        self._buses: dict[str, Bus] = {}
        self._sends: dict[tuple[str, str], float] = {}  # (voice, bus) → gain
        self._wires: dict[tuple[str, str], str] = {}    # (voice, bus) → port
        self._ctrl_values: dict[str, float] = {}  # path → last set value (for fade start)
        self._batching: bool = False
        self._graph_loaded: bool = False

    def _resolve_source(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        fallback_controls: tuple[str, ...] = (),
    ) -> tuple[str, tuple[str, ...]]:
        """Resolve a source to (type_id, controls). Writes .dsp and waits for JIT if needed."""
        if isinstance(source, DspDef):
            type_id = f"faust:{name}"
            self._dsp_dir.joinpath(f"{name}.py").write_text(source.source)
            faust_code, controls = source.faust, source.controls
        elif callable(source):
            type_id = f"faust:{name}"
            result = _transpile(source)  # type: ignore[arg-type]
            faust_code, controls = result.source, tuple(c.name for c in result.schema.controls)
        else:
            return source, self._node_controls.get(source, fallback_controls)

        self._dsp_dir.joinpath(f"{name}.dsp").write_text(faust_code)
        self._node_controls[type_id] = controls
        if not self._batching:
            self._wait_for_type(type_id)
        return type_id, controls

    def voice(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        gain: float = 0.5,
        **init: float,
    ) -> None:
        """Add or replace a voice.  Rebuilds the graph.

        ``source`` is a ``@dsp``-decorated function, a registered type_id
        string, or a raw Python DSP function (transpiled on the fly).
        """
        type_id, controls = self._resolve_source(name, source, tuple(init.keys()))
        self._muted.pop(name, None)

        # If replacing a poly voice with a mono voice, clean up poly state first.
        if name in self._poly:
            self.hush(name)
            old_pv = self._poly.pop(name)
            self._poly_alloc.pop(name, None)
            for i in range(old_pv.count):
                self._voices.pop(f"{name}_v{i}", None)
                self._muted.pop(f"{name}_v{i}", None)

        # Clean sends/wires from old voice
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]

        is_new = name not in self._voices
        if not is_new:
            self.hush(name)
        self._voices[name] = Voice(
            type_id=type_id,
            gain=gain,
            controls=controls,
            init=tuple(init.items()),
        )
        if not self._batching:
            if is_new and self._graph_loaded:
                self._session.add_voice(name, type_id, controls, gain)
            else:
                self._rebuild()

    def poly(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        voices: int = 4,
        gain: float = 0.5,
    ) -> None:
        """Create a polyphonic voice with N instances of the same FAUST type.

        Raises ValueError if voices < 1.

        Each instance is named ``{name}_v0``, ``{name}_v1``, etc.
        Use ``mix.note(name, freq)`` to trigger the next available instance
        (round-robin), or ``mix.note(name, f1, f2, f3)`` for simultaneous notes.
        """
        if voices < 1:
            raise ValueError("poly requires at least 1 voice")
        type_id, controls = self._resolve_source(name, source)
        self._muted.pop(name, None)

        # Clean up old state: either poly instances or a mono voice.
        if name in self._poly:
            self.hush(name)
            old = self._poly[name]
            for i in range(old.count):
                self._voices.pop(f"{name}_v{i}", None)
                self._muted.pop(f"{name}_v{i}", None)
        elif name in self._voices:
            self.hush(name)
            del self._voices[name]

        # Clean sends/wires from old voice
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]

        self._poly[name] = PolyVoice(type_id=type_id, count=voices, gain=gain, controls=controls)
        self._poly_alloc[name] = 0

        per_voice_gain = gain / voices
        for i in range(voices):
            inst = f"{name}_v{i}"
            self._voices[inst] = Voice(type_id=type_id, gain=per_voice_gain, controls=controls)

        if not self._batching:
            self._rebuild()

    def remove(self, name: str) -> None:
        """Remove a voice or poly voice. Rebuilds the graph."""
        if name not in self._voices and name not in self._poly:
            raise ValueError(f"voice '{name}' not found")
        self._muted.pop(name, None)
        self.hush(name)
        # Clean sends/wires where this voice is the source
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]
        if name in self._poly:
            pv = self._poly.pop(name)
            self._poly_alloc.pop(name, None)
            for i in range(pv.count):
                self._voices.pop(f"{name}_v{i}", None)
                self._muted.pop(f"{name}_v{i}", None)
        else:
            del self._voices[name]
        self._rebuild()

    def hush(self, name: str) -> None:
        """Stop the pattern, its fade, and release gates for a voice, control path, or group.

        - Control path (contains ``/``): hushes the ``_ctrl_`` slot
        - Voice name: hushes voice + fade + gates
        - Group prefix: hushes all matching voices
        """
        # Control path: hush the _ctrl_ slot
        if "/" in name:
            slot = f"_ctrl_{name.replace('/', '_')}"
            self._session.hush(slot)
            # Also try group-prefix resolution
            targets = self._resolve_targets_soft(name)
            for t in targets:
                self._hush_single(t)
            return

        # Exact match or group prefix
        targets = self._resolve_targets_soft(name)
        if targets:
            for t in targets:
                self._hush_single(t)
        else:
            # Not found — still pass through to session (e.g. custom slot names)
            self._session.hush(name)
            self._session.hush(f"_fade_{name}")

    def _hush_single(self, name: str) -> None:
        """Hush a single voice (not a group or path)."""
        self._session.hush(name)
        self._session.hush(f"_fade_{name}")
        if name in self._poly:
            pv = self._poly[name]
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                self._session.hush(inst)
                self._session.hush(f"_fade_{inst}")
                if "gate" in pv.controls:
                    self._session.set_ctrl(f"{inst}/gate", 0.0)
        else:
            voice = self._voices.get(name)
            if voice and "gate" in voice.controls:
                self._session.set_ctrl(f"{name}/gate", 0.0)

    def stop(self) -> None:
        """Hush all voices and release all gates."""
        # Collect exact poly instance names to avoid prefix-matching bugs
        # (e.g. mono "pad_vinyl" must not be skipped when poly "pad" exists).
        poly_instances: set[str] = set()
        for pname, pv in self._poly.items():
            self.hush(pname)
            for i in range(pv.count):
                poly_instances.add(f"{pname}_v{i}")
        for name in self._voices:
            if name not in poly_instances:
                self.hush(name)

    def gain(self, name: str, value: float) -> None:
        """Update a voice, bus, or group gain. Instant — no graph rebuild.

        For poly voices, distributes gain equally across instances.
        Prefix matching: ``gain("drums", 0.5)`` applies to all ``drums/*`` voices.
        """
        _check_finite(value, f"gain for '{name}'")
        targets = self._resolve_targets(name)
        for t in targets:
            self._gain_single(t, value)

    def _gain_single(self, name: str, value: float) -> None:
        """Set gain for a single voice, poly, or bus."""
        if name in self._buses:
            old_bus = self._buses[name]
            self._buses[name] = Bus(
                type_id=old_bus.type_id, gain=value,
                controls=old_bus.controls, num_inputs=old_bus.num_inputs,
            )
            self._session.set_ctrl(f"{name}/gain", float(value))
            return
        if name in self._poly:
            pv = self._poly[name]
            per_voice = value / pv.count
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                old = self._voices[inst]
                self._voices[inst] = Voice(
                    type_id=old.type_id, gain=per_voice, controls=old.controls, init=old.init
                )
                self._session.set_ctrl(f"{inst}/gain", float(per_voice))
            self._poly[name] = PolyVoice(
                type_id=pv.type_id, count=pv.count, gain=value, controls=pv.controls,
            )
        else:
            old = self._voices[name]
            self._voices[name] = Voice(
                type_id=old.type_id, gain=value, controls=old.controls, init=old.init
            )
            self._session.set_ctrl(f"{name}/gain", float(value))

    def mute(self, name: str) -> None:
        """Mute a voice or group — stores current gain, sets gain to 0. No-op if already muted."""
        targets = self._resolve_targets(name)
        for t in targets:
            self._mute_single(t)

    def _mute_single(self, name: str) -> None:
        """Mute a single voice."""
        if name in self._muted:
            return
        if name in self._poly:
            self._muted[name] = self._poly[name].gain
        elif name in self._voices:
            self._muted[name] = self._voices[name].gain
        self._gain_single(name, 0.0)

    def unmute(self, name: str) -> None:
        """Unmute a voice or group — restores gain saved by mute()."""
        targets = self._resolve_targets_soft(name)
        if not targets:
            if name not in self._muted:
                return
            # Single name not in current voices — just pop muted
            self._muted.pop(name, None)
            return
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def solo(self, name: str) -> None:
        """Solo a voice or group — mutes all others, unmutes targets."""
        targets = set(self._resolve_targets(name))
        # Collect all top-level names (mono voices + poly parents)
        all_names: set[str] = set()
        for vname in self._voices:
            all_names.add(vname)
        for pname in self._poly:
            all_names.add(pname)
            # Remove poly instances from the set — they're managed via parent
            pv = self._poly[pname]
            for i in range(pv.count):
                all_names.discard(f"{pname}_v{i}")
        for n in all_names:
            if n not in targets:
                self._mute_single(n)
        for t in targets:
            if t in self._muted:
                self._gain_single(t, self._muted.pop(t))

    def unsolo(self) -> None:
        """Unmute all muted voices — reverses solo() or manual mutes."""
        for name in list(self._muted):
            self.unmute(name)

    def play(self, target: str, pattern: Pattern) -> None:
        """Play a pattern on a voice or control path.

        - Plain name (no ``/``): voice name — rewrites bare params to ``voice/param``
        - Poly name: round-robin allocates instances (``pad_v0``, ``pad_v1``, ...)
        - Path with ``/``: control path — rewrites ``"ctrl"`` placeholder to the label
        """
        if "/" in target:
            # Control path: rewrite "ctrl" placeholder to full path label
            label = self._resolve_path(target)
            bound = Pattern(_bind_ctrl(pattern.node, label))
            slot = f"_ctrl_{target.replace('/', '_')}"
            self._session.play(slot, bound)
        elif target in self._poly:
            # Poly voice: round-robin allocate instances during rewrite
            pv = self._poly[target]
            alloc = self._poly_alloc.get(target, 0)
            bound_node, alloc = _bind_voice_poly(pattern.node, target, pv.count, alloc)
            self._poly_alloc[target] = alloc
            self._session.play(target, Pattern(bound_node))
        else:
            # Mono voice: rewrite bare params to voice/param
            bound = Pattern(_bind_voice(pattern.node, target))
            self._session.play(target, bound)

    def set(self, path: str, value: float) -> None:
        """Set a control value by path. Instant — no pattern scheduling."""
        _check_finite(value, path)
        self._ctrl_values[path] = value
        self._session.set_ctrl(path, float(value))

    def _resolve_path(self, path: str) -> str:
        """Convert a user-facing ``/``-separated path to the exposed control label.

        Most paths are identity (``bass/cutoff`` → ``bass/cutoff``).
        Send levels use a special convention:
        ``bass/verb_send`` → ``bass_send_verb/gain``
        """
        if "/" not in path:
            return path
        parts = path.rsplit("/", 1)
        name, param = parts[0], parts[1]
        # Check if param ends with _send (send level shorthand)
        if param.endswith("_send"):
            bus = param[: -len("_send")]
            return f"{name}_send_{bus}/gain"
        return path

    def _resolve_targets(self, name: str) -> list[str]:
        """Resolve name to matching voices/poly/buses. Exact match first, then prefix."""
        if name in self._voices or name in self._poly or name in self._buses:
            return [name]
        prefix = name + "/"
        matches = [n for n in [*self._voices, *self._poly, *self._buses] if n.startswith(prefix)]
        if not matches:
            raise ValueError(f"voice or group '{name}' not found")
        return matches

    def _resolve_targets_soft(self, name: str) -> list[str]:
        """Like _resolve_targets but returns empty list instead of raising."""
        if name in self._voices or name in self._poly or name in self._buses:
            return [name]
        prefix = name + "/"
        return [n for n in [*self._voices, *self._poly, *self._buses] if n.startswith(prefix)]

    def fade(
        self, path: str, target: float, bars: int = 4, steps_per_bar: int = 4
    ) -> None:
        """Fade any parameter to target over N bars. One-shot (holds at target).

        Accepts either a voice name (fades gain) or a ``/``-separated path
        like ``"bass/gain"``, ``"bass/cutoff"``.

        For voice names: poly voices fade all instances proportionally.
        """
        if bars < 1 or steps_per_bar < 1:
            raise ValueError("bars and steps_per_bar must be >= 1")

        # Path-based fade: "bass/gain", "bass/cutoff", etc.
        if "/" in path:
            parts = path.split("/", 1)
            voice_name, param = parts[0], parts[1]

            # Determine current value: check ctrl_values first, then gain bookkeeping
            if path in self._ctrl_values:
                current = self._ctrl_values[path]
            elif param == "gain" and voice_name in self._voices:
                current = self._voices[voice_name].gain
            elif param == "gain" and voice_name in self._poly:
                current = self._poly[voice_name].gain
            else:
                current = 0.0

            # Hush any existing control pattern on this path
            ctrl_slot = f"_ctrl_{path.replace('/', '_')}"
            self._session.hush(ctrl_slot)
            # Use higher resolution for smooth fades (16 steps/bar minimum)
            effective_spb = max(steps_per_bar, 16)
            pattern = self._build_fade_pattern(current, target, bars, effective_spb)
            self.play(path, pattern)
            self._ctrl_values[path] = target

            # Update gain bookkeeping if applicable
            if param == "gain":
                self._update_gain_bookkeeping(voice_name, target)
            return

        # Legacy: plain voice name → fade gain
        name = path
        if name not in self._poly and name not in self._voices:
            raise ValueError(f"voice '{name}' not found")

        if name in self._poly:
            pv = self._poly[name]
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                self._fade_voice(inst, target / pv.count, bars, steps_per_bar)
            self._poly[name] = PolyVoice(
                type_id=pv.type_id, count=pv.count, gain=target, controls=pv.controls,
            )
        else:
            self._fade_voice(name, target, bars, steps_per_bar)

    def _build_fade_pattern(
        self, current: float, target: float, bars: int, steps_per_bar: int
    ) -> Pattern:
        """Build a ramp pattern over N bars.

        The ramp fills exactly N bars. On loop it replays — acceptable since
        subsequent fades read from _ctrl_values (the target).
        """
        total_steps = bars * steps_per_bar
        atoms: list[Pattern] = []
        for i in range(total_steps + 1):
            t = i / total_steps
            value = current + (target - current) * t
            atoms.append(_osc("/soundman/set", OscStr("ctrl"), OscFloat(value)))
        pattern = atoms[0]
        for a in atoms[1:]:
            pattern = pattern + a
        return pattern.over(bars)

    def _fade_voice(
        self, name: str, target: float, bars: int, steps_per_bar: int
    ) -> None:
        """Schedule a gain fade for a single voice instance."""
        self._session.hush(f"_fade_{name}")
        current = self._voices[name].gain
        total_steps = bars * steps_per_bar
        ramp_atoms: list[Pattern] = []
        for i in range(total_steps + 1):
            t = i / total_steps
            value = current + (target - current) * t
            ramp_atoms.append(_osc("/soundman/set", OscStr(f"{name}/gain"), OscFloat(value)))
        # Hold: repeat target for 19x (one-shot behavior)
        hold_atom = _osc("/soundman/set", OscStr(f"{name}/gain"), OscFloat(target))
        hold_atoms = [hold_atom] * (total_steps * 19)
        all_atoms = ramp_atoms + hold_atoms
        pattern = all_atoms[0]
        for a in all_atoms[1:]:
            pattern = pattern + a
        self._session.play(f"_fade_{name}", pattern.over(bars * 20))
        old = self._voices[name]
        self._voices[name] = Voice(
            type_id=old.type_id, gain=target, controls=old.controls, init=old.init
        )

    def _update_gain_bookkeeping(self, name: str, target: float) -> None:
        """Update gain bookkeeping after a path-based fade."""
        if name in self._poly:
            pv = self._poly[name]
            per_voice = target / pv.count
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                old = self._voices[inst]
                self._voices[inst] = Voice(
                    type_id=old.type_id, gain=per_voice, controls=old.controls, init=old.init
                )
            self._poly[name] = PolyVoice(
                type_id=pv.type_id, count=pv.count, gain=target, controls=pv.controls,
            )
        elif name in self._voices:
            old = self._voices[name]
            self._voices[name] = Voice(
                type_id=old.type_id, gain=target, controls=old.controls, init=old.init
            )

    def bus(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        gain: float = 0.5,
    ) -> None:
        """Add an effect bus. Rebuilds the graph.

        Raises ValueError if name collides with an existing voice or poly parent.
        """
        if name in self._voices or name in self._poly:
            raise ValueError(f"name '{name}' already used as a voice")
        type_id, controls = self._resolve_source(name, source)
        num_inputs: int
        if isinstance(source, DspDef):
            num_inputs = source.num_inputs
        elif callable(source) and not isinstance(source, str):
            result = _transpile(source)  # type: ignore[arg-type]
            num_inputs = result.num_inputs
        else:
            num_inputs = 1
        self._buses[name] = Bus(type_id=type_id, gain=gain, controls=controls, num_inputs=num_inputs)
        if not self._batching:
            self._rebuild()

    def send(self, voice: str, bus: str, level: float = 0.5) -> None:
        """Route a voice to a bus via a gain-controlled send.

        If the (voice, bus) pair already exists, does an instant level update
        (no rebuild). Otherwise stores the send and rebuilds.
        Raises ValueError if a wire exists for the same (voice, bus) pair.
        """
        _check_finite(level, f"send level for '{voice}' → '{bus}'")
        # Resolve voice: accept poly parents or mono voices
        if voice not in self._voices and voice not in self._poly:
            raise ValueError(f"voice '{voice}' not found")
        if bus not in self._buses:
            raise ValueError(f"bus '{bus}' not found")

        key = (voice, bus)

        if key in self._wires:
            raise ValueError(f"wire already exists for ('{voice}', '{bus}') — cannot also send")

        if key in self._sends:
            # Instant update — no rebuild
            self._sends[key] = level
            self._session.set_ctrl(f"{voice}_send_{bus}/gain", level)
            return

        self._sends[key] = level
        if not self._batching:
            self._rebuild()

    def wire(self, voice: str, bus: str, port: str = "in0") -> None:
        """Wire a voice directly to a bus port (no gain stage).

        Raises ValueError if a send exists for the same (voice, bus) pair.
        """
        if voice not in self._voices and voice not in self._poly:
            raise ValueError(f"voice '{voice}' not found")
        if bus not in self._buses:
            raise ValueError(f"bus '{bus}' not found")

        key = (voice, bus)

        if key in self._sends:
            raise ValueError(f"send already exists for ('{voice}', '{bus}') — cannot also wire")

        self._wires[key] = port
        if not self._batching:
            self._rebuild()

    def remove_bus(self, name: str) -> None:
        """Remove a bus and all sends/wires targeting it. Rebuilds the graph."""
        if name not in self._buses:
            raise ValueError(f"bus '{name}' not found")
        del self._buses[name]
        # Clean sends targeting this bus
        for key in [k for k in self._sends if k[1] == name]:
            del self._sends[key]
        # Clean wires targeting this bus
        for key in [k for k in self._wires if k[1] == name]:
            del self._wires[key]
        self._rebuild()

    def mod(self, path: str, pattern: Pattern, bars: int = 1) -> None:
        """Sugar for ``play(path, pattern.over(bars))``."""
        self.play(path, pattern.over(bars))

    @contextmanager
    def batch(self) -> Generator[None]:
        """Batch voice declarations into a single graph rebuild.

        Writes all .dsp files immediately but defers hot-reload waits and
        graph loading until the context manager exits.
        """
        self._batching = True
        snap_voices = dict(self._voices)
        snap_poly = dict(self._poly)
        snap_alloc = dict(self._poly_alloc)
        ok = False
        try:
            yield
            ok = True
        finally:
            self._batching = False
            if ok:
                self._flush()
            else:
                self._voices = snap_voices
                self._poly = snap_poly
                self._poly_alloc = snap_alloc

    def __repr__(self) -> str:
        # Collect top-level names: mono voices + poly parents (skip poly instances)
        poly_instances: set[str] = set()
        for pname, pv in self._poly.items():
            for i in range(pv.count):
                poly_instances.add(f"{pname}_v{i}")

        top: list[str] = []
        for vname in self._voices:
            if vname not in poly_instances:
                top.append(vname)
        for pname in self._poly:
            if pname not in top:
                top.append(pname)

        count = len(top)
        lines = [f"VoiceMixer({count} voices)"]
        if not top:
            return lines[0]

        max_name = max(len(n) for n in top)
        for name in top:
            if name in self._poly:
                pv = self._poly[name]
                parts = f"  {name + ':':.<{max_name + 2}} {pv.type_id}  gain={pv.gain:.2f}"
                if name in self._muted:
                    parts += "  [muted]"
                parts += f"  poly({pv.count})"
            else:
                v = self._voices[name]
                parts = f"  {name + ':':.<{max_name + 2}} {v.type_id}  gain={v.gain:.2f}"
                if name in self._muted:
                    parts += "  [muted]"
            lines.append(parts)

        # Buses
        if self._buses:
            lines.append(f"  buses:")
            for bname, b in self._buses.items():
                lines.append(f"    {bname}: {b.type_id}  gain={b.gain:.2f}")

        return "\n".join(lines)

    @property
    def voices(self) -> dict[str, Voice]:
        """Read-only snapshot of active voices."""
        return dict(self._voices)

    @property
    def node_controls(self) -> dict[str, tuple[str, ...]]:
        """Read-only snapshot of known node type controls."""
        return dict(self._node_controls)

    def _flush(self) -> None:
        """Wait for all pending FAUST types and rebuild the graph once."""
        seen: set[str] = set()
        for voice in self._voices.values():
            if voice.type_id.startswith("faust:") and voice.type_id not in seen:
                seen.add(voice.type_id)
                self._wait_for_type(voice.type_id)
        self._rebuild()

    def _rebuild(self) -> None:
        ir = build_graph_ir(
            self._voices,
            buses=self._buses,
            sends=self._sends,
            wires=self._wires,
            poly={name: pv.count for name, pv in self._poly.items()},
        )
        self._session.load_graph(ir)
        self._graph_loaded = True

    def _wait_for_type(self, type_id: str, timeout: float = 10.0) -> None:
        """Poll until the engine has loaded the given FAUST type.

        Raises TimeoutError if the type doesn't appear within `timeout` seconds.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if type_id in self._session.list_nodes():
                    return
            except (TimeoutError, ConnectionError):
                pass
            time.sleep(0.1)
        raise TimeoutError(f"FAUST type '{type_id}' not ready after {timeout}s")
