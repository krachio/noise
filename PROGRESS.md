# Progress

## Current state

Live coding audio system — monorepo, Cargo workspace + Python (uv).

```
noise/
├── audio-engine/      Rust — audio engine (graph runtime, node reuse, crossfade, gain smoothing)
├── audio-faust/       Rust — FAUST LLVM JIT plugin (hot reload, recursive dir watcher)
├── pattern-engine/    Rust — pattern sequencer (min-heap, rational time, phase-reset, meter)
├── krach-engine/      Rust — unified binary (pattern-engine + audio-engine + audio-faust, one socket)
├── faust-dsl/         Python — Python → Faust .dsp transpiler
└── krach/             Python — live coding REPL (graph API, patterns, copilot, DSP design)
```

### Test counts
- audio-engine: 161 Rust tests
- audio-faust: 22 Rust tests
- pattern-engine: 160 Rust tests
- krach-engine: 25 Rust tests
- faust-dsl: 68 Python tests
- krach: 442 Python tests (includes patterns module, namespace tests)
- **Total: 878 tests**, all green. Pyright strict clean.

## Usage

```bash
./bin/krach
```

```python
import krach.dsp as krs

@krs.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

# Two symbols: kr (audio graph) and krs (dsp)
bass = kr.node("bass", acid_bass, gain=0.3)
kick = kr.node("drums/kick", kick_fn, gain=0.8)
verb = kr.node("verb", reverb_fn, gain=0.3)

bass >> (verb, 0.4)
bass @ kr.seq("A2", "D3", None, "E2").over(2)
kick @ kr.hit() * 4
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
- **Voice-free patterns**: `kr.note("C4")`, `kr.hit()`, `kr.seq("A2", "D3")` — bind at play time
- **`/` path addressing**: `kr.set("bass/cutoff", 1200)`, `kr.fade("verb/room", 0.8, bars=8)`
- **Node handles**: `bass = kr.node(...)` returns proxy — `bass @ pattern`, `bass["cutoff"] = 1200`, `bass >> verb`
- **Unified routing**: `kr.connect()` / `>>` replaces send/wire split — level and port as params
- **FAUST auto-smoothing**: DSP controls with si.smoo applied automatically, no zipper noise
- **Protocol hardening**: IPC message validation, length-prefixed framing, reconnect on stale socket
- **Native automation lanes**: block-rate modulation on audio thread (AutoShape + GraphSwapper)
- **Typed Control IR**: `Control(label, value)` replaces OSC string convention
- **Continuous patterns**: `kr.sine()`, `kr.saw()`, `kr.rand()` — smooth control sweeps
- **Multi-pattern combinators**: `kr.cat()`, `kr.stack()`, `kr.struct()` — cycle-level composition
- **Pattern transforms**: `.mask()`, `.sometimes()` — selective silence and probabilistic variation
- **Transition blocks**: `with kr.transition(bars=N)` — all changes fade smoothly
- **Mini-notation**: `kr.p("x . x . x . . x")` for fast pattern entry
- **Scenes**: `kr.save("verse")` / `kr.recall("chorus")` — snapshot + restore
- **Music as code**: `kr.load("songs/verse.py")` — exec Python files as scenes
- **Master gain**: `kr.master = 0.7` — prevents CoreAudio clipping
- **Group operations**: `kr.mute("drums")` — prefix matching for `/`-grouped nodes
- **ADC input**: `kr.input("mic")` — live audio from CoreAudio input into the graph
- **MIDI CC mapping**: `kr.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)`
- **Pattern compiler**: Control-voice patterns compile to block-rate wavetables (172 updates/sec)
- **Phase-reset**: fades/mods start from beat 1 via `SetPatternFromZero`
- **Meter**: `kr.meter = 3` for waltz, 7 for 7/8
- **Pattern retrieval**: `kr.pattern("kick")` returns unbound pattern
- **Unified Voice model**: `Voice(count=N)` — no separate poly concept

## Next

### Stage 10: Template caching (priority: medium)

XLA-style compilation cache for the pattern compiler. Hash pattern structure
(excluding seeds/cycle), cache EventTemplates. Same pattern + different seed
= cache hit at template level. Only parameterization + fill run per cycle.

### Stage 11: Looper (priority: low)

Record live audio input into a buffer, play back as a pattern-triggered node.
`kr.record("loop1", bars=4)` → captures audio → `loop1.play(kr.hit() * 4)`.

### Stage 12: WASM Engine — full krach in the browser (priority: high)

Compile the actual Rust engine to WASM instead of reimplementing in JS.
Same code, different compile target. FAUST JIT in browser via libfaust-wasm.

```
CLI:  Python → socket → krach-engine (Rust native) → CoreAudio
Web:  Python (Pyodide) → wasm-bindgen → krach-engine (Rust WASM) → Web Audio
```

**Components:**
- `pattern-engine` → WASM (already works with --no-default-features)
- `audio-engine` → WASM (cpal has wasm-bindgen feature for Web Audio)
- `faust-dsl` → Pyodide (pure Python, already works)
- FAUST JIT → `@grame/libfaust` npm package (FAUST compiler in WASM,
  compiles .dsp → AudioWorklet at runtime in browser)
- Frontend: CodeMirror cells + Pyodide main thread

**No PyO3 needed.** Python (Pyodide) calls wasm-bindgen JS exports directly.
The WASM engine exposes the same command interface as the Unix socket protocol.

**Key research findings:**
- cpal: has `wasm-bindgen` + `audioworklet` features (WebAudio backend)
- libfaust-wasm: entire FAUST compiler in browser, runtime .dsp → WASM compilation
- rtrb: compiles to WASM (atomics for cross-thread AudioWorklet)
- FAUST WASM: ~3-10x slower than LLVM native (acceptable for live coding)
