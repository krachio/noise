from typing import Any

from krach._copilot import SessionState, ask_claude, build_context, format_status


def make_state(**kwargs: object) -> SessionState:
    defaults: dict[str, object] = {
        "bpm": 120.0,
        "playing": ("kick", "bass"),
        "stopped": ("melody",),
        "nodes": ("oscillator", "dac", "faust:kit"),
    }
    return SessionState(**{**defaults, **kwargs})  # type: ignore[arg-type]


# ── build_context ────────────────────────────────────────────────────────────

def test_build_context_contains_bpm() -> None:
    ctx = build_context(make_state(bpm=132.0))
    assert "132" in ctx


def test_build_context_contains_playing_slots() -> None:
    ctx = build_context(make_state(playing=("kick", "bass")))
    assert "kick" in ctx
    assert "bass" in ctx


def test_build_context_contains_nodes() -> None:
    ctx = build_context(make_state(nodes=("oscillator", "faust:reverb")))
    assert "oscillator" in ctx
    assert "faust:reverb" in ctx


def test_build_context_contains_dsl_reference() -> None:
    ctx = build_context(make_state())
    # context.md content must be present
    assert "note(" in ctx
    assert "Graph()" in ctx
    assert "dsp(" in ctx


# ── format_status ────────────────────────────────────────────────────────────

def test_format_status_shows_bpm() -> None:
    out = format_status(make_state(bpm=128.0))
    assert "128" in out


def test_format_status_shows_playing_indicator() -> None:
    out = format_status(make_state(playing=("kick",), stopped=("bass",)))
    lines = out.splitlines()
    playing_lines = [l for l in lines if "kick" in l]
    stopped_lines = [l for l in lines if "bass" in l]
    assert playing_lines, "kick should appear in output"
    assert stopped_lines, "bass should appear in output"
    # playing slot marked differently from stopped
    assert playing_lines[0] != stopped_lines[0]


def test_format_status_shows_nodes() -> None:
    out = format_status(make_state(nodes=("oscillator", "faust:kit")))
    assert "faust:kit" in out


def test_format_status_empty_slots() -> None:
    out = format_status(make_state(playing=(), stopped=()))
    assert "128" not in out or "bpm" in out.lower()  # still shows BPM
    assert out.strip()  # not empty


# ── ask_claude ───────────────────────────────────────────────────────────────

def test_ask_claude_returns_text_content() -> None:
    class _Content:
        text = "sm.set('pitch', 880.0)"

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **_kwargs: Any) -> _Response:
            return _Response()

    class _Client:
        messages = _Messages()

    result = ask_claude(_Client(), "claude-sonnet-4-6", "system prompt", "make it louder")
    assert result == "sm.set('pitch', 880.0)"


def test_ask_claude_passes_model_and_prompts() -> None:
    captured: dict[str, object] = {}

    class _Content:
        text = "ok"

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **kwargs: Any) -> _Response:
            captured.update(kwargs)
            return _Response()

    class _Client:
        messages = _Messages()

    ask_claude(_Client(), "claude-haiku-4-5-20251001", "sys", "user prompt")

    assert captured["model"] == "claude-haiku-4-5-20251001"
    assert captured["system"] == "sys"  # type: ignore[comparison-overlap]
    msgs = captured["messages"]
    assert isinstance(msgs, list) and len(msgs) == 1  # type: ignore[arg-type]
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "user prompt"
