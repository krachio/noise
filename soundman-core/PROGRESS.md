# Progress

## Current state

**Milestone 1 complete + audio hardening.** 89 tests (83 unit + 6 integration), 0 unsafe, clippy clean.

### Modules
- **IR layer** (`ir/`): `NodeTypeDecl`, `PortDecl`, `ControlDecl`, `GraphIr`, `NodeInstance`, `ConnectionIr` — serde JSON wire format
- **Graph runtime** (`graph/`): `DspNode` trait, `DspGraph` with scratch-based processing, `BufferPool`, topological sort (Kahn's algorithm)
- **Graph compiler** (`graph/compiler.rs`): `GraphIr` -> `DspGraph` — validate types/ports, instantiate from registry, topo-sort, allocate buffers
- **Registry** (`registry.rs`): `NodeFactory` trait, `NodeRegistry`
- **Built-in nodes** (`nodes/`): `Oscillator` (sine/saw/square), `DacNode`
- **Swap** (`swap/`): `Command` enum, `GraphSwapper` with linear crossfade
- **Engine** (`engine/`): `AudioEngine` — shadow graph, compiler, swapper, registry; handles full `ClientMessage` protocol
- **Protocol** (`protocol.rs`): `ClientMessage`/`ServerMessage` JSON
- **Control** (`control/`): `ControlInput` trait, `MockControlInput`, `OscControlInput` (UDP/rosc)
- **Output** (`output/`): `AudioOutput` trait, `MockAudioOutput`, `CpalBackend` (cpal)
- **Binary** (`main.rs`): starts 440Hz sine via cpal, OSC control on 127.0.0.1:9000
- **Node introspection**: `/soundman/list_nodes <reply_port>` sends `/soundman/node_types` JSON reply via UDP; `EngineController::list_node_types()` exposes registry type IDs

### M1 acceptance criteria status
- [x] Engine starts, produces 440Hz sine through cpal
- [x] OSC `/soundman/set pitch 880.0` changes frequency (via exposed control)
- [x] OSC `/soundman/load_graph <json>` swaps graph with crossfade
- [x] `cargo test` passes (90 tests)
- [x] `cargo clippy -- -D warnings` clean
- [x] No `unsafe` in main crate

### Post-M1 hardening
- Lock-free audio: `EngineController` + `AudioProcessor` split, connected by `rtrb` SPSC ring buffer
- Pre-allocated crossfade buffers (no allocation on audio thread)
- Device sample rate query (uses native rate, not hardcoded 48000)
- `OscType::Double` support (midiman compatibility)
- `env_logger` integration (RUST_LOG=soundman=debug)

## Next (M2: Multi-node graph)
- Gain/mixer nodes
- Multi-node graph (osc -> filter -> dac)
- Graph builder API
