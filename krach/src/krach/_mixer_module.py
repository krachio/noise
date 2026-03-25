"""Mixer module operations — trace, capture, instantiate, export."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from krach.ir.module import ControlDef, ModuleIr, MutedDef, NodeDef, PatternDef, RouteDef
from krach._module_proxy import ModuleProxy
from krach.pattern.pattern import Pattern

if TYPE_CHECKING:
    from krach._types import Node
    from krach.pattern import Session


class MixerModuleMixin:
    """Mixin for module-related Mixer methods.

    Attrs declared here are defined on MixerInfra — this satisfies pyright
    without circular imports.
    """

    _scenes: dict[str, ModuleIr]
    _nodes: dict[str, Node]
    _sends: dict[tuple[str, str], float]
    _wires: dict[tuple[str, str], str]
    _muted: dict[str, float]
    _ctrl_values: dict[str, float]
    _patterns: dict[str, Pattern]
    _master_gain: float
    _session: Session
    _dsp_dir: Path
    _batching: bool

    def trace(self) -> ModuleProxy:
        """Return a tracing proxy that records calls as ModuleIr."""
        return ModuleProxy()

    def module(self, name: str) -> ModuleIr:
        """Get a saved module/scene by name."""
        if name not in self._scenes:
            raise ValueError(f"module '{name}' not found")
        return self._scenes[name]

    def load(self, path: str) -> None:
        """Load and execute a Python file with ``kr`` in scope."""
        from krach._scene import load_file
        load_file(path, {"kr": self, "mix": self})

    def capture(self) -> ModuleIr:
        """Snapshot current mixer state as a frozen ModuleIr."""
        nodes = tuple(
            NodeDef(
                name=name,
                source=node.type_id,
                gain=self._muted.get(name, node.gain),
                count=node.count,
                num_inputs=node.num_inputs,
                init=node.init,
                source_text=node.source_text,
            )
            for name, node in self._nodes.items()
        )
        routing: list[RouteDef] = []
        for (src, tgt), level in self._sends.items():
            routing.append(RouteDef(source=src, target=tgt, kind="send", level=level))
        for (src, tgt), port in self._wires.items():
            routing.append(RouteDef(source=src, target=tgt, kind="wire", port=port))

        controls = tuple(
            ControlDef(path=path, value=val)
            for path, val in self._ctrl_values.items()
        )
        muted = tuple(
            MutedDef(name=name, saved_gain=gain)
            for name, gain in self._muted.items()
        )
        try:
            tempo = float(self.tempo)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            tempo = None
        try:
            meter = float(self.meter)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            meter = None

        patterns = tuple(
            PatternDef(target=target, pattern=pat.node)
            for target, pat in self._patterns.items()
        )

        return ModuleIr(
            nodes=nodes,
            routing=tuple(routing),
            patterns=patterns,
            controls=controls,
            muted=muted,
            tempo=tempo,
            meter=meter,
            master=self._master_gain,
        )

    def instantiate(self, ir: ModuleIr) -> None:
        """Replay a ModuleIr onto this mixer. Batches all nodes into one rebuild."""
        with self.batch():  # type: ignore[attr-defined]
            for nd in ir.nodes:
                self.voice(nd.name, nd.source, gain=nd.gain, count=nd.count, **dict(nd.init))  # type: ignore[attr-defined]
                node = self._nodes[nd.name]
                if nd.num_inputs:
                    node.num_inputs = nd.num_inputs
                if nd.source_text:
                    node.source_text = nd.source_text

        for rd in ir.routing:
            if rd.kind == "send":
                self.send(rd.source, rd.target, level=rd.level)  # type: ignore[attr-defined]
            else:
                self.wire(rd.source, rd.target, port=rd.port)  # type: ignore[attr-defined]

        if ir.tempo is not None:
            self.tempo = ir.tempo  # type: ignore[attr-defined]
        if ir.meter is not None:
            self.meter = ir.meter  # type: ignore[attr-defined]
        if ir.master is not None:
            self.master = ir.master  # type: ignore[attr-defined]

        for cd in ir.controls:
            self.set(cd.path, cd.value)  # type: ignore[attr-defined]

        for pd in ir.patterns:
            self.play(pd.target, Pattern(pd.pattern))  # type: ignore[attr-defined]

        for md in ir.muted:
            self.mute(md.name)  # type: ignore[attr-defined]

    def export(self, path: str) -> None:
        """Export current session state to a reloadable Python script."""
        from krach._export import export_session
        try:
            tempo = float(self.tempo)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            tempo = 120.0
        try:
            meter = float(self.meter)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            meter = 4.0
        export_session(
            path, self._nodes, self._dsp_dir, self._sends, self._wires,
            self._patterns, self._ctrl_values, tempo, meter, self._master_gain,
        )
