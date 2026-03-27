# Pattern Cheat Sheet

Quick reference for krach pattern API. See [Patterns](patterns.md) for full documentation.

## Atoms

```python
krp.note("C4")                   # melodic trigger (sets freq + gate)
krp.note("C4", "E4", "G4")      # chord
krp.hit()                        # gate trigger (drums)
krp.rest()                       # silence
krp.seq("A2", "D3", None, "E2") # sequence (None = rest)
krp.p("x . x . x . . x")       # mini-notation
```

## Operators

```python
a + b             # sequence: play a then b
a | b             # stack: play simultaneously
p * 4             # repeat 4 times
```

## Time

```python
p.over(2)         # stretch to 2 cycles
p.fast(2)         # double speed
p.shift(0.5)      # offset by half cycle
```

## Transforms

```python
p.reverse()                     # reverse order
p.swing(0.67)                   # swing feel
p.spread(3, 8)                  # euclidean rhythm (3 hits in 8 slots)
p.thin(0.3)                     # drop 30% of events
p.mask("1 1 0 1")              # suppress by mask
p.every(4, lambda p: p.reverse())  # transform every 4th cycle
p.sometimes(0.3, lambda p: p.reverse())  # 30% chance per cycle
```

## Continuous (for control modulation)

```python
krp.sine(200, 2000)             # sine sweep
krp.tri(200, 2000)              # triangle
krp.ramp(0, 1)                  # linear ramp
krp.ramp_down(1, 0)             # ramp down
krp.square(0, 1)                # square wave
krp.exp(0, 1)                   # exponential curve
krp.rand(0, 1)                  # random values
```

## Combinators

```python
krp.cat(a, b, c)                 # play each for 1 cycle, loop
krp.stack(a, b)                  # layer simultaneously
krp.struct(rhythm, melody)       # impose rhythm onto melody
```

## Playing patterns

```python
# On kr
kr.play("bass", pattern)
kr.play("bass/cutoff", krp.sine(200, 2000).over(4))

# On NodeHandle
bass @ pattern                  # play note pattern
bass @ ("cutoff", pattern)      # modulate control
bass @ None                     # hush
bass @ "A2 D3 ~ E2"            # mini-notation string
```

## Common recipes

```python
# Four on the floor
krp.hit() * 4

# Offbeat hats
(krp.rest() + krp.hit()) * 4

# Swung hats
((krp.rest() + krp.hit()) * 4).swing(0.67)

# Bass line with rests
krp.seq("A2", "D3", None, "E2").over(2)

# Euclidean kick (5 hits in 8)
(krp.hit() * 8).spread(5, 8)

# Filter sweep
bass @ ("cutoff", krp.sine(200, 2000).over(4))

# Probabilistic variation
melody.sometimes(0.2, lambda p: p.reverse())
```

## Mini-notation

```
x         hit
.         rest
~         tie / hold
C4 E4 G4  note sequence
[C4 E4]   chord (simultaneous)
```
