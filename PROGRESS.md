# Progress

## Current state

Live coding / generative audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine library — graph runtime, lock-free audio, cpal, OSC, `list_nodes` — 90 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 27 tests.
- **soundman** (Rust binary): Composition binary — soundman-core + soundman-faust. Watches `~/.krach/dsp/`, OSC on port 9001.
- **midiman** (Rust): Pattern sequencer — IPC server, MIDI/OSC output — 105 tests.
- **midiman-frontend** (Python 3.13): Python DSL over midiman — pattern algebra, Session — 120 tests.
- **soundman-frontend** (Python 3.13): OSC client for soundman — `Graph`, `SoundmanSession`, `list_nodes()` — 28 tests.
- **faust-dsl** (Python 3.13): Python → Faust `.dsp` transpiler — `ControlSchema`, `control()` — 34 tests.
- **krach** (scaffold only — see `bin/krach`).
- **`bin/krach`**: Shell script — starts midiman + soundman, drops into IPython with mm, sm, dsp(), note, rest, Graph, transpile, etc. in scope.

## Usage

```bash
./bin/krach
# mm, sm, dsp(), note, rest, cc, Graph, transpile, sine_osc, ... all in scope
```

## Next

- Wire midiman OSC output → soundman for pattern-driven parameter control
- soundman M2: gain/mixer nodes (needed for multi-voice graphs)
- midiman: note-off scheduling, RT thread priority
