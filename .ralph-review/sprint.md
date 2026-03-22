# Ralph Review Sprint 13

## Sprint 13 — review + implementation
- [ ] MUTED_LEAK — _mixer.py:306,229,266 — remove()/voice()/poly() don't clean _muted; stale gain restored on re-add
- [ ] SEND_JSON_TIMEOUT — session.py:149 — _send_json() doesn't catch socket.timeout; raw exception escapes
- [ ] MIXER_REPR — _mixer.py:181 — VoiceMixer has no __repr__; `mix` shows <object> in REPL
- [ ] UNSOLO — _mixer.py — no unsolo(); performer stuck after solo() with no quick way to restore all
- [ ] THIN_DOCSTRING — pattern.py:109 — thin() has no docstring; prob semantics ambiguous (0.3 = drop 30%)

## Sprint 13 — adversarial
(to be filled after implementation)

---

## Completed Sprints

### Sprint 12 — review + implementation
- [x] SOCKET_TIMEOUT — session.py:136 — send() blocks forever if engine dies; add socket timeout + descriptive error
- [x] MUTE_SOLO — _mixer.py — missing mute()/unmute()/solo() — fundamental live performance ops
- [x] FADE_CANCEL_OLD — _mixer.py:473 — fade() reads stale bookkeeping gain, doesn't cancel previous fade; audible jumps
- [x] BATCH_EXCEPTION — _mixer.py:503 — batch() finally flushes on exception, corrupting graph state
- [x] OVER_ZERO_VALIDATION — pattern.py:68 — over(0)/scale(0) give confusing internal IR errors; validate at entry point

### Sprint 12 — ergonomics pass
- [x] UNIFIED_NOTE — merge step()+chord() into note(*pitches, vel=1.0, **params)
- [x] PITCH_HELPERS — mtof()/ftom() + note constants C0-B8
- [x] SCALE_TO_FAST — rename scale() → fast() on Pattern + Transform
- [x] MIX_PLAY — mix.play(name, pattern) delegation to Session
- [x] WIRE_EXPORTS — mtof/ftom/notes in REPL namespace, context.md updated

### Sprint 12 — adversarial fixes
- [x] DOUBLE_MUTE — mute() twice overwrites saved gain with 0; guard with early return
- [x] SOLO_CLOBBER — solo() clobbers previously-muted voices; mute() now no-ops if already muted
- [x] BATCH_ROLLBACK — batch() exception left ghost voices; now snapshots/restores on error
- [x] FTOM_RANGE — ftom() returned values outside 0-127; now clamped
- [x] FAST_INF_NAN — fast()/over() with inf/nan gave confusing Fraction errors; now validated
