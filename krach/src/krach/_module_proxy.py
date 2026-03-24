"""Module tracing proxy — records calls as ModuleIr instead of executing.

Used by @kr.module and with kr.trace() to capture session setup as
frozen IR without starting audio.
"""

from __future__ import annotations

from krach._module_ir import (
    ControlDef,
    ModuleIr,
    MutedDef,
    NodeDef,
    PatternDef,
    RouteDef,
)
from krach._types import DspDef, DspSource, dsp
from krach.patterns.pattern import Pattern


class ModuleProxy:
    """Records mixer calls as ModuleIr defs. Does not produce audio."""

    def __init__(self) -> None:
        self._nodes: list[NodeDef] = []
        self._routing: list[RouteDef] = []
        self._patterns: list[PatternDef] = []
        self._controls: list[ControlDef] = []
        self._muted: list[MutedDef] = []
        self._tempo: float | None = None
        self._meter: float | None = None
        self._master: float | None = None
        self._node_names: set[str] = set()

    def node(self, name: str, source: DspSource, *, gain: float = 0.5, count: int = 1, **init: float) -> None:
        """Record a node definition."""
        # Resolve source to get type_id + metadata
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
        self._routing.append(RouteDef(source=source, target=target, kind="send", level=level))

    def wire(self, source: str, target: str, *, port: str = "in0") -> None:
        """Record a wire route."""
        self._routing.append(RouteDef(source=source, target=target, kind="wire", port=port))

    def connect(self, source: str, target: str, *, level: float = 1.0) -> None:
        """Record a send connection."""
        self.send(source, target, level=level)

    def play(
        self, target: str, pattern: Pattern, *,
        from_zero: bool = False, swing: float | None = None,
    ) -> None:
        """Record a pattern assignment."""
        self._patterns.append(PatternDef(target=target, pattern=pattern.node, swing=swing))

    def set(self, path: str, value: float) -> None:
        """Record a control value."""
        self._controls.append(ControlDef(path=path, value=value))

    def mute(self, name: str) -> None:
        """Record a mute."""
        # Find the node's gain to save
        gain = 0.5
        for nd in self._nodes:
            if nd.name == name:
                gain = nd.gain
                break
        self._muted.append(MutedDef(name=name, saved_gain=gain))

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

    def build(self) -> ModuleIr:
        """Finalize and return the recorded ModuleIr."""
        return ModuleIr(
            nodes=tuple(self._nodes),
            routing=tuple(self._routing),
            patterns=tuple(self._patterns),
            controls=tuple(self._controls),
            muted=tuple(self._muted),
            tempo=self._tempo,
            meter=self._meter,
            master=self._master,
        )
