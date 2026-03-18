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


def test_list_nodes_sends_query_and_receives_reply() -> None:
    # Set up a fake soundman that receives the query and sends back a reply.
    fake_soundman = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fake_soundman.bind(("127.0.0.1", 0))
    fake_soundman.settimeout(1.0)
    soundman_port = fake_soundman.getsockname()[1]

    session = SoundmanSession(host="127.0.0.1", port=soundman_port)

    import threading

    result: list[list[str]] = []

    def fake_soundman_reply() -> None:
        data, _ = fake_soundman.recvfrom(4096)
        query = osc_packet.OscPacket(data).messages[0].message
        assert isinstance(query, osc_message.OscMessage)
        assert query.address == "/soundman/list_nodes"
        reply_port = query.params[0]

        # Send back a /soundman/node_types reply using SimpleUDPClient
        from pythonosc.udp_client import SimpleUDPClient
        reply_client = SimpleUDPClient("127.0.0.1", reply_port)
        reply_client.send_message("/soundman/node_types", '["oscillator","dac"]')  # type: ignore[reportUnknownMemberType]

    t = threading.Thread(target=fake_soundman_reply)
    t.start()
    result.append(session.list_nodes(timeout=1.0))
    t.join(timeout=2.0)

    assert result[0] == ["oscillator", "dac"]
    fake_soundman.close()


def test_list_nodes_timeout_raises() -> None:
    # Point at a port nothing is listening on — should time out.
    session = SoundmanSession(host="127.0.0.1", port=19001)
    with pytest.raises(TimeoutError):
        session.list_nodes(timeout=0.1)
