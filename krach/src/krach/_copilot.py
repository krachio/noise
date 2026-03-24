from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionState:
    bpm: float
    playing: tuple[str, ...]
    stopped: tuple[str, ...]
    nodes: tuple[str, ...]
    node_controls: tuple[tuple[str, tuple[str, ...]], ...]
    in_scope: tuple[str, ...]
    active_nodes: tuple[tuple[str, str, float, tuple[str, ...]], ...] = ()
    # (node_name, type_id, gain, (param1, param2, ...))


def _load_context() -> str:
    p = Path(__file__).parent / "context.md"
    if p.exists():
        return p.read_text()
    return ""  # graceful fallback if context.md missing


_CONTEXT_MD = _load_context()

_HSLIDER_RE = re.compile(r'hslider\("([^"]+)"')
_CODE_BLOCK_RE = re.compile(r"```(?:python)?\n(.*?)```", re.DOTALL)


def parse_dsp_controls(source: str) -> tuple[str, ...]:
    """Return deduplicated hslider control names from a FAUST .dsp source string."""
    seen: dict[str, None] = {}
    for name in _HSLIDER_RE.findall(source):
        seen[name] = None
    return tuple(seen)
# Match '# ---' only when it is the entire content of a line.
_CELL_DIVIDER_RE = re.compile(r"^[ \t]*# ---[ \t]*$", re.MULTILINE)


def extract_code(response: str) -> str | None:
    """Return the content of the last fenced code block, or None if absent."""
    matches = _CODE_BLOCK_RE.findall(response)
    if not matches:
        return None
    code = matches[-1].strip()
    return code or None


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def split_cells(code: str) -> list[str]:
    """Split code on '# ---' dividers; drop chunks that are not valid Python."""
    chunks = _CELL_DIVIDER_RE.split(code)
    return [c.strip() for c in chunks if c.strip() and _is_valid_python(c.strip())]


def build_context(state: SessionState) -> str:
    """Build the system prompt: DSL reference + live session state."""
    lines = [
        "## Current session state",
        f"- BPM: {state.bpm}",
        f"- Playing slots: {list(state.playing) or 'none'}",
        f"- Stopped slots: {list(state.stopped) or 'none'}",
        f"- Loaded nodes: {list(state.nodes)}",
    ]
    if state.active_nodes:
        lines.append("- Active voices (use kr.note/kr.hit/kr.seq with these):")
        for vname, type_id, gain, params in state.active_nodes:
            labels = ", ".join(f"{vname}/{p}" for p in params)
            lines.append(f"  - {vname} ({type_id}, gain={gain}): {labels}")
    if state.node_controls:
        lines.append("- Node controls (use ONLY these labels with kr.set):")
        for node_id, controls in state.node_controls:
            lines.append(f"  - {node_id}: {', '.join(controls)}")
    if state.in_scope:
        lines.append(f"- Available symbols (do not import, already in scope): {', '.join(sorted(state.in_scope))}")
    return _CONTEXT_MD + "\n---\n\n" + "\n".join(lines) + "\n"


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
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return str(response.content[0].text)
