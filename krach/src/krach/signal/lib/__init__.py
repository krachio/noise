"""krach DSP standard library: oscillators, filters, noise, utilities."""

from krach.signal.lib.filters import bandpass, dcblock, highpass, lowpass, onepole, resonant
from krach.signal.lib.noise import pink_noise, white_noise
from krach.signal.lib.oscillators import lfo, phasor, pulse, saw, sine_osc, square, triangle, wavetable
from krach.signal.lib.utilities import clip, db_to_linear, lerp, linear_to_db, smooth, wrap

__all__ = [
    "bandpass",
    "clip",
    "db_to_linear",
    "dcblock",
    "highpass",
    "lerp",
    "lfo",
    "linear_to_db",
    "lowpass",
    "onepole",
    "phasor",
    "pink_noise",
    "pulse",
    "resonant",
    "saw",
    "sine_osc",
    "smooth",
    "square",
    "triangle",
    "wavetable",
    "white_noise",
    "wrap",
]
