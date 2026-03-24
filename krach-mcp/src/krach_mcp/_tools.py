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

        Example: node("bass", "def bass():\\n  freq = krs.control('freq', 55, 20, 800)\\n  gate = krs.control('gate', 0, 0, 1)\\n  return krs.saw(freq) * gate", gain=0.3)
        Example: node("kick", "faust:kick", gain=0.8)

        Args:
            name: Node name (e.g. "bass", "drums/kick").
            source: Either a registered type_id ("faust:kick") or Python DSP function source.
                    DSP functions use krs.* for oscillators/filters/controls.
            gain: Output gain (0.0-1.0 typical, warn above 2.0).
            count: Poly instances for chords (must be >= simultaneous notes).
        """
        kr = get_session()
        if source.startswith("faust:") or "def " not in source:
            handle = kr.node(name, source, gain=gain, count=count)
        else:
            import krach.dsp as krs
            ns: dict[str, object] = {"__builtins__": {}, "krs": krs}
            exec(compile(source, f"<dsp:{name}>", "exec"), ns)  # noqa: S102
            fn = next((v for v in ns.values() if callable(v) and v is not krs), None)
            if fn is None:
                return f"Error: no function found in source code for '{name}'"
            handle = kr.node(name, fn, gain=gain, count=count)
        return str(handle)

    @mcp.tool()
    def play(target: str, pattern: str, swing: float | None = None) -> str:
        """Play a pattern on a node or control path.

        Example: play("kick", "hit() * 4")
        Example: play("bass", "seq('A2', 'D3', None, 'E2').over(2)")
        Example: play("bass/cutoff", "mod_sine(200, 2000).over(4)")
        Example: play("hat", "x . x . x . . x")

        Args:
            target: Node name ("bass") or control path ("bass/cutoff").
            pattern: Mini-notation ("x . x .", "C4 E4 G4 ~") or builder
                     expression ("note('C4', 'E4').over(2) + rest()").
            swing: Swing amount (0.5=straight, 0.67=standard, 0.75=heavy).
        """
        kr = get_session()
        pat = parse_pattern(pattern)
        kr.play(target, pat, swing=swing)
        return f"Playing on '{target}'"

    @mcp.tool()
    def set_control(path: str, value: float) -> str:
        """Set a control parameter. Value must be within declared [lo, hi] range.

        Example: set_control("bass/cutoff", 1200.0)
        Example: set_control("bass/gain", 0.3)

        Args:
            path: Control path ("bass/cutoff"). Poly nodes auto-fan-out.
            value: Value within the control's declared range.
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
    def connect(source: str, target: str, level: float = 1.0) -> str:
        """Route audio from source to target (send with gain, or direct wire).

        Example: connect("bass", "verb", level=0.4)
        Example: connect("kick", "comp")

        Args:
            source: Source node name.
            target: Target node name (auto-promoted to effect if needed).
            level: Send level (0.0-1.0). Default 1.0.
        """
        kr = get_session()
        kr.connect(source, target, level=level)
        return f"Connected '{source}' → '{target}' at {level}"

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
    def mute(name: str) -> str:
        """Mute a node (stores gain, sets to 0). Unmute restores it.

        Example: mute("bass")
        """
        kr = get_session()
        kr.mute(name)
        return f"Muted '{name}'"

    @mcp.tool()
    def unmute(name: str) -> str:
        """Unmute a previously muted node (restores saved gain).

        Example: unmute("bass")
        """
        kr = get_session()
        kr.unmute(name)
        return f"Unmuted '{name}'"

    @mcp.tool()
    def status() -> str:
        """Return full session state: transport, nodes, routing, active patterns."""
        kr = get_session()
        lines = [f"tempo={kr.tempo} bpm, master={kr.master}"]

        # Nodes
        lines.append("\nNodes:")
        for name, n in kr.node_data.items():
            kind = "fx" if n.num_inputs > 0 else "src"
            parts = f"  {name}: {n.type_id} gain={n.gain:.2f} [{kind}]"
            if n.count > 1:
                parts += f" poly({n.count})"
            if kr.is_muted(name):
                parts += " [muted]"
            lines.append(parts)

        # Routing
        sends = kr._sends  # type: ignore[attr-defined]
        wires = kr._wires  # type: ignore[attr-defined]
        if sends or wires:
            lines.append("\nRouting:")
            for (src, tgt), lvl in sends.items():
                lines.append(f"  {src} → {tgt} (level={lvl:.2f})")
            for (src, tgt), port in wires.items():
                lines.append(f"  {src} → {tgt}:{port}")

        # Active patterns
        slots = kr.slots
        if slots:
            lines.append("\nPatterns:")
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
