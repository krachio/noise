# Progress

## Current state

Audio engine with node reuse — 160 tests, 0 unsafe, clippy clean.

### Key features
- **Graph compiler** with `compile_with_reuse()` — reuses node instances across graph swaps, preserving ADSR phase, filter memory, reverb tails for unchanged voices. `LoadGraph` uses node reuse (not fresh-only).
- **Return channel** — retired graphs sent from audio thread to control thread via SPSC ring buffer (RT-safe: no dealloc on audio path)
- **Registry versioning** — per-type version counter; nodes only reused when type_id AND version match (prevents stale code after hot-reload)
- **Fan-in mixing** with per-source NaN isolation — diverged IIR filter silences only itself
- **Output clamping** with NaN→0 — prevents CoreAudio stream death
- **Built-in nodes**: oscillator, dac, gain (GainNode has virgin snap — immediate gain on first activation)
- **Lock-free audio**: EngineController + AudioProcessor split via rtrb SPSC
- **GraphSwapper** with linear crossfade, pre-allocated buffers
- **OSC control**: Float/Double/Int accepted for numeric args
- **Automation lanes**: block-rate AutoShape modulation in GraphSwapper (sine, tri, ramp, etc.)
- **ADC input node**: `AdcNode` reads CoreAudio input via lock-free ring buffer
- **MIDI CC input**: CC messages mapped to SetControl commands

## Next

- Incremental graph mutations (AddNode/Connect without full recompile)
- Sub-block sample splitting for ~0ms scheduling jitter
