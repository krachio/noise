"""Tests for Commit 7 — compose.py."""

from __future__ import annotations

from krach.ir.signal import Signal
from krach.signal.compose import chain, parallel, split
from krach.signal.transpile import make_graph


def test_chain_connects_outputs_to_inputs() -> None:
    # chain(f, g): f's output goes into g's input
    def double(a: Signal) -> Signal:
        return a * 2.0

    def add_one(a: Signal) -> Signal:
        return a + 1.0

    chained = chain(double, add_one)
    graph = make_graph(chained)

    # Should have 1 input, 1 output
    assert len(graph.inputs) == 1
    assert len(graph.outputs) == 1
    # Equations: const(2) + mul + const(1) + add = 4 equations
    assert len(graph.equations) >= 2


def test_parallel_independent_graphs() -> None:
    # parallel(f, g) should process independent inputs
    def double(a: Signal) -> Signal:
        return a * 2.0

    def triple(a: Signal) -> Signal:
        return a * 3.0

    par = parallel(double, triple)
    graph = make_graph(par)

    # 2 inputs, 2 outputs
    assert len(graph.inputs) == 2
    assert len(graph.outputs) == 2

    # Inputs should be independent signals (no shared equations)
    # Each input feeds one multiplication
    mul_eqns = [e for e in graph.equations if e.primitive.name == "mul"]
    assert len(mul_eqns) == 2

    # Each mul uses a different input
    input_ids = {s.id for s in graph.inputs}
    used_inputs: set[int] = set()
    for eqn in mul_eqns:
        for inp in eqn.inputs:
            if inp.id in input_ids:
                used_inputs.add(inp.id)
    assert len(used_inputs) == 2


def test_split_fans_out() -> None:
    def dsp(a: Signal) -> Signal:
        copies = split(a, 3)
        assert len(copies) == 3
        # All 3 are the same signal reference
        assert all(c.id == a.id for c in copies)
        return copies[0]

    graph = make_graph(dsp)
    assert len(graph.outputs) == 1
