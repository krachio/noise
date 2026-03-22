# Ralph Review Sprint 8

## Completed (sprint 7)
- [x] NEGATIVE_DEN_WRAP — midiman/src/ir/validate.rs:84

## Sprint 8 — review
No new issues found in code review (second consecutive clean review).

## Sprint 8 — adversarial fixes
- [x] FADE_SURVIVES_REMOVE — krach/_mixer.py:275 — remove() now also hushes _fade_{name}
- [x] CHORD_EXCEEDS_VOICES — krach/_mixer.py:345 — chord() raises ValueError when pitches > voice count
- [x] REPOLY_STALE_PATTERNS — krach/_mixer.py:259 — re-poly() now hushes old parent pattern before cleanup

## Sprint 8 — deferred (low practical impact)
- Stale pending control events survive LoadGraph (noise-engine: produces warnings, not crashes)
- control_values grows unbounded across LoadGraph label churn (slow growth, ~50 labels/session max)
- Pattern engine slot table only grows (slow growth, ~20 slots/session max)
