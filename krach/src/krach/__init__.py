import atexit
import os
import subprocess
import time
from pathlib import Path

from krach._config import load_config
from krach._mixer import Mixer


def _repo_root() -> Path:
    """Walk up from this file until we find Cargo.toml (monorepo root)."""
    p = Path(__file__).resolve().parent
    for _ in range(10):
        if (p / "Cargo.toml").exists():
            return p
        p = p.parent
    raise RuntimeError("cannot find monorepo root (no Cargo.toml in ancestors)")


def _wait_for_socket(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def connect(bpm: float = 120, master: float = 0.7, build: bool = True) -> Mixer:
    """Start krach-engine and return a connected Mixer.

    Reads configuration from ``~/.krach/config.toml`` (if present).
    Env vars ``NOISE_SOCKET`` and ``NOISE_DSP_DIR`` override config.
    """
    from krach.patterns import Session
    from krach._types import parse_dsp_controls

    cfg = load_config()
    cfg.ensure_dirs()

    repo = _repo_root()
    engine_bin = repo / "target" / cfg.profile / "krach-engine"

    if build:
        print("building krach-engine...")
        subprocess.run(
            ["cargo", "build", "--bin", "krach-engine", "-q"],
            cwd=repo,
            check=True,
        )

    cfg.socket.unlink(missing_ok=True)
    env = {**os.environ, "RUST_LOG": os.environ.get("RUST_LOG", "info")}

    _log_file = cfg.log_file.open("w")

    engine_proc = subprocess.Popen(
        [str(engine_bin)],
        env={
            **env,
            "NOISE_SOCKET": str(cfg.socket),
            "NOISE_DSP_DIR": str(cfg.dsp_dir),
        },
        stderr=_log_file,
    )

    def _cleanup() -> None:
        engine_proc.terminate()
        try:
            engine_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            engine_proc.kill()
            engine_proc.wait()
        cfg.socket.unlink(missing_ok=True)
        _log_file.close()

    atexit.register(_cleanup)

    if not _wait_for_socket(cfg.socket):
        raise RuntimeError(
            f"krach-engine socket not ready after 5s.\n"
            f"  Check engine log: {cfg.log_file}\n"
            f"  Binary: {engine_bin}\n"
            f"  Socket: {cfg.socket}"
        )

    mm = Session(socket_path=str(cfg.socket))
    mm.connect()

    # Pre-populate controls from DSP files already on disk (previous sessions).
    node_controls: dict[str, tuple[str, ...]] = {}
    for _p in cfg.dsp_dir.rglob("*.dsp"):
        controls = parse_dsp_controls(_p.read_text())
        if controls:
            _rel = _p.relative_to(cfg.dsp_dir).with_suffix("")
            node_controls[f"faust:{_rel}"] = controls

    kr = Mixer(session=mm, dsp_dir=cfg.dsp_dir, node_controls=node_controls)
    kr.tempo = bpm
    kr.master = master

    # Wait for engine to finish loading DSP files (hot-reload at startup).
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            mm.list_nodes()
            break
        except (TimeoutError, ConnectionError):
            time.sleep(0.1)
    else:
        raise RuntimeError(
            f"krach-engine not responding after 10s.\n"
            f"  Check engine log: {cfg.log_file}\n"
            f"  Socket: {cfg.socket}"
        )

    return kr


def main() -> None:
    from krach._pitch import NOTES as _NOTES
    import krach.dsp as krs

    kr = connect()

    print()
    print("  \u2588\u2588\u2557  \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557  \u2588\u2588\u2557")
    print("  \u2588\u2588\u2551 \u2588\u2588\u2554\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551  \u2588\u2588\u2551")
    print("  \u2588\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551")
    print("  \u2588\u2588\u2554\u2550\u2588\u2588\u2557 \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551")
    print("  \u2588\u2588\u2551  \u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551")
    print("  \u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d")
    print()
    print("  kr    Mixer \u2014 kr.node(), kr.play(), kr.note(), kr.hit(), ...")
    print("  krs   krach.dsp \u2014 krs.Signal, krs.control(), krs.saw(), krs.lowpass(), ...")
    print()

    import IPython

    user_ns: dict[str, object] = {
        "kr": kr,
        "krs": krs,
        **_NOTES,
    }

    IPython.embed(  # type: ignore[reportUnknownMemberType]
        user_ns=user_ns,
        banner1="",
        banner2="",
    )

    kr.disconnect()
