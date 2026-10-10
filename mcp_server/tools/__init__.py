"""MCP tool plugins.

Every module in this package is imported at server start-up and must define
``TOOLS``: a list of ``{"name", "description", "inputSchema", "handler"}``
dicts. Import shared state from ``mcp_server.core``.
"""
from __future__ import annotations

import importlib
import pkgutil


def load_tools() -> list[dict]:
    tools: list[dict] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        tools.extend(getattr(module, "TOOLS", []))
    return tools
