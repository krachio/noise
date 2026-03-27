"""Tests for loading DSP nodes from .py files."""

import tempfile
from pathlib import Path

import pytest

from krach_mcp._tools import _node_from_file


def test_node_from_file_not_found() -> None:
    """Raises FileNotFoundError for missing file."""
    from unittest.mock import MagicMock
    kr = MagicMock()
    with pytest.raises(FileNotFoundError, match="not found"):
        _node_from_file(kr, "bass", "/nonexistent/bass.py", 0.5, 1)


def test_node_from_file_no_function() -> None:
    """Raises ValueError if file has no callable."""
    from unittest.mock import MagicMock
    kr = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("x = 42\n")
        f.flush()
        with pytest.raises(ValueError, match="no function"):
            _node_from_file(kr, "bass", f.name, 0.5, 1)


def test_node_from_file_valid_dsp() -> None:
    """Loads a valid DSP function and calls kr.node with DspDef."""
    from unittest.mock import MagicMock
    from krach.graph.node import DspDef

    kr = MagicMock()
    kr.node.return_value = "handle"

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        # No import needed — krs is injected into the exec namespace
        f.write(
            "def bass():\n"
            "    freq = krs.control('freq', 55.0, 20.0, 800.0)\n"
            "    gate = krs.control('gate', 0.0, 0.0, 1.0)\n"
            "    return krs.saw(freq) * gate\n"
        )
        f.flush()
        result = _node_from_file(kr, "bass", f.name, 0.3, 1)

    assert result == "handle"
    kr.node.assert_called_once()
    args = kr.node.call_args
    assert args.args[0] == "bass"
    assert isinstance(args.args[1], DspDef)
    assert args.kwargs["gain"] == 0.3
