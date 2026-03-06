# Progress

## Current state

Milestone 1 core architecture implemented and tested (79 tests, 0 unsafe):

### Completed modules
- **IR layer** (`ir/`): `NodeTypeDecl`, `PortDecl`, `ControlDecl`, `GraphIr`, `NodeInstance`, `ConnectionIr` with serde JSON support
- **Graph runtime** (`graph/`): `DspNode` trait, `NodeId`/`PortId`, `DspGraph` with scratch-based processing, `BufferPool`, topological sort (Kahn's algorithm)
- **Graph compiler** (`graph/compiler.rs`): `GraphIr` -> `DspGraph` validation, instantiation, topo-sort, buffer allocation
- **Registry** (`registry.rs`): `NodeFactory` trait, `NodeRegistry` with type-safe creation
- **Built-in nodes** (`nodes/`): `Oscillator` (sine/saw/square), `DacNode` (output passthrough)
- **Swap** (`swap/`): `Command` enum, `GraphSwapper` with linear crossfade and deferred drop
- **Engine** (`engine/`): `AudioEngine` wiring shadow graph, compiler, swapper, registry; handles `LoadGraph`, incremental mutations, `SetControl` via exposed labels
- **Protocol** (`protocol.rs`): `ClientMessage`/`ServerMessage` with serde JSON
- **Control** (`control/`): `ControlInput` trait, `MockControlInput`
- **Output** (`output/`): `AudioOutput` trait, `MockAudioOutput`

### Test coverage
- Unit tests: IR serde roundtrip, registry register/resolve, topo-sort correctness, oscillator output values/bounds/frequency, crossfade blending, command queue, graph compiler validation (all error paths)
- Integration tests: end-to-end LoadGraph, SetControl frequency change, hot-swap no-glitch, control input polling, offline rendering, JSON wire format

## Not yet implemented (M1 remaining)
- `output/cpal_backend.rs` — real audio output via cpal (requires cpal dependency)
- `control/osc.rs` — OSC receiver via rosc + UdpSocket (requires rosc dependency)
- `main.rs` — binary entry point that starts engine with cpal + OSC

## Next
- Add cpal and rosc dependencies for real audio output and OSC control
- Implement `CpalBackend` and `OscControlInput`
- Add `main.rs` binary for manual testing (listen for sine, send OSC)
