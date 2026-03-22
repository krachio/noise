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

### Pitch utilities
- `mtof(note)` / `ftom(freq)` — MIDI↔Hz conversion
- Note constants: `C0`–`B8` (C4=60, A4=69), sharps as `Cs4`, `Ds4`, etc.

### Copilot (`c()`)
- Claude generates `mix.voice()` + `mix.note()` code, not raw Graph builder
- Session context includes active voices, their labels, and node controls

## Stats
- 107 krach tests, 129 midiman-frontend tests (pyright strict, 0 errors)

## Next
- Effects routing: `mix.bus()` / `mix.send()` for shared reverb/delay
- Scene support: `mm.scene()` for pattern snapshot switching
- Mini-notation parser: `p("bd sd ~ bd")` shorthand
- Rename: soundman-core → audio-engine, midiman → pattern-engine
