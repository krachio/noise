"""krach.dsp — DSP namespace for live coding. Import as: import krach.dsp as krs

Aggregates oscillators, filters, noise, envelopes, effects, math, and
core DSP primitives (control, delay, feedback, sr) from krach.signal/.
Also exports Signal type and transpile/control from the tracing layer.
"""

# Core types
from krach.signal.types import Signal as Signal
from krach.signal.transpile import control as control, transpile as transpile

# Oscillators
from krach.signal.lib import (
    sine_osc as sine_osc,
    saw as saw,
    square as square,
    phasor as phasor,
)

# Filters
from krach.signal.lib import (
    lowpass as lowpass,
    highpass as highpass,
    bandpass as bandpass,
)

# Noise
from krach.signal.lib import white_noise as white_noise

# Envelopes + effects
from krach.signal.music import adsr as adsr
from krach.signal.music import reverb as reverb

# DSP primitives: delay, memory, feedback, sample rate
from krach.signal.core import (
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
from krach.signal.core import (
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
    round_ as round_,
)

# Math (binary)
from krach.signal.core import (
    min_ as min_,
    max_ as max_,
    pow_ as pow_,
    fmod as fmod,
    remainder as remainder,
    atan2 as atan2,
)
