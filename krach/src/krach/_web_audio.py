# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Web Audio bridge for browser-based krach sessions.

Replaces the native Unix-socket Session with a Web Audio API backend.
Used by JupyterLite/Pyodide REPL. Synthesis uses built-in Web Audio
oscillators and gain nodes — no FAUST JIT in the browser.

Usage (in Pyodide):
    from krach._web_audio import WebSession
    from krach._mixer import VoiceMixer
    session = WebSession()
    kr = VoiceMixer(session=session, dsp_dir=Path("/tmp"))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krach.patterns.ir import ir_to_dict
from krach.patterns.pattern import Pattern


@dataclass
class SlotState:
    """Minimal slot state for the web session."""

    pattern: Pattern
    playing: bool = True


class WebSession:
    """Web Audio session — drop-in replacement for the native Session.

    Implements the same interface that VoiceMixer expects from Session,
    but routes audio to the Web Audio API via Pyodide's JS FFI instead
    of a Unix socket to krach-engine.
    """

    def __init__(self) -> None:
        self._tempo: float = 120.0
        self._meter: float = 4.0
        self._slots: dict[str, SlotState] = {}
        self._js_bridge: Any = None  # Set by connect_web()

    def connect(self) -> None:
        """Initialize Web Audio context (called from Pyodide)."""
        try:
            from js import AudioContext  # type: ignore[import-not-found]  # noqa: F401

            self._js_bridge = _create_web_audio_bridge()
        except ImportError:
            # Not in Pyodide — stub for testing
            pass

    @property
    def tempo(self) -> float:
        return self._tempo

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self._tempo = bpm

    @property
    def meter(self) -> float:
        return self._meter

    @meter.setter
    def meter(self, beats: float) -> None:
        self._meter = beats

    @property
    def slots(self) -> dict[str, Any]:
        return {k: v for k, v in self._slots.items()}

    def play(self, slot: str, pattern: Pattern) -> None:
        """Play a pattern on a slot."""
        self._slots[slot] = SlotState(pattern=pattern, playing=True)
        self._dispatch_pattern(slot, pattern)

    def play_from_zero(self, slot: str, pattern: Pattern) -> None:
        """Play a pattern from phase zero."""
        self.play(slot, pattern)

    def hush(self, slot: str) -> None:
        """Stop a slot."""
        if slot in self._slots:
            self._slots[slot].playing = False

    def hush_all(self) -> None:
        """Stop all slots."""
        for state in self._slots.values():
            state.playing = False

    def master_gain(self, value: float) -> None:
        """Set master output gain."""
        if self._js_bridge:
            self._js_bridge.set_master_gain(value)

    def set_ctrl(self, label: str, value: float) -> None:
        """Set a control parameter directly."""
        if self._js_bridge:
            self._js_bridge.set_control(label, value)

    def add_voice(
        self,
        name: str,
        type_id: str,
        controls: tuple[str, ...],
        gain: float,
    ) -> None:
        """Register a voice with the Web Audio backend."""
        if self._js_bridge:
            self._js_bridge.add_voice(name, type_id, list(controls), gain)

    def midi_map(
        self,
        channel: int,
        cc: int,
        label: str,
        lo: float,
        hi: float,
    ) -> None:
        """MIDI mapping — no-op in browser (no MIDI support yet)."""

    def start_input(self, channel: int = 0) -> None:
        """ADC input — no-op in browser."""

    def _send_json(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Send JSON to the web bridge (replaces Unix socket send)."""
        if self._js_bridge:
            self._js_bridge.send_json(json.dumps(obj))
        return {"status": "ok"}

    def _dispatch_pattern(self, slot: str, pattern: Pattern) -> None:
        """Send pattern IR to the web bridge for scheduling."""
        ir_dict = ir_to_dict(pattern.node)
        if self._js_bridge:
            self._js_bridge.set_pattern(slot, json.dumps(ir_dict))


def _create_web_audio_bridge() -> object | None:
    """Create the JavaScript Web Audio bridge via Pyodide FFI.

    Returns a JS object with methods: set_pattern, set_control,
    set_master_gain, add_voice, send_json.
    """
    try:
        from pyodide.code import run_js  # type: ignore[import-not-found]

        raw = run_js(  # type: ignore[import-not-found]
            """
        (() => {
            const ctx = new AudioContext();
            const master = ctx.createGain();
            master.gain.value = 0.7;
            master.connect(ctx.destination);

            const voices = {};

            return {
                set_master_gain(v) { master.gain.value = v; },
                set_control(label, value) {
                    const [voice, param] = label.split('/');
                    if (voices[voice] && voices[voice].params[param]) {
                        voices[voice].params[param].value = value;
                    }
                },
                add_voice(name, typeId, controls, gain) {
                    const osc = ctx.createOscillator();
                    const g = ctx.createGain();
                    g.gain.value = 0;
                    osc.connect(g);
                    g.connect(master);
                    osc.start();
                    voices[name] = {
                        osc, gain: g,
                        params: {
                            freq: osc.frequency,
                            gate: g.gain,
                            gain: g.gain,
                        }
                    };
                },
                set_pattern(slot, irJson) {
                    // Pattern scheduling handled by Python-side timer
                },
                send_json(json) {}
            };
        })()
        """)
        bridge: object = raw  # type: ignore[assignment]
        return bridge
    except ImportError:
        return None


def connect_web(bpm: float = 120, master: float = 0.7) -> Any:
    """Create a browser-based krach session.

    Returns a VoiceMixer connected to Web Audio.
    Use this instead of ``krach.connect()`` in JupyterLite/Pyodide.
    """
    from krach._mixer import VoiceMixer

    session = WebSession()
    session.connect()
    session.tempo = bpm
    kr = VoiceMixer(session=session, dsp_dir=Path("/tmp/krach-web/dsp"))  # type: ignore[arg-type]
    kr.master = master
    return kr
