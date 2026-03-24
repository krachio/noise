"""krach DSP music library: envelopes, effects, spatial, scales."""

from krach.dsl.music.effects import chorus, echo, flanger, reverb
from krach.dsl.music.envelopes import adsr, ar, decay, edge_trigger, latch, trigger
from krach.dsl.music.scales import freq_to_midi, midi_to_freq
from krach.dsl.music.spatial import pan, stereo_width

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
