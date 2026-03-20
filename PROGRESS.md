# Progress

## Current state

Live coding audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine — graph runtime with node reuse across swaps (compile_with_reuse + return channel), lock-free audio, fan-in with NaN isolation, output clamping, gain node, registry versioning — 112 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 14 tests.
- **soundman** (Rust binary): soundman-core + soundman-faust. Watches `~/.krach/dsp/`, OSC on port 9001.
- **midiman** (Rust): Pattern sequencer — single-loop engine with min-heap, sample-accurate OSC — 114 tests.
- **midiman-frontend** (Python 3.13): Pattern DSL with limit_denominator(256) for safe float rationals — 122 tests.
- **soundman-frontend** (Python 3.13): OSC client — `Graph`, `SoundmanSession` — 28 tests.
- **faust-dsl** (Python 3.13): Python → Faust transpiler — 68 tests.
- **krach** (Python 3.13): Live coding REPL — VoiceMixer (`mix`) with batch(), copilot (`c()`) — 46 tests.

## Usage

```bash
./bin/krach
# with mix.batch():
#     mix.voice("kick", kick_fn, gain=0.8)
#     mix.voice("bass", bass_fn, gain=0.3)
# mm.play("kick", mix.hit("kick", "gate") * 4)
```

## Next

- Effects routing: mix.bus() / mix.send() for reverb/delay
- Scenes: mm.scene() for pattern snapshot switching
- midiman: note-off scheduling, follow actions
- Phase 2 timing: sub-block sample splitting (~0ms jitter)
