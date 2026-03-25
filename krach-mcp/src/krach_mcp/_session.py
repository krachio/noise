"""Audio session lifecycle — lazy init, explicit start, auto-connect."""

from __future__ import annotations

from krach.mixer import Mixer

_session: Mixer | None = None


def get_session() -> Mixer:
    """Return the active Mixer, auto-connecting without build if not started."""
    global _session  # noqa: PLW0603
    if _session is None:
        _session = _connect(build=False)
    return _session


def start_session(build: bool = True, bpm: float = 120, master: float = 0.7) -> Mixer:
    """Start (or restart) the engine, optionally building first."""
    global _session  # noqa: PLW0603
    if _session is not None:
        _session.disconnect()
    _session = _connect(build=build, bpm=bpm, master=master)
    return _session


def _connect(build: bool, bpm: float = 120, master: float = 0.7) -> Mixer:
    """Connect to krach-engine. Raises RuntimeError with guidance on failure."""
    import krach
    try:
        return krach.connect(bpm=bpm, master=master, build=build)
    except (FileNotFoundError, RuntimeError) as e:
        if not build:
            raise RuntimeError(
                f"krach-engine not found or not running. "
                f"Call start(build=True) to build and start the engine.\n"
                f"Original error: {e}"
            ) from e
        raise
