"""Audio graph IR builder — converts nodes + sends + wires into a GraphIr.

Pure function: no I/O, no state. Takes a dict of nodes and routing info,
returns a frozen GraphIr suitable for sending to the audio engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from krach.patterns import Graph, GraphIr


def inst_name(name: str, i: int, count: int) -> str:
    """Instance name: ``name_v{i}`` if count > 1, else ``name``."""
    return f"{name}_v{i}" if count > 1 else name


class _NodeLike(Protocol):
    """Protocol for Node-like objects (avoids circular import with _mixer.py)."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int
    count: int
    init: tuple[tuple[str, float], ...]


def build_graph_ir(
    nodes: Mapping[str, _NodeLike],
    sends: dict[tuple[str, str], float] | None = None,
    wires: dict[tuple[str, str], str] | None = None,
) -> GraphIr:
    """Build a complete audio graph IR from nodes, sends, and wires.

    Source nodes (num_inputs=0): DSP node → gain node → DAC.
    Effect nodes (num_inputs>0): DSP node → gain node → DAC (receives sends).
    Poly nodes (count>1): expand to N instances.
    Sends: source → send_gain → target (fan-in at target input).
    Wires: source → target:port (direct, no gain node).
    """
    _sources = {n: v for n, v in nodes.items() if v.num_inputs == 0}
    _effects = {n: v for n, v in nodes.items() if v.num_inputs > 0}
    _sends = sends or {}
    _wires = wires or {}

    builder = Graph()
    builder.node("out", "dac")

    for name, node in _sources.items():
        for i in range(node.count):
            inst = inst_name(name, i, node.count)
            per_gain = node.gain / node.count
            builder.node(inst, node.type_id, **dict(node.init))
            builder.node(f"{inst}_g", "gain", gain=per_gain)
            builder.connect(inst, "out", f"{inst}_g", "in")
            builder.connect(f"{inst}_g", "out", "out", "in")
            for param in node.controls:
                builder.expose(f"{inst}/{param}", inst, param)
            builder.expose(f"{inst}/gain", f"{inst}_g", "gain")

    poly_with_routing: set[str] = set()
    for src_name, _tgt in [*_sends.keys(), *_wires.keys()]:
        n = _sources.get(src_name)
        if n is not None and n.count > 1:
            poly_with_routing.add(src_name)

    for parent in poly_with_routing:
        node = _sources[parent]
        builder.node(f"{parent}_sum", "gain", gain=1.0)
        for i in range(node.count):
            builder.connect(f"{parent}_v{i}", "out", f"{parent}_sum", "in")

    for name, node in _effects.items():
        builder.node(name, node.type_id)
        builder.node(f"{name}_g", "gain", gain=node.gain)
        builder.connect(name, "out", f"{name}_g", "in")
        builder.connect(f"{name}_g", "out", "out", "in")
        for param in node.controls:
            builder.expose(f"{name}/{param}", name, param)
        builder.expose(f"{name}/gain", f"{name}_g", "gain")

    for (src_name, tgt_name), level in _sends.items():
        source = f"{src_name}_sum" if src_name in poly_with_routing else src_name
        send_id = f"{src_name}_send_{tgt_name}"
        builder.node(send_id, "gain", gain=level)
        builder.connect(source, "out", send_id, "in")
        builder.connect(send_id, "out", tgt_name, "in")
        builder.expose(f"{send_id}/gain", send_id, "gain")

    for (src_name, tgt_name), port in _wires.items():
        source = f"{src_name}_sum" if src_name in poly_with_routing else src_name
        builder.connect(source, "out", tgt_name, port)

    return builder.build()
