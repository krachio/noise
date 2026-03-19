"""Tests for Commit 2 — Lowering + codegen."""

from __future__ import annotations

from faust_dsl._core import Signal
from faust_dsl._codegen import emit_faust
from faust_dsl._dsp import feedback
from faust_dsl.transpile import make_graph


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
