# audio-engine

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test`
- Package manager: Cargo

## Architecture

audio-engine is a library used by krach-engine (the unified binary). pattern-engine (pattern sequencer) and audio-engine run in-process, communicating via channels. External control comes through a single Unix socket (`/tmp/krach.sock`, JSON protocol).
