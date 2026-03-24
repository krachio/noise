# pattern-engine

Rust library — pattern sequencer with rational time, min-heap scheduling, curve compiler.

- `cargo check` / `cargo test` from workspace root
- Edition 2024, strict clippy lints
- Compiles pattern IR to block-rate wavetables (~172 updates/sec)
- No audio synthesis — produces Control/OSC events consumed by audio-engine
