# Progress

## Current state

Full implementation complete — all 7 commits from the plan delivered in one pass.

### Stack
- Language: Python 3.13
- Package manager: uv with hatchling build backend (src layout: `src/faust_dsl/`)
- Type checker: pyright strict — 0 errors
- Test runner: pytest — 68 tests, all passing

### Implemented modules

```
src/faust_dsl/
├── __init__.py            public surface
├── _core.py               Signal tracer, FaustGraph IR, TraceContext, ControlParams
├── _primitives.py         Primitive instances (arithmetic, math, mem, delay, feedback, control)
├── _dsp.py                User-facing DSP functions (feedback, mem, delay, sin, cos, ...)
├── _lowering.py           FaustGraph → Faust expression strings
├── _codegen.py            FaustGraph → complete .dsp source
├── _optimize.py           CSE / DCE / constant folding passes
├── ad.py                  Forward-mode AD: jvp(), jvp_graph(), ZeroTangent, register_jvp
├── transpile.py           transpile(), TranspiledDsp, ControlSchema, control()
├── compose.py             chain, parallel, split, merge, route
├── lib/
│   ├── oscillators.py     phasor, sine_osc, saw, square, triangle, lfo
│   ├── filters.py         lowpass, highpass, bandpass, resonant, onepole, dcblock
│   ├── noise.py           white_noise, pink_noise
│   └── utilities.py       clip, lerp, smooth, db_to_linear, linear_to_db
└── music/
    ├── envelopes.py       adsr, ar, decay, trigger, latch
    ├── effects.py         reverb, echo, chorus, flanger
    ├── spatial.py         pan, stereo_width
    └── scales.py          midi_to_freq, freq_to_midi
```

### Key design decisions
- Zero runtime dependencies (pure Python stdlib)
- `control()` lowers to `hslider(...)` and populates `ControlSchema`
- `transpile()` wraps `make_graph` + `emit_faust` + control collection
- `_dsp.py` added (not in original plan) to host user-facing DSP functions imported by lib/music
- `make_graph` coerces float/int return values to const signals

## Next

- Wire `ControlSchema` into soundman-frontend `exposed_controls`
- Consider adding `transpile(optimize=True)` as default once optimization is battle-tested
