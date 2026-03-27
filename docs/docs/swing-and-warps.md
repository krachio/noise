# Swing

Swing delays every other subdivision to create a shuffled, off-grid feel.
krach implements swing as a piecewise linear time remap applied at scheduling time.

## `.swing(amount, grid)`

Apply swing to any pattern:

```python
pattern.swing(amount)
pattern.swing(amount, grid)
```

**amount** -- how much to delay the offbeat:

| Value | Feel |
|---|---|
| `0.5` | Straight (no swing) |
| `0.67` | Standard swing (triplet feel) |
| `0.75` | Heavy triplet swing |

**grid** -- subdivisions per cycle. Defaults to 8 (8th notes in 4/4).

```python
(kr.hit() * 8).swing(0.67)       # swung 8th notes
(kr.hit() * 8).swing(0.67, 8)    # same, explicit grid
(kr.hit() * 16).swing(0.6, 16)   # swung 16th notes
```

## How it works

Swing operates on pairs of beats within the grid. For each pair, the second
beat is shifted forward in time by the swing amount:

- At `amount=0.5`, the second beat sits exactly halfway -- straight time
- At `amount=0.67`, the second beat sits 2/3 of the way through the pair --
  classic triplet swing
- At `amount=0.75`, the second beat sits 3/4 of the way -- heavy shuffle

The time warp is **piecewise linear** within each beat pair. This means all
events between the pair boundaries are smoothly redistributed, not just the
beats themselves.

## Examples

### Swung hi-hat

```python
def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5

kr.node("hat", hat, gain=0.5)

# Straight 8ths
kr.play("hat", kr.hit() * 8)

# Standard swing
kr.play("hat", (kr.hit() * 8).swing(0.67))

# Heavy shuffle
kr.play("hat", (kr.hit() * 8).swing(0.75))
```

### Shuffled bass line

```python
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2).swing(0.67))
```

### Swung kick pattern

```python
kr.play("kick", (kr.hit() * 8).swing(0.67))
```

## Convenience kwarg on `kr.play()`

Instead of calling `.swing()` on the pattern, pass `swing=` directly to
`kr.play()`:

```python
kr.play("kick", kr.hit() * 8, swing=0.67)
kr.play("hat", kr.hit() * 8, swing=0.67)
```

Both forms are equivalent.

## Combining swing with other transforms

Swing composes with all pattern operations:

```python
# Swung euclidean rhythm
kr.play("hat", kr.hit().spread(5, 8).swing(0.67))

# Swing with periodic reverse
p = (kr.hit() * 8).swing(0.67)
kr.play("kick", p.every(4, lambda p: p.reverse()))

# Swung mini-notation
kr.play("hat", kr.p("x . x x . x . x").swing(0.67))
```

## Implementation

Swing is implemented as a `WarpParams(kind="swing", amount, grid)` node in
the pattern IR. The engine applies the piecewise linear time remap at
scheduling time -- no interpolation, no latency.
