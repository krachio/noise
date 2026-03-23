# Scenes

krach can save and restore complete session states -- voices, buses, patterns,
tempo, and all control values. Use scenes to build song sections, switch
between arrangements, and persist your work to disk.

## In-memory snapshots

Save the current state to memory with a name:

```python
kr.save("verse")
```

Restore it later:

```python
kr.recall("verse")
```

In-memory snapshots are fast but **lost when you exit the REPL**.

### Workflow: A/B between sections

```python
# Build a verse
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.save("verse")

# Build a chorus
kr.play("kick", kr.hit() * 8)
kr.play("bass", kr.seq("A3", "C3", "E3", "G3"))
kr.save("chorus")

# Switch between them
kr.recall("verse")
kr.recall("chorus")
```

## File persistence

Export the full session to a Python file:

```python
kr.export("verse.py")
```

Reload it in a later session:

```python
kr.load("verse.py")
```

Load from a subdirectory:

```python
kr.load("songs/verse.py")
```

## What gets captured

A scene snapshot (both in-memory and file export) captures:

- **Voices** -- all active voices with their DSP type and gain
- **Buses** -- all effect buses and their configuration
- **Sends** -- all send routings and levels
- **Patterns** -- all active pattern assignments
- **Tempo** -- current BPM
- **Master gain** -- `kr.master` level
- **Controls** -- current values of all voice/bus controls

## Music as Python modules

Exported files are plain Python. You can edit them, share them, and version
them with git. A typical exported file sets up voices, buses, sends, and
patterns -- everything needed to reproduce the session.

Write reusable setup scripts by hand:

```python
# my_kit.py -- reusable drum kit setup
@kr.dsp
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

@kr.dsp
def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5

with kr.batch():
    kr.voice("drums/kick", kick, gain=0.8)
    kr.voice("drums/hat", hat, gain=0.5)
```

Then load it from the REPL:

```python
kr.load("my_kit.py")
kr.play("drums/kick", kr.hit() * 4)
kr.play("drums/hat", (kr.rest() + kr.hit()) * 4)
```

## Workflow: compose, export, iterate

1. **Compose** -- build your session interactively in the REPL
2. **Export** -- `kr.export("session.py")` saves everything
3. **Iterate** -- edit the file, reload with `kr.load()`, repeat

```python
# Session 1: build the initial arrangement
kr.tempo = 128
kr.voice("kick", kick, gain=0.8)
kr.voice("bass", acid_bass, gain=0.3)
kr.play("kick", kr.hit() * 4)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
kr.export("track_v1.py")

# Session 2: pick up where you left off
kr.load("track_v1.py")
kr.voice("lead", lead_fn, gain=0.25)
kr.play("lead", kr.seq("A4", "C5", "E5", "D5").over(2))
kr.export("track_v2.py")
```
