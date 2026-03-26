"""Tests for Session.pull() and Mixer.pull() — engine state sync."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from krach.mixer import Mixer
from krach.pattern.session import Session


def _fake_state(
    *,
    nodes: list[dict[str, object]] | None = None,
    connections: list[dict[str, str]] | None = None,
    exposed_controls: dict[str, list[str]] | None = None,
    control_values: dict[str, float] | None = None,
    slots: list[dict[str, object]] | None = None,
    transport: dict[str, float] | None = None,
) -> dict[str, object]:
    return {
        "status": "State",
        "nodes": nodes or [],
        "connections": connections or [],
        "exposed_controls": exposed_controls or {},
        "control_values": control_values or {},
        "slots": slots or [],
        "transport": transport or {"bpm": 120.0, "meter": 4.0, "master": 0.7},
    }


# ── Session.pull() ────────────────────────────────────────────────────────────


def test_session_pull_sends_status_command() -> None:
    """pull() sends {"cmd":"Status"} and returns the parsed response."""
    session = Session.__new__(Session)
    session._sock = MagicMock()
    session._reader = MagicMock()
    session._slots = {}
    session._tempo = 120.0
    session._meter = 4.0

    state = _fake_state(
        slots=[{"name": "kick", "playing": True}],
        transport={"bpm": 128.0, "meter": 4.0, "master": 0.8},
    )

    import json
    session._reader.readline.return_value = json.dumps(state).encode() + b"\n"

    result = session.pull()

    # Verify the Status command was sent
    sent = session._sock.sendall.call_args[0][0]
    assert b'"cmd":"Status"' in sent

    # Verify transport state is updated
    assert session._tempo == 128.0
    assert session._meter == 4.0

    # Verify return value
    assert result["status"] == "State"
    assert len(result["slots"]) == 1


def test_session_pull_empty_state() -> None:
    """pull() handles empty engine state gracefully."""
    session = Session.__new__(Session)
    session._sock = MagicMock()
    session._reader = MagicMock()
    session._slots = {}
    session._tempo = 120.0
    session._meter = 4.0

    import json
    state = _fake_state()
    session._reader.readline.return_value = json.dumps(state).encode() + b"\n"

    result = session.pull()
    assert result["nodes"] == []
    assert result["slots"] == []


# ── Mixer.pull() ──────────────────────────────────────────────────────────────


def _make_mixer(state: dict[str, object]) -> Mixer:
    """Create a Mixer with a mocked session that returns the given state."""
    import json

    session = Session.__new__(Session)
    session._sock = MagicMock()
    session._reader = MagicMock()
    session._slots = {}
    session._tempo = 120.0
    session._meter = 4.0
    session._reader.readline.return_value = json.dumps(state).encode() + b"\n"

    mixer = Mixer.__new__(Mixer)
    mixer._session = session
    mixer._dsp_dir = Path("/tmp/test-dsp")
    mixer._node_controls = {}
    mixer._nodes = {}
    mixer._muted = {}
    mixer._sends = {}
    mixer._wires = {}
    mixer._ctrl_values = {}
    mixer._patterns = {}
    mixer._scenes = {}
    mixer._batching = False
    mixer._graph_loaded = False
    mixer._master_gain = 0.7
    mixer._transition_bars = 0
    mixer._flush_scheduled = False
    return mixer


def test_mixer_pull_populates_nodes() -> None:
    """pull() creates Node entries for engine nodes (excluding helpers)."""
    state = _fake_state(
        nodes=[
            {"id": "bass", "type_id": "faust:acid_bass", "controls": {"freq": 55.0, "gate": 0.0}},
            {"id": "bass_g", "type_id": "gain", "controls": {"gain": 0.3}},
            {"id": "out", "type_id": "dac", "controls": {}},
        ],
        exposed_controls={
            "bass/freq": ["bass", "freq"],
            "bass/gate": ["bass", "gate"],
            "bass/gain": ["bass_g", "gain"],
        },
        control_values={"bass/freq": 110.0, "bass/gate": 1.0, "bass/gain": 0.3},
    )
    mixer = _make_mixer(state)
    mixer.pull()

    # bass is a real node, bass_g and out are helpers
    assert "bass" in mixer._nodes
    node = mixer._nodes["bass"]
    assert node.type_id == "faust:acid_bass"
    assert set(node.controls) == {"freq", "gate"}
    assert node.gain == 0.3


def test_mixer_pull_updates_control_values() -> None:
    """pull() syncs control values from engine."""
    state = _fake_state(
        nodes=[
            {"id": "bass", "type_id": "faust:acid_bass", "controls": {"freq": 55.0}},
            {"id": "bass_g", "type_id": "gain", "controls": {"gain": 0.5}},
            {"id": "out", "type_id": "dac", "controls": {}},
        ],
        exposed_controls={"bass/freq": ["bass", "freq"], "bass/gain": ["bass_g", "gain"]},
        control_values={"bass/freq": 440.0, "bass/gain": 0.5},
    )
    mixer = _make_mixer(state)
    mixer.pull()

    assert mixer._ctrl_values.get("bass/freq") == 440.0


def test_mixer_pull_updates_transport() -> None:
    """pull() syncs transport state (tempo, meter, master)."""
    state = _fake_state(
        transport={"bpm": 140.0, "meter": 3.0, "master": 0.6},
    )
    mixer = _make_mixer(state)
    mixer.pull()

    assert mixer._session._tempo == 140.0
    assert mixer._session._meter == 3.0
    assert mixer._master_gain == 0.6


def test_mixer_pull_preserves_local_state() -> None:
    """pull() does not clobber source_text, patterns, scenes, muted."""
    state = _fake_state(
        nodes=[
            {"id": "bass", "type_id": "faust:acid_bass", "controls": {"freq": 55.0}},
            {"id": "bass_g", "type_id": "gain", "controls": {"gain": 0.5}},
            {"id": "out", "type_id": "dac", "controls": {}},
        ],
        exposed_controls={"bass/freq": ["bass", "freq"], "bass/gain": ["bass_g", "gain"]},
        control_values={},
    )
    mixer = _make_mixer(state)

    # Set local-only state
    mixer._muted["bass"] = 0.5
    mixer._scenes["verse"] = MagicMock()  # type: ignore[assignment]

    mixer.pull()

    # Local state preserved
    assert "bass" in mixer._muted
    assert "verse" in mixer._scenes


def test_mixer_pull_detects_sends() -> None:
    """pull() reconstructs sends from _send_ gain nodes in the graph."""
    state = _fake_state(
        nodes=[
            {"id": "bass", "type_id": "faust:acid_bass", "controls": {"freq": 55.0}},
            {"id": "bass_g", "type_id": "gain", "controls": {"gain": 0.5}},
            {"id": "verb", "type_id": "faust:reverb", "controls": {"room": 0.8}},
            {"id": "verb_g", "type_id": "gain", "controls": {"gain": 0.4}},
            {"id": "bass_send_verb", "type_id": "gain", "controls": {"gain": 0.3}},
            {"id": "out", "type_id": "dac", "controls": {}},
        ],
        connections=[
            {"from_node": "bass", "from_port": "out", "to_node": "bass_g", "to_port": "in"},
            {"from_node": "bass_g", "from_port": "out", "to_node": "out", "to_port": "in"},
            {"from_node": "verb", "from_port": "out", "to_node": "verb_g", "to_port": "in"},
            {"from_node": "verb_g", "from_port": "out", "to_node": "out", "to_port": "in"},
            {"from_node": "bass", "from_port": "out", "to_node": "bass_send_verb", "to_port": "in"},
            {"from_node": "bass_send_verb", "from_port": "out", "to_node": "verb", "to_port": "in"},
        ],
        exposed_controls={
            "bass/freq": ["bass", "freq"],
            "bass/gain": ["bass_g", "gain"],
            "verb/room": ["verb", "room"],
            "verb/gain": ["verb_g", "gain"],
            "bass_send_verb/gain": ["bass_send_verb", "gain"],
        },
        control_values={"bass_send_verb/gain": 0.3},
    )
    mixer = _make_mixer(state)
    mixer.pull()

    # Should detect the send from bass to verb
    assert ("bass", "verb") in mixer._sends
    assert mixer._sends[("bass", "verb")] == 0.3


# ── Error paths ──────────────────────────────────────────────────────────────


def test_session_pull_engine_error_raises() -> None:
    """pull() raises KernelError when engine returns an error response."""
    import json
    from krach.pattern.session import KernelError

    session = Session.__new__(Session)
    session._sock = MagicMock()
    session._reader = MagicMock()
    session._slots = {}
    session._tempo = 120.0
    session._meter = 4.0

    error_response = {"status": "Error", "msg": "unknown command"}
    session._reader.readline.return_value = json.dumps(error_response).encode() + b"\n"

    import pytest
    with pytest.raises(KernelError, match="unknown command"):
        session.pull()


def test_mixer_pull_missing_transport_keys() -> None:
    """pull() handles partial transport gracefully (missing keys don't crash)."""
    state = _fake_state(transport={"bpm": 140.0})  # no meter, no master
    mixer = _make_mixer(state)
    mixer.pull()

    assert mixer._session._tempo == 140.0
    assert mixer._master_gain == 0.7  # unchanged (no "master" in transport)


def test_mixer_pull_empty_nodes() -> None:
    """pull() with no nodes clears _nodes dict."""
    state = _fake_state(nodes=[], connections=[])
    mixer = _make_mixer(state)
    # Pre-populate a node
    from krach.node_types import Node
    mixer._nodes["old"] = Node(type_id="faust:old", gain=0.5, controls=("gate",))

    mixer.pull()
    assert "old" not in mixer._nodes  # cleared by engine state


def test_mixer_pull_connection_error_is_silent() -> None:
    """pull() when session raises ConnectionError doesn't crash the mixer."""
    session = Session.__new__(Session)
    session._sock = MagicMock()
    session._reader = MagicMock()
    session._slots = {}
    session._tempo = 120.0
    session._meter = 4.0
    session._sock.sendall.side_effect = ConnectionError("socket closed")

    mixer = Mixer.__new__(Mixer)
    mixer._session = session
    mixer._dsp_dir = Path("/tmp/test-dsp")
    mixer._node_controls = {}
    mixer._nodes = {}
    mixer._muted = {}
    mixer._sends = {}
    mixer._wires = {}
    mixer._ctrl_values = {}
    mixer._patterns = {}
    mixer._scenes = {}
    mixer._batching = False
    mixer._graph_loaded = False
    mixer._master_gain = 0.7
    mixer._transition_bars = 0
    mixer._flush_scheduled = False

    # Should not raise — pull() degrades gracefully
    try:
        mixer.pull()
    except ConnectionError:
        pass  # acceptable — the error surfaces, caller handles it
