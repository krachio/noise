# Progress

## Current state

Live coding audio system — monorepo, Cargo workspace + Python (uv).

```
noise/
├── audio-engine/      Rust — audio engine (graph runtime, node reuse, crossfade, gain smoothing)
├── audio-faust/       Rust — FAUST LLVM JIT plugin (hot reload, recursive dir watcher)
├── pattern-engine/    Rust — pattern sequencer (min-heap, rational time, phase-reset, meter)
├── krach-engine/      Rust — unified binary (pattern-engine + audio-engine + audio-faust, one socket)
├── krach/             Python — live coding REPL (graph API, patterns, DSP transpiler, MCP server)
└── krach-mcp/         Python — MCP server (25 tools for Claude Code to drive krach)
```

### IR architecture (consolidated)

Pure `ir/` layer (7 files + __init__): frozen data, zero runtime imports.
- **Primitive** (`ir/primitive.py`): shared frozen dataclass, both domains
- **Signal IR** (`ir/signal.py`): `Signal`, `Equation`, `DspGraph`, typed params
- **Pattern IR** (`ir/pattern.py`): `PatternPrimitive` (= Primitive alias), `PatternNode`
- **Module IR** (`ir/module.py`): `ModuleIr`, `NodeDef(source: DspGraph | str)`, `RouteDef`
- **Values** (`ir/values.py`): `Note`, `Cc`, `Osc`, `Control`, `Value`
- **Canonicalize** (`ir/canonicalize.py`): `canonicalize()`, `graph_key()`, `module_key()`
- **Registry** (`ir/registry.py`): generic `RuleRegistry[P, R]` with `check_complete()` import-time guard

Tracing runtime in `signal/trace.py` (TraceContext, bind, coerce_to_signal).
Rules registered via RuleRegistry: abstract_eval in `signal/primitives.py`, lowering in `backends/faust_lowering.py`.
DspGraph cached by `graph_key` (structural hash). `NodeDef.source` holds `DspGraph` directly — Faust is derived, not canonical.

### krach surface (post-cleanup)

```
krach/
  mixer.py           Mixer + MixerProtocol + NodeHandle (single file, no mixins)
  node_types.py      Node, DspDef, dsp(), path resolution
  graph_builder.py   build_graph_ir() pure function
  module_proxy.py    ModuleProxy recorder
  export.py          export_session()
  config.py          Config
  dsp.py             krs namespace
  repl/              LiveMixer (REPL sugar), connect(), main(), banner
  ir/                (unchanged)
  signal/            (unchanged)
  pattern/           + mininotation.py, pitch.py (moved from root)
  backends/          (unchanged)
```

Library entry: `from krach.mixer import Mixer` — no REPL sugar, no staticmethods.
REPL entry: `krach.repl.connect()` returns `LiveMixer` with `kr.note()`, `kr.seq()`, etc.

### Test counts
- audio-engine: 167 Rust tests
- audio-faust: 29 Rust tests
- pattern-engine: 175 Rust tests
- krach-engine: 27 Rust tests
- krach: 760 Python tests
- krach-mcp: 21 Python tests
- **Total: 1181 tests**, all green. Pyright strict clean.

## Usage

```bash
./bin/krach
```

```python
# Two symbols: kr (audio graph) and krs (krach.dsp)
import krach.dsp as krs

# Define DSP functions — sources have no audio input params
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

# Effects take an audio input parameter — auto-detected by kr.node()
def reverb_fn(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room) * 0.8

# Create nodes
bass = kr.node("bass", acid_bass, gain=0.3)
verb = kr.node("verb", reverb_fn, gain=0.3)

# Operator DSL: >> routes, @ plays, [] controls
bass >> (verb, 0.4)
bass @ kr.seq("A2", "D3", None, "E2").over(2)
bass @ ("cutoff", kr.sine(400, 2000).over(4))
bass["cutoff"] = 1200

kr.tempo = 128
kr.meter = 4
kr.fade("bass/gain", 0.0, bars=4)
kr.mute("drums")
```

## Key features

- **Graph-first API**: `kr.node()` auto-detects source vs effect — one constructor for everything
- **Operator DSL**: `>>` routes signal, `@` plays patterns, `[]` gets/sets controls — fast REPL workflow
- **Two-symbol API**: `kr` (audio graph) + `krs` (krach.dsp) — clean namespace for live coding
- **Unbound patterns**: `kr.note("C4")`, `kr.hit()`, `kr.seq("A2", "D3")` — bind to node at play time
- **`/` path addressing**: `kr.set("bass/cutoff", 1200)`, `kr.fade("verb/room", 0.8, bars=8)`
- **Node handles**: `bass = kr.node(...)` returns proxy — `bass @ pattern`, `bass["cutoff"] = 1200`, `bass >> verb`
- **Unified routing**: `kr.connect()` / `>>` replaces send/wire split — level and port as params
- **FAUST auto-smoothing**: DSP controls with si.smoo applied automatically, no zipper noise
- **Protocol hardening**: IPC message validation, length-prefixed framing, reconnect on stale socket
- **Native automation lanes**: block-rate modulation on audio thread (AutoShape + GraphSwapper)
- **Typed Control IR**: `Control(label, value)` replaces OSC string convention
- **Continuous patterns**: `kr.sine()`, `kr.saw()`, `kr.rand()` — smooth control sweeps
- **Mini-notation**: `kr.p("x . x . x . . x")` for fast pattern entry
- **Scenes**: `kr.save("verse")` / `kr.recall("chorus")` — snapshot + restore
- **MCP server**: 25 tools for Claude Code to drive krach — chord(), euclid(), AST-safe pattern eval
- **Pattern IR**: PatternNode tree with per-primitive rules, generic fold, structural `__repr__`
- **DspGraph caching**: `dsp()` LRU keyed by `graph_key` (structural hash of DspGraph)
- **Module system**: `kr.capture()` → ModuleIr, `kr.instantiate(ir)`, `kr.trace()` proxy
- **ModuleIr serialization**: `to_dict()` / `from_dict()` — JSON round-trip for persistence
- **Batch rollback**: all 6 state dicts restored on failed `with kr.batch():`
- **Engine state sync**: `{"cmd":"Status"}` IPC returns full snapshot; `kr.pull()` syncs Python from engine; MCP auto-syncs on status()
- **Vendored wheel packaging**: `pip install krach` on macOS ARM64, macOS x86_64, Linux x86_64
- **Cross-platform build.rs**: env vars (FAUST_LIB_DIR, LLVM_LIB_DIR) → pkg-config → platform defaults
- **FAUST stdlib override**: `FAUST_STDLIB_DIR` env var → `-I` flag to JIT compiler, enabling vendored stdlib
- **CI release matrix**: 3-platform wheel build (macos-14, macos-13, ubuntu-22.04) + PyPI trusted publishing

## Backlog

### PyPI publish + Homebrew formula (priority: high)

Tag v0.1.0 to trigger CI release workflow → PyPI. Homebrew formula as
secondary install channel (`brew install krach`).

### Looper (priority: high)

Record live audio input into a buffer, play back as a pattern-triggered node.
`kr.record("loop1", bars=4)` → captures audio → `loop1 @ kr.hit() * 4`.

### Network sockets (priority: high)

TCP instead of Unix socket. Enables: remote jam sessions, multi-machine
setups, web client → engine communication. Prerequisite for browser REPL.

### Template caching (priority: medium)

XLA-style compilation cache for the pattern compiler. Hash pattern structure
(excluding seeds/cycle), cache EventTemplates.

### WASM Engine — full krach in the browser (priority: high)

Compile the actual Rust engine to WASM instead of reimplementing in JS.
Same code, different compile target. FAUST JIT in browser via libfaust-wasm.
