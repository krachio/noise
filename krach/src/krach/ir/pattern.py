"""Pattern IR — tree of temporal operations with registered primitives.

PatternNode is the single node type for all pattern operations.
Each operation is identified by a PatternPrimitive. Per-primitive rules
(bind, summary, serialize) are registered on the primitive, not via match arms.

The tree structure IS the temporal semantics — nesting determines timing.
This is NOT flat equations like the Signal IR — patterns are trees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from krach.patterns.ir import Value


# ── Primitive ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PatternPrimitive:
    """A registered pattern operation. Equality by name."""

    name: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PatternPrimitive):
            return NotImplemented
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


# ── Params ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AtomParams:
    """Leaf value — Control, Note, Cc, Osc."""
    value: Value


@dataclass(frozen=True, slots=True)
class SilenceParams:
    """Empty event."""
    pass


@dataclass(frozen=True, slots=True)
class CatParams:
    """Sequential composition — no extra data."""
    pass


@dataclass(frozen=True, slots=True)
class StackParams:
    """Parallel composition — no extra data."""
    pass


@dataclass(frozen=True, slots=True)
class FreezeParams:
    """Indivisible compound — marks poly voice allocation boundary."""
    pass


@dataclass(frozen=True, slots=True)
class FastParams:
    """Time scaling (speed up). factor = (numerator, denominator)."""
    factor: tuple[int, int]


@dataclass(frozen=True, slots=True)
class SlowParams:
    """Time scaling (slow down). factor = (numerator, denominator)."""
    factor: tuple[int, int]


@dataclass(frozen=True, slots=True)
class EarlyParams:
    """Phase offset (earlier). offset = (numerator, denominator)."""
    offset: tuple[int, int]


@dataclass(frozen=True, slots=True)
class LateParams:
    """Phase offset (later). offset = (numerator, denominator)."""
    offset: tuple[int, int]


@dataclass(frozen=True, slots=True)
class RevParams:
    """Reverse — no extra data."""
    pass


@dataclass(frozen=True, slots=True)
class EveryParams:
    """Apply transform every N cycles. children[0]=transform, children[1]=source."""
    n: int


@dataclass(frozen=True, slots=True)
class EuclidParams:
    """Euclidean rhythm distribution."""
    pulses: int
    steps: int
    rotation: int


@dataclass(frozen=True, slots=True)
class DegradeParams:
    """Probabilistic event dropout."""
    prob: float
    seed: int


@dataclass(frozen=True, slots=True)
class WarpParams:
    """Timing warp (swing, etc.)."""
    kind: str
    amount: float
    grid: int


PatternParams = Union[
    AtomParams, SilenceParams, CatParams, StackParams, FreezeParams,
    FastParams, SlowParams, EarlyParams, LateParams, RevParams,
    EveryParams, EuclidParams, DegradeParams, WarpParams,
]


# ── Node ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PatternNode:
    """A node in the pattern tree.

    One type for all operations. The primitive identifies the operation.
    Children are sub-trees (ordered — order matters for Cat, Every).
    Params carry operation-specific data (typed per primitive).
    """

    primitive: PatternPrimitive
    children: tuple[PatternNode, ...]
    params: PatternParams
