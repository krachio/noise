# Ralph Review Sprint 11

## Sprint 11 — review + implementation
- [x] STALE_SOCKET — krach/__init__.py:49 — _cleanup now wait/kill/unlink
- [x] STEP_SILENT_PITCH — krach/_mixer.py:117 — ValueError when pitch given but no freq control
- [x] STALE_CACHED_NODES — krach/__init__.py:96 — reads from mix._node_controls
- [x] SEQ_SHORTHAND — krach/_mixer.py:372 — mix.seq() for melodic sequences

## Sprint 11 — adversarial fixes
- [x] GAIN_MISSING_VOICE — gain() on nonexistent voice now raises ValueError
- [x] POLY_OVER_MONO — poly() replacing mono voice now hushes and deletes old entry
- [x] VOICE_REPLACE_FADE — voice() replacing existing mono now hushes old fade
- [x] GAIN_NAN_INF — _check_finite() validates gain and pitch values
- [x] FADE_MISSING_VOICE — fade() on nonexistent voice raises ValueError
- [x] PITCH_NAN_INF — build_step() validates pitch is finite
