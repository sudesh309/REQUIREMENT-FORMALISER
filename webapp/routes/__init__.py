"""Route plugins for the web backend.

Every module in this package is imported at server start-up. Register
handlers with ``webapp.core.route``; see ``webapp/core.py`` for the API.
"""
from __future__ import annotations

import importlib
import pkgutil


def load_plugins() -> list[str]:
    loaded = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        importlib.import_module(f"{__name__}.{info.name}")
        loaded.append(info.name)
    return loaded
