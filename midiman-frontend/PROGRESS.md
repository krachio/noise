# Progress

## Current state

Ableton-inspired Python DSL frontend for the midiman Rust kernel.

### Modules
- `ir.py` — frozen dataclasses for IrNode, Value, ClientMessage + JSON serialization + `__post_init__` validation
- `pattern.py` — Pattern class with `+` (seq), `|` (layer), `*` (repeat), `.over()`, `.scale()`, `.shift()`, `.reverse()`, `.every()`, `.spread()`, `.thin()`. Atom constructors: `note()`, `rest()`, `cc()`, `osc()`
- `transform.py` — composable Transform callables with `>>` composition
- `session.py` — Session with flat slot→pattern model: `play()`, `hush()`, `resume()`, `remove()`, `stop()`. SlotState (frozen) tracks playing/stopped per slot. KernelError on bad responses.

### Test coverage
112 tests, 0 pyright strict errors. Covers IR serialization, pattern algebra, transforms, session slot management, response handling, end-to-end integration, and IR validation.

### Wire compatibility
JSON output matches the Rust kernel's serde-tagged format: `{"op": ...}` for IrNode, `{"type": ...}` for Value, `{"cmd": ...}` for ClientMessage.

### Design decisions
- No Track/clip abstraction — pattern algebra handles all composition, Session is a flat slot→pattern binding
- State is visible: `s.slots` returns current slot states, `repr()` shows playing/stopped
- `hush()` remembers pattern (resumable), `remove()` forgets it, `stop()` hushes all but remembers

## Next

- Batch command support (kernel has it now) for atomic multi-slot updates
- Integration test against running midiman kernel
