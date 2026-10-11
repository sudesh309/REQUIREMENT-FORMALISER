"""Shared state and helpers for the web backend and its route plugins.

Route plugins (modules in ``webapp/routes/``) import from here, never from
``webapp.server``: under ``python -m webapp.server`` that module runs as
``__main__``, so importing it again would create a second, empty session.

Extension points
----------------
- ``route(method, pattern)``          decorator registering an API handler
- ``register_kind(name, cls)``        make a metaclass creatable via POST /api/element
- ``register_summary_hook(fn)``       ``fn(element, summary_dict)`` adds fields to element JSON
- ``register_prop_hook(fn)``          ``fn(element, key, value) -> bool`` handles a PATCH prop
- ``session()`` / ``reset_session()`` the single shared Session

Handlers receive ``request = {"body": dict|None, "query": dict}`` plus any
named regex groups, and return ``(status, payload)`` — use ``ok()`` / ``err()``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from engine import Repository
from engine.properties import set_property
from kerml.elements import Documentation, Element
from kerml.features import Feature
from kerml.namespaces import Package
from kerml.stereotypes import Stereotype, stereotypes_on
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
from sysmlv2.state_machines import StateMachineDefinition, StateMachineRunner


Body = tuple[int, Any]
Handler = Callable[..., Body]


def ok(payload: Any = None) -> Body:
    return (200, payload if payload is not None else {"ok": True})


def err(message: str, status: int = 400) -> Body:
    return (status, {"error": message})


# --- element kinds ------------------------------------------------------

KIND_REGISTRY: dict[str, type[Element]] = {
    "Package": Package,
    "PartDefinition": PartDefinition, "PartUsage": PartUsage,
    "ItemDefinition": ItemDefinition, "ItemUsage": ItemUsage,
    "AttributeDefinition": AttributeDefinition, "AttributeUsage": AttributeUsage,
    "PortDefinition": PortDefinition, "PortUsage": PortUsage,
    "InterfaceDefinition": InterfaceDefinition, "InterfaceUsage": InterfaceUsage,
    "ConnectionDefinition": ConnectionDefinition, "ConnectionUsage": ConnectionUsage,
    "ActionDefinition": ActionDefinition, "ActionUsage": ActionUsage,
    "CalculationDefinition": CalculationDefinition, "CalculationUsage": CalculationUsage,
    "StateDefinition": StateDefinition, "StateUsage": StateUsage,
    "ConstraintDefinition": ConstraintDefinition, "ConstraintUsage": ConstraintUsage,
    "RequirementDefinition": RequirementDefinition, "RequirementUsage": RequirementUsage,
    "ParameterDefinition": ParameterDefinition, "ParameterUsage": ParameterUsage,
    "EnumerationDefinition": EnumerationDefinition,
    "Stereotype": Stereotype,
}


def register_kind(name: str, cls: type[Element]) -> None:
    KIND_REGISTRY[name] = cls


# --- session ------------------------------------------------------------

class Session:
    def __init__(self) -> None:
        self.repo = Repository(name="UntitledProject")
        self.runners: dict[str, StateMachineRunner] = {}
        # Free-form per-session state for plugins (e.g. undo stacks), keyed by plugin name.
        self.plugin_state: dict[str, Any] = {}

    def find(self, ref: str) -> Optional[Element]:
        if not ref:
            return None
        return self.repo.by_id(ref) or self.repo.resolve(ref)

    def set_repo(self, repo: Repository) -> None:
        """Switch projects, dropping runtime state tied to the old one."""
        self.repo = repo
        self.runners.clear()
        self.plugin_state.clear()


SESSION = Session()


def session() -> Session:
    return SESSION


def reset_session() -> Session:
    """Reset in place so every module holding a reference sees the fresh state."""
    SESSION.__init__()
    return SESSION


# --- element JSON -------------------------------------------------------

_SUMMARY_HOOKS: list[Callable[[Element, dict], None]] = []
_PROP_HOOKS: list[Callable[[Element, str, Any], bool]] = []


def register_summary_hook(fn: Callable[[Element, dict], None]) -> None:
    _SUMMARY_HOOKS.append(fn)


def register_prop_hook(fn: Callable[[Element, str, Any], bool]) -> None:
    _PROP_HOOKS.append(fn)


def summarize(e: Element) -> dict:
    d = {
        "id": e.element_id,
        "kind": e.kind,
        "name": e.name,
        "short_name": e.short_name,
        "qualified_name": e.qualified_name,
        "owner_id": e.owner.element_id if e.owner else None,
        "is_abstract": getattr(e, "is_abstract", False),
        "doc": next((a.body for a in e.annotations if isinstance(a, Documentation)), ""),
        "stereotypes": [
            {"name": app.stereotype.name, "values": app.values}
            for app in stereotypes_on(e)
        ],
        "tool_data": e.tool_data,
    }
    if isinstance(e, Feature):
        up = e.multiplicity.upper
        d["multiplicity"] = [e.multiplicity.lower, "*" if up is None else up]
        d["direction"] = e.direction.value
        d["typed_by"] = [t.qualified_name for t in e.types]
    for attr in ("req_id", "text", "parameter_kind"):
        v = getattr(e, attr, None)
        if v is not None:
            d[attr] = v
    if hasattr(e, "ends"):
        d["ends"] = [f.qualified_name for f in getattr(e, "ends", []) if f]
        d["end_ids"] = [f.element_id for f in getattr(e, "ends", []) if f]
    if isinstance(e, StateMachineDefinition):
        runner = SESSION.runners.get(e.element_id)
        d["sm"] = {
            "states": [s.name for s in e.states],
            "initial": e.initial_state.name if e.initial_state else None,
            "finals":  [s.name for s in e.final_states],
            "transitions": [
                {"from": t.transition_source.name if t.transition_source else None,
                 "to":   t.transition_target.name if t.transition_target else None,
                 "trigger": t.trigger_event,
                 "guard":  t.guard if isinstance(t.guard, str) else (None if t.guard is None else "λ"),
                 "effect": t.effect if isinstance(t.effect, str) else (None if t.effect is None else "λ")}
                for t in e.transitions
            ],
            "current": runner.current.name if runner and runner.current else None,
        }
    for hook in _SUMMARY_HOOKS:
        hook(e, d)
    return d


def tree(e: Element) -> dict:
    return {**summarize(e), "children": [tree(c) for c in e.owned_elements]}


def apply_props(e: Element, props: dict) -> None:
    """Apply a PATCH ``props`` dict; raises ValueError for invalid keys or values."""
    for k, v in props.items():
        if any(hook(e, k, v) for hook in _PROP_HOOKS):
            continue
        set_property(e, k, v, SESSION.find)


# --- plugin routes ------------------------------------------------------

PLUGIN_ROUTES: list[tuple[str, str, Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    """Register an API handler. ``pattern`` is a full-match regex, e.g. r"^/api/views/(?P<vid>[^/]+)$"."""
    def deco(fn: Handler) -> Handler:
        PLUGIN_ROUTES.append((method.upper(), pattern, fn))
        return fn
    return deco
