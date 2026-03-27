"""Graph tracing proxy — records calls as GraphIr instead of executing.

Used by @kr.graph and with kr.trace() to capture session setup as
frozen IR without starting audio.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Concatenate, ParamSpec

from krach.ir.graph import (
    ControlDef,
    GraphIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
    prefix_ir,
)
from krach.node_types import DspDef, DspSource, dsp
from krach.pattern.pattern import Pattern


@dataclass(frozen=True, slots=True)
class SubGraphRef:
    """Reference to a sub-module registered in a GraphProxy."""

    prefix: str
    ir: GraphIr

    def input(self, name: str) -> str:
        """Return prefixed path for a declared input port."""
        if self.ir.inputs is None:
            raise ValueError(f"{self.prefix!r} has no declared inputs")
        if name not in self.ir.inputs:
            raise ValueError(f"{name!r} not in {self.prefix!r} inputs: {self.ir.inputs}")
        return f"{self.prefix}/{name}"

    def output(self, name: str) -> str:
        """Return prefixed path for a declared output port."""
        if self.ir.outputs is None:
            raise ValueError(f"{self.prefix!r} has no declared outputs")
        if name not in self.ir.outputs:
            raise ValueError(f"{name!r} not in {self.prefix!r} outputs: {self.ir.outputs}")
        return f"{self.prefix}/{name}"

    def __repr__(self) -> str:
        inputs = list(self.ir.inputs) if self.ir.inputs else []
        outputs = list(self.ir.outputs) if self.ir.outputs else []
        return f"SubGraphRef({self.prefix!r}, inputs={inputs}, outputs={outputs})"


class GraphProxy:
    """Records mixer calls as GraphIr defs. Does not produce audio."""

    def __init__(self) -> None:
        self._nodes: list[NodeDef] = []
        self._routing: list[RouteDef] = []
        self._patterns: list[PatternDef] = []
        self._controls: list[ControlDef] = []
        self._muted: list[MutedDef] = []
        self._sub_graphs: list[tuple[str, GraphIr]] = []
        self._tempo: float | None = None
        self._meter: float | None = None
        self._master: float | None = None
        self._node_names: set[str] = set()
        self._inputs: tuple[str, ...] | None = None
        self._outputs: tuple[str, ...] | None = None
        self._inputs_set: bool = False
        self._outputs_set: bool = False
        self._frozen: bool = False

    def _check_frozen(self) -> None:
        """Raise if proxy is frozen after build()."""
        if self._frozen:
            raise RuntimeError("GraphProxy is frozen after build()")

    def node(self, name: str, source: DspSource, *, gain: float = 0.5, count: int = 1, **init: float) -> None:
        """Record a node definition."""
        self._check_frozen()
        if callable(source) and not isinstance(source, (str, DspDef)):
            dsp_def = dsp(source)
            source_str = dsp_def.faust
            num_inputs = dsp_def.num_inputs
            source_text = dsp_def.source
        elif isinstance(source, DspDef):
            source_str = source.faust
            num_inputs = source.num_inputs
            source_text = source.source
        else:
            source_str = str(source)
            num_inputs = 0
            source_text = ""

        self._nodes.append(NodeDef(
            name=name, source=source_str, gain=gain, count=count,
            num_inputs=num_inputs, init=tuple(init.items()), source_text=source_text,
        ))
        self._node_names.add(name)

    def voice(self, name: str, source: DspSource, *, gain: float = 0.5, count: int = 1, **init: float) -> None:
        """Alias for node()."""
        self.node(name, source, gain=gain, count=count, **init)

    def send(self, source: str, target: str, *, level: float = 1.0) -> None:
        """Record a send route."""
        self._check_frozen()
        self._routing.append(RouteDef(source=source, target=target, kind="send", level=level))

    def wire(self, source: str, target: str, *, port: str = "in0") -> None:
        """Record a wire route."""
        self._check_frozen()
        self._routing.append(RouteDef(source=source, target=target, kind="wire", port=port))

    def connect(self, source: str, target: str, *, level: float = 1.0) -> None:
        """Record a send connection."""
        self.send(source, target, level=level)

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Record a pattern assignment."""
        self._check_frozen()
        self._patterns.append(PatternDef(target=target, pattern=pattern.node, swing=swing))

    def set(self, path: str, value: float) -> None:
        """Record a control value."""
        self._check_frozen()
        self._controls.append(ControlDef(path=path, value=value))

    def mute(self, name: str) -> None:
        """Record a mute."""
        self._check_frozen()
        gain = 0.5
        for nd in self._nodes:
            if nd.name == name:
                gain = nd.gain
                break
        self._muted.append(MutedDef(name=name, saved_gain=gain))

    def inputs(self, *names: str) -> None:
        """Declare input ports. Single call only."""
        self._check_frozen()
        if self._inputs_set:
            raise RuntimeError("inputs() already called")
        self._inputs = names
        self._inputs_set = True

    def outputs(self, *names: str) -> None:
        """Declare output ports. Single call only."""
        self._check_frozen()
        if self._outputs_set:
            raise RuntimeError("outputs() already called")
        self._outputs = names
        self._outputs_set = True

    def sub(self, prefix: str, ir: GraphIr) -> SubGraphRef:
        """Register a sub-module and return a reference for routing."""
        self._check_frozen()
        self._sub_graphs.append((prefix, ir))
        # Add prefixed node names for route validation
        prefixed = prefix_ir(ir, prefix)
        from krach.ir.graph import flatten
        flat = flatten(prefixed)
        for nd in flat.nodes:
            self._node_names.add(nd.name)
        return SubGraphRef(prefix=prefix, ir=ir)

    @property
    def tempo(self) -> float:
        return self._tempo or 120.0

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self._tempo = bpm

    @property
    def meter(self) -> float:
        return self._meter or 4.0

    @meter.setter
    def meter(self, beats: float) -> None:
        self._meter = beats

    @property
    def master(self) -> float:
        return self._master or 0.7

    @master.setter
    def master(self, value: float) -> None:
        self._master = value

    def build(self) -> GraphIr:
        """Finalize and return the recorded GraphIr."""
        # Validate route targets
        for route in self._routing:
            if route.target not in self._node_names:
                raise ValueError(
                    f"route target {route.target!r} not found in "
                    f"local nodes or sub_module nodes: {sorted(self._node_names)}"
                )

        self._frozen = True
        return GraphIr(
            nodes=tuple(self._nodes),
            routing=tuple(self._routing),
            patterns=tuple(self._patterns),
            controls=tuple(self._controls),
            muted=tuple(self._muted),
            tempo=self._tempo,
            meter=self._meter,
            master=self._master,
            inputs=self._inputs,
            outputs=self._outputs,
            sub_graphs=tuple(self._sub_graphs),
        )


# ---------------------------------------------------------------------------
# @graph — trace imperative code into frozen GraphIr
# ---------------------------------------------------------------------------

P = ParamSpec("P")


def graph(fn: Callable[Concatenate[GraphProxy, P], None]) -> Callable[P, GraphIr]:
    """Decorator that traces a function into a frozen GraphIr."""
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> GraphIr:
        proxy = GraphProxy()
        fn(proxy, *args, **kwargs)
        return proxy.build()

    # Fix signature: strip the first parameter (proxy)
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())[1:]  # skip proxy
    wrapper.__signature__ = sig.replace(parameters=params, return_annotation=GraphIr)  # type: ignore[attr-defined]
    return wrapper
