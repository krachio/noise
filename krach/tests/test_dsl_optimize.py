"""Tests for Commit 3 — Optimization passes."""

from __future__ import annotations

from krach.ir.signal import ConstParams, Signal
from krach.signal.optimize import (
    common_subexpression_elimination,
    constant_fold,
    dead_code_elimination,
)
from krach.signal.primitives import const_p, mem_p
from krach.signal.core import mem
from krach.signal.transpile import make_graph


def test_constant_fold_removes_equation() -> None:
    # const(2) + const(3) should fold to const(5)
    from krach.signal.trace import coerce_to_signal

    def dsp() -> Signal:
        a = coerce_to_signal(2.0)
        b = coerce_to_signal(3.0)
        return a + b

    graph = make_graph(dsp)
    folded = constant_fold(graph)

    # The result should ultimately be a const(5.0)
    output_id = folded.outputs[0].id
    output_eqn = next(
        e for e in folded.equations if e.outputs[0].id == output_id
    )
    assert output_eqn.primitive is const_p
    assert isinstance(output_eqn.params, ConstParams)
    assert output_eqn.params.value == 5.0


def test_cse_deduplicates_identical_ops() -> None:
    # Same expression used twice should share one equation after CSE
    def dsp(a: Signal, b: Signal) -> tuple[Signal, Signal]:
        x = a + b
        y = a + b
        return x, y

    graph = make_graph(dsp)
    # Before CSE: 2 add equations
    add_count_before = sum(1 for e in graph.equations if e.primitive.name == "add")
    assert add_count_before == 2

    optimized = common_subexpression_elimination(graph)
    add_count_after = sum(1 for e in optimized.equations if e.primitive.name == "add")
    assert add_count_after == 1
    # Both outputs should point to the same signal
    assert optimized.outputs[0] == optimized.outputs[1]


def test_dce_removes_unused_equations() -> None:
    # Equation not reachable from outputs should be removed
    def dsp(a: Signal, b: Signal) -> Signal:
        _unused = a * 99.0  # dead
        return a + b

    graph = make_graph(dsp)
    cleaned = dead_code_elimination(graph)

    # The multiply by 99 should be gone
    mul_eqns = [e for e in cleaned.equations if e.primitive.name == "mul"]
    assert len(mul_eqns) == 0


def test_stateful_ops_not_folded() -> None:
    # mem_p is stateful and should survive constant folding
    def dsp() -> Signal:
        return mem(1.0)  # type: ignore[arg-type]

    graph = make_graph(dsp)
    folded = constant_fold(graph)

    mem_eqns = [e for e in folded.equations if e.primitive is mem_p]
    assert len(mem_eqns) == 1
