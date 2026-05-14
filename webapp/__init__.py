"""Web frontend for the SysML v2 core engine.

Run with:
    python -m webapp.server

Then open http://localhost:8765 in your browser.
"""
from .server import main

__all__ = ["main"]
