"""MCP tool definitions for the krach audio engine."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from krach_mcp._session import get_session
from krach_mcp._patterns import parse_pattern


def register_tools(mcp: FastMCP) -> None:
    """Register all krach tools on the MCP server."""

    @mcp.tool()
    def node(
        name: str,
        source: str,
        gain: float = 0.5,
        count: int = 1,
    ) -> str:
        """Create or replace an audio node.

        Args:
            name: Node name (e.g. "bass", "drums/kick").
            source: Python DSP function source code, OR a registered type_id (e.g. "faust:kick").
            gain: Output gain (0.0-1.0 typical, warn above 2.0).
            count: Number of poly instances (>1 for chords — must be >= chord size).
        """
        kr = get_session()
        if source.startswith("faust:") or source.startswith('"') or "def " not in source:
            handle = kr.node(name, source, gain=gain, count=count)
        else:
            # Source is Python code — compile it
            ns: dict[str, object] = {}
            import krach.dsp as krs
            ns["krs"] = krs
            exec(compile(source, f"<dsp:{name}>", "exec"), ns)  # noqa: S102
            # Find the function (last def in the source)
            fn = None
            for v in ns.values():
                if callable(v) and v is not krs:
                    fn = v
            if fn is None:
                return f"Error: no function found in source code for '{name}'"
            handle = kr.node(name, fn, gain=gain, count=count)
        return str(handle)

    @mcp.tool()
    def play(target: str, pattern: str, swing: float | None = None) -> str:
        """Play a pattern on a node or control path.

        Args:
            target: Node name ("bass") or control path ("bass/cutoff").
            pattern: Mini-notation ("x . x . x . . x", "C4 E4 G4 ~ C5")
                     or builder expression ("note('C4', 'E4').over(2) + rest()").
            swing: Optional swing amount (0.5=straight, 0.67=standard, 0.75=heavy).
        """
        kr = get_session()
        pat = parse_pattern(pattern)
        kr.play(target, pat, swing=swing)
        return f"Playing on '{target}'"

    @mcp.tool()
    def set_control(path: str, value: float) -> str:
        """Set a control parameter value.

        Args:
            path: Control path like "bass/cutoff" or "bass/gain".
                  For poly nodes, automatically fans out to all instances.
            value: The value to set. Must be within the control's declared [lo, hi] range.
        """
        kr = get_session()
        kr.set(path, value)
        return f"Set {path} = {value}"

    @mcp.tool()
    def gain(name: str, value: float) -> str:
        """Set a node's output gain. Instant (no graph rebuild).

        Args:
            name: Node name or group prefix (e.g. "bass", "drums").
            value: Gain level (0.0-1.0 typical, warns above 2.0).
        """
        kr = get_session()
        kr.gain(name, value)
        return f"Gain '{name}' = {value}"

    @mcp.tool()
    def send(source: str, target: str, level: float = 0.5) -> str:
        """Route audio from source node to target effect node.

        Args:
            source: Source node name.
            target: Target effect node name.
            level: Send level (0.0-1.0).
        """
        kr = get_session()
        kr.send(source, target, level=level)
        return f"Send '{source}' → '{target}' at {level}"

    @mcp.tool()
    def hush(name: str) -> str:
        """Silence a node, control path, or group.

        Args:
            name: Node name, control path ("bass/cutoff"), or group prefix ("drums").
        """
        kr = get_session()
        kr.hush(name)
        return f"Hushed '{name}'"

    @mcp.tool()
    def stop() -> str:
        """Silence all nodes and release all gates."""
        kr = get_session()
        kr.stop()
        return "Stopped all"

    @mcp.tool()
    def fade(path: str, target: float, bars: int = 4) -> str:
        """Fade a parameter to a target value over N bars.

        Args:
            path: Node name (fades gain) or control path ("bass/cutoff").
            target: Target value.
            bars: Duration in bars.
        """
        kr = get_session()
        kr.fade(path, target, bars=bars)
        return f"Fading {path} → {target} over {bars} bars"

    @mcp.tool()
    def status() -> str:
        """Return current session state: nodes, controls, transport."""
        kr = get_session()
        lines = [f"tempo={kr.tempo} bpm, master={kr.master}"]
        for name, node in kr.node_data.items():
            kind = "fx" if node.num_inputs > 0 else "src"
            ctrl_info = ", ".join(
                f"{c}=[{lo:.0f},{hi:.0f}]"
                for c, (lo, hi) in node.control_ranges.items()
            )
            parts = f"  {name}: {node.type_id} gain={node.gain:.2f} [{kind}]"
            if node.count > 1:
                parts += f" poly({node.count})"
            if ctrl_info:
                parts += f" ({ctrl_info})"
            lines.append(parts)
        slots = kr.slots
        if slots:
            lines.append("")
            for slot, state in slots.items():
                label = "playing" if state.playing else "stopped"
                lines.append(f"  {slot}: {label}")
        return "\n".join(lines)

    @mcp.tool()
    def list_controls(name: str) -> str:
        """List all controls for a node with their ranges.

        Args:
            name: Node name.
        """
        kr = get_session()
        node = kr.get_node(name)
        if node is None:
            return f"No node named '{name}'"
        lines = [f"Controls for '{name}' ({node.type_id}):"]
        for ctrl in node.controls:
            rng = node.control_ranges.get(ctrl)
            current = kr.get_ctrl(name, ctrl)
            if rng:
                lo, hi = rng
                lines.append(f"  {ctrl}: current={current:.2f} range=[{lo:.2f}, {hi:.2f}]")
            else:
                lines.append(f"  {ctrl}: current={current:.2f}")
        return "\n".join(lines)

    @mcp.tool()
    def set_tempo(bpm: float) -> str:
        """Set the tempo in BPM.

        Args:
            bpm: Beats per minute (typically 60-200).
        """
        kr = get_session()
        kr.tempo = bpm
        return f"Tempo = {bpm} BPM"

    @mcp.tool()
    def remove(name: str) -> str:
        """Remove a node and all its routing.

        Args:
            name: Node name to remove.
        """
        kr = get_session()
        kr.remove(name)
        return f"Removed '{name}'"
