# krach API reference

## Two namespaces

- `kr` — the audio graph: nodes, routing, patterns, transport
- `krs` — DSP primitives: oscillators, filters, envelopes, math

## Quick reference

```python
# Create nodes
kick = kr.node("kick", kick_fn, gain=0.8)
bass = kr.node("bass", bass_fn, gain=0.3)
verb = kr.node("verb", reverb_fn, gain=0.3)  # auto-detected as effect (has audio input)

# Route + play
bass >> verb                            # route signal
bass @ (kr.hit() * 4)                   # play pattern
bass @ "A2 D3 ~ E2"                    # mini-notation
bass["cutoff"] = 1200                   # set control
bass @ None                             # hush

# Transport
kr.tempo = 128
kr.stop()
```

---

## Creating nodes

```python
kr.node(name: str, source, gain: float = 0.5, count: int = 1, **init: float) -> NodeHandle
```

- `source`: Python function, DspDef, or string type_id (`"faust:kick"`)
- `count > 1`: poly node — round-robin voice allocation for chords
- `**init`: initial control values (e.g. `cutoff=800`)

```python
# Source node (0 audio inputs → generator)
kr.node("bass", bass_fn, gain=0.3)

# Effect node (1+ audio inputs → auto-detected from function signature)
kr.node("verb", reverb_fn, gain=0.3)

# Poly node for chords (count >= chord size)
kr.node("pad", pad_fn, gain=0.3, count=4)

# Batch setup (one graph rebuild instead of N)
with kr.batch():
    kr.node("kick", kick_fn, gain=0.8)
    kr.node("bass", bass_fn, gain=0.3)
```

## Routing

```python
kr.send(source: str, target: str, level: float = 0.5) -> None
kr.connect(source: str, target: str, level: float = 1.0) -> None
kr.wire(source: str, target: str, port: str = "in0") -> None
```

```python
kr.send("bass", "verb", level=0.4)     # gain-controlled send
bass >> verb                             # operator shorthand
bass >> (verb, 0.4)                      # with level
```

## Pattern builders

```python
kr.note(*pitches: str | int | float, vel: float = 1.0, **params: float) -> Pattern
kr.hit(param: str = "gate", **kwargs: float) -> Pattern
kr.seq(*notes: str | int | float | None, vel: float = 1.0) -> Pattern
kr.rest() -> Pattern          # silence (one beat of nothing)
kr.p(notation: str) -> Pattern  # mini-notation (see below)
```

**note()** — melodic trigger (sets freq + gate on/off):
```python
kr.note("C4")                           # string pitch
kr.note(440.0)                          # Hz
kr.note(60)                             # MIDI note number
kr.note("A4", "C5", "E5")              # chord (simultaneous — needs count >= 3)
kr.note("C4", cutoff=1200.0)           # extra control params per note
```

**seq()** — sequential notes (one at a time, NOT chords):
```python
kr.seq("A2", "D3", None, "E2")         # None = rest
kr.seq("C4", "E4", "G4")               # melody, not chord!
```

**hit()** — percussive trigger:
```python
kr.hit()                                # gate on/off
kr.hit("trig")                          # custom param
```

## Playing patterns

```python
kr.play(target: str, pattern: Pattern, *, from_zero: bool = False, swing: float | None = None) -> None
```

```python
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.play("kick", kr.hit() * 8, swing=0.67)

# Control modulation (lo/hi values must be in the control's declared range):
kr.play("bass/cutoff", kr.mod_sine(200.0, 2000.0).over(4))
```

## Pattern algebra

```python
a + b           # sequence: a then b
a | b           # layer: simultaneous
p * 4           # repeat
p.over(2)       # stretch to 2 cycles
p.swing(0.67)   # swing (0.5=straight, 0.67=standard)
p.spread(3, 8)  # euclidean
p.thin(0.3)     # randomly drop 30%
p.every(4, fn)  # apply fn every 4th cycle
```

## Controls

```python
kr.set(path: str, value: float) -> None
kr.gain(name: str, value: float) -> None
kr.fade(path: str, target: float, bars: int = 4) -> None
```

```python
kr.set("bass/cutoff", 1200.0)
kr.gain("bass", 0.3)
kr.fade("bass/cutoff", 200.0, bars=8)

# Transition: all changes fade over N bars
with kr.transition(bars=8):
    kr.gain("bass", 0.8)
    kr.tempo = 140
```

## Mod patterns

```python
kr.mod_sine(lo, hi)         # sine sweep between lo and hi
kr.mod_tri(lo, hi)          # triangle
kr.mod_ramp(lo, hi)         # linear ramp up
kr.mod_ramp_down(lo, hi)    # linear ramp down
kr.mod_square(lo, hi)       # square wave
kr.mod_exp(lo, hi)          # exponential
kr.ramp(start, end)         # one-shot ramp
```

All return Pattern — use `.over(N)` for timing, compose with `+`, `|`.

**lo/hi must be within the control's declared range** (e.g. cutoff [100, 6000]).
The API warns if values fall outside the range.

## Mute / solo / stop

```python
kr.mute("bass")
kr.unmute("bass")
kr.solo("bass")
kr.unsolo()
kr.hush("bass")          # silence one node
kr.stop()                # silence all
kr.remove("bass")        # delete node + routing
```

## Groups

Node names with `/` form groups:
```python
kr.node("drums/kick", kick_fn, gain=0.8)
kr.node("drums/hat", hat_fn, gain=0.6)
kr.gain("drums", 0.4)    # applies to all drums/*
kr.hush("drums")
```

## Effects

**Effects MUST have an audio input parameter.** This is how `kr.node()` detects them:

```python
# CORRECT
def reverb_fn(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room)

# WRONG — no audio input → detected as source, sends won't work
def reverb_fn() -> krs.Signal:
    sig = krs.control("in", 0.0, -1.0, 1.0)  # control slider, not audio!
    return krs.reverb(sig, 0.7)
```

## DSP functions (`krs`)

```python
def my_synth() -> krs.Signal:
    freq   = krs.control("freq", 220.0, 20.0, 2000.0)
    gate   = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.5
```

### krs primitives

| Function | Signature |
|---|---|
| `krs.control(name, init, lo, hi)` | Exposed parameter (hslider) |
| `krs.sine_osc(freq)` | Sine oscillator |
| `krs.saw(freq)` | Sawtooth oscillator |
| `krs.square(freq)` | Square oscillator |
| `krs.phasor(freq)` | 0→1 ramp at freq Hz |
| `krs.white_noise()` | White noise |
| `krs.lowpass(sig, cutoff)` | Butterworth lowpass |
| `krs.highpass(sig, cutoff)` | Butterworth highpass |
| `krs.bandpass(sig, cutoff, q)` | Bandpass filter |
| `krs.adsr(a, d, s, r, gate)` | ADSR envelope |
| `krs.reverb(sig, room)` | Freeverb (room 0.0–1.0) |
| `krs.delay(sig, n)` | Delay by n samples |
| `krs.mem(sig)` | One-sample delay |
| `krs.feedback(fn)` | Feedback loop |
| `krs.select2(cond, a, b)` | Conditional: b when cond>0, else a |
| `krs.pow_(sig, exp)` | Power |
| `krs.abs_(sig)` | Absolute value |
| `krs.sqrt(sig)` | Square root |
| `krs.min_(a, b)` / `krs.max_(a, b)` | Min/max |
| `krs.exp(sig)` / `krs.log(sig)` | Exp/log |
| `krs.sin(sig)` / `krs.cos(sig)` | Trig (radians) |
| `krs.fmod(a, b)` / `krs.remainder(a, b)` | Modulo variants |
| `krs.round_(sig)` / `krs.floor(sig)` / `krs.ceil(sig)` | Rounding |

### Signal arithmetic

```python
sig + 1.0       sig - 0.5       sig * gain
sig / 2.0       sig % 1.0       sig ** 2.0
2.0 ** sig      abs(sig)        -sig
sig > 0.0       sig < 1.0       sig >= 0.0
```

## Mini-notation

```python
kr.p("x . x . x . . x")     # x=hit(), .=rest()
kr.p("C4 E4 G4 ~ C5")       # note names, ~=rest
kr.p("[C4 E4] G4 B4")       # []=simultaneous
kr.p("C4*2 E4 G4")          # *N=repeat
```

---

## Warnings

The API warns on likely mistakes:

- **Value outside range**: `kr.set("bass/cutoff", 0.5)` when cutoff range is [100, 6000]
- **Pattern outside range**: `kr.play("bass/freq", mod_sine(0.5, 1.5))` when freq is [20, 2000]
- **Unknown control**: `kr.play("bass", note("C4", volume=1))` when bass has no "volume" control
- **High gain**: `kr.gain("bass", 5.0)` — warns above 2.0 (clipping risk)
- **Unknown node**: `kr["typo"] = 0.3` — warns that node doesn't exist

Faust clamps control values to their declared range. Warnings tell you what the engine will do.

---

## Common mistakes

**WRONG**: modulate freq with ratio values (sets freq to ~1 Hz → subsonic rumble):
```python
kr.play("bass/freq", kr.mod_sine(0.97, 1.03))   # ← 0.97 Hz!
```
**RIGHT**: use actual Hz values matching the control range:
```python
kr.play("bass/freq", kr.mod_sine(100.0, 400.0))  # ← Hz
```

**WRONG**: use seq() for chords (plays notes one at a time):
```python
kr.play("pad", kr.seq("A4", "C5", "E5"))  # ← melody, not chord
```
**RIGHT**: use note() with multiple pitches + poly count:
```python
kr.node("pad", pad_fn, count=4)
kr.play("pad", kr.note("A4", "C5", "E5"))  # ← chord
```

**WRONG**: effect without audio input parameter:
```python
def verb() -> krs.Signal:
    return krs.reverb(krs.control("in", 0, -1, 1), 0.7)  # "in" is a slider!
```
**RIGHT**: effect with `inp: krs.Signal` parameter:
```python
def verb(inp: krs.Signal) -> krs.Signal:
    return krs.reverb(inp, 0.7)
```

**WRONG**: `@` without parens (@ has higher precedence than `*` and `+`):
```python
kick @ kr.hit() * 4       # parses as (kick @ kr.hit()) * 4
```
**RIGHT**: parenthesize the pattern:
```python
kick @ (kr.hit() * 4)
```

---

## Full example

```python
def my_kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

def my_hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5

def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

with kr.batch():
    kr.node("kick", my_kick,   gain=0.8)
    kr.node("hat",  my_hat,    gain=0.5)
    kr.node("bass", acid_bass, gain=0.3)

kr.tempo = 128
kr.play("kick", kr.hit() * 4)
kr.play("hat",  (kr.hit() + kr.rest()) * 8)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
```
