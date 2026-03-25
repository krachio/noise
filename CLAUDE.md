# noise monorepo

## Structure

```
noise/
├── audio-engine/       Rust — audio engine library (NodeFactory, DspNode, graph runtime)
├── audio-faust/        Rust — FAUST LLVM JIT plugin library for audio-engine
├── pattern-engine/     Rust lib — pattern sequencer (engine, IPC protocol, MIDI/OSC output)
├── krach-engine/       Rust binary — unified process (pattern-engine + audio-engine + audio-faust)
├── krach/              Python 3.13 — live coding REPL (IR, DSP transpiler, patterns, graph API)
└── krach-mcp/          Python 3.13 — MCP server (25 tools for Claude Code to drive krach)
```

## Rust workspace

`cargo test --workspace` from root runs all Rust tests.
Individual `cargo test` still works from within any Rust subproject.

## Python

krach and krach-mcp each have their own `uv` venv and `pyproject.toml`.
Run `uv run pytest` from within krach/. Do not use `pip install` — deps managed through `uv`.
The DSP transpiler (formerly faust-dsl) lives inside krach as `krach.ir.signal`, `krach.dsl.*`, `krach.backends.faust*`.

## Design Philosophy

krach is a **graph-based live coding system**, not a DAW. The Python API exposes the
graph directly: nodes, connections, patterns. No voice/bus/track abstractions —
everything is a node. Routing uses operators (`>>`), not named methods.

```python
bass = kr.node("bass", bass_fn, gain=0.3)    # source (0 inputs)
verb = kr.node("verb", reverb_fn, gain=0.3)  # effect (auto-detected: 1+ inputs)
bass >> verb                                   # route
bass.play(kr.seq("A2", "D3").swing(0.67))    # pattern
```

If a musician-friendly UI is needed, build it in Python on top of the graph API.
Don't bake DAW concepts (tracks, buses, aux sends) into the core.

## Issue tracking

Bugs and feature requests live in GitHub issues. During live sessions, `issues.log` (gitignored)
is the scratch pad — promote to GitHub issues after the session. Prefix entries with `[bug]`,
`[feature]`, or `[ux]`.

## Non-negotiable principles

- **No backward compatibility if it stands in the way of the pure solution.** Delete, rename, break imports. The right design wins over migration comfort. If old code is wrong, remove it — don't wrap it.
- **No half-baked work.** Either do it right or don't do it. No "fix later" shims, no "good enough for now" compromises. Strive for the correct thing.

## Code Style

Flat data, obvious flow, no unnecessary abstraction. Every type must map to a domain noun. Every abstraction must prevent a nameable bug.

### Do

- Structs with public fields, free functions that transform them
- `Vec`/`std::vector` with `reserve`/`with_capacity` for hot paths
- Templates/generics for callback inlining
- ~500 lines for multi-concern modules; cohesive single-class files up to ~800. Split on concern boundaries, not line counts
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

### No whack-a-mole fixes

When a bug appears in multiple call sites (or will appear once someone adds site N+1):
1. Identify the missing abstraction — a sum type, a resolver, a single function that owns the decision
2. Centralize — all call sites consume it via exhaustive pattern match
3. Make the wrong thing unrepresentable — if a new call site can forget a case, the abstraction is incomplete

A scattered `if` check in N places is a bug report waiting for N+1. A sum type with exhaustive match is a proof.
