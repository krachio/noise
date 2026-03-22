# Progress

## Current state

Live coding REPL integrating midiman (patterns) + soundman (audio) + faust-dsl (synth design).

### VoiceMixer (`mix`)
- `mix.voice(name, source, gain, count)` — add voice, returns `VoiceHandle`. `count > 1` = poly.
- `mix.bus(name, source, gain)` — add effect bus, returns `BusHandle`
- `mix.play(name, pattern)` / `mix.set(path, value)` / `mix.fade(path, target, bars)`
- `mix.send(voice, bus, level)` / `mix.wire(voice, bus, port)` — effect routing
- `mix.gain/mute/unmute/solo/unsolo/hush/stop` — live performance ops
- `mix.mod(path, pattern, bars)` — convenience for modulation
- `mix.tempo` / `mix.meter` — transport (no `mm` in namespace)
- Voice handles: `kick = mix.voice(...)` then `kick.play(hit() * 4)`

### Free pattern functions
- `note("C4")`, `hit()`, `seq("A2", "D3", None)` — bind to voice at play time
- `mod_sine(lo, hi)`, `ramp(start, end)` — modulation as patterns
- `/` path addressing: `mix.set("bass/cutoff", v)`, group ops: `mix.mute("drums")`

### Pitch utilities
- `mtof(note)` / `ftom(freq)` — MIDI↔Hz conversion
- Note constants: `C0`–`B8` (C4=60, A4=69), sharps as `Cs4`, `Ds4`, etc.

### Copilot (`c()`)
- Claude generates `mix.voice()` + `mix.note()` code, not raw Graph builder
- Session context includes active voices, their labels, and node controls

## Stats
- 218 krach tests (pyright strict, 0 errors)

## Next
- Scene support: scene snapshot switching
- Mini-notation parser: `p("bd sd ~ bd")` shorthand
