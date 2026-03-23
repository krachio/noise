"""NodeHandle — proxy for a named node in the audio graph.

Supports operator DSL: ``>>`` (routing), ``@`` (patterns), ``[]`` (controls).
All operators delegate to VoiceMixer methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from krach.patterns.pattern import Pattern

if TYPE_CHECKING:
    from krach._mixer import VoiceMixer


class NodeHandle:
    """Proxy for a named node in the audio graph."""

    def __init__(self, mixer: VoiceMixer, name: str) -> None:
        self._mixer = mixer
        self._name = name

    # ── Operator DSL ────────────────────────────────────────────────

    def __rshift__(self, other: NodeHandle | tuple[NodeHandle, float]) -> NodeHandle:
        """Route signal: ``bass >> verb`` or ``bass >> (verb, 0.4)``."""
        if isinstance(other, tuple):
            target, level = other
            self._mixer.connect(self._name, target._name, level=level)
            return target
        if isinstance(other, NodeHandle):  # pyright: ignore[reportUnnecessaryIsInstance]
            self._mixer.connect(self._name, other._name)
            return other
        raise TypeError(
            f"{self._name} >> {type(other).__name__} — expected NodeHandle or (NodeHandle, float).\n"
            f"  Try: {self._name} >> verb           — route to verb\n"
            f"       {self._name} >> (verb, 0.4)    — route at 40% level"
        )

    def __matmul__(self, pattern: Pattern | str | tuple[str, Pattern] | None) -> NodeHandle:
        """Play pattern: ``bass @ pattern``, ``bass @ \"A2 D3\"``, ``bass @ None``."""
        if pattern is None:
            self._mixer.hush(self._name)
        elif isinstance(pattern, str):
            from krach._mininotation import p
            self._mixer.play(self._name, p(pattern))
        elif isinstance(pattern, tuple):
            if len(pattern) == 2:
                param, pat = pattern
                if isinstance(param, str) and isinstance(pat, Pattern):  # pyright: ignore[reportUnnecessaryIsInstance]
                    self._mixer.play(f"{self._name}/{param}", pat)
                    return self
            raise TypeError(f"expected (str, Pattern) tuple, got {pattern!r}")
        else:
            self._mixer.play(self._name, pattern)
        return self

    def __getitem__(self, param: str) -> float:
        """Get control value: ``bass[\"cutoff\"]``."""
        return self._mixer.get_ctrl(self._name, param)

    def __setitem__(self, param: str, value: float) -> None:
        """Set control value: ``bass[\"cutoff\"] = 1200``."""
        self._mixer.set(f"{self._name}/{param}", value)

    # ── Explicit API ───────────────────────────────────────────────

    def play(self, target_or_pattern: str | Pattern, pattern: Pattern | None = None) -> None:
        """Play a pattern on this node or a specific control path."""
        if pattern is not None and isinstance(target_or_pattern, str):
            self._mixer.play(f"{self._name}/{target_or_pattern}", pattern)
        else:
            assert isinstance(target_or_pattern, Pattern)
            self._mixer.play(self._name, target_or_pattern)

    def pattern(self) -> Pattern | None:
        """Retrieve the last unbound pattern played on this node."""
        return self._mixer.pattern(self._name)

    def set(self, param: str, value: float) -> None:
        self._mixer.set(f"{self._name}/{param}", value)

    def fade(self, param: str, target: float, bars: int = 4) -> None:
        self._mixer.fade(f"{self._name}/{param}", target, bars=bars)

    def send(self, bus: NodeHandle | str, level: float = 0.5) -> None:
        bus_name = bus.name if isinstance(bus, NodeHandle) else bus
        self._mixer.send(self._name, bus_name, level)

    def mute(self) -> None:
        self._mixer.mute(self._name)

    def unmute(self) -> None:
        self._mixer.unmute(self._name)

    def hush(self) -> None:
        self._mixer.hush(self._name)

    def gain(self, value: float) -> None:
        self._mixer.gain(self._name, value)

    @property
    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:
        node = self._mixer.get_node(self._name)
        if node:
            parts = f"Node('{self._name}', {node.type_id}, gain={node.gain:.2f}"
            if node.count > 1:
                parts += f", count={node.count}"
            if self._mixer.is_muted(self._name):
                parts += ", muted"
            return parts + ")"
        return f"Node('{self._name}', removed)"
