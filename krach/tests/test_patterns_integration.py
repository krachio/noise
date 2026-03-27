from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from krach.pattern import Session, midi_note as note, rest, fast, thin


def _stub_ok_response(mock_cls: MagicMock) -> None:
    ok = json.dumps({"status": "Ok", "msg": "ok"}).encode() + b"\n"
    mock_cls.return_value.makefile.return_value.readline.return_value = ok


def _parse_sent(mock_sock: MagicMock) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in mock_sock.sendall.call_args_list:
        raw: bytes = call[0][0]
        for line in raw.decode().strip().split("\n"):
            if line:
                results.append(json.loads(line))
    return results


class TestPublicImports:
    def test_all_names_importable(self) -> None:
        from krach.pattern import (
            KernelError,
            Pattern,
            Session,
            SlotState,
            cc,
            midi_note as note,
            rest,
            reverse,
            fast,
            shift,
            spread,
            thin,
        )

        assert all(
            x is not None
            for x in [
                KernelError, Pattern, Session, SlotState, note, rest, cc,
                fast, reverse, shift, spread, thin,
            ]
        )


class TestEndToEnd:
    @patch("krach.session.socket.socket")
    def test_multi_slot_session(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.tempo = 128

            kick = note(36) + rest() + note(38) + rest()
            hats = note(42) * 4
            drums = kick | hats

            s.play("drums", drums)
            s.play("melody", (note(60) + note(64) + note(67)).over(3))

            s.hush("drums")
            s.stop()

        msgs = _parse_sent(mock_cls.return_value)

        cmds = [m["cmd"] for m in msgs]
        assert "SetBpm" in cmds
        assert "SetPattern" in cmds
        assert "Hush" in cmds
        assert "HushAll" in cmds

        bpm_msg = next(m for m in msgs if m["cmd"] == "SetBpm")
        assert bpm_msg["bpm"] == 128

        pattern_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        slots = {m["slot"] for m in pattern_msgs}
        assert "drums" in slots
        assert "melody" in slots

        drums_msg = next(m for m in pattern_msgs if m["slot"] == "drums")
        assert drums_msg["pattern"]["op"] == "Stack"
        assert len(drums_msg["pattern"]["children"]) == 2

        melody_msg = next(m for m in pattern_msgs if m["slot"] == "melody")
        assert melody_msg["pattern"]["op"] == "Slow"
        assert melody_msg["pattern"]["factor"] == [3, 1]
        inner = melody_msg["pattern"]["child"]
        assert inner["op"] == "Cat"
        assert len(inner["children"]) == 3

    @patch("krach.session.socket.socket")
    def test_composable_transforms(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            fx = fast(2) >> thin(0.1)
            s.play("drums", fx(note(36) + rest() + note(38) + rest()))

        msgs = _parse_sent(mock_cls.return_value)
        pattern_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        assert len(pattern_msgs) == 1
        pat = pattern_msgs[0]["pattern"]
        assert pat["op"] == "Degrade"
        assert pat["child"]["op"] == "Fast"
        assert pat["child"]["child"]["op"] == "Cat"

    @patch("krach.session.socket.socket")
    def test_atomic_launch(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        with Session() as s:
            s.launch({
                "drums": note(36) + rest() + note(38) + rest(),
                "melody": (note(60) + note(64) + note(67)).over(3),
            })
        msgs = _parse_sent(mock_cls.return_value)
        batch_msgs = [m for m in msgs if m["cmd"] == "Batch"]
        assert len(batch_msgs) == 1
        inner = batch_msgs[0]["commands"]
        assert len(inner) == 2
        slots = {c["slot"] for c in inner}
        assert slots == {"drums", "melody"}

    @patch("krach.session.socket.socket")
    def test_hush_resume_cycle(self, mock_cls: MagicMock) -> None:
        _stub_ok_response(mock_cls)
        pat = note(60) + note(64)
        with Session() as s:
            s.play("mel", pat)
            s.hush("mel")
            s.resume("mel")
            assert s.slots["mel"].playing is True
            assert s.slots["mel"].pattern == pat
