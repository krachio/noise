# Krach — Master Roadmap

## Current State

Live coding audio system. ~755 tests, pyright strict, all Rust tests green.

`mix` is the single user object. Voice handles (`kick = mix.voice(...)`),
voice-free patterns (`hit()`, `note("C4")`, `seq()`), `/` path addressing,
effect routing (bus/send/wire), modulation as patterns, unified Voice model,
phase-reset, meter, pattern retrieval, engine logs to `~/.krach/engine.log`.

---

## Stage 1: Stability + Polish (do first — unblocks everything else)

### Known bugs
- [ ] **gain() not working in some sessions** — investigate with `~/.krach/engine.log` (exposed labels now logged at info). Reproduce, find root cause.
- [ ] **Fade phase alignment** — phase-reset (SetPatternFromZero) implemented in Rust, needs REPL testing to verify fades start from beat 1
- [ ] **Total gain overflow** — multiple voices at gain=1.0 clip CoreAudio. Add a master limiter or warn when total gain >1.0

### Copilot quality
- [ ] Copilot still generates `mix.voice("verb", ...)` instead of `mix.bus("verb", ...)` — context.md updated but may need stronger emphasis or examples
- [ ] Copilot generates good code overall — track recurring mistakes and fix in context.md

### Missing convenience
- [ ] `mix.master(value)` — master output gain (already supported in engine: `SetMasterGain`), not exposed in Python
- [ ] `mix.bpm` alias for `mix.tempo` — musicians say BPM not tempo
- [ ] `mix.voices` property should show handles not raw Voice objects
- [ ] `mix.buses` property — list active buses
- [ ] Pattern `__repr__` — currently shows IR tree, should show something human-readable

---

## Stage 2: Pattern JIT (the endgame architecture)

### Why
Every control change is IPC: Python → JSON → socket → Rust. Scales poorly for dense
modulation (10K+ messages/sec). Pattern JIT compiles patterns to native code on the
audio thread — same model as `@dsp` → FAUST for synthesis.

### Phase 1: Rust-side automation lanes
- [ ] `AutomationNode` in soundman-core — graph node that outputs control signals
- [ ] `AutoShape` enum: `Sine`, `Tri`, `Ramp`, `Pulse(duty)`, `Custom(Vec<f32>)`
- [ ] Evaluate per-sample: `value = lo + (hi - lo) * shape.eval(phase)`
- [ ] Phase advances with BPM clock (beat-synced)
- [ ] `SetAutomation` IPC command — send shape description once, engine evaluates forever
- [ ] `SetParam` for live knob input (rate, depth, lo, hi) — same as DSP controls
- [ ] Python: `mod_sine(400, 2000).over(4)` compiles to one `SetAutomation`, not 64 events
- [ ] Pre-built shapes (Pulse, Ramp, Sine, Tri) ship compiled — no JIT at runtime

### Phase 2: Note triggers as automation
- [ ] Note triggers: `Pulse` automation with sample-accurate onset timing
- [ ] `hit()` compiles to a pulse generator node, not discrete OSC events
- [ ] `note("C4")` compiles to freq-set + pulse automation
- [ ] `seq()` compiles to a sequencer automation node (wavetable of freq values + pulse pattern)

### Phase 3: Pattern algebra compiles to automation graphs
- [ ] Pattern tree (Cat, Stack, Slow, Every, Euclid, Degrade) → Rust automation graph
- [ ] The pattern algebra is the symbolic authoring layer; compiled form runs at audio rate
- [ ] `.every(4, lambda p: p.reverse())` compiled to sample-accurate automation
- [ ] Envelope followers, sidechain — automation reading from other signals (feedback paths)

---

## Stage 3: Scenes + Music-as-Code

### Scenes / Snapshots
- [ ] `mix.save("verse")` — snapshot: all voice configs, patterns, control values, routing
- [ ] `mix.recall("chorus")` — instant switch to saved state
- [ ] `mix.recall("chorus", bars=4)` — crossfade between scenes over N bars
- [ ] Scenes as Python dicts — `json.dumps(scene)` / `json.loads(scene)`
- [ ] Scene diffing: `mix.diff("verse", "chorus")` shows what changes

### Music as Python repos
- [ ] Songs as Python modules: `from songs.dubstep import verse`
- [ ] `verse.activate(mix)` — applies voices, patterns, routing to the mixer
- [ ] Hot-swap: `importlib.reload(verse); verse.activate(mix)`
- [ ] Version control music with git — branches = arrangements
- [ ] Complex synths, step sequencers, arpeggiators = Python classes on top of DSL
- [ ] Collaborative: multiple people edit different modules in same repo
- [ ] `mix.load("songs/dubstep/verse.py")` — file-based scene loading

---

## Stage 4: Live Audio + Hardware

### Live audio input
- [ ] `mix.input(channel=0)` — system audio input as graph source node
- [ ] ADC node type in soundman-core (reads from CoreAudio input buffer)
- [ ] Wire mic to effects: `mic.wire(vocoder, port="modulator")`
- [ ] Guitar/instrument input with FAUST effects chains
- [ ] Looper: record live input into a buffer, play back as a voice

### MIDI hardware integration
- [ ] MIDI controller input → `mix.set()` / `mix.gain()` (knobs/faders)
- [ ] MIDI note input → `mix.play()` (keyboard)
- [ ] MIDI clock sync (external clock master)
- [ ] Map MIDI CC to any `/` path: `mix.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)`

---

## Stage 5: Infrastructure

### Mini-notation parser
- [ ] `p("x . x . x . . x")` — percussion shorthand
- [ ] `p("C4 E4 G4 ~ C5").over(2)` — melodic shorthand
- [ ] Compiles to existing Pattern IR
- [ ] Support `<>` alternation, `[]` grouping, `*` repeat

### Library restructure
- [ ] Merge midiman-frontend into krach as `krach.patterns`
- [ ] Single Python package: `krach` (patterns, voices, control, session, REPL)
- [ ] Rename Rust crates: soundman-core → audio-engine, midiman → pattern-engine
- [ ] noise-engine → krach-engine (or just `krach`)
- [ ] Publish to PyPI / crates.io

### Replace OSC wire format with typed Control IR
- [ ] New `Control(label, value)` IR value type (replaces `Osc("/soundman/set", ...)`)
- [ ] Eliminates string parsing on the hot path
- [ ] Both Python IR and Rust event system
- [ ] Backward compatible: engine accepts both during transition

---

## Priority Order

1. **Stage 1** — Fix bugs, polish UX. Small, high-impact. ~1 session.
2. **Stage 2 Phase 1** — Automation lanes. Core architecture. ~2-3 sessions.
3. **Stage 3 Scenes** — Enables music-as-code workflow. ~1 session.
4. **Stage 2 Phase 2+3** — Full pattern JIT. ~2-3 sessions.
5. **Stage 4** — Live audio + MIDI. ~2 sessions.
6. **Stage 5** — Infrastructure. Ongoing.
