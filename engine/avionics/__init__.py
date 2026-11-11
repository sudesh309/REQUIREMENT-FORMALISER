"""Avionics domain pack: profile, interface and requirement libraries, safety assessment,
project templates and a complete IMA example.

The pack sits on top of the public APIs of the studio's features (``engine.profiles``,
``interfaces``, ``requirements``, ``allocation``, ``architecture``) and re-implements none
of them. Importing this package registers the FHA persistence codec and the avionics
validator rules (``avionics.*`` rule ids), so projects that use them load and validate
without any other setup.

========================  ====================================================================
Module                    Contents
========================  ====================================================================
``profile``               the ``Avionics`` profile (equipment, IMA, software, bus stereotypes)
``interfaces_lib``        ARINC 429 / 664 / 825 / 653, MIL-STD-1553B, discrete and analog library
``requirements_lib``      ARP4754A and DO-178C skeleton requirement sets, verification guidance
``safety``                Functional Hazard Assessment table, DAL mapping, safety rules
``templates``             "New from template": blank avionics project, complete IMA example
``example``               builder of the complete IMA avionics example
========================  ====================================================================
"""
from __future__ import annotations

from . import profile, interfaces_lib, requirements_lib, safety   # noqa: F401 - registrations
from .profile import ensure_profile
from .safety import (
    CLASSIFICATIONS, DAL_BY_CLASSIFICATION, FhaEntry, FhaTable, add_fha_row, delete_fha_row,
    fha_rows, fha_table, safety_check, update_fha_row,
)

__all__ = [
    "profile", "interfaces_lib", "requirements_lib", "safety", "templates", "example",
    "ensure_profile", "CLASSIFICATIONS", "DAL_BY_CLASSIFICATION", "FhaEntry", "FhaTable",
    "add_fha_row", "update_fha_row", "delete_fha_row", "fha_rows", "fha_table", "safety_check",
]


def __getattr__(name: str):
    # templates / example are large and only needed when a project is created.
    if name in ("templates", "example"):
        import importlib
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(name)
