"""VoiceMixer — named voices with stable control labels.

Manages FAUST DSP voices, per-voice gain, and the underlying soundman graph.
Control labels follow a deterministic convention: ``{voice_name}_{param}``.
Adding or removing a voice rebuilds the graph; gain updates are instant.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from faust_dsl import transpile as _transpile
from midiman_frontend.ir import OscFloat, OscStr
from midiman_frontend.pattern import Pattern
from midiman_frontend.pattern import osc as _osc
from soundman_frontend import Graph, GraphIr, SoundmanSession


@dataclass(frozen=True)
class Voice:
    """A named audio voice in the mix."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    init: tuple[tuple[str, float], ...] = ()


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
    """Build a melodic trigger atom: set freq + extra params + gate trig/reset."""
    atoms: list[Pattern] = []

    if pitch is not None and "freq" in controls:
        atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_freq"), OscFloat(pitch)))

    for param, value in params.items():
        if param in controls:
            atoms.append(
                _osc("/soundman/set", OscStr(f"{voice_name}_{param}"), OscFloat(value))
            )

    if "gate" in controls:
        atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_gate"), OscFloat(1.0)))
        atoms.append(_osc("/soundman/set", OscStr(f"{voice_name}_gate"), OscFloat(0.0)))

    if not atoms:
        raise ValueError(f"voice '{voice_name}' has no triggerable controls")

    result = atoms[0]
    for atom in atoms[1:]:
        result = result + atom
    return result


def build_hit(voice_name: str, param: str) -> Pattern:
    """Build a percussive trigger atom: trig + reset on a single control."""
    label = f"{voice_name}_{param}"
    return (
        _osc("/soundman/set", OscStr(label), OscFloat(1.0))
        + _osc("/soundman/set", OscStr(label), OscFloat(0.0))
    )


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
    ) -> None:
        self._session = session
        self._dsp_dir = dsp_dir
        self._node_controls: dict[str, tuple[str, ...]] = dict(node_controls or {})
        self._voices: dict[str, Voice] = {}

    def voice(
        self,
        name: str,
        source: str | Callable[..., Any],
        gain: float = 0.5,
        **init: float,
    ) -> None:
        """Add or replace a voice.  Rebuilds the graph.

        ``source`` is either a registered type_id string (e.g. ``"faust:kit"``)
        or a Python DSP function that will be transpiled to FAUST on the fly.
        """
        if callable(source):
            type_id = f"faust:{name}"
            result = _transpile(source)  # type: ignore[arg-type]
            self._dsp_dir.joinpath(f"{name}.dsp").write_text(result.source)
            controls = tuple(c.name for c in result.schema.controls)
            self._node_controls[type_id] = controls
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
        self._session.set(f"{name}_gain", value)

    def step(self, name: str, pitch: float | None = None, **params: float) -> Pattern:
        """Melodic trigger: set freq + optional params + gate trig/reset."""
        return build_step(name, self._voices[name].controls, pitch, **params)

    def hit(self, name: str, param: str) -> Pattern:
        """Percussive trigger: trig + reset on a specific control."""
        return build_hit(name, param)

    @property
    def voices(self) -> dict[str, Voice]:
        """Read-only snapshot of active voices."""
        return dict(self._voices)

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
