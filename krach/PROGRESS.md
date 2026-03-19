# Progress

## Current state

Live coding REPL integrating midiman (patterns) + soundman (audio) + faust-dsl (synth design).

### VoiceMixer (`mix`)
- `mix.voice(name, source, gain)` — add/replace voice (string type_id or Python DSP function)
- `mix.gain(name, value)` — instant per-voice gain (no graph rebuild)
- `mix.step(name, pitch, **params)` — melodic trigger pattern atom
- `mix.hit(name, param)` — percussive trigger pattern atom
- Labels always `{voice_name}_{param}` — patterns survive graph changes
- Graph with gain nodes + DAC built transparently via `build_graph_ir()`

### Copilot (`c()`)
- Claude generates `mix.voice()` + `mix.step()` code, not raw Graph builder
- Session context includes active voices, their labels, and node controls
- Cell queue (`cn()`) for multi-step responses with `# ---` dividers
- Code blocks validated with `ast.parse()` to filter prose

### DSP at startup
- Scans `~/.krach/dsp/*.dsp` for `hslider` names → pre-populates `_node_controls`
- Always rebuilds Rust binaries (`cargo build -q`)
- Polls soundman readiness instead of fixed sleep

## Stats
- 44 tests (pyright strict, 0 errors)

## Next
- Effects routing: `mix.bus()` / `mix.send()` for shared reverb/delay
- `mix.seq("bass", [55, 73, 65])` — sequence builder shorthand
- Scene support: `mm.scene()` for pattern snapshot switching
