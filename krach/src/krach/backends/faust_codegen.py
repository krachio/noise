"""emit_faust(): DspGraph -> Faust source string."""

from __future__ import annotations

from krach.ir.signal import DspGraph
from krach.backends.faust_lowering import FaustLoweringContext


def emit_faust(graph: DspGraph, *, optimize: bool = False) -> str:
    """Lower a DspGraph to a complete Faust source string.

    Args:
        graph: The computation graph to lower.
        optimize: If True, run graph optimization passes before lowering.

    Returns:
        A Faust DSP source string ready for compilation.
    """
    if optimize:
        from krach.signal.optimize import optimize_graph
        graph = optimize_graph(graph)

    ctx = FaustLoweringContext()

    input_names = [f"input{i}" for i in range(len(graph.inputs))]
    for inp, name in zip(graph.inputs, input_names, strict=True):
        ctx.bind(inp, name)

    for eqn in graph.equations:
        expr = eqn.primitive.lower(ctx, eqn)
        ctx.bind(eqn.outputs[0], expr)

    output_expr = ", ".join(ctx.expr(o) for o in graph.outputs)
    args = ", ".join(input_names)

    lines: list[str] = []
    lines.append('import("stdfaust.lib");')

    process_lhs = f"process({args})" if args else "process"

    if ctx.with_defs:
        with_block = "\nwith {\n" + "\n".join(f"    {d}" for d in ctx.with_defs) + "\n}"
        lines.append(f"{process_lhs} = {output_expr}{with_block};")
    else:
        lines.append(f"{process_lhs} = {output_expr};")

    return "\n".join(lines) + "\n"
