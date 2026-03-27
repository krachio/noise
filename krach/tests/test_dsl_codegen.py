"""Tests for Commit 2 — Lowering + codegen."""

from __future__ import annotations

import pytest

from krach.ir.signal import Signal
from krach.backends.faust import emit_faust
from krach.signal.core import faust_expr, feedback
from krach.signal.transpile import make_graph


def test_constant_emits_literal() -> None:
    graph = make_graph(lambda: 3.0)  # type: ignore[arg-type]
    source = emit_faust(graph)
    assert "3" in source


def test_add_emits_plus() -> None:
    def dsp(a: Signal, b: Signal) -> Signal:
        return a + b

    source = emit_faust(make_graph(dsp))
    assert "+" in source


def test_feedback_emits_tilde() -> None:
    def dsp() -> Signal:
        return feedback(lambda fb: fb * 0.5)

    source = emit_faust(make_graph(dsp))
    assert "~" in source


def test_process_line_present() -> None:
    def dsp(a: Signal) -> Signal:
        return a * 2.0

    source = emit_faust(make_graph(dsp))
    assert "process" in source


def test_stdfaust_import_present() -> None:
    def dsp(a: Signal) -> Signal:
        return a

    source = emit_faust(make_graph(dsp))
    assert 'import("stdfaust.lib")' in source


def test_multioutput_process_tuple() -> None:
    def dsp(a: Signal, b: Signal) -> tuple[Signal, Signal]:
        return a, b

    source = emit_faust(make_graph(dsp))
    # Two outputs -> process = ..., ...
    # The process line should contain a comma between the outputs
    process_line = [line for line in source.splitlines() if "process" in line]
    assert len(process_line) >= 1
    assert "," in process_line[0]


def test_faust_expr_missing_placeholder_raises() -> None:
    """faust_expr with fewer inputs than placeholders must raise."""
    def dsp(a: Signal) -> Signal:
        return faust_expr("{0} + {1}", a)  # {1} has no input

    with pytest.raises(ValueError, match="placeholder"):
        make_graph(dsp)
