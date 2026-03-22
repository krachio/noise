# Progress

## Current state

Live coding audio system — monorepo, Cargo workspace + Python (uv).

```
noise/
├── soundman-core/     Rust — audio engine (graph runtime, node reuse, crossfade, gain smoothing)
├── soundman-faust/    Rust — FAUST LLVM JIT plugin (hot reload, recursive dir watcher)
├── midiman/           Rust — pattern sequencer (min-heap, rational time, phase-reset, meter)
├── noise-engine/      Rust — unified binary (midiman + soundman + faust, one socket)
├── midiman-frontend/  Python — Pattern DSL + Graph IR + Session
├── faust-dsl/         Python — Python → Faust .dsp transpiler
└── krach/             Python — live coding REPL (VoiceMixer, copilot, DSP design)
```

### Test counts
- soundman-core: 122 Rust tests
- soundman-faust: 14 Rust tests
- midiman: 129 Rust tests
- noise-engine: 24 Rust tests
- midiman-frontend: 139 Python tests
- faust-dsl: 68 Python tests
- krach: 218 Python tests
- **Total: ~714 tests**, all green. Pyright strict clean.

## Usage

```bash
./bin/krach
```

```python
@dsp
def acid_bass() -> Signal:
    freq = control("freq", 55.0, 20.0, 800.0)
    gate = control("gate", 0.0, 0.0, 1.0)
    cutoff = control("cutoff", 800.0, 100.0, 4000.0)
    env = adsr(0.005, 0.15, 0.3, 0.08, gate)
    return lowpass(saw(freq), cutoff) * env * 0.55

# Voice handles — zero name repetition
bass = mix.voice("bass", acid_bass, gain=0.3)
kick = mix.voice("drums/kick", kick_fn, gain=0.8)
verb = mix.bus("verb", reverb_fn, gain=0.3)

bass.play(seq("A2", "D3", None, "E2").over(2))
kick.play(hit() * 4)
bass.send(verb, 0.4)
bass.play("cutoff", mod_sine(400, 2000).over(4))

mix.tempo = 128
mix.meter = 4
mix.fade("bass/gain", 0.0, bars=4)
mix.mute("drums")
```

## Key features

- **Voice-free patterns**: `note("C4")`, `hit()`, `seq("A2", "D3")` — bind to voice at play time
- **`/` path addressing**: `mix.set("bass/cutoff", 1200)`, `mix.fade("verb/room", 0.8, bars=8)`
- **Voice handles**: `bass = mix.voice(...)` returns proxy — `bass.play()`, `bass.set()`, `bass.mute()`
- **Effect routing**: `mix.bus()`, `mix.send()`, `mix.wire()` — shared reverb, sidechain, multi-input
- **Modulation as patterns**: `mod_sine(lo, hi).over(bars)` — compose with pattern algebra
- **Group operations**: `mix.mute("drums")` — prefix matching for `/`-grouped voices
- **Phase-reset**: fades/mods start from beat 1 via `SetPatternFromZero`
- **Meter**: `mix.meter = 3` for waltz, 7 for 7/8
- **Pattern retrieval**: `mix.pattern("kick")` returns unbound pattern for modification
- **Unified Voice model**: `Voice(count=N)` — no separate poly concept
- **One user object**: `mix` handles everything (tempo, play, set, fade, mod, mute, solo)

## Next

- **Pattern JIT**: Compile pattern IR to native automation nodes on audio thread. Same model as `@dsp` → FAUST. Zero IPC for steady-state modulation.
- **Scenes**: `mix.save("verse")` / `mix.recall("chorus", bars=4)` — snapshot + crossfade
- **Music as Python repos**: Songs as importable modules, git-versioned
- **Live audio input**: `mix.input(channel=0)` — mic/instruments in the graph
- **Mini-notation**: `p("x . x . x . . x")` shorthand
- **Library restructure**: Merge midiman-frontend into krach, rename Rust crates
