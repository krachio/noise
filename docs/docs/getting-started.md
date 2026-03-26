# Getting Started

## 5-minute beat

Already installed? Start the REPL with `./bin/krach` and paste:

```python
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5

def bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

def reverb_fx(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room) * 0.8

# Build the graph
with kr.batch():
    k = kr.node("kick", kick, gain=0.8)
    h = kr.node("hat", hat, gain=0.5)
    b = kr.node("bass", bass, gain=0.3)

verb = kr.node("verb", reverb_fx, gain=0.3)
b >> (verb, 0.4)

# Play
kr.tempo = 128
k @ (kr.hit() * 4)
h @ ((kr.rest() + kr.hit()) * 4)
b @ kr.seq("A2", "D3", None, "E2").over(2)
b @ ("cutoff", kr.sine(200, 2000).over(4))
```

---

## Install

### Option A: pip (prebuilt wheel — macOS ARM64, macOS x86_64, Linux x86_64)

Requires **Python 3.13+** only:

```bash
pip install krach
```

### Option B: from source

Requires **Python 3.13+**, **Rust** stable ([rustup.rs](https://rustup.rs)), **[uv](https://docs.astral.sh/uv/)**, **FAUST** + **LLVM**:

```bash
brew install faust llvm
export LLVM_SYS_181_PREFIX=$(brew --prefix llvm)

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

**Controls** are named parameters that patterns drive automatically:

- `"gate"` — a trigger. 1.0 = note on, 0.0 = note off
- `"freq"` — pitch in Hz (set by `kr.note()` / `kr.seq()`)
- Custom controls (`"cutoff"`, `"room"`) — any parameter you want to automate
- The 4 numbers are: `name, default, min, max`

`krs.adsr(attack, decay, sustain, release, gate)` is an envelope — it shapes volume over time. All times are in seconds. Sustain is a level (0--1), not a time.

### 2. Create a node and play it

Pass Python DSP functions directly to `kr.node()` — transpilation to FAUST happens automatically:

```python
kr.node("kick", kick, gain=0.8)
kr.play("kick", kr.hit() * 4)
```

You should hear a four-on-the-floor kick. `kr.hit()` is a single gate trigger (1.0 = on, then 0.0 = off). `* 4` repeats it four times per cycle (one bar).

To stop: `kr.hush("kick")` stops the pattern, `kr.stop()` stops everything.

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

We shadow the function name with the node handle — the engine already compiled the DSP, so the original function is no longer needed.

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
    `kr.node()` auto-detects whether a DSP has audio inputs. Functions with an
    `inp: krs.Signal` parameter become effect nodes automatically.

### 8. Route the bass to reverb with `>>`

```python
bass >> (reverb, 0.4)    # send at 40% level
```

The `>>` operator routes signal between nodes. Use a tuple `(target, level)` for
gain-controlled routing, or just `bass >> reverb` for unity gain.

## Native automation with `kr.mod()`

For block-rate modulation on the audio thread (no per-event IPC):

```python
kr.mod("bass/cutoff", "sine", lo=200, hi=2000, bars=4)   # sine LFO
kr.mod("verb/room", "ramp", lo=0.2, hi=0.9, bars=8)      # linear ramp
kr.mod("hat/gain", "square", lo=0.0, hi=0.5, bars=2)     # on/off
```

Shapes: `"sine"`, `"tri"`, `"ramp"`, `"square"`. Runs entirely on the engine — zero Python overhead per cycle.

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

## Error recovery

| Symptom | Fix |
|---|---|
| No sound | Check `kr.master` (should be > 0), check node gain, check `kr.tempo` > 0 |
| `ConnectionError` on `kr.node()` | Engine not running — restart with `./bin/krach` |
| `"unknown node"` on `kr.play()` | Create the node first with `kr.node()` |
| `"unknown port"` on `kr.connect()` | Target is a source, not an effect — effects need `inp: krs.Signal` parameter |
| Clicks / zipper noise | Non-gate controls are auto-smoothed. If using `faust_expr`, apply `si.smoo` manually |
| Pattern sounds wrong | Check `.over(N)` — without it, the full sequence plays in one cycle |
| Engine crash | Check `~/.krach/engine.log`. Rebuild with `cargo build --release -p krach-engine` |

## Next steps

- [Synth Design](synth-design.md) — deep dive into DSP functions and `krs` primitives
- [Patterns](patterns.md) — pattern algebra, combinators, composition
- [Effect Routing](effect-routing.md) — node routing, `>>` operator
- [API Reference](api-reference.md) — complete API for `kr`, `krs`, patterns
