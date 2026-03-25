"""krach IR — specification layer for the audio graph.

All IRs live here:
- primitive: Primitive (shared by signal and pattern domains)
- signal: Signal, Equation, DspGraph, params (DSP computation)
- pattern: PatternNode, PatternPrimitive (temporal sequencing)
- values: Note, Cc, Osc, Control, Value (pattern value types)
- canonicalize: canonicalize(), graph_key()
- registry: RuleRegistry (generic rule registration)
"""

from krach.ir.primitive import Primitive as Primitive
from krach.ir.signal import Signal as Signal, Equation as Equation, DspGraph as DspGraph
from krach.ir.pattern import PatternNode as PatternNode
from krach.ir.values import Value as Value
