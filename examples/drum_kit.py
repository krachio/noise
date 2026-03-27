"""drum_kit.py -- kick, snare, hat with swing.

Run from the krach REPL:
    kr.load("examples/drum_kit.py")
"""

from krach import signal as krs


def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9


def snare() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.12, 0.0, 0.05, gate)
    body = krs.sine_osc(180.0) * env
    noise = krs.highpass(krs.white_noise(), 2000.0) * env * 0.6
    return (body + noise) * 0.7


def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5


# Build nodes
with kr.batch():
    kr.node("drums/kick", kick, gain=0.8)
    kr.node("drums/snare", snare, gain=0.6)
    kr.node("drums/hat", hat, gain=0.5)

# Patterns
kr.tempo = 128
kr.play("drums/kick", kr.hit() * 4)
kr.play("drums/snare", (kr.rest() + kr.hit()) * 2)
kr.play("drums/hat", (kr.rest() + kr.hit()) * 4, swing=0.67)
