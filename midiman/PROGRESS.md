# Progress

## Current state

All 6 phases of the architecture plan (`magical-discovering-eich.md`) are complete.

### Implemented
- **Time** (`time.rs`): Rational arithmetic (i64/u64), Arc (half-open interval), `split_cycles`
- **Event** (`event.rs`): `Event<V>` with whole/part model, `Value` enum (Note, Cc, Osc), onset detection
- **Pattern engine** (`pattern/`): Arena-indexed `CompiledPattern`, `PatternNode` enum, `query()` evaluator for Atom, Silence, Cat, Stack, Fast, Slow, Early, Late, Rev, Every, Euclid, Degrade
- **IR compiler** (`ir/`): `IrNode` serde-tagged enum, validation, `compile(IrNode) -> CompiledPattern`
- **Scheduler** (`scheduler/`): Real-time loop with `spin_sleep`, `Clock` (BPM to cycle-time), `SwapSlot` (arc-swap lock-free hot-swap), named pattern slots
- **Output sinks** (`output/`): `OutputSink` trait, MIDI via midir, OSC via rosc + UDP
- **IPC server** (`ipc/`): Unix domain socket, newline-delimited JSON protocol (SetPattern, Hush, HushAll, SetBpm, Ping)
- **Binary** (`main.rs`): Wires scheduler + IPC + output dispatch loop

### Stats
- 96 tests passing (94 unit + 2 integration)
- Rust edition 2024, strict clippy, `unsafe_code = "forbid"`
- Dependencies: arc-swap, crossbeam-channel, midir, rosc, serde, serde_json, smallvec, spin_sleep

## Next

- Note-off scheduling (priority queue for duration-based note-off)
- Real-time thread priority (`rt.rs` with `#[allow(unsafe_code)]`)
- MIDI clock sync output
- Benchmarks (criterion) for pattern eval and scheduler jitter
- Python frontend integration testing
