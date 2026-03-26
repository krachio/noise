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

from krach.ir.pattern import PatternNode
from krach.ir.primitive import Primitive
from krach.ir.signal import (
    ConstParams,
    ControlParams,
    DelayParams,
    DspGraph,
    Equation,
    FaustExprParams,
    FeedbackParams,
    NoParams,
    Precision,
    Signal,
    SignalType,
)


@dataclass(frozen=True, slots=True)
class NodeDef:
    """Specification of an audio node."""

    name: str
    source: DspGraph | str
    gain: float = 0.5
    count: int = 1
    num_inputs: int = 0
    init: tuple[tuple[str, float], ...] = ()
    source_text: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.source, DspGraph) and self.num_inputs == 0:
            object.__setattr__(self, "num_inputs", len(self.source.inputs))


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
    inputs: tuple[str, ...] | None = None
    outputs: tuple[str, ...] | None = None
    sub_modules: tuple[tuple[str, ModuleIr], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        from krach.pattern.serialize import pattern_node_to_dict

        d: dict[str, Any] = {}
        if self.nodes:
            d["nodes"] = [_node_def_to_dict(n) for n in self.nodes]
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
        if self.inputs is not None:
            d["inputs"] = list(self.inputs)
        if self.outputs is not None:
            d["outputs"] = list(self.outputs)
        if self.sub_modules:
            d["sub_modules"] = [
                {"prefix": prefix, "module": sub.to_dict()}
                for prefix, sub in self.sub_modules
            ]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ModuleIr:
        """Deserialize from a dict (inverse of to_dict)."""
        from krach.pattern.serialize import dict_to_pattern_node

        nodes = tuple(_dict_to_node_def(n) for n in d.get("nodes", ()))
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
        inputs: tuple[str, ...] | None = None
        if "inputs" in d:
            inputs = tuple(d["inputs"])
        outputs: tuple[str, ...] | None = None
        if "outputs" in d:
            outputs = tuple(d["outputs"])
        return ModuleIr(
            nodes=nodes, routing=routing, patterns=patterns,
            controls=controls, automations=automations, muted=muted,
            tempo=d.get("tempo"), meter=d.get("meter"), master=d.get("master"),
            inputs=inputs, outputs=outputs, sub_modules=sub_modules,
        )


# ---------------------------------------------------------------------------
# DspGraph serialization
# ---------------------------------------------------------------------------

_PRECISION_MAP = {Precision.FLOAT32: "float", Precision.FLOAT64: "double"}
_PRECISION_REV = {v: k for k, v in _PRECISION_MAP.items()}


def _signal_to_dict(s: Signal) -> dict[str, Any]:
    return {"id": s.id, "channels": s.aval.channels, "precision": _PRECISION_MAP[s.aval.precision]}


def _dict_to_signal(d: dict[str, Any]) -> Signal:
    return Signal(
        aval=SignalType(channels=d["channels"], precision=_PRECISION_REV[d["precision"]]),
        id=d["id"], owner_id=0,
    )


def _params_to_dict(p: NoParams | ConstParams | DelayParams | FeedbackParams | FaustExprParams | ControlParams) -> dict[str, Any]:
    match p:
        case NoParams():
            return {"type": "no"}
        case ConstParams(value=v):
            return {"type": "const", "value": v}
        case DelayParams():
            return {"type": "delay"}
        case FaustExprParams(template=t):
            return {"type": "faust_expr", "template": t}
        case ControlParams(name=n, init=i, lo=lo, hi=hi, step=s):
            return {"type": "control", "name": n, "init": i, "lo": lo, "hi": hi, "step": s}
        case FeedbackParams(body_graph=bg, feedback_input_index=idx, free_var_signals=fvs):
            return {
                "type": "feedback",
                "body_graph": dsp_graph_to_dict(bg),
                "feedback_input_index": idx,
                "free_var_signals": [_signal_to_dict(s) for s in fvs],
            }
        case _:
            raise TypeError(f"unhandled params type: {type(p).__name__}")


def _dict_to_params(d: dict[str, Any]) -> NoParams | ConstParams | DelayParams | FeedbackParams | FaustExprParams | ControlParams:
    match d["type"]:
        case "no":
            return NoParams()
        case "const":
            return ConstParams(value=d["value"])
        case "delay":
            return DelayParams()
        case "faust_expr":
            return FaustExprParams(template=d["template"])
        case "control":
            return ControlParams(name=d["name"], init=d["init"], lo=d["lo"], hi=d["hi"], step=d["step"])
        case "feedback":
            return FeedbackParams(
                body_graph=dict_to_dsp_graph(d["body_graph"]),
                feedback_input_index=d["feedback_input_index"],
                free_var_signals=tuple(_dict_to_signal(s) for s in d["free_var_signals"]),
            )
        case _:
            raise ValueError(f"unknown params type: {d['type']!r}")


def dsp_graph_to_dict(graph: DspGraph) -> dict[str, Any]:
    """Serialize a DspGraph to a JSON-friendly dict."""
    return {
        "type": "dsp_graph",
        "inputs": [_signal_to_dict(s) for s in graph.inputs],
        "outputs": [_signal_to_dict(s) for s in graph.outputs],
        "equations": [
            {
                "primitive": {"name": e.primitive.name, "stateful": e.primitive.stateful},
                "inputs": [_signal_to_dict(s) for s in e.inputs],
                "outputs": [_signal_to_dict(s) for s in e.outputs],
                "params": _params_to_dict(e.params),
            }
            for e in graph.equations
        ],
        "precision": _PRECISION_MAP[graph.precision],
    }


def dict_to_dsp_graph(d: dict[str, Any]) -> DspGraph:
    """Deserialize a DspGraph from a dict."""
    return DspGraph(
        inputs=tuple(_dict_to_signal(s) for s in d["inputs"]),
        outputs=tuple(_dict_to_signal(s) for s in d["outputs"]),
        equations=tuple(
            Equation(
                primitive=Primitive(name=e["primitive"]["name"], stateful=e["primitive"]["stateful"]),
                inputs=tuple(_dict_to_signal(s) for s in e["inputs"]),
                outputs=tuple(_dict_to_signal(s) for s in e["outputs"]),
                params=_dict_to_params(e["params"]),
            )
            for e in d["equations"]
        ),
        precision=_PRECISION_REV[d["precision"]],
    )


# ---------------------------------------------------------------------------
# NodeDef serialization helpers
# ---------------------------------------------------------------------------


def _node_def_to_dict(n: NodeDef) -> dict[str, Any]:
    if isinstance(n.source, DspGraph):
        source: Any = dsp_graph_to_dict(n.source)
    else:
        source = n.source
    return {
        "name": n.name, "source": source, "gain": n.gain, "count": n.count,
        "num_inputs": n.num_inputs, "init": list(n.init), "source_text": n.source_text,
    }


def _dict_to_node_def(d: dict[str, Any]) -> NodeDef:
    raw_source = d["source"]
    source: DspGraph | str
    if isinstance(raw_source, dict):
        source = dict_to_dsp_graph(raw_source)  # type: ignore[arg-type]
    else:
        source = str(raw_source)
    return NodeDef(
        name=d["name"], source=source, gain=d["gain"],
        count=d["count"], num_inputs=d.get("num_inputs", 0),
        init=tuple(tuple(x) for x in d["init"]),
        source_text=d.get("source_text", ""),
    )
