"""Workspace configuration — paths, env var overrides, config.toml.

Central source of truth for all filesystem paths used by krach.
Reads from ~/.krach/config.toml (if present), then env vars override.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_WORKSPACE = Path.home() / ".krach"


def _default_socket() -> Path:
    return Path(tempfile.gettempdir()) / "krach-engine.sock"


@dataclass(frozen=True)
class Config:
    """Frozen configuration for the krach workspace."""

    workspace: Path = field(default_factory=lambda: _WORKSPACE)
    dsp_dir: Path = field(default_factory=lambda: _WORKSPACE / "dsp")
    session_dir: Path = field(default_factory=lambda: _WORKSPACE / "sessions")
    log_file: Path = field(default_factory=lambda: _WORKSPACE / "engine.log")
    socket: Path = field(default_factory=_default_socket)
    build: bool = True
    profile: str = "debug"

    def ensure_dirs(self) -> None:
        """Create workspace directories if they don't exist."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.dsp_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)


def load_config(config_file: Path | None = None) -> Config:
    """Load config from toml file + env var overrides.

    Priority: env vars > config.toml > defaults.
    """
    if config_file is None:
        config_file = _WORKSPACE / "config.toml"

    # Read toml if it exists
    toml_paths: dict[str, str] = {}
    if config_file.exists():
        with config_file.open("rb") as f:
            data = tomllib.load(f)
        toml_paths = data.get("paths", {})

    # Build config: toml overrides defaults, env vars override toml
    workspace = Path(toml_paths.get("workspace", str(_WORKSPACE)))
    dsp_dir = Path(os.environ.get("NOISE_DSP_DIR", toml_paths.get("dsp_dir", str(workspace / "dsp"))))
    session_dir = Path(toml_paths.get("session_dir", str(workspace / "sessions")))
    log_file = Path(toml_paths.get("log_file", str(workspace / "engine.log")))
    socket = Path(os.environ.get("NOISE_SOCKET", toml_paths.get("socket", str(_default_socket()))))

    return Config(
        workspace=workspace,
        dsp_dir=dsp_dir,
        session_dir=session_dir,
        log_file=log_file,
        socket=socket,
    )
