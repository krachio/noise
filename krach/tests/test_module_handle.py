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
    _ = loop >> verb
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


def test_recall_clears_shadow_sub_modules() -> None:
    """Regression: recall() must clear _shadow_sub_modules from previous state."""
    mixer = _make_mixer()
    ir_a = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    # Save a clean scene (no modules)
    mixer.save("clean")
    # Instantiate a module — adds to _shadow_sub_modules
    mixer.instantiate(ir_a, "synth")
    assert len(mixer._shadow_sub_modules) == 1
    # Recall clean scene — shadow must be cleared
    mixer.recall("clean")
    assert mixer._shadow_sub_modules == []


def test_load_flattens_sub_modules() -> None:
    """Regression: load() must flatten sub_modules so nested nodes are replayed."""
    mixer = _make_mixer()
    # Build an IR that has sub_modules (as if captured after instantiate)
    child_ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    parent_ir = ModuleIr(
        nodes=(NodeDef(name="bus", source="faust:bus"),),
        sub_modules=(("child", child_ir),),
    )
    mixer.load(parent_ir)
    # The flattened sub_module node should exist as "child/osc"
    assert "child/osc" in mixer._nodes
    assert "bus" in mixer._nodes


def test_load_restores_shadow_sub_modules() -> None:
    """Regression: load() must restore _shadow_sub_modules from ir.sub_modules."""
    mixer = _make_mixer()
    child_ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    parent_ir = ModuleIr(
        nodes=(NodeDef(name="bus", source="faust:bus"),),
        sub_modules=(("child", child_ir),),
    )
    mixer.load(parent_ir)
    assert len(mixer._shadow_sub_modules) == 1
    assert mixer._shadow_sub_modules[0][0] == "child"


def test_save_recall_roundtrip_preserves_sub_modules() -> None:
    """Save/recall cycle must preserve module identity via sub_modules."""
    mixer = _make_mixer()
    ir = ModuleIr(nodes=(NodeDef(name="osc", source="faust:osc"),))
    mixer.instantiate(ir, "synth")
    mixer.save("scene1")
    mixer.recall("scene1")
    captured = mixer.capture()
    assert len(captured.sub_modules) == 1
    assert captured.sub_modules[0][0] == "synth"


def test_remove_partial_node_cleans_shadow_when_empty() -> None:
    """Regression: removing last node in a module prefix must clean shadow entry."""
    mixer = _make_mixer()
    ir = ModuleIr(nodes=(NodeDef(name="kick", source="faust:osc"),))
    mixer.instantiate(ir, "drums")
    assert "drums/kick" in mixer._nodes
    # Remove the individual node, not the group
    mixer.remove("drums/kick")
    assert "drums/kick" not in mixer._nodes
    # Shadow should be cleaned since no nodes with "drums/" prefix remain
    captured = mixer.capture()
    assert captured.sub_modules == ()


def test_remove_partial_node_cleans_shadow_when_partial() -> None:
    """Removing one node of a multi-node module must also clean shadow (partial module is invalid)."""
    mixer = _make_mixer()
    ir = ModuleIr(
        nodes=(
            NodeDef(name="kick", source="faust:osc"),
            NodeDef(name="snare", source="faust:osc"),
        ),
    )
    mixer.instantiate(ir, "drums")
    assert "drums/kick" in mixer._nodes
    assert "drums/snare" in mixer._nodes
    # Remove one node — module is now partial, shadow should be removed
    mixer.remove("drums/kick")
    captured = mixer.capture()
    assert captured.sub_modules == ()


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
