"""Pattern binding — rewrite PatternNode trees to bind controls to nodes.

Uses generic fold/fold_with_state instead of per-type match arms.
"""

from __future__ import annotations

from krach.ir.pattern import (
    AtomParams,
    PatternNode,
)
from krach.ir.values import Control, Osc, OscStr
from krach.pattern.primitives import atom_p, freeze_p, fold, fold_with_state, stack_p


def bind_voice(node: PatternNode, voice: str) -> PatternNode:
    """Prepend ``voice/`` to bare Control/Osc labels in a pattern tree."""

    def _rewrite(nd: PatternNode, children: tuple[PatternNode, ...]) -> PatternNode:
        if nd.primitive == atom_p and isinstance(nd.params, AtomParams):
            val = nd.params.value
            if isinstance(val, Control) and "/" not in val.label:
                new_val = Control(label=f"{voice}/{val.label}", value=val.value)
                return PatternNode(atom_p, (), AtomParams(new_val))
            if isinstance(val, Osc):
                new_args = tuple(
                    OscStr(f"{voice}/{a.value}") if isinstance(a, OscStr) and "/" not in a.value else a
                    for a in val.args
                )
                return PatternNode(atom_p, (), AtomParams(Osc(val.address, new_args)))
        return PatternNode(nd.primitive, children, nd.params)

    return fold(node, _rewrite)


def bind_ctrl(node: PatternNode, label: str) -> PatternNode:
    """Replace ``"ctrl"`` placeholder with a concrete label."""

    def _rewrite(nd: PatternNode, children: tuple[PatternNode, ...]) -> PatternNode:
        if nd.primitive == atom_p and isinstance(nd.params, AtomParams):
            val = nd.params.value
            if isinstance(val, Control) and val.label == "ctrl":
                return PatternNode(atom_p, (), AtomParams(Control(label=label, value=val.value)))
            if isinstance(val, Osc):
                new_args = tuple(
                    OscStr(label) if isinstance(a, OscStr) and a.value == "ctrl" else a
                    for a in val.args
                )
                return PatternNode(atom_p, (), AtomParams(Osc(val.address, new_args)))
        return PatternNode(nd.primitive, children, nd.params)

    return fold(node, _rewrite)


def bind_voice_poly(
    node: PatternNode, parent: str, count: int, alloc: int,
) -> tuple[PatternNode, int]:
    """Bind a pattern to poly voices, round-robin allocating on Freeze boundaries.

    Freeze(Stack(children)): recurse into Stack children WITHOUT allocating
    (each child is a separate note in a chord, gets its own voice).
    Freeze(other): allocate a voice for this event.
    """

    def _visitor(
        nd: PatternNode,
        child_results: tuple[tuple[PatternNode, int], ...],
        state: int,
    ) -> tuple[PatternNode, int]:
        new_children = tuple(cr[0] for cr in child_results)

        # Freeze(Stack(...)): the special case — recurse into stack children
        # without allocating. Each inner Freeze allocates its own voice.
        if nd.primitive == freeze_p and len(new_children) == 1 and new_children[0].primitive == stack_p:
            return PatternNode(freeze_p, new_children, nd.params), state

        # Freeze(other): allocate a voice and bind
        if nd.primitive == freeze_p and len(new_children) == 1:
            inst = f"{parent}_v{state % count}"
            bound_child = bind_voice(new_children[0], inst)
            return PatternNode(freeze_p, (bound_child,), nd.params), state + 1

        # Non-freeze: reconstruct with rewritten children, pass state through
        return PatternNode(nd.primitive, new_children, nd.params), state

    return fold_with_state(node, alloc, _visitor)


def collect_control_labels(node: PatternNode) -> set[str]:
    """Extract all Control.label strings from a PatternNode tree."""
    labels: set[str] = set()

    def _visit(nd: PatternNode, _children: tuple[object, ...]) -> None:
        if nd.primitive == atom_p and isinstance(nd.params, AtomParams):
            val = nd.params.value
            if isinstance(val, Control):
                labels.add(val.label)

    fold(node, _visit)  # type: ignore[arg-type]
    return labels


def collect_control_values(node: PatternNode) -> list[float]:
    """Extract all Control.value floats from a PatternNode tree."""
    values: list[float] = []

    def _visit(nd: PatternNode, _children: tuple[object, ...]) -> None:
        if nd.primitive == atom_p and isinstance(nd.params, AtomParams):
            val = nd.params.value
            if isinstance(val, Control):
                values.append(val.value)

    fold(node, _visit)  # type: ignore[arg-type]
    return values
