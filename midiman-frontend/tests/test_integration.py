from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from midiman_frontend import Session, note, rest, scale, thin


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
        from midiman_frontend import (
            Pattern,
            Session,
            cc,
            note,
            rest,
            reverse,
            scale,
            shift,
            spread,
            thin,
        )

        assert all(
            x is not None
            for x in [Pattern, Session, note, rest, cc, scale, reverse, shift, spread, thin]
        )


class TestEndToEnd:
    @patch("midiman_frontend.session.socket.socket")
    def test_multi_track_session(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            s.tempo = 128

            drums = s.track("drums")
            mel = s.track("melody")

            kick_pat = note(36) + rest() + note(38) + rest()
            hats_pat = note(42) * 4

            drums["kick"] = kick_pat
            drums["hats"] = hats_pat

            mel["arp"] = (note(60) + note(64) + note(67)).over(3)

            del drums["hats"]
            mel.stop()
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

        drums_stack = next(
            m for m in pattern_msgs if m["slot"] == "drums" and m["pattern"]["op"] == "Stack"
        )
        assert len(drums_stack["pattern"]["children"]) == 2

        melody_msg = next(m for m in pattern_msgs if m["slot"] == "melody")
        assert melody_msg["pattern"]["op"] == "Slow"
        assert melody_msg["pattern"]["factor"] == [3, 1]
        inner = melody_msg["pattern"]["child"]
        assert inner["op"] == "Cat"
        assert len(inner["children"]) == 3

    @patch("midiman_frontend.session.socket.socket")
    def test_composable_transforms_in_session(self, mock_cls: MagicMock) -> None:
        with Session() as s:
            drums = s.track("drums")
            fx = scale(2) >> thin(0.1)
            drums["main"] = fx(note(36) + rest() + note(38) + rest())

        msgs = _parse_sent(mock_cls.return_value)
        pattern_msgs = [m for m in msgs if m["cmd"] == "SetPattern"]
        assert len(pattern_msgs) == 1
        pat = pattern_msgs[0]["pattern"]
        assert pat["op"] == "Degrade"
        assert pat["child"]["op"] == "Fast"
        assert pat["child"]["child"]["op"] == "Cat"
