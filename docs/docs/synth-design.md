# Synth Design

krach lets you define synthesizers as plain Python functions. Pass them to
`kr.node()` and transpilation to FAUST + LLVM JIT compilation happens
automatically. You write Python, you hear audio -- no manual compilation step.

## Defining a DSP function

The pipeline: **Python function --> FAUST .dsp --> LLVM JIT --> audio node**.

```python
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

kr.node("bass", acid_bass, gain=0.3)
```

`kr.node()` takes care of everything: it transpiles the Python function to
FAUST, compiles it via LLVM, and registers the audio node. The generated FAUST
code (`.dsp`) is saved to `~/.krach/dsp/`.

## `krs` primitives reference

All DSP building blocks live in the `krs` namespace (`krach.dsp`).

### Controls

| Function | Description |
|---|---|
| `krs.control(name, init, lo, hi)` | Exposed parameter (automatable from patterns) |

### Oscillators

| Function | Description |
|---|---|
| `krs.sine_osc(freq)` | Sine oscillator |
| `krs.saw(freq)` | Sawtooth oscillator (bipolar) |
| `krs.square(freq, duty=0.5)` | Square/pulse wave |
| `krs.phasor(freq)` | 0--1 ramp at `freq` Hz |

### Noise

| Function | Description |
|---|---|
| `krs.white_noise()` | White noise generator |

### Filters

| Function | Description |
|---|---|
| `krs.lowpass(sig, freq, order=2)` | Butterworth lowpass |
| `krs.highpass(sig, freq, order=2)` | Butterworth highpass |
| `krs.bandpass(sig, freq, q)` | Bandpass (resonant) |

### Envelopes

| Function | Description |
|---|---|
| `krs.adsr(a, d, s, r, gate)` | ADSR envelope generator |

### Effects

| Function | Description |
|---|---|
| `krs.reverb(sig, room, damping)` | Mono Freeverb |

### DSP primitives

| Function | Description |
|---|---|
| `krs.sr()` | Sample rate signal |
| `krs.sample_rate()` | Alias for `sr()` |
| `krs.delay(sig, n)` | Variable-length delay line |
| `krs.mem(sig)` | Single-sample delay (z^-1) |
| `krs.unit_delay(sig)` | Alias for `mem()` |
| `krs.feedback(body_fn)` | Feedback loop (Faust `~` operator) |
| `krs.select2(sel, when_zero, when_one)` | Two-way signal router |
| `krs.faust_expr(template, *inputs)` | Inline Faust expression escape hatch |

### Math -- unary

| Function | Description |
|---|---|
| `krs.sin(sig)` | Sine |
| `krs.cos(sig)` | Cosine |
| `krs.tan(sig)` | Tangent |
| `krs.asin(sig)` | Inverse sine |
| `krs.acos(sig)` | Inverse cosine |
| `krs.atan(sig)` | Inverse tangent |
| `krs.exp(sig)` | Exponential |
| `krs.log(sig)` | Natural logarithm |
| `krs.log10(sig)` | Base-10 logarithm |
| `krs.sqrt(sig)` | Square root |
| `krs.abs_(sig)` | Absolute value |
| `krs.floor(sig)` | Floor |
| `krs.ceil(sig)` | Ceiling |
| `krs.round_(sig)` | Round |

### Math -- binary

| Function | Description |
|---|---|
| `krs.min_(a, b)` | Minimum |
| `krs.max_(a, b)` | Maximum |
| `krs.pow_(base, exp)` | Power |
| `krs.fmod(a, b)` | Floating-point modulo |
| `krs.remainder(a, b)` | IEEE remainder |
| `krs.atan2(y, x)` | Two-argument arctangent |

## Controls: `krs.control(name, init, lo, hi)`

Controls are the bridge between patterns and audio. Each control becomes an
automatable parameter on the node.

```python
freq = krs.control("freq", 55.0, 20.0, 800.0)
#                   name   init   lo     hi
```

- **name** -- label used in pattern binding (`bass/freq`)
- **init** -- default value
- **lo / hi** -- valid range (used by MIDI mapping and modulation)

Two controls are conventional for melodic synths:

- `"freq"` -- pitch in Hz (set by `kr.note()`)
- `"gate"` -- trigger (set by `kr.note()` and `kr.hit()`)

You can add any number of custom controls:

```python
cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
resonance = krs.control("res", 0.5, 0.0, 1.0)
drive = krs.control("drive", 0.0, 0.0, 1.0)
```

## Signal arithmetic

`krs.Signal` supports standard arithmetic. Use `*`, `+`, and `-` to combine
signals and scalars:

```python
# Scale an oscillator by an envelope
krs.saw(freq) * env

# Mix two oscillators
krs.saw(freq) + krs.square(freq) * 0.3

# Offset a control (filter envelope modulation)
cutoff + filt_env * 1200.0

# Invert a signal
-env + 1.0
```

These operations translate directly to FAUST arithmetic in the generated code.

## Effects (audio processors)

Effects that receive audio from other nodes — reverb, delay, compressors —
must take an audio input **parameter**. `kr.node()` auto-detects them:

```python
def simple_reverb(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    return krs.reverb(inp, room)

kr.node("verb", simple_reverb, gain=0.3)  # auto-detected as effect
kr.connect("bass", "verb", level=0.4)
```

!!! warning "Do NOT use `krs.control('in', ...)` for audio input"
    Using a control slider for audio input creates a 0-input generator,
    not an effect. Sends will fail with "unknown port 'in'". Always use
    a function parameter: `def fx(inp: krs.Signal) -> krs.Signal`.

See [Effect Routing](effect-routing.md) for the full send/wire system.

## Hot reload

Just redefine the function and call `kr.node()` again:

1. `kr.node()` re-transpiles the Python function to FAUST
2. LLVM recompiles the DSP to native code
3. The audio graph hot-swaps the node with a crossfade

No restart needed:

```python
# Change the synth -- hear the difference immediately
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    filt_env = krs.adsr(0.005, 0.2, 0.2, 0.1, gate)
    # Added filter envelope modulation
    return krs.lowpass(krs.saw(freq), cutoff + filt_env * 1200.0) * env * 0.55

kr.node("bass", acid_bass, gain=0.3)  # hot-swaps, patterns keep playing
```

## Example synths

### Acid bass

A classic 303-style bass with filter envelope:

```python
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    filt_env = krs.adsr(0.005, 0.2, 0.2, 0.1, gate)
    return krs.lowpass(krs.saw(freq), cutoff + filt_env * 1200.0) * env * 0.55
```

### Kick drum

Sine wave with pitch envelope for the characteristic thump:

```python
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9
```

### Hi-hat

Filtered white noise with a sharp envelope:

```python
def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5
```

### Pad

A detuned saw pair with slow attack for ambient textures:

```python
def pad() -> krs.Signal:
    freq = krs.control("freq", 220.0, 20.0, 2000.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 2000.0, 200.0, 8000.0)
    env = krs.adsr(0.3, 0.5, 0.7, 0.8, gate)
    osc = krs.saw(freq) + krs.saw(freq * 1.005) * 0.8
    return krs.lowpass(osc, cutoff) * env * 0.3
```

### Simple reverb

An effect using Freeverb (note the `inp` audio input parameter):

```python
def simple_reverb(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    return krs.reverb(inp, room)
```

## Pre-transpiling with `kr.dsp()`

By default, `kr.node()` transpiles on every call. If you're iterating on
routing but not changing the DSP function, you can pre-transpile once with
`kr.dsp()` to skip redundant work:

```python
acid_bass_dsp = kr.dsp(acid_bass)       # transpile once
kr.node("bass", acid_bass_dsp, gain=0.3)  # reuse the DspDef
kr.node("bass", acid_bass_dsp, gain=0.5)  # no re-transpile
```

This is purely an optimization -- the result is identical.

## Putting it together

```python
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

with kr.batch():
    kr.node("kick", kick, gain=0.8)
    kr.node("bass", acid_bass, gain=0.3)

kr.tempo = 128
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.play("bass/cutoff", kr.mod_sine(200, 2000).over(4))
```
