# Ralph Review Sprint 4

- [ ] POLY_RE_REGISTER_LEAK — krach/_mixer.py:262 — calling poly() twice leaks old _v0..vN entries in _voices. remove() crashes with KeyError on poly names. Fix poly lifecycle.
- [ ] DUPLICATED_DSP_RESOLVE — krach/_mixer.py:199 vs 244 — voice() and poly() have identical 11-line DSP source resolution. Extract function.
- [ ] GRAPHBATCH_SILENT_DROP — soundman-core/engine/mod.rs:252 — apply_mutation silently drops SetControl, LoadGraph, Shutdown inside GraphBatch. Reject or handle explicitly.
- [ ] MIDI_EVENT_LOSS — noise-engine/main.rs:279-289 — MIDI notes with fire_at > now but <= now+LOOKAHEAD are drained from heap but never dispatched. Events lost.
- [ ] WAIT_FOR_TYPE_SILENT_FAIL — krach/_mixer.py:407-419 — _wait_for_type returns silently on timeout. Should raise so caller knows the type never appeared.
