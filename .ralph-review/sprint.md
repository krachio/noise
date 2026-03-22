# Ralph Review Sprint 6

## Completed (previous sprints)
- [x] BPM_VALIDATION — midiman/engine.rs:142 + noise-engine/main.rs:42 — SetBpm with 0/negative/NaN/Inf guarded
- [x] FLUSH_REDUNDANT_WAITS — krach/_mixer.py:401 — _flush deduplicates by type_id

## Sprint 6 — review fixes
- [x] STOP_MISSES_POLY — krach/_mixer.py:300 — stop() now hushes poly parent slots before individual instances
- [x] HOT_PATH_ALLOC — soundman-core/src/graph/mod.rs:188-195 — SmallVec<[_; 4]> eliminates heap allocation for ≤4 port nodes
- [x] STEP_LABEL_TYPO — noise-engine/src/main.rs:332,335 — Fixed duplicate ⑦ labels to ⑦, ⑧, ⑨

## Sprint 6 — adversarial fixes
- [x] POLY_PREFIX_COLLISION — krach/_mixer.py:303 — Exact instance name set instead of startswith. Prevents "pad_vinyl" being skipped when poly "pad" exists.
- [x] NOTE_DUR_PANIC — noise-engine/src/main.rs:312 — Guard with .max(0.0) + is_finite. NaN/negative/Inf dur no longer panics.
- [x] CROSSFADE_DROP_ON_RT — soundman-core/src/swap/mod.rs:128 — begin_swap() during crossfade now moves old retiring to retired_ready before overwriting. RT-safe dealloc preserved.
