# Ralph Review Sprint 11

## Completed (sprint 10)
- [x] GAIN_POLY_PARENT — gain() on poly parent distributes across instances
- [x] REMOVE_MISSING — remove() raises ValueError for missing voices
- [x] STEP_MISSING — _alloc_voice() raises ValueError for missing names
- [x] VOICE_POLY_COLLISION — voice() over existing poly cleans up poly state

## Sprint 11
- [ ] STALE_SOCKET — krach/__init__.py:49 — _cleanup doesn't wait() on engine proc or unlink socket. Crash leaves stale socket, next launch connects to dead file.
- [ ] STEP_SILENT_PITCH — krach/_mixer.py:119 — step() silently ignores pitch when voice lacks "freq" control. Should warn.
- [ ] STALE_CACHED_NODES — krach/__init__.py:149 — _cached_nodes never refreshed after new @dsp voices. status()/copilot see outdated types. Fix: read from mixer or refresh on access.
- [ ] SEQ_SHORTHAND — krach/_mixer.py — mix.seq("bass", [55, 73, None, 65]) shorthand for melodic sequences. Biggest UX win.
