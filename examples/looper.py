"""looper.py -- circular buffer looper using rwtable.

Demonstrates krs.rwtable() for a fixed-size recording buffer with
feedback-based phase counter and record gate control.

This is application code, NOT a library function.

Run from the krach REPL:
    kr.load("examples/looper.py")
"""

from krach import signal as krs

# 30 seconds at 48 kHz
BUFFER_SIZE = 48000 * 30


def looper(input: krs.Signal) -> krs.Signal:
    """Circular buffer looper with record gate and feedback controls."""
    rec = krs.control("rec", 0.0, 0.0, 1.0)
    fb = krs.control("fb", 0.8, 0.0, 1.0)
    length = krs.control("length", float(BUFFER_SIZE), 1.0, float(BUFFER_SIZE))

    # Phase counter: wraps at `length` samples
    phase = krs.feedback(lambda ph: krs.fmod(ph + 1.0, length))

    # Mix input with existing buffer content
    existing = krs.rwtable(
        BUFFER_SIZE,
        0.0,           # init value
        phase,         # write index
        krs.select2(rec, 0.0, krs.dcblock(input + fb * krs.rwtable(
            BUFFER_SIZE, 0.0, 0.0, 0.0, phase,
        ))),           # write value: gated by rec
        phase,         # read index
    )

    return krs.dcblock(existing)
