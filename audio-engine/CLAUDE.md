# soundman-core

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test`
- Package manager: Cargo

## Architecture

soundman-core is a library used by noise-engine (the unified binary). midiman (pattern sequencer) and soundman (audio engine) run in-process, communicating via channels. External control comes through a single Unix socket (JSON protocol).
