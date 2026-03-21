# Progress

## Current state

Live coding audio system — monorepo at `krachio/noise`, Cargo workspace.

- **soundman-core** (Rust): Audio engine — graph runtime with node reuse + return channel, gain smoothing, fan-in with NaN isolation, output clamping, registry versioning, pre-computed connection map, live control tracking, crossfade trigger forwarding, additive-swap detection, fresh-only control restore — 120 tests.
- **soundman-faust** (Rust): FAUST LLVM JIT plugin — hot reload of `.dsp` files — 14 tests.
- **midiman** (Rust lib): Pattern sequencer — Freeze compound atoms, single-loop engine with min-heap, slot index (no string clone on hot path), SetBpm no-op guard — 119 tests.
- **noise-engine** (Rust binary): Unified binary — merges midiman + soundman-core + soundman-faust. Single process, direct event dispatch (no OSC), BPM-relative crossfade (1/4 beat), dual-protocol IPC (pattern + graph commands on one Unix socket) — 22 tests.
- **midiman-frontend** (Python 3.13): Pattern DSL + Graph IR + unified Session (patterns, graph, controls) — 122 tests.
- **faust-dsl** (Python 3.13): Python → Faust transpiler — 68 tests.
- **krach** (Python 3.13): Live coding REPL — VoiceMixer with @dsp, batch(), fade(), copilot. Starts one binary (noise-engine), one socket — 48 tests.

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

mm.play("kick", mix.hit("kick", "gate") * 4)
mm.play("bass", (mix.step("bass", 55) + rest() + mix.step("bass", 73)).over(2))
mix.fade("bass", target=0.15, bars=8)
```

## Recent fixes

- **Fresh-only control restore**: compile_with_reuse returns fresh node IDs. Control values only applied to fresh nodes — reused nodes keep undisturbed DSP state (no spurious ADSR triggers).
- **Instant swap for additive changes**: Adding voices uses 1-sample crossfade (instant). Node reuse preserves DSP state. BPM-relative crossfade only for breaking changes.
- **Crossfade trigger forwarding**: SetParam reaches both active AND retiring graphs during crossfade.
- **Live control tracking**: EngineController records last-set value for each exposed control.
- **SetBpm no-op guard**: Same-BPM set no longer nukes the event heap.

## Next

- Follow-up PR: rename soundman-core → audio-engine, soundman-faust → audio-faust, midiman → pattern-engine, midiman-frontend → noise-client (zero functional changes, clean git-blame)
- Effects routing: mix.bus() / mix.send() for reverb/delay
- Extended pattern IR: Choose, Seq, Map, Interpolate
- Polyphony: FAUST nvoices + voice allocator
- Scenes: mm.scene() for pattern snapshot switching
- Profile collect() in DspGraph::process() — may be a non-issue with small-vec optimization
