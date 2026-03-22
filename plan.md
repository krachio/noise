# Plan: Incremental voice addition + polyphonic voices

## Problem 1: Glitches when adding voices

Every `mix.voice()` triggers full `LoadGraph` → `recompile_and_send` → `SwapGraph` with
crossfade. Fresh FAUST nodes have reset internal state. The crossfade blends old (playing)
with new (cold), producing audible artifacts.

### Fix: Re-enable node reuse for incremental mutations + batch mutations

The stale-cache problem that caused us to disable reuse only affects `LoadGraph` (full
replacement). For `AddNode`/`Connect`, the shadow graph already has existing nodes — the
recompile can reuse them from the return channel because the retired graph has matching
node IDs/types.

### Commits

#### Commit 1: Re-enable node reuse for incremental mutations

Add `force_fresh: bool` to `recompile_and_send`. `LoadGraph` passes `true` (always fresh
— stale cache problem). `AddNode`/`Connect`/`RemoveNode`/`Disconnect` pass `false`
(reuse from return channel when available).

**Files:** `soundman-core/src/engine/mod.rs`

#### Commit 2: Add `GraphBatch` to soundman-core protocol

New `ClientMessage::GraphBatch { commands: Vec<ClientMessage> }`. `handle_message`
applies all mutations to the shadow graph, then calls `recompile_and_send` once.
Single SwapGraph for the entire batch.

**Files:** `soundman-core/src/protocol.rs`, `soundman-core/src/engine/mod.rs`

#### Commit 3: Session.add_voice + VoiceMixer incremental add

Python side: `Session.add_voice(name, type_id, controls, gain)` sends a `GraphBatch`
of AddNode + Connect + ExposeControl.

VoiceMixer: when adding a NEW voice (not replacing) and a graph is already loaded, use
`session.add_voice()` instead of `_rebuild()`. For `batch()`, collect deltas and send
as one GraphBatch.

**Files:** `midiman-frontend/session.py`, `noise-engine/src/ipc.rs`, `krach/_mixer.py`

---

## Problem 2: Polyphony

Currently each voice = one FAUST node = one freq + gate. Playing a chord requires
separate named voices. We want proper polyphonic voices at the graph level.

FAUST's `declare nvoices` is NOT supported by libfaust LLVM JIT. Polyphony must be
at the graph level: N instances of the same FAUST type, each with independent freq/gate.

### Commits

#### Commit 4: `mix.poly(name, source, voices=4, gain=0.5)`

New VoiceMixer method that creates N FAUST node instances:
- Nodes: `{name}_v0`, `{name}_v1`, ..., `{name}_v{N-1}` (same type_id)
- Each with its own gain node: `{name}_v0_g`, etc.
- All connected to DAC via fan-in
- Exposed: `{name}_v0_freq`, `{name}_v0_gate`, ..., `{name}_v0_gain`, etc.

Internally stores a `PolyVoice` dataclass:
```python
@dataclass(frozen=True)
class PolyVoice:
    type_id: str
    count: int
    gain: float
    controls: tuple[str, ...]
```

Uses `add_voice` (incremental) for each instance if graph already loaded.

**Files:** `krach/_mixer.py`

#### Commit 5: Voice allocator — `mix.note`/`mix.hit` on poly voices

When `mix.note("pad", freq)` is called on a poly voice, the allocator picks the next
instance (round-robin). Returns a pattern targeting `{name}_v{N}_freq`, `{name}_v{N}_gate`.
Multiple pitches on a poly voice play a chord: `mix.note("pad", 261.6, 329.6, 392.0)`.

```python
# Arpeggio — each note targets next voice instance (round-robin)
mix.play("pad_arp", mix.seq("pad", 261.6, 329.6, 392.0).over(2))

# Chord — all pitches simultaneously on poly instances
mix.play("chords", mix.note("pad", 261.6, 329.6, 392.0))
```

**Files:** `krach/_mixer.py`

---

## Verification

1. `cargo test --workspace` — all Rust tests pass
2. `cd krach && uv run pytest` — all Python tests pass
3. Manual test:
   ```python
   mix.voice("kick", "faust:kick", gain=0.9)
   mm.play("kick", mix.hit("kick", "gate") * 4)
   # Kick is playing...
   mix.voice("hat", "faust:hihat", gain=0.35)  # ← NO glitch, kick continues
   mm.play("hat", mix.hit("hat", "gate") * 16)
   ```
4. Polyphony test:
   ```python
   mix.poly("pad", pad_synth, voices=4, gain=0.3)
   mix.play("chords", (
       mix.note("pad", 261.6, 329.6, 392.0) +
       mix.note("pad", 293.7, 349.2, 440.0)
   ).over(4))
   ```
