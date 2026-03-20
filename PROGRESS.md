# Progress

## Current state

Live coding audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine — graph runtime with node reuse + return channel, gain smoothing, fan-in with NaN isolation, output clamping, registry versioning — 114 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 14 tests.
- **soundman** (Rust binary): soundman-core + soundman-faust. Watches `~/.krach/dsp/`, OSC on port 9001.
- **midiman** (Rust): Pattern sequencer — AtomGroup compound atoms, single-loop engine with min-heap, sample-accurate OSC — 116 tests.
- **midiman-frontend** (Python 3.13): Pattern DSL with AtomGroup, limit_denominator(256) — 122 tests.
- **soundman-frontend** (Python 3.13): OSC client — `Graph`, `SoundmanSession` — 28 tests.
- **faust-dsl** (Python 3.13): Python → Faust transpiler — 68 tests.
- **krach** (Python 3.13): Live coding REPL — VoiceMixer with @dsp, batch(), fade(), copilot — 48 tests.

## Usage

```bash
./bin/krach
```

```python
@dsp
def acid_bass() -> Signal:
    freq = control("freq", 55.0, 20.0, 800.0)
    gate = control("gate", 0.0, 0.0, 1.0)
    return lowpass(saw(freq), 800.0) * adsr(0.005, 0.15, 0.3, 0.08, gate) * 0.55

with mix.batch():
    mix.voice("kick", kick_fn, gain=0.8)
    mix.voice("bass", acid_bass, gain=0.3)

mm.play("kick", mix.hit("kick", "gate") * 4)
mm.play("bass", (mix.step("bass", 55) + rest() + mix.step("bass", 73)).over(2))
mix.fade("bass", target=0.15, bars=8)
```

## Next

- Unified binary: merge midiman + soundman → noise-engine (eliminate OSC overhead)
- Effects routing: mix.bus() / mix.send() for reverb/delay
- Extended pattern IR: Choose, Seq, Map, Interpolate
- Polyphony: FAUST nvoices + voice allocator
- Scenes: mm.scene() for pattern snapshot switching
