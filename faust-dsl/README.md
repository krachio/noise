# faust-dsl

Python DSL for writing FAUST signal processing code. Transpiles Python functions to FAUST `.dsp` source.

Used by `krach` to let users define synths in Python that compile to native audio via FAUST + LLVM JIT.

## Example

```python
from faust_dsl import Signal, control, transpile
from faust_dsl.lib.oscillators import saw
from faust_dsl.lib.filters import lowpass
from faust_dsl.music.envelopes import adsr

def acid_bass() -> Signal:
    freq = control("freq", 55.0, 20.0, 800.0)
    gate = control("gate", 0.0, 0.0, 1.0)
    cutoff = control("cutoff", 800.0, 100.0, 4000.0)
    env = adsr(0.005, 0.15, 0.3, 0.08, gate)
    return lowpass(saw(freq), cutoff) * env * 0.55

result = transpile(acid_bass)
print(result.source)  # FAUST .dsp code
print(result.schema.controls)  # [ControlSpec("freq", ...), ...]
```

## Primitives

| Module | Functions |
|--------|-----------|
| `lib.oscillators` | `sine_osc`, `saw`, `square`, `phasor` |
| `lib.filters` | `lowpass`, `highpass`, `bandpass` |
| `lib.noise` | `white_noise` |
| `music.envelopes` | `adsr` |
| `music.effects` | `reverb` |
| (core) | `Signal`, `control`, `transpile` |

## Development

```bash
uv sync
uv run pytest
```

## License

MIT
