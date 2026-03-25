"""Shared Primitive type for both signal and pattern domains."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Primitive:
    """A named operation, shared by signal and pattern IRs.

    Equality and hashing are structural, based on (name, stateful).
    This is required for DspGraph canonicalization and caching.
    """

    name: str
    stateful: bool = False
