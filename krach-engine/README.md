# krach-engine

Unified binary merging the pattern sequencer, audio engine, and FAUST JIT compiler into a single process.

This is the Rust binary that `krach` (the Python REPL) starts automatically. It listens on a Unix socket (`$TMPDIR/krach-engine.sock`) for JSON commands from the Python frontend.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              krach-engine                │
Unix socket ──────▶ │  ┌──────────────┐  ┌──────────────────┐ │
$TMPDIR/krach-engine.sock     │  │ pattern-     │  │ audio-engine     │ │
  JSON commands     │  │ engine       │──▶ graph + swapper  │──▶ CoreAudio
                    │  │ (sequencer)  │  │ + automation     │ │
                    │  └──────────────┘  └──────────────────┘ │
                    │                    ┌──────────────────┐ │
                    │                    │ audio-faust      │ │
  ~/.krach/dsp/ ────▶────────────────────▶ (LLVM JIT,      │ │
  .dsp hot reload   │                    │  hot reload)     │ │
                    │                    └──────────────────┘ │
                    └─────────────────────────────────────────┘
```

## Main loop

The main loop runs ~1000 iterations/sec:

1. Drain IPC commands (pattern changes, graph loads, automation)
2. Fill pattern heap (evaluate patterns for upcoming cycles)
3. Compile control-voice curves (block-rate wavetables)
4. Dispatch pending events (sample-accurate timing)
5. Poll FAUST hot reload
6. Drain MIDI note-offs
7. MIDI clock + CC input
8. Sleep until next event

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `NOISE_DSP_DIR` | `~/.krach/dsp` | FAUST .dsp file directory |
| `NOISE_SOCKET` | `$TMPDIR/krach-engine.sock` | IPC socket path |
| `NOISE_MIDI_CLOCK` | off | Set to `1` for 24 ppqn MIDI clock |

## Development

```bash
cargo build -p krach-engine
cargo test -p krach-engine
```

## License

MIT
