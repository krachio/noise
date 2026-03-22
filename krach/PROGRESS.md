# Progress

## Current state

Live coding REPL integrating pattern-engine (patterns) + audio-engine (audio) + faust-dsl (synth design).

### Two-symbol API: `kr` + `krs`
- `kr` = VoiceMixer instance (all live coding ops)
- `krs` = `krach.dsp` module (synthesis primitives)
- `krach.connect()` encapsulates startup

### VoiceMixer (`kr`)
- `kr.voice(name, source, gain, count)` — add voice, returns `VoiceHandle`. `count > 1` = poly.
- `kr.bus(name, source, gain)` — add effect bus, returns `BusHandle`
- `kr.play(name, pattern)` / `kr.set(path, value)` / `kr.fade(path, target, bars)`
- `kr.send(voice, bus, level)` / `kr.wire(voice, bus, port)` — effect routing
- `kr.gain/mute/unmute/solo/unsolo/hush/stop` — live performance ops
- `kr.mod(path, pattern, bars)` — modulation
- `kr.tempo` / `kr.meter` — transport
- `kr.save("verse")` / `kr.recall("chorus")` — scene snapshot + restore
- `kr.load("songs/verse.py")` — music-as-code
- `kr.input("mic")` — ADC input node (live audio from CoreAudio)
- `kr.midi_map(cc=74, path="bass/cutoff", lo=200, hi=4000)` — MIDI CC mapping
- Voice handles: `kick = kr.voice(...)` then `kick.play(kr.hit() * 4)`

### Pattern builders (on `kr`)
- `kr.note("C4")`, `kr.hit()`, `kr.seq("A2", "D3", None)` — bind to voice at play time
- `kr.mod_sine(lo, hi)`, `kr.ramp(start, end)` — modulation as patterns
- `kr.p("x . x . x . . x")` — mini-notation parser
- `/` path addressing: `kr.set("bass/cutoff", v)`, group ops: `kr.mute("drums")`

### Pitch utilities (on `kr`)
- `kr.mtof(note)` / `kr.ftom(freq)` — MIDI↔Hz conversion
- `kr.parse_note("C#4")` — note name to MIDI number

### Copilot (`kr.c()`)
- Claude generates `kr.voice()` + `kr.note()` code
- Session context includes active voices, their labels, and node controls

## Stats
- 442 krach tests (pyright strict, 0 errors)

## Next
- Looper: record live input into buffer, play back as pattern-triggered voice
