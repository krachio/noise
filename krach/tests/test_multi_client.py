"""Multi-client + control UX tests — bugs #21, #25, #26."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from krach.mixer import Mixer


def _make_mixer() -> tuple[MagicMock, Mixer]:
    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "faust:verb", "dac", "gain"]
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
        "faust:verb": ("room",),
    })
    return session, mixer


# ── Multi-client (bug #21) — documenting the limitation ──────────────────


@pytest.mark.xfail(reason="bug #21: multi-client session clobber — architectural")
def test_two_mixers_share_session_clobber_graph() -> None:
    """Two Mixers on the same session: second load_graph overwrites the first.
    This is a known architectural limitation documented for future work."""
    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "faust:pad", "dac", "gain"]

    mixer_a = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer_b = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:pad": ("freq", "gate"),
    })

    mixer_a.voice("bass", "faust:bass", gain=0.5)
    mixer_b.voice("pad", "faust:pad", gain=0.5)

    # The last load_graph call wins — mixer_a's bass is gone.
    last_ir = session.load_graph.call_args[0][0]
    node_ids = {n.id for n in last_ir.nodes}

    # This assertion documents the bug: bass should still be present
    # but it's been overwritten by mixer_b's graph.
    assert "bass" in node_ids, "bass node should survive (multi-client sync)"
    assert "pad" in node_ids, "pad node should be present"


def test_save_scene_not_visible_in_other_mixer() -> None:
    """Scene saved by mixer_a is not visible in mixer_b."""
    session = MagicMock()
    session.list_nodes.return_value = ["faust:bass", "dac", "gain"]

    mixer_a = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    mixer_b = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })

    mixer_a.voice("bass", "faust:bass", gain=0.5)
    mixer_a.save("verse")

    # mixer_b doesn't know about mixer_a's scene.
    assert "verse" not in mixer_b.scenes, "scenes should not be shared across mixers"


# ── Control UX (bugs #25, #26) ───────────────────────────────────────────


def test_set_control_warns_when_pattern_active() -> None:
    """set('bass/cutoff', 1200) should warn if a control pattern is already
    driving bass/cutoff — the set value will be immediately overwritten."""
    import warnings

    _session, mixer = _make_mixer()
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Play a control pattern on bass/cutoff.
    from krach.pattern.builders import sine
    mixer.play("bass/cutoff", sine(400, 2000))

    # Now set the same control — should produce a warning.
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mixer.set("bass/cutoff", 1200)

    pattern_warnings = [x for x in w if "pattern" in str(x.message).lower()]
    assert len(pattern_warnings) > 0, (
        "set() should warn when a control pattern is active on the same path"
    )


def test_hush_by_control_path() -> None:
    """hush('bass/cutoff') should stop the control pattern on that path."""
    session, mixer = _make_mixer()
    mixer.voice("bass", "faust:bass", gain=0.5)

    # Play a control pattern.
    from krach.pattern.builders import sine
    mixer.play("bass/cutoff", sine(400, 2000))

    session.reset_mock()
    mixer.hush("bass/cutoff")

    # Should have hushed the control slot.
    hushed = {c.args[0] for c in session.hush.call_args_list}
    assert "_ctrl_bass_cutoff" in hushed, (
        f"hush('bass/cutoff') should hush _ctrl_bass_cutoff, but hushed: {hushed}"
    )
