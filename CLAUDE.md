# noise monorepo

## Structure

```
noise/
├── audio-engine/       Rust — audio engine library (NodeFactory, DspNode, graph runtime)
├── audio-faust/        Rust — FAUST LLVM JIT plugin library for audio-engine
├── pattern-engine/     Rust lib — pattern sequencer (engine, IPC protocol, MIDI/OSC output)
├── krach-engine/       Rust binary — unified process (pattern-engine + audio-engine + audio-faust)
├── faust-dsl/          Python 3.13 — Python → Faust .dsp transpiler
└── krach/              Python 3.13 — live coding REPL (starts krach-engine, patterns, one socket)
```

## Rust workspace

`cargo test --workspace` from root runs all Rust tests.
Individual `cargo test` still works from within any Rust subproject.

## Python subprojects

Each Python project has its own `uv` venv and `pyproject.toml`.
Run `uv run pytest` from within each subproject directory.
Do not use `pip install` — all deps managed through `uv`.

## Code Style

Flat data, obvious flow, no unnecessary abstraction. Every type must map to a domain noun. Every abstraction must prevent a nameable bug.

### Do

- Structs with public fields, free functions that transform them
- `Vec`/`std::vector` with `reserve`/`with_capacity` for hot paths
- Templates/generics for callback inlining
- Single-file modules up to ~500 lines
- Value types, contiguous storage, POD where possible
- `assert`/`debug_assert!` for contract violations
- Short names: `count`, `key`, `scratch` — not `eventCounter`, `temporaryScratchBuffer`

### Don't

- No classes/encapsulation unless protecting a multi-field invariant
- No inheritance, no virtual dispatch, no trait objects unless runtime-polymorphic
- No design patterns by name (visitor, builder, factory, etc.)
- No heap allocation on hot paths
- No `std::function`/`Box<dyn Fn>` on hot paths — use template/generic params
- No `HashMap`/`unordered_map` for n < 100 — use linear scan
- No async unless actual I/O concurrency demands it
- No premature file splitting — one file is fine until ~500 lines
- No STL algorithms over simple loops unless they genuinely clarify intent
- No metaprogramming unless >2 concrete instantiations exist today

### Before adding any abstraction

1. Name the specific bug it prevents — not a category, a scenario in this code
2. If you can't → delete it and use a function
