# soundman-faust

## Commands

- `/qa` - Run `cargo check && cargo test` + critical QA review of test quality
- `/progress` - Check if PROGRESS.md needs updating after a commit

## Stack

- Language: Rust stable (edition 2024)
- Type checker: `cargo check` (strict lints via Cargo.toml)
- Test runner: `cargo test` (serialized via `.cargo/config.toml` — FAUST LLVM JIT not thread-safe)
- Package manager: Cargo
- External dependency: libfaust (homebrew on macOS)

## soundman ↔ soundman-faust ↔ midiman

soundman is the graph wiring / audio rendering engine. soundman-faust is the primary DSP provider — it compiles FAUST code via LLVM JIT and registers nodes through soundman's `NodeFactory`/`DspNode` traits. soundman is agnostic to the DSP provider.

midiman is a pattern sequencer that sends timed OSC messages. It controls soundman (not soundman-faust directly) via OSC. soundman routes control to FAUST nodes through exposed controls.

Control flow: `midiman → soundman (OSC) → soundman-faust nodes (via registry)`
