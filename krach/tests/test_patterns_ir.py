from __future__ import annotations

import json

from krach.backends.pattern import (
    Batch,
    Hush,
    HushAll,
    Ping,
    SetBpm,
    SetBeatsPerCycle,
    SetPattern,
    SetPatternFromZero,
    command_to_json,
)
from krach.ir.values import Note


class TestCommandSerialization:
    def test_set_pattern(self) -> None:
        from krach.pattern.types import AtomParams, PatternNode
        from krach.pattern.primitives import atom_p
        pn = PatternNode(atom_p, (), AtomParams(Note(channel=0, note=60, velocity=100, dur=0.5)))
        cmd = SetPattern(slot="drums", pattern=pn)
        parsed = json.loads(command_to_json(cmd))
        assert parsed["cmd"] == "SetPattern"
        assert parsed["slot"] == "drums"
        assert parsed["pattern"]["op"] == "Atom"

    def test_set_pattern_from_zero(self) -> None:
        from krach.pattern.types import AtomParams, PatternNode
        from krach.pattern.primitives import atom_p
        pn = PatternNode(atom_p, (), AtomParams(Note(channel=0, note=60, velocity=100, dur=0.5)))
        cmd = SetPatternFromZero(slot="bass", pattern=pn)
        parsed = json.loads(command_to_json(cmd))
        assert parsed["cmd"] == "SetPatternFromZero"
        assert parsed["slot"] == "bass"
        assert parsed["pattern"]["op"] == "Atom"

    def test_hush(self) -> None:
        parsed = json.loads(command_to_json(Hush(slot="drums")))
        assert parsed == {"cmd": "Hush", "slot": "drums"}

    def test_hush_all(self) -> None:
        parsed = json.loads(command_to_json(HushAll()))
        assert parsed == {"cmd": "HushAll"}

    def test_set_bpm(self) -> None:
        parsed = json.loads(command_to_json(SetBpm(bpm=140.0)))
        assert parsed == {"cmd": "SetBpm", "bpm": 140.0}

    def test_set_beats_per_cycle(self) -> None:
        parsed = json.loads(command_to_json(SetBeatsPerCycle(beats=3.0)))
        assert parsed == {"cmd": "SetBeatsPerCycle", "beats": 3.0}

    def test_ping(self) -> None:
        parsed = json.loads(command_to_json(Ping()))
        assert parsed == {"cmd": "Ping"}

    def test_batch(self) -> None:
        from krach.pattern.types import AtomParams, PatternNode
        from krach.pattern.primitives import atom_p
        pn = PatternNode(atom_p, (), AtomParams(Note(channel=0, note=36, velocity=100, dur=1.0)))
        cmd = Batch(commands=(
            SetPattern(slot="drums", pattern=pn),
            SetBpm(bpm=140.0),
            Hush(slot="melody"),
        ))
        parsed = json.loads(command_to_json(cmd))
        assert parsed["cmd"] == "Batch"
        assert len(parsed["commands"]) == 3
        assert parsed["commands"][0]["cmd"] == "SetPattern"
        assert parsed["commands"][0]["slot"] == "drums"
        assert parsed["commands"][1] == {"cmd": "SetBpm", "bpm": 140.0}
        assert parsed["commands"][2] == {"cmd": "Hush", "slot": "melody"}

    def test_batch_single_command(self) -> None:
        cmd = Batch(commands=(Ping(),))
        parsed = json.loads(command_to_json(cmd))
        assert parsed == {"cmd": "Batch", "commands": [{"cmd": "Ping"}]}
