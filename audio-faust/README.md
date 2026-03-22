# audio-faust

FAUST LLVM JIT plugin for the `audio-engine` (sibling in this monorepo). Write DSP in [FAUST](https://faust.grame.fr), drop `.dsp` files in a directory, get live hot-reloading nodes in the audio graph.

## Architecture

```
.dsp files ──▶ DspWatcher ──notify──▶ HotReloadEngine
                                           │
                                    ┌──────┴──────┐
                                    ▼              ▼
                              FaustFactory    EngineController
                              (LLVM JIT)     (graph recompile)
                                    │              │
                                    ▼              ▼
                               FaustDsp       GraphSwapper
                            (UIGlue params)  (linear crossfade)
```

**Compilation:** FAUST source → LLVM JIT factory → DSP instance with discovered parameters.
**Hot reload:** file watcher detects `.dsp` change → recompile → reregister → graph crossfade swap.

| Module | Role |
|--------|------|
| `ffi` | Raw FFI bindings to libfaust C API (`llvm-dsp-c.h`, `CInterface.h`) |
| `dsp` | Safe `FaustDsp` wrapper — compile, parameter discovery via UIGlue, audio processing |
| `factory` | `FaustFactory` implements audio-engine's `NodeFactory` — probes ports and controls |
| `node` | `FaustNode` adapts `FaustDsp` to audio-engine's `DspNode` trait |
| `loader` | Load `.dsp` files from disk, register entire directories |
| `watcher` | `notify`-based file watcher, `apply_reload()` for register/reregister |
| `hot_reload` | `HotReloadEngine` — wraps engine + watcher + graph for live reloading |

## Quick start

### Prerequisites

Install FAUST with LLVM backend:

```bash
brew install faust  # macOS
```

### Programmatic usage

```rust
use audio_engine::engine::{self, config::EngineConfig};
use audio_faust::hot_reload::HotReloadEngine;

// Point at a directory of .dsp files
let (mut engine, mut proc) = HotReloadEngine::new(
    &EngineConfig::default(),
    "./dsp",
).unwrap();

// Load a graph using FAUST nodes (type_id = "faust:<filename>")
engine.load_graph(my_graph_ir).unwrap();

// In your audio loop:
proc.process(&mut output_buffer);

// In your control loop — picks up .dsp file changes:
engine.poll_reload().unwrap();
```

### Writing FAUST nodes

Drop `.dsp` files in your DSP directory (supports subdirectories). The relative path becomes the type ID:

**`dsp/lowpass.dsp`** → type ID `faust:lowpass`
**`dsp/fx/reverb.dsp`** → type ID `faust:fx/reverb`

```faust
import("stdfaust.lib");
cutoff = hslider("cutoff", 1000, 20, 20000, 1);
q = hslider("q", 0.707, 0.1, 10, 0.01);
process = fi.resonlp(cutoff, q, 1);
```

**`dsp/sine.dsp`** → type ID `faust:sine`

```faust
import("stdfaust.lib");
freq = hslider("freq", 440, 20, 20000, 1);
process = os.osc(freq);
```

FAUST parameters (`hslider`, `vslider`, `nentry`, `button`, `checkbox`) are automatically discovered and exposed as audio-engine controls.

### Hot reload

Edit any `.dsp` file while the engine is running. `poll_reload()` detects the change, recompiles the FAUST code, updates the registry, and crossfade-swaps to the new graph. No restart needed.

## With audio-engine and pattern-engine

audio-faust provides DSP nodes to `audio-engine`. `pattern-engine` sequences control messages via OSC (both siblings in this monorepo).

```bash
# Terminal 1: run audio-engine with FAUST nodes + hot reload
# (binary wiring is up to your application)

# Terminal 2: run pattern-engine
cd ../pattern-engine && MIDIMAN_OSC_TARGET=127.0.0.1:9000 cargo run

# Terminal 3: sequence a FAUST node's parameters
echo '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[
  {"op":"Atom","value":{"type":"Osc","address":"/audio/set","args":[{"Str":"cutoff"},{"Float":500.0}]}},
  {"op":"Atom","value":{"type":"Osc","address":"/audio/set","args":[{"Str":"cutoff"},{"Float":2000.0}]}},
  {"op":"Atom","value":{"type":"Osc","address":"/audio/set","args":[{"Str":"cutoff"},{"Float":8000.0}]}}
]}}' | socat - UNIX-CONNECT:/tmp/krach.sock
```

## Graph IR

Reference a FAUST node in audio-engine's JSON graph format:

```json
{
  "nodes": [
    {"id": "osc", "type_id": "faust:sine", "controls": {"freq": 440.0}},
    {"id": "filt", "type_id": "faust:lowpass", "controls": {"cutoff": 1000.0, "q": 2.0}},
    {"id": "out", "type_id": "dac", "controls": {}}
  ],
  "connections": [
    {"from_node": "osc", "from_port": "out", "to_node": "filt", "to_port": "in0"},
    {"from_node": "filt", "from_port": "out", "to_node": "out", "to_port": "in"}
  ],
  "exposed_controls": {
    "freq": ["osc", "freq"],
    "cutoff": ["filt", "cutoff"]
  }
}
```

Port names are derived from channel count: `in`/`out` for mono, `in0`/`in1`/`out0`/`out1` for stereo, etc.

## Development

```bash
cargo check    # type check (strict clippy: all + pedantic + nursery)
cargo test     # 14 tests (serialized — FAUST LLVM JIT not thread-safe)
```

Requires libfaust linked at build time (`build.rs` handles homebrew paths on macOS).

## License

MIT
