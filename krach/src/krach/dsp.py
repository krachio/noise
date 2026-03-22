"""krach.dsp — synthesis primitives. Import as: import krach.dsp as krs"""

from faust_dsl import Signal as Signal, control as control, transpile as transpile
from faust_dsl.lib.oscillators import (
    sine_osc as sine_osc,
    saw as saw,
    square as square,
    phasor as phasor,
)
from faust_dsl.lib.filters import (
    lowpass as lowpass,
    highpass as highpass,
    bandpass as bandpass,
)
from faust_dsl.lib.noise import white_noise as white_noise
from faust_dsl.music.envelopes import adsr as adsr
from faust_dsl.music.effects import reverb as reverb
