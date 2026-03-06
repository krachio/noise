# midiman

A [Tidal Cycles](https://tidalcycles.org)-inspired live coding kernel for MIDI and OSC. No audio synthesis — just precise, composable control signal patterns evaluated over rational time.

A separate Python frontend (not in this repo) sends pattern IR over a Unix socket; the Rust kernel compiles, schedules, and outputs events in real time.

## Architecture

```
Python frontend ──JSON/IPC──▶ midiman kernel
                                 │
                         ┌───────┴───────┐
                         ▼               ▼
                      MIDI out        OSC out
                      (midir)      (rosc + UDP)
```

**Core pipeline:** IR → compile → arena-indexed pattern → scheduler query → output dispatch

| Module | Role |
|--------|------|
| `time.rs` | Rational time (i64/u64), half-open arcs, `split_cycles` |
| `event.rs` | `Event<V>` with whole/part model, `Value` (Note, Cc, Osc) |
| `pattern/` | Arena-indexed `CompiledPattern`, `query()` evaluator |
| `ir/` | `IrNode` serde-tagged enum, validation, compile |
| `scheduler/` | Real-time loop, `Clock`, lock-free hot-swap via arc-swap |
| `output/` | `OutputSink` trait, MIDI (midir), OSC (rosc + UDP) |
| `ipc/` | Unix socket, newline-delimited JSON protocol |

## Pattern combinators

`Atom` `Silence` `Cat` `Stack` `Fast` `Slow` `Early` `Late` `Rev` `Every` `Euclid` `Degrade`

## Quick start

```bash
# Run the kernel (listens on /tmp/midiman.sock)
cargo run

# In another terminal, send patterns via socat
echo '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}},{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}]}}' \
  | socat - UNIX-CONNECT:/tmp/midiman.sock
```

Or try the programmatic example:

```bash
cargo run --example demo
```

## IPC protocol

Newline-delimited JSON over Unix socket. Messages:

| Command | Payload |
|---------|---------|
| `SetPattern` | `{"cmd":"SetPattern", "slot":"d1", "pattern": <IrNode>}` |
| `Hush` | `{"cmd":"Hush", "slot":"d1"}` |
| `HushAll` | `{"cmd":"HushAll"}` |
| `SetBpm` | `{"cmd":"SetBpm", "bpm": 140.0}` |
| `Ping` | `{"cmd":"Ping"}` |

Responses: `{"status":"Ok", "msg":"..."}`, `{"status":"Error", "msg":"..."}`, or `{"status":"Pong"}`.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `MIDIMAN_SOCKET` | `/tmp/midiman.sock` | IPC socket path |
| `MIDIMAN_OSC_TARGET` | `127.0.0.1:57120` | OSC destination (e.g. SuperDirt) |

MIDI output connects to the first available port automatically.

## Development

```bash
cargo check    # type check (strict clippy, unsafe_code = "forbid")
cargo test     # 105 tests (94 unit + 11 integration)
```

## License

MIT
