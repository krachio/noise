from dataclasses import dataclass

import pytest

from soundman_frontend.graph import Graph
from soundman_frontend.ir import ConnectionIr, NodeInstance


def test_node_creates_node_instance() -> None:
    graph = Graph().node("osc1", "oscillator", freq=440.0).build()
    assert len(graph.nodes) == 1
    assert graph.nodes[0] == NodeInstance(id="osc1", type_id="oscillator", controls={"freq": 440.0})


def test_node_returns_self_for_chaining() -> None:
    g = Graph()
    assert g.node("osc1", "oscillator") is g


def test_connect_creates_connection_ir() -> None:
    graph = (
        Graph()
        .node("osc1", "oscillator")
        .node("out", "dac")
        .connect("osc1", "out", "out", "in")
        .build()
    )
    assert len(graph.connections) == 1
    assert graph.connections[0] == ConnectionIr(
        from_node="osc1", from_port="out", to_node="out", to_port="in"
    )


def test_expose_adds_label_to_exposed_controls() -> None:
    graph = Graph().node("osc1", "oscillator").expose("pitch", "osc1", "freq").build()
    assert graph.exposed_controls == {"pitch": ("osc1", "freq")}


def test_expose_schema_wires_all_controls() -> None:
    @dataclass(frozen=True)
    class Spec:
        name: str

    @dataclass(frozen=True)
    class Schema:
        controls: tuple[Spec, ...]

    schema = Schema(controls=(Spec(name="freq"), Spec(name="gate")))
    graph = Graph().node("synth1", "faust:mysynth").expose_schema("synth1", schema).build()

    assert graph.exposed_controls["freq"] == ("synth1", "freq")
    assert graph.exposed_controls["gate"] == ("synth1", "gate")


def test_build_captures_node_content() -> None:
    graph = Graph().node("osc1", "oscillator", freq=880.0).build()
    assert graph.nodes[0].id == "osc1"
    assert graph.nodes[0].type_id == "oscillator"
    assert graph.nodes[0].controls["freq"] == 880.0


def test_duplicate_node_id_raises() -> None:
    with pytest.raises(ValueError, match="osc1"):
        Graph().node("osc1", "oscillator").node("osc1", "dac").build()


def test_empty_graph_builds_successfully() -> None:
    graph = Graph().build()
    assert graph.nodes == ()
    assert graph.connections == ()
    assert graph.exposed_controls == {}


def test_full_chain() -> None:
    graph = (
        Graph()
        .node("osc1", "oscillator", freq=440.0)
        .node("out", "dac")
        .connect("osc1", "out", "out", "in")
        .expose("pitch", "osc1", "freq")
        .build()
    )
    assert len(graph.nodes) == 2
    assert len(graph.connections) == 1
    assert graph.exposed_controls == {"pitch": ("osc1", "freq")}
