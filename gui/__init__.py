"""Tkinter-based GUI front-end for the SysML v2 core engine.

Layout (Cameo-inspired):
+-------------------------------------------------------+
|  Menu  |  Toolbar (New / Open / Save / Add... / Validate)
+-------------------------------------------------------+
| Containment tree   | Properties editor                |
| (Treeview)         | (form for selected element)      |
|                    +----------------------------------+
|                    | Validation log / output          |
+-------------------------------------------------------+

Run with:  python -m gui.app
"""
from __future__ import annotations

from .app import main

__all__ = ["main"]
