"""Tests for MCP status() tool — error handling for old engine versions."""

from unittest.mock import MagicMock, patch

from mcp.server.fastmcp import FastMCP

from krach_mcp._tools import register_tools


def _get_status_tool() -> object:
    """Register tools on a throw-away MCP and extract the status function."""
    mcp = FastMCP("test")
    register_tools(mcp)
    # FastMCP stores tools by name
    return mcp._tool_manager._tools["status"].fn


def test_status_catches_unrecognized_message() -> None:
    """status() must return actionable guidance when engine sends 'unrecognized message'."""
    from krach.pattern.session import KernelError

    status_fn = _get_status_tool()
    mock_session = MagicMock()
    mock_session.pull.side_effect = KernelError("unrecognized message: {\"cmd\":\"Status\"}")

    with patch("krach_mcp._tools.get_session", return_value=mock_session):
        result = status_fn()

    assert "start(build=True)" in result
    assert "Error" in result


def test_status_reraises_other_kernel_errors() -> None:
    """status() must re-raise KernelError that isn't about unrecognized messages."""
    import pytest
    from krach.pattern.session import KernelError

    status_fn = _get_status_tool()
    mock_session = MagicMock()
    mock_session.pull.side_effect = KernelError("connection refused")

    with patch("krach_mcp._tools.get_session", return_value=mock_session):
        with pytest.raises(KernelError, match="connection refused"):
            status_fn()
