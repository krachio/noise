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
    from krach._copilot import parse_dsp_controls

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
    import anthropic

    from krach._copilot import SessionState, ask_claude, build_context, extract_code, format_status, split_cells
    from krach._pitch import NOTES as _NOTES
    import krach.dsp as krs

    kr = connect()

    _user_ns_keys: tuple[str, ...] = ()  # populated after user_ns is built

    def _session_state() -> SessionState:
        return SessionState(
            bpm=kr.tempo,
            playing=tuple(k for k, v in kr.slots.items() if v.playing),
            stopped=tuple(k for k, v in kr.slots.items() if not v.playing),
            nodes=tuple(kr.node_controls.keys()),
            node_controls=tuple(kr.node_controls.items()),
            in_scope=_user_ns_keys,
            active_nodes=tuple(
                (name, v.type_id, v.gain, v.controls) for name, v in kr.node_data.items()
            ),
        )

    def status() -> None:
        """Print current session state: BPM, slots, loaded nodes."""
        print(format_status(_session_state()))

    _cell_queue: list[str] = []

    def _paste(cell: str) -> None:
        import IPython
        print(cell)
        IPython.get_ipython().set_next_input(cell)  # type: ignore[union-attr]

    def c(prompt: str) -> None:
        """Ask Claude for help; splits response into cells, pastes the first."""
        model = os.environ.get("KRACH_MODEL", "claude-sonnet-4-6")
        client = anthropic.Anthropic()
        system = build_context(_session_state())
        response = ask_claude(client, model, system, prompt)
        code = extract_code(response)
        if not code:
            print(response)
            return
        cells = split_cells(code)
        _cell_queue.clear()
        _cell_queue.extend(cells[1:])
        _paste(cells[0])
        if _cell_queue:
            print(f"\n  ({len(_cell_queue)} more cell(s) — call cn() to advance)")

    def cn() -> None:
        """Paste the next queued cell (from the last c() call)."""
        if not _cell_queue:
            print("cell queue empty")
            return
        _paste(_cell_queue.pop(0))
        if _cell_queue:
            print(f"\n  ({len(_cell_queue)} more cell(s) — call cn() to advance)")

    # Bind session helpers onto kr instance
    kr.status = status  # type: ignore[attr-defined]
    kr.c = c  # type: ignore[attr-defined]
    kr.cn = cn  # type: ignore[attr-defined]

    print()
    print("  \u2588\u2588\u2557  \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557  \u2588\u2588\u2557")
    print("  \u2588\u2588\u2551 \u2588\u2588\u2554\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551  \u2588\u2588\u2551")
    print("  \u2588\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551")
    print("  \u2588\u2588\u2554\u2550\u2588\u2588\u2557 \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551")
    print("  \u2588\u2588\u2551  \u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551")
    print("  \u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d")
    print()
    print("  kr    Mixer — kr.node(), kr.play(), kr.note(), kr.hit(), ...")
    print("  krs   krach.dsp  — krs.Signal, krs.control(), krs.saw(), krs.lowpass(), ...")
    print()

    import IPython

    user_ns: dict[str, object] = {
        "kr": kr,
        "krs": krs,
        # Note constants for convenience (C0..B8)
        **_NOTES,
        # Compat aliases (will be removed in future)
        "status": status,
        "c": c,
        "cn": cn,
    }
    _user_ns_keys = tuple(sorted(user_ns))

    IPython.embed(  # type: ignore[reportUnknownMemberType]
        user_ns=user_ns,
        banner1="",
        banner2="",
    )

    kr.disconnect()
