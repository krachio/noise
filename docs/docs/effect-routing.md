# Effect Routing

krach routes audio between nodes using the `>>` operator. Every audio node --
sources and effects alike -- is created with `kr.node()`. The system auto-detects
whether a DSP is a source (0 audio inputs) or an effect (1+ audio inputs) from
the DSP definition.

## The `>>` operator

`>>` is the primary routing method. It connects one node's output to another
node's input:

```python
bass = kr.node("bass", acid_bass, gain=0.3)
verb = kr.node("verb", reverb_fn, gain=0.3)

bass >> verb                  # route at unity gain
bass >> (verb, 0.4)           # route with send level (40%)
```

Chains work naturally:

```python
mic = kr.input("mic")
filt = kr.node("filt", filter_fn, gain=1.0)
verb = kr.node("verb", reverb_fn, gain=0.3)

mic >> filt >> verb           # mic -> filter -> reverb
```

`>>` returns the target node, so chaining always reads left-to-right.

## `kr.node()` -- unified constructor

`kr.node()` auto-detects the node type from the DSP function's audio inputs:

```python
# Source (0 audio inputs) -- generates audio
bass = kr.node("bass", acid_bass, gain=0.3)

# Effect (1+ audio inputs) -- receives audio from sends/routes
verb = kr.node("verb", reverb_fn, gain=0.3)
```

No need to decide upfront. If the DSP has audio input controls, it becomes an
effect node automatically.

!!! note
    Sources have no audio input parameters. Effects take `inp: krs.Signal` as
    their first parameter — this is how `kr.node()` detects them automatically.

## `kr.connect()` -- explicit routing

The explicit API equivalent of `>>`:

```python
kr.connect("bass", "verb", level=0.4)      # gain-controlled send
kr.connect("kick", "comp", port="in0")     # direct wire to port
```

Use `kr.connect()` when building routing from strings (e.g., in loops or
abstractions). Use `>>` for interactive REPL work.

## Source vs effect auto-detection

| | Source (0 audio inputs) | Effect (1+ audio inputs) |
|---|---|---|
| **Purpose** | Sound source (synth, sampler) | Processor (reverb, delay, compressor) |
| **DSP signature** | `def synth() -> Signal` | `def fx(inp: Signal) -> Signal` |
| **Created with** | `kr.node()` (auto) | `kr.node()` (auto) |
| **Receives sends** | No | Yes |

## Send levels

The dry signal from a source always goes to master. A send is a parallel copy
scaled by the level:

```python
bass >> (verb, 0.4)           # 40% to reverb, dry still goes to master
```

Update the send level at any time (no graph rebuild):

```python
bass >> (verb, 0.7)           # change to 70%
# or explicitly:
kr.connect("bass", "verb", level=0.7)
```

## Direct wires (port assignment)

Wire a node directly to a specific input port. No gain stage -- the signal
passes through as-is:

```python
kr.connect("kick", "comp", port="in0")
kr.connect("snare", "comp", port="in1")
```

Use wires for multi-input effects like sidechain compressors or mixers where
you need explicit port assignment.

## Common setups

### Reverb send

Multiple sources share one reverb:

```python
@kr.dsp
def reverb_fx() -> krs.Signal:
    room = krs.control("room", 0.6, 0.0, 1.0)
    sig = krs.control("in0", 0.0, -1.0, 1.0)
    return krs.reverb(sig, room)

verb = kr.node("verb", reverb_fx, gain=0.3)

bass >> (verb, 0.4)
lead >> (verb, 0.6)
pad >> (verb, 0.5)
```

### Parallel compression

Wire drums to a compressor:

```python
comp = kr.node("comp", compressor_fn, gain=0.5)
kr.connect("kick", "comp", port="in0")
kr.connect("snare", "comp", port="in1")
```

### Effect chain

Route through multiple effects in series:

```python
filt = kr.node("filt", filter_fn, gain=1.0)
verb = kr.node("verb", reverb_fn, gain=0.3)

bass >> filt >> verb
```

### Multi-input mixer bus

Route several sources to a submix:

```python
drums = kr.node("drums_bus", mixer_fn, gain=0.8)
kr.connect("kick", "drums_bus", port="in0")
kr.connect("snare", "drums_bus", port="in1")
kr.connect("hat", "drums_bus", port="in2")
```

## Control access with `[]`

Set and read controls directly on node handles:

```python
verb["room"] = 0.8
verb["room"]              # returns 0.8
bass["cutoff"] = 1200
```

Or use the explicit API:

```python
kr.set("verb/room", 0.8)
```

## Group operations with `/` prefix

Node names with `/` act as groups. Operations on the prefix affect all
matching nodes:

```python
kr.node("drums/kick", kick_fn, gain=0.8)
kr.node("drums/hat", hat_fn, gain=0.6)
kr.node("drums/snare", snare_fn, gain=0.7)

# Adjust gain for all drums at once
kr.gain("drums", 0.4)

# Mute/solo the group
kr.mute("drums")
kr.solo("drums")

# Hush all drum patterns
kr.hush("drums")
```

## `kr.gain()` -- works on all nodes

Set gain without rebuilding the audio graph:

```python
kr.gain("bass", 0.15)     # source gain
kr.gain("verb", 0.5)      # effect gain
kr.gain("drums", 0.4)     # group gain
```

## Smooth fades

Use `kr.fade()` for gradual gain changes:

```python
kr.fade("bass/gain", target=0.0, bars=4)     # fade out over 4 bars
kr.fade("verb/gain", target=0.8, bars=8)     # fade in reverb
kr.fade("bass/cutoff", target=200.0, bars=4) # fade a control
```

## Removing nodes

Remove a node and clean up all its routes:

```python
kr.remove("bass")
kr.remove("verb")
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

# Set up nodes
with kr.batch():
    k = kr.node("kick", kick, gain=0.8)
    bass = kr.node("bass", acid_bass, gain=0.3)

verb = kr.node("verb", reverb_fx, gain=0.3)
bass >> (verb, 0.4)

# Play
kr.tempo = 128
k @ (kr.hit() * 4)
bass @ kr.seq("A2", "D3", None, "E2").over(2)
bass["cutoff"] = 1200
```
