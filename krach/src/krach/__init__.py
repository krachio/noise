import atexit
import os
import subprocess
import tempfile
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _wait_for_socket(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def main() -> None:
    repo = _repo_root()
    midiman_bin = repo / "target" / "debug" / "midiman"
    soundman_bin = repo / "target" / "debug" / "soundman"

    print("building binaries...")
    subprocess.run(
        ["cargo", "build", "--bin", "midiman", "--bin", "soundman", "-q"],
        cwd=repo,
        check=True,
    )

    midiman_sock = Path(tempfile.gettempdir()) / "midiman.sock"
    dsp_dir = Path.home() / ".krach" / "dsp"
    dsp_dir.mkdir(parents=True, exist_ok=True)

    midiman_sock.unlink(missing_ok=True)
    env = {**os.environ, "RUST_LOG": os.environ.get("RUST_LOG", "warn")}

    midiman_proc = subprocess.Popen(
        [str(midiman_bin)],
        env={
            **env,
            "MIDIMAN_SOCKET": str(midiman_sock),
            "MIDIMAN_OSC_TARGET": "127.0.0.1:9001",  # route OSC atoms to soundman
        },
    )
    soundman_proc = subprocess.Popen(
        [str(soundman_bin)],
        env={**env, "SOUNDMAN_DSP_DIR": str(dsp_dir)},
    )

    def _cleanup() -> None:
        midiman_proc.terminate()
        soundman_proc.terminate()

    atexit.register(_cleanup)

    if not _wait_for_socket(midiman_sock):
        raise RuntimeError("midiman socket not ready after 5s")

    # ── imports ──────────────────────────────────────────────────────────────
    from midiman_frontend import Session
    from midiman_frontend.pattern import rest
    from soundman_frontend import SoundmanSession
    from faust_dsl import Signal, control
    from faust_dsl.lib.filters import bandpass, highpass, lowpass
    from faust_dsl.lib.noise import white_noise
    from faust_dsl.lib.oscillators import phasor, saw, sine_osc, square
    from faust_dsl.music.effects import reverb
    from faust_dsl.music.envelopes import adsr

    import anthropic

    from krach._copilot import SessionState, ask_claude, build_context, extract_code, format_status, parse_dsp_controls, split_cells
    from krach._mixer import VoiceMixer, dsp

    mm = Session(socket_path=str(midiman_sock))
    mm.connect()
    sm = SoundmanSession(host="127.0.0.1", port=9001)

    # Pre-populate controls from DSP files already on disk (previous sessions).
    _node_controls: dict[str, tuple[str, ...]] = {}
    for _p in dsp_dir.glob("*.dsp"):
        _controls = parse_dsp_controls(_p.read_text())
        if _controls:
            _node_controls[f"faust:{_p.stem}"] = _controls

    mix = VoiceMixer(session=sm, dsp_dir=dsp_dir, node_controls=_node_controls)
    _user_ns_keys: tuple[str, ...] = ()  # populated after user_ns is built

    def _session_state() -> SessionState:
        return SessionState(
            bpm=mm.tempo,
            playing=tuple(k for k, v in mm.slots.items() if v.playing),
            stopped=tuple(k for k, v in mm.slots.items() if not v.playing),
            nodes=tuple(_cached_nodes),
            node_controls=tuple(_node_controls.items()),
            in_scope=_user_ns_keys,
            active_voices=tuple(
                (name, v.type_id, v.gain, v.controls) for name, v in mix.voices.items()
            ),
        )

    # dsp decorator imported from _mixer — replaces the old dsp() function

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

    # Wait for soundman to finish loading DSP files (hot-reload at startup).
    _soundman_deadline = time.monotonic() + 10.0
    while time.monotonic() < _soundman_deadline:
        try:
            sm.list_nodes(timeout=0.5)
            break
        except TimeoutError:
            time.sleep(0.1)
    else:
        raise RuntimeError("soundman not ready after 10s")

    nodes = sm.list_nodes()

    # Cache nodes so status() and c() don't block on an OSC round-trip.
    _cached_nodes: list[str] = list(nodes)

    print()
    print("  ██╗  ██╗██████╗  █████╗  ██████╗██╗  ██╗")
    print("  ██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║")
    print("  █████╔╝ ██████╔╝███████║██║     ███████║")
    print("  ██╔═██╗ ██╔══██╗██╔══██║██║     ██╔══██║")
    print("  ██║  ██╗██║  ██║██║  ██║╚██████╗██║  ██║")
    print("  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝")
    print()
    print(f"  midiman  {midiman_sock}")
    print(f"  soundman 127.0.0.1:9001  nodes: {nodes}")
    print(f"  dsp dir  {dsp_dir}")
    print()
    print("  in scope: mix  mm  dsp()  rest  status()  c()  cn()"
          "  + faust-dsl: control sine_osc saw lowpass adsr ...")
    print()

    import IPython

    user_ns = {
        # Primary API — voices and patterns
        "mix": mix,
        "mm": mm,
        "rest": rest,
        # Synth design (faust-dsl)
        "dsp": dsp,
        "control": control,
        "Signal": Signal,
        "sine_osc": sine_osc,
        "phasor": phasor,
        "saw": saw,
        "square": square,
        "lowpass": lowpass,
        "highpass": highpass,
        "bandpass": bandpass,
        "white_noise": white_noise,
        "adsr": adsr,
        "reverb": reverb,
        # Session
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

    mm.disconnect()
