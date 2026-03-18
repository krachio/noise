# Progress

## Current state

Ableton-inspired Python DSL frontend for the midiman Rust kernel.

### Modules
- `ir.py` — frozen dataclasses for IrNode, Value, ClientMessage (incl. `Batch`, `SimpleCommand`) + JSON serialization + `__post_init__` validation
- `pattern.py` — Pattern class with `+` (seq), `|` (layer), `*` (repeat), `.over()`, `.scale()`, `.shift()`, `.reverse()`, `.every()`, `.spread()`, `.thin()`. Atom constructors: `note()`, `rest()`, `cc()`, `osc()`
- `transform.py` — composable Transform callables with `>>` composition
- `session.py` — Session with flat slot→pattern model: `play()`, `hush()`, `resume()`, `remove()`, `stop()`, `launch()`. SlotState (frozen) tracks playing/stopped per slot. KernelError on bad responses.

### Test coverage
120 tests, 0 pyright strict errors. Covers IR serialization (incl. Batch), pattern algebra, transforms, session slot management, launch/batch, response handling, end-to-end integration, and IR validation.

### Wire compatibility
JSON output matches the Rust kernel's serde-tagged format: `{"op": ...}` for IrNode, `{"type": ...}` for Value, `{"cmd": ...}` for ClientMessage. Batch: `{"cmd":"Batch","commands":[...]}`.

### Design decisions
- No Track/clip abstraction — pattern algebra handles all composition, Session is a flat slot→pattern binding
- State is visible: `s.slots` returns current slot states, `repr()` shows playing/stopped
- `hush()` remembers pattern (resumable), `remove()` forgets it, `stop()` hushes all but remembers
- `launch()` for atomic multi-slot updates via Batch — kernel applies all-or-nothing

## Next

- Integration test against running midiman kernel
