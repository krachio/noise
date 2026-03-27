"""Pattern primitives — registered operations with per-primitive serialize rules.

Each primitive is a PatternPrimitive singleton. Serialize rules are registered
in a dict keyed by name. Import-time completeness check asserts every primitive
has all required rules. Summary uses a direct recursive function (no registry).
"""

from __future__ import annotations

from typing import Any, Callable

from krach.pattern.types import PatternPrimitive, PatternNode

# ── Primitive instances ──────────────────────────────────────────────────

atom_p = PatternPrimitive("atom")
silence_p = PatternPrimitive("silence")
cat_p = PatternPrimitive("cat")
stack_p = PatternPrimitive("stack")
freeze_p = PatternPrimitive("freeze")
fast_p = PatternPrimitive("fast")
slow_p = PatternPrimitive("slow")
early_p = PatternPrimitive("early")
late_p = PatternPrimitive("late")
rev_p = PatternPrimitive("rev")
every_p = PatternPrimitive("every")
euclid_p = PatternPrimitive("euclid")
degrade_p = PatternPrimitive("degrade")
warp_p = PatternPrimitive("warp")

ALL_PATTERN_PRIMITIVES: tuple[PatternPrimitive, ...] = (
    atom_p, silence_p, cat_p, stack_p, freeze_p,
    fast_p, slow_p, early_p, late_p, rev_p,
    every_p, euclid_p, degrade_p, warp_p,
)

# ── Rule registries ──────────────────────────────────────────────────────

# Each rule is a function: (node: PatternNode, child_results: tuple, ...extra) -> result
# The exact signature depends on the rule type.

SerializeRule = Callable[[PatternNode, tuple[Any, ...]], Any]

_serialize_rules: dict[str, SerializeRule] = {}


def def_serialize(primitive: PatternPrimitive, fn: SerializeRule) -> None:
    """Register a serialize rule for a primitive."""
    _serialize_rules[primitive.name] = fn


def get_serialize_rule(primitive: PatternPrimitive) -> SerializeRule:
    """Get the serialize rule for a primitive. Raises if not registered."""
    rule = _serialize_rules.get(primitive.name)
    if rule is None:
        raise RuntimeError(f"No serialize rule for pattern primitive {primitive.name!r}")
    return rule


# ── Generic fold ─────────────────────────────────────────────────────────


def fold(node: PatternNode, visitor: Callable[[PatternNode, tuple[Any, ...]], Any]) -> Any:
    """Generic tree fold — process children first, then call visitor on the node.

    visitor(node, child_results) where child_results is the tuple of
    results from folding each child. Leaf nodes get empty tuple.
    """
    child_results = tuple(fold(c, visitor) for c in node.children)
    return visitor(node, child_results)


S = Any  # State type variable (used in fold_with_state)


def fold_with_state(
    node: PatternNode,
    state: S,
    visitor: Callable[[PatternNode, tuple[tuple[PatternNode, S], ...], S], tuple[PatternNode, S]],
) -> tuple[PatternNode, S]:
    """Stateful tree fold — threads state through children left-to-right.

    visitor(node, child_results, state) -> (new_node, new_state)
    child_results is tuple of (rewritten_child, state_after_child).
    State threads: initial → child_0 → child_1 → ... → visitor.

    Used by bind_voice_poly where state = alloc counter.
    """
    child_results: list[tuple[PatternNode, S]] = []
    current_state = state
    for child in node.children:
        rewritten, current_state = fold_with_state(child, current_state, visitor)
        child_results.append((rewritten, current_state))
    return visitor(node, tuple(child_results), current_state)


# ── Import-time completeness check ──────────────────────────────────────


def check_completeness() -> None:
    """Assert every primitive has all required rules. Call at module load time."""
    missing: list[str] = []
    for p in ALL_PATTERN_PRIMITIVES:
        if p.name not in _serialize_rules:
            missing.append(f"{p.name}: missing serialize rule")
    if missing:
        raise RuntimeError(
            "Pattern primitive rules incomplete:\n  " + "\n  ".join(missing)
        )
