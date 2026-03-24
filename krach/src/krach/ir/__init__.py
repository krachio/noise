"""krach IR — specification layer for the audio graph.

All IRs live here:
- signal: DspGraph, Signal, SignalPrimitive, SignalEqn (DSP computation)
- pattern: PatternNode, PatternPrimitive (temporal sequencing) [future]
- module: ModuleIr, NodeDef, RouteDef (session specification)
"""
