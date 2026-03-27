"""REPL entry point — connect(), main(), LiveMixer.

Library users import ``from krach.mixer import Mixer`` directly.
REPL users get ``LiveMixer`` (via ``connect()``) with ``__setattr__``
guard that catches typos like ``kr.swong = 0.67``.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
from pathlib import Path

from krach.repl.paths import resolve_engine_bin, resolve_faust_stdlib_dir, resolve_lib_dir
from krach.config import load_config
from krach.graph.node import parse_dsp_controls
from krach.mixer import Mixer


# ── LiveMixer ────────────────────────────────────────────────────────────


class LiveMixer(Mixer):
    """REPL-enhanced Mixer with typo guard."""

    _PUBLIC_SETTERS = frozenset({"master", "tempo", "meter"})

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_") or name in self._PUBLIC_SETTERS or hasattr(type(self), name) or callable(value):
            super(Mixer, self).__setattr__(name, value)
        else:
            raise AttributeError(
                f"kr has no property {name!r}. Settable properties: {', '.join(sorted(self._PUBLIC_SETTERS))}"
            )


# ── Engine lifecycle ─────────────────────────────────────────────────────


def _is_dev_layout(engine_bin: Path) -> bool:
    """True if engine_bin lives inside a cargo target/ directory."""
    return "target" in engine_bin.parts


def _wait_for_socket(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def connect_remote(
    host: str,
    port: int,
    token: str | None = None,
    bpm: float = 120,
    master: float = 0.7,
) -> LiveMixer:
    """Connect to a remote krach-engine over TCP. Skips engine spawn.

    Usage::

        kr = connect_remote("192.168.1.42", 9090, token="abc123")
    """
    from krach.session import Session

    cfg = load_config()
    cfg.ensure_dirs()

    # Read token from ~/.krach/token if not provided.
    if token is None:
        token_path = cfg.workspace / "token"
        if token_path.exists():
            token = token_path.read_text().strip()

    mm = Session(address=(host, port), token=token)
    mm.connect()

    node_controls: dict[str, tuple[str, ...]] = {}
    for dsp_file in cfg.dsp_dir.rglob("*.dsp"):
        controls = parse_dsp_controls(dsp_file.read_text())
        if controls:
            _rel = dsp_file.relative_to(cfg.dsp_dir).with_suffix("")
            node_controls[f"faust:{_rel}"] = controls

    kr = LiveMixer(session=mm, dsp_dir=cfg.dsp_dir, node_controls=node_controls)
    kr.tempo = bpm
    kr.master = master
    return kr


def connect(bpm: float = 120, master: float = 0.7, build: bool = True) -> LiveMixer:
    """Start krach-engine and return a connected LiveMixer.

    Reads configuration from ``~/.krach/config.toml`` (if present).
    Env vars ``NOISE_SOCKET`` and ``NOISE_DSP_DIR`` override config.
    """
    from krach.session import Session

    cfg = load_config()
    cfg.ensure_dirs()

    engine_bin = resolve_engine_bin()

    # In dev mode, optionally build before launching
    if build and _is_dev_layout(engine_bin):
        repo = engine_bin.parent.parent.parent  # target/<profile>/krach-engine → repo
        print("building krach-engine...")
        subprocess.run(
            ["cargo", "build", "--bin", "krach-engine", "-q"],
            cwd=repo,
            check=True,
        )

    cfg.socket.unlink(missing_ok=True)
    env = {
        **os.environ,
        "RUST_LOG": os.environ.get("RUST_LOG", "info"),
        "NOISE_SOCKET": str(cfg.socket),
        "NOISE_DSP_DIR": str(cfg.dsp_dir),
    }

    # Point engine at vendored libs if available
    lib_dir = resolve_lib_dir()
    if lib_dir:
        import sys

        lib_path_var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
        env[lib_path_var] = str(lib_dir)

    stdlib_dir = resolve_faust_stdlib_dir()
    if stdlib_dir:
        env["FAUST_STDLIB_DIR"] = str(stdlib_dir)

    _log_file = cfg.log_file.open("w")

    engine_proc = subprocess.Popen(
        [str(engine_bin)],
        env=env,
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

    node_controls: dict[str, tuple[str, ...]] = {}
    for dsp_file in cfg.dsp_dir.rglob("*.dsp"):
        controls = parse_dsp_controls(dsp_file.read_text())
        if controls:
            _rel = dsp_file.relative_to(cfg.dsp_dir).with_suffix("")
            node_controls[f"faust:{_rel}"] = controls

    kr = LiveMixer(session=mm, dsp_dir=cfg.dsp_dir, node_controls=node_controls)
    kr.tempo = bpm
    kr.master = master

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            mm.list_nodes()
            break
        except (TimeoutError, ConnectionError):
            time.sleep(0.1)
    else:
        raise RuntimeError(
            f"krach-engine not responding after 10s.\n  Check engine log: {cfg.log_file}\n  Socket: {cfg.socket}"
        )

    return kr


# ── REPL entry point ─────────────────────────────────────────────────────


def main() -> None:
    import sys

    if "--version" in sys.argv or "-V" in sys.argv:
        from krach import __version__

        print(f"krach {__version__}")
        return

    if "--help" in sys.argv or "-h" in sys.argv:
        print("krach — live coding audio system")
        print()
        print("Usage: krach [--help] [--version] [--midi-sync]")
        print()
        print("Starts an IPython REPL with kr (Mixer), krs (DSP), krp (patterns).")
        print("Requires: krach-engine binary (bundled in wheel or cargo build).")
        print()
        print("  --midi-sync                  start with external MIDI clock sync")
        print()
        print("  kr.node('bass', bass_fn)    create a DSP node")
        print("  bass >> verb                 route signal")
        print("  bass @ krp.seq('A2', 'D3')   play a pattern")
        print("  kr.tempo = 128              set tempo")
        print()
        print("https://krach.io")
        return

    from krach.pattern.pitch import NOTES as _NOTES
    from krach import signal as krs
    from krach import pattern as krp

    kr = connect()

    if "--midi-sync" in sys.argv:
        kr.sync = "midi"

    print()
    print("  ██╗  ██╗██████╗ █████╗  ██████╗██╗  ██╗")
    print("  ██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║")
    print("  █████╔╝ ██████╔╝███████║██║     ███████║")
    print("  ██╔═██╗ ██╔══██╗██╔══██║██║     ██╔══██║")
    print("  ██║  ██╗██║  ██║██║  ██║╚██████╗██║  ██║")
    print("  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝")
    print()
    print("  kr    Mixer — kr.node(), kr.play(), kr.load(), ...")
    print("  krs   krach.signal — krs.saw(), krs.lowpass(), krs.control(), ...")
    print("  krp   krach.pattern — krp.note(), krp.seq(), krp.hit(), ...")
    print()

    import IPython  # type: ignore[import-not-found]

    user_ns: dict[str, object] = {
        "kr": kr,
        "krs": krs,
        "krp": krp,
        **_NOTES,
    }

    IPython.embed(  # type: ignore[reportUnknownMemberType]
        user_ns=user_ns,
        banner1="",
        banner2="",
    )

    kr.disconnect()
