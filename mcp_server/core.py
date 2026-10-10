"""Shared state for the MCP server and its tool plugins.

Tool plugins (modules in ``mcp_server/tools/``) import from here, never from
``mcp_server.server``: under ``python -m mcp_server.server`` that module runs
as ``__main__``, so importing it again would create a second, empty session.

A tool plugin module defines ``TOOLS = [{"name", "description", "inputSchema",
"handler"}, ...]``; handlers return ``_ok(result)`` or ``_err(message)``.
Use ``register_kind`` to make new metaclasses creatable via sysml_create_element.
"""
from __future__ import annotations

from typing import Any, Optional

from engine import Repository
from kerml.elements import Element
from kerml.features import Feature
from kerml.namespaces import Package
from kerml.stereotypes import Stereotype
from sysmlv2 import (
    ActionDefinition, ActionUsage,
    AttributeDefinition, AttributeUsage,
    CalculationDefinition, CalculationUsage,
    ConnectionDefinition, ConnectionUsage,
    ConstraintDefinition, ConstraintUsage,
    EnumerationDefinition,
    InterfaceDefinition, InterfaceUsage,
    ItemDefinition, ItemUsage,
    ParameterDefinition, ParameterUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage,
    StateDefinition, StateUsage,
)
from sysmlv2.state_machines import StateMachineRunner


# --- kind registry -------------------------------------------------------

KIND_REGISTRY: dict[str, type[Element]] = {
    "Package":               Package,
    "PartDefinition":        PartDefinition,
    "PartUsage":             PartUsage,
    "ItemDefinition":        ItemDefinition,
    "ItemUsage":             ItemUsage,
    "AttributeDefinition":   AttributeDefinition,
    "AttributeUsage":        AttributeUsage,
    "PortDefinition":        PortDefinition,
    "PortUsage":             PortUsage,
    "InterfaceDefinition":   InterfaceDefinition,
    "InterfaceUsage":        InterfaceUsage,
    "ConnectionDefinition":  ConnectionDefinition,
    "ConnectionUsage":       ConnectionUsage,
    "ActionDefinition":      ActionDefinition,
    "ActionUsage":           ActionUsage,
    "StateDefinition":       StateDefinition,
    "StateUsage":            StateUsage,
    "ConstraintDefinition":  ConstraintDefinition,
    "ConstraintUsage":       ConstraintUsage,
    "RequirementDefinition": RequirementDefinition,
    "RequirementUsage":      RequirementUsage,
    "EnumerationDefinition": EnumerationDefinition,
    "ParameterDefinition":   ParameterDefinition,
    "ParameterUsage":        ParameterUsage,
    "CalculationDefinition": CalculationDefinition,
    "CalculationUsage":      CalculationUsage,
    "Stereotype":            Stereotype,
}


# --- session -------------------------------------------------------------

_SUMMARY_HOOKS: list = []


def register_summary_hook(fn) -> None:
    """``fn(element, summary_dict)`` adds fields to element summaries returned by tools."""
    _SUMMARY_HOOKS.append(fn)


class Session:
    """Holds the active repository for the duration of the MCP connection."""

    def __init__(self) -> None:
        self.repo: Repository = Repository(name="UntitledProject")
        # Active state-machine runners, keyed by SM element_id.
        self.runners: dict[str, StateMachineRunner] = {}
        # Free-form per-session state for tool plugins, keyed by plugin name.
        self.plugin_state: dict[str, Any] = {}

    # -- resolution ----------------------------------------------------
    def find(self, ref: str) -> Optional[Element]:
        """Find an element by UUID first, then by qualified name."""
        if not ref:
            return None
        hit = self.repo.by_id(ref)
        if hit is not None:
            return hit
        return self.repo.resolve(ref)

    # -- serialization helpers -----------------------------------------
    def element_summary(self, e: Element) -> dict[str, Any]:
        out = {
            "id": e.element_id,
            "kind": e.kind,
            "name": e.name,
            "qualified_name": e.qualified_name,
            "owner_id": e.owner.element_id if e.owner else None,
            "is_abstract": getattr(e, "is_abstract", False),
        }
        if isinstance(e, Feature):
            up = e.multiplicity.upper
            out["multiplicity"] = [e.multiplicity.lower, "*" if up is None else up]
            out["typed_by"] = [t.qualified_name for t in e.types]
        for attr in ("req_id", "text"):
            if hasattr(e, attr):
                v = getattr(e, attr)
                if v is not None:
                    out[attr] = v
        if hasattr(e, "ends"):
            out["ends"] = [f.qualified_name for f in getattr(e, "ends", []) if f]
        for hook in _SUMMARY_HOOKS:
            hook(e, out)
        return out

    def set_repo(self, repo: Repository) -> None:
        """Switch projects, dropping runtime state tied to the old one."""
        self.repo = repo
        self.runners.clear()
        self.plugin_state.clear()

    def tree(self, e: Element) -> dict[str, Any]:
        node = self.element_summary(e)
        node["children"] = [self.tree(c) for c in e.owned_elements]
        return node


SESSION = Session()


# --- tool implementations ------------------------------------------------

def _ok(payload: Any) -> dict:
    return {"ok": True, "result": payload}


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


def register_kind(name: str, cls: type[Element]) -> None:
    KIND_REGISTRY[name] = cls
