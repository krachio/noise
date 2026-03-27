from pathlib import Path


# ── Commit 6: NodeHandle / NodeHandle ────────────────────────────────────────


def test_voice_returns_handle() -> None:
    """voice() returns a NodeHandle."""
    from unittest.mock import MagicMock

    from krach.mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)
    assert isinstance(h, NodeHandle)
    assert h.name == "bass"


def test_handle_play_delegates_to_mixer() -> None:
    """handle.play(pattern) delegates to mixer.play(name, pattern)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer
    from krach.pattern.builders import hit

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:kick": ("gate",),
    })
    h = mixer.voice("kick", "faust:kick", gain=0.8)

    pat = hit()
    with patch.object(mixer, "play") as mock_play:
        h.play(pat)
        mock_play.assert_called_once_with("kick", pat)


def test_handle_play_control_path() -> None:
    """handle.play('cutoff', pattern) delegates to mixer.play('name/cutoff', pattern)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer
    from krach.pattern.builders import sine

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    pat = sine(200.0, 800.0)
    with patch.object(mixer, "play") as mock_play:
        h.play("cutoff", pat)
        mock_play.assert_called_once_with("bass/cutoff", pat)


def test_handle_set_delegates() -> None:
    """handle.set('cutoff', 800.0) delegates to mixer.set('name/cutoff', 800.0)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "set") as mock_set:
        h.set("cutoff", 800.0)
        mock_set.assert_called_once_with("bass/cutoff", 800.0)


def test_handle_fade_delegates() -> None:
    """handle.fade('cutoff', 200.0, bars=8) delegates to mixer.fade(...)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate", "cutoff"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "fade") as mock_fade:
        h.fade("cutoff", 200.0, bars=8)
        mock_fade.assert_called_once_with("bass/cutoff", 200.0, bars=8)


def test_handle_send_with_bus_handle() -> None:
    """handle.send(bus_handle, 0.3) delegates to mixer.send(name, bus_name, 0.3)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
        "faust:verb": ("room",),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    with patch.object(mixer, "send") as mock_send:
        h.send(bh, 0.3)
        mock_send.assert_called_once_with("bass", "verb", 0.3)


def test_handle_mute_unmute() -> None:
    """handle.mute() / handle.unmute() delegate to mixer."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "mute") as mock_mute:
        h.mute()
        mock_mute.assert_called_once_with("bass")

    with patch.object(mixer, "unmute") as mock_unmute:
        h.unmute()
        mock_unmute.assert_called_once_with("bass")


def test_handle_hush() -> None:
    """handle.hush() delegates to mixer.hush(name)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    with patch.object(mixer, "hush") as mock_hush:
        h.hush()
        mock_hush.assert_called_once_with("bass")


def test_handle_repr() -> None:
    """NodeHandle repr shows voice info."""
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:bass": ("freq", "gate"),
    })
    h = mixer.voice("bass", "faust:bass", gain=0.3)

    r = repr(h)
    assert "Node" in r
    assert "bass" in r
    assert "faust:bass" in r
    assert "gain=0.30" in r


def test_bus_returns_handle() -> None:
    """bus() returns a NodeHandle."""
    from unittest.mock import MagicMock

    from krach.mixer import NodeHandle, Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)
    assert isinstance(bh, NodeHandle)
    assert bh.name == "verb"


def test_bus_handle_set() -> None:
    """bus_handle.set('room', 0.8) delegates to mixer.set('verb/room', 0.8)."""
    from unittest.mock import MagicMock, patch

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    with patch.object(mixer, "set") as mock_set:
        bh.set("room", 0.8)
        mock_set.assert_called_once_with("verb/room", 0.8)


def test_bus_handle_repr() -> None:
    """NodeHandle repr shows bus info."""
    from unittest.mock import MagicMock

    from krach.mixer import Mixer

    session = MagicMock()
    mixer = Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:verb": ("room",),
    })
    bh = mixer.bus("verb", "faust:verb", gain=0.5)

    r = repr(bh)
    assert "Node" in r
    assert "verb" in r
    assert "faust:verb" in r
    assert "gain=0.50" in r
