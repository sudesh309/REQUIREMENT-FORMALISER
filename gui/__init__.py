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
# `app` is not imported here: doing so would double-load it under
# `python -m gui.app` and force a tkinter import on any `gui.*` import.
