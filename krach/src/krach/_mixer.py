"""VoiceMixer — named voices with stable control labels.

Manages FAUST DSP voices, per-voice gain, and the underlying audio graph.
Control labels follow a deterministic convention: ``{voice_name}/{param}``.
Adding or removing a voice rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

import inspect
import json
import math
import textwrap
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable  # Any still used for DspDef.fn

from faust_dsl import transpile as _transpile
from krach.patterns import Graph, GraphIr, Session
from krach.patterns.ir import IrNode, OscStr
from krach.patterns.pattern import Pattern
from krach.patterns.pattern import ctrl as _ctrl
from krach.patterns.pattern import freeze as _freeze
from krach.patterns.pattern import rest as _rest

from krach._pitch import ftom as _ftom
from krach._pitch import mtof as _mtof
from krach._pitch import parse_note as _parse_note


@dataclass(frozen=True)
class Scene:
    """Snapshot of the mixer state — voices, buses, sends, patterns, controls."""

    voices: dict[str, tuple[str, float, tuple[str, ...], int, tuple[tuple[str, float], ...], str]]
    buses: dict[str, tuple[str, float, tuple[str, ...], int]]
    sends: dict[tuple[str, str], float]
    wires: dict[tuple[str, str], str]
    patterns: dict[str, Pattern]
    ctrl_values: dict[str, float]
    tempo: float
    master: float
    muted: dict[str, float]  # name → gain before mute


@dataclass
class Voice:
    """A named audio voice — mono (count=1) or polyphonic (count>1)."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = field(default="", repr=False)
    alloc: int = field(default=0, repr=False)


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

        kr.voice("bass", acid_bass, gain=0.3)
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


def _inst_name(name: str, i: int, count: int) -> str:
    """Instance name: ``name_v{i}`` if count > 1, else ``name``."""
    return f"{name}_v{i}" if count > 1 else name


# ── Control pattern builders ──────────────────────────────────────────────────


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


# ── Pure builders (testable without I/O) ──────────────────────────────────────


def build_graph_ir(
    voices: dict[str, Voice],
    buses: dict[str, Bus] | None = None,
    sends: dict[tuple[str, str], float] | None = None,
    wires: dict[tuple[str, str], str] | None = None,
) -> GraphIr:
    """Build a complete audio graph IR from voices, buses, sends, and wires.

    Each voice gets: DSP node → gain node → DAC.
    Poly voices (count>1) expand to N instances internally.
    Each bus gets: DSP node → gain node → DAC.
    Sends: voice → send_gain → bus (fan-in at bus input).
    Wires: voice → bus:port (direct, no gain node).
    Poly sum: if a poly parent has sends/wires, an implicit sum node collects instances.
    """
    _buses = buses or {}
    _sends = sends or {}
    _wires = wires or {}

    builder = Graph()
    builder.node("out", "dac")

    # Voices: expand instances, DSP → gain → DAC
    for name, voice in voices.items():
        for i in range(voice.count):
            inst = _inst_name(name, i, voice.count)
            per_gain = voice.gain / voice.count
            builder.node(inst, voice.type_id, **dict(voice.init))
            builder.node(f"{inst}_g", "gain", gain=per_gain)
            builder.connect(inst, "out", f"{inst}_g", "in")
            builder.connect(f"{inst}_g", "out", "out", "in")
            for param in voice.controls:
                builder.expose(f"{inst}/{param}", inst, param)
            builder.expose(f"{inst}/gain", f"{inst}_g", "gain")

    # Poly sum nodes: implicit summing point for poly parents with sends/wires
    poly_with_routing: set[str] = set()
    for voice_name, _bus in [*_sends.keys(), *_wires.keys()]:
        v = voices.get(voice_name)
        if v is not None and v.count > 1:
            poly_with_routing.add(voice_name)

    for parent in poly_with_routing:
        voice = voices[parent]
        builder.node(f"{parent}_sum", "gain", gain=1.0)
        for i in range(voice.count):
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
    for (voice_name, bus_name), level in _sends.items():
        source = f"{voice_name}_sum" if voice_name in poly_with_routing else voice_name
        send_id = f"{voice_name}_send_{bus_name}"
        builder.node(send_id, "gain", gain=level)
        builder.connect(source, "out", send_id, "in")
        builder.connect(send_id, "out", bus_name, "in")
        builder.expose(f"{send_id}/gain", send_id, "gain")

    # Wires: source → bus:port (direct, no gain node)
    for (voice_name, bus_name), port in _wires.items():
        source = f"{voice_name}_sum" if voice_name in poly_with_routing else voice_name
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
        onset_atoms.append(_ctrl(f"{voice_name}/freq", pitch))

    if vel != 1.0 and "vel" in controls:
        onset_atoms.append(_ctrl(f"{voice_name}/vel", vel))

    for param, value in params.items():
        if param in controls:
            onset_atoms.append(_ctrl(f"{voice_name}/{param}", value))

    if "gate" in controls:
        onset_atoms.append(_ctrl(f"{voice_name}/gate", 1.0))

    if not onset_atoms:
        raise ValueError(f"voice '{voice_name}' has no triggerable controls")

    # Stack all onset values (fire simultaneously)
    onset = onset_atoms[0]
    for a in onset_atoms[1:]:
        onset = onset | a  # Stack: fire simultaneously

    if "gate" in controls:
        reset = _ctrl(f"{voice_name}/gate", 0.0)
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
    trig = _ctrl(label, 1.0)
    reset = _ctrl(label, 0.0)
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
        onset: Pattern = _ctrl("gate", 1.0)
        reset = _ctrl("gate", 0.0)
        return _freeze(onset + reset)

    atoms: list[Pattern] = []
    for p in pitches:
        hz = _resolve_pitch(p)
        onset_parts: list[Pattern] = []
        onset_parts.append(_ctrl("freq", hz))
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
    onset_parts: list[Pattern] = [_ctrl(param, 1.0)]
    for k, v in kwargs.items():
        onset_parts.append(_ctrl(k, v))

    onset = onset_parts[0]
    for a in onset_parts[1:]:
        onset = onset | a

    reset = _ctrl(param, 0.0)
    return _freeze(onset + reset)


def seq(*notes: str | int | float | None, vel: float = 1.0, **params: float) -> Pattern:
    """Build a sequence of notes/rests with bare param names.

    Bind to a voice at play time via ``_bind_voice()``.
    """
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


# ── Tree rewriters ────────────────────────────────────────────────────────────


def _bind_voice(node: IrNode, voice: str) -> IrNode:
    """Prepend ``voice/`` to bare param names in Control and Osc atoms.

    A param is "bare" if it does not contain ``/``.  Already-bound params
    (containing ``/``) are left unchanged.  Walks the full IR tree.
    """
    from krach.patterns.ir import (
        Atom,
        Cat,
        Control,
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
        Warp,
    )

    match node:
        case Atom(Control(label=label, value=val)):
            if "/" not in label:
                return Atom(Control(label=f"{voice}/{label}", value=val))
            return node
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
        case Warp(kind, amount, grid, child):
            return Warp(kind, amount, grid, _bind_voice(child, voice))
        case _:
            return node


def _bind_voice_poly(
    node: IrNode, parent: str, count: int, alloc: int,
) -> tuple[IrNode, int]:
    """Bind a pattern to a poly voice, round-robin allocating instances.

    Each Freeze compound (note/hit event) binds to the next instance.
    Returns (rewritten_node, updated_alloc_counter).
    """
    from krach.patterns.ir import (
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
        Warp,
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
        case Warp(kind, amount, grid, child):
            bound, alloc = _bind_voice_poly(child, parent, count, alloc)
            return Warp(kind, amount, grid, bound), alloc
        case _:
            # Atom without Freeze — bind to current instance (non-compound event)
            inst = f"{parent}_v{alloc % count}"
            return _bind_voice(node, inst), alloc


def _bind_ctrl(node: IrNode, label: str) -> IrNode:
    """Replace the ``"ctrl"`` placeholder param in Control and Osc atoms with ``label``.

    Similar to ``_bind_voice()`` but replaces the specific placeholder
    ``"ctrl"`` rather than prepending a prefix.
    """
    from krach.patterns.ir import (
        Atom,
        Cat,
        Control,
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
        Warp,
    )

    match node:
        case Atom(Control(label=ctrl_label, value=val)):
            if ctrl_label == "ctrl":
                return Atom(Control(label=label, value=val))
            return node
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
        case Warp(kind, amount, grid, child):
            return Warp(kind, amount, grid, _bind_ctrl(child, label))
        case _:
            return node


# ── VoiceMixer ────────────────────────────────────────────────────────────────


class VoiceMixer:
    """Manages named audio voices with stable control labels.

    Each voice is a FAUST DSP node (string type_id or Python function) with
    an independent gain stage.  Adding/removing voices rebuilds the audio
    graph transparently.  ``gain()`` updates are instant (no rebuild).

    Pattern builders and pitch utilities are exposed as static methods so
    that ``kr.note()``, ``kr.hit()``, etc. work when ``kr`` is an instance.
    """

    # ── Pattern builders (static — no instance state) ─────────────────────
    note = staticmethod(note)
    hit = staticmethod(hit)
    seq = staticmethod(seq)
    rest = staticmethod(_rest)
    ramp = staticmethod(ramp)
    mod_sine = staticmethod(mod_sine)
    mod_tri = staticmethod(mod_tri)
    mod_ramp = staticmethod(mod_ramp)
    mod_ramp_down = staticmethod(mod_ramp_down)
    mod_square = staticmethod(mod_square)
    mod_exp = staticmethod(mod_exp)
    dsp = staticmethod(dsp)

    # ── Pitch utilities (static) ──────────────────────────────────────────
    mtof = staticmethod(_mtof)
    ftom = staticmethod(_ftom)
    parse_note = staticmethod(_parse_note)

    # Settable public properties — __setattr__ rejects unknown public names.
    _PUBLIC_SETTERS = frozenset({"master", "tempo", "bpm", "meter"})

    def __setattr__(self, name: str, value: object) -> None:
        # Allow private attributes, known property setters, and class-defined attributes
        # (the latter enables unittest.mock.patch to work).
        if name.startswith("_") or name in self._PUBLIC_SETTERS or hasattr(type(self), name):
            super().__setattr__(name, value)
        else:
            raise AttributeError(
                f"kr has no property {name!r}. "
                f"Settable properties: {', '.join(sorted(self._PUBLIC_SETTERS))}"
            )

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
        self._muted: dict[str, float] = {}  # name → gain before mute
        self._buses: dict[str, Bus] = {}
        self._sends: dict[tuple[str, str], float] = {}  # (voice, bus) → gain
        self._wires: dict[tuple[str, str], str] = {}    # (voice, bus) → port
        self._ctrl_values: dict[str, float] = {}  # path → last set value (for fade start)
        self._patterns: dict[str, Pattern] = {}  # target → last unbound pattern
        self._scenes: dict[str, Scene] = {}
        self._batching: bool = False
        self._graph_loaded: bool = False
        self._master_gain: float = 0.7
        self._session.master_gain(self._master_gain)

    def _resolve_source(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        fallback_controls: tuple[str, ...] = (),
    ) -> tuple[str, tuple[str, ...], str]:
        """Resolve a source to (type_id, controls, source_text).

        Writes .dsp and .py to dsp_dir and waits for JIT if needed.
        ``source_text`` is the Python source code (empty for string type_ids).
        """
        if isinstance(source, DspDef):
            type_id = f"faust:{name}"
            source_text = source.source
            faust_code, controls = source.faust, source.controls
        elif callable(source):
            type_id = f"faust:{name}"
            source_text = textwrap.dedent(inspect.getsource(source))
            result = _transpile(source)  # type: ignore[arg-type]
            faust_code, controls = result.source, tuple(c.name for c in result.schema.controls)
        else:
            return source, self._node_controls.get(source, fallback_controls), ""

        py_path = self._dsp_dir.joinpath(f"{name}.py")
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(source_text)
        dsp_path = self._dsp_dir.joinpath(f"{name}.dsp")
        dsp_path.parent.mkdir(parents=True, exist_ok=True)
        dsp_path.write_text(faust_code)
        self._node_controls[type_id] = controls
        if not self._batching:
            self._wait_for_type(type_id)
        return type_id, controls, source_text

    def input(self, name: str = "mic", channel: int = 0, gain: float = 0.5) -> VoiceHandle:
        """Add an audio input voice (ADC).

        Starts the system audio input stream (if not already started) and
        creates an ``adc_input`` node in the graph.

        ``channel``: which input channel to capture (0-based).
        """
        self._session.start_input(channel)
        self._node_controls["adc_input"] = ()
        # Use voice() with the built-in adc_input type.
        return self.voice(name, "adc_input", gain=gain)

    def midi_map(
        self,
        cc: int,
        path: str,
        lo: float = 0.0,
        hi: float = 1.0,
        channel: int = 0,
    ) -> None:
        """Map a MIDI CC to a control path.

        ``cc``: MIDI CC number (0-127).
        ``path``: control path, e.g. ``"bass/cutoff"`` or ``"bass/gain"``.
        ``lo``/``hi``: output range the CC 0-127 is scaled to.
        ``channel``: MIDI channel (0-based, default 0).
        """
        label = self._resolve_path(path)
        self._session.midi_map(channel, cc, label, lo, hi)

    def voice(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        gain: float = 0.5,
        count: int = 1,
        **init: float,
    ) -> VoiceHandle:
        """Add or replace a voice.  Rebuilds the graph.

        ``source`` is a ``@dsp``-decorated function, a registered type_id
        string, or a raw Python DSP function (transpiled on the fly).

        ``count``: 1 for mono, >1 for polyphonic (N instances, round-robin).
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        type_id, controls, source_text = self._resolve_source(name, source, tuple(init.keys()))
        self._muted.pop(name, None)

        # Clean up old voice state if replacing
        if name in self._voices:
            old = self._voices[name]
            self.hush(name)
            # Clean instance-level muted entries from old poly
            for i in range(old.count):
                self._muted.pop(_inst_name(name, i, old.count), None)

        # Clean sends/wires from old voice
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]

        is_new = name not in self._voices
        self._voices[name] = Voice(
            type_id=type_id,
            gain=gain,
            controls=controls,
            count=count,
            init=tuple(init.items()),
            source_text=source_text,
            alloc=0,
        )
        if not self._batching:
            if is_new and self._graph_loaded and count == 1:
                self._session.add_voice(name, type_id, controls, gain)
            else:
                self._rebuild()
        return VoiceHandle(self, name)

    def remove(self, name: str) -> None:
        """Remove a voice. Rebuilds the graph."""
        if name not in self._voices:
            raise ValueError(f"voice '{name}' not found")
        voice = self._voices[name]
        self._muted.pop(name, None)
        self.hush(name)
        # Clean instance-level muted entries
        for i in range(voice.count):
            self._muted.pop(_inst_name(name, i, voice.count), None)
        # Clean sends/wires where this voice is the source
        for key in [k for k in self._sends if k[0] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[0] == name]:
            del self._wires[key]
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
        voice = self._voices.get(name)
        if voice is not None:
            for i in range(voice.count):
                inst = _inst_name(name, i, voice.count)
                if voice.count > 1:
                    self._session.hush(inst)
                    self._session.hush(f"_fade_{inst}")
                if "gate" in voice.controls:
                    self._session.set_ctrl(f"{inst}/gate", 0.0)

    def stop(self) -> None:
        """Hush all voices and release all gates."""
        for name in self._voices:
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
        """Set gain for a single voice or bus."""
        if name in self._buses:
            old_bus = self._buses[name]
            self._buses[name] = Bus(
                type_id=old_bus.type_id, gain=value,
                controls=old_bus.controls, num_inputs=old_bus.num_inputs,
            )
            self._session.set_ctrl(f"{name}/gain", float(value))
            return
        voice = self._voices[name]
        voice.gain = value
        per_voice = value / voice.count
        for i in range(voice.count):
            inst = _inst_name(name, i, voice.count)
            self._session.set_ctrl(f"{inst}/gain", float(per_voice))

    def mute(self, name: str) -> None:
        """Mute a voice or group — stores current gain, sets gain to 0. No-op if already muted."""
        targets = self._resolve_targets(name)
        for t in targets:
            self._mute_single(t)

    def _mute_single(self, name: str) -> None:
        """Mute a single voice or bus."""
        if name in self._muted:
            return
        if name in self._voices:
            self._muted[name] = self._voices[name].gain
        elif name in self._buses:
            self._muted[name] = self._buses[name].gain
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
        all_names: set[str] = set(self._voices.keys())
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

    # ── Scenes ─────────────────────────────────────────────────────────────

    def save(self, name: str) -> None:
        """Save current state as a named scene."""
        self._scenes[name] = Scene(
            voices={n: (v.type_id, v.gain, v.controls, v.count, v.init, v.source_text) for n, v in self._voices.items()},
            buses={n: (b.type_id, b.gain, b.controls, b.num_inputs) for n, b in self._buses.items()},
            sends=dict(self._sends),
            wires=dict(self._wires),
            patterns=dict(self._patterns),
            ctrl_values=dict(self._ctrl_values),
            tempo=self.tempo,
            master=self._master_gain,
            muted=dict(self._muted),
        )

    def recall(self, name: str) -> None:
        """Recall a saved scene — rebuilds graph, replays patterns, restores controls."""
        if name not in self._scenes:
            raise ValueError(f"scene '{name}' not found")
        scene = self._scenes[name]

        # Stop everything
        self.stop()

        # Rebuild voices and buses
        self._voices.clear()
        self._buses.clear()
        self._sends.clear()
        self._wires.clear()

        for vname, (type_id, gain, controls, count, init, source_text) in scene.voices.items():
            self._voices[vname] = Voice(
                type_id=type_id, gain=gain, controls=controls,
                count=count, init=init, source_text=source_text,
            )
        for bname, (type_id, gain, controls, num_inputs) in scene.buses.items():
            self._buses[bname] = Bus(type_id=type_id, gain=gain, controls=controls, num_inputs=num_inputs)
        self._sends = dict(scene.sends)
        self._wires = dict(scene.wires)
        self._muted = dict(scene.muted)
        self._rebuild()

        # Restore tempo and master
        self.tempo = scene.tempo
        self.master = scene.master

        # Restore control values
        for path, value in scene.ctrl_values.items():
            self.set(path, value)

        # Replay patterns
        for slot, pattern in scene.patterns.items():
            self.play(slot, pattern)

    @property
    def scenes(self) -> list[str]:
        """List of saved scene names."""
        return list(self._scenes.keys())

    def load(self, path: str) -> None:
        """Load and execute a Python file with ``kr`` (and ``mix`` compat) in scope."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"scene file not found: {path}")
        code = p.read_text()
        ns: dict[str, object] = {"kr": self, "mix": self}
        exec(compile(code, path, "exec"), ns)  # noqa: S102

    def export(self, path: str) -> None:
        """Export current session state to a reloadable Python script.

        The generated file can be loaded back with ``kr.load(path)``.
        DSP definitions, voices, buses, sends, patterns, and transport
        settings are all captured.
        """
        from krach.patterns.ir import ir_to_dict

        lines: list[str] = [
            '"""Exported krach session."""',
            "import json",
            "from krach.patterns.ir import dict_to_ir",
            "from krach.patterns.pattern import Pattern",
            "import krach.dsp as krs",
            "",
        ]

        # ── DSP function definitions ──
        emitted_fns: dict[str, str] = {}  # type_id → function name
        for name, voice in self._voices.items():
            if voice.source_text and voice.type_id.startswith("faust:"):
                fn_name = name.replace("/", "_")
                lines.append("")
                # Emit source with @kr.dsp decorator
                source = voice.source_text.rstrip()
                if "@kr.dsp" not in source and "@dsp" not in source:
                    lines.append("@kr.dsp")
                lines.append(source)
                emitted_fns[voice.type_id] = fn_name
        for bname, bus in self._buses.items():
            py_path = self._dsp_dir.joinpath(f"{bname}.py")
            if py_path.exists():
                fn_name = bname.replace("/", "_")
                source = py_path.read_text().rstrip()
                if fn_name not in emitted_fns.values():
                    lines.append("")
                    if "@kr.dsp" not in source and "@dsp" not in source:
                        lines.append("@kr.dsp")
                    lines.append(source)
                    emitted_fns[bus.type_id] = fn_name

        # ── Voices and buses ──
        lines.append("")
        lines.append("with kr.batch():")
        for name, voice in self._voices.items():
            src = emitted_fns.get(voice.type_id, f'"{voice.type_id}"')
            init_kw = "".join(f", {k}={v}" for k, v in voice.init)
            count_kw = f", count={voice.count}" if voice.count > 1 else ""
            lines.append(f'    kr.voice("{name}", {src}, gain={voice.gain}{count_kw}{init_kw})')
        for bname, bus in self._buses.items():
            src = emitted_fns.get(bus.type_id, f'"{bus.type_id}"')
            lines.append(f'    kr.bus("{bname}", {src}, gain={bus.gain})')

        # ── Sends and wires ──
        for (voice, bus), level in self._sends.items():
            lines.append(f'kr.send("{voice}", "{bus}", level={level})')
        for (voice, bus), port in self._wires.items():
            lines.append(f'kr.wire("{voice}", "{bus}", port="{port}")')

        # ── Transport ──
        try:
            lines.append(f"kr.tempo = {float(self.tempo)}")
        except (TypeError, ValueError):
            pass
        lines.append(f"kr.master = {self._master_gain}")
        try:
            meter = float(self.meter)
            if meter != 4.0:
                lines.append(f"kr.meter = {meter}")
        except (TypeError, ValueError):
            pass

        # ── Patterns as JSON ──
        if self._patterns:
            pat_dict = {slot: ir_to_dict(pat.node) for slot, pat in self._patterns.items()}
            pat_json = json.dumps(pat_dict, separators=(",", ":"))
            lines.append("")
            lines.append(f"_patterns = json.loads('{pat_json}')")
            lines.append("for _slot, _ir in _patterns.items():")
            lines.append("    kr.play(_slot, Pattern(dict_to_ir(_ir)))")

        # ── Control values ──
        for ctrl_path, value in self._ctrl_values.items():
            lines.append(f'kr.set("{ctrl_path}", {value})')

        lines.append("")
        Path(path).write_text("\n".join(lines))

    def _is_voice_or_bus(self, name: str) -> bool:
        """Check if name is a known voice or bus."""
        return name in self._voices or name in self._buses

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Play a pattern on a voice or control path.

        - Known voice name (exact match): binds bare params to ``voice/param``
        - Poly voice (count>1): round-robin allocates instances
        - Otherwise with ``/``: control path — rewrites ``"ctrl"`` placeholder
        - Otherwise without ``/``: mono voice binding (may be a new slot)

        ``from_zero``: if True, uses ``play_from_zero`` so the pattern phase
        starts at 0 regardless of the current cycle position.
        """
        if swing is not None:
            pattern = pattern.swing(swing)
        self._patterns[target] = pattern
        send = self._session.play_from_zero if from_zero else self._session.play
        voice = self._voices.get(target)
        if voice is not None and voice.count > 1:
            bound_node, new_alloc = _bind_voice_poly(
                pattern.node, target, voice.count, voice.alloc
            )
            voice.alloc = new_alloc
            send(target, Pattern(bound_node))
        elif self._is_voice_or_bus(target):
            bound = Pattern(_bind_voice(pattern.node, target))
            send(target, bound)
        elif "/" in target:
            label = self._resolve_path(target)
            bound = Pattern(_bind_ctrl(pattern.node, label))
            slot = f"_ctrl_{target.replace('/', '_')}"
            send(slot, bound)
        else:
            bound = Pattern(_bind_voice(pattern.node, target))
            send(target, bound)

    def pattern(self, name: str) -> Pattern:
        """Retrieve the last unbound pattern played on a target."""
        if name not in self._patterns:
            raise ValueError(f"no pattern for '{name}'")
        return self._patterns[name]

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
        """Resolve name to matching voices/buses. Exact match first, then prefix."""
        if name in self._voices or name in self._buses:
            return [name]
        prefix = name + "/"
        matches = [n for n in [*self._voices, *self._buses] if n.startswith(prefix)]
        if not matches:
            raise ValueError(f"voice or group '{name}' not found")
        return matches

    def _resolve_targets_soft(self, name: str) -> list[str]:
        """Like _resolve_targets but returns empty list instead of raising."""
        if name in self._voices or name in self._buses:
            return [name]
        prefix = name + "/"
        return [n for n in [*self._voices, *self._buses] if n.startswith(prefix)]

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

            # Determine current value
            if path in self._ctrl_values:
                current = self._ctrl_values[path]
            elif param == "gain" and voice_name in self._voices:
                current = self._voices[voice_name].gain
            else:
                current = 0.0

            # Clear any existing pattern-based control on this path
            ctrl_slot = f"_ctrl_{path.replace('/', '_')}"
            self._session.hush(ctrl_slot)

            # Use native automation (one-shot ramp)
            label = self._resolve_path(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(
                label, "ramp", current, target, period_secs, one_shot=True
            )
            self._ctrl_values[path] = target

            # Update gain bookkeeping if applicable
            if param == "gain":
                self._update_gain_bookkeeping(voice_name, target)
            return

        # Legacy: plain voice name → fade gain
        name = path
        if name not in self._voices:
            raise ValueError(f"voice '{name}' not found")

        voice = self._voices[name]
        for i in range(voice.count):
            inst = _inst_name(name, i, voice.count)
            self._fade_voice(inst, target / voice.count, bars, steps_per_bar)
        voice.gain = target

    def _fade_voice(
        self, name: str, target: float, bars: int, steps_per_bar: int
    ) -> None:
        """Schedule a gain fade for a single voice instance."""
        self._session.hush(f"_fade_{name}")
        # Find current gain for this instance
        # For poly instances, compute from parent
        current = target  # fallback
        for vname, voice in self._voices.items():
            if voice.count == 1 and vname == name:
                current = voice.gain
                break
            if voice.count > 1:
                for i in range(voice.count):
                    if _inst_name(vname, i, voice.count) == name:
                        current = voice.gain / voice.count
                        break

        total_steps = bars * steps_per_bar
        ramp_atoms: list[Pattern] = []
        for i in range(total_steps + 1):
            t = i / total_steps
            value = current + (target - current) * t
            ramp_atoms.append(_ctrl(f"{name}/gain", value))
        # Hold: repeat target for 19x (one-shot behavior)
        hold_atom = _ctrl(f"{name}/gain", target)
        hold_atoms = [hold_atom] * (total_steps * 19)
        all_atoms = ramp_atoms + hold_atoms
        pattern = all_atoms[0]
        for a in all_atoms[1:]:
            pattern = pattern + a
        self._session.play(f"_fade_{name}", pattern.over(bars * 20))

    def _update_gain_bookkeeping(self, name: str, target: float) -> None:
        """Update gain bookkeeping after a path-based fade."""
        if name in self._voices:
            self._voices[name].gain = target

    def bus(
        self,
        name: str,
        source: str | DspDef | Callable[..., Any],
        gain: float = 0.5,
    ) -> BusHandle:
        """Add an effect bus. Rebuilds the graph.

        Raises ValueError if name collides with an existing voice.
        """
        if name in self._voices:
            raise ValueError(f"name '{name}' already used as a voice")
        type_id, controls, _source_text = self._resolve_source(name, source)
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
        return BusHandle(self, name)

    def send(self, voice: str, bus: str, level: float = 0.5) -> None:
        """Route a voice to a bus via a gain-controlled send.

        If the (voice, bus) pair already exists, does an instant level update
        (no rebuild). Otherwise stores the send and rebuilds.
        Raises ValueError if a wire exists for the same (voice, bus) pair.
        """
        _check_finite(level, f"send level for '{voice}' → '{bus}'")
        if voice not in self._voices:
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
        if voice not in self._voices:
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
        for key in [k for k in self._sends if k[1] == name]:
            del self._sends[key]
        for key in [k for k in self._wires if k[1] == name]:
            del self._wires[key]
        self._rebuild()

    def mod(
        self, path: str, pattern_or_shape: Pattern | str,
        lo: float = 0.0, hi: float = 1.0, bars: int = 1,
    ) -> None:
        """Modulate a control parameter.

        If ``pattern_or_shape`` is a ``Pattern``, schedules it as a timed
        pattern (legacy path).  If it is a ``str`` (e.g. ``"sine"``,
        ``"tri"``), sends a native automation to the audio engine.
        """
        if isinstance(pattern_or_shape, str):
            label = self._resolve_path(path)
            beats = bars * self._session.meter
            period_secs = beats * 60.0 / self.tempo
            self._session.set_automation(label, pattern_or_shape, lo, hi, period_secs)
        else:
            self.play(path, pattern_or_shape.over(bars), from_zero=True)

    @contextmanager
    def batch(self) -> Generator[None]:
        """Batch voice declarations into a single graph rebuild.

        Writes all .dsp files immediately but defers hot-reload waits and
        graph loading until the context manager exits.
        """
        self._batching = True
        snap_voices = dict(self._voices)
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

    def __repr__(self) -> str:
        top = list(self._voices.keys())
        count = len(top)
        lines = [f"VoiceMixer({count} voices)"]
        if not top:
            return lines[0]

        max_name = max(len(n) for n in top)
        for name in top:
            v = self._voices[name]
            parts = f"  {name + ':':.<{max_name + 2}} {v.type_id}  gain={v.gain:.2f}"
            if name in self._muted:
                parts += "  [muted]"
            if v.count > 1:
                parts += f"  poly({v.count})"
            lines.append(parts)

        # Buses
        if self._buses:
            lines.append(f"  buses:")
            for bname, b in self._buses.items():
                lines.append(f"    {bname}: {b.type_id}  gain={b.gain:.2f}")

        return "\n".join(lines)

    def disconnect(self) -> None:
        """Disconnect from the audio engine."""
        self._session.disconnect()

    @property
    def master(self) -> float:
        """Master output gain (0.0-1.0)."""
        return self._master_gain

    @master.setter
    def master(self, value: float) -> None:
        _check_finite(value, "master gain")
        self._master_gain = value
        self._session.master_gain(value)

    @property
    def tempo(self) -> float:
        """Current tempo (BPM), delegated to session."""
        return self._session.tempo

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self._session.tempo = bpm

    @property
    def bpm(self) -> float:
        """Alias for tempo."""
        return self._session.tempo

    @bpm.setter
    def bpm(self, value: float) -> None:
        self._session.tempo = value

    @property
    def meter(self) -> float:
        """Current beats per cycle, delegated to session."""
        return self._session.meter

    @meter.setter
    def meter(self, beats: float) -> None:
        self._session.meter = beats

    @property
    def slots(self) -> dict[str, Any]:
        """Read-only snapshot of session slots."""
        return self._session.slots

    def get_voice(self, name: str) -> Voice | None:
        """Look up a single voice by name, or None if not found."""
        return self._voices.get(name)

    def is_muted(self, name: str) -> bool:
        """Check if a voice is currently muted."""
        return name in self._muted

    def get_bus(self, name: str) -> Bus | None:
        """Look up a single bus by name, or None if not found."""
        return self._buses.get(name)

    @property
    def voice_data(self) -> dict[str, Voice]:
        """Read-only snapshot of active voices as raw Voice structs."""
        return dict(self._voices)

    @property
    def voices(self) -> dict[str, VoiceHandle]:
        """Active voices as name → VoiceHandle."""
        return {name: VoiceHandle(self, name) for name in self._voices}

    @property
    def buses(self) -> dict[str, BusHandle]:
        """Active buses as name → BusHandle."""
        return {name: BusHandle(self, name) for name in self._buses}

    @property
    def node_controls(self) -> dict[str, tuple[str, ...]]:
        """Read-only snapshot of known node type controls."""
        return dict(self._node_controls)

    def _flush(self) -> None:
        """Wait for all pending FAUST types (voices + buses) and rebuild the graph once."""
        seen: set[str] = set()
        for voice in self._voices.values():
            if voice.type_id.startswith("faust:") and voice.type_id not in seen:
                seen.add(voice.type_id)
                self._wait_for_type(voice.type_id)
        for bus in self._buses.values():
            if bus.type_id.startswith("faust:") and bus.type_id not in seen:
                seen.add(bus.type_id)
                self._wait_for_type(bus.type_id)
        self._rebuild()

    def _rebuild(self) -> None:
        ir = build_graph_ir(
            self._voices,
            buses=self._buses,
            sends=self._sends,
            wires=self._wires,
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


class VoiceHandle:
    """Proxy for a named voice — delegates all operations to VoiceMixer."""

    def __init__(self, mixer: VoiceMixer, name: str) -> None:
        self._mixer = mixer
        self._name = name

    def play(self, target_or_pattern: str | Pattern, pattern: Pattern | None = None) -> None:
        if pattern is not None and isinstance(target_or_pattern, str):
            self._mixer.play(f"{self._name}/{target_or_pattern}", pattern)
        else:
            assert isinstance(target_or_pattern, Pattern)
            self._mixer.play(self._name, target_or_pattern)

    def pattern(self) -> Pattern:
        """Retrieve the last unbound pattern played on this voice."""
        return self._mixer.pattern(self._name)

    def set(self, param: str, value: float) -> None:
        self._mixer.set(f"{self._name}/{param}", value)

    def fade(self, param: str, target: float, bars: int = 4) -> None:
        self._mixer.fade(f"{self._name}/{param}", target, bars=bars)

    def send(self, bus: BusHandle | str, level: float = 0.5) -> None:
        bus_name = bus.name if isinstance(bus, BusHandle) else bus
        self._mixer.send(self._name, bus_name, level)

    def mute(self) -> None:
        self._mixer.mute(self._name)

    def unmute(self) -> None:
        self._mixer.unmute(self._name)

    def hush(self) -> None:
        self._mixer.hush(self._name)

    def gain(self, value: float) -> None:
        self._mixer.gain(self._name, value)

    @property
    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:
        v = self._mixer.get_voice(self._name)
        if not v:
            return f"VoiceHandle('{self._name}', removed)"
        parts = f"VoiceHandle('{self._name}', {v.type_id}, gain={v.gain:.2f}"
        if v.count > 1:
            parts += f", count={v.count}"
        if self._mixer.is_muted(self._name):
            parts += ", muted"
        return parts + ")"


class BusHandle:
    """Proxy for a named bus — delegates to VoiceMixer."""

    def __init__(self, mixer: VoiceMixer, name: str) -> None:
        self._mixer = mixer
        self._name = name

    def set(self, param: str, value: float) -> None:
        self._mixer.set(f"{self._name}/{param}", value)

    def gain(self, value: float) -> None:
        self._mixer.gain(self._name, value)

    @property
    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:
        b = self._mixer.get_bus(self._name)
        if not b:
            return f"BusHandle('{self._name}', removed)"
        return f"BusHandle('{self._name}', {b.type_id}, gain={b.gain:.2f})"
