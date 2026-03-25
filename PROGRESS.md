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
└── krach-mcp/         Python — MCP server (22 tools for Claude Code to drive krach)
```

faust-dsl merged into krach as `krach.ir.signal`, `krach.dsl.*`, `krach.backends.faust*`.

### IR architecture (unified)

Three typed IRs, each domain-specific:
- **Signal IR** (`krach.ir.signal`): `SignalPrimitive`, `SignalEqn`, `DspGraph` — flat DAG, data flows forward
- **Pattern IR** (`krach.ir.pattern`): `PatternPrimitive`, `PatternNode` — tree, nesting IS temporal semantics
- **Module IR** (`krach._module_ir`): `ModuleIr`, `NodeDef`, `RouteDef`, `PatternDef` — flat record

Pattern primitives use per-primitive rule registration (serialize). Generic `fold`/`fold_with_state` for tree traversal. `DspGraph` has canonicalization + structural hashing for cache keys.

### Test counts
- audio-engine: 163 Rust tests
- audio-faust: 29 Rust tests
- pattern-engine: 172 Rust tests
- krach-engine: 25 Rust tests
- krach: 710 Python tests
- **Total: 1099 tests**, all green. Pyright strict clean.

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
- **MCP server**: 25 tools for Claude Code to drive krach (node, play, status, capture, export, etc.)
- **Pattern IR**: PatternNode tree with per-primitive rules, generic fold, structural `__repr__`
- **DspGraph caching**: `dsp()` LRU keyed by hash of transpiled Faust IR (canonicalized)
- **Module system**: `kr.capture()` → ModuleIr, `kr.instantiate(ir)`, `kr.trace()` proxy
- **ModuleIr serialization**: `to_dict()` / `from_dict()` — JSON round-trip for persistence
- **Batch rollback**: all 6 state dicts restored on failed `with kr.batch():`

## Next

### IR consolidation: unified graph IR (priority: high)

ModuleIr is the top-level jaxpr. NodeDef holds DspGraph (not string).
Rename dsl/ → signal/, unify Primitive type, extract tracing from ir/.
DspGraph cached by graph_key — change a pattern, zero DSP recompilation.
See plan: `~/.claude/plans/ir-consolidation.md`

### Engine state sync: multi-client support (priority: high)

Add `Status` IPC command so multiple Python clients (REPL + MCP, or two
REPLs) share a single engine and see consistent state. Engine is the source
of truth; Python syncs on connect via `Mixer.pull()`.
See plan: `~/.claude/plans/engine-state-sync.md`

### Template caching (priority: medium)

XLA-style compilation cache for the pattern compiler. Hash pattern structure
(excluding seeds/cycle), cache EventTemplates.

### WASM Engine — full krach in the browser (priority: high)

Compile the actual Rust engine to WASM instead of reimplementing in JS.
Same code, different compile target. FAUST JIT in browser via libfaust-wasm.
