# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Web Audio session — browser backend for krach.

Subclasses Session, overriding only the transport layer.
Pattern slot management (play/hush/tempo/meter) is inherited.
Audio commands (load_graph/set_ctrl/etc.) route to Web Audio via Pyodide JS FFI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from krach.patterns.graph import GraphIr
from krach.patterns.ir import ir_to_dict
from krach.patterns.pattern import Pattern
from krach.patterns.session import Session, SlotState


class WebSession(Session):
    """Browser-based session using Web Audio API.

    Inherits all slot management from Session. Overrides the transport:
    - ``send()`` is a no-op (no Unix socket)
    - ``_send_json()`` is a no-op (no Unix socket)
    - Audio commands delegate to Web Audio via JS FFI
    """

    def __init__(self) -> None:
        # Skip Session.__init__ (it sets up socket fields we don't need)
        self._slots: dict[str, SlotState] = {}
        self._tempo: float = 120.0
        self._meter: float = 4.0
        self._js_bridge: Any = None

    # ── Transport override (no socket) ──────────────────────────────

    def connect(self) -> None:
        """Initialize Web Audio context."""
        self._js_bridge = _create_web_audio_bridge()

    def disconnect(self) -> None:
        """No-op in browser."""

    def send(self, msg: object) -> None:  # type: ignore[override]
        """Pattern commands — route Hush/HushAll to JS bridge."""
        from krach.patterns.ir import Hush, HushAll
        if isinstance(msg, Hush) and self._js_bridge:
            self._js_bridge.stop_slot(msg.slot)
        elif isinstance(msg, HushAll) and self._js_bridge:
            self._js_bridge.stop_all()

    def _send_json(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Audio commands — route to Web Audio bridge."""
        msg_type = obj.get("type", "")
        if msg_type == "set_control" and self._js_bridge:
            self._js_bridge.set_control(obj["label"], obj["value"])
        elif msg_type == "set_master_gain" and self._js_bridge:
            self._js_bridge.set_master_gain(obj["gain"])
        elif msg_type == "load_graph":
            pass  # Voices created individually via add_voice
        return {"status": "ok"}

    # ── Audio commands (Web Audio equivalents) ──────────────────────

    def load_graph(self, graph: GraphIr) -> None:
        """In browser, voices are created individually — graph rebuild is no-op."""

    def add_voice(
        self, name: str, type_id: str, controls: tuple[str, ...], gain: float,
    ) -> None:
        """Create a Web Audio voice (oscillator + gain node)."""
        if self._js_bridge:
            self._js_bridge.add_voice(name, type_id, list(controls), gain)

    def set_ctrl(self, label: str, value: float) -> None:
        """Set a Web Audio parameter."""
        if self._js_bridge:
            self._js_bridge.set_control(label, value)

    def master_gain(self, value: float) -> None:
        """Set master output gain."""
        if self._js_bridge:
            self._js_bridge.set_master_gain(value)

    def list_nodes(self) -> list[str]:
        """No pre-registered node types in browser."""
        return []

    def set_automation(
        self, label: str, shape: str, lo: float, hi: float,
        period_secs: float, one_shot: bool = False,
    ) -> None:
        """Automation — not yet implemented in browser."""

    def clear_automation(self, id: str) -> None:
        """Clear automation — not yet implemented in browser."""

    def start_input(self, channel: int = 0) -> None:
        """ADC input — not available in browser."""

    def midi_map(
        self, channel: int, cc: int, label: str, lo: float, hi: float,
    ) -> None:
        """MIDI mapping — not available in browser."""

    def ping(self) -> None:
        """No-op in browser."""

    # ── Pattern dispatch (Web Audio scheduling) ─────────────────────

    def play(self, slot: str, pattern: Pattern) -> None:
        """Play a pattern — bookkeep + schedule via Web Audio."""
        self._slots[slot] = SlotState(pattern=pattern, playing=True)
        self._dispatch_pattern(slot, pattern)

    def play_from_zero(self, slot: str, pattern: Pattern) -> None:
        """Play from phase zero."""
        self.play(slot, pattern)

    def _dispatch_pattern(self, slot: str, pattern: Pattern) -> None:
        """Evaluate pattern and schedule via Web Audio."""
        ir_dict = ir_to_dict(pattern.node)
        ir_json = json.dumps(ir_dict)
        if self._js_bridge:
            cycle_secs = self._meter * 60.0 / max(self._tempo, 1.0)
            self._js_bridge.schedule_pattern(slot, ir_json, cycle_secs)


def _create_web_audio_bridge() -> object | None:
    """Create the JavaScript Web Audio bridge via Pyodide FFI."""
    try:
        from pyodide.code import run_js  # type: ignore[import-not-found]

        bridge = run_js(  # type: ignore[no-untyped-call]
            """
        (() => {
            const ctx = new AudioContext();
            const master = ctx.createGain();
            master.gain.value = 0.7;
            master.connect(ctx.destination);

            const voices = {};
            const schedulers = {};

            return {
                set_master_gain(v) { master.gain.value = v; },
                set_control(label, value) {
                    const parts = label.split('/');
                    if (parts.length < 2) return;
                    const [voice, param] = parts;
                    if (voices[voice] && voices[voice].params[param]) {
                        voices[voice].params[param].setValueAtTime(value, ctx.currentTime);
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
                        params: { freq: osc.frequency, gate: g.gain }
                    };
                },
                schedule_pattern(slot, irJson, cycleSecs) {
                    if (schedulers[slot]) clearInterval(schedulers[slot]);
                    const ir = JSON.parse(irJson);
                    const events = [];
                    function walk(node, s, e) {
                        if (!node) return;
                        if (node.op === 'Atom' && node.value && node.value.type === 'Control')
                            events.push({t: s, label: node.value.label, value: node.value.value});
                        else if (node.op === 'Cat' && node.children) {
                            const n = node.children.length, d = (e - s) / n;
                            node.children.forEach((c, i) => walk(c, s + i*d, s + (i+1)*d));
                        } else if (node.op === 'Stack' && node.children)
                            node.children.forEach(c => walk(c, s, e));
                        else if (node.op === 'Freeze' && node.child) walk(node.child, s, e);
                        else if (node.op === 'Fast' && node.child && node.factor) {
                            const f = node.factor[0] / node.factor[1], d = (e - s) / f;
                            for (let i = 0; i < f; i++) walk(node.child, s + i*d, s + (i+1)*d);
                        } else if (node.child) walk(node.child, s, e);
                    }
                    walk(ir, 0, 1);
                    events.sort((a, b) => a.t - b.t);
                    let cycleStart = ctx.currentTime;
                    function tick() {
                        events.forEach(ev => {
                            const t = cycleStart + ev.t * cycleSecs;
                            const p = ev.label.split('/');
                            if (p.length >= 2 && voices[p[0]] && voices[p[0]].params[p[1]])
                                voices[p[0]].params[p[1]].setValueAtTime(ev.value, t);
                        });
                        cycleStart += cycleSecs;
                    }
                    tick();
                    schedulers[slot] = setInterval(tick, cycleSecs * 800);
                },
                stop_slot(slot) {
                    if (schedulers[slot]) {
                        clearInterval(schedulers[slot]);
                        delete schedulers[slot];
                    }
                    // Silence the voice's gain
                    const parts = slot.split('/');
                    const name = parts[0] || slot;
                    if (voices[name]) {
                        voices[name].gain.gain.cancelScheduledValues(ctx.currentTime);
                        voices[name].gain.gain.setValueAtTime(0, ctx.currentTime);
                    }
                },
                stop_all() {
                    for (const slot of Object.keys(schedulers)) {
                        clearInterval(schedulers[slot]);
                    }
                    for (const name of Object.keys(voices)) {
                        voices[name].gain.gain.cancelScheduledValues(ctx.currentTime);
                        voices[name].gain.gain.setValueAtTime(0, ctx.currentTime);
                    }
                    Object.keys(schedulers).forEach(k => delete schedulers[k]);
                },
                send_json(json) {}
            };
        })()
        """)
        return bridge  # type: ignore[no-any-return]
    except ImportError:
        return None


def connect_web(bpm: float = 120, master: float = 0.7) -> Any:
    """Create a browser-based krach session.

    Returns a VoiceMixer connected to Web Audio.
    """
    from krach._mixer import VoiceMixer

    session = WebSession()
    session.connect()
    session.tempo = bpm
    import tempfile
    dsp_dir = Path(tempfile.gettempdir()) / "krach-web" / "dsp"
    dsp_dir.mkdir(parents=True, exist_ok=True)
    kr = VoiceMixer(session=session, dsp_dir=dsp_dir)  # type: ignore[arg-type]
    kr.master = master
    return kr
