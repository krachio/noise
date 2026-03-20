# Progress

## Current state

Audio engine with node reuse — 112 tests, 0 unsafe, clippy clean.

### Key features
- **Graph compiler** with `compile_with_reuse()` — reuses node instances across graph swaps, preserving ADSR phase, filter memory, reverb tails for unchanged voices
- **Return channel** — retired graphs sent from audio thread to control thread via SPSC ring buffer (RT-safe: no dealloc on audio path)
- **Registry versioning** — per-type version counter; nodes only reused when type_id AND version match (prevents stale code after hot-reload)
- **Fan-in mixing** with per-source NaN isolation — diverged IIR filter silences only itself
- **Output clamping** with NaN→0 — prevents CoreAudio stream death
- **Built-in nodes**: oscillator, dac, gain
- **Lock-free audio**: EngineController + AudioProcessor split via rtrb SPSC
- **GraphSwapper** with linear crossfade, pre-allocated buffers
- **OSC control**: Float/Double/Int accepted for numeric args

## Next

- Effects routing: send/return buses in the graph
- Incremental graph mutations (AddNode/Connect without full recompile)
- Sub-block sample splitting for ~0ms scheduling jitter
