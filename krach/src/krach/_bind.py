"""IR tree rewriting — bind bare parameters to node/control paths.

Provides a generic ``map_atoms`` walker and concrete binders:
- ``bind_voice``: prepend ``node_name/`` to bare Control/Osc labels
- ``bind_voice_poly``: round-robin bind to poly node instances
- ``bind_ctrl``: replace ``"ctrl"`` placeholder with a concrete label
"""

from __future__ import annotations

from typing import Callable

from krach.patterns.ir import (
    Atom,
    Cat,
    Control,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Freeze,
    IrNode,
    Late,
    Osc,
    OscStr,
    Rev,
    Silence,
    Slow,
    Stack,
    Warp,
)


def map_atoms(node: IrNode, fn: Callable[[IrNode], IrNode]) -> IrNode:
    """Walk an IR tree, applying ``fn`` to every Atom and Silence leaf.

    Structural nodes (Cat, Stack, Fast, ...) are reconstructed with
    recursively-mapped children. ``fn`` receives Atom/Silence nodes only.
    """
    match node:
        case Atom():
            return fn(node)
        case Silence():
            return fn(node)
        case Freeze(child):
            return Freeze(map_atoms(child, fn))
        case Cat(children):
            return Cat(tuple(map_atoms(c, fn) for c in children))
        case Stack(children):
            return Stack(tuple(map_atoms(c, fn) for c in children))
        case Fast(factor, child):
            return Fast(factor, map_atoms(child, fn))
        case Slow(factor, child):
            return Slow(factor, map_atoms(child, fn))
        case Early(offset, child):
            return Early(offset, map_atoms(child, fn))
        case Late(offset, child):
            return Late(offset, map_atoms(child, fn))
        case Rev(child):
            return Rev(map_atoms(child, fn))
        case Every(n, transform, child):
            return Every(n, map_atoms(transform, fn), map_atoms(child, fn))
        case Euclid(pulses, steps, rotation, child):
            return Euclid(pulses, steps, rotation, map_atoms(child, fn))
        case Degrade(prob, seed, child):
            return Degrade(prob, seed, map_atoms(child, fn))
        case Warp(kind, amount, grid, child):
            return Warp(kind, amount, grid, map_atoms(child, fn))
        case _:
            return node


def bind_voice(node: IrNode, voice: str) -> IrNode:
    """Prepend ``voice/`` to bare param names in Control and Osc atoms."""

    def _rewrite(n: IrNode) -> IrNode:
        match n:
            case Atom(Control(label=label, value=val)):
                if "/" not in label:
                    return Atom(Control(label=f"{voice}/{label}", value=val))
                return n
            case Atom(Osc(addr, args)):
                new_args = tuple(
                    OscStr(f"{voice}/{a.value}")
                    if isinstance(a, OscStr) and "/" not in a.value
                    else a
                    for a in args
                )
                return Atom(Osc(addr, new_args))
            case _:
                return n

    return map_atoms(node, _rewrite)


def bind_ctrl(node: IrNode, label: str) -> IrNode:
    """Replace ``"ctrl"`` placeholder in Control/Osc atoms with ``label``."""

    def _rewrite(n: IrNode) -> IrNode:
        match n:
            case Atom(Control(label=ctrl_label, value=val)):
                if ctrl_label == "ctrl":
                    return Atom(Control(label=label, value=val))
                return n
            case Atom(Osc(addr, args)):
                new_args = tuple(
                    OscStr(label) if isinstance(a, OscStr) and a.value == "ctrl" else a
                    for a in args
                )
                return Atom(Osc(addr, new_args))
            case _:
                return n

    return map_atoms(node, _rewrite)


def bind_voice_poly(
    node: IrNode, parent: str, count: int, alloc: int,
) -> tuple[IrNode, int]:
    """Bind a pattern to a poly voice, round-robin allocating instances.

    Each Freeze compound (note/hit event) binds to the next instance.
    Returns (rewritten_node, updated_alloc_counter).
    """
    match node:
        case Freeze(Stack(children)):
            new_children: list[IrNode] = []
            for c in children:
                bound_c, alloc = bind_voice_poly(c, parent, count, alloc)
                new_children.append(bound_c)
            return Freeze(Stack(tuple(new_children))), alloc
        case Freeze(child):
            inst = f"{parent}_v{alloc % count}"
            alloc += 1
            return Freeze(bind_voice(child, inst)), alloc
        case Cat(children):
            new_children_cat: list[IrNode] = []
            for c in children:
                bound_c, alloc = bind_voice_poly(c, parent, count, alloc)
                new_children_cat.append(bound_c)
            return Cat(tuple(new_children_cat)), alloc
        case Stack(children):
            new_children_stack: list[IrNode] = []
            for c in children:
                bound_c, alloc = bind_voice_poly(c, parent, count, alloc)
                new_children_stack.append(bound_c)
            return Stack(tuple(new_children_stack)), alloc
        case Silence():
            return node, alloc
        case Fast(factor, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Fast(factor, bound), alloc
        case Slow(factor, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Slow(factor, bound), alloc
        case Early(offset, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Early(offset, bound), alloc
        case Late(offset, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Late(offset, bound), alloc
        case Rev(child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Rev(bound), alloc
        case Every(n, transform, child):
            bt, alloc = bind_voice_poly(transform, parent, count, alloc)
            bc, alloc = bind_voice_poly(child, parent, count, alloc)
            return Every(n, bt, bc), alloc
        case Euclid(pulses, steps, rotation, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Euclid(pulses, steps, rotation, bound), alloc
        case Degrade(prob, seed, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Degrade(prob, seed, bound), alloc
        case Warp(kind, amount, grid, child):
            bound, alloc = bind_voice_poly(child, parent, count, alloc)
            return Warp(kind, amount, grid, bound), alloc
        case _:
            inst = f"{parent}_v{alloc % count}"
            return bind_voice(node, inst), alloc
