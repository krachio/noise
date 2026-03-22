# Ralph Review Sprint 7

## Completed (sprint 6)
- [x] STOP_MISSES_POLY — krach/_mixer.py:300
- [x] HOT_PATH_ALLOC — soundman-core/src/graph/mod.rs:188-195
- [x] STEP_LABEL_TYPO — noise-engine/src/main.rs:332,335
- [x] POLY_PREFIX_COLLISION — krach/_mixer.py:303
- [x] NOTE_DUR_PANIC — noise-engine/src/main.rs:312
- [x] CROSSFADE_DROP_ON_RT — soundman-core/src/swap/mod.rs:128

## Sprint 7
- [x] NEGATIVE_DEN_WRAP — midiman/src/ir/validate.rs:84 — reject negative denominators (pair[1] <= 0)

## Sprint 7 — adversarial (deferred, theoretical-only)
These are theoretically reachable overflow paths in Time arithmetic but practically unreachable — musical time values are small rationals. GCD reduction keeps denominators small. Adding overflow checks would clutter hot-path code for scenarios that can't occur from the Python REPL.
- Time::reduce128 truncation on u128→u64/i64 downcast (time.rs:59-65)
- cross_add i128 overflow for extreme inputs (time.rs:52-55)
- floor() den cast wraps for den > i64::MAX (time.rs:110-113)
- Unbounded query recursion (query.rs:18 — depth bounded by frontend DSL)
