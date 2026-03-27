"""Tests for Commit 2 — wavetable() refactored to use rdtable_p."""

from __future__ import annotations

from krach.signal.lib import wavetable
from krach.signal.types import RdTableParams, Signal
from krach.signal.transpile import make_graph
from krach.backends.faust import emit_faust
from krach.ir.canonicalize import graph_key


def test_wavetable_uses_rdtable_p() -> None:
    """wavetable() must produce an rdtable_p equation, not faust_expr_p."""
    data = [0.0, 0.5, 1.0, 0.5]

    def dsp(idx: Signal) -> Signal:
        return wavetable(data, idx)

    g = make_graph(dsp)
    prims = {e.primitive.name for e in g.equations}
    assert "rdtable" in prims
    assert "faust_expr" not in prims


def test_wavetable_rdtable_params() -> None:
    """wavetable() equation should have RdTableParams with correct data."""
    data = [1.0, 2.0, 3.0]

    def dsp(idx: Signal) -> Signal:
        return wavetable(data, idx)

    g = make_graph(dsp)
    rd_eqns = [e for e in g.equations if e.primitive.name == "rdtable"]
    assert len(rd_eqns) == 1
    assert isinstance(rd_eqns[0].params, RdTableParams)
    assert rd_eqns[0].params.data == (1.0, 2.0, 3.0)


def test_wavetable_empty_rejected() -> None:
    """Empty wavetable data must raise ValueError."""
    import pytest
    with pytest.raises(ValueError, match="must not be empty"):
        def dsp(idx: Signal) -> Signal:
            return wavetable([], idx)
        make_graph(dsp)


def test_wavetable_faust_output() -> None:
    """FAUST output should contain rdtable(..., waveform{...}, ...)."""
    data = [0.0, 1.0]

    def dsp(idx: Signal) -> Signal:
        return wavetable(data, idx)

    src = emit_faust(make_graph(dsp))
    assert "rdtable(2" in src
    assert "waveform{0.0, 1.0}" in src


def test_wavetable_graph_key_stable() -> None:
    """Two traces of the same wavetable produce the same graph_key."""
    data = [0.0, 0.25, 0.5, 0.75]

    def dsp(idx: Signal) -> Signal:
        return wavetable(data, idx)

    k1 = graph_key(make_graph(dsp))
    k2 = graph_key(make_graph(dsp))
    assert k1 == k2


def test_wavetable_different_data_different_key() -> None:
    """Different wavetable data must produce different graph_key."""
    def dsp_a(idx: Signal) -> Signal:
        return wavetable([0.0, 1.0], idx)

    def dsp_b(idx: Signal) -> Signal:
        return wavetable([1.0, 0.0], idx)

    assert graph_key(make_graph(dsp_a)) != graph_key(make_graph(dsp_b))
