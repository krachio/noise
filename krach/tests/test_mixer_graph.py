from krach.node_types import Node
from krach.graph_builder import build_graph_ir


# ── build_graph_ir ────────────────────────────────────────────────────────────


def test_build_graph_ir_single_voice() -> None:
    nodes = {
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate", "cutoff")),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert node_ids == {"bass", "bass_g", "out"}
    assert len(ir.connections) == 2

    # Controls exposed as {voice}/{param}
    assert ir.exposed_controls["bass/freq"] == ("bass", "freq")
    assert ir.exposed_controls["bass/gate"] == ("bass", "gate")
    assert ir.exposed_controls["bass/cutoff"] == ("bass", "cutoff")
    assert ir.exposed_controls["bass/gain"] == ("bass_g", "gain")


def test_build_graph_ir_two_voices() -> None:
    nodes = {
        "kit": Node("faust:kit", 0.8, ("kick", "hat", "snare")),
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate")),
    }
    ir = build_graph_ir(nodes)

    assert len(ir.nodes) == 5  # kit, kit_g, bass, bass_g, out
    assert len(ir.connections) == 4

    assert ir.exposed_controls["kit/kick"] == ("kit", "kick")
    assert ir.exposed_controls["bass/freq"] == ("bass", "freq")
    assert ir.exposed_controls["kit/gain"] == ("kit_g", "gain")
    assert ir.exposed_controls["bass/gain"] == ("bass_g", "gain")


def test_build_graph_ir_empty_produces_dac_only() -> None:
    ir = build_graph_ir({})
    assert len(ir.nodes) == 1
    assert ir.nodes[0].id == "out"
    assert len(ir.connections) == 0
    assert len(ir.exposed_controls) == 0


def test_build_graph_ir_gain_node_has_initial_value() -> None:
    nodes = {"bass": Node("faust:acid_bass", 0.35, ("freq", "gate"))}
    ir = build_graph_ir(nodes)

    gain_node = next(n for n in ir.nodes if n.id == "bass_g")
    assert gain_node.type_id == "gain"
    assert gain_node.controls["gain"] == 0.35


def test_build_graph_ir_with_init_values() -> None:
    nodes = {
        "bass": Node("faust:acid_bass", 0.3, ("freq", "gate"),
                       init=(("freq", 55.0), ("gate", 0.0))),
    }
    ir = build_graph_ir(nodes)

    bass_node = next(n for n in ir.nodes if n.id == "bass")
    assert bass_node.controls["freq"] == 55.0
    assert bass_node.controls["gate"] == 0.0


def test_build_graph_ir_poly_voice_expands_instances() -> None:
    """A voice with count>1 expands to N instances in the IR."""
    nodes = {
        "pad": Node("faust:pad", 0.6, ("freq", "gate"), count=2),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "pad_v0" in node_ids
    assert "pad_v1" in node_ids
    assert "pad_v0_g" in node_ids
    assert "pad_v1_g" in node_ids
    # No bare "pad" node — instances only
    assert "pad" not in node_ids

    # Each instance gain = total gain / count
    g0 = next(n for n in ir.nodes if n.id == "pad_v0_g")
    assert g0.controls["gain"] == 0.3  # 0.6 / 2

    # Controls exposed per instance
    assert ir.exposed_controls["pad_v0/freq"] == ("pad_v0", "freq")
    assert ir.exposed_controls["pad_v1/gate"] == ("pad_v1", "gate")


def test_build_graph_ir_mono_voice_no_suffix() -> None:
    """A voice with count=1 uses name directly (no _v0 suffix)."""
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate"), count=1),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "bass" in node_ids
    assert "bass_v0" not in node_ids


def test_build_graph_ir_poly_sum_node() -> None:
    """Poly voice with sends gets an implicit sum node."""
    nodes = {
        "pad": Node("faust:pad", 0.6, ("freq", "gate"), count=2),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("pad", "verb"): 0.4}

    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "pad_sum" in node_ids  # implicit sum node

    # Both instances fan into sum
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("pad_v0", "pad_sum") in conns
    assert ("pad_v1", "pad_sum") in conns
    # Sum → send → bus
    assert ("pad_sum", "pad_send_verb") in conns


def test_build_graph_ir_namespaced_type_id_with_slash() -> None:
    """type_id with '/' (e.g. faust:drums/kick) must be treated as opaque.

    Regression test for GitHub issue #1: the slash in the type_id must
    not be confused with the control path separator.
    """
    nodes = {
        "kick": Node("faust:drums/kick", 0.8, ("gate",)),
    }
    ir = build_graph_ir(nodes)

    node_ids = {n.id for n in ir.nodes}
    assert "kick" in node_ids
    assert "kick_g" in node_ids
    assert "out" in node_ids

    # type_id preserved verbatim
    kick_node = next(n for n in ir.nodes if n.id == "kick")
    assert kick_node.type_id == "faust:drums/kick"

    # Control exposed correctly: kick/gate, not drums/kick/gate
    assert ir.exposed_controls["kick/gate"] == ("kick", "gate")
    assert ir.exposed_controls["kick/gain"] == ("kick_g", "gain")


def test_build_graph_ir_mono_no_sum_node() -> None:
    """Mono voice with sends does NOT get a sum node."""
    nodes = {
        "bass": Node("faust:bass", 0.5, ("freq", "gate"), count=1),
        "verb": Node("faust:verb", 0.3, ("room",), num_inputs=1),
    }
    sends = {("bass", "verb"): 0.4}

    ir = build_graph_ir(nodes, sends=sends)

    node_ids = {n.id for n in ir.nodes}
    assert "bass_sum" not in node_ids
    # Direct: bass → send → verb
    conns = [(c.from_node, c.to_node) for c in ir.connections]
    assert ("bass", "bass_send_verb") in conns
