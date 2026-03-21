The audit reveals a deeper issue than just "reuse nodes" — it's about real-time safety and state preservation across graph swaps. Here's the full picture:

  ---
  Three flaws solved by one refactor

  Flaw 1: Node state loss on graph swap
  Every compile() creates fresh DSP instances. Existing voices lose their ADSR phase, filter memory, reverb tails. This is the audible gap you hear.

  Flaw 2: Deallocation on the audio thread
  self.retiring = None drops the old graph (with all its FAUST LLVM JIT nodes, heap buffers) directly on the CoreAudio callback thread. This is a real-time safety violation — allocator
  calls can block for unbounded time.

  Flaw 3: No factory version tracking
  When a FAUST .dsp is hot-reloaded (reregister()), the registry replaces the factory but existing compiled nodes use the old code. If we naively reuse nodes, we'd keep stale FAUST code
   after hot-reload.

  ---
  The fix: return channel + versioned node reuse

  BEFORE:
    Control thread: compile(ir) → SwapGraph(new) → [ring buffer →] Audio thread
    Audio thread:   swap, crossfade, DROP old graph ← RT safety violation + state lost

  AFTER:
    Control thread: compile_with_reuse(ir, old_graph) → SwapGraph(new) → Audio thread
    Audio thread:   swap, crossfade, RETURN old graph → [return buffer →] Control thread
    Control thread: receives old graph → extracts nodes for next compile

  Key additions:
  - Registry version counter: register() / reregister() bump a per-type version. Nodes are only reused if type_id AND version match.
  - DspGraph.into_nodes(): consumes graph, returns HashMap<id, (type_id, version, Box<dyn DspNode>)>
  - compile_with_reuse(): takes optional previous graph, reuses matching nodes, creates fresh for new/changed ones
  - Return ring buffer (audio→control): retired graphs sent back for reuse, deallocation happens off the audio thread

  ---
  Plan (4 commits)

  Commit 1: Registry version tracking (~20 lines + tests)
  - versions: HashMap<String, u64> in NodeRegistry
  - Bumped on register() and reregister()
  - Test: version increments on reregister, different types have independent versions

  Commit 2: DspGraph.into_nodes + compile_with_reuse (~80 lines + tests)
  - DspGraph gains node_type_ids: Vec<String>, node_versions: Vec<u64>
  - into_nodes(self) extracts nodes for reuse
  - compile_with_reuse(ir, registry, previous, sr, bs) reuses matching nodes
  - Tests: node reused when same type+version, fresh when type changed, fresh when version bumped

  Commit 3: Return channel + engine wiring (~50 lines + tests)
  - Second SPSC ring buffer (audio→control) for returning retired graphs
  - GraphSwapper sends retired graph back instead of dropping
  - EngineController drains returned graphs, passes to compile_with_reuse
  - Test: end-to-end — graph swap preserves node state for unchanged voices

  Commit 4: VoiceMixer.batch() (~30 lines + tests)
  - Context manager for batching voice declarations
  - Writes all .dsp files first, waits for all types, one rebuild
  - Test: batch produces single rebuild

  ---
  What this fixes for the user

  # BEFORE: 8 voices = 8 gaps, all voices restarted fresh each time
  mix.voice("kick", house_kick, gain=0.88)   # other voices go silent
  mix.voice("bass", deep_bass, gain=0.58)    # kick goes silent, restarts

  # AFTER: 8 voices = 8 crossfades, but each preserves all existing state
  mix.voice("kick", house_kick, gain=0.88)   # kick plays
  mix.voice("bass", deep_bass, gain=0.58)    # kick keeps playing, bass joins seamlessly

  # EVEN BETTER with batch():
  with mix.batch():
      mix.voice("kick", house_kick, gain=0.88)
      mix.voice("bass", deep_bass, gain=0.58)
      # ... 8 voices
  # ONE crossfade, all voices start together

  This is ~175 lines of Rust + ~30 lines of Python. It's a real architectural improvement, not a workaround. Proceed?
