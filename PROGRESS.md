# Progress

## Current state

Live coding audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine — graph runtime, lock-free audio, fan-in mixing with NaN isolation, output clamping, gain node, cpal, OSC — 104 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 14 tests.
- **soundman** (Rust binary): soundman-core + soundman-faust. Watches `~/.krach/dsp/`, OSC on port 9001.
- **midiman** (Rust): Pattern sequencer — single-loop engine with min-heap, sample-accurate OSC via bundle timestamps — 114 tests.
- **midiman-frontend** (Python 3.13): Pattern DSL — algebra (+, |, *, .over()), Session — 120 tests.
- **soundman-frontend** (Python 3.13): OSC client — `Graph`, `SoundmanSession` — 28 tests.
- **faust-dsl** (Python 3.13): Python → Faust transpiler — 68 tests.
- **krach** (Python 3.13): Live coding REPL — VoiceMixer (`mix`), copilot (`c()`), cell queue (`cn()`) — 44 tests.

## Usage

```bash
./bin/krach
# mix.voice("kit", "faust:kit", gain=0.8)
# mm.play("kick", mix.hit("kit", "kick") * 4)
```

## Next

- Effects routing: mix.bus() / mix.send() for reverb/delay
- Scenes: mm.scene() for pattern snapshot switching
- midiman: note-off scheduling, follow actions
- Phase 2 timing: sub-block sample splitting (~0ms jitter)
