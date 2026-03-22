# midiman-frontend

Ableton-inspired Python DSL for the [noise](https://github.com/krachio) ecosystem. Immutable pattern graphs composed with Python operators, compiled to JSON IR, sent to the [midiman](https://github.com/krachio/midiman) kernel over a Unix socket.

## Architecture

```
Python DSL ──(pattern graph)──▶ JSON IR ──Unix socket──▶ midiman kernel
                                                             │
                                                     ┌───────┴───────┐
                                                     ▼               ▼
                                                  MIDI out        OSC out
```

**Pattern layer:** immutable dataclass graphs built with `+`, `|`, `*` operators and transform methods.
**Session layer:** flat slot→pattern binding with explicit state management.

| Module | Role |
|--------|------|
| `ir.py` | Frozen dataclasses for `IrNode`, `Value`, `ClientMessage` (incl. `Batch`) + JSON serialization + validation |
| `pattern.py` | `Pattern` class with operators and transform methods, atom constructors |
| `transform.py` | Composable `Transform` callables with `>>` composition |
| `session.py` | `Session` (Unix socket IPC), `SlotState`, `KernelError` |

## Quick start

```bash
uv pip install -e .
```

Start the midiman kernel in another terminal:

```bash
cd ../midiman && cargo run
```

Then in Python (or IPython for live coding):

```python
from midiman_frontend import Session, note, rest

with Session() as s:
    s.tempo = 128

    kick = note(36) + rest() + note(36) + rest()
    hats = note(42, duration=0.1) * 8

    # Atomic multi-slot launch — stays in sync
    s.launch({
        "drums": kick | hats,
        "melody": (note(60) + note(64) + note(67)).over(3),
    })

    # Live update — recompose and resend
    s.play("drums", kick.spread(3, 8) | hats)

    # Silence a slot (pattern remembered)
    s.hush("drums")

    # Bring it back
    s.resume("drums")

    # Forget a slot entirely
    s.remove("drums")

    # Silence everything (patterns remembered)
    s.stop()
```

## Pattern algebra

All operations return new `Pattern` objects — nothing is mutated.

| Syntax | Semantics | Compiles to |
|--------|-----------|-------------|
| `note(60)` | MIDI note atom | `Atom(Note(...))` |
| `rest()` | silence | `Silence` |
| `cc(74, 127)` | MIDI CC | `Atom(Cc(...))` |
| `osc("/addr", OscFloat(1.0))` | OSC message | `Atom(Osc(...))` |
| `p + q` | sequence (equal time share) | `Cat([p, q])` |
| `p \| q` | layer (both occupy full cycle) | `Stack([p, q])` |
| `p * n` | repeat n times | `Cat([p] * n)` |
| `p.over(n)` | loop over n cycles | `Slow(n, p)` |
| `p.fast(f)` | speed up by factor f | `Fast(f, p)` |
| `p.shift(t)` | shift in time | `Late(t, p)` / `Early(-t, p)` |
| `p.reverse()` | reverse within cycle | `Rev(p)` |
| `p.every(n, fn)` | transform every n cycles | `Every(n, fn(p), p)` |
| `p.spread(k, n)` | euclidean distribution | `Euclid(k, n, 0, p)` |
| `p.thin(prob)` | random dropout | `Degrade(prob, seed, p)` |

Nested `+` and `|` flatten automatically: `(a + b) + c` produces `Cat([a, b, c])`.

## Composable transforms

Standalone curried versions of pattern methods, composable with `>>`:

```python
from midiman_frontend import fast, reverse, thin, every

fx = fast(2) >> reverse >> thin(0.2)
processed = fx(note(60) + note(64) + note(67))

# Apply a transform every N cycles
swing = every(2, reverse)
```

Available: `scale`, `reverse`, `shift`, `every`, `spread`, `thin`.

## Session

Session is a thin binding layer — maps slot names to pattern trees and sends them to the kernel over a Unix socket. All state is visible.

| Method | Effect | Wire command |
|--------|--------|-------------|
| `s.play("drums", pat)` | set pattern, mark playing | `SetPattern` |
| `s.hush("drums")` | silence, keep pattern (resumable) | `Hush` |
| `s.resume("drums")` | re-send remembered pattern | `SetPattern` |
| `s.remove("drums")` | silence and forget pattern | `Hush` |
| `s.stop()` | silence all slots (patterns remembered) | `HushAll` |
| `s.launch({"drums": p1, "mel": p2})` | atomic multi-slot update | `Batch` |
| `s.tempo = 128` | set BPM | `SetBpm` |
| `s.ping()` | health check | `Ping` |

`launch()` sends all patterns in a single `Batch` command — the kernel applies them atomically, so slots stay in sync.

State is queryable:

```python
>>> s
Session(connected, tempo=128.0)
  drums: playing
  melody: playing
  bass: stopped

>>> s.slots
{"drums": SlotState(pattern=..., playing=True), ...}
```

## With midiman + soundman

Drive [soundman](https://github.com/krachio/soundman) oscillators through midiman:

```bash
# Terminal 1: audio engine
cd ../soundman && cargo run

# Terminal 2: pattern sequencer
cd ../midiman && MIDIMAN_OSC_TARGET=127.0.0.1:9000 cargo run

# Terminal 3: Python
python
```

```python
from midiman_frontend import Session, osc
from midiman_frontend.ir import OscFloat, OscStr

with Session() as s:
    s.tempo = 120
    s.play("synth", (
        osc("/soundman/set", OscStr("pitch"), OscFloat(261.63))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(329.63))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(392.00))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(493.88))
    ))
```

C major 7th arpeggio through soundman's oscillator.

## Development

```bash
uv run pyright   # type check (strict mode, 0 errors)
uv run pytest    # 120 tests
```

## License

MIT
