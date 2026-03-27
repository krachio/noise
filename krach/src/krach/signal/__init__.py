"""krach.signal — DSP namespace for live coding.

Import as: from krach import signal as krs

Aggregates oscillators, filters, noise, envelopes, effects, math, and
core DSP primitives (control, delay, feedback, sr) from krach.signal/.
Also exports Signal type and transpile/control from the tracing layer.
"""

# Core types
from krach.signal.types import Signal as Signal
from krach.signal.transpile import control as control, transpile as transpile

# Oscillators
from krach.signal.lib import (
    lfo as lfo,
    phasor as phasor,
    pulse as pulse,
    saw as saw,
    sine_osc as sine_osc,
    square as square,
    triangle as triangle,
    wavetable as wavetable,
)

# Filters
from krach.signal.lib import (
    bandpass as bandpass,
    dcblock as dcblock,
    highpass as highpass,
    lowpass as lowpass,
    onepole as onepole,
    resonant as resonant,
)

# Noise
from krach.signal.lib import pink_noise as pink_noise, white_noise as white_noise

# Effects
from krach.signal.lib import passthrough as passthrough

# Utilities
from krach.signal.lib import (
    clip as clip,
    db_to_linear as db_to_linear,
    lerp as lerp,
    linear_to_db as linear_to_db,
    smooth as smooth,
    wrap as wrap,
)

# Envelopes
from krach.signal.music import (
    adsr as adsr,
    ar as ar,
    decay as decay,
    edge_trigger as edge_trigger,
    latch as latch,
    trigger as trigger,
)

# Music effects
from krach.signal.music import (
    chorus as chorus,
    echo as echo,
    flanger as flanger,
    reverb as reverb,
)

# Scales
from krach.signal.music import (
    freq_to_midi as freq_to_midi,
    midi_to_freq as midi_to_freq,
)

# Spatial
from krach.signal.music import (
    pan as pan,
    stereo_width as stereo_width,
)

# DSP primitives: delay, memory, feedback, sample rate
from krach.signal.core import (
    delay as delay,
    faust_expr as faust_expr,
    feedback as feedback,
    mem as mem,
    sample_rate as sample_rate,
    select2 as select2,
    sr as sr,
    unit_delay as unit_delay,
)

# Math (unary)
from krach.signal.core import (
    abs_ as abs_,
    acos as acos,
    asin as asin,
    atan as atan,
    ceil as ceil,
    cos as cos,
    exp as exp,
    floor as floor,
    log as log,
    log10 as log10,
    round_ as round_,
    sin as sin,
    sqrt as sqrt,
    tan as tan,
)

# Math (binary)
from krach.signal.core import (
    atan2 as atan2,
    fmod as fmod,
    max_ as max_,
    min_ as min_,
    pow_ as pow_,
    remainder as remainder,
)

__all__ = [
    # Types
    "Signal",
    "control",
    "transpile",
    # Oscillators
    "lfo",
    "phasor",
    "pulse",
    "saw",
    "sine_osc",
    "square",
    "triangle",
    "wavetable",
    # Filters
    "bandpass",
    "dcblock",
    "highpass",
    "lowpass",
    "onepole",
    "resonant",
    # Noise
    "pink_noise",
    "white_noise",
    # Effects
    "passthrough",
    # Utilities
    "clip",
    "db_to_linear",
    "lerp",
    "linear_to_db",
    "smooth",
    "wrap",
    # Envelopes
    "adsr",
    "ar",
    "decay",
    "edge_trigger",
    "latch",
    "trigger",
    # Music effects
    "chorus",
    "echo",
    "flanger",
    "reverb",
    # Scales
    "freq_to_midi",
    "midi_to_freq",
    # Spatial
    "pan",
    "stereo_width",
    # DSP primitives
    "delay",
    "faust_expr",
    "feedback",
    "mem",
    "sample_rate",
    "select2",
    "sr",
    "unit_delay",
    # Math (unary)
    "abs_",
    "acos",
    "asin",
    "atan",
    "ceil",
    "cos",
    "exp",
    "floor",
    "log",
    "log10",
    "round_",
    "sin",
    "sqrt",
    "tan",
    # Math (binary)
    "atan2",
    "fmod",
    "max_",
    "min_",
    "pow_",
    "remainder",
]
