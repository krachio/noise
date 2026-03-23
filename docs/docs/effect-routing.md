# Effect Routing

krach has two kinds of audio nodes: **voices** and **buses**. Understanding the
difference is essential for routing effects correctly.

## Voice vs Bus

| | `kr.voice()` | `kr.bus()` |
|---|---|---|
| **Purpose** | Sound source (synth, sampler) | Effect processor (reverb, delay, compressor) |
| **Audio input** | None -- generates audio | Yes -- receives audio from sends/wires |
| **Created with** | `kr.voice("name", dsp_fn)` | `kr.bus("name", dsp_fn)` |
| **Receives sends** | No | Yes |

!!! warning "Use `kr.bus()` for effects"
    Effects that receive audio from other voices **must** use `kr.bus()`.
    `kr.voice()` creates a sound source with no audio input -- sends will not
    work.

    ```python
    # CORRECT
    kr.bus("verb", reverb_fn, gain=0.3)

    # WRONG -- sends won't reach this node
    kr.voice("verb", reverb_fn, gain=0.3)
    ```

## `kr.send()` -- gain-controlled send

Route audio from a voice (or bus) to a bus with an adjustable level:

```python
kr.send("bass", "verb", level=0.4)
```

Update the send level at any time (no graph rebuild):

```python
kr.send("bass", "verb", level=0.7)
```

The voice's dry signal still goes to the master output. The send is a
parallel copy scaled by `level`.

## `kr.wire()` -- direct connection

Wire a voice directly to a specific bus input port. No gain stage -- the
signal passes through as-is:

```python
kr.wire("kick", "comp", port="in0")
kr.wire("snare", "comp", port="in1")
```

Use wires for multi-input effects like sidechain compressors or mixers where
you need explicit port assignment.

## Common setups

### Reverb send

The most common effect setup. Multiple voices share one reverb bus:

```python
@kr.dsp
def reverb_fx() -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    sig = krs.control("in0", 0.0, -1.0, 1.0)
    return krs.reverb(sig, room)

kr.bus("verb", reverb_fx, gain=0.3)

kr.send("bass", "verb", level=0.4)
kr.send("lead", "verb", level=0.6)
kr.send("pad", "verb", level=0.5)
```

### Parallel compression

Wire drums to a compressor bus:

```python
kr.bus("comp", compressor_fn, gain=0.5)
kr.wire("kick", "comp", port="in0")
kr.wire("snare", "comp", port="in1")
```

### Multi-input mixer bus

Route several voices to a submix:

```python
kr.bus("drums_bus", mixer_fn, gain=0.8)
kr.wire("kick", "drums_bus", port="in0")
kr.wire("snare", "drums_bus", port="in1")
kr.wire("hat", "drums_bus", port="in2")
```

## Voice handles for sends

Voice handles returned by `kr.voice()` and `kr.bus()` support sends directly:

```python
bass = kr.voice("bass", acid_bass, gain=0.3)
verb = kr.bus("verb", reverb_fx, gain=0.3)

bass.send(verb, 0.4)
```

## Group operations with `/` prefix

Voice names with `/` act as groups. Operations on the prefix affect all
matching voices:

```python
kr.voice("drums/kick", kick_fn, gain=0.8)
kr.voice("drums/hat", hat_fn, gain=0.6)
kr.voice("drums/snare", snare_fn, gain=0.7)

# Adjust gain for all drums at once
kr.gain("drums", 0.4)

# Mute/solo the group
kr.mute("drums")
kr.solo("drums")

# Hush all drum patterns
kr.hush("drums")
```

## `kr.gain()` -- works on both voices and buses

Set gain without rebuilding the audio graph:

```python
kr.gain("bass", 0.15)     # voice gain
kr.gain("verb", 0.5)      # bus gain
kr.gain("drums", 0.4)     # group gain
```

## Smooth fades

Use `kr.fade()` for gradual gain changes:

```python
kr.fade("bass/gain", target=0.0, bars=4)     # fade out over 4 bars
kr.fade("verb/gain", target=0.8, bars=8)     # fade in reverb
kr.fade("bass/cutoff", target=200.0, bars=4) # fade a control
```

## Removing buses

Remove a bus and clean up all its sends and wires:

```python
kr.remove_bus("verb")
```

Remove a voice:

```python
kr.remove("bass")
```

## Full routing example

```python
# Define synths
@kr.dsp
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

@kr.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

@kr.dsp
def reverb_fx() -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    sig = krs.control("in0", 0.0, -1.0, 1.0)
    return krs.reverb(sig, room)

# Set up voices and bus
with kr.batch():
    kr.voice("kick", kick, gain=0.8)
    kr.voice("bass", acid_bass, gain=0.3)

kr.bus("verb", reverb_fx, gain=0.3)
kr.send("bass", "verb", level=0.4)

# Play
kr.tempo = 128
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
```
