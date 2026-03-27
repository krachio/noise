"""Tests for Commit 3 — Looper example traces to valid DspGraph."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from krach.signal.types import RwTableParams
from krach.signal.transpile import make_graph
from krach.backends.faust import emit_faust

# Load the example module from repo root
_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "looper.py"


def _load_looper_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("looper", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_looper_traces_with_rwtable() -> None:
    """The looper DSP function must trace to a graph containing rwtable."""
    mod = _load_looper_module()
    g = make_graph(mod.looper)
    rw_eqns = [e for e in g.equations if e.primitive.name == "rwtable"]
    assert len(rw_eqns) >= 1
    assert isinstance(rw_eqns[0].params, RwTableParams)


def test_looper_emits_valid_faust() -> None:
    """The looper must emit valid FAUST containing rwtable."""
    mod = _load_looper_module()
    src = emit_faust(make_graph(mod.looper))
    assert "rwtable(" in src
    assert "process" in src
