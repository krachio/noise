"""Scene utilities — load Python files as session scripts."""

from __future__ import annotations

from pathlib import Path


def load_file(path: str, context: dict[str, object]) -> None:
    """Load and execute a Python file with the given namespace."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"scene file not found: {path}")
    code = p.read_text()
    try:
        exec(compile(code, path, "exec"), context)  # noqa: S102
    except Exception as e:
        raise RuntimeError(f"error loading {path}: {e}") from e
