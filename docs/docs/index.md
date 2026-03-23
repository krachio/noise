# krach

Live coding audio system. Define synths in Python, sequence them with composable patterns, hear them instantly.

```python
import krach.dsp as krs

@kr.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

bass = kr.node("bass", acid_bass, gain=0.3)
verb = kr.node("verb", reverb_fn, gain=0.3)
bass >> verb                                       # route
bass @ kr.seq("A2", "D3", None, "E2").over(2)      # play
bass["cutoff"] = 1200                               # control
```

## What makes krach different

- **Graph-first API** — everything is a node. `>>` routes signal, `@` plays patterns, `[]` gets/sets controls.
- **Synths are Python functions** — write DSP code, it compiles to FAUST and JIT-compiles to native audio via LLVM. Hot reload on save.
- **Patterns are composable** — TidalCycles-inspired algebra. `+` sequences, `|` layers, `.over()` stretches, `.swing()` grooves.
- **One process, zero latency** — Rust engine runs pattern sequencer + audio graph + FAUST JIT in a single binary. Python only sends pattern IR once — all per-cycle work is Rust.
- **Two symbols** — `kr` (the audio graph) and `krs` (DSP primitives). That's the entire API.

## Quick links

- [Getting Started](getting-started.md) — install, first sound, first sequence
- [Synth Design](synth-design.md) — `@kr.dsp`, `krs` primitives, hot reload
- [Patterns](patterns.md) — pattern algebra, combinators, composition
- [Effect Routing](effect-routing.md) — buses, sends, wires
- [Architecture](architecture.md) — how the system works under the hood
- [GitHub](https://github.com/krachio/noise) — source code
