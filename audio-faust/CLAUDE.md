# audio-faust

Rust library — FAUST LLVM JIT plugin for audio-engine. Compiles .dsp files at runtime.

- `cargo check` / `cargo test` (serialized — FAUST LLVM JIT not thread-safe)
- External dependency: libfaust (homebrew on macOS)
- Hot-reload: watches dsp directory, recompiles on file change
