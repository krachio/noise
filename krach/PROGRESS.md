# Progress

## Current state

Live coding REPL integrating midiman (patterns) + soundman (audio) + faust-dsl (synth design).

### VoiceMixer (`mix`)
- `mix.voice(name, source, gain)` — add/replace voice (string type_id or Python DSP function)
- `mix.poly(name, source, voices, gain)` — polyphonic voice (round-robin allocation)
- `mix.note(name, *pitches, vel, **params)` — unified melodic trigger (single, chord, gate-only)
- `mix.hit(name, param)` — percussive trigger pattern atom
- `mix.seq(name, *notes, **params)` — sequence builder shorthand (None = rest)
- `mix.play(name, pattern)` — play pattern on slot (delegates to Session)
- `mix.gain/fade/mute/unmute/solo` — gain control + live performance ops
- Labels always `{voice_name}_{param}` — patterns survive graph changes
- Voice handles: returned from `mix.voice()` / `mix.poly()` for direct access
- Voice-free patterns: patterns without a bound voice (effect routing, modulation)
- `/` path addressing — hierarchical slot naming
- Effect routing: send/return via path addressing
- Modulation as patterns: LFO-style control via pattern slots
- `mix.tempo` / `mix.meter` — tempo and meter control (no `mm` in namespace)

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
