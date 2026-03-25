"""Tests for graph_key-based caching."""

from __future__ import annotations

import time

from krach.ir.signal import Signal
from krach.ir.canonicalize import graph_key
from krach.signal.transpile import make_graph


def test_graph_key_deterministic() -> None:
    """Trace the same function twice, assert graph_key(g1) == graph_key(g2)."""
    def simple(x: Signal) -> Signal:
        return x * 0.5

    g1 = make_graph(simple, num_inputs=1)
    g2 = make_graph(simple, num_inputs=1)
    assert graph_key(g1) == graph_key(g2)


def test_graph_key_stable_across_traces() -> None:
    """Trace in two separate calls, keys must match despite different auto-increment IDs."""
    def synth() -> Signal:
        from krach.signal.transpile import control
        freq = control("freq", 440.0, 20.0, 20000.0)
        return freq * 0.5

    g1 = make_graph(synth, num_inputs=0)
    g2 = make_graph(synth, num_inputs=0)
    # IDs will differ but canonical form should match
    assert graph_key(g1) == graph_key(g2)


def test_trace_performance_simple() -> None:
    """Trace + canonicalize + graph_key for a simple fn must take < 10ms."""
    def simple(x: Signal) -> Signal:
        return x * 0.5

    start = time.perf_counter()
    g = make_graph(simple, num_inputs=1)
    _ = graph_key(g)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.01, f"trace took {elapsed:.3f}s, expected < 10ms"
