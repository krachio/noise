"""krach.pattern — pattern namespace for live coding.

Import as: from krach import pattern as krp

Pattern builders, transforms, pitch utilities, and mini-notation.
"""

from krach.backends.graph import ConnectionIr, Graph, GraphIr, NodeInstance
from krach.pattern.builders import (
    cat as cat,
    check_finite as check_finite,
    exp as exp,
    hit as hit,
    note as note,
    ramp as ramp,
    ramp_down as ramp_down,
    rand as rand,
    seq as seq,
    sine as sine,
    square as square,
    stack as stack,
    struct as struct,
    tri as tri,
)
from krach.pattern.mininotation import p as p
from krach.pattern.pattern import Pattern as Pattern, cc as cc, midi_note as midi_note, osc as osc, rest as rest
from krach.pattern.pitch import ftom as ftom, midi_to_name as midi_to_name, mtof as mtof, parse_note as parse_note
from krach.pattern.transform import (
    Transform as Transform,
    every as every,
    fast as fast,
    reverse as reverse,
    shift as shift,
    spread as spread,
    thin as thin,
)
from krach.session import KernelError, Session, SlotState

__all__ = [
    # Graph (re-exported for backward compat during transition)
    "ConnectionIr",
    "Graph",
    "GraphIr",
    "NodeInstance",
    # Session
    "KernelError",
    "Session",
    "SlotState",
    # Pattern
    "Pattern",
    # Builders
    "cat",
    "cc",
    "check_finite",
    "exp",
    "hit",
    "midi_note",
    "note",
    "osc",
    "p",
    "ramp",
    "ramp_down",
    "rand",
    "rest",
    "seq",
    "sine",
    "square",
    "stack",
    "struct",
    "tri",
    # Pitch
    "ftom",
    "midi_to_name",
    "mtof",
    "parse_note",
    # Transform
    "Transform",
    "every",
    "fast",
    "reverse",
    "shift",
    "spread",
    "thin",
]
