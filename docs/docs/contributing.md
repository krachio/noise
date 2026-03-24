# Contributing

## Prerequisites

- **Rust** stable (edition 2024) via [rustup](https://rustup.rs/)
- **Python 3.13+**
- **uv** for Python dependency management
- **libfaust** (FAUST LLVM JIT compiler) — `brew install faust` on macOS
- **socat** (optional, for manual IPC testing)

## Dev setup

```bash
git clone <repo-url> noise
cd noise

# Build all Rust crates
cargo build --workspace

# Set up Python environment
cd krach && uv sync && cd ..
```

## Running tests

### Rust (all crates)

```bash
cargo test --workspace
```

This runs tests for audio-engine, audio-faust, pattern-engine, and krach-engine. audio-faust tests run serialized (FAUST LLVM JIT is not thread-safe).

### Python — krach

```bash
cd krach
uv run pyright    # type checking (strict mode)
uv run pytest     # unit tests
```

### Quick check before committing

```bash
cargo check --workspace && cargo test --workspace
cd krach && uv run pyright && uv run pytest && cd ..
```

## Code style

The full style guide is in `CODING_STYLE.md` at the repo root. The short version:

**Flat data, obvious flow, no unnecessary abstraction.** Every type must map to a domain noun. Every abstraction must prevent a nameable bug.

### The abstraction test

Before adding any abstraction, ask:

1. Can I name the specific bug this prevents? Not a category — a scenario in this code.
2. Does the reader need to understand the abstraction to understand the data flow?
3. Can I delete this and replace it with a function?

If you cannot answer (1) with a concrete scenario, do not add the abstraction.

### Rust guidelines

- Structs with public fields, free functions that transform them
- `Vec` with `with_capacity` for hot paths — no heap allocation in audio callbacks
- Templates/generics for callback inlining — no `Box<dyn Fn>` on hot paths
- `assert!` / `debug_assert!` for contract violations
- `Result<T, E>` for recoverable errors, fail loudly and early
- Single-file modules up to ~500 lines — do not split prematurely
- Short names: `count`, `key`, `scratch` — not `eventCounter`, `temporaryScratchBuffer`
- No inheritance, no virtual dispatch, no trait objects unless runtime-polymorphic
- No `HashMap` for n < 100 — use linear scan
- No async unless actual I/O concurrency demands it
- No design patterns by name (visitor, builder, factory, etc.)
- Strict clippy lints, `unsafe_code = "forbid"`

### Python guidelines

- Strict pyright type checking — no `Any` escape hatches
- Frozen dataclasses for IR types (immutable value objects)
- Pattern matching (`match`/`case`) over if-elif chains
- All deps managed through uv, never pip
- Each subproject has its own venv and `pyproject.toml`

## Project structure

```
noise/
├── audio-engine/       Rust lib  — graph-based audio engine
├── audio-faust/        Rust lib  — FAUST LLVM JIT plugin + hot reload
├── pattern-engine/     Rust lib  — pattern sequencer
├── krach-engine/       Rust bin  — unified process
├── krach/              Python    — live coding REPL, IR layer, DSP transpiler
└── krach-mcp/          Python    — MCP server for Claude Code
```

See the [architecture documentation](architecture.md) for detailed data flow and design decisions.

## Making changes

### Where things live

| Change | Location |
|--------|----------|
| New DSP node type | `audio-faust/` (FAUST .dsp) or `audio-engine/src/nodes/` (Rust) |
| Pattern combinator | `pattern-engine/src/ir.rs` + `pattern-engine/src/pattern.rs` |
| Python pattern API | `krach/src/krach/patterns/` |
| IPC protocol | `krach-engine/src/ipc.rs` + `audio-engine/src/protocol.rs` + `pattern-engine/src/ipc/` |
| DSP transpiler | `krach/src/krach/dsl/` + `krach/src/krach/ir/signal.py` |
| REPL commands | `krach/src/krach/` |

### Adding a new pattern combinator

1. Add the variant to `IrNode` in `pattern-engine/src/ir.rs`
2. Add compile logic in `pattern-engine/src/pattern.rs`
3. Add a `PatternPrimitive` + `*Params` in `krach/src/krach/ir/pattern.py`
4. Register it in `krach/src/krach/patterns/primitives.py`
5. Add a serialize rule in `krach/src/krach/patterns/serialize.py`
6. Add a summary handler in `krach/src/krach/_ir_summary.py`
7. Import-time completeness checks enforce steps 5-6 — missing rules fail at import

### Adding a new audio node type

For FAUST nodes: write a `.dsp` file and drop it in `~/.krach/dsp/`. The hot reload engine picks it up automatically.

For Rust nodes: implement `DspNode` and register via `NodeTypeDecl` + `NodeFactory`. See `audio-engine/src/nodes/` for examples.

## Commit guidelines

- Small, focused commits — one logical change per commit
- Clear commit messages describing why, not just what
- Tests first: if you are fixing a bug, write a failing test before the fix
- Run the full test suite before pushing

## PR process

1. Create a feature branch from `main`
2. Make small commits with clear messages
3. Ensure all tests pass (`cargo test --workspace`, `uv run pytest` in Python projects)
4. Ensure type checks pass (`cargo check --workspace`, `uv run pyright` in krach)
5. Open a PR with a description of the change and how to test it
