# pattern-engine - Project Instructions

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit
- `/stack` - Configure project stack (language, type checker, test runner, tooling)

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test`
- Package manager: Cargo
- Pre-commit hooks: `cargo check`, `cargo test`
