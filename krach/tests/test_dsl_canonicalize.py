"""Tests for DspGraph canonicalization — alpha-renaming Signal IDs."""

from __future__ import annotations

from krach.ir.signal import Signal, Precision
from krach.signal.transpile import make_graph, control
from krach.signal.core import sin, feedback
from krach.ir.canonicalize import canonicalize, graph_key


def _double(x: Signal) -> Signal:
    return x * 2.0


def _add_two(x: Signal) -> Signal:
    return x + 2.0


def _double_plus_one(x: Signal) -> Signal:
    return x * 2.0 + 1.0


def _square_plus_one(x: Signal) -> Signal:
    return x * x + 1.0


def test_same_fn_same_canonical_hash() -> None:
    """Two traces of the same function produce the same canonical hash."""
    def osc(x: Signal) -> Signal:
        return sin(x * 440.0)

    g1 = make_graph(osc, num_inputs=1)
    g2 = make_graph(osc, num_inputs=1)
    # Raw signal IDs differ between traces
    assert g1.inputs[0].id != g2.inputs[0].id
    # Canonical hashes are equal
    assert graph_key(g1) == graph_key(g2)


def test_different_fn_different_hash() -> None:
    """Different computations produce different hashes."""
    g1 = make_graph(_double, num_inputs=1)
    g2 = make_graph(_add_two, num_inputs=1)
    assert graph_key(g1) != graph_key(g2)


def test_canonical_ids_sequential() -> None:
    """After canonicalization, signal IDs are sequential starting from 0."""
    g = make_graph(_double_plus_one, num_inputs=1)
    c = canonicalize(g)
    all_ids: set[int] = set()
    for s in c.inputs:
        all_ids.add(s.id)
    for eqn in c.equations:
        for s in eqn.inputs:
            all_ids.add(s.id)
        for s in eqn.outputs:
            all_ids.add(s.id)
    assert all_ids == set(range(len(all_ids)))


def test_idempotent() -> None:
    """Canonicalizing a canonical graph produces the same result."""
    g = make_graph(_square_plus_one, num_inputs=1)
    c1 = canonicalize(g)
    c2 = canonicalize(c1)
    assert graph_key(c1) == graph_key(c2)


def test_control_params_in_hash() -> None:
    """Controls with different params produce different hashes."""
    def synth_a() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    def synth_b() -> Signal:
        return control("freq", 880.0, 20.0, 20000.0)

    g1 = make_graph(synth_a)
    g2 = make_graph(synth_b)
    assert graph_key(g1) != graph_key(g2)


def test_same_control_same_hash() -> None:
    """Same control spec produces same hash across traces."""
    def synth() -> Signal:
        return control("freq", 440.0, 20.0, 20000.0)

    g1 = make_graph(synth)
    g2 = make_graph(synth)
    assert graph_key(g1) == graph_key(g2)


def test_feedback_same_hash() -> None:
    """Feedback graphs with identical structure produce the same canonical hash."""
    def integrator(x: Signal) -> Signal:
        return feedback(lambda fb: fb * 0.99 + x * 0.01)

    g1 = make_graph(integrator, num_inputs=1)
    g2 = make_graph(integrator, num_inputs=1)
    assert g1.inputs[0].id != g2.inputs[0].id
    assert graph_key(g1) == graph_key(g2)


def test_feedback_different_body_different_hash() -> None:
    """Feedback graphs with different body computations differ."""
    def integrator_a(x: Signal) -> Signal:
        return feedback(lambda fb: fb * 0.99 + x * 0.01)

    def integrator_b(x: Signal) -> Signal:
        return feedback(lambda fb: fb * 0.5 + x * 0.5)

    g1 = make_graph(integrator_a, num_inputs=1)
    g2 = make_graph(integrator_b, num_inputs=1)
    assert graph_key(g1) != graph_key(g2)


def test_feedback_canonical_idempotent() -> None:
    """Canonicalizing a feedback graph twice gives the same result."""
    def osc(x: Signal) -> Signal:
        return feedback(lambda fb: fb * 0.99 + x)

    g = make_graph(osc, num_inputs=1)
    c1 = canonicalize(g)
    c2 = canonicalize(c1)
    assert graph_key(c1) == graph_key(c2)


def test_precision_matters() -> None:
    """Different precision produces different hash."""
    g32 = make_graph(_double, num_inputs=1, precision=Precision.FLOAT32)
    g64 = make_graph(_double, num_inputs=1, precision=Precision.FLOAT64)
    assert graph_key(g32) != graph_key(g64)
