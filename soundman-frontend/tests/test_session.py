import json
import socket

import pytest
from pythonosc import osc_message, osc_packet

from soundman_frontend.graph import Graph
from soundman_frontend.session import SoundmanSession


def _recv_osc(sock: socket.socket) -> osc_message.OscMessage:
    data, _ = sock.recvfrom(4096)
    packet = osc_packet.OscPacket(data)
    msg = packet.messages[0].message
    assert isinstance(msg, osc_message.OscMessage)
    return msg


@pytest.fixture()
def receiver() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    return sock


def session_for(receiver: socket.socket) -> SoundmanSession:
    _, port = receiver.getsockname()
    return SoundmanSession(host="127.0.0.1", port=port)


def test_ping_sends_correct_osc_address(receiver: socket.socket) -> None:
    session_for(receiver).ping()
    msg = _recv_osc(receiver)
    assert msg.address == "/soundman/ping"
    assert msg.params == []


def test_gain_sends_float_arg(receiver: socket.socket) -> None:
    session_for(receiver).gain(0.75)
    msg = _recv_osc(receiver)
    assert msg.address == "/soundman/gain"
    assert len(msg.params) == 1
    assert abs(msg.params[0] - 0.75) < 1e-5


def test_set_sends_label_and_value(receiver: socket.socket) -> None:
    session_for(receiver).set("pitch", 440.0)
    msg = _recv_osc(receiver)
    assert msg.address == "/soundman/set"
    assert msg.params[0] == "pitch"
    assert abs(msg.params[1] - 440.0) < 1e-5


def test_load_graph_sends_json_string(receiver: socket.socket) -> None:
    graph = (
        Graph()
        .node("osc1", "oscillator", freq=440.0)
        .node("out", "dac")
        .connect("osc1", "out", "out", "in")
        .build()
    )
    session_for(receiver).load_graph(graph)
    msg = _recv_osc(receiver)
    assert msg.address == "/soundman/load_graph"
    assert len(msg.params) == 1
    parsed = json.loads(msg.params[0])
    assert "nodes" in parsed
    assert "connections" in parsed
    assert "exposed_controls" in parsed


def test_context_manager_sends_while_open(receiver: socket.socket) -> None:
    with session_for(receiver) as s:
        s.ping()
    msg = _recv_osc(receiver)
    assert msg.address == "/soundman/ping"


def test_default_host_and_port() -> None:
    s = SoundmanSession()
    assert s.host == "127.0.0.1"
    assert s.port == 9000
