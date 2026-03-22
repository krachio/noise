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
└── krach/             Python — live coding REPL (VoiceMixer, patterns, copilot, DSP design)
```

### Test counts
- audio-engine: 160 Rust tests
- audio-faust: 22 Rust tests
- pattern-engine: 141 Rust tests
- krach-engine: 25 Rust tests
- faust-dsl: 68 Python tests
- krach: 409 Python tests (includes patterns module, formerly midiman-frontend)
- **Total: 825 tests**, all green. Pyright strict clean.

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
- **Native automation lanes**: block-rate modulation on audio thread (AutoShape + GraphSwapper)
- **Typed Control IR**: `Control(label, value)` replaces OSC string convention
- **Mini-notation**: `p("x . x . x . . x")` for fast pattern entry
- **Scenes**: `mix.save("verse")` / `mix.recall("chorus")` — snapshot + restore
- **Music as code**: `mix.load("songs/verse.py")` — exec Python files as scenes
- **Master gain**: `mix.master = 0.7` — prevents CoreAudio clipping
- **Group operations**: `mix.mute("drums")` — prefix matching for `/`-grouped voices
- **ADC input**: `mix.input("mic")` — live audio from CoreAudio input into the graph
- **MIDI CC mapping**: `mix.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)`
- **Phase-reset**: fades/mods start from beat 1 via `SetPatternFromZero`
- **Meter**: `mix.meter = 3` for waltz, 7 for 7/8
- **Pattern retrieval**: `mix.pattern("kick")` returns unbound pattern
- **Unified Voice model**: `Voice(count=N)` — no separate poly concept
- **One user object**: `mix` handles everything (tempo, play, set, fade, mod, mute, solo)

## Next

- **Looper**: Record live input into buffer, play back as pattern-triggered voice
