# Getting Started

## Prerequisites

- **macOS** (CoreAudio — Linux/Windows support planned)
- **Rust** stable toolchain ([rustup.rs](https://rustup.rs))
- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **FAUST** compiler + LLVM development headers
    ```bash
    brew install faust llvm
    export LLVM_SYS_181_PREFIX=$(brew --prefix llvm)
    ```

## Install

```bash
git clone https://github.com/krachio/noise.git
cd noise

# Build the Rust engine (first build compiles FAUST bindings — takes ~2 min)
cargo build --release -p krach-engine

# Install the Python package
cd krach && uv sync && cd ..
```

## Start the REPL

```bash
./bin/krach
```

This starts the Rust audio engine in the background and opens an IPython REPL with two objects:

- `kr` — the audio graph (nodes, routing, patterns, transport)
- `krs` — DSP primitives (oscillators, filters, envelopes)

Engine logs go to `~/.krach/engine.log` — tail them in a second terminal for debugging:

```bash
tail -f ~/.krach/engine.log
```

## Your first sound

### 1. Define a kick drum

```python
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9
```

The `krs.control()` calls define parameters that patterns can drive.

### 2. Create a voice and play it

Pass Python DSP functions directly to `kr.node()` — transpilation to FAUST happens automatically:

```python
kr.node("kick", kick, gain=0.8)
kr.play("kick", kr.hit() * 4)
```

You should hear a four-on-the-floor kick. `kr.hit()` triggers the gate parameter. `* 4` repeats it four times per cycle.

### 3. Change the tempo

```python
kr.tempo = 140
```

The kick immediately speeds up. No restart, no rebuild.

## Your first sequence

### 4. Add a bass synth

```python
def bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

bass = kr.node("bass", bass, gain=0.3)
```

### 5. Play a bass line

```python
bass @ kr.seq("A2", "D3", None, "E2").over(2)
```

The `@` operator plays a pattern on a node. You can also use `kr.play("bass", pattern)` for the explicit form.

`kr.seq()` creates a sequence of notes. `None` is a rest. `.over(2)` stretches the pattern to 2 cycles (8 beats at meter=4).

### 6. Modulate the filter

```python
bass @ ("cutoff", kr.sine(200, 2000).over(4))
```

The `@` operator also accepts `(param, pattern)` tuples for control modulation.
The cutoff sweeps between 200 Hz and 2000 Hz over 4 cycles with a sine wave.

## Adding effects

### 7. Create a reverb and route the bass

```python
def verb(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    return krs.reverb(inp, room)

reverb = kr.node("verb", verb, gain=0.3)
```

!!! note
    `kr.node()` auto-detects whether a DSP has audio inputs. Effects (like reverb)
    are detected automatically -- effects are detected automatically from audio input parameters.

### 8. Route the bass to reverb with `>>`

```python
bass >> (reverb, 0.4)    # send at 40% level
```

The `>>` operator routes signal between nodes. Use a tuple `(target, level)` for
gain-controlled sends, or just `bass >> reverb` for unity gain.

## Live performance

```python
kr.mute("kick")          # silence the kick
kr.unmute("kick")         # bring it back
kr.fade("bass/gain", 0.0, bars=4)  # fade bass out over 4 bars
kr.solo("bass")           # mute everything except bass
kr.unsolo()               # unmute all
kr.hush("kick")           # stop kick pattern (node stays, can replay)
kr.stop()                 # stop all patterns
```

## Saving your work

```python
# Save to a reloadable Python file
kr.export("my_session.py")

# Later, in a new REPL session:
kr.load("my_session.py")
```

## Operator DSL cheat sheet

| Operator | Example | Meaning |
|---|---|---|
| `>>` | `bass >> verb` | Route signal |
| `>>` | `bass >> (verb, 0.4)` | Route with send level |
| `@` | `bass @ pattern` | Play pattern |
| `@` | `bass @ "A2 D3 ~ E2"` | Play mini-notation |
| `@` | `bass @ ("cutoff", pat)` | Modulate control |
| `@` | `bass @ None` | Hush |
| `[]` | `bass["cutoff"] = 1200` | Set control |
| `[]` | `bass["cutoff"]` | Get control value |

All operators have explicit equivalents: `kr.connect()`, `kr.play()`, `kr.set()`.

## Next steps

- [Synth Design](synth-design.md) — deep dive into DSP functions and `krs` primitives
- [Patterns](patterns.md) — pattern algebra, combinators, composition
- [Effect Routing](effect-routing.md) — node routing, `>>` operator, sends, wires
