# Progress

## Current state

Rust crate (`soundman-faust` v0.1.0, edition 2024) — FAUST LLVM JIT backend for the `soundman` audio engine.

### Modules
- `ffi` — raw FFI bindings to libfaust C API (`llvm-dsp-c.h`, `CInterface.h`)
- `dsp` — safe `FaustDsp` wrapper: compile FAUST code, discover params via UIGlue callbacks, process audio
- `factory` — `FaustFactory` implements soundman's `NodeFactory` trait; probes port layout and controls at registration time. Returns `Result` from `create()` (no panic).
- `node` — `FaustNode` adapts `FaustDsp` to soundman's `DspNode` trait
- `loader` — load `.dsp` files from disk, register entire directories. Type IDs derived from filename (`sine.dsp` → `faust:sine`).
- `watcher` — `notify`-based file watcher emits `WatchEvent::Changed`/`Removed` for `.dsp` files. `apply_reload()` handles register/reregister via soundman's `NodeRegistry`.
- `lib` — public `register_faust_node()` entry point + `faust_version()`

### Build
- `build.rs` links libfaust (homebrew) and LLVM
- Strict clippy (all + pedantic + nursery denied)
- Dependencies: soundman (path), log, notify

### Tests (24 total)
- Integration (14): version check, sine/gain/stereo compile+process, error paths, reset, factory probe, full engine round-trip
- Loader (5): file loading, type_id derivation, directory registration, non-dsp skip, invalid code error
- Watcher (5): new file detection, modify detection, removal detection, non-dsp filtering, reregister round-trip

## Next

- Wire watcher into a running engine (event loop that calls `apply_reload` + triggers graph recompile)
- Consider: `.dsp` file convention / directory structure for projects
