# Krach — Master Implementation Plan

## Current State

817 tests (257 krach, 143 midiman-frontend, 68 faust-dsl, 349 Rust). Pyright strict clean.
Single user object `mix` with voice handles, voice-free patterns, `/` path addressing,
effect routing, native automation lanes (block-rate on audio thread), unified Voice model,
phase-reset, meter, pattern retrieval, scenes, mix.load().
Engine logs to `~/.krach/engine.log`.

### Completed
- ✅ Stage 1: Stability (master gain, bpm alias, voice/bus handles, copilot context)
- ✅ Stage 2: Automation lanes (AutoShape, GraphSwapper integration, IPC, Python mod/fade)
- ✅ Stage 3: Scenes + music-as-code (save/recall, mix.load())
- ✅ Stage 5.1: Mini-notation parser (`p("x . x . x . . x")`)
- ✅ Stage 5.3: Typed Control IR (Control(label, value) replaces Osc convention)

---

## Stage 1: Stability + Polish

Small, high-impact fixes. ~1 session.

### 1.1 Fix gain bug
**Symptom:** `mix.gain("stab", 0.0)` doesn't reduce volume in some sessions.
**Debug:** Start with `RUST_LOG=info`, reproduce, check `~/.krach/engine.log` for:
- `graph compiled — exposed: [...]` — verify the label exists
- `set_control: unknown label '...'` — means label mismatch
**Root cause candidates:**
- `add_voice()` incremental path was using `_` labels (fixed in `d5bfc26`) — restart needed
- Graph rebuild race: 3 sequential `send()` calls = 3 `LoadGraph` commands; last one wins but intermediate ones may have incomplete exposed_controls
**Fix if race:** Batch send() calls internally — accumulate sends, one rebuild at end.
**Files:** `krach/_mixer.py` (send batching), investigation in REPL with log tailing

### 1.2 Master gain / limiter
**Problem:** Multiple voices at gain=1.0 clip CoreAudio (sum > 1.0).
**Fix:** Expose `mix.master(value)` that calls `session.master_gain(value)`.
Session already has `master_gain()` (sends `SetMasterGain`). VoiceMixer just needs a property.
Also: set a safe default master gain on startup (0.7 or compute from voice count).
```python
@property
def master(self) -> float: return self._master_gain
@master.setter
def master(self, value: float):
    self._master_gain = value
    self._session.master_gain(value)
```
**Files:** `krach/_mixer.py` (property + startup default), `krach/__init__.py` (set on startup)

### 1.3 Convenience properties
- `mix.bpm` alias for `mix.tempo` — add `bpm` property delegating to `tempo`
- `mix.voices` — return `dict[str, VoiceHandle]` not raw `Voice` objects
- `mix.buses` — return `dict[str, BusHandle]`
- `VoiceHandle.__repr__` / `BusHandle.__repr__` — already done, verify they're useful
**Files:** `krach/_mixer.py`

### 1.4 Fade phase verification
**Status:** `SetPatternFromZero` implemented in Rust + Python. `fade()` and `mod()` use `from_zero=True`.
**Action:** Test in REPL — verify `mix.fade("bass/cutoff", 200, bars=4)` starts ramping from current value, not from mid-cycle.
**If still broken:** Debug with engine log + check `play_from_zero` is actually sending `SetPatternFromZero` command.

### 1.5 Copilot context improvements
- Stronger `bus()` vs `voice()` distinction (already updated)
- Add `seq()` examples showing mixed `note()` + pitches
- Add common patterns section: "4-on-the-floor", "offbeat hat", "bass line"
**Files:** `krach/context.md`

---

## Stage 2: Pattern JIT — Automation Lanes

The core architectural evolution. Patterns compile to audio-thread automation instead of IPC events.

### Architecture Decision: Block-rate automation via GraphSwapper

**Not** a new node type in the graph (avoids graph topology changes for modulation).
Instead: automation state lives in `GraphSwapper`, evaluated at block boundaries.

```rust
// In GraphSwapper:
struct Automation {
    node_id: String,
    param: String,
    shape: AutoShape,
    lo: f32,
    hi: f32,
    period_samples: usize,  // one full cycle of the shape
    phase: usize,           // current sample position within period
    active: bool,
}

enum AutoShape {
    Sine,
    Tri,
    Ramp,
    RampDown,
    Square,
    Exp,
    Pulse { duty: f32 },           // for note triggers
    Custom { table: Vec<f32> },    // wavetable for complex shapes
}
```

On each `process()` call, `GraphSwapper` iterates active automations, evaluates the
shape at the current phase, and calls `graph.set_param(node_id, param, value)` on the
active graph. Phase advances by `block_size` samples each call.

**Why block-rate not sample-rate:** `set_param` goes through the node's smoothing
(GainNode has exponential smoothing at 0.02/sample). Calling it once per block (256
samples) is sufficient — the node interpolates between values. This is ~172 calls/sec
at 44100Hz/256 block, vs 64 pattern events over 4 bars (~8/sec currently). 20x improvement
with zero IPC overhead.

### 2.1 AutoShape + Automation struct (Rust)
**New file:** `soundman-core/src/automation.rs`
```rust
pub enum AutoShape { Sine, Tri, Ramp, RampDown, Square, Exp, Pulse { duty: f32 }, Custom { table: Vec<f32> } }

pub struct Automation {
    pub node_id: String,
    pub param: String,
    pub shape: AutoShape,
    pub lo: f32,
    pub hi: f32,
    pub period_samples: usize,
    pub phase: usize,
    pub active: bool,
    pub one_shot: bool,  // true for fades (stop after one period)
}

impl Automation {
    pub fn eval(&self) -> f32 {
        let t = self.phase as f32 / self.period_samples as f32;
        let normalized = self.shape.eval(t);  // 0..1
        self.lo + (self.hi - self.lo) * normalized
    }
    pub fn advance(&mut self, samples: usize) {
        self.phase += samples;
        if self.phase >= self.period_samples {
            if self.one_shot {
                self.phase = self.period_samples - 1;  // hold at end
                self.active = false;
            } else {
                self.phase %= self.period_samples;  // loop
            }
        }
    }
}

impl AutoShape {
    pub fn eval(&self, t: f32) -> f32 { /* sine/tri/ramp/etc */ }
}
```
**Tests:** Unit tests for each shape at key t values (0, 0.25, 0.5, 0.75, 1.0).
**Files:** `soundman-core/src/automation.rs`, `soundman-core/src/lib.rs` (pub mod)

### 2.2 Automation in GraphSwapper (Rust)
**File:** `soundman-core/src/swap/mod.rs`
Add `automations: Vec<Automation>` to `GraphSwapper`.
In `process()`, after processing the graph, evaluate all active automations:
```rust
for auto in &mut self.automations {
    if !auto.active { continue; }
    let value = auto.eval();
    if let Some(graph) = &mut self.active {
        let _ = graph.set_param(&auto.node_id, &auto.param, value);
    }
    auto.advance(output.len());
}
```
New `Command` variant:
```rust
Command::SetAutomation { id: String, automation: Automation }
Command::ClearAutomation { id: String }
```
The `id` is a unique key (e.g., `"bass/cutoff"`) so multiple automations on different
params coexist, and re-sending replaces the existing one.
**Tests:** `test_automation_modulates_gain`, `test_automation_one_shot_holds`, `test_automation_replaces`
**Files:** `soundman-core/src/swap/mod.rs`, `soundman-core/src/swap/command.rs`

### 2.3 SetAutomation IPC (Rust)
**soundman-core protocol:** Add `ClientMessage::SetAutomation` and `ClearAutomation` variants.
**noise-engine IPC:** Add `{"type": "set_automation", ...}` JSON handler that constructs the
`Automation` struct and sends it as a `Command` to the audio thread.
**Serialization:** Shape as string (`"sine"`, `"tri"`, etc.), lo/hi/period as f32/f32/f64.
For `Custom`: table as `Vec<f32>` (JSON array).
**Files:** `soundman-core/src/protocol.rs`, `noise-engine/src/ipc.rs`, `noise-engine/src/main.rs`

### 2.4 Python: SetAutomation in Session
**midiman-frontend session.py:**
```python
def set_automation(self, label: str, shape: str, lo: float, hi: float,
                   period_beats: float, one_shot: bool = False) -> None:
    period_secs = period_beats * 60.0 / self._tempo
    # Engine computes period_samples from period_secs * sample_rate
    self._send_json({"type": "set_automation", "id": label, "shape": shape,
                     "lo": lo, "hi": hi, "period_secs": period_secs,
                     "one_shot": one_shot})

def clear_automation(self, label: str) -> None:
    self._send_json({"type": "clear_automation", "id": label})
```
**Files:** `midiman-frontend/session.py`

### 2.5 Python: VoiceMixer uses automation for mod/fade
**krach/_mixer.py:**
```python
def mod(self, path: str, pattern_or_shape: Pattern | str, ...) -> None:
    if isinstance(pattern_or_shape, str):
        # Direct automation: mod("bass/cutoff", "sine", lo=400, hi=2000, bars=4)
        label = self._resolve_path(path)
        self._session.set_automation(label, pattern_or_shape, lo, hi,
                                      period_beats=bars * self._session._beats_per_cycle)
    else:
        # Pattern-based (legacy): play(path, pattern.over(bars))
        self.play(path, pattern_or_shape.over(bars), from_zero=True)

def fade(self, path: str, target: float, bars: int = 4, ...) -> None:
    label = self._resolve_path(path)
    current = self._ctrl_values.get(path, 0.0)
    self._session.set_automation(label, "ramp", lo=current, hi=target,
                                  period_beats=bars * self._session._beats_per_cycle,
                                  one_shot=True)
    self._ctrl_values[path] = target
```
Mod shapes (`mod_sine`, `mod_tri`, etc.) can still return Patterns for composition,
but when used with `mod()` directly, they compile to native automation.
**Files:** `krach/_mixer.py`

### 2.6 Note triggers as Pulse automation (future)
After automation lanes work for continuous modulation:
- `hit()` pattern → `Pulse` automation (duty cycle = gate-on duration / period)
- `note("C4")` → freq `SetParam` + `Pulse` gate automation
- `seq("A2", "D3", None, "E2")` → `Custom` wavetable for freq + `Pulse` pattern for gate
This replaces all OSC events with zero-IPC automation. Deferred to later.

---

## Stage 3: Scenes + Music-as-Code

### 3.1 Scene snapshots
```python
@dataclass
class Scene:
    voices: dict[str, VoiceConfig]   # name → (source_id, gain, count, init)
    buses: dict[str, BusConfig]
    sends: dict[tuple[str,str], float]
    wires: dict[tuple[str,str], str]
    patterns: dict[str, Pattern]     # slot → unbound pattern
    ctrl_values: dict[str, float]    # path → value
    tempo: float
    meter: float
```

`mix.save("verse")` captures current state into `self._scenes["verse"]`.
`mix.recall("chorus")` applies the saved state: rebuilds graph, replays patterns, restores controls.
`mix.recall("chorus", bars=4)` — cross-fades: old patterns fade out, new patterns fade in.

**Files:** `krach/_mixer.py` (Scene dataclass, save/recall methods)

### 3.2 Scene serialization
```python
mix.export("verse", "scenes/verse.json")  # save to file
mix.load("scenes/verse.json")             # load from file
```
JSON or TOML serialization. Patterns serialize via `ir_to_dict()`.

### 3.3 Music as Python modules
```python
# songs/dubstep/verse.py
def activate(mix):
    with mix.batch():
        mix.voice("drums/kick", "faust:kick", gain=0.8)
        mix.voice("bass", "faust:sub", gain=0.7)
    mix.play("drums/kick", hit() * 4)
    mix.play("bass", seq("A1", "D2", None, "E1").over(2))
    mix.tempo = 140
```
```python
# In REPL:
from songs.dubstep import verse
verse.activate(mix)
# Later:
importlib.reload(verse)
verse.activate(mix)
```
This works TODAY with no code changes — it's just a Python function that calls mix methods.
The only addition is convenience: `mix.load("songs/dubstep/verse.py")` which `exec()`s the file
with `mix` in the namespace.

**Files:** `krach/_mixer.py` (load method), example songs directory

---

## Stage 4: Live Audio + Hardware

### 4.1 ADC input node
New `AdcNode` in soundman-core: reads from the system audio input buffer (CoreAudio).
Needs: shared buffer between CoreAudio input callback and the DspNode. Use a lock-free
ring buffer (same `rtrb` crate already in the project).
```rust
pub struct AdcNode {
    consumer: Consumer<f32>,  // reads from CoreAudio input callback
}
impl DspNode for AdcNode {
    fn process(&mut self, _inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if let Some(out) = outputs.first_mut() {
            for s in out.iter_mut() {
                *s = self.consumer.pop().unwrap_or(0.0);
            }
        }
    }
}
```
Python: `mix.input(channel=0)` returns a handle. Wire like any voice.
**Files:** `soundman-core/src/nodes/adc.rs`, `soundman-core/src/output/cpal_backend.rs` (input stream)

### 4.2 MIDI controller input
MIDI input already partially exists (`midiman` has MIDI output). Add MIDI input:
- Read MIDI CC messages from a port
- Map CC → `/` path: `mix.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)`
- Map generates `SetControl` commands from CC values
**Files:** `noise-engine/src/main.rs` (MIDI input polling), `krach/_mixer.py` (midi_map)

### 4.3 Looper (future)
Record live input into a buffer, play back as a pattern-triggered voice.
Complex — deferred.

---

## Stage 5: Infrastructure

### 5.1 Mini-notation parser
```python
p("x . x . x . . x")           # x=hit, .=rest
p("C4 E4 G4 ~ C5").over(2)     # ~=rest, note names
p("[C4 E4] G4 B4")              # [] = simultaneous (Stack)
p("C4*2 E4 G4")                 # *N = repeat
p("<C4 E4> G4")                 # <> = alternate each cycle
```
Returns a `Pattern`. Pure Python, no engine changes.
**Files:** New `krach/src/krach/_mininotation.py`, tests

### 5.2 Library restructure
- Move `midiman-frontend/src/midiman_frontend/` → `krach/src/krach/patterns/`
- Update all imports
- Single `pyproject.toml` for krach
- Rename Rust crates (zero-functional-change PR)

### 5.3 Replace OSC wire format
New `Control(label, value)` IR value type alongside `Note`, `Cc`, `Osc`.
- Python IR: new `Control` dataclass
- Rust event: new `Value::Control { label, value }` variant
- Engine dispatch: direct `SetControl` from `Value::Control`, no string parsing
- Backward compatible: keep `Osc` support during transition

---

## Implementation Order

```
Stage 1.1  Fix gain bug                    (investigate + fix)
Stage 1.2  Master gain                     (tiny: 1 property + startup default)
Stage 1.3  Convenience properties          (tiny: bpm alias, voices/buses dicts)
Stage 1.4  Verify fade phase-reset         (REPL testing)
Stage 1.5  Copilot context                 (doc update)
─────────────────────────────────────────────────────────────
Stage 2.1  AutoShape + Automation struct   (Rust: new file, unit tests)
Stage 2.2  Automation in GraphSwapper      (Rust: integrate, Command variants)
Stage 2.3  SetAutomation IPC              (Rust: protocol + engine dispatch)
Stage 2.4  Session.set_automation         (Python: IPC client)
Stage 2.5  VoiceMixer mod/fade → automation (Python: use native automation)
─────────────────────────────────────────────────────────────
Stage 3.1  Scene snapshots                (Python: save/recall)
Stage 3.2  Scene serialization            (Python: export/load)
Stage 3.3  Music as Python modules        (Python: mix.load())
─────────────────────────────────────────────────────────────
Stage 4.1  ADC input node                 (Rust: new node + CoreAudio input)
Stage 4.2  MIDI controller input          (Rust + Python: CC mapping)
─────────────────────────────────────────────────────────────
Stage 5.1  Mini-notation parser           (Python: new module)
Stage 5.2  Library restructure            (refactor: move files)
Stage 5.3  Typed Control IR               (Rust + Python: new value type)
```

## Verification

After each stage:
```
cd krach && uv run pyright && uv run pytest -x -q
cd midiman-frontend && uv run pyright && uv run pytest -x -q
cargo test --workspace
```

After Stage 2: REPL test with `tail -f ~/.krach/engine.log`:
```python
mix.voice("bass", "faust:bass", gain=0.5)
mix.play("bass", seq("A2", "D3", None, "E2").over(2))
mix.mod("bass/cutoff", "sine", lo=200, hi=2000, bars=4)  # should be ONE command, not 64 events
# Log should show: set_automation bass/cutoff sine 200-2000 period=...
# No flood of set_control messages
```

---

## Witnessed Failures (to be fixed)

### Audio silence/glitch when adding voices to a running graph
**Symptom:** Adding a new voice while others are playing causes a brief silence or
audible cycle suppression. Existing voices cut out momentarily during the graph swap.

**Root cause:** Every topology change (voice/bus/send add) triggers a full graph
recompile + `SwapGraph` with crossfade. If the retired graph hasn't been returned
via the lock-free channel yet, `cached_graph = None` and node reuse fails — all
nodes are fresh (phase=0, filter state reset). The crossfade blends old (correct
state) with new (cold state), producing audible artifacts.

**Aggravating factors:**
- FAUST JIT compilation blocks the `_wait_for_type()` poll loop (~50-200ms)
- Multiple sequential `send()` calls trigger multiple rapid graph rebuilds
- The crossfade is 250ms at 120 BPM — if JIT takes longer, the swap is queued

**When to fix:** After Stage 2 automation lanes reduce the frequency of graph swaps
(mod/fade no longer trigger swaps). The remaining swaps (voice/bus add) need either:
- A faster incremental mutation path that avoids full recompile
- Double-buffered graph with lock-free node addition
- Longer crossfade + guaranteed node reuse via synchronous return channel drain

### gain() not working in some sessions
**Symptom:** `mix.gain("stab", 0.0)` doesn't reduce volume.
**Status:** Likely fixed by `add_voice()` underscore→slash label fix (`d5bfc26`).
Needs verification in fresh session with `~/.krach/engine.log` monitoring.
Log now shows exposed labels at info level — mismatch will be visible.
