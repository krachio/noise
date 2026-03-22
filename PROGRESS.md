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

## In progress

- **Unified Voice model**: Merge Voice + PolyVoice → single `Voice(count=N)`. Eliminate 22 poly/mono branch points.
- **Absorb Session into VoiceMixer**: `mix.tempo`, `mix.meter`, remove `mm` from user namespace.
- **Voice handles**: `kick = mix.voice("kick", kick_fn)` returns proxy — `kick.play(hit() * 4)`.
- **Phase-reset**: Rust `SetPatternFromZero` so fades/mods start from beat 1.

## Next

- **Pattern JIT** (same compilation model as DSP): Pattern IR → native automation node on audio thread. Pre-built shapes (hit, ramp, sine) ship compiled. Complex patterns JIT at play() time. Zero IPC for steady-state modulation.
- **Scenes**: `mix.save("verse")` / `mix.recall("chorus", bars=4)` — snapshot all patterns + controls + routing.
- **Music as Python repos**: Each song = a Python module. Load/hot-swap scenes by importing. Version control with git.
- **Live audio input**: `mix.input(channel=0)` — mic/instruments as graph source nodes.
- **Library restructure**: Merge midiman-frontend into krach. Single package.
- Rename crates: soundman-core → audio-engine, midiman → pattern-engine
