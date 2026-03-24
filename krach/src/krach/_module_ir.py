"""Module IR — frozen specification types for the krach audio graph.

ModuleIr is the canonical representation of a complete audio setup:
nodes, routing, patterns, controls, automations, transport. Three
construction paths produce the same type: @kr.module (trace),
kr.capture() (snapshot), ModuleIr.from_dict() (deserialize).

If it's not IR, it doesn't exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from krach.patterns.ir import IrNode

# Forward reference for DspDef (avoid circular import)
from krach._types import DspDef


@dataclass(frozen=True)
class NodeDef:
    """Specification of an audio node."""

    name: str
    source: Union[DspDef, str]  # DspDef or type_id string
    gain: float = 0.5
    count: int = 1
    init: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class PatternDef:
    """Specification of a pattern assignment."""

    target: str
    pattern: IrNode
    swing: float | None = None


@dataclass(frozen=True)
class ControlDef:
    """Specification of a control value."""

    path: str
    value: float


@dataclass(frozen=True)
class AutomationDef:
    """Specification of a native engine automation."""

    path: str
    shape: str
    lo: float
    hi: float
    bars: int


@dataclass(frozen=True)
class MutedDef:
    """Specification of a muted node with its saved gain."""

    name: str
    saved_gain: float


@dataclass(frozen=True)
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
