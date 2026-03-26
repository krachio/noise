"""REPL entry point — connect(), main(), LiveMixer with pattern builder sugar.

Library users import ``from krach.mixer import Mixer`` directly.
REPL users get ``LiveMixer`` (via ``connect()``) which adds static convenience
methods (``kr.note()``, ``kr.seq()``, etc.) and a ``__setattr__`` guard
that catches typos like ``kr.swong = 0.67``.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
from pathlib import Path

from krach._paths import resolve_engine_bin, resolve_faust_stdlib_dir, resolve_lib_dir
from krach.config import load_config
from krach.pattern.mininotation import p as _p
from krach.pattern.pitch import ftom as _ftom, mtof as _mtof, parse_note as _parse_note
from krach.node_types import dsp, parse_dsp_controls
from krach.mixer import Mixer
from krach.pattern.builders import (
    cat, hit, mod_exp, mod_ramp, mod_ramp_down, mod_sine, mod_square,
    mod_tri, note, rand, ramp, saw, seq, sine, stack, struct,
)
from krach.pattern.pattern import rest as _rest


# ── LiveMixer ────────────────────────────────────────────────────────────


class LiveMixer(Mixer):
    """REPL-enhanced Mixer with pattern builder sugar and typo guard."""

    note = staticmethod(note)
    hit = staticmethod(hit)
    seq = staticmethod(seq)
    rest = staticmethod(_rest)
    ramp = staticmethod(ramp)
    mod_sine = staticmethod(mod_sine)
    mod_tri = staticmethod(mod_tri)
    mod_ramp = staticmethod(mod_ramp)
    mod_ramp_down = staticmethod(mod_ramp_down)
    mod_square = staticmethod(mod_square)
    mod_exp = staticmethod(mod_exp)
    dsp = staticmethod(dsp)
    sine = staticmethod(sine)
    saw = staticmethod(saw)
    rand = staticmethod(rand)
    cat = staticmethod(cat)
    stack = staticmethod(stack)
    struct = staticmethod(struct)
    mtof = staticmethod(_mtof)
    ftom = staticmethod(_ftom)
    parse_note = staticmethod(_parse_note)
    p = staticmethod(_p)

    _PUBLIC_SETTERS = frozenset({"master", "tempo", "meter"})

    def __setattr__(self, name: str, value: object) -> None:
        if (name.startswith("_")
            or name in self._PUBLIC_SETTERS
            or hasattr(type(self), name)
            or callable(value)):
            super(Mixer, self).__setattr__(name, value)
        else:
            raise AttributeError(
                f"kr has no property {name!r}. "
                f"Settable properties: {', '.join(sorted(self._PUBLIC_SETTERS))}"
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


def connect(bpm: float = 120, master: float = 0.7, build: bool = True) -> LiveMixer:
    """Start krach-engine and return a connected LiveMixer.

    Reads configuration from ``~/.krach/config.toml`` (if present).
    Env vars ``NOISE_SOCKET`` and ``NOISE_DSP_DIR`` override config.
    """
    from krach.pattern import Session

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
            f"krach-engine not responding after 10s.\n"
            f"  Check engine log: {cfg.log_file}\n"
            f"  Socket: {cfg.socket}"
        )

    return kr


# ── REPL entry point ─────────────────────────────────────────────────────


def main() -> None:
    from krach.pattern.pitch import NOTES as _NOTES
    import krach.dsp as krs

    kr = connect()

    print()
    print("  ██╗  ██╗██████╗ █████╗  ██████╗██╗  ██╗")
    print("  ██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║")
    print("  █████╔╝ ██████╔╝███████║██║     ███████║")
    print("  ██╔═██╗ ██╔══██╗██╔══██║██║     ██╔══██║")
    print("  ██║  ██╗██║  ██║██║  ██║╚██████╗██║  ██║")
    print("  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝")
    print()
    print("  kr    Mixer — kr.node(), kr.play(), kr.note(), kr.hit(), ...")
    print("  krs   krach.dsp — krs.Signal, krs.control(), krs.saw(), krs.lowpass(), ...")
    print()

    import IPython  # type: ignore[import-not-found]  # optional dep (repl extra)

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
