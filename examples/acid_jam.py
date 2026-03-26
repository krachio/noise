"""acid_jam.py -- synth + drums + effects + scenes.

Run from the krach REPL:
    kr.load("examples/acid_jam.py")
"""

import krach.dsp as krs


# -- DSP definitions --


def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9


def hat() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.04, 0.0, 0.02, gate)
    return krs.highpass(krs.white_noise(), 8000.0) * env * 0.5


def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    filt_env = krs.adsr(0.005, 0.2, 0.2, 0.1, gate)
    return krs.lowpass(krs.saw(freq), cutoff + filt_env * 1200.0) * env * 0.55


def reverb_fx(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room) * 0.8


# -- Build the graph --

with kr.batch():
    k = kr.node("kick", kick, gain=0.8)
    h = kr.node("hat", hat, gain=0.5)
    bass = kr.node("bass", acid_bass, gain=0.3)

verb = kr.node("verb", reverb_fx, gain=0.3)
bass >> (verb, 0.4)

# -- Transport --

kr.tempo = 133
kr.meter = 4

# -- Verse --

k @ (kr.hit() * 4)
h @ ((kr.rest() + kr.hit()) * 4).swing(0.67)
bass @ kr.seq("A2", "D3", None, "E2").over(2)
bass @ ("cutoff", kr.sine(400, 2000).over(4))

kr.save("verse")

# -- Chorus: double-time hats, higher bass line --

h @ (kr.hit() * 8)
bass @ kr.seq("A3", "C3", "E3", "G3")
bass["cutoff"] = 2000

kr.save("chorus")

# -- Switch between scenes --
# kr.recall("verse")
# kr.recall("chorus")
# with kr.transition(bars=4):
#     kr.recall("verse")
