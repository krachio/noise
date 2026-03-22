import pytest

from krach._pitch import NOTES, ftom, mtof


class TestMtof:
    def test_a4_is_440(self) -> None:
        assert mtof(69) == 440.0

    def test_c4(self) -> None:
        assert abs(mtof(60) - 261.626) < 0.01

    def test_a0(self) -> None:
        assert abs(mtof(21) - 27.5) < 0.01

    def test_midi_0(self) -> None:
        assert mtof(0) > 0

    def test_midi_127(self) -> None:
        assert mtof(127) > 0

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="0-127"):
            mtof(-1)

    def test_128_raises(self) -> None:
        with pytest.raises(ValueError, match="0-127"):
            mtof(128)


class TestFtom:
    def test_440_is_69(self) -> None:
        assert ftom(440.0) == 69

    def test_round_trip(self) -> None:
        for n in (21, 36, 48, 60, 69, 72, 84, 96, 108):
            assert ftom(mtof(n)) == n

    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            ftom(0.0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            ftom(-100.0)


class TestConstants:
    def test_c4_is_60(self) -> None:
        from krach._pitch import C4
        assert C4 == 60

    def test_a4_is_69(self) -> None:
        from krach._pitch import A4
        assert A4 == 69

    def test_cs4_is_61(self) -> None:
        from krach._pitch import Cs4
        assert Cs4 == 61

    def test_c0_is_12(self) -> None:
        from krach._pitch import C0
        assert C0 == 12

    def test_b8_is_119(self) -> None:
        from krach._pitch import B8
        assert B8 == 119

    def test_notes_dict_has_all_names(self) -> None:
        # 9 octaves (0-8) x 12 notes = 108 constants
        assert len(NOTES) == 108
        assert NOTES["C4"] == 60
        assert NOTES["A4"] == 69


# ── Sprint 12 adversarial: ftom output range ─────────────────────────────────


class TestFtomOutputRange:
    """BUG: ftom() returns values outside MIDI 0-127 range without any
    validation or clamping. ftom(1.0) returns -36, ftom(100000.0) returns 163.

    Root cause: _pitch.py:17-21 — ftom() only validates input > 0 but does
    not validate/clamp the output to 0-127 range. If mtof() validates 0-127
    on input, ftom() should at minimum warn or clamp on output.
    """

    def test_ftom_very_low_freq_returns_valid_midi(self) -> None:
        """ftom(1.0) returns -36 — should either clamp to 0 or raise."""
        result = ftom(1.0)
        assert 0 <= result <= 127, (
            f"ftom(1.0) returned {result}, outside MIDI 0-127"
        )

    def test_ftom_very_high_freq_returns_valid_midi(self) -> None:
        """ftom(100000.0) returns 163 — should either clamp to 127 or raise."""
        result = ftom(100000.0)
        assert 0 <= result <= 127, (
            f"ftom(100000.0) returned {result}, outside MIDI 0-127"
        )
