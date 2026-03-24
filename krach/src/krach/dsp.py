"""krach.dsp — synthesis primitives. Import as: import krach.dsp as krs"""

# Core types
from faust_dsl import Signal as Signal, control as control, transpile as transpile

# Oscillators
from faust_dsl.lib.oscillators import (
    sine_osc as sine_osc,
    saw as saw,
    square as square,
    phasor as phasor,
)

# Filters
from faust_dsl.lib.filters import (
    lowpass as lowpass,
    highpass as highpass,
    bandpass as bandpass,
)

# Noise
from faust_dsl.lib.noise import white_noise as white_noise

# Envelopes + effects
from faust_dsl.music.envelopes import adsr as adsr
from faust_dsl.music.effects import reverb as reverb

# DSP primitives: delay, memory, feedback, sample rate
from faust_dsl import (
    delay as delay,
    mem as mem,
    feedback as feedback,
    sr as sr,
    sample_rate as sample_rate,
    unit_delay as unit_delay,
    faust_expr as faust_expr,
    select2 as select2,
)

# Math (unary)
from faust_dsl import (
    sin as sin,
    cos as cos,
    tan as tan,
    asin as asin,
    acos as acos,
    atan as atan,
    exp as exp,
    log as log,
    log10 as log10,
    sqrt as sqrt,
    abs_ as abs_,
    floor as floor,
    ceil as ceil,
)

# Math (binary)
from faust_dsl import (
    min_ as min_,
    max_ as max_,
    pow_ as pow_,
    fmod as fmod,
    atan2 as atan2,
)
