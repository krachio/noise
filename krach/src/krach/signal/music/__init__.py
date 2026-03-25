"""krach DSP music library: envelopes, effects, spatial, scales."""

from krach.signal.music.effects import chorus, echo, flanger, reverb
from krach.signal.music.envelopes import adsr, ar, decay, edge_trigger, latch, trigger
from krach.signal.music.scales import freq_to_midi, midi_to_freq
from krach.signal.music.spatial import pan, stereo_width

__all__ = [
    "adsr",
    "ar",
    "chorus",
    "decay",
    "echo",
    "edge_trigger",
    "flanger",
    "freq_to_midi",
    "latch",
    "midi_to_freq",
    "pan",
    "reverb",
    "stereo_width",
    "trigger",
]
