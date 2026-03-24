# audio-engine

Rust library — real-time audio graph runtime. Used by krach-engine (the unified binary).

- `cargo check` / `cargo test` from workspace root
- Edition 2024, strict clippy lints via Cargo.toml
- Pattern-engine and audio-engine run in-process, communicating via channels
- External control via Unix socket (JSON protocol)
