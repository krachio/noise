"""Lazy audio session — starts krach-engine on first tool call."""

from __future__ import annotations

from krach._mixer import Mixer

_session: Mixer | None = None


def get_session() -> Mixer:
    """Return the active Mixer, starting krach-engine if needed."""
    global _session  # noqa: PLW0603
    if _session is None:
        import krach
        _session = krach.connect()
    return _session
