# Ralph Review Sprint 12

## Sprint 12 — review + implementation
- [x] SOCKET_TIMEOUT — session.py:136 — send() blocks forever if engine dies; add socket timeout + descriptive error
- [x] MUTE_SOLO — _mixer.py — missing mute()/unmute()/solo() — fundamental live performance ops
- [x] FADE_CANCEL_OLD — _mixer.py:473 — fade() reads stale bookkeeping gain, doesn't cancel previous fade; audible jumps
- [x] BATCH_EXCEPTION — _mixer.py:503 — batch() finally flushes on exception, corrupting graph state
- [x] OVER_ZERO_VALIDATION — pattern.py:68 — over(0)/scale(0) give confusing internal IR errors; validate at entry point

## Sprint 12 — ergonomics pass
- [x] UNIFIED_NOTE — merge step()+chord() into note(*pitches, vel=1.0, **params)
- [x] PITCH_HELPERS — mtof()/ftom() + note constants C0-B8
- [x] SCALE_TO_FAST — rename scale() → fast() on Pattern + Transform
- [x] MIX_PLAY — mix.play(name, pattern) delegation to Session
- [x] WIRE_EXPORTS — mtof/ftom/notes in REPL namespace, context.md updated

## Sprint 12 — adversarial fixes
- [x] DOUBLE_MUTE — mute() twice overwrites saved gain with 0; guard with early return
- [x] SOLO_CLOBBER — solo() clobbers previously-muted voices; mute() now no-ops if already muted
- [x] BATCH_ROLLBACK — batch() exception left ghost voices; now snapshots/restores on error
- [x] FTOM_RANGE — ftom() returned values outside 0-127; now clamped
- [x] FAST_INF_NAN — fast()/over() with inf/nan gave confusing Fraction errors; now validated

---

## Completed Sprints

### Sprint 11 — review + implementation
- [x] STALE_SOCKET — krach/__init__.py:49 — _cleanup now wait/kill/unlink
- [x] STEP_SILENT_PITCH — krach/_mixer.py:117 — ValueError when pitch given but no freq control
- [x] STALE_CACHED_NODES — krach/__init__.py:96 — reads from mix._node_controls
- [x] SEQ_SHORTHAND — krach/_mixer.py:372 — mix.seq() for melodic sequences

### Sprint 11 — adversarial fixes
- [x] GAIN_MISSING_VOICE — gain() on nonexistent voice now raises ValueError
- [x] POLY_OVER_MONO — poly() replacing mono voice now hushes and deletes old entry
- [x] VOICE_REPLACE_FADE — voice() replacing existing mono now hushes old fade
- [x] GAIN_NAN_INF — _check_finite() validates gain and pitch values
- [x] FADE_MISSING_VOICE — fade() on nonexistent voice raises ValueError
- [x] PITCH_NAN_INF — build_step() validates pitch is finite
