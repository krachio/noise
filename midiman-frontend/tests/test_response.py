from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch

from midiman_frontend.pattern import note
from midiman_frontend.session import KernelError, Session


def _mock_response(mock_cls: MagicMock, response: dict[str, object]) -> None:
    """Configure mock socket to return a JSON response line on readline()."""
    line = json.dumps(response) + "\n"
    mock_cls.return_value.makefile.return_value.readline.return_value = line.encode()


class TestResponseHandling:
    @patch("midiman_frontend.session.socket.socket")
    def test_ok_response_no_error(self, mock_cls: MagicMock) -> None:
        _mock_response(mock_cls, {"status": "Ok", "msg": "pattern set on drums"})
        with Session() as s:
            s.play("drums", note(36))

    @patch("midiman_frontend.session.socket.socket")
    def test_error_response_raises_kernel_error(self, mock_cls: MagicMock) -> None:
        _mock_response(mock_cls, {"status": "Error", "msg": "invalid pattern"})
        with Session() as s:
            with pytest.raises(KernelError, match="invalid pattern"):
                s.play("drums", note(36))

    @patch("midiman_frontend.session.socket.socket")
    def test_kernel_error_contains_message(self, mock_cls: MagicMock) -> None:
        _mock_response(mock_cls, {"status": "Error", "msg": "bad factor"})
        with Session() as s:
            with pytest.raises(KernelError) as exc_info:
                s.stop()
            assert "bad factor" in str(exc_info.value)

    @patch("midiman_frontend.session.socket.socket")
    def test_pong_response_no_error(self, mock_cls: MagicMock) -> None:
        _mock_response(mock_cls, {"status": "Pong"})
        with Session() as s:
            s.ping()

    @patch("midiman_frontend.session.socket.socket")
    def test_ping_sends_ping_command(self, mock_cls: MagicMock) -> None:
        _mock_response(mock_cls, {"status": "Pong"})
        with Session() as s:
            s.ping()
        raw: bytes = mock_cls.return_value.sendall.call_args[0][0]
        msg = json.loads(raw.decode().strip())
        assert msg["cmd"] == "Ping"

    @patch("midiman_frontend.session.socket.socket")
    def test_disconnect_closes_reader(self, mock_cls: MagicMock) -> None:
        with Session():
            pass
        mock_cls.return_value.makefile.return_value.close.assert_called_once()

    @patch("midiman_frontend.session.socket.socket")
    def test_empty_response_raises(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.makefile.return_value.readline.return_value = b""
        with Session() as s:
            with pytest.raises(ConnectionError):
                s.stop()
