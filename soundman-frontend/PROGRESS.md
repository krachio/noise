# Progress

## Current state

Python OSC client for soundman. 26 tests, pyright strict clean.

- **`ir.py`**: `NodeInstance`, `ConnectionIr`, `GraphIr` — frozen dataclasses, JSON serialization wire-compatible with soundman's serde format
- **`graph.py`**: Fluent `Graph` builder — `node()`, `connect()`, `expose()`, `expose_schema()` (duck-typed `ControlSchemaLike` Protocol for faust-dsl integration), `build() → GraphIr`
- **`session.py`**: `SoundmanSession` — OSC UDP client wrapping python-osc; `load_graph`, `set`, `gain`, `ping`, `shutdown`; context manager

## Next

- Wire into krach alongside midiman-frontend and faust-dsl
- `expose_schema()` integration test against a real faust-dsl `ControlSchema`
