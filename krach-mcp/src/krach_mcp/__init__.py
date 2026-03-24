"""krach-mcp — MCP server exposing the krach audio engine to Claude Code."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from krach_mcp._session import get_session
from krach_mcp._tools import register_tools

mcp = FastMCP("krach")
register_tools(mcp)


def main() -> None:
    mcp.run(transport="stdio")
