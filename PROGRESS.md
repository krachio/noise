# Progress

## Current state

Live coding audio system — monorepo, Cargo workspace + Python (uv).

```
noise/
├── audio-engine/      Rust — audio engine (graph runtime, node reuse, crossfade, gain smoothing)
├── audio-faust/       Rust — FAUST LLVM JIT plugin (hot reload, recursive dir watcher)
├── pattern-engine/    Rust — pattern sequencer (min-heap, rational time, phase-reset, meter)
├── krach-engine/      Rust — unified binary (pattern-engine + audio-engine + audio-faust, Unix + TCP)
├── krach/             Python — live coding REPL (graph API, patterns, DSP transpiler)
└── krach-mcp/         Python — MCP server (25 tools for Claude Code to drive krach)
```

### Package structure (post-restructure)

```
krach/src/krach/
  __init__.py           Mixer, GraphHandle, NodeHandle, graph decorator
  mixer.py              Mixer + MixerProtocol + NodeHandle
  session.py            Engine IPC (Session, KernelError, SlotState)
  export.py             export_session()
  config.py             Config

  ir/                   SHARED kernel (5 files)
    primitive.py        Primitive(name, stateful)
    values.py           Note, Cc, Osc, Control, Value
    canonicalize.py     graph_key, graph_ir_key
    registry.py         RuleRegistry
    graph.py            GraphIr, NodeDef, RouteDef, prefix_ir, flatten

  signal/               krs: types + impl + user API
    __init__.py         USER API (__all__): ~60 DSP functions + Signal
    types.py            Signal, DspGraph, Equation, *Params
    trace.py            TraceContext, bind, coerce_to_signal
    primitives.py       Primitive instances + abstract_eval rules
    transpile.py        make_graph, collect_controls, control()
    core.py             Core DSP functions (delay, feedback, sr, math)
    lib.py              Oscillators, filters, noise, effects, utilities
    music.py            Envelopes, effects, scales, spatial
    compose.py          Graph composition
    optimize.py         Graph optimization passes
    ad.py, ad_rules.py  Automatic differentiation

  pattern/              krp: types + impl + user API
    __init__.py         USER API (__all__): builders + Pattern + pitch
    types.py            PatternNode, *Params
    pattern.py          Pattern wrapper, operators
    primitives.py       Pattern primitive instances
    builders.py         note, hit, seq, sine, tri, ramp, etc.
    bind.py             Voice binding
    serialize.py        PatternNode ↔ dict
    summary.py          Pattern summary
    mininotation.py     Mini-notation parser
    pitch.py            MIDI/Hz conversion
    transform.py        every, reverse, fast, shift, spread, thin

  graph/                Graph construction layer
    __init__.py         Re-exports: Node, GraphProxy, graph, build_graph_ir
    node.py             Node, DspDef, dsp(), path resolution, build_graph_ir
    proxy.py            GraphProxy, SubGraphRef, graph decorator

  backends/             Lowering: domain IR → wire format
    faust.py            DspGraph → FAUST source
    pattern.py          PatternNode → krach-engine pattern commands
    graph.py            NodeInstance + ConnectionIr → krach-engine graph payload

  repl/
    __init__.py         LiveMixer, connect, main
    paths.py            resolve_engine_bin, resolve_lib_dir
```

### Three-symbol API

```python
# kr  — audio graph (Mixer)
# krs — DSP (from krach import signal as krs)
# krp — patterns (from krach import pattern as krp)

from krach import signal as krs

def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

bass = kr.node("bass", acid_bass, gain=0.3)
verb = kr.node("verb", reverb_fn, gain=0.3)

bass >> (verb, 0.4)
bass @ krp.seq("A2", "D3", None, "E2").over(2)
bass @ ("cutoff", krp.sine(400, 2000).over(4))
bass["cutoff"] = 1200
```

### Test counts
- audio-engine: 167 Rust tests
- audio-faust: 29 Rust tests
- pattern-engine: 192 Rust tests
- krach-engine: 42 Rust tests
- krach: 831 Python tests
- krach-mcp: 21 Python tests
- **Total: 1282 tests**, all green. Pyright strict clean.

## Key features

- **Graph-first API**: `kr.node()` auto-detects source vs effect — one constructor for everything
- **Operator DSL**: `>>` routes signal, `@` plays patterns, `[]` gets/sets controls — fast REPL workflow
- **Three-symbol API**: `kr` (audio graph) + `krs` (signal) + `krp` (patterns) — clean namespace for live coding
- **Unbound patterns**: `krp.note("C4")`, `krp.hit()`, `krp.seq("A2", "D3")` — bind to node at play time
- **7 pattern shapes**: `sine`, `tri`, `ramp`, `ramp_down`, `square`, `exp`, `rand` — clean, no aliases
- **`/` path addressing**: `kr.set("bass/cutoff", 1200)`, `kr.fade("verb/room", 0.8, bars=8)`
- **Node handles**: `bass = kr.node(...)` returns proxy — `bass @ pattern`, `bass["cutoff"] = 1200`, `bass >> verb`
- **Unified routing**: `kr.connect()` / `>>` replaces send/wire split — level and port as params
- **FAUST auto-smoothing**: DSP controls with si.smoo applied automatically, no zipper noise
- **Protocol hardening**: IPC message validation, length-prefixed framing, reconnect on stale socket
- **TCP support**: `--tcp <addr>` / `NOISE_TCP_ADDR` enables remote connections with token auth; `connect_remote()` in Python
- **Native automation lanes**: block-rate modulation on audio thread (AutoShape + GraphSwapper)
- **Typed Control IR**: `Control(label, value)` replaces OSC string convention
- **Continuous patterns**: `krp.sine()`, `krp.ramp()`, `krp.rand()` — smooth control sweeps
- **Mini-notation**: `krp.p("x . x . x . . x")` for fast pattern entry
- **Scenes**: `kr.save("verse")` / `kr.recall("chorus")` — snapshot + restore
- **MCP server**: 25 tools for Claude Code to drive krach — chord(), euclid(), AST-safe pattern eval
- **Pattern IR**: PatternNode tree with per-primitive rules, generic fold, structural `__repr__`
- **DspGraph caching**: `dsp()` LRU keyed by `graph_key` (structural hash of DspGraph)
- **Module composition**: `prefix_ir()`, `flatten()`, `@kr.graph` decorator, `GraphHandle` with `>>`, `@`, `[]` operators
- **Module system**: `kr.capture()` → GraphIr, `kr.load(ir)`, `kr.instantiate(ir, prefix)` → GraphHandle, `kr.trace()` proxy
- **GraphIr serialization**: `to_dict()` / `from_dict()` — JSON round-trip for persistence
- **Batch rollback**: all 6 state dicts restored on failed `with kr.batch():`
- **Engine state sync**: `{"cmd":"Status"}` IPC returns full snapshot; `kr.pull()` syncs Python from engine; MCP auto-syncs on status()
- **Vendored wheel packaging**: `pip install krach` on macOS ARM64 + Linux x86_64 (macOS Intel paused — needs paid runner)
- **Cross-platform build.rs**: env vars (FAUST_LIB_DIR, LLVM_LIB_DIR) → pkg-config → platform defaults
- **FAUST stdlib override**: `FAUST_STDLIB_DIR` env var → `-I` flag to JIT compiler, enabling vendored stdlib
- **CI release matrix**: 2-platform wheel build (macos-14, ubuntu-22.04) + PyPI trusted publishing + clean-install test + GitHub Release
- **PyPI v0.1.0 published**: full metadata, `krach --version`, THIRD_PARTY_LICENSES (GPL for libfaust, Apache for LLVM)
- **MIDI clock input**: external clock sync for jam sessions — ClockFollower (EMA + jitter gate), `kr.sync = "midi"`, `NOISE_MIDI_SYNC=1`, `--midi-sync` CLI flag, 2s timeout fallback, phase correction

## Backlog

Issues tracked at https://github.com/krachio/noise/issues

### Later

- **krach-stdlib** — composable GraphIr building blocks (looper, drum machine,
  polysynth). Module infrastructure is done; stdlib builds on top.
- **WASM engine** — Rust → WASM, browser client
- **Template caching** — XLA-style pattern compilation cache (Rust)
- **graph_key determinism** (#6) — replace hash() with SHA-256
- **Mermaid diagrams** (#10) — replace ASCII art in mkdocs
- **macOS Intel wheel** — blocked on paid CI runner
