# Architecture

krach is a live coding system for music. A Python REPL sends pattern and audio commands over a Unix socket to a single Rust binary that sequences events and renders audio in real time.

## Monorepo structure

```
noise/
├── audio-engine/       Rust lib  — graph-based audio engine (NodeFactory, DspGraph, GraphSwapper)
├── audio-faust/        Rust lib  — FAUST LLVM JIT plugin, hot reload via file watcher
├── pattern-engine/     Rust lib  — pattern sequencer (IR compiler, scheduler, MIDI/OSC output)
├── krach-engine/       Rust bin  — unified process (pattern-engine + audio-engine + audio-faust)
├── krach/              Python    — live coding REPL, IR layer, DSP transpiler, graph API
└── krach-mcp/          Python    — MCP server (25 tools for Claude Code to drive krach)
```

**audio-engine** is DSP-agnostic. It provides a graph of `DspNode` instances wired together, processed in topological order, with lock-free graph swaps and linear crossfades. No synthesis code lives here — just wiring, mixing, and control routing.

**audio-faust** compiles FAUST `.dsp` files via LLVM JIT into `DspNode` implementations and registers them with audio-engine's `NodeRegistry`. A file watcher triggers hot reload on save.

**pattern-engine** is a Tidal Cycles-inspired sequencer. It compiles a JSON IR (pattern trees) into arena-indexed `CompiledPattern` structs, evaluates them over rational time, and dispatches MIDI and OSC events on a real-time scheduler thread.

**krach-engine** links all three into one process. Pattern events that target the audio engine are dispatched directly via function calls — no network hop.

**krach** is the user-facing Python REPL and the IR layer. It contains three typed IRs (Signal, Pattern, Module), a Python-to-FAUST DSP transpiler (`krach.signal` + `krach.backends`), pattern builders and transforms, and the graph management API. Starts `krach-engine` as a subprocess, connects over a Unix socket.

**krach-mcp** is an MCP server that exposes krach operations as tools for Claude Code — node creation, pattern playback, session capture/export, and introspection.

## Data flow

```
krach (Python REPL)
    │
    │  JSON over Unix socket ($TMPDIR/krach-engine.sock)
    │
    ▼
krach-engine (Rust, single process)
    │
    ├─── IPC thread ──── parse JSON ──── route by tag
    │         │                              │
    │    "cmd" tag                      "type" tag
    │         │                              │
    │         ▼                              ▼
    │    pattern-engine              audio-engine controller
    │    (EngineCommand)             (ClientMessage)
    │         │                              │
    │    scheduler thread            shadow graph + compiler
    │    (query patterns,            (compile, swap, crossfade)
    │     dispatch events)                   │
    │         │                         rtrb SPSC
    │         │                              │
    │         └──── direct fn call ──── AudioProcessor
    │                                        │
    │                                   DspGraph::process()
    │                                        │
    └─────────────────────────────────── cpal → CoreAudio
```

The IPC thread reads newline-delimited JSON from the socket. Messages with a `"cmd"` tag are pattern commands (SetPattern, Hush, etc.). Messages with a `"type"` tag are audio commands (load_graph, set_control, etc.). Both are sent over a single `crossbeam_channel` as `LoopCommand` variants to the main loop.

## Pattern compiler pipeline

```
Python IR (frozen dataclasses)
    │
    │  serialize to JSON
    ▼
IrNode (Rust, serde-tagged enum)
    │
    │  compile: validate, flatten into arena
    ▼
CompiledPattern (arena-indexed nodes)
    │
    │  query(arc): evaluate over rational time interval
    ▼
Vec<Event<Value>> (timed events with whole/part spans)
    │
    │  dispatch: match on Value type
    ▼
MIDI note-on/off  ──or──  audio-engine SetControl / SetAutomation
```

Pattern IR nodes: `Atom`, `Silence`, `Cat`, `Stack`, `Fast`, `Slow`, `Early`, `Late`, `Rev`, `Every`, `Euclid`, `Degrade`, `Freeze`.

Time is rational (`i64/u64` numerator/denominator). Subdivisions are exact — no floating-point drift. `Cat [a, b, c]` splits a cycle into exact thirds. `Fast [3, 2]` compresses by 3/2.

The scheduler runs a real-time loop with 1ms sleep. It queries each active slot for the current cycle window plus a 100ms lookahead, collects events, and dispatches them via the appropriate output sink.

## Audio graph

### NodeFactory and NodeRegistry

Every DSP type is registered as a `(NodeTypeDecl, NodeFactory)` pair. `NodeTypeDecl` declares ports (audio in/out) and controls (name, range, default). `NodeFactory::create(sample_rate, block_size)` returns a `Box<dyn DspNode>`.

Built-in types: `Oscillator` (sine/saw/square), `DacNode`. FAUST types are registered dynamically by `audio-faust`.

### DspGraph

A topologically sorted DAG of `DspNode` instances. Processing walks nodes in order, passing scratch buffers between connected ports. No allocation during `process()`.

### GraphSwapper

When the control thread compiles a new graph, it sends a `SwapGraph` command over an `rtrb` SPSC ring buffer. The audio thread crossfades linearly between old and new graphs over a configurable duration (default: half a beat at current BPM).

Node reuse: if the new graph contains a node with the same ID and type as the old graph, the existing instance is reused (preserving state, avoiding clicks).

### EngineController / AudioProcessor split

- **EngineController** (control thread): receives commands, maintains the shadow graph, compiles `GraphIr` → `DspGraph`, sends swap commands.
- **AudioProcessor** (audio thread): drains commands from the SPSC ring, processes the active graph, writes to the output buffer. No locks, no allocation.

Connected by an `rtrb` single-producer single-consumer ring buffer.

## Automation

Automation drives node parameters through repeating (or one-shot) waveforms at block rate.

Available shapes: `Sine`, `Tri`, `Ramp`, `RampDown`, `Square`, `Exp`, `Pulse { duty }`, `Custom { table }`.

Each shape is evaluated at normalised time `t` in `[0, 1)` producing a value in `[0, 1]`, then mapped to `[lo, hi]`. At 256-sample blocks and 44100 Hz sample rate, automation updates at ~172 Hz (once per block).

Automation is set via `SetAutomation` commands and cleared via `ClearAutomation`.

## FAUST JIT

```
~/.krach/dsp/
├── synth.dsp
├── filter.dsp
└── reverb.dsp
        │
        │  file watcher (notify crate)
        ▼
   FAUST LLVM JIT compiler
        │
        │  compile .dsp → machine code
        ▼
   DspNode implementation
        │
        │  register / re-register in NodeRegistry
        ▼
   Available as node type in audio graph
```

`HotReloadEngine` wraps an audio-engine with FAUST file watching. On startup, it scans a directory (default: `~/.krach/dsp/`, override with `NOISE_DSP_DIR`) and registers all `.dsp` files. When a file is saved, it recompiles the FAUST code and calls `reregister()` on the registry, then reloads the current graph to pick up the new node.

FAUST LLVM JIT is not thread-safe — tests run serialized via `.cargo/config.toml`.

## Unified binary design

krach-engine is a single process with:

- **One socket** (`$TMPDIR/krach-engine.sock`) for all IPC
- **One audio callback** (cpal → CoreAudio)
- **One main loop** that drains the command channel, queries patterns, dispatches events, and pumps the audio controller

Pattern events targeting the audio engine (OSC events with address `/audio/set`) are parsed and dispatched directly as `SetControl` calls — no UDP, no serialization.

MIDI note-offs are tracked in a `BinaryHeap<PendingNoteOff>` ordered by fire time. Audio control events use a similar pending queue for scheduled dispatch.

## Key design decisions

- **Block-rate automation**: parameter modulation happens once per audio block (~172 updates/sec at 256 samples / 44100 Hz), not per-sample. Good enough for musical LFOs, avoids per-sample branching.
- **Rational time**: patterns use exact rational arithmetic. No floating-point accumulation means subdivisions stay perfectly aligned over arbitrarily long performances.
- **Lock-free audio thread**: the audio callback never locks, never allocates, never blocks. All mutation happens on the control thread; the audio thread only reads.
- **Graph crossfade**: swapping graphs crossfades linearly over half a beat. Old node instances are reused when IDs match, avoiding discontinuities.
- **Direct dispatch**: in the unified binary, pattern → audio communication is a function call, not a network message. Latency is bounded by the scheduler's 1ms sleep + 100ms lookahead.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `NOISE_SOCKET` | `$TMPDIR/krach-engine.sock` | IPC socket path |
| `NOISE_DSP_DIR` | `~/.krach/dsp/` | FAUST .dsp file directory |
| `PATTERN_ENGINE_MIDI_CLOCK` | off | Set to `1` for 24 ppqn MIDI clock |

Engine defaults: 48 kHz sample rate, 256-sample blocks, stereo output.
