"""Module IR — frozen specification types for the krach audio graph.

ModuleIr is the canonical representation of a complete audio setup:
nodes, routing, patterns, controls, automations, transport. Three
construction paths produce the same type: @kr.module (trace),
kr.capture() (snapshot), ModuleIr.from_dict() (deserialize).

If it's not IR, it doesn't exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from krach._types import DspDef
from krach.ir.pattern import PatternNode


@dataclass(frozen=True, slots=True)
class NodeDef:
    """Specification of an audio node."""

    name: str
    source: DspDef | str
    gain: float = 0.5
    count: int = 1
    num_inputs: int = 0
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = ""


@dataclass(frozen=True, slots=True)
class RouteDef:
    """Specification of an audio route between nodes.

    kind="send": gain-controlled send (level meaningful, port ignored)
    kind="wire": direct connection (port meaningful, level ignored)
    Port indexes by name; invalid port is an error at instantiation time.
    """

    source: str
    target: str
    kind: Literal["send", "wire"]
    level: float = 1.0
    port: str = "in0"


@dataclass(frozen=True, slots=True)
class PatternDef:
    """Specification of a pattern assignment."""

    target: str
    pattern: PatternNode
    swing: float | None = None


@dataclass(frozen=True, slots=True)
class ControlDef:
    """Specification of a control value."""

    path: str
    value: float


@dataclass(frozen=True, slots=True)
class AutomationDef:
    """Specification of a native engine automation."""

    path: str
    shape: str
    lo: float
    hi: float
    bars: int


@dataclass(frozen=True, slots=True)
class MutedDef:
    """Specification of a muted node with its saved gain."""

    name: str
    saved_gain: float


@dataclass(frozen=True, slots=True)
class ModuleIr:
    """Frozen specification of a complete audio setup.

    Immutable, serializable, diffable. The canonical representation
    of everything krach needs to reconstruct an audio session.
    """

    nodes: tuple[NodeDef, ...] = ()
    routing: tuple[RouteDef, ...] = ()
    patterns: tuple[PatternDef, ...] = ()
    controls: tuple[ControlDef, ...] = ()
    automations: tuple[AutomationDef, ...] = ()
    muted: tuple[MutedDef, ...] = ()
    tempo: float | None = None
    meter: float | None = None
    master: float | None = None
    sub_modules: tuple[tuple[str, ModuleIr], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        from krach.patterns.serialize import pattern_node_to_dict

        d: dict[str, Any] = {}
        if self.nodes:
            d["nodes"] = [
                {"name": n.name, "source": n.source if isinstance(n.source, str) else n.source.faust,
                 "gain": n.gain, "count": n.count, "num_inputs": n.num_inputs,
                 "init": list(n.init), "source_text": n.source_text}
                for n in self.nodes
            ]
        if self.routing:
            d["routing"] = [
                {"source": r.source, "target": r.target, "kind": r.kind,
                 "level": r.level, "port": r.port}
                for r in self.routing
            ]
        if self.patterns:
            d["patterns"] = [
                {"target": p.target, "pattern": pattern_node_to_dict(p.pattern),
                 **({"swing": p.swing} if p.swing is not None else {})}
                for p in self.patterns
            ]
        if self.controls:
            d["controls"] = [{"path": c.path, "value": c.value} for c in self.controls]
        if self.automations:
            d["automations"] = [
                {"path": a.path, "shape": a.shape, "lo": a.lo, "hi": a.hi, "bars": a.bars}
                for a in self.automations
            ]
        if self.muted:
            d["muted"] = [{"name": m.name, "saved_gain": m.saved_gain} for m in self.muted]
        if self.tempo is not None:
            d["tempo"] = self.tempo
        if self.meter is not None:
            d["meter"] = self.meter
        if self.master is not None:
            d["master"] = self.master
        if self.sub_modules:
            d["sub_modules"] = [
                {"prefix": prefix, "module": sub.to_dict()}
                for prefix, sub in self.sub_modules
            ]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ModuleIr:
        """Deserialize from a dict (inverse of to_dict)."""
        from krach.patterns.serialize import dict_to_pattern_node

        nodes = tuple(
            NodeDef(
                name=n["name"], source=n["source"], gain=n["gain"],
                count=n["count"], num_inputs=n.get("num_inputs", 0),
                init=tuple(tuple(x) for x in n["init"]),
                source_text=n.get("source_text", ""),
            )
            for n in d.get("nodes", ())
        )
        routing = tuple(
            RouteDef(
                source=r["source"], target=r["target"], kind=r["kind"],
                level=r["level"], port=r["port"],
            )
            for r in d.get("routing", ())
        )
        patterns = tuple(
            PatternDef(
                target=p["target"],
                pattern=dict_to_pattern_node(p["pattern"]),
                swing=p.get("swing"),
            )
            for p in d.get("patterns", ())
        )
        controls = tuple(
            ControlDef(path=c["path"], value=c["value"])
            for c in d.get("controls", ())
        )
        automations = tuple(
            AutomationDef(
                path=a["path"], shape=a["shape"],
                lo=a["lo"], hi=a["hi"], bars=a["bars"],
            )
            for a in d.get("automations", ())
        )
        muted = tuple(
            MutedDef(name=m["name"], saved_gain=m["saved_gain"])
            for m in d.get("muted", ())
        )
        sub_modules = tuple(
            (s["prefix"], ModuleIr.from_dict(s["module"]))
            for s in d.get("sub_modules", ())
        )
        return ModuleIr(
            nodes=nodes, routing=routing, patterns=patterns,
            controls=controls, automations=automations, muted=muted,
            tempo=d.get("tempo"), meter=d.get("meter"), master=d.get("master"),
            sub_modules=sub_modules,
        )
