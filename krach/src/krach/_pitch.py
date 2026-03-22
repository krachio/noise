"""Pitch utilities — MIDI note numbers, Hz conversion, note name constants."""

from __future__ import annotations

import math
import re

_NAMES = ("C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B")

_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE_RE = re.compile(r"^([A-G])([#sb]?)(\d)$")


def mtof(note: int) -> float:
    """MIDI note number to frequency in Hz."""
    if note < 0 or note > 127:
        raise ValueError(f"MIDI note must be 0-127, got {note}")
    return 440.0 * 2 ** ((note - 69) / 12.0)


def parse_note(s: str) -> float:
    """Parse a note name string to frequency in Hz.

    Format: ``{letter}{accidental?}{octave}`` where letter is A-G,
    accidental is ``#`` or ``s`` (sharp) or ``b`` (flat), octave is 0-8.

    Examples: ``"C4"`` -> 261.63, ``"C#4"`` -> 277.18, ``"Db4"`` -> 277.18.
    """
    m = _NOTE_RE.match(s)
    if m is None:
        raise ValueError(f"invalid note name: {s!r}")
    letter, accidental, octave_str = m.group(1), m.group(2), m.group(3)
    octave = int(octave_str)
    if octave < 0 or octave > 8:
        raise ValueError(f"octave must be 0-8, got {octave}")
    semitone = _SEMITONES[letter]
    if accidental in ("#", "s"):
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    midi = (octave + 1) * 12 + semitone
    if midi < 0 or midi > 127:
        raise ValueError(f"resulting MIDI note {midi} out of range 0-127")
    return mtof(midi)


def ftom(freq: float) -> int:
    """Frequency in Hz to nearest MIDI note number, clamped to 0-127."""
    if freq <= 0:
        raise ValueError(f"frequency must be positive, got {freq}")
    return max(0, min(127, round(69 + 12 * math.log2(freq / 440.0))))


# Note name constants: C0=12 .. B8=107
# C-1=0 is valid MIDI but below audible range; start at C0=12.
C0 = 12; Cs0 = 13; D0 = 14; Ds0 = 15; E0 = 16; F0 = 17
Fs0 = 18; G0 = 19; Gs0 = 20; A0 = 21; As0 = 22; B0 = 23

C1 = 24; Cs1 = 25; D1 = 26; Ds1 = 27; E1 = 28; F1 = 29
Fs1 = 30; G1 = 31; Gs1 = 32; A1 = 33; As1 = 34; B1 = 35

C2 = 36; Cs2 = 37; D2 = 38; Ds2 = 39; E2 = 40; F2 = 41
Fs2 = 42; G2 = 43; Gs2 = 44; A2 = 45; As2 = 46; B2 = 47

C3 = 48; Cs3 = 49; D3 = 50; Ds3 = 51; E3 = 52; F3 = 53
Fs3 = 54; G3 = 55; Gs3 = 56; A3 = 57; As3 = 58; B3 = 59

C4 = 60; Cs4 = 61; D4 = 62; Ds4 = 63; E4 = 64; F4 = 65
Fs4 = 66; G4 = 67; Gs4 = 68; A4 = 69; As4 = 70; B4 = 71

C5 = 72; Cs5 = 73; D5 = 74; Ds5 = 75; E5 = 76; F5 = 77
Fs5 = 78; G5 = 79; Gs5 = 80; A5 = 81; As5 = 82; B5 = 83

C6 = 84; Cs6 = 85; D6 = 86; Ds6 = 87; E6 = 88; F6 = 89
Fs6 = 90; G6 = 91; Gs6 = 92; A6 = 93; As6 = 94; B6 = 95

C7 = 96; Cs7 = 97; D7 = 98; Ds7 = 99; E7 = 100; F7 = 101
Fs7 = 102; G7 = 103; Gs7 = 104; A7 = 105; As7 = 106; B7 = 107

C8 = 108; Cs8 = 109; D8 = 110; Ds8 = 111; E8 = 112; F8 = 113
Fs8 = 114; G8 = 115; Gs8 = 116; A8 = 117; As8 = 118; B8 = 119

# Bulk export dict for REPL namespace injection
NOTES: dict[str, int] = {
    f"{name}{octave}": 12 * (octave + 1) + i
    for octave in range(9)
    for i, name in enumerate(_NAMES)
}
