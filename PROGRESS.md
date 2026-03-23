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

# Two symbols: kr (mixer) and krs (dsp)
bass = kr.voice("bass", acid_bass, gain=0.3)
kick = kr.voice("drums/kick", kick_fn, gain=0.8)
verb = kr.bus("verb", reverb_fn, gain=0.3)

bass.play(kr.seq("A2", "D3", None, "E2").over(2))
kick.play(kr.hit() * 4)
bass.send(verb, 0.4)
bass.play("cutoff", kr.mod_sine(400, 2000).over(4))

kr.tempo = 128
kr.meter = 4
kr.fade("bass/gain", 0.0, bars=4)
kr.mute("drums")
```

## Key features

- **Two-symbol API**: `kr` (VoiceMixer) + `krs` (krach.dsp) — clean namespace for live coding
- **Voice-free patterns**: `kr.note("C4")`, `kr.hit()`, `kr.seq("A2", "D3")` — bind at play time
- **`/` path addressing**: `kr.set("bass/cutoff", 1200)`, `kr.fade("verb/room", 0.8, bars=8)`
- **Voice handles**: `bass = kr.voice(...)` returns proxy — `bass.play()`, `bass.set()`, `bass.mute()`
- **Effect routing**: `kr.bus()`, `kr.send()`, `kr.wire()` — shared reverb, sidechain, multi-input
- **Native automation lanes**: block-rate modulation on audio thread (AutoShape + GraphSwapper)
- **Typed Control IR**: `Control(label, value)` replaces OSC string convention
- **Mini-notation**: `kr.p("x . x . x . . x")` for fast pattern entry
- **Scenes**: `kr.save("verse")` / `kr.recall("chorus")` — snapshot + restore
- **Music as code**: `kr.load("songs/verse.py")` — exec Python files as scenes
- **Master gain**: `kr.master = 0.7` — prevents CoreAudio clipping
- **Group operations**: `kr.mute("drums")` — prefix matching for `/`-grouped voices
- **ADC input**: `kr.input("mic")` — live audio from CoreAudio input into the graph
- **MIDI CC mapping**: `kr.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)`
- **Pattern compiler**: Control-voice patterns compile to block-rate wavetables (172 updates/sec)
- **Phase-reset**: fades/mods start from beat 1 via `SetPatternFromZero`
- **Meter**: `kr.meter = 3` for waltz, 7 for 7/8
- **Pattern retrieval**: `kr.pattern("kick")` returns unbound pattern
- **Unified Voice model**: `Voice(count=N)` — no separate poly concept

## Next

- **Looper**: Record live input into buffer, play back as pattern-triggered voice
