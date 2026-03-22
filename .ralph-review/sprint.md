# Ralph Review Sprint 9 (continued)

## Open from previous adversarial pass
- [ ] FADE_LIFECYCLE — krach/_mixer.py — hush() should also hush _fade_{name}. This fixes stop(), remove(), and re-poly() fade leaks in one place. Additionally: remove() for poly must hush per-instance fades; re-poly() must hush old instance patterns.
