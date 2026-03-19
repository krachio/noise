# soundman

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test`
- Package manager: Cargo

## midiman ↔ soundman OSC bridge

midiman (sibling repo at `../midiman`) is a pattern sequencer that sends timed OSC messages. soundman is the audio engine. They connect over UDP/OSC: midiman sends `/soundman/set pitch <freq>` messages, soundman receives them via `OscControlInput` and routes to the oscillator.

### Demo

Terminal 1: `cd soundman && cargo run`
Terminal 2: `cd midiman && MIDIMAN_OSC_TARGET=127.0.0.1:9000 cargo run`
Terminal 3 (send arpeggio pattern):
```bash
echo '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":261.63}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":329.63}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":392.0}]}},{"op":"Atom","value":{"type":"Osc","address":"/soundman/set","args":[{"Str":"pitch"},{"Float":493.88}]}}]}}' | socat - UNIX-CONNECT:/tmp/midiman.sock
```

Plays a C major 7th arpeggio (C4→E4→G4→B4) through soundman's oscillator at 120 BPM.
