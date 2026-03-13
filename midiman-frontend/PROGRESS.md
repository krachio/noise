# Progress

## Current state

Ableton-inspired Python DSL frontend for the midiman Rust kernel.

### Modules
- `ir.py` — frozen dataclasses for IrNode, Value, ClientMessage + JSON serialization
- `pattern.py` — Pattern class with `+` (seq), `|` (layer), `*` (repeat), `.over()`, `.scale()`, `.shift()`, `.reverse()`, `.every()`, `.spread()`, `.thin()`. Atom constructors: `note()`, `rest()`, `cc()`, `osc()`
- `transform.py` — composable Transform callables with `>>` composition
- `session.py` — Session (Unix socket IPC) + Track (dict-like clip management)
- `__init__.py` — public API re-exports

### Test coverage
71 tests, 0 pyright strict errors. Covers IR serialization, pattern algebra, transforms, session IPC (mocked), and end-to-end integration.

### Wire compatibility
JSON output matches the Rust kernel's serde-tagged format: `{"op": ...}` for IrNode, `{"type": ...}` for Value, `{"cmd": ...}` for ClientMessage.

## Next

- Integration test against running midiman kernel
- Mini-notation parser for quick pattern entry
- Scene launch (`s.launch(drums=..., melody=...)`)
- Track mute/unmute
- Track-level `.apply()` for persistent transforms
