# MIDI and Hardware

krach connects to external MIDI controllers and audio hardware for hands-on
control of your live coding session.

## MIDI CC mapping

Map a MIDI continuous controller to any voice or bus parameter:

```python
kr.midi_map(cc=74, path="bass/cutoff", lo=200.0, hi=4000.0)
```

The CC value (0--127) is scaled linearly to the `lo`--`hi` range and applied
to the parameter in real time.

### Parameters

| Parameter | Description |
|---|---|
| `cc` | MIDI CC number (0--127) |
| `path` | Control path, e.g. `"bass/cutoff"`, `"verb/room"` |
| `lo` | Value when CC is 0 |
| `hi` | Value when CC is 127 |
| `channel` | MIDI channel (optional, defaults to all channels) |

### Examples

```python
# Knob 74 controls bass filter cutoff
kr.midi_map(cc=74, path="bass/cutoff", lo=200.0, hi=4000.0)

# Knob 1 (mod wheel) controls bass gain, channel 5 only
kr.midi_map(cc=1, path="bass/gain", lo=0.0, hi=1.0, channel=5)

# Map reverb room size to a fader
kr.midi_map(cc=7, path="verb/room", lo=0.0, hi=1.0)

# Master volume on a fader
kr.midi_map(cc=7, path="master", lo=0.0, hi=1.0, channel=1)
```

### Typical controller mappings

A practical starting point for an 8-knob MIDI controller:

```python
kr.midi_map(cc=70, path="kick/gain", lo=0.0, hi=1.0)
kr.midi_map(cc=71, path="hat/gain", lo=0.0, hi=1.0)
kr.midi_map(cc=72, path="bass/gain", lo=0.0, hi=1.0)
kr.midi_map(cc=73, path="lead/gain", lo=0.0, hi=1.0)
kr.midi_map(cc=74, path="bass/cutoff", lo=200.0, hi=4000.0)
kr.midi_map(cc=75, path="lead/cutoff", lo=500.0, hi=8000.0)
kr.midi_map(cc=76, path="verb/room", lo=0.0, hi=1.0)
kr.midi_map(cc=77, path="verb/gain", lo=0.0, hi=0.8)
```

## ADC input: live audio

Capture audio from your system's audio interface (CoreAudio on macOS):

```python
mic = kr.input("mic", channel=0, gain=0.5)
```

### Parameters

| Parameter | Description |
|---|---|
| `name` | Label for the input (e.g. `"mic"`, `"guitar"`) |
| `channel` | ADC input channel (0-indexed) |
| `gain` | Input gain (0.0--1.0) |

### Routing input to effects

Live audio inputs can be sent to buses just like voices:

```python
mic = kr.input("mic", channel=0, gain=0.5)
verb = kr.bus("verb", reverb_fn, gain=0.3)

mic.send(verb, 0.4)   # send mic to reverb at 40%
```

### Multiple inputs

```python
mic = kr.input("mic", channel=0, gain=0.5)
guitar = kr.input("guitar", channel=1, gain=0.7)

mic.send(verb, 0.3)
guitar.send(verb, 0.5)
```

## MIDI clock output

krach can send MIDI clock to sync external hardware (drum machines, sequencers,
synths). Enable it with an environment variable before starting the REPL:

```bash
KRACH_MIDI_CLOCK=1 ./bin/krach
```

The clock follows `kr.tempo` and sends standard MIDI clock messages (24 ppqn)
to all connected MIDI outputs.

## Hardware setup tips

**Audio interface** -- krach uses CoreAudio on macOS. Set your preferred
interface in Audio MIDI Setup before starting the REPL. Lower buffer sizes
give lower latency but higher CPU load.

**MIDI controllers** -- any class-compliant USB MIDI controller works. No
driver installation needed on macOS. Plug in before starting the REPL.

**Channel isolation** -- use the `channel=` parameter on `kr.midi_map()` when
multiple controllers are connected, to avoid CC collisions.

**Persisting mappings** -- save your MIDI mappings in a setup script and load
it at the start of each session:

```python
# midi_setup.py
kr.midi_map(cc=74, path="bass/cutoff", lo=200.0, hi=4000.0)
kr.midi_map(cc=1, path="bass/gain", lo=0.0, hi=1.0)
kr.midi_map(cc=7, path="verb/room", lo=0.0, hi=1.0)
```

```python
# In the REPL
kr.load("midi_setup.py")
```

**Monitoring latency** -- for live performance with external audio input, keep
your audio buffer size at 128 or 256 samples. At 44.1 kHz, 128 samples is
about 3 ms of latency.
