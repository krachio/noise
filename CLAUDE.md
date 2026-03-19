# noise monorepo

## Structure

```
noise/
├── soundman-core/      Rust — audio engine library (NodeFactory, DspNode, OSC control)
├── soundman-faust/     Rust — FAUST LLVM JIT plugin library for soundman-core
├── soundman/           Rust — composition binary (soundman-core + soundman-faust)
├── midiman/            Rust — pattern sequencer (IPC server, MIDI/OSC output)
├── midiman-frontend/   Python 3.13 — Python DSL over midiman
├── soundman-frontend/  Python 3.13 — Python OSC client for soundman
├── faust-dsl/          Python 3.13 — Python → Faust .dsp transpiler
└── krach/              Python 3.12 — live coding REPL (ties everything together)
```

## Rust workspace

`cargo test --workspace` from root runs all Rust tests.
Individual `cargo test` still works from within any Rust subproject.

## Python subprojects

Each Python project has its own `uv` venv and `pyproject.toml`.
Run `uv run pytest` from within each subproject directory.
