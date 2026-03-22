# Ralph Review Sprint 5

- [ ] BPM_VALIDATION — midiman/engine.rs:142 + noise-engine/main.rs:42 — SetBpm with 0 or negative causes division by zero. Add guard: bpm must be > 0.
- [ ] FLUSH_REDUNDANT_WAITS — krach/_mixer.py:397-401 — _flush iterates _voices and calls _wait_for_type per instance. 4 poly voices = 4 redundant waits for same type. Deduplicate by collecting unique type_ids first.
