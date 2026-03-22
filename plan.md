# Krach — Roadmap

## Current State

Live coding audio system. 714+ tests, pyright strict clean.

One user object (`mix`), voice handles, voice-free patterns, `/` path addressing,
effect routing (bus/send/wire), beat-synced modulation as patterns, unified Voice
model (no poly/mono split), phase-reset, meter support, pattern retrieval.

## Next: Pattern JIT

Same compilation model as `@dsp` → FAUST. Patterns compile to native automation
nodes on the audio thread. Zero IPC for steady-state modulation.

```
@dsp function:  Python traces → FAUST IR → JIT compile → native DspNode
Pattern:        Python traces → Pattern IR → compile   → native AutomationNode
```

### Phase 1: Rust-side automation lanes
- [ ] `AutomationNode` in soundman-core — graph node that outputs control signals
- [ ] `AutoShape` enum: Sine, Tri, Ramp, Pulse(duty), Custom(Vec<f32>) wavetable
- [ ] Evaluate per-sample: `value = lo + (hi - lo) * shape.eval(phase)`
- [ ] `SetAutomation` IPC command — send shape once, engine evaluates forever
- [ ] Python: `mod_sine(400, 2000).over(4)` → one `SetAutomation`, not 64 events
- [ ] Pre-built shapes (Pulse, Ramp) ship compiled — no JIT at runtime
- [ ] Note triggers: Pulse automation with sample-accurate onset timing

### Phase 2: Pattern algebra compiles to automation graphs
- [ ] Pattern tree (Cat, Stack, Slow, Every, Euclid) → Rust automation graph
- [ ] `.every(4, lambda p: p.reverse())` compiled to sample-accurate automation
- [ ] Envelope followers, sidechain — signals reading from other signals

## Scenes / Snapshots
- [ ] `mix.save("verse")` — snapshot all patterns + controls + routing
- [ ] `mix.recall("chorus", bars=4)` — crossfade between scenes
- [ ] Scenes as Python dicts — serializable, storable, importable

## Music as Python Repos
- [ ] Songs as Python modules: `from songs.dubstep import verse; verse.activate(mix)`
- [ ] Hot-swap via `importlib.reload(verse); verse.activate(mix)`
- [ ] Version control music with git
- [ ] Complex synths, step sequencers, arps as Python abstractions on top of DSL

## Live Audio Input
- [ ] `mix.input(channel=0)` — system audio input as graph source node
- [ ] Wire to effects, vocoders, sidechain compressors
- [ ] Need ADC node type in soundman-core

## Mini-notation Parser
- [ ] `p("x . x . x . . x")` — shorthand for percussion patterns
- [ ] `p("A2 A2 ~ D3 E3 ~ A2 C3").over(2)` — melodic shorthand
- [ ] Compiles to Pattern IR

## Library Restructure
- [ ] Merge midiman-frontend into krach as `krach.patterns`
- [ ] Single package: `krach` (patterns, voices, control, session, REPL)
- [ ] Rename Rust crates: soundman-core → audio-engine, midiman → pattern-engine

## Known Issues
- [ ] **gain() not working in some sessions** — `mix.gain("stab", 0.0)` and `mix.set("stab/gain", 0.0)` don't reduce volume. Suspected: exposed_controls label mismatch after graph rebuild. Needs investigation with engine WARN logs enabled (`RUST_LOG=warn`). CoreAudio can crash if total voice gain >1.0.
- [ ] Fade starts at arbitrary cycle position (phase-reset implemented but needs testing in REPL)
- [ ] Copilot sometimes generates `seq(note("A1"), ...)` instead of `seq("A1", ...)` — validation added but copilot context should be clearer
