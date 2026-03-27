"""Core data types for the audio graph.

- Node: a source or effect in the graph
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
from typing import TYPE_CHECKING, Any, Callable, Protocol as _Protocol, Union

if TYPE_CHECKING:
    from krach.backends.graph import GraphIr as _GraphIr

from krach.ir.canonicalize import graph_key as _graph_key
from krach.signal.types import DspGraph

# Type alias for DSP source parameters: string type_id, DspDef, or callable DSP function.
# The callable form accepts 0+ Signal args and returns a Signal.
# We use Callable[..., Any] because the transpiler handles signature inspection.
DspSource = Union[str, "DspDef", Callable[..., Any]]


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
    control_defaults: dict[str, float] = field(default_factory=lambda: dict[str, float](), repr=False)


@dataclass(frozen=True)
class DspDef:
    """A pre-transpiled DSP definition created by the ``@dsp`` decorator."""

    fn: Callable[..., Any]
    source: str
    faust: str
    graph: DspGraph
    controls: tuple[str, ...]
    num_inputs: int = 0
    control_ranges: dict[str, tuple[float, float]] = field(default_factory=lambda: dict[str, tuple[float, float]]())
    control_defaults: dict[str, float] = field(default_factory=lambda: dict[str, float]())


_DSP_CACHE_MAX = 64
_dsp_cache: dict[int, DspDef] = {}
_dsp_cache_order: list[int] = []  # LRU order (oldest first)
_dsp_cache_hits = 0
_dsp_cache_misses = 0


def dsp_cache_clear() -> None:
    """Clear the dsp() transpilation cache."""
    global _dsp_cache_hits, _dsp_cache_misses  # noqa: PLW0603
    _dsp_cache.clear()
    _dsp_cache_order.clear()
    _dsp_cache_hits = 0
    _dsp_cache_misses = 0


def dsp_cache_info() -> dict[str, int]:
    """Return cache statistics."""
    return {"size": len(_dsp_cache), "hits": _dsp_cache_hits, "misses": _dsp_cache_misses}


def dsp(fn: Callable[..., Any], source: str = "") -> DspDef:
    """Transpile a Python DSP function to a DspDef with memoization.

    Cache keyed by graph_key (structural hash of the DspGraph).
    Same computation → same graph_key → cache hit. Bounded LRU.
    """
    global _dsp_cache_hits, _dsp_cache_misses  # noqa: PLW0603
    from krach.signal.transpile import make_graph
    from krach.backends.faust import emit_faust

    graph = make_graph(fn)  # type: ignore[arg-type]
    key = _graph_key(graph)

    if key in _dsp_cache:
        _dsp_cache_hits += 1
        if key in _dsp_cache_order:
            _dsp_cache_order.remove(key)
        _dsp_cache_order.append(key)
        return _dsp_cache[key]
    _dsp_cache_misses += 1

    faust = emit_faust(graph)

    # Collect control schema from graph
    from krach.signal.transpile import collect_controls
    controls_spec = collect_controls(graph)

    # Source text for export/persistence (best-effort, not part of cache key)
    if not source:
        try:
            source = textwrap.dedent(inspect.getsource(fn))
        except (OSError, TypeError):
            source = ""

    dsp_def = DspDef(
        fn=fn,
        source=source,
        faust=faust,
        graph=graph,
        controls=tuple(c.name for c in controls_spec),
        num_inputs=len(graph.inputs),
        control_ranges={c.name: (c.lo, c.hi) for c in controls_spec},
        control_defaults={c.name: c.init for c in controls_spec},
    )

    _dsp_cache[key] = dsp_def
    _dsp_cache_order.append(key)
    while len(_dsp_cache) > _DSP_CACHE_MAX:
        evicted = _dsp_cache_order.pop(0)
        _dsp_cache.pop(evicted, None)

    return dsp_def


@dataclass(frozen=True)
class ResolvedSource:
    """Result of resolving a DSP source."""
    type_id: str
    controls: tuple[str, ...]
    source_text: str
    control_ranges: dict[str, tuple[float, float]]
    control_defaults: dict[str, float] = field(default_factory=lambda: dict[str, float]())


def resolve_dsp_source(
    name: str,
    source: DspSource,
    dsp_dir: Path,
    node_controls: dict[str, tuple[str, ...]],
    fallback_controls: tuple[str, ...] = (),
    wait: Callable[..., None] | None = None,
) -> ResolvedSource:
    """Resolve a DSP source to type_id, controls, source_text, and control ranges."""
    if isinstance(source, DspDef):
        dsp_def = source
    elif callable(source):
        dsp_def = dsp(source)
    else:
        return ResolvedSource(
            source, node_controls.get(source, fallback_controls), "", {},
        )
    type_id = f"faust:{name}"
    if dsp_def.source:
        py_path = dsp_dir.joinpath(f"{name}.py")
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(dsp_def.source)
    dsp_path = dsp_dir.joinpath(f"{name}.dsp")
    dsp_path.parent.mkdir(parents=True, exist_ok=True)
    dsp_path.write_text(dsp_def.faust)
    node_controls[type_id] = dsp_def.controls
    if wait is not None:
        wait(type_id)
    return ResolvedSource(
        type_id, dsp_def.controls, dsp_def.source,
        dsp_def.control_ranges, dsp_def.control_defaults,
    )


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


# ── Graph IR builder ─────────────────────────────────────────────────────


def inst_name(name: str, i: int, count: int) -> str:
    """Instance name: ``name_v{i}`` if count > 1, else ``name``."""
    return f"{name}_v{i}" if count > 1 else name


class _NodeLike(_Protocol):
    """Protocol for Node-like objects (avoids circular import with mixer)."""

    type_id: str
    gain: float
    controls: tuple[str, ...]
    num_inputs: int
    count: int
    init: tuple[tuple[str, float], ...]


def build_graph_ir(
    nodes: Mapping[str, _NodeLike],
    sends: dict[tuple[str, str], float] | None = None,
    wires: dict[tuple[str, str], str] | None = None,
) -> _GraphIr:
    """Build a complete audio graph IR from nodes, sends, and wires."""
    from krach.backends.graph import Graph

    _sources = {n: v for n, v in nodes.items() if v.num_inputs == 0}
    _effects = {n: v for n, v in nodes.items() if v.num_inputs > 0}
    _sends = sends or {}
    _wires = wires or {}

    builder = Graph()
    builder.node("out", "dac")

    for name, node in _sources.items():
        for i in range(node.count):
            inst = inst_name(name, i, node.count)
            per_gain = node.gain / node.count
            builder.node(inst, node.type_id, **dict(node.init))
            builder.node(f"{inst}_g", "gain", gain=per_gain)
            builder.connect(inst, "out", f"{inst}_g", "in")
            builder.connect(f"{inst}_g", "out", "out", "in")
            for param in node.controls:
                builder.expose(f"{inst}/{param}", inst, param)
            builder.expose(f"{inst}/gain", f"{inst}_g", "gain")

    poly_with_routing: set[str] = set()
    for src_name, _tgt in [*_sends.keys(), *_wires.keys()]:
        n = _sources.get(src_name)
        if n is not None and n.count > 1:
            poly_with_routing.add(src_name)

    for parent in poly_with_routing:
        node = _sources[parent]
        builder.node(f"{parent}_sum", "gain", gain=1.0)
        for i in range(node.count):
            builder.connect(f"{parent}_v{i}", "out", f"{parent}_sum", "in")

    for name, node in _effects.items():
        builder.node(name, node.type_id)
        builder.node(f"{name}_g", "gain", gain=node.gain)
        builder.connect(name, "out", f"{name}_g", "in")
        builder.connect(f"{name}_g", "out", "out", "in")
        for param in node.controls:
            builder.expose(f"{name}/{param}", name, param)
        builder.expose(f"{name}/gain", f"{name}_g", "gain")

    for (src_name, tgt_name), level in _sends.items():
        source = f"{src_name}_sum" if src_name in poly_with_routing else src_name
        send_id = f"{src_name}_send_{tgt_name}"
        builder.node(send_id, "gain", gain=level)
        builder.connect(source, "out", send_id, "in")
        builder.connect(send_id, "out", tgt_name, "in")
        builder.expose(f"{send_id}/gain", send_id, "gain")

    for (src_name, tgt_name), port in _wires.items():
        source = f"{src_name}_sum" if src_name in poly_with_routing else src_name
        builder.connect(source, "out", tgt_name, port)

    return builder.build()
