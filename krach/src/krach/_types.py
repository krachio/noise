"""Core data types for the audio graph.

- Node: a source or effect in the graph
- NodeSnapshot: frozen snapshot for scene storage
- Scene: complete mixer state snapshot
- DspDef: pre-transpiled DSP definition
- dsp(): decorator for pre-transpilation
- ResolvedPath: sum type for path disambiguation
- resolve_path(): single source of truth for path resolution
"""

from __future__ import annotations

import inspect
import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
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
    control_ranges: dict[str, tuple[float, float]] = field(default_factory=lambda: dict[str, tuple[float, float]]())
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
    control_ranges: dict[str, tuple[float, float]] = field(default_factory=lambda: dict[str, tuple[float, float]](), repr=False)


@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    controls: tuple[str, ...]
    num_inputs: int = 0
    control_ranges: dict[str, tuple[float, float]] = field(default_factory=lambda: dict[str, tuple[float, float]]())


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
        control_ranges={c.name: (c.lo, c.hi) for c in result.schema.controls},
    )


@dataclass(frozen=True)
class ResolvedSource:
    """Result of resolving a DSP source."""
    type_id: str
    controls: tuple[str, ...]
    source_text: str
    control_ranges: dict[str, tuple[float, float]]


def resolve_dsp_source(
    name: str,
    source: DspSource,
    dsp_dir: Path,
    node_controls: dict[str, tuple[str, ...]],
    fallback_controls: tuple[str, ...] = (),
    wait: Callable[..., None] | None = None,
) -> ResolvedSource:
    """Resolve a DSP source to type_id, controls, source_text, and control ranges."""
    ranges: dict[str, tuple[float, float]] = {}
    if isinstance(source, DspDef):
        type_id = f"faust:{name}"
        source_text = source.source
        faust_code, controls = source.faust, source.controls
        ranges = source.control_ranges
    elif callable(source):
        type_id = f"faust:{name}"
        source_text = textwrap.dedent(inspect.getsource(source))
        result = _transpile(source)  # type: ignore[arg-type]
        faust_code = result.source
        controls = tuple(c.name for c in result.schema.controls)
        ranges = {c.name: (c.lo, c.hi) for c in result.schema.controls}
    else:
        return ResolvedSource(
            source, node_controls.get(source, fallback_controls), "", {},
        )
    py_path = dsp_dir.joinpath(f"{name}.py")
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(source_text)
    dsp_path = dsp_dir.joinpath(f"{name}.dsp")
    dsp_path.parent.mkdir(parents=True, exist_ok=True)
    dsp_path.write_text(faust_code)
    node_controls[type_id] = controls
    if wait is not None:
        wait(type_id)
    return ResolvedSource(type_id, controls, source_text, ranges)


# ── Path resolution ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodePath:
    """Exact node name match."""
    name: str


@dataclass(frozen=True)
class ControlPath:
    """Node + param, resolved to engine label."""
    node: str
    param: str
    label: str


@dataclass(frozen=True)
class GroupPath:
    """Prefix matching multiple nodes."""
    prefix: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class UnknownPath:
    """No node, control, or group match."""
    raw: str


type ResolvedPath = NodePath | ControlPath | GroupPath | UnknownPath


def _make_label(node: str, param: str) -> str:
    """Convert user-facing node/param to engine control label."""
    if param.endswith("_send"):
        target = param[: -len("_send")]
        return f"{node}_send_{target}/gain"
    return f"{node}/{param}"


def resolve_path(path: str, nodes: Mapping[str, object]) -> ResolvedPath:
    """Single source of truth for path disambiguation.

    Priority (longest node-name match wins):
    1. Exact node name → NodePath
    2. Rightmost split where left side is a node → ControlPath
    3. Prefix matching multiple nodes → GroupPath
    4. Nothing → UnknownPath
    """
    # 1. Exact node name (handles slashed names like "drums/kick")
    if path in nodes:
        return NodePath(path)

    # 2. Try splits from right to find longest matching node name.
    #    "a/b/c/param" tries "a/b/c" first, then "a/b", then "a".
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        node_name = "/".join(parts[:i])
        param = "/".join(parts[i:])
        if node_name in nodes:
            return ControlPath(node_name, param, _make_label(node_name, param))

    # 3. Group prefix
    prefix = path + "/"
    members = tuple(n for n in nodes if n.startswith(prefix))
    if members:
        return GroupPath(path, members)

    # 4. Not found
    return UnknownPath(path)


# ── DSP file parsing ──────────────────────────────────────────────────────

_HSLIDER_RE = re.compile(r'hslider\("([^"]+)"')


def parse_dsp_controls(source: str) -> tuple[str, ...]:
    """Extract deduplicated hslider control names from a FAUST .dsp source string."""
    seen: dict[str, None] = {}
    for name in _HSLIDER_RE.findall(source):
        seen[name] = None
    return tuple(seen)
