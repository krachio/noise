import json
import socket

from pythonosc import osc_message, osc_packet

from soundman_frontend import ConnectionIr, Graph, GraphIr, NodeInstance, SoundmanSession


def test_public_api_roundtrip() -> None:
    node = NodeInstance(id="osc1", type_id="oscillator", controls={"freq": 440.0})
    conn = ConnectionIr(from_node="osc1", from_port="out", to_node="out", to_port="in")
    graph = GraphIr(nodes=(node,), connections=(conn,), exposed_controls={})
    assert graph.nodes[0].type_id == "oscillator"
    assert graph.connections[0].to_node == "out"

    built = Graph().node("osc1", "oscillator", freq=440.0).node("out", "dac").connect("osc1", "out", "out", "in").build()
    assert built == GraphIr(
        nodes=(
            NodeInstance(id="osc1", type_id="oscillator", controls={"freq": 440.0}),
            NodeInstance(id="out", type_id="dac"),
        ),
        connections=(conn,),
        exposed_controls={},
    )


def test_build_and_send_graph() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    _, port = receiver.getsockname()

    graph = (
        Graph()
        .node("osc1", "oscillator", freq=440.0)
        .node("out", "dac")
        .connect("osc1", "out", "out", "in")
        .build()
    )

    SoundmanSession(host="127.0.0.1", port=port).load_graph(graph)

    data, _ = receiver.recvfrom(4096)
    packet = osc_packet.OscPacket(data)
    msg = packet.messages[0].message
    assert isinstance(msg, osc_message.OscMessage)
    assert msg.address == "/soundman/load_graph"

    parsed = json.loads(msg.params[0])
    node_ids = [n["id"] for n in parsed["nodes"]]
    assert "osc1" in node_ids
    assert "out" in node_ids
    assert parsed["connections"][0]["from_node"] == "osc1"
    assert parsed["connections"][0]["to_node"] == "out"

    receiver.close()
