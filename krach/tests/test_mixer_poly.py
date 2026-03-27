"""Poly lifecycle tests — bugs #22 (poly routing) and #23 (poly remove)."""

from pathlib import Path
from unittest.mock import MagicMock

from krach.graph.node import Node, build_graph_ir
from krach.mixer import Mixer


def _make_mixer(**extra_controls: tuple[str, ...]) -> tuple[MagicMock, Mixer]:
    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "faust:verb", "dac", "gain"]
    controls: dict[str, tuple[str, ...]] = {
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
        **extra_controls,
    }
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls=controls)
    return session, mixer


def test_remove_poly_node_removes_all_instances() -> None:
    """remove('pad') on a poly voice (count=4) must remove pad_v0..v3 from
    the graph IR. After remove, the next load_graph call must not contain
    any instance nodes or the sum node."""
    session, mixer = _make_mixer()
    mixer.voice("pad", "faust:pad", count=4, gain=0.6)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    session.reset_mock()
    mixer.remove("pad")

    ir = session.load_graph.call_args[0][0]
    node_ids = {n.id for n in ir.nodes}

    for i in range(4):
        assert f"pad_v{i}" not in node_ids, f"pad_v{i} leaked after remove"
        assert f"pad_v{i}_g" not in node_ids, f"pad_v{i}_g leaked after remove"
    assert "pad_sum" not in node_ids, "pad_sum leaked after remove"
    assert "pad_send_verb" not in node_ids, "send node leaked after remove"


def test_remove_poly_node_clears_ctrl_values() -> None:
    """remove('pad') must clean ctrl_values for all voice instances."""
    _session, mixer = _make_mixer()
    mixer.voice("pad", "faust:pad", count=3, gain=0.6)

    # Simulate control values accumulating.
    mixer.set("pad/freq", 440.0)  # fans out to pad_v0/freq, pad_v1/freq, pad_v2/freq

    mixer.remove("pad")

    # No orphaned control values.
    stale = [k for k in mixer.controls if k.startswith("pad")]
    assert stale == [], f"orphaned controls after remove: {stale}"


def test_connect_poly_to_bus_routes_through_sum() -> None:
    """send('pad', 'verb') on a poly voice must create a sum node and route
    pad_v0..vN → pad_sum → pad_send_verb → verb."""
    session, mixer = _make_mixer()
    mixer.voice("pad", "faust:pad", count=2, gain=0.6)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    ir = session.load_graph.call_args[0][0]
    node_ids = {n.id for n in ir.nodes}
    conns = [(c.from_node, c.to_node) for c in ir.connections]

    assert "pad_sum" in node_ids, "sum node missing"
    assert ("pad_v0", "pad_sum") in conns, "pad_v0 → pad_sum missing"
    assert ("pad_v1", "pad_sum") in conns, "pad_v1 → pad_sum missing"
    assert ("pad_sum", "pad_send_verb") in conns, "pad_sum → send missing"


def test_connect_mono_to_bus_no_sum_node() -> None:
    """send('bass', 'verb') on a mono voice (count=1) must NOT create a sum node.
    Routing goes bass → bass_send_verb → verb directly."""
    session, mixer = _make_mixer(**{"faust:bass": ("freq", "gate")})
    session.list_nodes.return_value = ["faust:bass", "faust:verb", "dac", "gain"]
    mixer.voice("bass", "faust:bass", count=1, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    ir = session.load_graph.call_args[0][0]
    node_ids = {n.id for n in ir.nodes}

    assert "bass_sum" not in node_ids, "mono voice should not have sum node"
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns or \
        ("bass_g", "bass_send_verb") in conns, \
        f"expected direct bass→send connection, got {conns}"


def test_build_graph_ir_poly_send_correct_connections() -> None:
    """build_graph_ir with poly source + send must produce:
    pad_v0 → pad_v0_g → out, pad_v1 → pad_v1_g → out,
    pad_v0 → pad_sum, pad_v1 → pad_sum,
    pad_sum → pad_send_verb → verb → verb_g → out."""
    nodes = {
        "pad": Node("faust:pad", 0.6, ("freq", "gate"), count=2),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("pad", "verb"): 0.4}

    ir = build_graph_ir(nodes, sends=sends)
    node_ids = {n.id for n in ir.nodes}
    conns = {(c.from_node, c.to_node) for c in ir.connections}

    # Instances exist.
    assert "pad_v0" in node_ids
    assert "pad_v1" in node_ids
    assert "pad_sum" in node_ids
    assert "pad_send_verb" in node_ids

    # Correct routing.
    assert ("pad_v0", "pad_sum") in conns
    assert ("pad_v1", "pad_sum") in conns
    assert ("pad_sum", "pad_send_verb") in conns
    assert ("pad_send_verb", "verb") in conns

    # Send gain exposed.
    assert "pad_send_verb/gain" in ir.exposed_controls
