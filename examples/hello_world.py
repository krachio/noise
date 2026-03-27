"""hello_world.py -- one sound, one pattern.

Run from the krach REPL:
    kr.load("examples/hello_world.py")
"""

from krach import signal as krs


def sine_beep() -> krs.Signal:
    freq = krs.control("freq", 440.0, 20.0, 2000.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.01, 0.1, 0.3, 0.2, gate)
    return krs.sine_osc(freq) * env * 0.5


kr.node("beep", sine_beep, gain=0.5)
kr.play("beep", kr.seq("C4", "E4", "G4", "C5").over(2))
kr.tempo = 120
