"""MCP (Model Context Protocol) server for the SysML v2 core engine.

Run with:
    python -m mcp_server.server

Communicates over stdio using JSON-RPC 2.0 per the MCP specification, so
any MCP-compatible AI agent (Claude Desktop, Claude Code, Cursor, etc.)
can drive the engine.
"""
from .server import main

__all__ = ["main"]
