# krach-mcp

MCP server that exposes krach operations as tools for Claude Code. 25 tools covering node lifecycle, pattern playback, routing, scenes, automation, and session management.

## Quick start

```bash
cd krach-mcp && uv sync
```

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "krach": {
      "command": "uv",
      "args": ["--directory", "/path/to/noise/krach-mcp", "run", "krach-mcp"],
      "env": { "KRACH_SOCKET": "/tmp/krach.sock" }
    }
  }
}
```

## Tool reference

### Transport

| Tool | Parameters | Description |
|------|-----------|-------------|
| `start` | `build?: bool, bpm?: float, master?: float` | Start the krach engine |
| `stop` | — | Silence all nodes and release all gates |
| `set_tempo` | `bpm: float` | Set tempo in BPM |
| `set_meter` | `beats: float` | Set beats per cycle (default 4 for 4/4) |
| `status` | — | Full session snapshot: transport, nodes, routing, patterns, types |

### Nodes

| Tool | Parameters | Description |
|------|-----------|-------------|
| `node` | `name: str, source: str, gain?: float, count?: int` | Create or replace an audio node |
| `remove` | `name: str` | Remove a node and all its routing |
| `gain` | `name: str, value: float` | Set node output gain (instant, no rebuild) |
| `mute` | `name: str` | Mute a node (stores gain, sets to 0) |
| `unmute` | `name: str` | Unmute (restores saved gain) |
| `list_controls` | `name: str` | List all controls with their ranges |
| `set_control` | `path: str, value: float` | Set a control value by path |

### Patterns

| Tool | Parameters | Description |
|------|-----------|-------------|
| `play` | `target: str, pattern: str, swing?: float` | Play a pattern on a node or control path |
| `hush` | `name: str` | Silence a node, control path, or group |

### Routing

| Tool | Parameters | Description |
|------|-----------|-------------|
| `connect` | `source: str, target: str, level?: float` | Route audio from source to target |
| `disconnect` | `source: str, target: str` | Remove a send/wire between two nodes |

### Automation

| Tool | Parameters | Description |
|------|-----------|-------------|
| `fade` | `path: str, target: float, bars?: int` | Fade a parameter over N bars |
| `mod` | `path: str, shape: str, lo?: float, hi?: float, bars?: int` | Native engine automation (sine, tri, ramp, square) |

### Scenes & Persistence

| Tool | Parameters | Description |
|------|-----------|-------------|
| `save` | `name: str` | Save session as named in-memory scene |
| `recall` | `name: str` | Recall a saved scene |
| `capture` | `name?: str` | Capture session as frozen ModuleIr JSON |
| `export_session` | `path: str` | Export session to reloadable Python file |
| `load_session` | `path: str` | Load a previously exported session |
| `export_module` | `name: str, path: str` | Export a saved module to JSON file |
| `load_module` | `path: str, name?: str` | Load a module from JSON and optionally instantiate |

## LLM agent workflow

### Typical session flow

1. **Start** — `start(bpm=128)` to launch the engine
2. **Build nodes** — `node("kick", "kick.py")`, `node("bass", "acid_bass.py")`
3. **Play patterns** — `play("kick", "hit() * 4")`, `play("bass", "seq('A2', 'D3', None, 'E2').over(2)")`
4. **Route** — `connect("bass", "verb", level=0.4)`
5. **Tweak** — `set_control("bass/cutoff", 1200)`, `fade("bass/gain", 0.0, bars=4)`
6. **Check state** — `status()` returns complete session snapshot
7. **Save** — `save("verse")`, `export_session("verse.py")`

### Best practices for agents

- Call `status()` after changes to verify state
- Use `list_controls(name)` before setting controls — confirms available parameters and ranges
- Use `capture()` before destructive changes — enables rollback
- Pattern strings are Python expressions: `"hit() * 4"`, `"seq('C4', 'E4').over(2)"`, `"mod_sine(200, 2000).over(4)"`
- Mini-notation also works: `"x . x . x . . x"`, `"C4 E4 G4"`
- Control paths use `/`: `"bass/cutoff"`, `"drums/kick/gain"`

## DSP file conventions

DSP files are Python files in `~/.krach/dsp/` defining one function using `krs.*` primitives. The `krs` module is auto-injected — no imports needed.

```python
# ~/.krach/dsp/acid_bass.py
def acid_bass():
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55
```

- One callable per file, no arguments
- Use `krs.control(name, default, lo, hi)` for parameters
- `"freq"` + `"gate"` are conventional for melodic synths
- Return the final audio signal

## Pattern expression grammar

The `pattern` parameter in `play()` accepts two formats:

### Builder expressions

Python expressions using pattern builders (no builtins, safe eval):

```python
"hit() * 4"                              # 4 kicks
"seq('A2', 'D3', None, 'E2').over(2)"   # bass line (None = rest)
"note('C4', 'E4').over(2)"              # two notes over 2 bars
"mod_sine(200, 2000).over(4)"           # control modulation
"note('C4') + rest() + note('E4')"      # composed sequence
```

Available builders: `note`, `hit`, `seq`, `rest`, `cat`, `stack`, `struct`, `ramp`, `rand`, `sine`, `saw`, `mod_sine`, `mod_tri`, `mod_ramp`, `mod_ramp_down`, `mod_square`, `mod_exp`.

Operators: `.over(N)` duration, `* N` repeat, `+` concatenate, `|` layer.

### Mini-notation

Space-separated symbols for quick entry:

```
"x . x . x . . x"     # drum pattern (x = hit, . = rest)
"C4 E4 G4"             # note sequence
"C4 E4 ~ G4"           # with tie
```
