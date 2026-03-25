from pathlib import Path

from krach.node_types import Node
from krach.graph_builder import build_graph_ir


# ── build_graph_ir with buses/sends/wires ────────────────────────────────────


def test_build_graph_ir_with_bus() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids
    assert ir.exposed_controls["verb/room"] == ("verb", "room")
    assert ir.exposed_controls["verb/gain"] == ("verb_g", "gain")


def test_build_graph_ir_with_send() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids

    assert ir.exposed_controls["bass_send_verb/gain"] == ("bass_send_verb", "gain")

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns
    assert ("bass_send_verb", "verb") in conns


def test_build_graph_ir_two_sends_same_bus() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "pad": Node("faust:pad", 0.3, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4, ("pad", "verb"): 0.6}
    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids
    assert "pad_send_verb" in node_ids

    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass_send_verb", "verb") in conns
    assert ("pad_send_verb", "verb") in conns


def test_build_graph_ir_send_gain_initial_value() -> None:
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate")),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}
    ir = build_graph_ir(nodes, sends=sends)

    send_node = next(n for n in ir.nodes if n.id == "bass_send_verb")
    assert send_node.controls["gain"] == 0.4


def test_build_graph_ir_with_wire() -> None:
    nodes = {
        "pad": Node("faust:pad", 0.5, ("freq", "gate")),
        "kick": Node("faust:kick", 0.8, ("gate",)),
        "comp": Node("faust:comp", 1.0, ("threshold",), num_inputs=2),
    }
    wires = {("pad", "comp"): "in0", ("kick", "comp"): "in1"}
    ir = build_graph_ir(nodes, wires=wires)

    wire_conns = [
        (c.from_node, c.to_node, c.to_port)
        for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns
    assert ("kick", "comp", "in1") in wire_conns


def test_build_graph_ir_no_buses_backward_compatible() -> None:
    nodes = {"bass": Node("faust:bass", 0.5, ("freq", "gate"))}
    ir_old = build_graph_ir(nodes)
    ir_new = build_graph_ir(nodes, sends=None, wires=None)
    assert ir_old == ir_new


# ── Commit 3: bus() + send() + remove() ──────────────────────────────────


def test_bus_creates_bus_and_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    session.reset_mock()

    mixer.bus("verb", "faust:verb", gain=0.3)

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "verb" in node_ids
    assert "verb_g" in node_ids


def test_send_new_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    session.reset_mock()

    mixer.send("bass", "verb", level=0.4)

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" in node_ids


def test_send_update_instant() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)
    session.reset_mock()

    mixer.send("bass", "verb", level=0.7)

    assert session.load_graph.call_count == 0
    session.set_ctrl.assert_called_once_with("bass_send_verb/gain", 0.7)


def test_send_missing_source_is_noop_old() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("nope", "verb", level=0.4)  # must not raise


def test_send_missing_target_is_noop_old() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.send("bass", "nope", level=0.4)  # must not raise


def test_remove_voice_cleans_sends() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.remove("bass")

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_remove_cleans_sends_and_wires() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.remove("verb")

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "verb" not in node_ids
    assert "bass_send_verb" not in node_ids


def test_bus_replaces_voice_with_same_name() -> None:
    """bus() replaces a voice with an effect node (unified model)."""
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("bass", "faust:bass", gain=0.3)
    node = mixer.get_node("bass")
    assert node is not None
    assert node.gain == 0.3
    assert node.num_inputs > 0


def test_bus_replaces_poly_voice() -> None:
    """bus() replaces a poly voice, cleaning up instances."""
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("pad", "faust:pad", gain=0.3)
    node = mixer.get_node("pad")
    assert node is not None
    assert node.count == 1  # bus is always mono
    assert node.num_inputs > 0


def test_gain_works_for_bus() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    mixer.bus("verb", "faust:verb", gain=0.3)
    session.reset_mock()

    mixer.gain("verb", 0.8)

    session.set_ctrl.assert_called_once_with("verb/gain", 0.8)


def test_send_poly_parent_instant_update() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)
    session.reset_mock()

    mixer.send("pad", "verb", level=0.7)

    assert session.load_graph.call_count == 0
    session.set_ctrl.assert_called_once_with("pad_send_verb/gain", 0.7)


def test_repr_shows_buses() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)

    r = repr(mixer)
    assert "verb" in r
    assert "bus" in r.lower() or "faust:verb" in r


def test_voice_replace_cleans_sends() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:bass2": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("bass", "faust:bass", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("bass", "verb", level=0.4)

    mixer.voice("bass", "faust:bass2", gain=0.3)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "bass_send_verb" not in node_ids


def test_poly_replace_cleans_sends() -> None:
    """voice() replacement with count change cleans up sends."""
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    session.list_nodes.return_value = ["faust:pad", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", count=2, gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    # Re-voice — sends should be cleaned
    mixer.voice("pad", "faust:pad", count=3, gain=0.6)

    ir = session.load_graph.call_args.args[0]
    node_ids = {n.id for n in ir.nodes}
    assert "pad_send_verb" not in node_ids


# ── Commit 4: wire() ─────────────────────────────────────────────────────────


def test_wire_rebuilds() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:comp": ("threshold",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("comp", "faust:comp", gain=1.0)
    session.reset_mock()

    mixer.wire("pad", "comp", port="in0")

    assert session.load_graph.call_count == 1
    ir = session.load_graph.call_args.args[0]
    wire_conns = [
        (c.from_node, c.to_node, c.to_port) for c in ir.connections
    ]
    assert ("pad", "comp", "in0") in wire_conns


def test_wire_and_send_same_pair_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.send("pad", "verb", level=0.4)

    with pytest.raises(ValueError, match="send already exists"):
        mixer.wire("pad", "verb", port="in0")


def test_send_and_wire_same_pair_raises() -> None:
    from unittest.mock import MagicMock

    import pytest

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("verb", "faust:verb", gain=0.3)
    mixer.wire("pad", "verb", port="in0")

    with pytest.raises(ValueError, match="wire already exists"):
        mixer.send("pad", "verb", level=0.4)


def test_remove_voice_cleans_wires() -> None:
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
        "faust:comp": ("threshold",),
    })
    mixer.voice("pad", "faust:pad", gain=0.5)
    mixer.bus("comp", "faust:comp", gain=1.0)
    mixer.wire("pad", "comp", port="in0")

    mixer.remove("pad")

    ir = session.load_graph.call_args.args[0]
    wire_conns = [(c.from_node, c.to_node, c.to_port) for c in ir.connections]
    assert ("pad", "comp", "in0") not in wire_conns
