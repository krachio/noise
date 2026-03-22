# Ralph Review Sprint 10

## Sprint 10 — review
No new code issues found. Review clean.

## Sprint 10 — adversarial fixes
- [x] GAIN_POLY_PARENT — krach/_mixer.py:317 — gain() on poly parent now distributes across instances
- [x] REMOVE_MISSING — krach/_mixer.py:275 — remove() raises ValueError for missing voices (was KeyError)
- [x] STEP_MISSING — krach/_mixer.py:376 — _alloc_voice() raises ValueError for missing names (was KeyError)
- [x] VOICE_POLY_COLLISION — krach/_mixer.py:225 — voice() over existing poly cleans up poly state first
