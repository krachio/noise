"""Resolve paths to krach-engine binary, shared libs, and FAUST stdlib.

Resolution order for each:
1. Environment variable (KRACH_ENGINE_BIN, KRACH_LIB_DIR, FAUST_STDLIB_DIR)
2. Vendored location inside the installed package (_bin/, _lib/, _share/faust/)
3. Dev layout — walk up to monorepo root, use target/debug/
"""

from __future__ import annotations

import os
from pathlib import Path


def _package_dir() -> Path:
    """Directory containing this module (krach/)."""
    return Path(__file__).resolve().parent.parent


def resolve_engine_bin() -> Path:
    """Find the krach-engine binary."""
    if env := os.environ.get("KRACH_ENGINE_BIN"):
        return Path(env)

    # Vendored: krach/_bin/krach-engine
    vendored = _package_dir() / "_bin" / "krach-engine"
    if vendored.is_file():
        return vendored

    # Dev: walk up to repo root (Cargo.toml), use target/debug/
    root = _find_repo_root()
    if root:
        for profile in ("debug", "release"):
            candidate = root / "target" / profile / "krach-engine"
            if candidate.is_file():
                return candidate

    raise FileNotFoundError(
        "krach-engine binary not found.\n"
        "  Install pre-built: pip install krach (from a platform wheel)\n"
        "  Build from source: cargo build --bin krach-engine (in the noise repo)\n"
        "  Or set KRACH_ENGINE_BIN=/path/to/krach-engine"
    )


def resolve_lib_dir() -> Path | None:
    """Find the directory containing vendored shared libraries."""
    if env := os.environ.get("KRACH_LIB_DIR"):
        return Path(env)

    vendored = _package_dir() / "_lib"
    if vendored.is_dir():
        return vendored

    return None


def resolve_faust_stdlib_dir() -> Path | None:
    """Find the FAUST standard library directory."""
    if env := os.environ.get("FAUST_STDLIB_DIR"):
        return Path(env)

    vendored = _package_dir() / "_share" / "faust"
    if vendored.is_dir():
        return vendored

    return None


def _find_repo_root() -> Path | None:
    """Walk up from package dir to find monorepo root (contains Cargo.toml)."""
    p = _package_dir()
    for _ in range(10):
        if (p / "Cargo.toml").exists():
            return p
        p = p.parent
    return None
