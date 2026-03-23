# Protocol Reference

krach uses a single Unix socket for all communication between the Python REPL and the Rust engine. Messages are newline-delimited JSON.

## Transport

- **Socket**: `/tmp/krach.sock` (override with `NOISE_SOCKET` env var)
- **Format**: one JSON object per line, terminated by `\n`
- **Direction**: request/response — the client sends a command, the server replies with one JSON line

## Message families

The IPC server accepts two distinct message families on the same socket:

| Family | Tag field | Purpose |
|--------|-----------|---------|
| Pattern commands | `"cmd"` | Control the pattern sequencer (set patterns, hush, tempo) |
| Audio commands | `"type"` | Control the audio engine (load graphs, set controls, automation) |

The IPC thread inspects the top-level tag to route each message to the correct subsystem.

## Pattern commands

All pattern commands use a `"cmd"` tag.

### SetPattern

Assign a pattern to a named slot. The pattern starts playing from the current cycle position.

```json
{"cmd": "SetPattern", "slot": "d1", "pattern": {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}}}
```

### SetPatternFromZero

Same as `SetPattern`, but restarts the slot from cycle zero.

```json
{"cmd": "SetPatternFromZero", "slot": "d1", "pattern": {"op": "Cat", "children": [...]}}
```

### Hush

Silence a single slot.

```json
{"cmd": "Hush", "slot": "d1"}
```

### HushAll

Silence all slots.

```json
{"cmd": "HushAll"}
```

### SetBpm

Change tempo. Takes effect on the next scheduler tick.

```json
{"cmd": "SetBpm", "bpm": 140.0}
```

### SetBeatsPerCycle

Set meter (beats per cycle). Default is 4.

```json
{"cmd": "SetBeatsPerCycle", "beats": 3}
```

### Batch

Atomic group of commands. All commands are validated before any are applied. If any command fails, the entire batch is rejected. Nested batches are not allowed.

```json
{"cmd": "Batch", "commands": [
  {"cmd": "SetPattern", "slot": "d1", "pattern": {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}}},
  {"cmd": "SetPattern", "slot": "d2", "pattern": {"op": "Silence"}},
  {"cmd": "SetBpm", "bpm": 140.0}
]}
```

### Ping

Health check.

```json
{"cmd": "Ping"}
```

## Audio commands

All audio commands use a `"type"` tag with `snake_case` variant names.

### load_graph

Replace the entire audio graph. Crossfades from the current graph. Nodes with matching IDs are reused.

```json
{"type": "load_graph", "nodes": [
  {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}},
  {"id": "out", "type_id": "dac", "controls": {}}
], "connections": [
  {"from_node": "osc1", "from_port": "out", "to_node": "out", "to_port": "in"}
], "exposed_controls": {"pitch": ["osc1", "freq"]}}
```

### set_control

Set an exposed control parameter by label.

```json
{"type": "set_control", "label": "pitch", "value": 440.0}
```

### set_master_gain

Set the master output gain (0.0-1.0).

```json
{"type": "set_master_gain", "gain": 0.5}
```

### set_automation

Add or replace a parameter automation. The shape drives the parameter between `lo` and `hi` with the given period.

```json
{"type": "set_automation", "id": "lfo1", "label": "pitch", "shape": "sine", "lo": 220.0, "hi": 880.0, "period_secs": 2.0, "one_shot": false}
```

Available shapes: `sine`, `tri`, `ramp`, `ramp_down`, `square`, `exp`, `pulse`.

### clear_automation

Remove an automation by ID.

```json
{"type": "clear_automation", "id": "lfo1"}
```

### add_node / remove_node / connect / disconnect

Incremental graph mutations. These modify the shadow graph and trigger a recompile.

```json
{"type": "add_node", "id": "filt1", "type_id": "lpf", "controls": {"cutoff": 1000.0}}
{"type": "remove_node", "id": "filt1"}
{"type": "connect", "from_node": "osc1", "from_port": "out", "to_node": "filt1", "to_port": "in"}
{"type": "disconnect", "from_node": "osc1", "from_port": "out", "to_node": "filt1", "to_port": "in"}
```

### graph_batch

Atomic batch of graph mutations. All mutations are applied to the shadow graph before a single recompile.

```json
{"type": "graph_batch", "commands": [
  {"type": "add_node", "id": "filt1", "type_id": "lpf", "controls": {"cutoff": 1000.0}},
  {"type": "connect", "from_node": "osc1", "from_port": "out", "to_node": "filt1", "to_port": "in"}
]}
```

### list_nodes

Request the list of registered node type IDs. The engine sends a response with all available types.

```json
{"type": "list_nodes", "reply_port": 9001}
```

### ping

Health check for the audio engine.

```json
{"type": "ping"}
```

### shutdown

Stop the engine.

```json
{"type": "shutdown"}
```

## Pattern IR format

Patterns are JSON trees tagged by `"op"`. Every pattern occupies one cycle (one bar). Children of `Cat` divide the cycle equally; children of `Stack` overlap the full cycle.

### Combinators

| Op | Fields | Description |
|----|--------|-------------|
| `Atom` | `value` | Single event, plays once per cycle |
| `Silence` | — | No events |
| `Cat` | `children` | Sequential: children share the cycle equally |
| `Stack` | `children` | Parallel: all children occupy the full cycle |
| `Fast` | `factor`, `child` | Speed up by rational factor `[num, den]` |
| `Slow` | `factor`, `child` | Slow down by rational factor `[num, den]` |
| `Early` | `offset`, `child` | Shift events earlier by rational offset |
| `Late` | `offset`, `child` | Shift events later by rational offset |
| `Rev` | `child` | Reverse within each cycle |
| `Every` | `n`, `transform`, `child` | Apply transform every n cycles |
| `Euclid` | `pulses`, `steps`, `rotation`, `child` | Euclidean rhythm distribution |
| `Degrade` | `prob`, `seed`, `child` | Random dropout with given probability |
| `Freeze` | `child` | Mark sub-pattern as indivisible unit |

### Value types

| Type | Fields | Description |
|------|--------|-------------|
| `Note` | `channel`, `note`, `velocity`, `dur` | MIDI note (note-off auto-scheduled) |
| `Cc` | `channel`, `controller`, `value` | MIDI CC |
| `Osc` | `address`, `args` | OSC message with typed args (`Float`, `Int`, `Str`) |
| `Control` | `label`, `value` | Direct audio-engine control (no OSC serialization) |

### Rational time

`Fast`, `Slow`, `Early`, `Late` take rational values as `[numerator, denominator]`. Examples: `[1, 1]` = 1, `[3, 2]` = 1.5, `[1, 3]` = one third.

## Responses

### Pattern command responses

```json
{"status": "Ok", "msg": "pattern set on d1"}
{"status": "Error", "msg": "Cat requires at least one child"}
{"status": "Pong"}
```

### Audio command responses

```json
{"type": "ok"}
{"type": "error", "message": "unknown node type: foo"}
{"type": "pong"}
{"type": "node_types", "types": ["oscillator", "dac", "synth", "lpf"]}
```

## Example with socat

```bash
# Ping the engine
echo '{"cmd": "Ping"}' | socat - UNIX-CONNECT:/tmp/krach.sock

# Set a pattern
echo '{"cmd": "SetPattern", "slot": "d1", "pattern": {"op": "Cat", "children": [{"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}}, {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}]}}' | socat - UNIX-CONNECT:/tmp/krach.sock

# Load an audio graph
echo '{"type": "load_graph", "nodes": [{"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}}, {"id": "out", "type_id": "dac", "controls": {}}], "connections": [{"from_node": "osc1", "from_port": "out", "to_node": "out", "to_port": "in"}], "exposed_controls": {"pitch": ["osc1", "freq"]}}' | socat - UNIX-CONNECT:/tmp/krach.sock

# Set a control
echo '{"type": "set_control", "label": "pitch", "value": 880.0}' | socat - UNIX-CONNECT:/tmp/krach.sock

# Hush all
echo '{"cmd": "HushAll"}' | socat - UNIX-CONNECT:/tmp/krach.sock
```
