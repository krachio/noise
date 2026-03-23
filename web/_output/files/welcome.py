# krach — live coding audio
#
# This is a browser-based demo using Web Audio API.
# Synthesis uses built-in oscillators (sine, saw, square).
# For the full experience with FAUST JIT, install krach locally.
#
# Try running each cell (Shift+Enter):

# ── Cell 1: Connect ──
from krach._web_audio import connect_web
kr = connect_web(bpm=120, master=0.7)
print("Connected to Web Audio!")

# ── Cell 2: Play a kick ──
kr.voice("kick", "oscillator", gain=0.8)
kr.play("kick", kr.hit() * 4)
print("4-on-the-floor kick playing")

# ── Cell 3: Add a bass line ──
kr.voice("bass", "oscillator", gain=0.3)
kr.play("bass", kr.seq("A2", "D3", None, "E2").over(2))
print("Bass line playing")

# ── Cell 4: Add swing ──
kr.play("kick", (kr.hit() * 8).swing(0.67))
print("Swung kick!")

# ── Cell 5: Pattern algebra ──
pattern = kr.seq("C4", "E4", "G4", None)
kr.play("bass", (pattern + pattern.reverse()).over(4))
print("Pattern with reverse every other bar")

# ── Cell 6: Stop ──
kr.stop()
print("Silence.")
