"""Tests for krach._paths — vendored vs dev binary/lib resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from krach._paths import resolve_engine_bin, resolve_lib_dir, resolve_faust_stdlib_dir


def test_resolve_engine_bin_from_env(tmp_path: Path) -> None:
    bin_path = tmp_path / "krach-engine"
    bin_path.touch(mode=0o755)
    with patch.dict(os.environ, {"KRACH_ENGINE_BIN": str(bin_path)}):
        assert resolve_engine_bin() == bin_path


def test_resolve_engine_bin_vendored(tmp_path: Path) -> None:
    # Simulate vendored layout: krach/_bin/krach-engine
    bin_dir = tmp_path / "_bin"
    bin_dir.mkdir()
    engine = bin_dir / "krach-engine"
    engine.touch(mode=0o755)

    with patch("krach._paths._package_dir", return_value=tmp_path):
        result = resolve_engine_bin()
    assert result == engine


def test_resolve_engine_bin_dev_fallback(tmp_path: Path) -> None:
    # Simulate dev layout: repo root with Cargo.toml and target/debug/krach-engine
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[workspace]")
    target = repo / "target" / "debug"
    target.mkdir(parents=True)
    engine = target / "krach-engine"
    engine.touch(mode=0o755)

    # _package_dir points to repo/krach/src/krach (simulated)
    pkg = repo / "krach" / "src" / "krach"
    pkg.mkdir(parents=True)

    with patch("krach._paths._package_dir", return_value=pkg):
        result = resolve_engine_bin()
    assert result == engine


def test_resolve_lib_dir_from_env(tmp_path: Path) -> None:
    lib_dir = tmp_path / "libs"
    lib_dir.mkdir()
    with patch.dict(os.environ, {"KRACH_LIB_DIR": str(lib_dir)}):
        assert resolve_lib_dir() == lib_dir


def test_resolve_lib_dir_vendored(tmp_path: Path) -> None:
    lib_dir = tmp_path / "_lib"
    lib_dir.mkdir()
    with patch("krach._paths._package_dir", return_value=tmp_path):
        assert resolve_lib_dir() == lib_dir


def test_resolve_faust_stdlib_dir_from_env(tmp_path: Path) -> None:
    share = tmp_path / "faust"
    share.mkdir()
    with patch.dict(os.environ, {"FAUST_STDLIB_DIR": str(share)}):
        assert resolve_faust_stdlib_dir() == share


def test_resolve_faust_stdlib_dir_vendored(tmp_path: Path) -> None:
    share = tmp_path / "_share" / "faust"
    share.mkdir(parents=True)
    with patch("krach._paths._package_dir", return_value=tmp_path):
        assert resolve_faust_stdlib_dir() == share


def test_resolve_engine_bin_dev_release_fallback(tmp_path: Path) -> None:
    """When only release binary exists, it should be found."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[workspace]")
    target = repo / "target" / "release"
    target.mkdir(parents=True)
    engine = target / "krach-engine"
    engine.touch(mode=0o755)

    pkg = repo / "krach" / "src" / "krach"
    pkg.mkdir(parents=True)

    with patch("krach._paths._package_dir", return_value=pkg):
        assert resolve_engine_bin() == engine


def test_resolve_engine_bin_dev_prefers_debug(tmp_path: Path) -> None:
    """When both debug and release exist, debug is preferred."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[workspace]")
    for profile in ("debug", "release"):
        target = repo / "target" / profile
        target.mkdir(parents=True)
        (target / "krach-engine").touch(mode=0o755)

    pkg = repo / "krach" / "src" / "krach"
    pkg.mkdir(parents=True)

    with patch("krach._paths._package_dir", return_value=pkg):
        result = resolve_engine_bin()
    assert result == repo / "target" / "debug" / "krach-engine"


def test_resolve_lib_dir_missing_returns_none() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("krach._paths._package_dir", return_value=Path("/nonexistent")),
    ):
        os.environ.pop("KRACH_LIB_DIR", None)
        assert resolve_lib_dir() is None


def test_resolve_faust_stdlib_dir_missing_returns_none() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("krach._paths._package_dir", return_value=Path("/nonexistent")),
    ):
        os.environ.pop("FAUST_STDLIB_DIR", None)
        assert resolve_faust_stdlib_dir() is None


def test_resolve_engine_bin_missing_raises() -> None:
    """When no binary found anywhere, raise a clear error."""
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("krach._paths._package_dir", return_value=Path("/nonexistent")),
    ):
        os.environ.pop("KRACH_ENGINE_BIN", None)
        try:
            resolve_engine_bin()
            assert False, "should have raised"
        except FileNotFoundError as e:
            assert "krach-engine" in str(e)
            assert "cargo build" in str(e)  # actionable message
