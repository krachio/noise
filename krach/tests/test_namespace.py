"""Tests for the kr/krs namespace refactor.

Verifies that pattern builders, pitch utilities, and DSP primitives
are accessible through VoiceMixer (kr) and krach.dsp (krs).
"""

from krach._mixer import VoiceMixer, note, hit, seq, ramp, mod_sine, mod_tri
from krach._mixer import mod_ramp, mod_ramp_down, mod_square, mod_exp, dsp
from krach._pitch import mtof, ftom, parse_note
from krach.patterns.pattern import Pattern, rest


# ── Pattern builders on VoiceMixer ────────────────────────────────────────────


def test_note_is_same_function() -> None:
    assert VoiceMixer.note is note


def test_hit_is_same_function() -> None:
    assert VoiceMixer.hit is hit


def test_seq_is_same_function() -> None:
    assert VoiceMixer.seq is seq


def test_rest_is_same_function() -> None:
    assert VoiceMixer.rest is rest


def test_ramp_is_same_function() -> None:
    assert VoiceMixer.ramp is ramp


def test_mod_sine_is_same_function() -> None:
    assert VoiceMixer.mod_sine is mod_sine


def test_mod_tri_is_same_function() -> None:
    assert VoiceMixer.mod_tri is mod_tri


def test_mod_ramp_is_same_function() -> None:
    assert VoiceMixer.mod_ramp is mod_ramp


def test_mod_ramp_down_is_same_function() -> None:
    assert VoiceMixer.mod_ramp_down is mod_ramp_down


def test_mod_square_is_same_function() -> None:
    assert VoiceMixer.mod_square is mod_square


def test_mod_exp_is_same_function() -> None:
    assert VoiceMixer.mod_exp is mod_exp


def test_dsp_is_same_function() -> None:
    assert VoiceMixer.dsp is dsp


# ── Pitch utilities on VoiceMixer ─────────────────────────────────────────────


def test_mtof_is_same_function() -> None:
    assert VoiceMixer.mtof is mtof


def test_ftom_is_same_function() -> None:
    assert VoiceMixer.ftom is ftom


def test_parse_note_is_same_function() -> None:
    assert VoiceMixer.parse_note is parse_note


# ── Static methods produce correct results ────────────────────────────────────


def test_voicemixer_note_produces_pattern() -> None:
    pat = VoiceMixer.note("C4")
    assert pat is not None
    # Should produce the same pattern as the free function
    assert pat.node == note("C4").node


def test_voicemixer_hit_produces_pattern() -> None:
    pat = VoiceMixer.hit()
    assert pat.node == hit().node


def test_voicemixer_seq_produces_pattern() -> None:
    pat = VoiceMixer.seq("A2", "D3", None, "E2")
    assert pat.node == seq("A2", "D3", None, "E2").node


def test_voicemixer_mtof_converts() -> None:
    assert VoiceMixer.mtof(69) == 440.0


def test_voicemixer_ftom_converts() -> None:
    assert VoiceMixer.ftom(440.0) == 69


def test_voicemixer_parse_note_converts() -> None:
    hz = VoiceMixer.parse_note("A4")
    assert hz == 440.0


def test_voicemixer_rest_produces_silence() -> None:
    r = VoiceMixer.rest()
    assert r.node == rest().node


def test_voicemixer_ramp_produces_pattern() -> None:
    pat = VoiceMixer.ramp(0.0, 1.0, steps=4)
    assert pat.node == ramp(0.0, 1.0, steps=4).node


def test_voicemixer_mod_sine_produces_pattern() -> None:
    pat = VoiceMixer.mod_sine(0.0, 1.0, steps=4)
    assert pat.node == mod_sine(0.0, 1.0, steps=4).node


# ── krach.dsp module ──────────────────────────────────────────────────────────


def test_p_is_same_function() -> None:
    from krach._mininotation import p
    assert VoiceMixer.p is p  # type: ignore[attr-defined]


def test_voicemixer_p_produces_pattern() -> None:
    from krach._mininotation import p
    pat: Pattern = VoiceMixer.p("x . x .")  # type: ignore[attr-defined]
    assert pat.node == p("x . x .").node  # type: ignore[reportUnknownMemberType]


def test_dsp_module_exports_signal() -> None:
    import krach.dsp as krs
    from faust_dsl import Signal
    assert krs.Signal is Signal


def test_dsp_module_exports_control() -> None:
    import krach.dsp as krs
    from faust_dsl import control
    assert krs.control is control


def test_dsp_module_exports_saw() -> None:
    import krach.dsp as krs
    from faust_dsl.lib.oscillators import saw
    assert krs.saw is saw


def test_dsp_module_exports_lowpass() -> None:
    import krach.dsp as krs
    from faust_dsl.lib.filters import lowpass
    assert krs.lowpass is lowpass


def test_dsp_module_exports_adsr() -> None:
    import krach.dsp as krs
    from faust_dsl.music.envelopes import adsr
    assert krs.adsr is adsr


def test_dsp_module_exports_reverb() -> None:
    import krach.dsp as krs
    from faust_dsl.music.effects import reverb
    assert krs.reverb is reverb


def test_dsp_module_exports_white_noise() -> None:
    import krach.dsp as krs
    from faust_dsl.lib.noise import white_noise
    assert krs.white_noise is white_noise
