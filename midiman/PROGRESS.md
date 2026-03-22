# Progress

## Current state

Architecture fully rewritten from two-thread scheduler to single-loop engine with min-heap.

### Implemented
- **Time** (`time.rs`): Rational arithmetic (i64/u64), Arc, `split_cycles`
- **Event** (`event.rs`): `Event<V>` with whole/part, `Value` enum (Note, Cc, Osc)
- **Pattern engine** (`pattern/`): Arena-indexed `CompiledPattern`, `query()` for all combinators
- **IR compiler** (`ir/`): `IrNode` serde-tagged enum, validation, `compile()`
- **Engine** (`engine.rs`): Single-loop `Engine` with `BinaryHeap<Reverse<TimedEvent>>` — correct global fire_at ordering across all slots. `drain(horizon)` pre-dispatches OSC events up to 100ms ahead.
- **Output sinks** (`output/`): MIDI via midir; OSC via rosc sends bundles with NTP `fire_at` time tags (soundman queues and fires at correct audio block).
- **IPC server** (`ipc/`): Unix domain socket, JSON protocol — commands sent as `EngineCommand` via channel (no shared mutex)
- **Binary** (`main.rs`): drain commands → fill heap → drain(now+LOOKAHEAD) → sleep 1ms

### Sample-accurate OSC scheduling
OSC events sent as `OscBundle` with `fire_at` encoded as NTP time tag. soundman receives
early (~100ms ahead), queues in `BinaryHeap<Reverse<Timed>>`, fires at the audio block
containing `fire_at`. Error: ±5.8ms (one 256-sample block @ 44100Hz) vs previously 1–7ms late.

### Stats
- 141 tests passing
- Rust edition 2024, strict clippy, `unsafe_code = "forbid"`

### Additional features
- **Phase reset** (`SetPatternFromZero`): start pattern from cycle zero on next set
- **Meter** (`SetBeatsPerCycle`): configure beats per cycle independently of BPM

## Next

- Real-time thread priority
- Phase 2: sub-block sample splitting (~0ms jitter)
- MIDI clock sync output
