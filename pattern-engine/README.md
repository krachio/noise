# pattern-engine

A [Tidal Cycles](https://tidalcycles.org)-inspired live coding kernel for MIDI and OSC. No audio synthesis — just precise, composable control signal patterns evaluated over rational time.

The `krach.patterns` Python module (in `krach/` sibling) sends pattern IR over a Unix socket; the Rust kernel compiles, schedules, and outputs events in real time.

## Architecture

```
Python frontend ──JSON/IPC──▶ pattern-engine kernel
                                 │
                         ┌───────┴───────┐
                         ▼               ▼
                      MIDI out        OSC out
                      (midir)      (rosc + UDP)
```

**Core pipeline:** IR → compile → arena-indexed pattern → scheduler query → output dispatch

| Module | Role |
|--------|------|
| `time` | Rational time (i64/u64), half-open arcs, `split_cycles` |
| `event` | `Event<V>` with whole/part model, `Value` (Note, Cc, Osc) |
| `pattern` | Arena-indexed `CompiledPattern`, `query()` evaluator |
| `ir` | `IrNode` serde-tagged enum, validation, compile |
| `scheduler` | Real-time loop, `Clock`, lock-free hot-swap via arc-swap |
| `output` | `OutputSink` trait, MIDI (midir), OSC (rosc + UDP) |
| `ipc` | Unix socket, newline-delimited JSON protocol |
| `rt` | Thread priority elevation (non-fatal) |

## Quick start

```bash
cargo run                    # listens on $TMPDIR/krach-engine.sock
```

In another terminal:

```bash
# Play middle C
echo '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}' \
  | socat - UNIX-CONNECT:$TMPDIR/krach-engine.sock

# Silence it
echo '{"cmd":"Hush","slot":"d1"}' | socat - UNIX-CONNECT:$TMPDIR/krach-engine.sock
```

## Pattern IR reference

Patterns are JSON trees tagged by `"op"`. Every pattern occupies one **cycle** — the fundamental time unit (one bar). At 120 BPM with 4 beats/cycle, one cycle = 2 seconds.

### Values

Leaf values go inside `Atom` nodes.

**Note** — MIDI note-on (note-off scheduled automatically):

```json
{"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}
```

| Field | Type | Description |
|-------|------|-------------|
| `channel` | 0–15 | MIDI channel |
| `note` | 0–127 | MIDI note number |
| `velocity` | 0–127 | Note-on velocity |
| `dur` | float | Duration in cycles (0.5 = half a cycle) |

**Cc** — MIDI continuous controller:

```json
{"type": "Cc", "channel": 0, "controller": 1, "value": 64}
```

**Osc** — OSC message with typed arguments:

```json
{"type": "Osc", "address": "/synth/freq", "args": [{"Float": 440.0}, {"Int": 42}, {"Str": "hello"}]}
```

### Combinators

#### `Atom` — single event

Plays a value once per cycle.

```json
{"op": "Atom", "value": <Value>}
```

#### `Silence` — no events

```json
{"op": "Silence"}
```

#### `Cat` — sequential concatenation

Children share the cycle equally. `Cat [a, b, c]` plays a in the first third, b in the second, c in the last.

```json
{"op": "Cat", "children": [<pattern>, <pattern>, ...]}
```

#### `Stack` — parallel layering

All children occupy the full cycle simultaneously. Polyphonic.

```json
{"op": "Stack", "children": [<pattern>, <pattern>, ...]}
```

#### `Fast` — speed up

Compress the child pattern by a rational factor. `Fast [2,1]` plays the pattern twice per cycle.

```json
{"op": "Fast", "factor": [2, 1], "child": <pattern>}
```

#### `Slow` — slow down

Stretch the child pattern by a rational factor. `Slow [2,1]` takes two cycles to complete.

```json
{"op": "Slow", "factor": [2, 1], "child": <pattern>}
```

#### `Early` / `Late` — time shift

Shift events earlier or later by a rational offset (in cycles).

```json
{"op": "Early", "offset": [1, 4], "child": <pattern>}
{"op": "Late",  "offset": [1, 4], "child": <pattern>}
```

#### `Rev` — reverse

Reverse the child pattern within each cycle.

```json
{"op": "Rev", "child": <pattern>}
```

#### `Every` — periodic transform

Apply `transform` every `n` cycles, otherwise play `child` unchanged.

```json
{"op": "Every", "n": 4, "transform": <pattern>, "child": <pattern>}
```

#### `Euclid` — Euclidean rhythm

Distribute `pulses` hits evenly across `steps` slots. Classic Euclidean algorithm for rhythms like tresillo (3,8) or rumba (5,16).

```json
{"op": "Euclid", "pulses": 3, "steps": 8, "rotation": 0, "child": <pattern>}
```

#### `Degrade` — random dropout

Drop events with probability `prob` (0.0 = keep all, 1.0 = drop all). Deterministic — same `seed` always produces the same pattern.

```json
{"op": "Degrade", "prob": 0.5, "seed": 42, "child": <pattern>}
```

### Rational time

`Fast`, `Slow`, `Early`, `Late` take rational values as `[numerator, denominator]`:

| Value | Meaning |
|-------|---------|
| `[1, 1]` | 1 |
| `[3, 2]` | 1.5 |
| `[1, 3]` | one third |
| `[7, 4]` | 1.75 |

Rational time prevents floating-point drift. Subdivisions are always exact.

## IPC protocol

Newline-delimited JSON over Unix socket.

### Commands

**SetPattern** — assign a pattern to a named slot:

```json
{"cmd": "SetPattern", "slot": "d1", "pattern": <IrNode>}
```

**Hush** — silence a slot:

```json
{"cmd": "Hush", "slot": "d1"}
```

**HushAll** — silence all slots:

```json
{"cmd": "HushAll"}
```

**SetBpm** — change tempo (takes effect next tick):

```json
{"cmd": "SetBpm", "bpm": 140.0}
```

**SetBeatsPerCycle** — set meter (beats per cycle):

```json
{"cmd": "SetBeatsPerCycle", "beats": 3}
```

**SetPatternFromZero** — assign pattern and restart from cycle zero:

```json
{"cmd": "SetPatternFromZero", "slot": "d1", "pattern": <IrNode>}
```

**Ping** — health check:

```json
{"cmd": "Ping"}
```

**Batch** — atomic group of commands (all-or-nothing):

```json
{"cmd": "Batch", "commands": [
  {"cmd": "SetPattern", "slot": "d1", "pattern": <IrNode>},
  {"cmd": "SetPattern", "slot": "d2", "pattern": <IrNode>},
  {"cmd": "SetBpm", "bpm": 140.0}
]}
```

All commands compile and validate before any are applied. If any command fails, the entire batch is rejected. Nested batches are not allowed.

### Responses

```json
{"status": "Ok",    "msg": "pattern set on d1"}
{"status": "Error", "msg": "Cat requires at least one child"}
{"status": "Pong"}
```

## Cookbook

### Two-note alternation

```json
{"cmd": "SetPattern", "slot": "d1", "pattern":
  {"op": "Cat", "children": [
    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
  ]}
}
```

Plays C4 for the first half of each cycle, E4 for the second.

### Euclidean kick pattern

```json
{"cmd": "SetPattern", "slot": "d1", "pattern":
  {"op": "Euclid", "pulses": 3, "steps": 8, "rotation": 0, "child":
    {"op": "Atom", "value": {"type": "Note", "channel": 9, "note": 36, "velocity": 100, "dur": 0.25}}
  }
}
```

Three kicks distributed across eight slots — the classic tresillo rhythm (x..x..x.).

### Layered polyrhythm

```json
{"cmd": "SetPattern", "slot": "d1", "pattern":
  {"op": "Stack", "children": [
    {"op": "Fast", "factor": [3, 1], "child":
      {"op": "Atom", "value": {"type": "Note", "channel": 9, "note": 42, "velocity": 80, "dur": 0.1}}
    },
    {"op": "Euclid", "pulses": 5, "steps": 8, "rotation": 0, "child":
      {"op": "Atom", "value": {"type": "Note", "channel": 9, "note": 36, "velocity": 100, "dur": 0.25}}
    }
  ]}
}
```

Hi-hat triplets layered with a Euclidean kick — 3-against-5 polyrhythm.

### Driving audio-engine over OSC

With `audio-engine` (sibling in this monorepo) running on port 9000:

```bash
PATTERN_ENGINE_OSC_TARGET=127.0.0.1:9000 cargo run
```

```json
{"cmd": "SetPattern", "slot": "d1", "pattern":
  {"op": "Cat", "children": [
    {"op": "Atom", "value": {"type": "Osc", "address": "/audio/set", "args": [{"Str": "pitch"}, {"Float": 261.63}]}},
    {"op": "Atom", "value": {"type": "Osc", "address": "/audio/set", "args": [{"Str": "pitch"}, {"Float": 329.63}]}},
    {"op": "Atom", "value": {"type": "Osc", "address": "/audio/set", "args": [{"Str": "pitch"}, {"Float": 392.0}]}},
    {"op": "Atom", "value": {"type": "Osc", "address": "/audio/set", "args": [{"Str": "pitch"}, {"Float": 493.88}]}}
  ]}
}
```

Sequences a C major 7th arpeggio through audio-engine's oscillator.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `PATTERN_ENGINE_SOCKET` | `$TMPDIR/krach-engine.sock` | IPC socket path |
| `PATTERN_ENGINE_OSC_TARGET` | `127.0.0.1:57120` | OSC destination |
| `PATTERN_ENGINE_MIDI_CLOCK` | off | Set to `1` to emit 24 ppqn MIDI clock |

MIDI output connects to the first available port automatically.

## Development

```bash
cargo check    # type check (strict clippy, unsafe_code = "forbid")
cargo test     # 129 tests
```

## License

MIT
