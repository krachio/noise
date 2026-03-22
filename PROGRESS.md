# Progress

## Current state

Live coding audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine — graph runtime with node reuse + return channel, gain smoothing, fan-in with NaN isolation, output clamping, registry versioning, pre-computed connection map, live control tracking, crossfade trigger forwarding, RT-safe crossfade-during-crossfade, SmallVec hot-path refs, fresh-only control restore — 121 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 14 tests.
- **midiman** (Rust lib): Pattern sequencer — Freeze compound atoms, single-loop engine with min-heap, slot index (no string clone on hot path), SetBpm no-op guard, BPM NaN/Inf validation — 122 tests.
- **noise-engine** (Rust binary): Unified binary — merges midiman + soundman-core + soundman-faust. Single process, direct event dispatch (no OSC), BPM-relative crossfade (1/2 beat), dual-protocol IPC (pattern + graph commands on one Unix socket), note-dur panic guard — 24 tests.
- **midiman-frontend** (Python 3.13): Pattern DSL + Graph IR + unified Session. Pattern.fast() (was scale), over()/fast() inf/nan guards — 133 tests.
- **faust-dsl** (Python 3.13): Python → Faust transpiler — 68 tests.
- **krach** (Python 3.13): Live coding REPL — VoiceMixer with @dsp, note(), hit(), seq(), poly(), batch(), fade(), mute/unmute/solo, mix.play(), mtof/ftom, note constants (C0-B8), copilot — 112 tests.

### Removed

- **soundman** (Rust binary): Replaced by noise-engine. OSC control input eliminated.
- **soundman-frontend** (Python): OSC client. Graph/Session merged into midiman-frontend.

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

mix.play("kick", mix.hit("kick", "gate") * 4)
mix.play("bass", mix.seq("bass", mtof(A2), mtof(D3), None, mtof(E2)).over(2))
mix.fade("bass", target=0.15, bars=8)
```

## Recent fixes

- **Ergonomics pass**: Unified note() API (replaces step/chord), mtof/ftom + note constants, scale()→fast(), mix.play() delegation.
- **Live performance**: mute()/unmute()/solo(), socket timeout, fade cancel, batch rollback on exception.
- **Polyphonic voices**: poly(), round-robin allocator in VoiceMixer.
- **RT-safe crossfade-during-crossfade**: begin_swap() during active crossfade moves old retiring graph to retired_ready instead of dropping on audio thread.
- **BPM validation**: NaN, Inf, zero, negative BPM all guarded in midiman + noise-engine.

## Next

- Follow-up PR: rename soundman-core → audio-engine, soundman-faust → audio-faust, midiman → pattern-engine, midiman-frontend → noise-client
- Effects routing: mix.bus() / mix.send() for reverb/delay
- Mini-notation parser: p("bd sd ~ bd") shorthand
- Scenes: mm.scene() for pattern snapshot switching
