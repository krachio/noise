"""Tests for the kr/krs/krp namespace refactor.

Verifies that DSP functions are accessible through krach.signal (krs),
pattern builders through krach.pattern (krp), and LiveMixer has dsp().
"""

from krach.repl import LiveMixer
from krach.graph.node import dsp


# ── LiveMixer retains dsp() ──────────────────────────────────────────────


def test_dsp_is_same_function() -> None:
    assert LiveMixer.dsp is dsp


# ── krach.signal (krs) ──────────────────────────────────────────────────


def test_signal_exports_signal() -> None:
    from krach import signal as krs
    from krach.signal.types import Signal
    assert krs.Signal is Signal


def test_signal_exports_control() -> None:
    from krach import signal as krs
    from krach.signal.transpile import control
    assert krs.control is control


def test_signal_exports_saw() -> None:
    from krach import signal as krs
    from krach.signal.lib import saw
    assert krs.saw is saw


def test_signal_exports_lowpass() -> None:
    from krach import signal as krs
    from krach.signal.lib import lowpass
    assert krs.lowpass is lowpass


def test_signal_exports_adsr() -> None:
    from krach import signal as krs
    from krach.signal.music import adsr
    assert krs.adsr is adsr


def test_signal_exports_reverb() -> None:
    from krach import signal as krs
    from krach.signal.music import reverb
    assert krs.reverb is reverb


def test_signal_exports_white_noise() -> None:
    from krach import signal as krs
    from krach.signal.lib import white_noise
    assert krs.white_noise is white_noise


# ── krach.pattern (krp) ─────────────────────────────────────────────────


def test_pattern_exports_note() -> None:
    from krach import pattern as krp
    from krach.pattern.builders import note
    assert krp.note is note


def test_pattern_exports_hit() -> None:
    from krach import pattern as krp
    from krach.pattern.builders import hit
    assert krp.hit is hit


def test_pattern_exports_seq() -> None:
    from krach import pattern as krp
    from krach.pattern.builders import seq
    assert krp.seq is seq


def test_pattern_exports_rest() -> None:
    from krach import pattern as krp
    from krach.pattern.pattern import rest
    assert krp.rest is rest


def test_pattern_exports_sine() -> None:
    from krach import pattern as krp
    from krach.pattern.builders import sine
    assert krp.sine is sine


def test_pattern_exports_p() -> None:
    from krach import pattern as krp
    from krach.pattern.mininotation import p
    assert krp.p is p


def test_pattern_exports_mtof() -> None:
    from krach import pattern as krp
    from krach.pattern.pitch import mtof
    assert krp.mtof is mtof


# ── __setattr__ guard (on LiveMixer) ────────────────────────────────────────


def test_setattr_rejects_unknown_property() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock
    import pytest
    mixer = LiveMixer(session=MagicMock(), dsp_dir=Path("/tmp"))
    with pytest.raises(AttributeError, match="kr has no property 'swing'"):
        mixer.swing = 0.67  # type: ignore[attr-defined]


def test_setattr_allows_known_properties() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock
    mixer = LiveMixer(session=MagicMock(), dsp_dir=Path("/tmp"))
    mixer.master = 0.5  # should not raise
    mixer.tempo = 140.0
    mixer.meter = 3.0
