"""Tests for dsp() memoization — bounded LRU by source text hash."""

from __future__ import annotations

from krach.graph.node import dsp, dsp_cache_clear, dsp_cache_info
import krach.dsp as krs


def _make_fn(freq_default: float):
    """Create a DSP function with a specific freq default (different source each time)."""
    def synth() -> krs.Signal:
        freq = krs.control("freq", freq_default, 20.0, 20000.0)
        gate = krs.control("gate", 0.0, 0.0, 1.0)
        return krs.saw(freq) * gate
    return synth


class TestDspCache:
    def setup_method(self) -> None:
        dsp_cache_clear()

    def test_same_function_hits_cache(self) -> None:
        fn = _make_fn(440.0)
        a = dsp(fn)
        b = dsp(fn)
        assert a.faust == b.faust
        info = dsp_cache_info()
        assert info["hits"] >= 1

    def test_different_source_misses_cache(self) -> None:
        fn1 = _make_fn(440.0)
        fn2 = _make_fn(220.0)
        a = dsp(fn1)
        b = dsp(fn2)
        assert a.faust != b.faust
        info = dsp_cache_info()
        assert info["misses"] >= 2

    def test_redefined_function_different_faust(self) -> None:
        """Redefining a function (new source text) produces different Faust output."""
        fn1 = _make_fn(440.0)
        fn2 = _make_fn(880.0)
        a = dsp(fn1)
        b = dsp(fn2)
        assert "440" in a.faust
        assert "880" in b.faust

    def test_cache_hit_produces_identical_faust(self) -> None:
        """Cache hit returns byte-identical .dsp output (Kai's 9/10 requirement)."""
        fn = _make_fn(440.0)
        a = dsp(fn)
        b = dsp(fn)
        assert a.faust == b.faust
        assert a.controls == b.controls
        assert a.control_ranges == b.control_ranges

    def test_explicit_source_overrides_getsource(self) -> None:
        """When source is provided explicitly, it's used as cache key."""
        fn = _make_fn(440.0)
        src = "def synth():\n    return krs.saw(krs.control('freq', 440.0, 20.0, 20000.0))\n"
        a = dsp(fn, source=src)
        b = dsp(fn, source=src)
        assert a.faust == b.faust
        info = dsp_cache_info()
        assert info["hits"] >= 1

    def test_cache_bounded(self) -> None:
        """Cache evicts entries when exceeding max size."""
        # Create many unique functions to exceed cache
        for i in range(70):
            fn = _make_fn(float(100 + i))
            dsp(fn)
        info = dsp_cache_info()
        assert info["size"] <= 64

    def test_cache_clear(self) -> None:
        fn = _make_fn(440.0)
        dsp(fn)
        assert dsp_cache_info()["size"] > 0
        dsp_cache_clear()
        assert dsp_cache_info()["size"] == 0
