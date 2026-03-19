from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionState:
    bpm: float
    playing: tuple[str, ...]
    stopped: tuple[str, ...]
    nodes: tuple[str, ...]


_CONTEXT_MD = (Path(__file__).parent / "context.md").read_text()


def build_context(state: SessionState) -> str:
    """Build the system prompt: DSL reference + live session state."""
    live = (
        f"## Current session state\n"
        f"- BPM: {state.bpm}\n"
        f"- Playing slots: {list(state.playing) or 'none'}\n"
        f"- Stopped slots: {list(state.stopped) or 'none'}\n"
        f"- Loaded nodes: {list(state.nodes)}\n"
    )
    return _CONTEXT_MD + "\n---\n\n" + live


def format_status(state: SessionState) -> str:
    """Return a concise text snapshot of the current session."""
    lines = [f"BPM: {state.bpm}"]
    if state.playing or state.stopped:
        lines.append("slots:")
        for slot in state.playing:
            lines.append(f"  ▶ {slot}")
        for slot in state.stopped:
            lines.append(f"  ⏸ {slot}")
    lines.append(f"nodes: {', '.join(state.nodes) or 'none'}")
    return "\n".join(lines)


def ask_claude(client: Any, model: str, system: str, prompt: str) -> str:  # noqa: ANN401
    """Send a prompt to the Claude API and return the text response."""
    response = client.messages.create(
        model=model,
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return str(response.content[0].text)
