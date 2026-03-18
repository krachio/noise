from typing import Protocol

from soundman_frontend.ir import ConnectionIr, GraphIr, NodeInstance


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

    def node(self, id: str, type_id: str, **controls: float) -> "Graph":
        self._nodes.append(NodeInstance(id=id, type_id=type_id, controls=dict(controls)))
        return self

    def connect(self, from_node: str, from_port: str, to_node: str, to_port: str) -> "Graph":
        self._connections.append(
            ConnectionIr(
                from_node=from_node,
                from_port=from_port,
                to_node=to_node,
                to_port=to_port,
            )
        )
        return self

    def expose(self, label: str, node_id: str, param: str) -> "Graph":
        self._exposed[label] = (node_id, param)
        return self

    def expose_schema(self, node_id: str, schema: _ControlSchemaLike) -> "Graph":
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
