"""Tests for the kr/krs namespace refactor.

Verifies that pattern builders, pitch utilities, and DSP primitives
are accessible through LiveMixer (REPL kr) and krach.dsp (krs).
Library Mixer is tested separately for core API.
"""

from krach.repl import LiveMixer
from krach.pattern.builders import note, hit, seq, ramp, mod_sine, mod_tri
from krach.pattern.builders import mod_ramp, mod_ramp_down, mod_square, mod_exp
from krach.node_types import dsp
from krach.pattern.pitch import mtof, ftom, parse_note
from krach.pattern.pattern import Pattern, rest


# ── Pattern builders on LiveMixer ────────────────────────────────────────


def test_note_is_same_function() -> None:
    assert LiveMixer.note is note


def test_hit_is_same_function() -> None:
    assert LiveMixer.hit is hit


def test_seq_is_same_function() -> None:
    assert LiveMixer.seq is seq


def test_rest_is_same_function() -> None:
    assert LiveMixer.rest is rest


def test_ramp_is_same_function() -> None:
    assert LiveMixer.ramp is ramp


def test_mod_sine_is_same_function() -> None:
    assert LiveMixer.mod_sine is mod_sine


def test_mod_tri_is_same_function() -> None:
    assert LiveMixer.mod_tri is mod_tri


def test_mod_ramp_is_same_function() -> None:
    assert LiveMixer.mod_ramp is mod_ramp


def test_mod_ramp_down_is_same_function() -> None:
    assert LiveMixer.mod_ramp_down is mod_ramp_down


def test_mod_square_is_same_function() -> None:
    assert LiveMixer.mod_square is mod_square


def test_mod_exp_is_same_function() -> None:
    assert LiveMixer.mod_exp is mod_exp


def test_dsp_is_same_function() -> None:
    assert LiveMixer.dsp is dsp


# ── Pitch utilities on LiveMixer ─────────────────────────────────────────


def test_mtof_is_same_function() -> None:
    assert LiveMixer.mtof is mtof


def test_ftom_is_same_function() -> None:
    assert LiveMixer.ftom is ftom


def test_parse_note_is_same_function() -> None:
    assert LiveMixer.parse_note is parse_note


# ── Static methods produce correct results ────────────────────────────────────


def test_voicemixer_note_produces_pattern() -> None:
    pat = LiveMixer.note("C4")
    assert pat is not None
    assert pat.node == note("C4").node


def test_voicemixer_hit_produces_pattern() -> None:
    pat = LiveMixer.hit()
    assert pat.node == hit().node


def test_voicemixer_seq_produces_pattern() -> None:
    pat = LiveMixer.seq("A2", "D3", None, "E2")
    assert pat.node == seq("A2", "D3", None, "E2").node


def test_voicemixer_mtof_converts() -> None:
    assert LiveMixer.mtof(69) == 440.0


def test_voicemixer_ftom_converts() -> None:
    assert LiveMixer.ftom(440.0) == 69


def test_voicemixer_parse_note_converts() -> None:
    hz = LiveMixer.parse_note("A4")
    assert hz == 440.0


def test_voicemixer_rest_produces_silence() -> None:
    r = LiveMixer.rest()
    assert r.node == rest().node


def test_voicemixer_ramp_produces_pattern() -> None:
    pat = LiveMixer.ramp(0.0, 1.0, steps=4)
    assert pat.node == ramp(0.0, 1.0, steps=4).node


def test_voicemixer_mod_sine_produces_pattern() -> None:
    pat = LiveMixer.mod_sine(0.0, 1.0, steps=4)
    assert pat.node == mod_sine(0.0, 1.0, steps=4).node


# ── krach.dsp module ──────────────────────────────────────────────────────────


def test_p_is_same_function() -> None:
    from krach.pattern.mininotation import p
    assert LiveMixer.p is p  # type: ignore[attr-defined]


def test_voicemixer_p_produces_pattern() -> None:
    from krach.pattern.mininotation import p
    pat: Pattern = LiveMixer.p("x . x .")  # type: ignore[attr-defined]
    assert pat.node == p("x . x .").node  # type: ignore[reportUnknownMemberType]


def test_dsp_module_exports_signal() -> None:
    import krach.dsp as krs
    from krach.signal.types import Signal
    assert krs.Signal is Signal


def test_dsp_module_exports_control() -> None:
    import krach.dsp as krs
    from krach.signal.transpile import control
    assert krs.control is control


def test_dsp_module_exports_saw() -> None:
    import krach.dsp as krs
    from krach.signal.lib import saw
    assert krs.saw is saw


def test_dsp_module_exports_lowpass() -> None:
    import krach.dsp as krs
    from krach.signal.lib import lowpass
    assert krs.lowpass is lowpass


def test_dsp_module_exports_adsr() -> None:
    import krach.dsp as krs
    from krach.signal.music import adsr
    assert krs.adsr is adsr


def test_dsp_module_exports_reverb() -> None:
    import krach.dsp as krs
    from krach.signal.music import reverb
    assert krs.reverb is reverb


def test_dsp_module_exports_white_noise() -> None:
    import krach.dsp as krs
    from krach.signal.lib import white_noise
    assert krs.white_noise is white_noise


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
