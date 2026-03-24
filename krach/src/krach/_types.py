"""Core data types for the audio graph.

- Node: a source or effect in the graph
- NodeSnapshot: frozen snapshot for scene storage
- Scene: complete mixer state snapshot
- DspDef: pre-transpiled DSP definition
- dsp(): decorator for pre-transpilation
"""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Union

from faust_dsl import transpile as _transpile
from krach.patterns.pattern import Pattern

# Type alias for DSP source parameters: string type_id, DspDef, or callable DSP function.
# The callable form accepts 0+ Signal args and returns a Signal.
# We use Callable[..., Any] because the transpiler handles signature inspection.
DspSource = Union[str, "DspDef", Callable[..., Any]]


@dataclass(frozen=True)
class NodeSnapshot:
    """Frozen snapshot of a Node's state for scene storage."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int = 0
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = ""


@dataclass(frozen=True)
class Scene:
    """Snapshot of the mixer state — nodes, sends, patterns, controls."""

    nodes: dict[str, NodeSnapshot]
    sends: dict[tuple[str, str], float]
    wires: dict[tuple[str, str], str]
    patterns: dict[str, Pattern]
    ctrl_values: dict[str, float]
    tempo: float
    master: float
    muted: dict[str, float]


@dataclass
class Node:
    """A node in the audio graph — source (num_inputs=0) or effect (num_inputs>0)."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int = 0
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = field(default="", repr=False)
    alloc: int = field(default=0, repr=False)


@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    controls: tuple[str, ...]
    num_inputs: int = 0


def dsp(fn: Callable[..., Any]) -> DspDef:
    """Decorator: captures Python source + pre-transpiles to FAUST."""
    source = textwrap.dedent(inspect.getsource(fn))
    result = _transpile(fn)  # type: ignore[arg-type]
    return DspDef(
        fn=fn,
        source=source,
        faust=result.source,
        controls=tuple(c.name for c in result.schema.controls),
        num_inputs=result.num_inputs,
    )
