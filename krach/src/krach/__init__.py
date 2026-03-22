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
    engine_bin = repo / "target" / "debug" / "krach-engine"

    print("building krach-engine...")
    subprocess.run(
        ["cargo", "build", "--bin", "krach-engine", "-q"],
        cwd=repo,
        check=True,
    )

    engine_sock = Path(tempfile.gettempdir()) / "krach-engine.sock"
    dsp_dir = Path.home() / ".krach" / "dsp"
    dsp_dir.mkdir(parents=True, exist_ok=True)

    engine_sock.unlink(missing_ok=True)
    env = {**os.environ, "RUST_LOG": os.environ.get("RUST_LOG", "info")}

    log_path = Path.home() / ".krach" / "engine.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _log_file = log_path.open("w")

    engine_proc = subprocess.Popen(
        [str(engine_bin)],
        env={
            **env,
            "NOISE_SOCKET": str(engine_sock),
            "NOISE_DSP_DIR": str(dsp_dir),
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
        engine_sock.unlink(missing_ok=True)
        _log_file.close()

    atexit.register(_cleanup)

    if not _wait_for_socket(engine_sock):
        raise RuntimeError("krach-engine socket not ready after 5s")

    # ── imports ──────────────────────────────────────────────────────────────
    from krach.patterns import Session
    from krach.patterns.pattern import rest
    from faust_dsl import Signal, control
    from faust_dsl.lib.filters import bandpass, highpass, lowpass
    from faust_dsl.lib.noise import white_noise
    from faust_dsl.lib.oscillators import phasor, saw, sine_osc, square
    from faust_dsl.music.effects import reverb
    from faust_dsl.music.envelopes import adsr

    import anthropic

    from krach._copilot import SessionState, ask_claude, build_context, extract_code, format_status, parse_dsp_controls, split_cells
    from krach._mininotation import p
    from krach._mixer import (
        VoiceMixer, dsp, hit, mod_exp, mod_ramp,
        mod_ramp_down, mod_sine, mod_square, mod_tri, note, ramp, seq,
    )
    from krach._pitch import NOTES as _NOTES, ftom, mtof, parse_note

    mm = Session(socket_path=str(engine_sock))
    mm.connect()

    # Pre-populate controls from DSP files already on disk (previous sessions).
    _node_controls: dict[str, tuple[str, ...]] = {}
    for _p in dsp_dir.rglob("*.dsp"):
        _controls = parse_dsp_controls(_p.read_text())
        if _controls:
            _rel = _p.relative_to(dsp_dir).with_suffix("")
            _node_controls[f"faust:{_rel}"] = _controls

    mix = VoiceMixer(session=mm, dsp_dir=dsp_dir, node_controls=_node_controls)
    _user_ns_keys: tuple[str, ...] = ()  # populated after user_ns is built

    def _session_state() -> SessionState:
        return SessionState(
            bpm=mix.tempo,
            playing=tuple(k for k, v in mix.slots.items() if v.playing),
            stopped=tuple(k for k, v in mix.slots.items() if not v.playing),
            nodes=tuple(mix.node_controls.keys()),
            node_controls=tuple(mix.node_controls.items()),
            in_scope=_user_ns_keys,
            active_voices=tuple(
                (name, v.type_id, v.gain, v.controls) for name, v in mix.voice_data.items()
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

    # Wait for engine to finish loading DSP files (hot-reload at startup).
    _engine_deadline = time.monotonic() + 10.0
    while time.monotonic() < _engine_deadline:
        try:
            nodes = mm.list_nodes()
            break
        except (TimeoutError, ConnectionError):
            time.sleep(0.1)
    else:
        raise RuntimeError("krach-engine not ready after 10s")

    # nodes list used for the banner only; status() reads live from mix._node_controls.

    print()
    print("  ██╗  ██╗██████╗  █████╗  ██████╗██╗  ██╗")
    print("  ██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║")
    print("  █████╔╝ ██████╔╝███████║██║     ███████║")
    print("  ██╔═██╗ ██╔══██╗██╔══██║██║     ██╔══██║")
    print("  ██║  ██╗██║  ██║██║  ██║╚██████╗██║  ██║")
    print("  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝")
    print()
    print(f"  engine   {engine_sock}")
    print(f"  log      {log_path}")
    print(f"  nodes    {nodes}")
    print(f"  dsp dir  {dsp_dir}")
    print()
    print("  in scope: mix  dsp()  note()  hit()  seq()  p()  rest  ramp()  mtof  ftom  parse_note"
          "  C0..B8  status()  c()  cn()"
          "  mod_sine  mod_tri  mod_ramp  mod_ramp_down  mod_square  mod_exp"
          "  + faust-dsl: control sine_osc saw lowpass adsr ...")
    print()

    import IPython

    user_ns = {
        # Primary API — voices and patterns
        "mix": mix,
        "rest": rest,
        # Free pattern builders (shadow krach.patterns.pattern.note)
        "note": note,
        "hit": hit,
        "seq": seq,
        "p": p,
        "ramp": ramp,
        # Pitch utilities
        "mtof": mtof,
        "ftom": ftom,
        "parse_note": parse_note,
        **_NOTES,
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
        # Mod patterns
        "mod_sine": mod_sine,
        "mod_tri": mod_tri,
        "mod_ramp": mod_ramp,
        "mod_ramp_down": mod_ramp_down,
        "mod_square": mod_square,
        "mod_exp": mod_exp,
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
