# Progress

## Current state

Rust crate (`soundman-faust` v0.1.0, edition 2024) — FAUST LLVM JIT backend for the `soundman` audio engine.

Modules:
- `ffi` — raw FFI bindings to libfaust C API (`llvm-dsp-c.h`, `CInterface.h`)
- `dsp` — safe `FaustDsp` wrapper: compile FAUST code, discover params via UIGlue callbacks, process audio
- `factory` — `FaustFactory` implements soundman's `NodeFactory` trait; probes port layout and controls at registration time
- `node` — `FaustNode` adapts `FaustDsp` to soundman's `DspNode` trait
- `lib` — public `register_faust_node()` entry point + `faust_version()`

Build:
- `build.rs` links libfaust (homebrew) and LLVM
- Strict clippy (all + pedantic + nursery denied)

Tests (`tests/integration_test.rs`):
- FAUST version check
- Compile sine (0 in, 1 out) and gain (1 in, 1 out) DSPs
- Sine produces nonzero audio output
- Gain applies parameter correctly (default 0.5, then set to 0.25)
- Factory probes correct `NodeTypeDecl`
- Full end-to-end: register FAUST node in soundman engine, load graph, process audio

## Next

- (none currently tracked)
