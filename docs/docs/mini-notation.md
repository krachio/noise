# Mini-Notation

`kr.p()` parses a compact string notation into a pattern. It is a shorthand
for building patterns without chaining Python calls.

## Syntax

```python
kr.p("x . x . x . . x")
```

Returns a `Pattern` object -- composable like any other pattern.

## Tokens

| Token | Meaning | Equivalent |
|---|---|---|
| `x` or `X` | Hit (percussive trigger) | `kr.hit()` |
| `.` | Rest | `kr.rest()` |
| `~` | Rest (alternative) | `kr.rest()` |
| `-` | Rest (alternative) | `kr.rest()` |
| `C4`, `Cs4`, `C#4` | Note by pitch name | `kr.note("C4")` |

## Grouping: `[]`

Square brackets play tokens simultaneously (stacked):

```python
kr.p("[C4 E4] G4 B4")    # C4 and E4 together, then G4, then B4
kr.p("[x x] . x .")      # double hit, rest, hit, rest
```

## Repeat: `*N`

Repeat a token N times:

```python
kr.p("C4*2 E4 G4")       # C4 C4 E4 G4 (C4 played twice)
kr.p("x*4")              # equivalent to kr.hit() * 4
```

## Examples

### Drum patterns

```python
# Basic 4/4 kick
kr.play("kick", kr.p("x . . . x . . . x . . . x . . ."))

# Shorter: 4 hits with rests between
kr.play("kick", kr.p("x . x . x . . x"))

# Hi-hat 8ths
kr.play("hat", kr.p("x x x x x x x x"))
```

### Melodic patterns

```python
# Simple melody
kr.play("lead", kr.p("C4 E4 G4 ~ C5"))

# With simultaneous notes
kr.play("pad", kr.p("[C4 E4] [D4 F4] [E4 G4] ~"))
```

### Composable

Mini-notation patterns support all the same transforms:

```python
kr.play("kick", kr.p("x . x . x . . x").swing(0.67))
kr.play("hat", kr.p("x x x x").over(2))
kr.play("bass", kr.p("C3 E3 G3 ~").every(4, lambda p: p.reverse()))
```
