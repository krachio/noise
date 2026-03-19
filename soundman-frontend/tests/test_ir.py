import json
from dataclasses import FrozenInstanceError

import pytest

from soundman_frontend.ir import ConnectionIr, GraphIr, NodeInstance


def test_node_instance_to_dict() -> None:
    node = NodeInstance(id="osc1", type_id="oscillator", controls={"freq": 440.0})
    assert node.to_dict() == {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}}


def test_node_instance_default_controls() -> None:
    node = NodeInstance(id="out", type_id="dac")
    assert node.to_dict() == {"id": "out", "type_id": "dac", "controls": {}}


def test_connection_ir_to_dict() -> None:
    conn = ConnectionIr(from_node="osc1", from_port="out", to_node="out", to_port="in")
    assert conn.to_dict() == {
        "from_node": "osc1",
        "from_port": "out",
        "to_node": "out",
        "to_port": "in",
    }


def test_graph_ir_to_json_contains_required_keys() -> None:
    graph = GraphIr(nodes=(), connections=(), exposed_controls={})
    parsed = json.loads(graph.to_json())
    assert "nodes" in parsed
    assert "connections" in parsed
    assert "exposed_controls" in parsed


def test_exposed_controls_serializes_as_array() -> None:
    graph = GraphIr(
        nodes=(),
        connections=(),
        exposed_controls={"pitch": ("osc1", "freq")},
    )
    parsed = json.loads(graph.to_json())
    assert parsed["exposed_controls"]["pitch"] == ["osc1", "freq"]


def test_graph_ir_empty() -> None:
    graph = GraphIr(nodes=(), connections=(), exposed_controls={})
    parsed = json.loads(graph.to_json())
    assert parsed["nodes"] == []
    assert parsed["connections"] == []
    assert parsed["exposed_controls"] == {}


def test_node_instance_frozen() -> None:
    node = NodeInstance(id="osc1", type_id="oscillator")
    with pytest.raises(FrozenInstanceError):
        node.id = "osc2"  # type: ignore[misc]


def test_graph_ir_json_roundtrip() -> None:
    node = NodeInstance(id="osc1", type_id="oscillator", controls={"freq": 440.0})
    conn = ConnectionIr(from_node="osc1", from_port="out", to_node="out", to_port="in")
    graph = GraphIr(
        nodes=(node,),
        connections=(conn,),
        exposed_controls={"pitch": ("osc1", "freq")},
    )
    parsed = json.loads(graph.to_json())
    assert parsed["nodes"][0]["id"] == "osc1"
    assert abs(parsed["nodes"][0]["controls"]["freq"] - 440.0) < 1e-5
    assert parsed["connections"][0]["from_node"] == "osc1"
    assert parsed["exposed_controls"]["pitch"] == ["osc1", "freq"]
