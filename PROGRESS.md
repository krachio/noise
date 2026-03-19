# Progress

## Current state

Live coding / generative audio system in active development across 6 subprojects.

- **midiman** (Rust): Full-featured pattern sequencer with IPC server — 105 tests. Handles time, events, patterns, scheduler, MIDI/OSC output, hot-swap via Unix socket.
- **midiman-frontend** (Python 3.13): Python DSL over midiman — pattern algebra, Session, IR serialization — 120 tests, wire-compatible with Rust kernel.
- **soundman** (Rust): Audio engine with graph runtime, lock-free audio thread, cpal output, OSC control, crossfade graph swap, `/soundman/list_nodes` query — 90 tests, M1 complete.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin for soundman — compiles `.dsp` files, hot reload, 27 tests.
- **faust-dsl** (Python 3.13): Python DSL that transpiles to Faust `.dsp` source — 34 tests, zero deps.
- **soundman-frontend** (Python 3.13): OSC client for soundman — `Graph` builder, `SoundmanSession`, `expose_schema()`, `list_nodes()` — 28 tests.
- **krach** (Python 3.12): Stack bootstrapped (pyright strict, pytest, uv), no domain logic yet.

Control flow: `midiman-frontend → midiman (Unix IPC) → soundman (OSC) → soundman-faust (FAUST LLVM JIT)`

`krach` will be the REPL shell that wraps all of the above into a live coding session.

## Next

Planned build order for completing krach:

1. ~~`soundman-frontend`~~ ✅ done
2. ~~soundman: `/soundman/list_nodes`~~ ✅ done
3. **`krach`**: REPL shell wrapping `midiman-frontend` + `soundman-frontend` + `faust-dsl` into a unified live coding session.

Other pending work:
- **midiman**: Note-off scheduling (priority queue); real-time thread priority
- **soundman (M2)**: Gain/mixer nodes, multi-node graph (osc → filter → dac)
- **soundman-faust**: Wire into a binary with OSC control + hot reload loop
- **midiman-frontend**: Integration test against a running midiman kernel
