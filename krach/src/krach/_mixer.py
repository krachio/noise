"""VoiceMixer — named voices with stable control labels.

Manages FAUST DSP voices, per-voice gain, and the underlying soundman graph.
Control labels follow a deterministic convention: ``{voice_name}_{param}``.
Adding or removing a voice rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

import inspect
import textwrap
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from faust_dsl import transpile as _transpile
from midiman_frontend.ir import OscFloat, OscStr
from midiman_frontend.pattern import Pattern
from midiman_frontend.pattern import freeze as _freeze
from midiman_frontend.pattern import osc as _osc
from soundman_frontend import Graph, GraphIr, SoundmanSession


@dataclass(frozen=True)
class Voice:
    """A named audio voice in the mix."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    init: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    controls: tuple[str, ...]


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
    )


# ── Pure builders (testable without I/O) ──────────────────────────────────────


def build_graph_ir(voices: dict[str, Voice]) -> GraphIr:
    """Build a complete soundman graph IR from the voice set.

    Each voice gets: DSP node → gain node → DAC.
    Controls exposed as ``{name}_{param}``.  Gain exposed as ``{name}_gain``.
    """
    builder = Graph()
    builder.node("out", "dac")

    for name, voice in voices.items():
        builder.node(name, voice.type_id, **dict(voice.init))
        builder.node(f"{name}_g", "gain", gain=voice.gain)
        builder.connect(name, "out", f"{name}_g", "in")
        builder.connect(f"{name}_g", "out", "out", "in")

        for param in voice.controls:
            builder.expose(f"{name}_{param}", name, param)
        builder.expose(f"{name}_gain", f"{name}_g", "gain")

    return builder.build()


def build_step(
    voice_name: str,
    controls: tuple[str, ...],
    pitch: float | None = None,
    **params: float,
) -> Pattern:
    """Build a frozen trigger compound: onset values stacked + reset sequenced.

    Uses ``Freeze(Cat([onset_stack, reset]))`` so this counts as ONE atom
    for cycle division (Freeze prevents Cat flattening). The trigger fires
    at the first half, reset at the second half, leaving a gap before the
    next atom's onset for FAUST to detect the rising edge.
    """
    onset_atoms: list[Pattern] = []

    if pitch is not None and "freq" in controls:
        onset_atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_freq"), OscFloat(pitch)))

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
        # Cat([onset, reset]) = trig at first half, reset at second half
        # Freeze prevents flatten — counts as 1 atom in any outer Cat
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
        session: SoundmanSession,
        dsp_dir: Path,
        node_controls: dict[str, tuple[str, ...]] | None = None,
        mm: Any = None,
    ) -> None:
        self._session = session
        self._dsp_dir = dsp_dir
        self._node_controls: dict[str, tuple[str, ...]] = dict(node_controls or {})
        self._voices: dict[str, Voice] = {}
        self._batching: bool = False
        self._mm: Any = mm  # midiman Session, optional (needed for fade)

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
        if isinstance(source, DspDef):
            type_id = f"faust:{name}"
            self._dsp_dir.joinpath(f"{name}.py").write_text(source.source)
            self._dsp_dir.joinpath(f"{name}.dsp").write_text(source.faust)
            controls = source.controls
            self._node_controls[type_id] = controls
            if not self._batching:
                self._wait_for_type(type_id)
        elif callable(source):
            type_id = f"faust:{name}"
            result = _transpile(source)  # type: ignore[arg-type]
            self._dsp_dir.joinpath(f"{name}.dsp").write_text(result.source)
            controls = tuple(c.name for c in result.schema.controls)
            self._node_controls[type_id] = controls
            if not self._batching:
                self._wait_for_type(type_id)
        else:
            type_id = source
            controls = self._node_controls.get(type_id, tuple(init.keys()))

        self._voices[name] = Voice(
            type_id=type_id,
            gain=gain,
            controls=controls,
            init=tuple(init.items()),
        )
        if not self._batching:
            self._rebuild()

    def remove(self, name: str) -> None:
        """Remove a voice.  Rebuilds the graph."""
        del self._voices[name]
        self._rebuild()

    def gain(self, name: str, value: float) -> None:
        """Update a voice's gain.  Instant — no graph rebuild."""
        old = self._voices[name]
        self._voices[name] = Voice(
            type_id=old.type_id, gain=value, controls=old.controls, init=old.init
        )
        self._session.set(f"{name}_gain", float(value))

    def step(self, name: str, pitch: float | None = None, **params: float) -> Pattern:
        """Melodic trigger: set freq + optional params + gate trig/reset."""
        return build_step(name, self._voices[name].controls, pitch, **params)

    def hit(self, name: str, param: str) -> Pattern:
        """Percussive trigger: trig + reset on a specific control."""
        return build_hit(name, param)

    def fade(
        self, name: str, target: float, bars: int = 4, steps_per_bar: int = 4
    ) -> None:
        """Smoothly fade voice gain over N bars using a midiman pattern.

        No Python threads needed — schedules gain changes through the pattern
        engine, synchronized to the beat grid.
        """
        if self._mm is None:
            raise RuntimeError("fade() requires mm (midiman Session) — pass mm= to VoiceMixer")
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
        self._mm.play(f"_fade_{name}", pattern.over(bars))
        # Update stored gain to target (will be reached at end of fade)
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
        try:
            yield
        finally:
            self._batching = False
            self._flush()

    @property
    def voices(self) -> dict[str, Voice]:
        """Read-only snapshot of active voices."""
        return dict(self._voices)

    def _flush(self) -> None:
        """Wait for all pending FAUST types and rebuild the graph once."""
        for voice in self._voices.values():
            if voice.type_id.startswith("faust:"):
                self._wait_for_type(voice.type_id)
        self._rebuild()

    def _rebuild(self) -> None:
        ir = build_graph_ir(self._voices)
        self._session.load_graph(ir)

    def _wait_for_type(self, type_id: str) -> None:
        """Poll until soundman has loaded the given FAUST type."""
        import time

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                if type_id in self._session.list_nodes(timeout=0.5):
                    return
            except TimeoutError:
                pass
            time.sleep(0.1)
