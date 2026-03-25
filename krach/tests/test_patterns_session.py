from __future__ import annotations

import json
import socket
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from krach.pattern.pattern import note
from krach.pattern.session import Session, SlotState


def _stub_ok_response(mock_cls: MagicMock) -> None:
    ok = json.dumps({"status": "Ok", "msg": "ok"}).encode() + b"\n"
    mock_cls.return_value.makefile.return_value.readline.return_value = ok


def _parse_sent(mock_sock: MagicMock) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in mock_sock.sendall.call_args_list:
        raw: bytes = call[0][0]
        for line in raw.decode().strip().split("\n"):
            if line:
                results.append(json.loads(line))
    return results


class TestSessionConnection:
    @patch("krach.pattern.session.socket.socket")
    def test_connect_creates_unix_socket(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        mock_cls.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
        import tempfile
        from pathlib import Path as P
        expected = str(P(tempfile.gettempdir()) / "krach-engine.sock")
        mock_cls.return_value.connect.assert_called_once_with(expected)

    @patch("krach.pattern.session.socket.socket")
    def test_env_var_override(self, mock_cls: MagicMock) -> None:
        with patch.dict("os.environ", {"NOISE_SOCKET": "/tmp/custom.sock"}):
            s = Session()
        s.connect()
        mock_cls.return_value.connect.assert_called_once_with("/tmp/custom.sock")

    @patch("krach.pattern.session.socket.socket")
    def test_context_manager(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            assert s is not None
        mock_cls.return_value.close.assert_called_once()

    @patch("krach.pattern.session.socket.socket")
    def test_disconnect_closes_socket_and_reader(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        s.disconnect()
        mock_cls.return_value.makefile.return_value.close.assert_called_once()
        mock_cls.return_value.close.assert_called_once()


class TestPlay:
    @patch("krach.pattern.session.socket.socket")
    def test_play_sends_set_pattern(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
        msgs = _parse_sent(mock_cls.return_value)
        pat_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        assert len(pat_msgs) == 1
        assert pat_msgs[0]["slot"] == "drums"
        assert pat_msgs[0]["pattern"]["op"] == "Atom"

    @patch("krach.pattern.session.socket.socket")
    def test_play_tracks_slot_state(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        pat = note(36)
        with Session() as s:
            s.play("drums", pat)
            state = s.slots["drums"]
            assert state.pattern == pat
            assert state.playing is True

    @patch("krach.pattern.session.socket.socket")
    def test_play_replaces_existing_pattern(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.play("drums", note(38))
            assert s.slots["drums"].pattern == note(38)

    @patch("krach.pattern.session.socket.socket")
    def test_play_on_hushed_slot_resumes(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.hush("drums")
            s.play("drums", note(38))
            assert s.slots["drums"].playing is True


class TestHush:
    @patch("krach.pattern.session.socket.socket")
    def test_hush_sends_hush_command(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.hush("drums")
        msgs = _parse_sent(mock_cls.return_value)
        hush_msgs = [m for m in msgs if m["cmd"] == "Hush"]
        assert len(hush_msgs) == 1
        assert hush_msgs[0]["slot"] == "drums"

    @patch("krach.pattern.session.socket.socket")
    def test_hush_keeps_pattern_stopped(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        pat = note(36)
        with Session() as s:
            s.play("drums", pat)
            s.hush("drums")
            state = s.slots["drums"]
            assert state.pattern == pat
            assert state.playing is False

    @patch("krach.pattern.session.socket.socket")
    def test_hush_unknown_slot_no_error(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.hush("nonexistent")
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m["cmd"] == "Hush" and m["slot"] == "nonexistent" for m in msgs)


class TestResume:
    @patch("krach.pattern.session.socket.socket")
    def test_resume_sends_set_pattern(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.hush("drums")
            s.resume("drums")
        msgs = _parse_sent(mock_cls.return_value)
        pat_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        assert len(pat_msgs) == 2  # initial play + resume

    @patch("krach.pattern.session.socket.socket")
    def test_resume_sets_playing_true(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.hush("drums")
            s.resume("drums")
            assert s.slots["drums"].playing is True

    @patch("krach.pattern.session.socket.socket")
    def test_resume_unknown_slot_raises(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            with pytest.raises(KeyError):
                s.resume("nonexistent")

    @patch("krach.pattern.session.socket.socket")
    def test_resume_already_playing_is_noop(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.resume("drums")
        msgs = _parse_sent(mock_cls.return_value)
        pat_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        assert len(pat_msgs) == 1  # only the initial play


class TestRemove:
    @patch("krach.pattern.session.socket.socket")
    def test_remove_sends_hush(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.remove("drums")
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m["cmd"] == "Hush" and m["slot"] == "drums" for m in msgs)

    @patch("krach.pattern.session.socket.socket")
    def test_remove_deletes_from_slots(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.remove("drums")
            assert "drums" not in s.slots

    @patch("krach.pattern.session.socket.socket")
    def test_remove_unknown_slot_no_error(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.remove("nonexistent")


class TestStop:
    @patch("krach.pattern.session.socket.socket")
    def test_stop_sends_hush_all(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.stop()
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m["cmd"] == "HushAll" for m in msgs)

    @patch("krach.pattern.session.socket.socket")
    def test_stop_marks_all_stopped(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.play("melody", note(60))
            s.stop()
            assert all(not st.playing for st in s.slots.values())
            assert "drums" in s.slots
            assert "melody" in s.slots


class TestLaunch:
    @patch("krach.pattern.session.socket.socket")
    def test_launch_sends_batch(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.launch({"drums": note(36), "melody": note(60)})
        msgs = _parse_sent(mock_cls.return_value)
        batch_msgs = [m for m in msgs if m["cmd"] == "Batch"]
        assert len(batch_msgs) == 1
        cmds = batch_msgs[0]["commands"]
        assert len(cmds) == 2
        slots = {c["slot"] for c in cmds}
        assert slots == {"drums", "melody"}
        assert all(c["cmd"] == "SetPattern" for c in cmds)

    @patch("krach.pattern.session.socket.socket")
    def test_launch_tracks_slot_states(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.launch({"drums": note(36), "melody": note(60)})
            assert s.slots["drums"].playing is True
            assert s.slots["melody"].playing is True
            assert s.slots["drums"].pattern == note(36)
            assert s.slots["melody"].pattern == note(60)

    @patch("krach.pattern.session.socket.socket")
    def test_launch_replaces_existing_slots(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            s.launch({"drums": note(38), "bass": note(24)})
            assert s.slots["drums"].pattern == note(38)
            assert s.slots["bass"].pattern == note(24)


class TestTempo:
    @patch("krach.pattern.session.socket.socket")
    def test_set_tempo_sends_bpm(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.tempo = 140.0
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m["cmd"] == "SetBpm" and m["bpm"] == 140.0 for m in msgs)

    @patch("krach.pattern.session.socket.socket")
    def test_tempo_readable(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.tempo = 140.0
            assert s.tempo == 140.0


class TestPlayFromZero:
    @patch("krach.pattern.session.socket.socket")
    def test_play_from_zero_sends_correct_command(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play_from_zero("mod_slot", note(60))
        msgs = _parse_sent(mock_cls.return_value)
        pat_msgs = [m for m in msgs if m["cmd"] == "SetPatternFromZero"]
        assert len(pat_msgs) == 1
        assert pat_msgs[0]["slot"] == "mod_slot"
        assert pat_msgs[0]["pattern"]["op"] == "Atom"

    @patch("krach.pattern.session.socket.socket")
    def test_play_from_zero_tracks_slot_state(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        pat = note(60)
        with Session() as s:
            s.play_from_zero("mod_slot", pat)
            state = s.slots["mod_slot"]
            assert state.pattern == pat
            assert state.playing is True


class TestSlotStateImmutable:
    def test_slot_state_is_frozen(self) -> None:
        state = SlotState(pattern=note(36), playing=True)
        with pytest.raises(AttributeError):
            state.playing = False  # type: ignore[misc]


class TestSlotsReadOnly:
    @patch("krach.pattern.session.socket.socket")
    def test_slots_returns_copy(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
            slots = s.slots
            slots.pop("drums")  # mutate the copy
            assert "drums" in s.slots  # original unchanged


class TestSendBeforeConnect:
    @patch("krach.pattern.session.socket.socket")
    def test_play_before_connect_raises(self, mock_cls: MagicMock) -> None:
        s = Session()
        with pytest.raises(RuntimeError):
            s.play("drums", note(36))


class TestSocketTimeout:
    @patch("krach.pattern.session.socket.socket")
    def test_connect_sets_timeout(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        mock_cls.return_value.settimeout.assert_called_once_with(5.0)

    @patch("krach.pattern.session.socket.socket")
    def test_send_catches_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        mock_cls.return_value.sendall.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.ping()

    @patch("krach.pattern.session.socket.socket")
    def test_readline_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        mock_cls.return_value.makefile.return_value.readline.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.ping()


class TestNewlineDelimited:
    @patch("krach.pattern.session.socket.socket")
    def test_messages_end_with_newline(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.play("drums", note(36))
        raw: bytes = mock_cls.return_value.sendall.call_args[0][0]
        assert raw.endswith(b"\n")


class TestLoadGraphTimeout:
    @patch("krach.pattern.session.socket.socket")
    def test_load_graph_sendall_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        """BUG: load_graph() does not catch socket.timeout.
        send() and _send_json() both catch it, but load_graph() has its own
        raw sendall() call (line 168) with no try/except. A timeout during
        graph load produces a bare socket.timeout instead of ConnectionError.

        Root cause: session.py:160-169 — load_graph uses raw socket ops
        without the timeout-catching wrapper used by send() and _send_json().
        """
        from krach.pattern.graph import Graph

        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()

        # Build a minimal graph IR
        g = Graph()
        g.node("out", "dac")
        ir = g.build()

        mock_cls.return_value.sendall.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.load_graph(ir)

    @patch("krach.pattern.session.socket.socket")
    def test_load_graph_readline_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        """BUG: load_graph() readline does not catch socket.timeout."""
        from krach.pattern.graph import Graph

        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()

        g = Graph()
        g.node("out", "dac")
        ir = g.build()

        # sendall succeeds, but readline times out
        mock_cls.return_value.makefile.return_value.readline.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.load_graph(ir)


class TestSendJsonTimeout:
    @patch("krach.pattern.session.socket.socket")
    def test_send_json_sendall_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        """_send_json must catch socket.timeout and raise ConnectionError."""
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        mock_cls.return_value.sendall.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.set_ctrl("bass_gain", 0.5)

    @patch("krach.pattern.session.socket.socket")
    def test_send_json_readline_timeout_raises_connection_error(self, mock_cls: MagicMock) -> None:
        """_send_json readline timeout must raise ConnectionError."""
        s = Session()
        s.connect()
        mock_cls.return_value.makefile.return_value.readline.side_effect = socket.timeout("timed out")
        with pytest.raises(ConnectionError, match="engine"):
            s.set_ctrl("bass_gain", 0.5)


class TestSetAutomation:
    @patch("krach.pattern.session.socket.socket")
    def test_set_automation_sends_json(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.set_automation("bass/cutoff", "sine", 200.0, 2000.0, 2.0)
        msgs = _parse_sent(mock_cls.return_value)
        auto_msgs = [m for m in msgs if m.get("type") == "set_automation"]
        assert len(auto_msgs) == 1
        msg = auto_msgs[0]
        assert msg["id"] == "bass/cutoff"
        assert msg["label"] == "bass/cutoff"
        assert msg["shape"] == "sine"
        assert msg["lo"] == 200.0
        assert msg["hi"] == 2000.0
        assert msg["period_secs"] == 2.0
        assert msg["one_shot"] is False

    @patch("krach.pattern.session.socket.socket")
    def test_set_automation_one_shot(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.set_automation("bass/gain", "ramp", 0.0, 1.0, 4.0, one_shot=True)
        msgs = _parse_sent(mock_cls.return_value)
        auto_msgs = [m for m in msgs if m.get("type") == "set_automation"]
        assert auto_msgs[0]["one_shot"] is True

    @patch("krach.pattern.session.socket.socket")
    def test_clear_automation_sends_json(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.clear_automation("bass/cutoff")
        msgs = _parse_sent(mock_cls.return_value)
        clear_msgs = [m for m in msgs if m.get("type") == "clear_automation"]
        assert len(clear_msgs) == 1
        assert clear_msgs[0]["id"] == "bass/cutoff"


class TestStartInput:
    @patch("krach.pattern.session.socket.socket")
    def test_start_input_sends_json(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.start_input(channel=1)
        msgs = _parse_sent(mock_cls.return_value)
        input_msgs = [m for m in msgs if m.get("type") == "start_input"]
        assert len(input_msgs) == 1
        assert input_msgs[0]["channel"] == 1

    @patch("krach.pattern.session.socket.socket")
    def test_start_input_default_channel(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.start_input()
        msgs = _parse_sent(mock_cls.return_value)
        input_msgs = [m for m in msgs if m.get("type") == "start_input"]
        assert len(input_msgs) == 1
        assert input_msgs[0]["channel"] == 0


class TestMidiMap:
    @patch("krach.pattern.session.socket.socket")
    def test_midi_map_sends_json(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        s = Session()
        s.connect()
        s.midi_map(channel=0, cc=74, label="bass/cutoff", lo=200.0, hi=4000.0)
        msgs = _parse_sent(mock_cls.return_value)
        map_msgs = [m for m in msgs if m.get("type") == "midi_map"]
        assert len(map_msgs) == 1
        msg = map_msgs[0]
        assert msg["channel"] == 0
        assert msg["cc"] == 74
        assert msg["label"] == "bass/cutoff"
        assert msg["lo"] == 200.0
        assert msg["hi"] == 4000.0
