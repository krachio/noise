"""Session export — serialize current state to a reloadable Python script."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from krach.patterns.ir import ir_to_dict
from krach.patterns.pattern import Pattern

if TYPE_CHECKING:
    from krach._types import Node


def export_session(
    path: str,
    nodes: dict[str, Node],
    dsp_dir: Path,
    sends: dict[tuple[str, str], float],
    wires: dict[tuple[str, str], str],
    patterns: dict[str, Pattern],
    ctrl_values: dict[str, float],
    tempo: float,
    meter: float,
    master: float,
) -> None:
    """Export session state to a reloadable Python script."""
    lines: list[str] = [
        '"""Exported krach session."""',
        "import json",
        "from krach.patterns.ir import dict_to_ir",
        "from krach.patterns.pattern import Pattern",
        "import krach.dsp as krs",
        "",
    ]

    # DSP function definitions
    emitted_fns: dict[str, str] = {}
    for name, node in nodes.items():
        if node.source_text and node.type_id.startswith("faust:"):
            fn_name = name.replace("/", "_")
            lines.append("")
            source = node.source_text.rstrip()
            if "@kr.dsp" not in source and "@dsp" not in source:
                lines.append("@kr.dsp")
            lines.append(source)
            emitted_fns[node.type_id] = fn_name
    for bname, node in nodes.items():
        py_path = dsp_dir.joinpath(f"{bname}.py")
        if py_path.exists():
            fn_name = bname.replace("/", "_")
            source = py_path.read_text().rstrip()
            if fn_name not in emitted_fns.values():
                lines.append("")
                if "@kr.dsp" not in source and "@dsp" not in source:
                    lines.append("@kr.dsp")
                lines.append(source)
                emitted_fns[node.type_id] = fn_name

    # Nodes
    lines.append("")
    lines.append("with kr.batch():")
    sources = {n: v for n, v in nodes.items() if v.num_inputs == 0}
    effects = {n: v for n, v in nodes.items() if v.num_inputs > 0}
    for name, node in sources.items():
        src = emitted_fns.get(node.type_id, f'"{node.type_id}"')
        init_kw = "".join(f", {k}={v}" for k, v in node.init)
        count_kw = f", count={node.count}" if node.count > 1 else ""
        lines.append(f'    kr.node("{name}", {src}, gain={node.gain}{count_kw}{init_kw})')
    for name, node in effects.items():
        src = emitted_fns.get(node.type_id, f'"{node.type_id}"')
        lines.append(f'    kr.node("{name}", {src}, gain={node.gain})')

    # Sends and wires
    for (voice, bus), level in sends.items():
        lines.append(f'kr.send("{voice}", "{bus}", level={level})')
    for (voice, bus), port in wires.items():
        lines.append(f'kr.wire("{voice}", "{bus}", port="{port}")')

    # Transport
    lines.append(f"kr.tempo = {tempo}")
    lines.append(f"kr.master = {master}")
    if meter != 4.0:
        lines.append(f"kr.meter = {meter}")

    # Patterns as JSON
    if patterns:
        pat_dict = {slot: ir_to_dict(pat.node) for slot, pat in patterns.items()}
        pat_json = json.dumps(pat_dict, separators=(",", ":"))
        lines.append("")
        lines.append(f"_patterns = json.loads('{pat_json}')")
        lines.append("for _slot, _ir in _patterns.items():")
        lines.append("    kr.play(_slot, Pattern(dict_to_ir(_ir)))")

    # Control values
    for ctrl_path, value in ctrl_values.items():
        lines.append(f'kr.set("{ctrl_path}", {value})')

    lines.append("")
    Path(path).write_text("\n".join(lines))
