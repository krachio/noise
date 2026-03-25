"""Composition operators: split, merge, bus, chain, parallel, route, DspFunc."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce

from krach.ir.signal import Signal, coerce_to_signal

# ---------------------------------------------------------------------------
# DspFunc — callable wrapper with num_inputs metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DspFunc:
    """A DSP function with known input/output channel counts."""

    fn: Callable[..., Signal | tuple[Signal, ...]]
    num_inputs: int
    num_outputs: int | None = None

    def __call__(self, *args: Signal) -> Signal | tuple[Signal, ...]:
        return self.fn(*args)


# ---------------------------------------------------------------------------
# Input-count introspection
# ---------------------------------------------------------------------------


def get_num_inputs(fn: Callable[..., Signal | tuple[Signal, ...]]) -> int:
    """Infer the number of input signals a DSP function expects."""
    if isinstance(fn, DspFunc):
        return fn.num_inputs
    sig = inspect.signature(fn)
    return len(sig.parameters)


def _get_output_count(
    fn: Callable[..., Signal | tuple[Signal, ...]],
) -> int | None:
    if isinstance(fn, DspFunc):
        return fn.num_outputs
    return None


# ---------------------------------------------------------------------------
# split — one signal to N copies
# ---------------------------------------------------------------------------


def split(sig: Signal, n: int) -> tuple[Signal, ...]:
    """Fan-out a single signal to n copies."""
    if n < 1:
        raise ValueError(f"split requires n >= 1, got {n}")
    return tuple(sig for _ in range(n))


# ---------------------------------------------------------------------------
# merge — N signals to 1 by summation
# ---------------------------------------------------------------------------


def merge(*signals: Signal) -> Signal:
    """Fan-in multiple signals to one by summation."""
    if len(signals) == 0:
        raise ValueError("merge requires at least one signal")
    return reduce(lambda a, b: a + b, signals)


# ---------------------------------------------------------------------------
# bus — N-channel identity
# ---------------------------------------------------------------------------


def bus(n: int) -> DspFunc:
    """Create an n-channel identity (pass-through) function."""
    if n < 1:
        raise ValueError(f"bus requires n >= 1, got {n}")

    def _bus(*args: Signal) -> Signal | tuple[Signal, ...]:
        if len(args) != n:
            raise TypeError(f"bus({n}) expects {n} arguments, got {len(args)}")
        if n == 1:
            return args[0]
        return args

    return DspFunc(fn=_bus, num_inputs=n, num_outputs=n)


# ---------------------------------------------------------------------------
# chain — sequential composition
# ---------------------------------------------------------------------------


def chain(*fns: Callable[..., Signal | tuple[Signal, ...]]) -> DspFunc:
    """Sequential composition of DSP functions (Faust's : operator)."""
    if len(fns) < 2:
        raise ValueError(f"chain requires at least 2 functions, got {len(fns)}")

    first_num_inputs = get_num_inputs(fns[0])

    for i in range(len(fns) - 1):
        prev_fn, next_fn = fns[i], fns[i + 1]
        prev_outputs = _get_output_count(prev_fn)
        if prev_outputs is not None:
            next_inputs = get_num_inputs(next_fn)
            if prev_outputs != next_inputs:
                raise ValueError(
                    f"Channel count mismatch in chain at position {i}: "
                    f"{prev_outputs} outputs but next function expects {next_inputs} inputs"
                )

    last_num_outputs = _get_output_count(fns[-1])

    def _chained(*args: Signal) -> Signal | tuple[Signal, ...]:
        result: Signal | tuple[Signal, ...] = fns[0](*args)
        for fn in fns[1:]:
            if isinstance(result, Signal):
                result = fn(result)
            else:
                result = fn(*result)
        return result

    return DspFunc(
        fn=_chained, num_inputs=first_num_inputs, num_outputs=last_num_outputs
    )


# ---------------------------------------------------------------------------
# parallel — parallel composition
# ---------------------------------------------------------------------------


def parallel(*fns: Callable[..., Signal | tuple[Signal, ...]]) -> DspFunc:
    """Parallel composition of DSP functions (Faust's , operator)."""
    if len(fns) < 2:
        raise ValueError(f"parallel requires at least 2 functions, got {len(fns)}")

    counts = [get_num_inputs(fn) for fn in fns]
    total_inputs = sum(counts)

    total_outputs: int | None = None
    sub_outputs = [_get_output_count(fn) for fn in fns]
    if all(n is not None for n in sub_outputs):
        total_outputs = sum(n for n in sub_outputs if n is not None)

    def _parallel(*args: Signal) -> Signal | tuple[Signal, ...]:
        if len(args) != total_inputs:
            raise TypeError(
                f"parallel expects {total_inputs} arguments, got {len(args)}"
            )
        outputs: list[Signal] = []
        offset = 0
        for fn, count in zip(fns, counts):
            chunk = args[offset : offset + count]
            offset += count
            result = fn(*chunk)
            if isinstance(result, Signal):
                outputs.append(result)
            else:
                outputs.extend(result)
        if len(outputs) == 1:
            return outputs[0]
        return tuple(outputs)

    return DspFunc(fn=_parallel, num_inputs=total_inputs, num_outputs=total_outputs)


# ---------------------------------------------------------------------------
# route — N-channel routing
# ---------------------------------------------------------------------------


def route(n_in: int, n_out: int, pairs: list[tuple[int, int]]) -> DspFunc:
    """Arbitrary signal routing matrix."""
    if n_in < 1:
        raise ValueError(f"route requires n_in >= 1, got {n_in}")
    if n_out < 1:
        raise ValueError(f"route requires n_out >= 1, got {n_out}")

    for in_idx, out_idx in pairs:
        if in_idx < 0 or in_idx >= n_in:
            raise ValueError(
                f"Invalid input index {in_idx} for route with {n_in} inputs"
            )
        if out_idx < 0 or out_idx >= n_out:
            raise ValueError(
                f"Invalid output index {out_idx} for route with {n_out} outputs"
            )

    routing: dict[int, list[int]] = {}
    for in_idx, out_idx in pairs:
        routing.setdefault(out_idx, []).append(in_idx)

    def _route(*args: Signal) -> Signal | tuple[Signal, ...]:
        if len(args) != n_in:
            raise TypeError(
                f"route({n_in}, {n_out}, ...) expects {n_in} arguments, got {len(args)}"
            )
        outputs: list[Signal] = []
        for out_idx in range(n_out):
            in_indices = routing.get(out_idx)
            if in_indices is None:
                outputs.append(coerce_to_signal(0.0))
            elif len(in_indices) == 1:
                outputs.append(args[in_indices[0]])
            else:
                outputs.append(merge(*(args[i] for i in in_indices)))
        if len(outputs) == 1:
            return outputs[0]
        return tuple(outputs)

    return DspFunc(fn=_route, num_inputs=n_in, num_outputs=n_out)
