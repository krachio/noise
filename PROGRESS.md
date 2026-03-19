# Progress

## Current state

Live coding / generative audio system — single monorepo (`krachio/noise`), Cargo workspace.

- **soundman-core** (Rust): Audio engine library — graph runtime, lock-free audio thread, cpal, OSC control, `list_nodes` — 90 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin for soundman-core — hot reload, 27 tests. Library only, no binary yet.
- **midiman** (Rust): Pattern sequencer — IPC server, MIDI/OSC output, 105 tests.
- **midiman-frontend** (Python 3.13): Python DSL over midiman — pattern algebra, Session — 120 tests.
- **soundman-frontend** (Python 3.13): OSC client for soundman — `Graph`, `SoundmanSession`, `list_nodes()` — 28 tests.
- **faust-dsl** (Python 3.13): Python → Faust `.dsp` transpiler — `ControlSchema`, `control()` — 34 tests.
- **krach** (Python 3.12): Stack bootstrapped, no domain logic yet.

Control flow: `midiman-frontend → midiman (Unix IPC) → soundman (OSC) → soundman-faust (FAUST LLVM JIT)`

`krach` will be the REPL shell tying everything together.

## Next

1. **`soundman/`** — composition binary: soundman-core + soundman-faust in one process. Watches `~/.krach/dsp/`, exposes full OSC API on port 9001.
2. **`krach`** — REPL shell: `KrachSession(mm, sm)`, `k.dsp(name, fn)`, IPython entry point.

## Open decisions

- soundman-core has its own lean `main.rs` (440Hz sine demo). Keep or remove once `soundman/` binary exists?
