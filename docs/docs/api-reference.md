# API Reference

Complete reference for the krach Python API. Two symbols: `kr` (the audio graph) and `krs` (DSP primitives).

## Mixer (`kr`)

The `Mixer` class manages the audio graph. In the REPL, `kr` is a `LiveMixer` instance (a thin wrapper that adds REPL sugar like `kr.note()`, `kr.seq()`, etc.).

### Transport

| Property / Method | Description |
|---|---|
| `kr.tempo = 128` | Set tempo in BPM |
| `kr.meter = 4` | Set beats per cycle (4 = 4/4 time) |
| `kr.master = 0.7` | Set master output gain |

### Node lifecycle

| Method | Description |
|---|---|
| `kr.node(name, source, gain=0.5, count=1, **init)` | Create or replace a node. Auto-detects source vs effect from DSP signature. Returns `NodeHandle` |
| `kr.voice(name, source, gain=0.5, count=1, **init)` | Add or replace a source node explicitly |
| `kr.bus(name, source, gain=0.5)` | Add or replace an effect node explicitly |
| `kr.remove(name)` | Remove a node or group and all its routing |
| `kr.input(name="mic", channel=0, gain=0.5)` | Add an audio input node (ADC) |
| `kr.dsp(fn)` | Pre-transpile a DSP function. Returns `DspDef` for reuse |

### Routing

| Method | Description |
|---|---|
| `kr.connect(source, target, level=1.0, port=None)` | Route audio. Use `level` for gain-controlled routing, `port` for direct port connections |
| `kr.unsend(source, target)` | Remove a routing connection between two nodes |
| `bass >> verb` | Operator shorthand for `kr.connect()` |
| `bass >> (verb, 0.4)` | Route with send level |

### Patterns

| Method | Description |
|---|---|
| `kr.play(target, pattern, from_zero=False, swing=None)` | Play a pattern on a node or control path |
| `kr.hush(name)` | Stop pattern, fade, and release gates |
| `kr.stop()` | Hush all nodes and release all gates |
| `bass @ pattern` | Operator shorthand for `kr.play()` |
| `bass @ ("cutoff", pattern)` | Play pattern on a specific control |
| `bass @ None` | Hush the node |

### Controls

| Method | Description |
|---|---|
| `kr.set(path, value)` | Set a control by path: `kr.set("bass/cutoff", 1200)` |
| `bass["cutoff"] = 1200` | Operator shorthand for `kr.set()` |
| `bass["cutoff"]` | Read current control value |

### Gain / Mute / Solo

| Method | Description |
|---|---|
| `kr.gain(name, value)` | Update gain (instant, no graph rebuild) |
| `kr.mute(name)` | Mute node or group (stores gain) |
| `kr.unmute(name)` | Unmute (restores gain) |
| `kr.solo(name)` | Solo a node or group (mutes all others) |
| `kr.unsolo()` | Unmute everything |

### Automation

| Method | Description |
|---|---|
| `kr.fade(path, target, bars=4)` | Fade any parameter over N bars |
| `kr.mod(path, shape_or_pattern, lo=0.0, hi=1.0, bars=1)` | Native engine automation. Shapes: `"sine"`, `"tri"`, `"ramp"`, `"square"` |

### Scenes

| Method | Description |
|---|---|
| `kr.save(name)` | Save current state as named scene |
| `kr.recall(name)` | Recall a saved scene |
| `kr.scenes` | List of saved scene names |

### Modules & persistence

| Method | Description |
|---|---|
| `kr.capture()` | Snapshot session as frozen `GraphIr` |
| `kr.load(ir)` | Replay a `GraphIr` onto the mixer (flattens sub_graphs) |
| `kr.instantiate(ir, prefix)` | Instantiate module with prefix namespace. Returns `GraphHandle` |
| `kr.trace()` | Return a `GraphProxy` that records calls |
| `kr.scene(name)` | Get a saved scene by name (returns `GraphIr`) |
| `@kr.graph` | Decorator: traces a function into a frozen `GraphIr` |
| `kr.export(path)` | Export session to reloadable Python file |
| `kr.exec_file(path)` | Load and execute a Python session file |

### State

| Property / Method | Description |
|---|---|
| `kr.nodes` | All nodes as `{name: NodeHandle}` |
| `kr.sources` | Source nodes only |
| `kr.effects` | Effect nodes only |
| `kr.routing` | Routing snapshot: `[(source, target, kind, level_or_port)]` |
| `kr.slots` | Session slot states |
| `kr.node_data` | All nodes as raw `Node` structs |
| `kr.node_controls` | Known node type controls |
| `kr.ctrl_values` | All set control values |
| `kr.pull()` | Sync local state from engine |
| `kr.get_node(name)` | Look up a `Node` by name |
| `kr.get_ctrl(node, param)` | Get last-set control value |
| `kr.is_muted(name)` | Check mute state |

### Indexing

| Operator | Description |
|---|---|
| `kr["bass"]` | Returns `NodeHandle` for the node |
| `kr["bass/cutoff"]` | Returns current control value |
| `kr["bass/cutoff"] = 1200` | Sets a control value |

### MIDI

| Method | Description |
|---|---|
| `kr.midi_map(cc, path, lo=0.0, hi=1.0, channel=0)` | Map a MIDI CC to a control path |

### Context managers

| Method | Description |
|---|---|
| `with kr.batch():` | Batch node declarations into one graph rebuild |
| `with kr.transition(bars=4):` | All gain/control changes become fades over N bars |

---

## NodeHandle

Returned by `kr.node()`. Wraps a named node with operator DSL.

### Operators

| Operator | Description |
|---|---|
| `bass >> verb` | Route to another node |
| `bass >> (verb, 0.4)` | Route with send level |
| `bass @ pattern` | Play a pattern |
| `bass @ ("cutoff", pattern)` | Play on a specific control |
| `bass @ None` | Hush |
| `bass["cutoff"]` | Get control value |
| `bass["cutoff"] = 1200` | Set control value |

### Methods

| Method | Description |
|---|---|
| `bass.play(pattern)` | Play a pattern |
| `bass.play("cutoff", pattern)` | Play on a control |
| `bass.pattern()` | Get last unbound pattern |
| `bass.set(param, value)` | Set a control |
| `bass.fade(param, target, bars=4)` | Fade a control |
| `bass >> (verb, 0.4)` | Route to a node with level (equivalent to `kr.connect`) |
| `bass.gain(value)` | Set gain |
| `bass.mute()` | Mute |
| `bass.unmute()` | Unmute |
| `bass.hush()` | Stop patterns |
| `bass.name` | Node name |

---

## GraphHandle

Returned by `kr.instantiate(ir, prefix)`. Wraps a prefixed module with operator DSL delegating to declared inputs/outputs.

### Properties

| Property | Description |
|---|---|
| `handle.prefix` | Module prefix string |
| `handle.nodes` | Dict of relative name → `NodeHandle` |
| `handle.input` | `NodeHandle` for first declared input |
| `handle.output` | `NodeHandle` for first declared output |
| `handle.inputs` | All declared input names (prefixed) |
| `handle.outputs` | All declared output names (prefixed) |

### Operators

| Operator | Description |
|---|---|
| `handle >> verb` | Route module output to target |
| `bass >> handle` | Route into module input |
| `handle @ pattern` | Play pattern on first input |
| `handle["node/param"]` | Get control value |
| `handle["node/param"] = 1200` | Set control value |

---

## `@kr.graph` decorator

Traces a function into a frozen `GraphIr`. First parameter is a `GraphProxy`:

```python
@kr.graph
def synth(m, freq=440):
    g.node("osc", osc_fn, gain=0.5)
    g.outputs("osc")

ir = synth(freq=220)  # → GraphIr
```

---

## Pattern

Composable pattern objects. Created via builders, combined with operators.

### Operators

| Operator | Description |
|---|---|
| `a + b` | Concatenate — play a then b |
| `a \| b` | Stack — play simultaneously |
| `p * 4` | Repeat 4 times |

### Transforms

| Method | Description |
|---|---|
| `.over(cycles)` | Stretch to N cycles |
| `.fast(factor)` | Speed up by factor |
| `.shift(offset)` | Time-shift |
| `.reverse()` | Reverse |
| `.swing(amount=0.67, grid=8)` | Swing feel |
| `.every(n, fn)` | Apply transform every N cycles |
| `.spread(pulses, steps, rotation=0)` | Euclidean rhythm |
| `.thin(prob, seed=0)` | Drop events by probability |
| `.mask(mask_str)` | Mask with `"x 0 x ."` notation |
| `.sometimes(prob, fn, seed=0)` | Probabilistic transform |

### Builders (REPL — on `kr`)

| Builder | Description |
|---|---|
| `kr.note(*pitches, vel=1.0, **params)` | Note trigger |
| `kr.hit(param="gate", **kwargs)` | Gate trigger |
| `kr.seq(*notes, vel=1.0, **params)` | Sequence of notes (`None` = rest) |
| `kr.rest()` | Silence |
| `kr.cat(*patterns)` | Concatenate: each plays for one cycle |
| `kr.stack(*patterns)` | Layer simultaneously |
| `kr.struct(rhythm, melody)` | Impose rhythm onto melody |
| `kr.p("x . x . x . . x")` | Mini-notation |

### Atom constructors (import from `krach.pattern`)

| Builder | Description |
|---|---|
| `midi_note(pitch, vel=100, channel=0, duration=1.0)` | Raw MIDI note atom |
| `cc(controller, value, channel=0)` | MIDI CC atom |
| `osc(address, *args)` | OSC message atom |
| `ctrl(label, value)` | Control value atom |
| `freeze(pat)` | Freeze a pattern (hold values across cycles) |

### Continuous patterns

| Builder | Description |
|---|---|
| `kr.sine(lo, hi)` | Sine sweep |
| `kr.saw(lo, hi)` | Sawtooth ramp |
| `kr.rand(lo, hi)` | Random values |
| `kr.ramp(start, end)` | Linear ramp |
| `kr.mod_sine(lo, hi)` | Sine modulation |
| `kr.mod_tri(lo, hi)` | Triangle modulation |
| `kr.mod_ramp(lo, hi)` | Ramp up modulation |
| `kr.mod_ramp_down(lo, hi)` | Ramp down modulation |
| `kr.mod_square(lo, hi)` | Square wave modulation |
| `kr.mod_exp(lo, hi)` | Exponential modulation |

---

## `krs` — DSP primitives

All DSP building blocks. `import krach.dsp as krs`.

### Core

| Function | Description |
|---|---|
| `krs.control(name, init, lo, hi, step=0.001)` | Exposed parameter — automatable from patterns |
| `krs.sr()` | Sample rate signal |
| `krs.sample_rate()` | Alias for `sr()` |
| `krs.delay(sig, n)` | Variable-length delay line |
| `krs.mem(sig)` | Single-sample delay (z^-1) |
| `krs.unit_delay(sig)` | Alias for `mem()` |
| `krs.feedback(body_fn)` | Feedback loop (Faust `~` operator) |
| `krs.select2(sel, when_zero, when_one)` | Two-way signal router |
| `krs.faust_expr(template, *inputs)` | Inline Faust expression escape hatch |

### Oscillators

| Function | Description |
|---|---|
| `krs.sine_osc(freq)` | Sine oscillator |
| `krs.saw(freq)` | Sawtooth oscillator (bipolar) |
| `krs.square(freq, duty=0.5)` | Square/pulse wave |
| `krs.phasor(freq)` | 0--1 ramp at `freq` Hz |

### Filters

| Function | Description |
|---|---|
| `krs.lowpass(sig, freq, order=2)` | Butterworth lowpass |
| `krs.highpass(sig, freq, order=2)` | Butterworth highpass |
| `krs.bandpass(sig, freq, q)` | Bandpass (resonant) |

### Noise

| Function | Description |
|---|---|
| `krs.white_noise()` | White noise generator |

### Envelopes

| Function | Description |
|---|---|
| `krs.adsr(a, d, s, r, gate)` | ADSR envelope generator |

### Effects

| Function | Description |
|---|---|
| `krs.reverb(sig, room=0.5, damping=0.5)` | Mono Freeverb |

### Math — unary

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

### Math — binary

| Function | Description |
|---|---|
| `krs.min_(a, b)` | Minimum |
| `krs.max_(a, b)` | Maximum |
| `krs.pow_(base, exp)` | Power |
| `krs.fmod(a, b)` | Floating-point modulo |
| `krs.remainder(a, b)` | IEEE remainder |
| `krs.atan2(y, x)` | Two-argument arctangent |

### Signal arithmetic

`krs.Signal` supports `+`, `-`, `*`, `/`, `//`, `%`, `**`, `-` (negation), and comparisons (`>`, `<`, `>=`, `<=`, `==`, `!=`) via operator overloads.
