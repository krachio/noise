from __future__ import annotations

import json
import socket
import threading

import pytest

from krach.session import Session


def _make_tcp_server(
    token: str | None = None,
) -> tuple[socket.socket, int]:
    """Spin up a minimal TCP server that speaks the krach protocol."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def handler() -> None:
        conn, _ = srv.accept()
        conn.settimeout(2.0)
        f = conn.makefile("rwb")
        # Send protocol handshake.
        f.write(b'{"protocol":1,"engine":"krach-engine"}\n')
        f.flush()
        # If token required, expect auth message.
        if token is not None:
            auth_line = f.readline()
            data = json.loads(auth_line)
            if data.get("auth") == token:
                f.write(b'{"status":"Ok","msg":"authenticated"}\n')
                f.flush()
            else:
                f.write(b'{"status":"Error","msg":"auth failed"}\n')
                f.flush()
                conn.close()
                return
        # Echo pong for any Ping.
        while True:
            line = f.readline()
            if not line:
                break
            f.write(b'{"status":"Pong"}\n')
            f.flush()
        conn.close()

    t = threading.Thread(target=handler, daemon=True)
    t.start()
    return srv, port


class TestSessionTcpConnect:
    def test_connect_to_tcp_address(self) -> None:
        srv, port = _make_tcp_server()
        try:
            s = Session(address=("127.0.0.1", port))
            s.connect()
            s.ping()
            s.disconnect()
        finally:
            srv.close()

    def test_tcp_with_valid_token(self) -> None:
        srv, port = _make_tcp_server(token="secret123")
        try:
            s = Session(address=("127.0.0.1", port), token="secret123")
            s.connect()
            s.ping()
            s.disconnect()
        finally:
            srv.close()

    def test_tcp_with_wrong_token_raises(self) -> None:
        srv, port = _make_tcp_server(token="secret123")
        try:
            s = Session(address=("127.0.0.1", port), token="wrong")
            with pytest.raises(ConnectionError, match="auth failed"):
                s.connect()
        finally:
            srv.close()

    def test_unix_path_still_works(self) -> None:
        """Session with socket_path= uses AF_UNIX (existing behavior)."""
        s = Session(socket_path="/tmp/nonexistent.sock")
        # Can't actually connect (no server), but verify it stores the path.
        assert s.socket_path == "/tmp/nonexistent.sock"
        assert s._address is None

    def test_address_detection_host_port_tuple(self) -> None:
        s = Session(address=("192.168.1.1", 9090))
        assert s._address == ("192.168.1.1", 9090)
