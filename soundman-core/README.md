# soundman

Real-time audio engine for the [noise](https://github.com/krachio) ecosystem. Graph-based DSP with lock-free audio, hot-swappable graphs, and OSC control.

## Architecture

```
OSC / JSON ──▶ EngineController ──rtrb──▶ AudioProcessor ──▶ cpal output
                    │                          │
              shadow graph              GraphSwapper
              + compiler               (linear crossfade)
                    │                          │
               NodeRegistry              DspGraph
               (pluggable)            (topo-sorted DAG)
```

**Control thread:** receives messages, compiles graphs, sends commands via lock-free SPSC ring buffer.
**Audio thread:** drains commands, processes audio. No locks, no allocation.

| Module | Role |
|--------|------|
| `ir/` | `GraphIr`, `NodeInstance`, `ConnectionIr` — serde JSON wire format |
| `graph/` | `DspNode` trait, `DspGraph` with scratch-based processing, topo-sort |
| `graph/compiler.rs` | `GraphIr` → `DspGraph` — validate, instantiate, sort, allocate |
| `registry.rs` | `NodeFactory` trait, `NodeRegistry` — pluggable node types |
| `nodes/` | Built-in nodes: `Oscillator` (sine/saw/square), `DacNode` |
| `swap/` | `GraphSwapper` with pre-allocated linear crossfade buffers |
| `engine/` | `EngineController` + `AudioProcessor` split, `rtrb` SPSC channel |
| `protocol.rs` | `ClientMessage` / `ServerMessage` JSON protocol |
| `control/` | `ControlInput` trait, `OscControlInput` (UDP/rosc) |
| `output/` | `AudioOutput` trait, `CpalBackend` (cpal) |

## Quick start

```bash
# Run (440 Hz sine on default output, OSC control on port 9000)
cargo run

# Change frequency
oscsend 127.0.0.1 9000 /soundman/set sf pitch 880.0

# Set master gain
oscsend 127.0.0.1 9000 /soundman/gain f 0.5

# Shutdown
oscsend 127.0.0.1 9000 /soundman/shutdown
```

## OSC protocol

All commands are under the `/soundman/` namespace:

| Address | Args | Description |
|---------|------|-------------|
| `/soundman/set` | `s:label f:value` | Set an exposed control parameter |
| `/soundman/gain` | `f:gain` | Set master gain (0.0–1.0) |
| `/soundman/load_graph` | `s:json` | Hot-swap to a new graph (JSON `GraphIr`) |
| `/soundman/ping` | — | Health check |
| `/soundman/shutdown` | — | Stop the engine |

Accepts both `OscType::Float` and `OscType::Double` for numeric values.

## JSON protocol

Load a graph via OSC or programmatically:

```json
{
  "nodes": [
    {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}},
    {"id": "out", "type_id": "dac", "controls": {}}
  ],
  "connections": [
    {"from_node": "osc1", "from_port": "out", "to_node": "out", "to_port": "in"}
  ],
  "exposed_controls": {"pitch": ["osc1", "freq"]}
}
```

## With midiman

[midiman](https://github.com/krachio/midiman) is a pattern sequencer that sends timed OSC messages. Connect them:

```bash
# Terminal 1: audio engine
cargo run

# Terminal 2: pattern sequencer
cd ../midiman && MIDIMAN_OSC_TARGET=127.0.0.1:9000 cargo run

# Terminal 3: send a C major 7th arpeggio
echo '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":261.63}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":329.63}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":392.0}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":493.88}]}}]}}' | socat - UNIX-CONNECT:/tmp/midiman.sock
```

## Custom node types

soundman is DSP-agnostic. Register your own node types via `EngineController::registry_mut()`:

```rust
let (mut ctrl, proc) = engine::engine(&config);

// Register a new type
ctrl.registry_mut().register(decl, factory).unwrap();

// Hot-reload: swap factory for an existing type (e.g. after recompilation)
ctrl.registry_mut().reregister(updated_decl, new_factory).unwrap();
```

Each type needs:
- **`NodeTypeDecl`** — declares ports (audio in/out) and controls (name, range, default)
- **`NodeFactory`** — `create(sample_rate, block_size) -> Result<Box<dyn DspNode>, String>`

See [`soundman-faust`](https://github.com/krachio/soundman-faust) for a real-world example that compiles FAUST DSP code via LLVM JIT and registers nodes at runtime.

## Development

```bash
cargo check    # type check (strict clippy, unsafe_code = "forbid")
cargo test     # 91 unit + 6 integration tests
```

## License

MIT
