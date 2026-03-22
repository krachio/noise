# audio-faust

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test` (serialized via `.cargo/config.toml` — FAUST LLVM JIT not thread-safe)
- Package manager: Cargo
- External dependency: libfaust (homebrew on macOS)

## Architecture

audio-engine is the graph wiring / audio rendering engine. audio-faust is the primary DSP provider -- it compiles FAUST code via LLVM JIT and registers nodes through audio-engine's `NodeFactory`/`DspNode` traits. Both are linked into krach-engine (the unified binary). Control flow: `krach (Python) → krach-engine (Unix socket /tmp/krach.sock) → audio-engine → audio-faust nodes (via registry)`
