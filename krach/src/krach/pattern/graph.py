"""Graph IR types and builder for the audio engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol


def _node_controls() -> dict[str, float]:
    return {}


def _exposed_controls() -> dict[str, tuple[str, str]]:
    return {}


@dataclass(frozen=True)
class NodeInstance:
    id: str
    type_id: str
    controls: dict[str, float] = field(default_factory=_node_controls)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "type_id": self.type_id, "controls": dict(self.controls)}


@dataclass(frozen=True)
class ConnectionIr:
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from_node": self.from_node,
            "from_port": self.from_port,
            "to_node": self.to_node,
            "to_port": self.to_port,
        }


@dataclass(frozen=True)
class GraphIr:
    nodes: tuple[NodeInstance, ...]
    connections: tuple[ConnectionIr, ...]
    exposed_controls: dict[str, tuple[str, str]] = field(
        default_factory=_exposed_controls
    )

    def to_json(self) -> str:
        return json.dumps(
            {
                "nodes": [n.to_dict() for n in self.nodes],
                "connections": [c.to_dict() for c in self.connections],
                "exposed_controls": {
                    label: list(pair)
                    for label, pair in self.exposed_controls.items()
                },
            },
            separators=(",", ":"),
        )


class _ControlSpecLike(Protocol):
    @property
    def name(self) -> str: ...


class _ControlSchemaLike(Protocol):
    @property
    def controls(self) -> tuple[_ControlSpecLike, ...]: ...


class Graph:
    def __init__(self) -> None:
        self._nodes: list[NodeInstance] = []
        self._connections: list[ConnectionIr] = []
        self._exposed: dict[str, tuple[str, str]] = {}

    def node(self, id: str, type_id: str, **controls: float) -> Graph:
        self._nodes.append(NodeInstance(id=id, type_id=type_id, controls=dict(controls)))
        return self

    def connect(
        self, from_node: str, from_port: str, to_node: str, to_port: str
    ) -> Graph:
        self._connections.append(
            ConnectionIr(
                from_node=from_node,
                from_port=from_port,
                to_node=to_node,
                to_port=to_port,
            )
        )
        return self

    def expose(self, label: str, node_id: str, param: str) -> Graph:
        self._exposed[label] = (node_id, param)
        return self

    def expose_schema(self, node_id: str, schema: _ControlSchemaLike) -> Graph:
        for spec in schema.controls:
            self.expose(spec.name, node_id, spec.name)
        return self

    def build(self) -> GraphIr:
        ids = [n.id for n in self._nodes]
        seen: set[str] = set()
        for id in ids:
            if id in seen:
                raise ValueError(f"duplicate node id: {id!r}")
            seen.add(id)
        return GraphIr(
            nodes=tuple(self._nodes),
            connections=tuple(self._connections),
            exposed_controls=dict(self._exposed),
        )
