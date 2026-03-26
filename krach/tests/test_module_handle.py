"""Tests for ModuleHandle, instantiate with prefix, and shadow tracking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from krach.ir.module import ModuleIr, NodeDef
from krach.mixer import Mixer


def _make_mixer() -> Mixer:
    session = MagicMock()
    session.list_nodes.return_value = [
        "faust:osc", "faust:verb", "faust:bus", "dac", "gain",
    ]
    return Mixer(session=session, dsp_dir=Path("/tmp"), node_controls={
        "faust:osc": ("freq", "gate"),
        "faust:verb": ("room",),
        "faust:bus": (),
    })


# ── ModuleHandle basics ─────────────────────────────────────────────────


def test_module_handle_frozen() -> None:
    """ModuleHandle is a frozen dataclass."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    handle = mixer.instantiate(ir, "synth")
    with pytest.raises(AttributeError):
        handle.prefix = "other"  # type: ignore[misc]


def test_module_handle_prefix() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    handle = mixer.instantiate(ir, "synth")
    assert handle.prefix == "synth"


def test_module_handle_repr() -> None:
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        inputs=("osc",),
        outputs=("osc",),
    )
    handle = mixer.instantiate(ir, "synth")
    r = repr(handle)
    assert "synth" in r
    assert "osc" in r


# ── ModuleHandle operators ──────────────────────────────────────────────


def test_module_handle_rshift() -> None:
    """bass >> loop works where loop is a ModuleHandle."""
    mixer = _make_mixer()
    bass = mixer.voice("bass", "faust:osc", gain=0.3)
    ir = ModuleIr(
        nodes=(NodeDef(name="verb", source="faust:verb"),),
        inputs=("verb",),
        outputs=("verb",),
    )
    loop = mixer.instantiate(ir, "loop")
    bass >> loop  # type: ignore[operator]
    # Should have created a send from bass to loop's first input
    assert ("bass", "loop/verb") in mixer._sends


def test_module_handle_rrshift() -> None:
    """loop >> verb works where loop is a ModuleHandle outputting."""
    mixer = _make_mixer()
    verb = mixer.voice("verb", "faust:verb", gain=0.3)
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    loop = mixer.instantiate(ir, "loop")
    loop >> verb
    assert ("loop/osc", "verb") in mixer._sends


def test_module_handle_getitem() -> None:
    """loop['osc/freq'] = 440 controls prefixed node."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
    )
    handle = mixer.instantiate(ir, "loop")
    handle["osc/freq"] = 440.0
    assert mixer._ctrl_values.get("loop/osc/freq") == 440.0


def test_module_handle_setitem() -> None:
    """loop['osc/freq'] sets control on prefixed path."""
    mixer = _make_mixer()
    ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    handle = mixer.instantiate(ir, "loop")
    handle["osc/freq"] = 220.0
    assert mixer._ctrl_values.get("loop/osc/freq") == 220.0


# ── Mixer.load() (renamed from instantiate) ─────────────────────────────


def test_load_replays_ir() -> None:
    """Mixer.load(ir) replays a ModuleIr without prefix (session replay)."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        tempo=128.0,
    )
    mixer.load(ir)
    assert "osc" in mixer._nodes
    assert mixer.tempo == 128.0


def test_load_returns_none() -> None:
    """load() returns None (not a handle)."""
    mixer = _make_mixer()
    ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    result = mixer.load(ir)
    assert result is None


# ── Shadow tracking ─────────────────────────────────────────────────────


def test_capture_includes_sub_modules_after_instantiate() -> None:
    """After instantiate, capture() returns IR with sub_modules populated."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
        outputs=("osc",),
    )
    mixer.instantiate(ir, "synth")
    captured = mixer.capture()
    assert len(captured.sub_modules) == 1
    assert captured.sub_modules[0][0] == "synth"


def test_remove_cleans_shadow() -> None:
    """remove() cleans up shadow sub_modules too."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
    )
    mixer.instantiate(ir, "synth")
    mixer.remove("synth")
    captured = mixer.capture()
    assert captured.sub_modules == ()
    assert "synth/osc" not in mixer._nodes


def test_remove_after_instantiate_leaves_empty_capture() -> None:
    """Regression: remove after instantiate leaves empty capture."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(NodeDef(name="osc", source="faust:osc"),),
    )
    mixer.instantiate(ir, "synth")
    mixer.remove("synth")
    captured = mixer.capture()
    assert captured.nodes == ()
    assert captured.sub_modules == ()
