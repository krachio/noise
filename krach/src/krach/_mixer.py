"""VoiceMixer — named voices with stable control labels.

Manages FAUST DSP voices, per-voice gain, and the underlying soundman graph.
Control labels follow a deterministic convention: ``{voice_name}_{param}``.
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
from midiman_frontend.ir import OscFloat, OscStr
from midiman_frontend.pattern import Pattern
from midiman_frontend.pattern import freeze as _freeze
from midiman_frontend.pattern import osc as _osc
from midiman_frontend.pattern import rest as _rest


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
            builder.expose(f"{name}_{param}", name, param)
        builder.expose(f"{name}_gain", f"{name}_g", "gain")

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
            builder.expose(f"{name}_{param}", name, param)
        builder.expose(f"{name}_gain", f"{name}_g", "gain")

    # Sends: source → send_gain → bus:in
    for (voice, bus_name), level in _sends.items():
        source = f"{voice}_sum" if voice in poly_with_routing else voice
        send_id = f"{voice}_send_{bus_name}"
        builder.node(send_id, "gain", gain=level)
        builder.connect(source, "out", send_id, "in")
        builder.connect(send_id, "out", bus_name, "in")
        builder.expose(f"{send_id}_gain", send_id, "gain")

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
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_freq"), OscFloat(pitch)))

    if vel != 1.0 and "vel" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_vel"), OscFloat(vel)))

    for param, value in params.items():
        if param in controls:
            onset_atoms.append(
                _osc("/soundman/set", OscStr(f"{voice_name}_{param}"), OscFloat(value))
            )

    if "gate" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_gate"), OscFloat(1.0)))

    if not onset_atoms:
        raise ValueError(f"voice '{voice_name}' has no triggerable controls")

    # Stack all onset values (fire simultaneously)
    onset = onset_atoms[0]
    for a in onset_atoms[1:]:
        onset = onset | a  # Stack: fire simultaneously

    if "gate" in controls:
        reset = _osc("/soundman/set", OscStr(f"{voice_name}_gate"), OscFloat(0.0))
        return _freeze(onset + reset)
    return _freeze(onset)


def build_hit(voice_name: str, param: str) -> Pattern:
    """Build a frozen trigger compound: trig + reset with guaranteed gap.

    Uses ``Freeze(Cat([trig, reset]))`` so this counts as ONE atom.
    ``rest() + build_hit(...)`` is 2 top-level atoms (not 3). The trig fires
    at the first half of the slot, reset at the second half, leaving a gap
    before the next atom's onset for FAUST to detect the rising edge.
    """
    label = f"{voice_name}_{param}"
    trig = _osc("/soundman/set", OscStr(label), OscFloat(1.0))
    reset = _osc("/soundman/set", OscStr(label), OscFloat(0.0))
    return _freeze(trig + reset)


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
        self._mods: set[str] = set()                     # active mod slot names
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
        """Stop the pattern, its fade, and release gates for a voice (or all poly instances)."""
        self._session.hush(name)
        self._session.hush(f"_fade_{name}")
        if name in self._poly:
            pv = self._poly[name]
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                self._session.hush(inst)
                self._session.hush(f"_fade_{inst}")
                if "gate" in pv.controls:
                    self._session.set_ctrl(f"{inst}_gate", 0.0)
        else:
            voice = self._voices.get(name)
            if voice and "gate" in voice.controls:
                self._session.set_ctrl(f"{name}_gate", 0.0)

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
        """Update a voice's gain. Instant — no graph rebuild.

        For poly voices, distributes gain equally across instances.
        """
        _check_finite(value, f"gain for '{name}'")
        if name not in self._poly and name not in self._voices:
            raise ValueError(f"voice '{name}' not found")
        if name in self._poly:
            pv = self._poly[name]
            per_voice = value / pv.count
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                old = self._voices[inst]
                self._voices[inst] = Voice(
                    type_id=old.type_id, gain=per_voice, controls=old.controls, init=old.init
                )
                self._session.set_ctrl(f"{inst}_gain", float(per_voice))
            self._poly[name] = PolyVoice(
                type_id=pv.type_id, count=pv.count, gain=value, controls=pv.controls,
            )
        else:
            old = self._voices[name]
            self._voices[name] = Voice(
                type_id=old.type_id, gain=value, controls=old.controls, init=old.init
            )
            self._session.set_ctrl(f"{name}_gain", float(value))

    def mute(self, name: str) -> None:
        """Mute a voice — stores current gain, sets gain to 0. No-op if already muted."""
        if name not in self._voices and name not in self._poly:
            raise ValueError(f"voice '{name}' not found")
        if name in self._muted:
            return
        if name in self._poly:
            self._muted[name] = self._poly[name].gain
        else:
            self._muted[name] = self._voices[name].gain
        self.gain(name, 0.0)

    def unmute(self, name: str) -> None:
        """Unmute a voice — restores gain saved by mute()."""
        if name not in self._muted:
            return
        self.gain(name, self._muted.pop(name))

    def solo(self, name: str) -> None:
        """Solo a voice — mutes all others, unmutes target."""
        if name not in self._voices and name not in self._poly:
            raise ValueError(f"voice '{name}' not found")
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
            if n != name:
                self.mute(n)
        self.unmute(name)

    def unsolo(self) -> None:
        """Unmute all muted voices — reverses solo() or manual mutes."""
        for name in list(self._muted):
            self.unmute(name)

    def note(self, name: str, *pitches: float, vel: float = 1.0, **params: float) -> Pattern:
        """Unified melodic trigger: single note, chord, or gate-only.

        - 0 pitches: gate-only trigger (no freq set)
        - 1 pitch: single note on mono or next poly instance
        - N pitches on poly: simultaneous notes (one per instance), frozen stack
        - N pitches on mono: raises ValueError
        """
        if len(pitches) > 1:
            if name not in self._poly:
                raise ValueError(
                    f"'{name}' is not a poly voice — cannot play {len(pitches)} pitches"
                )
            pv = self._poly[name]
            if len(pitches) > pv.count:
                raise ValueError(
                    f"more pitches ({len(pitches)}) than voices ({pv.count}) for '{name}'"
                )
            atoms: list[Pattern] = []
            for pitch in pitches:
                inst = self._alloc_voice(name)
                atoms.append(build_note(inst, self._voices[inst].controls, pitch, vel=vel, **params))
            result = atoms[0]
            for a in atoms[1:]:
                result = result | a
            return _freeze(result)
        pitch = pitches[0] if pitches else None
        inst = self._alloc_voice(name)
        return build_note(inst, self._voices[inst].controls, pitch, vel=vel, **params)

    def play(self, name: str, pattern: Pattern) -> None:
        """Play a pattern on a named slot — delegates to the underlying Session."""
        self._session.play(name, pattern)

    def hit(self, name: str, param: str) -> Pattern:
        """Percussive trigger: trig + reset on a specific control.

        For poly voices, allocates the next instance (round-robin).
        """
        inst = self._alloc_voice(name)
        return build_hit(inst, param)

    def seq(self, name: str, *notes: float | None, **params: float) -> Pattern:
        """Build a Cat of steps/rests from a sequence of pitches.

        Each element is a float (pitch) or None (rest).
        For poly voices, allocates instances via round-robin per note.

        Usage::

            mix.seq("bass", 55, 73, None, 65)
        """
        if not notes:
            raise ValueError("seq requires at least one note")
        atoms: list[Pattern] = []
        for pitch in notes:
            if pitch is None:
                atoms.append(_rest())
            else:
                atoms.append(self.note(name, pitch, **params))
        result = atoms[0]
        for a in atoms[1:]:
            result = result + a
        return result

    def _alloc_voice(self, name: str) -> str:
        """Resolve a voice name to a concrete instance. For poly voices,
        returns the next instance via round-robin. For mono voices, returns name."""
        if name in self._poly:
            pv = self._poly[name]
            idx = self._poly_alloc[name] % pv.count
            self._poly_alloc[name] = idx + 1
            return f"{name}_v{idx}"
        if name not in self._voices:
            raise ValueError(f"voice '{name}' not found")
        return name

    def fade(
        self, name: str, target: float, bars: int = 4, steps_per_bar: int = 4
    ) -> None:
        """Smoothly fade voice gain over N bars using a midiman pattern.

        For poly voices, fades all instances proportionally.
        No Python threads needed — schedules gain changes through the pattern
        engine, synchronized to the beat grid.
        """
        if bars < 1 or steps_per_bar < 1:
            raise ValueError("bars and steps_per_bar must be >= 1")
        if name not in self._poly and name not in self._voices:
            raise ValueError(f"voice '{name}' not found")

        if name in self._poly:
            pv = self._poly[name]
            for i in range(pv.count):
                inst = f"{name}_v{i}"
                self._fade_voice(inst, target / pv.count, bars, steps_per_bar)
            # Update poly gain for bookkeeping
            self._poly[name] = PolyVoice(
                type_id=pv.type_id, count=pv.count, gain=target, controls=pv.controls,
            )
        else:
            self._fade_voice(name, target, bars, steps_per_bar)

    def _fade_voice(
        self, name: str, target: float, bars: int, steps_per_bar: int
    ) -> None:
        """Schedule a gain fade for a single voice instance."""
        self._session.hush(f"_fade_{name}")
        current = self._voices[name].gain
        total_steps = bars * steps_per_bar
        atoms: list[Pattern] = []
        for i in range(total_steps + 1):
            t = i / total_steps
            value = current + (target - current) * t
            atoms.append(_osc("/soundman/set", OscStr(f"{name}_gain"), OscFloat(value)))
        pattern = atoms[0]
        for a in atoms[1:]:
            pattern = pattern + a
        self._session.play(f"_fade_{name}", pattern.over(bars))
        old = self._voices[name]
        self._voices[name] = Voice(
            type_id=old.type_id, gain=target, controls=old.controls, init=old.init
        )

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
        ir = build_graph_ir(self._voices)
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
