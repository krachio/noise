"""Generic rule registry for primitive operations.

Each domain registers rules (abstract_eval, lowering, serialize, summary)
on a per-primitive basis. One mechanism, four instances.
"""

from __future__ import annotations

from typing import Generic, TypeVar

P = TypeVar("P")  # param type for lookup key (usually Primitive)
R = TypeVar("R")  # rule type (the callable)


class RuleRegistry(Generic[P, R]):
    """Registry mapping primitives to rules.

    Usage:
        abstract_eval = RuleRegistry[Primitive, AbstractEvalRule]("abstract_eval")
        abstract_eval.register(add_p, _binop_eval)
        rule = abstract_eval.lookup(add_p)
    """

    __slots__ = ("_name", "_rules")

    def __init__(self, name: str) -> None:
        self._name = name
        self._rules: dict[P, R] = {}

    def register(self, key: P, rule: R) -> R:
        """Register a rule. Returns the rule for decorator use."""
        self._rules[key] = rule
        return rule

    def lookup(self, key: P) -> R:
        """Look up a rule. Raises RuntimeError if not found."""
        try:
            return self._rules[key]
        except KeyError:
            name = getattr(key, "name", repr(key))
            raise RuntimeError(
                f"No {self._name} rule for primitive {name!r}"
            ) from None

    def get(self, key: P) -> R | None:
        """Look up a rule, returning None if not found."""
        return self._rules.get(key)

    def __contains__(self, key: P) -> bool:
        return key in self._rules

    def __len__(self) -> int:
        return len(self._rules)

    def check_complete(self, expected: frozenset[P]) -> None:
        """Assert all expected keys have registered rules. Raises RuntimeError if incomplete."""
        missing = expected - self._rules.keys()
        if missing:
            names = sorted(getattr(k, "name", repr(k)) for k in missing)
            raise RuntimeError(
                f"{self._name} rules incomplete — missing: {', '.join(names)}"
            )
