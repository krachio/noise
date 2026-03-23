# Patterns

Patterns are the sequencing system in krach. They describe *what* happens and
*when*, using composable IR trees with rational time. Patterns are independent
of voices -- you build a pattern, then bind it to a voice with `kr.play()`.

## What is a pattern?

A pattern is a tree of events distributed over a **cycle** (one bar by
default). The tree is pure data -- an intermediate representation that the
Rust engine compiles to block-rate automation curves. No per-event IPC happens
during playback.

Patterns are:

- **Composable** -- combine with `+`, `|`, `*`, and transforms
- **Rational time** -- subdivisions are exact, no floating-point drift
- **Reusable** -- the same pattern can play on different voices

## Atoms

Atoms are the smallest pattern elements. All pattern builders live on the `kr`
namespace.

### `kr.note()` -- melodic trigger

Sets `freq` and fires `gate` (trigger + reset). Accepts multiple pitch formats:

```python
kr.note(440.0)                          # float Hz
kr.note("C4")                           # string pitch name
kr.note(60)                             # int MIDI note number (converted via mtof)
kr.note(440.0, vel=0.7, cutoff=1200.0)  # extra params set alongside freq/gate
```

#### Note syntax details

**Float** -- interpreted as Hz directly:

```python
kr.note(440.0)   # A4
kr.note(55.0)    # A1
```

**String** -- pitch name with octave. Sharps use `s` or `#`:

```python
kr.note("C4")    # middle C
kr.note("Cs4")   # C sharp 4
kr.note("C#4")   # also C sharp 4
kr.note("Bb3")   # B flat 3
```

**Integer** -- MIDI note number, converted to Hz internally:

```python
kr.note(60)      # middle C (261.63 Hz)
kr.note(69)      # A4 (440 Hz)
```

#### Chords (multiple simultaneous pitches)

Pass multiple pitches to `kr.note()` for a chord:

```python
kr.note("A4", "C5", "E5")           # A minor triad
kr.note(220.0, 330.0, 440.0)        # same as Hz
```

Or use the `|` (layer) operator:

```python
kr.note("A4") | kr.note("C5") | kr.note("E5")
```

!!! warning "Chords require polyphony"
    The voice **must** have `count` >= the number of simultaneous pitches:

    ```python
    kr.voice("rhodes", rhodes_fn, gain=0.3, count=4)  # poly voice
    kr.play("rhodes", kr.note("A4", "C5", "E5") + kr.rest())
    ```

### `kr.hit()` -- percussive trigger

Fires a gate trigger without setting pitch. Use for drums and one-shot sounds:

```python
kr.hit()           # triggers "gate" control
kr.hit("kick")     # triggers a custom-named control
```

### `kr.rest()` -- silence

A single beat of silence:

```python
kr.rest()
```

### `kr.seq()` -- sequential notes

Plays notes **one at a time**, in sequence. Use `None` for rests:

```python
kr.seq(55.0, 73.0, None, 65.0)     # Hz values, with a rest
kr.seq("C4", "E4", "G4")           # pitch names
kr.seq("A2", "D3", None, "E2")     # bass line with rest
```

`kr.seq()` also accepts `kr.note()` objects, letting you set per-note params:

```python
kr.seq(
    kr.note(220.0, cutoff=800.0),
    kr.note(330.0, cutoff=1200.0),
    None,
    kr.note(440.0)
)

# Mix pitch strings and note objects freely:
kr.seq("A2", "D3", kr.note("E2", vel=0.5), None)
```

!!! warning "`kr.seq()` is NOT for chords"
    `kr.seq("A4", "C5", "E5")` plays three notes **one after another** -- it
    is a melody, not a chord. For chords, use `kr.note("A4", "C5", "E5")`.

## Operators

### `+` -- sequence

Concatenates patterns in time, dividing the cycle equally:

```python
kr.note("C4") + kr.note("E4") + kr.note("G4")  # 3 notes, each 1/3 cycle
```

### `|` -- layer (simultaneous)

Stacks patterns to play at the same time:

```python
kr.note("A4") | kr.note("C5") | kr.note("E5")  # chord
```

### `*` -- repeat

Repeats a pattern N times within one cycle:

```python
kr.hit() * 4           # 4-on-the-floor
kr.hit() * 8           # 8th notes
(kr.hit() + kr.rest()) * 4  # offbeat pattern, repeated 4x
```

## Time transforms

### `.over(n)` -- stretch to N cycles

Stretches a pattern to span multiple bars:

```python
kr.seq("A2", "D3", None, "E2").over(2)   # 4 notes over 2 bars
kr.ramp(200.0, 2000.0).over(4)           # 4-bar ramp
```

### `.fast(n)` -- speed up

Doubles (or triples, etc.) the playback speed:

```python
p = kr.hit() * 4
kr.play("kick", p.fast(2))   # 8 hits per cycle
```

### `.slow(n)` -- slow down

The inverse of `.fast()`:

```python
p.slow(2)   # half speed, pattern spans 2 cycles
```

## Combinators

### `.every(n, fn)` -- periodic transform

Apply a transform every Nth cycle:

```python
p = kr.hit() * 4
p.every(4, lambda p: p.reverse())    # reverse every 4th bar
p.every(3, lambda p: p.fast(2))      # double time every 3rd bar
```

### `.reverse()` -- reverse

Plays the pattern backwards:

```python
kr.seq("A2", "D3", "E3", "G3").reverse()
```

### `.spread(hits, steps)` -- euclidean rhythm

Distributes `hits` evenly across `steps` slots:

```python
kr.hit().spread(3, 8)    # 3 hits in 8 steps (tresillo)
kr.hit().spread(5, 8)    # 5 hits in 8 steps (cinquillo)
kr.hit().spread(7, 16)   # 7 hits in 16 steps
```

### `.thin(probability)` -- degrade

Randomly drops events with the given probability:

```python
kr.hit() * 8
(kr.hit() * 8).thin(0.3)   # randomly drop 30% of hits
```

## Modulation patterns

Modulation patterns generate continuous control values instead of note
triggers. All return `Pattern` objects and compose like any other pattern.

```python
kr.mod_sine(lo, hi)         # sine LFO between lo and hi
kr.mod_tri(lo, hi)          # triangle LFO
kr.mod_ramp(lo, hi)         # ramp up (sawtooth)
kr.mod_ramp_down(lo, hi)    # ramp down
kr.mod_square(lo, hi)       # square LFO
kr.mod_exp(lo, hi)          # exponential curve
kr.ramp(start, end)         # one-shot linear ramp
```

All accept an optional `steps=64` parameter to control resolution.

### Using modulation patterns

Play them on a control path:

```python
# Sine LFO on bass cutoff over 4 bars
kr.play("bass/cutoff", kr.mod_sine(200.0, 2000.0).over(4))

# Triangle LFO on gain
kr.play("bass/gain", kr.mod_tri(0.1, 0.5).over(8))

# One-shot ramp
kr.play("bass/cutoff", kr.ramp(200.0, 2000.0).over(4))
```

Or use the `kr.mod()` shorthand:

```python
kr.mod("bass/cutoff", kr.mod_sine(200.0, 2000.0), bars=4)
kr.mod("bass/gain", kr.mod_tri(0.1, 0.5), bars=8)
```

Stop a modulation with `kr.hush()`:

```python
kr.hush("bass/cutoff")
```

## Playing patterns

### `kr.play(target, pattern)`

Binds a pattern to a voice or control path. The pattern starts on the next
cycle boundary:

```python
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.play("bass/cutoff", kr.ramp(200.0, 2000.0).over(4))
```

### Voice handles

`kr.voice()` returns a handle that eliminates name repetition:

```python
bass = kr.voice("bass", acid_bass, gain=0.3)

bass.play(kr.seq("A2", "D3", None, "E2").over(2))
bass.set("cutoff", 1200)
bass.fade("cutoff", 200, bars=4)
bass.play("cutoff", kr.mod_sine(400, 2000).over(4))
bass.mute()
```

### Convenience kwargs

`kr.play()` accepts `swing=` as a keyword argument:

```python
kr.play("kick", kr.hit() * 8, swing=0.67)
```

## Pattern retrieval

Get the current pattern from a voice to modify and replay:

```python
p = kr.pattern("kick")            # get current pattern by name
kr.play("kick", p.fast(2))       # modify and replay

# Or via a voice handle:
kick = kr.voice("drums/kick", kick_fn, gain=0.8)
p = kick.pattern()
kick.play(p.every(4, lambda p: p.reverse()))
```

## How binding works

Pattern atoms like `kr.note()` and `kr.hit()` produce **bare parameter
names** (e.g., `freq`, `gate`). When you call `kr.play("bass", pattern)`, the
system binds those bare names to the voice's control namespace:

- `freq` becomes `bass/freq`
- `gate` becomes `bass/gate`
- `cutoff` becomes `bass/cutoff`

This means the same pattern can be reused on different voices:

```python
melody = kr.seq("A2", "D3", None, "E2").over(2)
kr.play("bass", melody)
kr.play("lead", melody)   # same pattern, different voice
```

## Common recipes

### 4-on-the-floor kick

```python
kr.play("kick", kr.hit() * 4)
```

### Offbeat hi-hat

```python
kr.play("hat", (kr.rest() + kr.hit()) * 4)
```

### Bass line with rests

```python
kr.play("bass", kr.seq("A2", "C3", "D3", "E3").over(2))
```

### Chord stabs

```python
kr.voice("rhodes", rhodes_fn, gain=0.3, count=4)
kr.play("rhodes", kr.note("A4", "C5", "E5") + kr.rest())
```

### Euclidean hi-hat with degradation

```python
kr.play("hat", kr.hit().spread(5, 8).thin(0.2))
```

### Evolving pattern

```python
p = kr.hit() * 4
kr.play("kick", p.every(4, lambda p: p.fast(2)))
```
