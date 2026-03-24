"""Scene management — save, recall, and load session snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from krach._types import Node, NodeSnapshot, Scene

if TYPE_CHECKING:
    from krach.patterns.pattern import Pattern


def save_scene(
    nodes: dict[str, Node],
    sends: dict[tuple[str, str], float],
    wires: dict[tuple[str, str], str],
    patterns: dict[str, Pattern],
    ctrl_values: dict[str, float],
    tempo: float,
    master: float,
    muted: dict[str, float],
) -> Scene:
    """Create a frozen snapshot of the current mixer state."""
    return Scene(
        nodes={
            n: NodeSnapshot(
                type_id=v.type_id, gain=v.gain, controls=v.controls,
                num_inputs=v.num_inputs, count=v.count, init=v.init,
                source_text=v.source_text,
            )
            for n, v in nodes.items()
        },
        sends=dict(sends),
        wires=dict(wires),
        patterns=dict(patterns),
        ctrl_values=dict(ctrl_values),
        tempo=tempo,
        master=master,
        muted=dict(muted),
    )


def restore_scene(scene: Scene) -> dict[str, Node]:
    """Reconstruct nodes from a scene snapshot. Returns new nodes dict."""
    return {
        name: Node(
            type_id=snap.type_id, gain=snap.gain, controls=snap.controls,
            num_inputs=snap.num_inputs, count=snap.count, init=snap.init,
            source_text=snap.source_text,
        )
        for name, snap in scene.nodes.items()
    }


def load_file(path: str, context: dict[str, object]) -> None:
    """Load and execute a Python file with the given namespace."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"scene file not found: {path}")
    code = p.read_text()
    try:
        exec(compile(code, path, "exec"), context)  # noqa: S102
    except Exception as e:
        raise RuntimeError(f"error loading {path}: {e}") from e
