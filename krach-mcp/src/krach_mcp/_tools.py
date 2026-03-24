"""MCP tool definitions for the krach audio engine."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from krach_mcp._session import get_session, start_session
from krach_mcp._patterns import parse_pattern


def _node_from_file(
    kr: object, name: str, path: str, gain: float, count: int,
) -> object:
    """Load a DSP function from a .py file and create a node."""
    import os
    import krach.dsp as krs
    from krach._types import dsp as _dsp

    resolved = os.path.expanduser(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"DSP file not found: {resolved}")

    source_text = open(resolved).read()  # noqa: SIM115
    ns: dict[str, object] = {"__builtins__": {}, "krs": krs}
    exec(compile(source_text, resolved, "exec"), ns)  # noqa: S102

    fn = next((v for v in ns.values() if callable(v) and v is not krs), None)
    if fn is None:
        raise ValueError(f"no function found in {resolved}")

    dsp_def = _dsp(fn, source=source_text)
    return kr.node(name, dsp_def, gain=gain, count=count)  # type: ignore[union-attr]


def register_tools(mcp: FastMCP) -> None:
    """Register all krach tools on the MCP server."""

    @mcp.tool()
    def start(build: bool = True, bpm: float = 120, master: float = 0.7) -> str:
        """Start the krach audio engine. Call this first before making music.

        Example: start()                    — build engine + connect
        Example: start(build=False)         — connect to already-running engine
        Example: start(bpm=140, master=0.8) — custom tempo and master gain

        Args:
            build: If True, runs cargo build before starting (slower but ensures latest code).
            bpm: Initial tempo in beats per minute.
            master: Master output gain (0.0-1.0).
        """
        try:
            kr = start_session(build=build, bpm=bpm, master=master)
            return f"Engine started. tempo={kr.tempo} bpm, master={kr.master:.2f}"
        except Exception as e:
            return f"Error starting engine: {e}"

    @mcp.tool()
    def node(
        name: str,
        source: str,
        gain: float = 0.5,
        count: int = 1,
    ) -> str:
        """Create or replace an audio node.

        source is either a registered type_id or a path to a Python DSP file.
        To create a DSP, write a .py file first (using the Write tool), then
        pass its path here.

        Example: node("kick", "faust:kick", gain=0.8)
        Example: node("bass", "~/.krach/dsp/bass.py", gain=0.3)

        The .py file should define a function using krs.* primitives
        (krs is available automatically — no import needed):
            def bass():
                freq = krs.control("freq", 55.0, 20.0, 800.0)
                gate = krs.control("gate", 0.0, 0.0, 1.0)
                return krs.saw(freq) * gate

        Args:
            name: Node name (e.g. "bass", "drums/kick").
            source: Registered type_id ("faust:kick") or path to a .py DSP file.
            gain: Output gain (0.0-1.0 typical, warn above 2.0).
            count: Poly instances for chords (must be >= simultaneous notes).
        """
        kr = get_session()
        if source.endswith(".py"):
            handle = _node_from_file(kr, name, source, gain, count)
        else:
            handle = kr.node(name, source, gain=gain, count=count)
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
        """Return full session state in one call: transport, nodes with controls, routing, patterns, available types.

        Call this before making changes to understand the current session.
        """
        from krach._ir_summary import summarize as _summarize

        kr = get_session()
        lines = [f"tempo={kr.tempo} bpm, meter={kr.meter}, master={kr.master:.2f}"]

        # Nodes with inline controls
        if kr.node_data:
            lines.append("\nNodes:")
            ctrl_vals = kr.ctrl_values
            for name, n in kr.node_data.items():
                kind = "fx" if n.num_inputs > 0 else "src"
                parts = f"  {name}: {n.type_id} gain={n.gain:.2f} [{kind}]"
                if n.count > 1:
                    parts += f" poly({n.count})"
                if kr.is_muted(name):
                    parts += " [muted]"
                lines.append(parts)
                # Inline controls: name=current [lo, hi]
                if n.controls:
                    ctrls = []
                    for ctrl in n.controls:
                        current = ctrl_vals.get(f"{name}/{ctrl}", 0.0)
                        rng = n.control_ranges.get(ctrl)
                        if rng:
                            ctrls.append(f"{ctrl}={current:.2g} [{rng[0]:.4g}, {rng[1]:.4g}]")
                        else:
                            ctrls.append(f"{ctrl}={current:.2g}")
                    lines.append(f"    {', '.join(ctrls)}")

        # Routing (public API — no private attr access)
        routes = kr.routing
        if routes:
            lines.append("\nRouting:")
            for src, tgt, kind, val in routes:
                if kind == "send":
                    lines.append(f"  {src} -> {tgt} (send, level={val})")
                else:
                    lines.append(f"  {src} -> {tgt}:{val}")

        # Active patterns with content summaries
        slots = kr.slots
        if slots:
            lines.append("\nPatterns:")
            for slot, state in slots.items():
                label = "playing" if state.playing else "stopped"
                try:
                    summary = _summarize(state.pattern.node)
                    lines.append(f"  {slot}: {label} — {summary}")
                except (ValueError, TypeError, KeyError):
                    lines.append(f"  {slot}: {label}")

        # Available types
        types = kr.node_controls
        if types:
            lines.append("\nAvailable types:")
            for tid, ctrls in types.items():
                lines.append(f"  {tid} ({', '.join(ctrls)})")

        # Scenes
        scenes = kr.scenes
        if scenes:
            lines.append(f"\nScenes: {', '.join(scenes)}")

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
    def set_meter(beats: float) -> str:
        """Set the meter (beats per cycle). Default 4 (4/4 time).

        Example: set_meter(3)   — waltz (3/4)
        Example: set_meter(7)   — 7/8

        Args:
            beats: Beats per cycle.
        """
        kr = get_session()
        kr.meter = beats
        return f"Meter = {beats} beats/cycle"

    @mcp.tool()
    def remove(name: str) -> str:
        """Remove a node and all its routing.

        Args:
            name: Node name to remove.
        """
        kr = get_session()
        kr.remove(name)
        return f"Removed '{name}'"

    @mcp.tool()
    def disconnect(source: str, target: str) -> str:
        """Remove a send/wire between two nodes without destroying either node.

        Example: disconnect("bass", "verb")

        Args:
            source: Source node name.
            target: Target node name.
        """
        kr = get_session()
        kr.unsend(source, target)
        return f"Disconnected '{source}' → '{target}'"

    @mcp.tool()
    def save(name: str) -> str:
        """Save current session as a named in-memory scene snapshot.

        Example: save("verse")

        Args:
            name: Scene name (recall later with recall()).
        """
        kr = get_session()
        kr.save(name)
        return f"Saved scene '{name}'"

    @mcp.tool()
    def recall(name: str) -> str:
        """Recall a saved scene — rebuilds graph, replays patterns, restores controls.

        Example: recall("verse")

        Args:
            name: Scene name (previously saved with save()).
        """
        kr = get_session()
        try:
            kr.recall(name)
            return f"Recalled scene '{name}'"
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool()
    def export_session(path: str) -> str:
        """Export current session to a reloadable Python file.

        Example: export_session("~/.krach/sessions/my_jam.py")

        Args:
            path: File path to write. Use ~/.krach/sessions/ for the standard location.
        """
        import os
        kr = get_session()
        resolved = os.path.expanduser(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        kr.export(resolved)
        return f"Exported to {resolved}"

    @mcp.tool()
    def load_session(path: str) -> str:
        """Load a previously exported session file.

        Example: load_session("~/.krach/sessions/my_jam.py")

        Args:
            path: File path to load.
        """
        import os
        kr = get_session()
        resolved = os.path.expanduser(path)
        try:
            kr.load(resolved)
            return f"Loaded {resolved}"
        except (FileNotFoundError, RuntimeError) as e:
            return f"Error: {e}"

    @mcp.tool()
    def mod(path: str, shape: str, lo: float = 0.0, hi: float = 1.0, bars: int = 4) -> str:
        """Native engine automation — more efficient than pattern-based modulation.

        Example: mod("bass/cutoff", "sine", lo=200, hi=2000, bars=8)
        Example: mod("verb/room", "tri", lo=0.3, hi=0.9, bars=16)

        Args:
            path: Control path ("bass/cutoff").
            shape: Automation shape — "sine", "tri", "ramp", "square".
            lo: Minimum value (must be within control range).
            hi: Maximum value (must be within control range).
            bars: Duration in bars.
        """
        kr = get_session()
        kr.mod(path, shape, lo=lo, hi=hi, bars=bars)
        return f"Modulating {path} with {shape} [{lo}, {hi}] over {bars} bars"

    @mcp.tool()
    def capture(name: str | None = None) -> str:
        """Capture the current session as a frozen ModuleIr.

        If name is given, also saves it as a named scene.
        Returns the JSON representation of the captured module.

        Example: capture("verse1")

        Args:
            name: Optional scene name to save as.
        """
        import json
        kr = get_session()
        ir = kr.capture()
        if name:
            kr.save(name)
        return json.dumps(ir.to_dict(), indent=2)

    @mcp.tool()
    def export_module(name: str, path: str) -> str:
        """Export a saved module/scene to a JSON file.

        Example: export_module("verse1", "~/.krach/modules/verse1.json")

        Args:
            name: Name of the saved scene/module.
            path: File path to write.
        """
        import json
        import os
        kr = get_session()
        try:
            ir = kr.module(name)
        except ValueError as e:
            return f"Error: {e}"
        resolved = os.path.expanduser(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w") as f:
            json.dump(ir.to_dict(), f, indent=2)
        return f"Exported module '{name}' to {resolved}"

    @mcp.tool()
    def load_module(path: str, name: str | None = None) -> str:
        """Load a module from a JSON file and optionally instantiate it.

        Example: load_module("~/.krach/modules/verse1.json", name="verse1")

        Args:
            path: JSON file path.
            name: If given, save the loaded module under this name.
        """
        import json
        import os
        from krach._module_ir import ModuleIr
        kr = get_session()
        resolved = os.path.expanduser(path)
        try:
            with open(resolved) as f:
                d = json.load(f)
            ir = ModuleIr.from_dict(d)
            kr.instantiate(ir)
            return f"Loaded and instantiated module from {resolved}"
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            return f"Error: {e}"
