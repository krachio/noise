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
**Session layer:** Ableton-style tracks and clips with automatic recompilation on mutation.

| Module | Role |
|--------|------|
| `ir.py` | Frozen dataclasses for `IrNode`, `Value`, `ClientMessage` + JSON serialization + validation |
| `pattern.py` | `Pattern` class with operators and transform methods, atom constructors |
| `transform.py` | Composable `Transform` callables with `>>` composition |
| `session.py` | `Session` (Unix socket IPC), `Track` (dict-like clip management), `KernelError` |

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

    drums = s.track("drums")
    drums["kick"]  = note(36) + rest() + note(36) + rest()
    drums["snare"] = rest() + note(38) + rest() + note(38)
    drums["hats"]  = note(42, duration=0.1) * 8

    melody = s.track("melody")
    melody["arp"] = (note(60) + note(64) + note(67)).over(3)

    # Live update — replace a clip, others stay
    drums["kick"] = note(36).spread(3, 8)

    # Remove a clip
    del drums["hats"]

    # Stop
    drums.stop()   # silence one track
    s.stop()       # silence all
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
| `p.scale(f)` | speed up by factor f | `Fast(f, p)` |
| `p.shift(t)` | shift in time | `Late(t, p)` / `Early(-t, p)` |
| `p.reverse()` | reverse within cycle | `Rev(p)` |
| `p.every(n, fn)` | transform every n cycles | `Every(n, fn(p), p)` |
| `p.spread(k, n)` | euclidean distribution | `Euclid(k, n, 0, p)` |
| `p.thin(prob)` | random dropout | `Degrade(prob, seed, p)` |

Nested `+` and `|` flatten automatically: `(a + b) + c` produces `Cat([a, b, c])`.

## Composable transforms

Standalone curried versions of pattern methods, composable with `>>`:

```python
from midiman_frontend import scale, thin, reverse

fx = scale(2) >> reverse >> thin(0.2)
processed = fx(note(60) + note(64) + note(67))
```

## Session model

**Session** — owns the Unix socket connection. Reads kernel responses and raises `KernelError` on errors.

```python
s = Session()                    # default /tmp/midiman.sock
s = Session("/custom/path.sock") # custom socket
```

**Track** — dict-like container of named clips bound to a session slot. On any clip mutation, recompiles and sends the pattern to the kernel.

- 0 clips → `Hush`
- 1 clip → `SetPattern(slot, clip_ir)`
- N clips → `SetPattern(slot, Stack([clip1, ..., clipN]))`

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
    synth = s.track("synth")
    synth["arp"] = (
        osc("/soundman/set", OscStr("pitch"), OscFloat(261.63))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(329.63))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(392.00))
        + osc("/soundman/set", OscStr("pitch"), OscFloat(493.88))
    )
```

C major 7th arpeggio through soundman's oscillator.

## Development

```bash
uv run pyright   # type check (strict mode, 0 errors)
uv run pytest    # 98 tests
```

## License

MIT
