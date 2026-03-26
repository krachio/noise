# Understanding krach's IR

krach uses a JAX-inspired tracing model: Python functions become frozen IR graphs that lower to backend code. This page walks through the system from trace to execution.

## The big picture

```
Python DSP function → trace → DspGraph (Signal IR) → emit_faust → FAUST → LLVM JIT → audio
Python patterns     → build → PatternNode tree      → serialize  → JSON  → Rust engine
Python session      → capture → ModuleIr            → to_dict    → JSON  → persistence
```

Three IRs, one for each domain:

| IR | Shape | Produced by | Consumed by |
|----|-------|-------------|-------------|
| **DspGraph** | Flat DAG of equations | Signal tracing (`TraceContext`) | Faust codegen |
| **PatternNode** | Tree | Direct construction (operators) | Engine protocol serialization |
| **ModuleIr** | Flat record of definitions | `capture()` or `ModuleProxy` | `instantiate()`, JSON persistence |

## Signal tracing: Python → DspGraph

This is the core idea. A Python function executes once against `Signal` proxy objects. Each operation records an `Equation` into a `DspGraph`. The function never runs again — the graph IS the computation.

### A concrete example

```python
import krach.dsp as krs

def bass():
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), 800.0) * env
```

When krach traces this function, it produces:

```
{ lambda ;  . let
    s0 = control  [ControlParams(name='freq', init=55.0, lo=20.0, hi=800.0, step=0.001)]
    s1 = control  [ControlParams(name='gate', init=0.0, lo=0.0, hi=1.0, step=0.001)]
    s2 = const    [ConstParams(value=0.005)]
    s3 = const    [ConstParams(value=0.15)]
    s4 = const    [ConstParams(value=0.3)]
    s5 = const    [ConstParams(value=0.08)]
    s6 = faust_expr s2 s3 s4 s5 s1  [FaustExprParams(template='en.adsr(...)')]
    s18 = feedback s0  [FeedbackParams(body_graph=<saw phasor>)]
    s20 = mul s18 2.0
    s22 = sub s20 1.0
    s24 = faust_expr 800.0 s22  [FaustExprParams(template='{1} : fi.lowpass(2, {0})')]
    s25 = mul s24 s6
  in (s25) }
```

This is the DspGraph — krach's equivalent of a jaxpr. Each line is an `Equation`:

```python
@dataclass(frozen=True, slots=True)
class Equation:
    primitive: Primitive       # operation name (e.g., "mul", "control", "feedback")
    inputs: tuple[Signal, ...]  # input signals (by ID)
    outputs: tuple[Signal, ...] # output signals (by ID)
    params: PrimitiveParams    # typed parameters (ControlParams, ConstParams, etc.)
```

### How tracing works

1. `make_graph(bass)` creates a `TraceContext` and calls `bass()`
2. `krs.control("freq", ...)` calls `bind(control_p, ...)` which:
   - Runs the `abstract_eval` rule to compute the output type
   - Creates a fresh `Signal` for the output
   - Records an `Equation` into the TraceContext
   - Returns the output Signal (a proxy, not a value)
3. `krs.saw(freq)` — same: `bind(feedback_p, freq)` records another equation
4. `krs.lowpass(sig, 800.0)` — `800.0` is coerced to a `const` Signal via `coerce_to_signal()`
5. `* env` — `Signal.__mul__` calls `bind(mul_p, sig, env)` (operator overload)
6. The function returns. TraceContext collects all equations into a `DspGraph`

The key insight: **the function runs once, against abstract values, to produce a graph.** No audio is generated during tracing. The graph is then lowered to FAUST, compiled via LLVM, and runs at 44.1kHz.

### The types

```python
# ir/signal.py — pure frozen data
@dataclass(frozen=True, slots=True, eq=False)
class Signal:
    aval: SignalType    # abstract value (channels, precision)
    id: int             # unique identifier
    owner_id: int       # which TraceContext created this
    # eq=False: identity comparison by id only (custom __eq__/__hash__)

@dataclass(frozen=True, slots=True)
class DspGraph:
    inputs: tuple[Signal, ...]     # function parameters (audio inputs)
    outputs: tuple[Signal, ...]    # function return values
    equations: tuple[Equation, ...]
    precision: Precision = Precision.FLOAT32
```

### Canonicalization and caching

Signal IDs are assigned during tracing and vary between runs. Two traces of the same function produce different IDs but the same computation.

`canonicalize(graph)` alpha-renames all Signal IDs to sequential integers (0, 1, 2, ...). `graph_key(graph)` returns a structural hash of the canonicalized graph.

Two DspGraphs with the same `graph_key` are semantically identical — they share compiled FAUST binaries:

```python
g1 = make_graph(bass)
g2 = make_graph(bass)

g1.inputs[0].id != g2.inputs[0].id  # different raw IDs
graph_key(g1) == graph_key(g2)       # same structural hash → cache hit
```

## Pattern building: operators → PatternNode

Patterns don't trace — they build trees directly. The Python expression IS the tree:

```python
pat = kr.note("C4") + kr.note("E4") + kr.rest()
```

Produces:

```
PatternNode(cat_p, children=(
    PatternNode(freeze_p, children=(
        PatternNode(cat_p, children=(
            PatternNode(stack_p, children=(
                PatternNode(atom_p, AtomParams(Control("freq", 261.63))),
                PatternNode(atom_p, AtomParams(Control("gate", 1.0))),
            )),
            PatternNode(atom_p, AtomParams(Control("gate", 0.0))),
        )),
    )),
    PatternNode(freeze_p, children=(...)),  # E4
    PatternNode(silence_p),                  # rest
))
```

Each `PatternNode` has:

```python
@dataclass(frozen=True, slots=True)
class PatternNode:
    primitive: Primitive              # "cat", "freeze", "atom", etc.
    children: tuple[PatternNode, ...]  # sub-trees
    params: PatternParams             # typed per-primitive params
```

Why no tracing? Because patterns are **trees** (no sharing), and Python's expression syntax naturally builds the right shape. Signals need tracing because they're **graphs** (with sharing — the same signal can feed multiple equations).

## ModuleIr: the top-level jaxpr

`ModuleIr` is the session specification — it contains DspGraphs and PatternNodes:

```python
@dataclass(frozen=True, slots=True)
class ModuleIr:
    nodes: tuple[NodeDef, ...]       # each has source: DspGraph | str
    routing: tuple[RouteDef, ...]     # connections between nodes
    patterns: tuple[PatternDef, ...]  # each has pattern: PatternNode
    controls: tuple[ControlDef, ...]
    muted: tuple[MutedDef, ...]
    automations: tuple[AutomationDef, ...] = ()
    tempo: float | None
    meter: float | None
    master: float | None
    sub_modules: tuple[tuple[str, ModuleIr], ...]  # recursion
```

The `NodeDef.source` field holds a `DspGraph` (the signal computation for that node) or a `str` (reference to a pre-compiled FAUST type like `"faust:kick"`).

## Shared infrastructure

### Primitive

One frozen type for both domains:

```python
# ir/primitive.py
@dataclass(frozen=True, slots=True)
class Primitive:
    name: str
    stateful: bool = False
```

Signal primitives: `add_p = Primitive("add")`, `sin_p = Primitive("sin")`, `feedback_p = Primitive("feedback", stateful=True)`

Pattern primitives: `cat_p = Primitive("cat")`, `fast_p = Primitive("fast")`, `freeze_p = Primitive("freeze")`

### RuleRegistry

Per-primitive rules registered externally (not on the Primitive — it's just data):

```python
# ir/registry.py
class RuleRegistry(Generic[P, R]):
    def register(self, prim: P, rule: R) -> R
    def lookup(self, prim: P) -> R
    def check_complete(self, expected: frozenset[P]) -> None
```

Two `RuleRegistry` instances (defined in `signal/trace.py`, rules registered externally):

| Registry | Rules registered in | Purpose |
|----------|----------|---------|
| `abstract_eval` | `signal/primitives.py` | Type inference during tracing |
| `lowering` | `backends/faust_lowering.py` | Signal IR → FAUST expressions |

`check_complete()` runs at import time — adding a primitive without a rule fails immediately, not at runtime.

Pattern rules use a simpler mechanism: a `dict[str, Rule]` in `pattern/primitives.py` with `def_serialize` / `def_summary` wrappers. Same import-time completeness guarantee, different implementation.

## Dependency layering

```
ir/          → stdlib only (pure frozen data)
signal/      → ir/ + backends/ (tracing runtime + DSL; transpile imports codegen)
pattern/     → ir/ (building + DSL)
backends/    → ir/ + signal/ (lowering)
top-level    → everything (Mixer, REPL)
```

`tests/test_dependency_invariant.py` enforces this: no module-level imports from `ir/` to `signal/`, `pattern/`, or `backends/`.

## Adding a new signal primitive

1. Define it: `my_p = Primitive("my_op")` in `signal/primitives.py`
2. Register abstract_eval: `abstract_eval.register(my_p, my_eval_fn)`
3. Write the user-facing function in `signal/core.py`: calls `bind(my_p, ...)`
4. Register lowering: `lowering.register(my_p, my_lower_fn)` in `backends/faust_lowering.py`
5. `check_complete()` at import time verifies nothing is missing

## Adding a new pattern primitive

1. Add a `*Params` dataclass to `ir/pattern.py`
2. Define it: `my_p = Primitive("my_op")` in `pattern/primitives.py`
3. Register serialize rule in `pattern/serialize.py`
4. Register summary handler in `pattern/summary.py`
5. Add an operator or method on `Pattern` in `pattern/pattern.py`
6. Import-time completeness checks catch missing rules
