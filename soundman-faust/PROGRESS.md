# Progress

## Current state

Rust crate (`soundman-faust` v0.1.0, edition 2024) — FAUST LLVM JIT backend for the `soundman` audio engine.

### Modules
- `ffi` — raw FFI bindings to libfaust C API (`llvm-dsp-c.h`, `CInterface.h`)
- `dsp` — safe `FaustDsp` wrapper: compile FAUST code, discover params via UIGlue callbacks, process audio
- `factory` — `FaustFactory` implements soundman's `NodeFactory` trait; returns `Result` from `create()`
- `node` — `FaustNode` adapts `FaustDsp` to soundman's `DspNode` trait
- `loader` — load `.dsp` files from disk, register entire directories (`sine.dsp` → `faust:sine`)
- `watcher` — `notify`-based file watcher emits `WatchEvent::Changed`/`Removed`, `apply_reload()` handles register/reregister
- `hot_reload` — `HotReloadEngine` wraps `EngineController` + `DspWatcher` + `GraphIr`; `poll_reload()` recompiles changed nodes and re-sends the graph for crossfade swap
- `lib` — public `register_faust_node()` entry point + `faust_version()`

### Build
- `build.rs` links libfaust (homebrew) and LLVM
- Strict clippy (all + pedantic + nursery denied)
- `.cargo/config.toml` serializes tests (FAUST LLVM JIT not thread-safe across factory creation/deletion)
- Dependencies: soundman (path), log, notify

### Tests (27 total)
- Integration (14): version, sine/gain/stereo compile+process, error paths, reset, factory probe, engine round-trip
- Loader (5): file loading, type_id derivation, directory registration, non-dsp skip, invalid code error
- Watcher (5): new file, modify, removal detection, non-dsp filtering, reregister round-trip
- Hot reload (3): initial load + audio, file change triggers reload + audio changes, new file auto-registers

## Next

- Wire into a binary (main.rs) with OSC control + hot reload loop
- Consider: `.dsp` file convention / directory structure for projects
