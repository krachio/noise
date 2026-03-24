# krach

Live coding audio system. Define synths in Python, sequence them with composable patterns, hear them instantly.

```python
# Define a synth — just a Python function
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

# Define an effect — takes audio input
def reverb(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room) * 0.8

# Create nodes, route, play
bass = kr.node("bass", acid_bass, gain=0.3)
verb = kr.node("verb", reverb, gain=0.3)
bass >> (verb, 0.4)                                # route with send level
bass @ kr.seq("A2", "D3", None, "E2").over(2)     # play pattern
bass @ ("cutoff", kr.sine(200, 2000).over(4))      # modulate control
```

## What it does

- **Design synths in Python** — write DSP functions, they compile to FAUST and JIT to native audio
- **Sequence with patterns** — TidalCycles-inspired composable patterns with rational time
- **Hear changes instantly** — hot reload, crossfade on graph swaps, no restart needed
- **Graph-first API** — everything is a node, `>>` routes signal, `@` plays patterns, `[]` sets controls
- **Two symbols**: `kr` (the audio graph) and `krs` (DSP primitives)

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

The REPL gives you two objects: `kr` (the audio graph) and `krs` (DSP module).

### Define a synth

```python
@kr.dsp
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9
```

### Create nodes and play patterns

```python
k = kr.node("kick", kick, gain=0.8)
k @ kr.hit() * 4                          # 4-on-the-floor
k @ (kr.hit() * 8).swing(0.67)            # swung 8ths
```

### Sequences, chords, modulation

```python
bass = kr.node("bass", acid_bass, gain=0.3)
bass @ kr.seq("A2", "D3", None, "E2").over(2)

# Modulate cutoff with a sine LFO
bass @ ("cutoff", kr.sine(200, 2000).over(4))

# Chords need poly nodes (count > 1)
pad = kr.node("pad", acid_bass, gain=0.2, count=4)
pad @ kr.note("A4", "C5", "E5") + kr.rest()
```

### Effect routing with `>>`

```python
verb = kr.node("verb", reverb, gain=0.3)   # auto-detected as effect
bass >> (verb, 0.4)                          # send at 40%
```

### Control access with `[]`

```python
bass["cutoff"] = 1200                  # set control
bass["cutoff"]                          # read control value
kr["bass"]                              # get node handle by name
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

# Transition: all changes inside fade over N bars
with kr.transition(bars=8):
    bass["gain"] = 0.8
    kr.tempo = 140
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
p.mask("1 1 0 1")  # suppress events by mask
p.sometimes(0.3, lambda p: p.reverse())  # probabilistic transform
kr.p("x . x . x . . x")  # mini-notation

# Multi-pattern combinators
kr.cat(a, b, c)             # play a, b, c one cycle each, loop
kr.stack(a, b)              # layer (same as a | b)
kr.struct(rhythm, melody)   # impose rhythm onto melody values

# Continuous patterns
kr.sine(200, 2000)          # sine sweep lo..hi
kr.saw(200, 2000)           # sawtooth ramp lo..hi
kr.rand(200, 2000)          # random values lo..hi
```

## Architecture

```
noise/
├── audio-engine/      Rust — graph runtime, node reuse, crossfade, FAUST auto-smoothing
├── audio-faust/       Rust — FAUST LLVM JIT, hot reload
├── pattern-engine/    Rust — pattern sequencer, rational time, curve compiler
├── krach-engine/      Rust — unified binary (one process, one socket)
├── faust-dsl/         Python — Python → FAUST transpiler
└── krach/             Python — live coding REPL, graph API, patterns
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
