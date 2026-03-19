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

    # Build binaries if missing
    if not midiman_bin.exists() or not soundman_bin.exists():
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
    env = {**os.environ, "RUST_LOG": "warn"}

    midiman_proc = subprocess.Popen(
        [str(midiman_bin)],
        env={**env, "MIDIMAN_SOCKET": str(midiman_sock)},
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
    time.sleep(0.4)  # soundman OSC port

    # ── imports ──────────────────────────────────────────────────────────────
    from midiman_frontend import Session, cc, note, rest
    from midiman_frontend.pattern import osc as midi_osc
    from soundman_frontend import (
        ConnectionIr,
        Graph,
        GraphIr,
        NodeInstance,
        SoundmanSession,
    )
    from faust_dsl import Signal, control, transpile
    from faust_dsl.lib.filters import bandpass, highpass, lowpass
    from faust_dsl.lib.noise import white_noise
    from faust_dsl.lib.oscillators import phasor, saw, sine_osc, square
    from faust_dsl.music.effects import reverb
    from faust_dsl.music.envelopes import adsr

    import anthropic

    from krach._copilot import SessionState, ask_claude, build_context, format_status

    mm = Session(socket_path=str(midiman_sock))
    mm.connect()
    sm = SoundmanSession(host="127.0.0.1", port=9001)

    def _session_state() -> SessionState:
        return SessionState(
            bpm=mm.tempo,
            playing=tuple(k for k, v in mm.slots.items() if v.playing),
            stopped=tuple(k for k, v in mm.slots.items() if not v.playing),
            nodes=tuple(sm.list_nodes()),
        )

    def dsp(name: str, fn: object) -> object:
        """Transpile a Python DSP function and hot-drop it into soundman."""
        result = transpile(fn)  # type: ignore[arg-type]
        (dsp_dir / f"{name}.dsp").write_text(result.source)
        controls = [ctrl.name for ctrl in result.schema.controls]
        print(f"  {name}.dsp — controls: {controls}")
        return result

    def status() -> None:
        """Print current session state: BPM, slots, loaded nodes."""
        print(format_status(_session_state()))

    def c(prompt: str) -> None:
        """Ask Claude for live-coding help with full session context."""
        model = os.environ.get("KRACH_MODEL", "claude-sonnet-4-6")
        client = anthropic.Anthropic()
        system = build_context(_session_state())
        print(ask_claude(client, model, system, prompt))

    nodes = sm.list_nodes()

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
    print("  in scope: mm  sm  dsp()  note rest cc  Graph  transpile control"
          "  status()  c()")
    print()

    import IPython

    IPython.embed(  # type: ignore[reportUnknownMemberType]
        user_ns={
            "mm": mm,
            "sm": sm,
            "dsp": dsp,
            "note": note,
            "rest": rest,
            "cc": cc,
            "midi_osc": midi_osc,
            "Graph": Graph,
            "GraphIr": GraphIr,
            "NodeInstance": NodeInstance,
            "ConnectionIr": ConnectionIr,
            "transpile": transpile,
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
            "dsp_dir": dsp_dir,
            "status": status,
            "c": c,
        },
        banner1="",
        banner2="",
    )

    mm.disconnect()
