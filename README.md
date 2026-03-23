# krach

Live coding audio system. Define synths in Python, sequence them with composable patterns, hear them instantly.

```python
import krach.dsp as krs

@kr.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

kr.voice("bass", acid_bass, gain=0.3)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.play("bass/cutoff", kr.mod_sine(200, 2000).over(4))
```

## What it does

- **Design synths in Python** — write DSP functions, they compile to FAUST and JIT to native audio
- **Sequence with patterns** — TidalCycles-inspired composable patterns with rational time
- **Hear changes instantly** — hot reload, crossfade on graph swaps, no restart needed
- **Two symbols**: `kr` (the mixer) and `krs` (DSP primitives)

## Install

Requires: macOS (CoreAudio), Rust toolchain, Python 3.13+, [uv](https://docs.astral.sh/uv/), FAUST + LLVM.

```bash
git clone https://github.com/krachio/noise.git
cd noise

# Build the Rust engine
cargo build --release -p krach-engine

# Install the Python package
cd krach && uv sync && cd ..

# Start the REPL
./bin/krach
```

## Quick start

The REPL gives you two objects: `kr` (VoiceMixer) and `krs` (DSP module).

### Define a synth

```python
@kr.dsp
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9
```

### Add voices and play patterns

```python
kr.voice("kick", kick, gain=0.8)
kr.play("kick", kr.hit() * 4)           # 4-on-the-floor
kr.play("kick", (kr.hit() * 8).swing(0.67))  # swung 8ths
```

### Sequences, chords, modulation

```python
kr.voice("bass", acid_bass, gain=0.3)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))

# Modulate cutoff with a sine LFO
kr.play("bass/cutoff", kr.mod_sine(200, 2000).over(4))

# Chords need poly voices (count > 1)
kr.voice("pad", pad_fn, gain=0.2, count=4)
kr.play("pad", kr.note("A4", "C5", "E5") + kr.rest())
```

### Effect routing

```python
kr.bus("verb", reverb_fn, gain=0.3)
kr.send("bass", "verb", level=0.4)
```

### Transport and control

```python
kr.tempo = 128
kr.master = 0.7
kr.fade("bass/gain", 0.0, bars=4)
kr.mute("bass")
kr.save("verse")
kr.recall("verse")
kr.export("my_session.py")  # save to file
kr.load("my_session.py")    # reload later
```

## Pattern algebra

```python
a + b           # sequence (equal time share)
a | b           # layer (simultaneous)
p * 4           # repeat 4 times
p.over(2)       # stretch to 2 cycles
p.fast(2)       # double speed
p.reverse()     # reverse
p.every(4, lambda p: p.reverse())  # transform every 4th cycle
p.spread(3, 8)  # euclidean rhythm
p.thin(0.3)     # randomly drop 30%
p.swing(0.67)   # swing feel
kr.p("x . x . x . . x")  # mini-notation
```

## Architecture

```
noise/
├── audio-engine/      Rust — graph runtime, node reuse, crossfade, automation
├── audio-faust/       Rust — FAUST LLVM JIT, hot reload
├── pattern-engine/    Rust — pattern sequencer, rational time, curve compiler
├── krach-engine/      Rust — unified binary (one process, one socket)
├── faust-dsl/         Python — Python → FAUST transpiler
└── krach/             Python — live coding REPL, VoiceMixer, patterns
```

Single process architecture. Python sends pattern IR over a Unix socket. The Rust engine compiles patterns to block-rate automation curves — no per-event IPC during playback. FAUST DSPs hot-reload from `~/.krach/dsp/`.

## DSP primitives (`krs`)

| Function | Description |
|---|---|
| `krs.sine_osc(freq)` | Sine oscillator |
| `krs.saw(freq)` | Sawtooth |
| `krs.square(freq)` | Square wave |
| `krs.white_noise()` | White noise |
| `krs.lowpass(sig, cutoff)` | Butterworth lowpass |
| `krs.highpass(sig, cutoff)` | Butterworth highpass |
| `krs.bandpass(sig, cutoff, q)` | Bandpass |
| `krs.adsr(a, d, s, r, gate)` | ADSR envelope |
| `krs.reverb(sig, room)` | Freeverb |
| `krs.control(name, init, lo, hi)` | Exposed parameter |

## Development

```bash
cargo test --workspace                    # Rust tests
cd krach && uv run pyright && uv run pytest  # Python tests
cd faust-dsl && uv run pytest             # Transpiler tests
```

## License

MIT
