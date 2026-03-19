# Progress

## Current state

FAUST LLVM JIT plugin for soundman with hot reload. 27 tests, clippy clean (all + pedantic + nursery).

### Modules
- **FFI** (`ffi.rs`): Raw bindings to libfaust C API (`llvm-dsp-c.h`, `CInterface.h`)
- **DSP** (`dsp.rs`): Safe `FaustDsp` wrapper — compile, parameter discovery via UIGlue, audio processing
- **Factory** (`factory.rs`): `FaustFactory` implements soundman's `NodeFactory` — probes ports and controls
- **Node** (`node.rs`): `FaustNode` adapts `FaustDsp` to soundman's `DspNode` trait
- **Loader** (`loader.rs`): Load `.dsp` files from disk, register entire directories (`sine.dsp` → `faust:sine`)
- **Watcher** (`watcher.rs`): `notify`-based file watcher, `apply_reload()` for register/reregister
- **Hot reload** (`hot_reload.rs`): `HotReloadEngine` — wraps engine + watcher + graph for live reloading

### Stats
- 27 tests passing (14 integration + 5 loader + 5 watcher + 3 hot reload)
- Rust edition 2024, strict clippy (all + pedantic + nursery denied)
- Tests serialized (`.cargo/config.toml`) — FAUST LLVM JIT not thread-safe across factory creation/deletion
- Dependencies: soundman (path), log, notify

## Next

- Wire into a binary (main.rs) with OSC control + hot reload loop
- Consider: `.dsp` file convention / directory structure for projects
