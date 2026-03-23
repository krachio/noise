from __future__ import annotations

import dataclasses
import json

import pytest

from krach.patterns.ir import (
    Atom,
    Batch,
    Cat,
    Cc,
    Control,
    Degrade,
    Early,
    Euclid,
    Every,
    Fast,
    Freeze,
    Hush,
    HushAll,
    IrNode,
    Late,
    Note,
    Osc,
    OscFloat,
    OscInt,
    OscStr,
    Ping,
    Rev,
    SetBpm,
    SetPattern,
    Silence,
    Slow,
    Stack,
    Warp,
    command_to_json,
    dict_to_ir,
    ir_to_dict,
)


class TestValueSerialization:
    def test_note(self) -> None:
        node = Atom(Note(channel=0, note=60, velocity=100, dur=0.5))
        assert ir_to_dict(node) == {
            "op": "Atom",
            "value": {
                "type": "Note",
                "channel": 0,
                "note": 60,
                "velocity": 100,
                "dur": 0.5,
            },
        }

    def test_cc(self) -> None:
        node = Atom(Cc(channel=1, controller=74, value=127))
        assert ir_to_dict(node) == {
            "op": "Atom",
            "value": {"type": "Cc", "channel": 1, "controller": 74, "value": 127},
        }

    def test_osc(self) -> None:
        node = Atom(
            Osc(
                address="/test",
                args=(OscFloat(1.0), OscInt(42), OscStr("hi")),
            )
        )
        assert ir_to_dict(node) == {
            "op": "Atom",
            "value": {
                "type": "Osc",
                "address": "/test",
                "args": [{"Float": 1.0}, {"Int": 42}, {"Str": "hi"}],
            },
        }

    def test_control_value_serializes(self) -> None:
        node = Atom(Control(label="bass/cutoff", value=1200.0))
        assert ir_to_dict(node) == {
            "op": "Atom",
            "value": {
                "type": "Control",
                "label": "bass/cutoff",
                "value": 1200.0,
            },
        }


class TestIrNodeSerialization:
    def test_silence(self) -> None:
        assert ir_to_dict(Silence()) == {"op": "Silence"}

    def test_cat(self) -> None:
        node = Cat(
            children=(
                Atom(Note(channel=0, note=60, velocity=100, dur=1.0)),
                Silence(),
            )
        )
        result = ir_to_dict(node)
        assert result["op"] == "Cat"
        assert len(result["children"]) == 2
        assert result["children"][0]["op"] == "Atom"
        assert result["children"][1]["op"] == "Silence"

    def test_stack(self) -> None:
        a = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        b = Atom(Note(channel=0, note=64, velocity=100, dur=1.0))
        node = Stack(children=(a, b))
        result = ir_to_dict(node)
        assert result["op"] == "Stack"
        assert len(result["children"]) == 2

    def test_fast(self) -> None:
        child = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        node = Fast(factor=(2, 1), child=child)
        assert ir_to_dict(node) == {
            "op": "Fast",
            "factor": [2, 1],
            "child": ir_to_dict(child),
        }

    def test_slow(self) -> None:
        child = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        node = Slow(factor=(3, 2), child=child)
        assert ir_to_dict(node) == {
            "op": "Slow",
            "factor": [3, 2],
            "child": ir_to_dict(child),
        }

    def test_early(self) -> None:
        child = Silence()
        node = Early(offset=(1, 4), child=child)
        assert ir_to_dict(node) == {
            "op": "Early",
            "offset": [1, 4],
            "child": {"op": "Silence"},
        }

    def test_late(self) -> None:
        child = Silence()
        node = Late(offset=(1, 8), child=child)
        assert ir_to_dict(node) == {
            "op": "Late",
            "offset": [1, 8],
            "child": {"op": "Silence"},
        }

    def test_rev(self) -> None:
        child = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        node = Rev(child=child)
        assert ir_to_dict(node) == {
            "op": "Rev",
            "child": ir_to_dict(child),
        }

    def test_every(self) -> None:
        child = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        transform = Rev(child=child)
        node = Every(n=4, transform=transform, child=child)
        result = ir_to_dict(node)
        assert result["op"] == "Every"
        assert result["n"] == 4
        assert result["transform"]["op"] == "Rev"
        assert result["child"]["op"] == "Atom"

    def test_euclid(self) -> None:
        child = Atom(Note(channel=0, note=36, velocity=100, dur=1.0))
        node = Euclid(pulses=3, steps=8, rotation=0, child=child)
        assert ir_to_dict(node) == {
            "op": "Euclid",
            "pulses": 3,
            "steps": 8,
            "rotation": 0,
            "child": ir_to_dict(child),
        }

    def test_degrade(self) -> None:
        child = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        node = Degrade(prob=0.3, seed=42, child=child)
        assert ir_to_dict(node) == {
            "op": "Degrade",
            "prob": 0.3,
            "seed": 42,
            "child": ir_to_dict(child),
        }

    def test_nested_tree(self) -> None:
        atom = Atom(Note(channel=0, note=60, velocity=100, dur=0.5))
        inner = Fast(factor=(2, 1), child=atom)
        outer = Cat(children=(inner, Silence(), inner))
        result = ir_to_dict(outer)
        assert result["op"] == "Cat"
        assert len(result["children"]) == 3
        assert result["children"][0]["op"] == "Fast"
        assert result["children"][0]["child"]["op"] == "Atom"
        assert result["children"][1]["op"] == "Silence"


class TestCommandSerialization:
    def test_set_pattern(self) -> None:
        atom = Atom(Note(channel=0, note=60, velocity=100, dur=0.5))
        cmd = SetPattern(slot="drums", pattern=atom)
        parsed = json.loads(command_to_json(cmd))
        assert parsed["cmd"] == "SetPattern"
        assert parsed["slot"] == "drums"
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

    def test_ping(self) -> None:
        parsed = json.loads(command_to_json(Ping()))
        assert parsed == {"cmd": "Ping"}

    def test_batch(self) -> None:
        atom = Atom(Note(channel=0, note=36, velocity=100, dur=1.0))
        cmd = Batch(commands=(
            SetPattern(slot="drums", pattern=atom),
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


class TestImmutability:
    def test_ir_nodes_frozen(self) -> None:
        node = Atom(Note(channel=0, note=60, velocity=100, dur=1.0))
        with pytest.raises(dataclasses.FrozenInstanceError):
            node.value = Note(channel=1, note=64, velocity=80, dur=0.5)  # type: ignore[misc]

    def test_values_frozen(self) -> None:
        n = Note(channel=0, note=60, velocity=100, dur=1.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            n.note = 64  # type: ignore[misc]


class TestWarpSerialization:
    def test_warp_serializes_to_json(self) -> None:
        node = Warp(
            kind="swing", amount=0.67, grid=8,
            child=Atom(Note(channel=0, note=60, velocity=100, dur=0.5)),
        )
        d = ir_to_dict(node)
        assert d["op"] == "Warp"
        assert d["kind"] == "swing"
        assert d["amount"] == 0.67
        assert d["grid"] == 8


class TestDictToIr:
    """Round-trip tests: dict_to_ir(ir_to_dict(node)) == node."""

    def _roundtrip(self, node: IrNode) -> None:
        d = ir_to_dict(node)
        reconstructed = dict_to_ir(d)
        assert reconstructed == node, f"{reconstructed!r} != {node!r}"

    def test_atom_note(self) -> None:
        self._roundtrip(Atom(Note(channel=0, note=60, velocity=100, dur=0.5)))

    def test_atom_control(self) -> None:
        self._roundtrip(Atom(Control(label="freq", value=440.0)))

    def test_atom_osc(self) -> None:
        self._roundtrip(Atom(Osc(address="/set", args=(OscStr("pitch"), OscFloat(440.0)))))

    def test_atom_cc(self) -> None:
        self._roundtrip(Atom(Cc(channel=0, controller=1, value=64)))

    def test_silence(self) -> None:
        self._roundtrip(Silence())

    def test_freeze(self) -> None:
        self._roundtrip(Freeze(child=Atom(Note(0, 60, 100, 0.5))))

    def test_cat(self) -> None:
        self._roundtrip(Cat((Atom(Note(0, 60, 100, 0.5)), Silence())))

    def test_stack(self) -> None:
        self._roundtrip(Stack((Atom(Note(0, 60, 100, 0.5)), Atom(Note(0, 64, 100, 0.5)))))

    def test_fast(self) -> None:
        self._roundtrip(Fast(factor=(2, 1), child=Atom(Note(0, 60, 100, 0.5))))

    def test_slow(self) -> None:
        self._roundtrip(Slow(factor=(2, 1), child=Atom(Note(0, 60, 100, 0.5))))

    def test_early(self) -> None:
        self._roundtrip(Early(offset=(1, 4), child=Atom(Note(0, 60, 100, 0.5))))

    def test_late(self) -> None:
        self._roundtrip(Late(offset=(1, 4), child=Atom(Note(0, 60, 100, 0.5))))

    def test_rev(self) -> None:
        self._roundtrip(Rev(child=Atom(Note(0, 60, 100, 0.5))))

    def test_every(self) -> None:
        self._roundtrip(Every(n=4, transform=Rev(child=Atom(Note(0, 60, 100, 0.5))),
                              child=Atom(Note(0, 60, 100, 0.5))))

    def test_euclid(self) -> None:
        self._roundtrip(Euclid(pulses=3, steps=8, rotation=0, child=Atom(Note(0, 60, 100, 0.5))))

    def test_degrade(self) -> None:
        self._roundtrip(Degrade(prob=0.3, seed=42, child=Atom(Note(0, 60, 100, 0.5))))

    def test_warp(self) -> None:
        self._roundtrip(Warp(kind="swing", amount=0.67, grid=8,
                             child=Atom(Note(0, 60, 100, 0.5))))

    def test_nested(self) -> None:
        self._roundtrip(Fast(factor=(2, 1), child=Cat((Atom(Note(0, 60, 100, 0.5)), Silence()))))

    def test_unknown_op_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown IR op"):
            dict_to_ir({"op": "DoesNotExist"})
