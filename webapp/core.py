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
- ``register_undo_label(m, pat, l)``  human-readable undo step name of a route (str or fn(ctx))
- ``register_mutation_hook(fn)``      runs around every non-GET request (undo snapshots)
- ``session()`` / ``reset_session()`` the single shared Session

Handlers receive ``request = {"body": dict|None, "query": dict}`` plus any
named regex groups, and return ``(status, payload)`` — use ``ok()`` / ``err()``.
"""
from __future__ import annotations

import re
import threading
import urllib.parse
from typing import Any, Callable, Optional, Union

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
        # Model revision: changes whenever a request changed the model (sent to the
        # browser as the X-Model-Revision header so every view can tell it is stale).
        self.revision = 0

    def find(self, ref: str) -> Optional[Element]:
        """By id or qualified name, root-relative or with the project root in front as
        element JSON gives it (``Repository.resolve``). A percent-encoded name (a URL path
        segment such as ``Avionics%3A%3AADIRU``) is decoded."""
        if not ref or not isinstance(ref, str):
            return None
        if "%" in ref and self.repo.by_id(ref) is None and self.repo.resolve(ref) is None:
            from urllib.parse import unquote
            ref = unquote(ref)
        return self.repo.by_id(ref) or self.repo.resolve(ref)

    def touch(self) -> None:
        """Record that the model changed (see ``revision``)."""
        self.revision += 1

    def set_repo(self, repo: Repository) -> None:
        """Switch projects, dropping runtime state tied to the old one."""
        self.repo = repo
        self.runners.clear()
        self.plugin_state.clear()
        self.touch()


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
        # Cross-feature display contract: summary hooks append short labels to
        # `badges` and set keys in `style` (fill, stroke, text, dash, icon);
        # the tree and the architecture canvas render both.
        "badges": [],
        "style": {},
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


# --- mutation hooks (undo/redo snapshots) -------------------------------

_MUTATION_HOOKS: list[Callable[[str, str, Any], Optional[Callable[[int], None]]]] = []


class Mutation:
    """A non-GET API request, as mutation hooks and undo labels see it. ``status`` and
    ``payload`` (the handler's answer) are set once the handler has run."""

    def __init__(self, method: str, path: str, body: Any, headers: Optional[dict] = None) -> None:
        self.method = method
        self.path = path
        self.body = body
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.status: Optional[int] = None
        self.payload: Any = None


_CURRENT = threading.local()


def current_mutation() -> Optional[Mutation]:
    """The mutating request this thread is serving (None outside one)."""
    return getattr(_CURRENT, "mutation", None)


def register_mutation_hook(fn: Callable[[str, str, Any], Optional[Callable[[int], None]]]) -> None:
    """``fn(method, path, body)`` runs before every non-GET API request; it may return a
    ``finish(status)`` callback that runs after the handler (e.g. to record an undo step).
    ``current_mutation()`` gives both the request headers and, in ``finish``, the payload."""
    _MUTATION_HOOKS.append(fn)


def begin_mutation(method: str, path: str, body: Any,
                   headers: Optional[dict] = None) -> Callable[..., None]:
    m = _CURRENT.mutation = Mutation(method, path, body, headers)
    try:
        finishers = [f for f in (hook(method, path, body) for hook in _MUTATION_HOOKS) if f]
    except Exception:
        _CURRENT.mutation = None
        raise

    def finish(status: int, payload: Any = None) -> None:
        m.status, m.payload = status, payload
        _CURRENT.mutation = m
        try:
            for f in finishers:
                f(status)
        finally:
            _CURRENT.mutation = None
    return finish


# --- undo step labels ---------------------------------------------------
#
# Each feature names the undo steps of its routes ("Set Avionics.LRU.mass of FMS",
# "Allocate ComputeNavigation → CPM1"); the Undo / Redo buttons and the Output log show
# them. A label is a string or ``fn(ctx: LabelContext) -> str``, called after the handler
# ran; requests without a label get a generic one ("Edit allocation"), never a raw route.

LabelSpec = Union[str, Callable[["LabelContext"], Optional[str]]]
_UNDO_LABELS: list[tuple[str, re.Pattern, LabelSpec]] = []
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_VERBS = {"POST": "Change", "PUT": "Edit", "PATCH": "Edit", "DELETE": "Delete"}


def register_undo_label(method: str, pattern: str, label: LabelSpec) -> None:
    """Name the undo step of ``method`` requests whose path matches ``pattern`` (the route's
    regex; its named groups are ``ctx.args``, URL-decoded). Later registrations win."""
    _UNDO_LABELS.insert(0, (method.upper(), re.compile(pattern), label))


class LabelContext:
    """What a label function sees: the request, its answer and the model before / after."""

    def __init__(self, m: Mutation, args: dict, before: Optional[dict] = None) -> None:
        self.method, self.path = m.method, m.path
        self.body = m.body if isinstance(m.body, dict) else {}
        self.payload = m.payload
        self.args = {k: urllib.parse.unquote(v) for k, v in args.items() if v is not None}
        self._before = before
        self._old: Optional[dict] = None

    # model lookups -------------------------------------------------------
    def find(self, ref: Any) -> Optional[Element]:
        """An element of the current model by id or qualified name."""
        return SESSION.find(ref) if isinstance(ref, str) and ref else None

    def old(self, ref: Any) -> Optional[dict]:
        """The saved form of an element before the request (for deleted / renamed ones)."""
        if self._before is None or not isinstance(ref, str):
            return None
        if self._old is None:
            self._old = {}
            for d in self._before.get("elements", ()):
                self._old[d.get("id")] = d
            for d in self._before.get("links", ()):
                self._old[d.get("id")] = d
        return self._old.get(ref)

    def name(self, ref: Any, default: str = "element") -> str:
        """Display name now (requirements by their id, e.g. SYS-3), else before the request."""
        e = self.find(ref)
        if e is not None:
            return display_name(e)
        d = self.old(ref)
        if d:
            return d.get("req_id") or d.get("name") or d.get("kind") or default
        # A reference by name ("Avionics.LRU", "Pkg::FMS") reads well; an unknown id does not.
        if isinstance(ref, str) and ref and not _UUID.search(ref):
            return ref.rsplit("::", 1)[-1]
        return default

    def old_name(self, ref: Any) -> Optional[str]:
        d = self.old(ref)
        return (d.get("req_id") or d.get("name")) if d else None

    def names(self, refs: Any, limit: int = 3) -> str:
        """'ADC, FMS and 2 more'."""
        items = [self.name(r) for r in (refs or [])]
        if len(items) > limit:
            return f"{', '.join(items[:limit])} and {len(items) - limit} more"
        return ", ".join(items)

    def port(self, ref: Any) -> str:
        """'ADIRU.airData' for a port (owner name + port name)."""
        e = self.find(ref)
        if e is not None and e.owner is not None and e.owner is not SESSION.repo.root_package:
            return f"{e.owner.name}.{e.name}"
        return self.name(ref, "port")

    def pid(self, key: str = "id") -> Any:
        """A field of the answer, e.g. the id of what the request created."""
        return self.payload.get(key) if isinstance(self.payload, dict) else None


def display_name(e: Element) -> str:
    return getattr(e, "req_id", None) or e.name or e.kind


def generic_label(method: str, path: str) -> str:
    """'Edit allocation' for routes without a label: no HTTP verbs, paths or ids."""
    parts = [p for p in path.split("/") if p and p != "api"]
    feature = (parts[0] if parts else "model").replace("-", " ").replace("_", " ")
    feature = {"arch": "architecture", "req": "requirements", "sm": "state machine",
               "element": "model", "elements": "model"}.get(feature, feature)
    return f"{_VERBS.get(method, 'Change')} {feature}"


def undo_label(m: Mutation, before: Optional[dict] = None) -> tuple[str, Callable[[], str]]:
    """The undo step label of a request, and a function that recomputes it later (after an
    in-place rename merged into the step, the label names the element's final name)."""
    for verb, pattern, spec in _UNDO_LABELS:
        if verb != m.method:
            continue
        hit = pattern.match(m.path)
        if not hit:
            continue
        ctx = LabelContext(m, hit.groupdict(), before)

        def compute(spec=spec, ctx=ctx) -> str:
            try:
                text = spec(ctx) if callable(spec) else spec
            except Exception:          # noqa: BLE001 - a label must never break an edit
                text = None
            return " ".join(str(text).split()) if text else generic_label(m.method, m.path)
        return compute(), compute
    text = generic_label(m.method, m.path)
    return text, lambda: text


# --- plugin routes ------------------------------------------------------

PLUGIN_ROUTES: list[tuple[str, str, Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    """Register an API handler. ``pattern`` is a full-match regex, e.g. r"^/api/views/(?P<vid>[^/]+)$"."""
    def deco(fn: Handler) -> Handler:
        PLUGIN_ROUTES.append((method.upper(), pattern, fn))
        return fn
    return deco
