# IR Architecture

krach has three typed IRs that compose hierarchically. Understanding them is essential for contributing to the codebase.

## The three IRs

```
ModuleIr (top-level — session specification)
├── NodeDef.source → DspGraph (signal computation)
├── PatternDef.pattern → PatternNode (temporal sequencing)
├── RouteDef (graph topology)
└── SubModule → ModuleIr (recursion)
```

**Signal IR** (`ir/signal.py`): A flat DAG of equations. Each equation has a primitive, typed inputs/outputs (`Signal`), and params. `DspGraph` is the container — like a jaxpr. Used for DSP: oscillators, filters, envelopes.

**Pattern IR** (`ir/pattern.py`): A tree of temporal operations. Each `PatternNode` has a primitive, children (sub-trees), and params. Nesting IS the temporal semantics — a `Cat` node sequences its children, a `Stack` layers them. Used for: rhythms, melodies, modulation.

**Module IR** (`ir/module.py`): A flat record of definitions. `ModuleIr` specifies a complete audio session: which nodes exist, how they're connected, what patterns play, what controls are set. This is the top-level "jaxpr" — it contains DspGraphs and PatternNodes as sub-computations.

## Shared infrastructure

**Primitive** (`ir/primitive.py`): One frozen dataclass shared by both signal and pattern domains. Just a name + `stateful` flag. No behavior — rules are registered externally.

**RuleRegistry** (`ir/registry.py`): Generic `RuleRegistry[P, R]` for registering per-primitive rules. Four instances exist:
- `abstract_eval` in `signal/primitives.py` — type inference during signal tracing
- `lowering` in `backends/faust_lowering.py` — signal IR → FAUST code
- `serialize` in `pattern/serialize.py` — pattern IR → dict
- `summary` in `pattern/summary.py` — pattern IR → human-readable string

All registries support `check_complete()` to verify every primitive has a rule at import time.

**Values** (`ir/values.py`): Leaf types carried by pattern atoms: `Note`, `Cc`, `Osc`, `Control`. Shared by pattern IR and serialization.

## Signal tracing

Signal DSP functions are traced, not interpreted. When you write:

```python
def bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    return krs.lowpass(krs.saw(freq), 800.0)
```

The function runs once against `Signal` proxy objects. Each operation (`saw`, `lowpass`, `control`) calls `bind()` which records an `Equation` into the `TraceContext`. The result is a `DspGraph` — a flat list of equations with explicit data flow.

This is the same model as JAX's `make_jaxpr`: trace Python → produce IR → lower to backend.

The tracing runtime lives in `signal/trace.py`. Signal primitives + abstract_eval rules live in `signal/primitives.py`. The IR types (`Signal`, `Equation`, `DspGraph`) live in `ir/signal.py` — pure frozen data.

## Pattern building

Patterns are built directly — no tracing needed. `note("C4") + note("E4")` directly constructs `PatternNode(cat_p, (freeze_node, freeze_node), CatParams())`. The Python expression IS the tree.

This works because patterns are trees (not graphs with sharing), so direct construction produces the right shape. Pattern primitives + serialize rules live in `pattern/primitives.py`. The IR types live in `ir/pattern.py`.

## Canonicalization & caching

`ir/canonicalize.py` provides:
- `canonicalize(graph)` — alpha-rename signal IDs to sequential integers
- `graph_key(graph)` — structural hash of a canonicalized DspGraph

Two DspGraphs that compute the same thing (regardless of signal ID assignment) produce the same `graph_key`. This is the cache key for FAUST compilation — identical graphs share compiled binaries.

## Dependency layering

```
ir/         → stdlib only (pure data)
signal/     → ir/ (tracing + DSL)
pattern/    → ir/ (building + DSL)
backends/   → ir/ + signal/ + pattern/ (lowering)
top-level   → everything (Mixer, NodeHandle, etc.)
```

This invariant is enforced by `tests/test_dependency_invariant.py` which walks AST imports in `ir/` and asserts no module-level imports to `signal/`, `pattern/`, or `backends/`.

## Adding a new primitive

### Signal primitive

1. Add to `signal/primitives.py`: create `my_p = Primitive("my_op")` + register `abstract_eval` rule
2. Add to `signal/core.py` or `signal/lib/`: user-facing function that calls `bind(my_p, ...)`
3. Add to `backends/faust_lowering.py`: register `lowering` rule
4. `check_complete()` at import time verifies you didn't forget a rule

### Pattern primitive

1. Add `*Params` dataclass to `ir/pattern.py`
2. Add `my_p = Primitive("my_op")` to `pattern/primitives.py`
3. Register serialize rule in `pattern/serialize.py`
4. Register summary handler in `pattern/summary.py`
5. Add operator on `Pattern` class in `pattern/pattern.py`
6. Import-time completeness checks catch missing rules
