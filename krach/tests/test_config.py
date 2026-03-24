"""Tests for _config.py — workspace path configuration."""

import os
import tempfile
from pathlib import Path

from krach._config import Config, load_config


def test_default_config_uses_home_krach() -> None:
    """Default config points to ~/.krach/ workspace."""
    cfg = Config()
    assert cfg.workspace == Path.home() / ".krach"
    assert cfg.dsp_dir == Path.home() / ".krach" / "dsp"
    assert cfg.session_dir == Path.home() / ".krach" / "sessions"
    assert cfg.log_file == Path.home() / ".krach" / "engine.log"


def test_default_socket_uses_tempdir() -> None:
    """Socket defaults to $TMPDIR/krach-engine.sock."""
    cfg = Config()
    assert cfg.socket == Path(tempfile.gettempdir()) / "krach-engine.sock"


def test_env_var_overrides_socket() -> None:
    """NOISE_SOCKET env var overrides the default socket path."""
    old = os.environ.get("NOISE_SOCKET")
    try:
        os.environ["NOISE_SOCKET"] = "/custom/path.sock"
        cfg = load_config()
        assert cfg.socket == Path("/custom/path.sock")
    finally:
        if old is None:
            os.environ.pop("NOISE_SOCKET", None)
        else:
            os.environ["NOISE_SOCKET"] = old


def test_env_var_overrides_dsp_dir() -> None:
    """NOISE_DSP_DIR env var overrides the default dsp directory."""
    old = os.environ.get("NOISE_DSP_DIR")
    try:
        os.environ["NOISE_DSP_DIR"] = "/custom/dsp"
        cfg = load_config()
        assert cfg.dsp_dir == Path("/custom/dsp")
    finally:
        if old is None:
            os.environ.pop("NOISE_DSP_DIR", None)
        else:
            os.environ["NOISE_DSP_DIR"] = old


def test_load_config_from_toml(tmp_path: Path) -> None:
    """load_config reads from a config.toml file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[paths]\n'
        'dsp_dir = "/my/dsp"\n'
        'session_dir = "/my/sessions"\n'
    )
    cfg = load_config(config_file=config_file)
    assert cfg.dsp_dir == Path("/my/dsp")
    assert cfg.session_dir == Path("/my/sessions")
    # Unset fields keep defaults
    assert cfg.log_file == Path.home() / ".krach" / "engine.log"


def test_load_config_missing_file_returns_defaults() -> None:
    """load_config with nonexistent file returns defaults."""
    cfg = load_config(config_file=Path("/nonexistent/config.toml"))
    assert cfg.dsp_dir == Path.home() / ".krach" / "dsp"


def test_config_ensure_dirs_creates_workspace(tmp_path: Path) -> None:
    """ensure_dirs creates workspace, dsp_dir, and session_dir."""
    cfg = Config(
        workspace=tmp_path / "krach",
        dsp_dir=tmp_path / "krach" / "dsp",
        session_dir=tmp_path / "krach" / "sessions",
    )
    cfg.ensure_dirs()
    assert (tmp_path / "krach").is_dir()
    assert (tmp_path / "krach" / "dsp").is_dir()
    assert (tmp_path / "krach" / "sessions").is_dir()
