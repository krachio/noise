from __future__ import annotations

import json
import socket
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from midiman_frontend.pattern import note
from midiman_frontend.session import Session


def _parse_sent(mock_sock: MagicMock) -> list[dict[str, Any]]:
    """Parse all newline-delimited JSON messages sent via sendall."""
    results: list[dict[str, Any]] = []
    for call in mock_sock.sendall.call_args_list:
        raw: bytes = call[0][0]
        for line in raw.decode().strip().split("\n"):
            if line:
                results.append(json.loads(line))
    return results


class TestSessionConnection:
    @patch("midiman_frontend.session.socket.socket")
    def test_connect_creates_unix_socket(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        mock_cls.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
        mock_cls.return_value.connect.assert_called_once_with("/tmp/midiman.sock")

    @patch("midiman_frontend.session.socket.socket")
    def test_env_var_override(self, mock_cls: MagicMock) -> None:
        with patch.dict("os.environ", {"MIDIMAN_SOCKET": "/tmp/custom.sock"}):
            s = Session()
        s.connect()
        mock_cls.return_value.connect.assert_called_once_with("/tmp/custom.sock")

    @patch("midiman_frontend.session.socket.socket")
    def test_context_manager(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            assert s is not None
        mock_cls.return_value.close.assert_called_once()

    @patch("midiman_frontend.session.socket.socket")
    def test_disconnect_closes_socket(self, mock_cls: MagicMock) -> None:
        s = Session()
        s.connect()
        s.disconnect()
        mock_cls.return_value.close.assert_called_once()


class TestSessionCommands:
    @patch("midiman_frontend.session.socket.socket")
    def test_set_tempo(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            s.tempo = 130.0
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m.get("cmd") == "SetBpm" and m.get("bpm") == 130.0 for m in msgs)

    @patch("midiman_frontend.session.socket.socket")
    def test_stop_all(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            s.stop()
        msgs = _parse_sent(mock_cls.return_value)
        assert any(m.get("cmd") == "HushAll" for m in msgs)


class TestTrackClipManagement:
    @patch("midiman_frontend.session.socket.socket")
    def test_single_clip_sends_set_pattern(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            drums["kick"] = note(36)
        msgs = _parse_sent(mock_cls.return_value)
        pattern_msgs = [m for m in msgs if m.get("cmd") == "SetPattern"]
        assert len(pattern_msgs) == 1
        assert pattern_msgs[0]["slot"] == "drums"
        assert pattern_msgs[0]["pattern"]["op"] == "Atom"

    @patch("midiman_frontend.session.socket.socket")
    def test_two_clips_sends_stack(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            drums["kick"] = note(36)
            drums["hats"] = note(42)
        msgs = _parse_sent(mock_cls.return_value)
        pattern_msgs = [m for m in msgs if m.get("cmd") == "SetPattern"]
        last = pattern_msgs[-1]
        assert last["pattern"]["op"] == "Stack"
        assert len(last["pattern"]["children"]) == 2

    @patch("midiman_frontend.session.socket.socket")
    def test_del_clip_with_remaining(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            drums["kick"] = note(36)
            drums["hats"] = note(42)
            del drums["hats"]
        msgs = _parse_sent(mock_cls.return_value)
        pattern_msgs = [m for m in msgs if m.get("cmd") == "SetPattern"]
        last = pattern_msgs[-1]
        assert last["pattern"]["op"] == "Atom"

    @patch("midiman_frontend.session.socket.socket")
    def test_del_last_clip_sends_hush(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            drums["kick"] = note(36)
            del drums["kick"]
        msgs = _parse_sent(mock_cls.return_value)
        hush_msgs = [m for m in msgs if m.get("cmd") == "Hush"]
        assert len(hush_msgs) == 1
        assert hush_msgs[0]["slot"] == "drums"

    @patch("midiman_frontend.session.socket.socket")
    def test_track_stop_clears_and_hushes(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            drums["kick"] = note(36)
            drums.stop()
        msgs = _parse_sent(mock_cls.return_value)
        hush_msgs = [m for m in msgs if m.get("cmd") == "Hush"]
        assert any(m["slot"] == "drums" for m in hush_msgs)

    @patch("midiman_frontend.session.socket.socket")
    def test_newline_delimited(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            s.stop()
        raw: bytes = mock_cls.return_value.sendall.call_args[0][0]
        assert raw.endswith(b"\n")

    @patch("midiman_frontend.session.socket.socket")
    def test_send_before_connect_raises(self, mock_cls: MagicMock) -> None:
        s = Session()
        with pytest.raises(RuntimeError):
            s.stop()
