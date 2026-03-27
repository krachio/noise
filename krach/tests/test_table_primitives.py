"""Tests for rwtable_p + rdtable_p primitives (Commit 1)."""

from __future__ import annotations

import pytest

from krach.signal.types import (
    RdTableParams,
    RwTableParams,
    Signal,
)
from krach.signal.trace import TraceContext, pop_trace, push_trace
from krach.signal.primitives import rdtable_p, rwtable_p
from krach.signal.transpile import make_graph
from krach.signal.core import rwtable, rdtable
from krach.backends.faust import emit_faust
from krach.ir.canonicalize import graph_key
from krach.ir.graph import dsp_graph_to_dict, dict_to_dsp_graph


def _make_ctx() -> TraceContext:
    return TraceContext()


def _with_ctx(ctx: TraceContext) -> object:
    class _CM:
        def __enter__(self) -> TraceContext:
            self._token = push_trace(ctx)
            return ctx
        def __exit__(self, *args: object) -> None:
            pop_trace(self._token)
    return _CM()


# ── Param validation ────────────────────────────────────────────────────


class TestRwTableParams:
    def test_valid(self) -> None:
        p = RwTableParams(size=1024)
        assert p.size == 1024

    def test_size_must_be_int(self) -> None:
        with pytest.raises(TypeError):
            RwTableParams(size=1024.5)  # type: ignore[arg-type]

    def test_size_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            RwTableParams(size=0)

    def test_size_max_2_24(self) -> None:
        RwTableParams(size=2**24)  # ok
        with pytest.raises(ValueError):
            RwTableParams(size=2**24 + 1)


class TestRdTableParams:
    def test_valid(self) -> None:
        p = RdTableParams(data=(1.0, 2.0, 3.0))
        assert p.data == (1.0, 2.0, 3.0)

    def test_frozen_hashable(self) -> None:
        p = RdTableParams(data=(1.0, 2.0))
        assert hash(p) == hash(RdTableParams(data=(1.0, 2.0)))

    def test_empty_data_rejected(self) -> None:
        with pytest.raises(ValueError):
            RdTableParams(data=())


# ── Primitive instances ─────────────────────────────────────────────────


def test_rwtable_primitive_is_stateful() -> None:
    assert rwtable_p.stateful is True
    assert rwtable_p.name == "rwtable"


def test_rdtable_primitive_is_stateful() -> None:
    assert rdtable_p.stateful is True
    assert rdtable_p.name == "rdtable"


# ── Tracing ─────────────────────────────────────────────────────────────


def test_rwtable_traces_equation() -> None:
    def dsp(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    g = make_graph(dsp)
    rw_eqns = [e for e in g.equations if e.primitive.name == "rwtable"]
    assert len(rw_eqns) == 1
    eqn = rw_eqns[0]
    assert isinstance(eqn.params, RwTableParams)
    assert eqn.params.size == 1024
    assert len(eqn.inputs) == 4
    assert len(eqn.outputs) == 1


def test_rdtable_traces_equation() -> None:
    data = (0.0, 0.5, 1.0, 0.5)

    def dsp(idx: Signal) -> Signal:
        return rdtable(data, idx)

    g = make_graph(dsp)
    rd_eqns = [e for e in g.equations if e.primitive.name == "rdtable"]
    assert len(rd_eqns) == 1
    eqn = rd_eqns[0]
    assert isinstance(eqn.params, RdTableParams)
    assert eqn.params.data == data
    assert len(eqn.inputs) == 1
    assert len(eqn.outputs) == 1


# ── Abstract eval ───────────────────────────────────────────────────────


def test_rwtable_abstract_eval() -> None:
    def dsp(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    g = make_graph(dsp)
    out = g.outputs[0]
    assert out.aval.channels == 1


def test_rdtable_abstract_eval() -> None:
    def dsp(idx: Signal) -> Signal:
        return rdtable((1.0, 2.0), idx)

    g = make_graph(dsp)
    out = g.outputs[0]
    assert out.aval.channels == 1


# ── FAUST lowering ──────────────────────────────────────────────────────


def test_rwtable_faust_lowering() -> None:
    def dsp(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    src = emit_faust(make_graph(dsp))
    assert "rwtable(1024" in src
    assert "int(" in src


def test_rdtable_faust_lowering() -> None:
    data = (0.0, 0.5, 1.0)

    def dsp(idx: Signal) -> Signal:
        return rdtable(data, idx)

    src = emit_faust(make_graph(dsp))
    assert "rdtable(3" in src
    assert "waveform{0.0, 0.5, 1.0}" in src
    assert "int(" in src


# ── Canonicalize distinctness ───────────────────────────────────────────


def test_rwtable_different_sizes_different_key() -> None:
    def dsp_a(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    def dsp_b(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(2048, init, w_idx, w_val, r_idx)

    assert graph_key(make_graph(dsp_a)) != graph_key(make_graph(dsp_b))


def test_rdtable_different_data_different_key() -> None:
    def dsp_a(idx: Signal) -> Signal:
        return rdtable((0.0, 1.0), idx)

    def dsp_b(idx: Signal) -> Signal:
        return rdtable((1.0, 0.0), idx)

    assert graph_key(make_graph(dsp_a)) != graph_key(make_graph(dsp_b))


def test_rwtable_same_fn_same_key() -> None:
    def dsp(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    assert graph_key(make_graph(dsp)) == graph_key(make_graph(dsp))


def test_rdtable_same_fn_same_key() -> None:
    data = (0.0, 0.5, 1.0)

    def dsp(idx: Signal) -> Signal:
        return rdtable(data, idx)

    assert graph_key(make_graph(dsp)) == graph_key(make_graph(dsp))


# ── Serialization round-trip ────────────────────────────────────────────


def test_rwtable_serialization_roundtrip() -> None:
    def dsp(init: Signal, w_idx: Signal, w_val: Signal, r_idx: Signal) -> Signal:
        return rwtable(1024, init, w_idx, w_val, r_idx)

    g = make_graph(dsp)
    d = dsp_graph_to_dict(g)
    reconstructed = dict_to_dsp_graph(d)
    from krach.ir.canonicalize import canonicalize
    assert canonicalize(g) == canonicalize(reconstructed)


def test_rdtable_serialization_roundtrip() -> None:
    data = (0.0, 0.5, 1.0, 0.5)

    def dsp(idx: Signal) -> Signal:
        return rdtable(data, idx)

    g = make_graph(dsp)
    d = dsp_graph_to_dict(g)
    reconstructed = dict_to_dsp_graph(d)
    from krach.ir.canonicalize import canonicalize
    assert canonicalize(g) == canonicalize(reconstructed)


# ── ALL_SIGNAL_PRIMITIVES completeness ──────────────────────────────────


def test_table_prims_in_all_signal_primitives() -> None:
    from krach.signal.primitives import ALL_SIGNAL_PRIMITIVES
    assert rwtable_p in ALL_SIGNAL_PRIMITIVES
    assert rdtable_p in ALL_SIGNAL_PRIMITIVES
