"""HTTP API of the Allocation Editor (see docs/features/allocation.md).

Sets and scenarios
    GET    /api/allocation/architectures            candidate source/target architectures
    GET    /api/allocation/sets                     every set with its scenarios
    POST   /api/allocation/sets                     {name, source, target, description?,
                                                     require_complete_coverage?, scenario?}
    GET    /api/allocation/sets/<set>
    PATCH  /api/allocation/sets/<set>               {name?, description?, source?, target?,
                                                     require_complete_coverage?, force?}
    DELETE /api/allocation/sets/<set>
    POST   /api/allocation/sets/<set>/scenarios     {name?}
    POST   /api/allocation/scenarios                {set, name?}
    PATCH  /api/allocation/scenarios/<scenario>     {name}
    DELETE /api/allocation/scenarios/<scenario>
    POST   /api/allocation/scenarios/<scenario>/duplicate   {name?}

Allocations
    POST   /api/allocation/allocate                 {scenario, source, target}
    POST   /api/allocation/deallocate               {scenario, source, target} | {allocation}
    POST   /api/allocation/toggle                   {scenario, source, target}

Queries
    GET    /api/allocation/scenarios/<scenario>/matrix?rows=&cols=&show=&col_show=&q=&col_q=
    GET    /api/allocation/scenarios/<scenario>/allocations
    GET    /api/allocation/scenarios/<scenario>/coverage?kinds=&leaves=
    GET    /api/allocation/scenarios/<scenario>/map
    GET    /api/allocation/allocated_to/<element>?scenario=
    GET    /api/allocation/allocated_from/<element>?scenario=
    GET    /api/allocation/element/<element>        allocations touching an element
    GET    /api/allocation/chain/<element>          multi-level chain (+ Mermaid)

References are element ids or qualified names (URL-encoded in paths). A
scenario reference may also name a set (its first scenario is used).
"""
from __future__ import annotations

import functools
import urllib.parse
from typing import Any, Callable

from engine import allocation as A
from engine.allocation import AllocationError
from webapp.core import (
    err, ok, register_kind, register_prop_hook, register_summary_hook, route, session,
)


def _api(fn: Callable) -> Callable:
    """URL-decode path parameters; turn AllocationError into a JSON error with its status."""
    @functools.wraps(fn)
    def wrapper(req: dict, **path: str):
        try:
            return fn(req, **{k: urllib.parse.unquote(v) for k, v in path.items()})
        except AllocationError as ex:
            return err(str(ex), ex.status)
    return wrapper


def _find(ref: Any, what: str):
    if not isinstance(ref, str) or not ref:
        raise AllocationError(f"{what} is required")
    e = session().find(ref)
    if e is None:
        raise AllocationError(f"{what} {ref!r} not found", 404)
    return e


def _opt_find(ref: Any, what: str):
    """Like _find, but a missing reference yields None (the engine reports it)."""
    if ref in (None, ""):
        return None
    return _find(ref, what)


def _set(ref: Any) -> A.AllocationSet:
    e = _find(ref, "allocation set")
    if not isinstance(e, A.AllocationSet):
        raise AllocationError(f"{e.qualified_name!r} is a {e.kind}, not an allocation set")
    return e


def scenario_ref(ref: Any) -> A.AllocationScenario:
    e = _find(ref, "scenario")
    if isinstance(e, A.AllocationSet):
        if not e.scenarios:
            raise AllocationError(f"allocation set {e.name!r} has no scenario", 404)
        return e.scenarios[0]
    if not isinstance(e, A.AllocationScenario):
        raise AllocationError(f"{e.qualified_name!r} is a {e.kind}, not an allocation scenario")
    return e


def _body(req: dict) -> dict:
    body = req.get("body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AllocationError("request body must be a JSON object")
    return body


def _query(req: dict) -> dict:
    return req.get("query") or {}


def _opt_scenario(req: dict):
    ref = _query(req).get("scenario")
    return scenario_ref(ref) if ref else None


def _flag(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


# --- sets and scenarios --------------------------------------------------

@route("GET", r"^/api/allocation/architectures$")
@_api
def api_architectures(req: dict):
    return ok(A.architecture_candidates(session().repo))


@route("GET", r"^/api/allocation/sets$")
@_api
def api_sets(req: dict):
    return ok([A.set_summary(s) for s in A.allocation_sets(session().repo)])


@route("POST", r"^/api/allocation/sets$")
@_api
def api_create_set(req: dict):
    b = _body(req)
    repo = session().repo
    s = A.create_allocation_set(
        repo, b.get("name"),
        _find(b.get("source"), "source architecture"),
        _find(b.get("target"), "target architecture"),
        description=b.get("description") or "",
        require_complete_coverage=b.get("require_complete_coverage", False),
        scenario_name=b.get("scenario") or "Scenario 1")
    return ok(A.set_summary(s))


@route("GET", r"^/api/allocation/sets/(?P<sid>[^/]+)$")
@_api
def api_get_set(req: dict, sid: str):
    return ok(A.set_summary(_set(sid)))


@route("PATCH", r"^/api/allocation/sets/(?P<sid>[^/]+)$")
@_api
def api_update_set(req: dict, sid: str):
    s = _set(sid)
    b = _body(req)
    changes: dict[str, Any] = {}
    for key in ("name", "description", "require_complete_coverage"):
        if key in b:
            changes[key] = b[key]
    for key in ("source", "target"):
        if key in b:
            changes[key] = _find(b[key], f"{key} architecture")
    A.update_allocation_set(session().repo, s, force=bool(b.get("force")), **changes)
    return ok(A.set_summary(s))


@route("DELETE", r"^/api/allocation/sets/(?P<sid>[^/]+)$")
@_api
def api_delete_set(req: dict, sid: str):
    s = _set(sid)
    A.delete_allocation_set(session().repo, s)
    return ok({"deleted": s.element_id})


@route("POST", r"^/api/allocation/sets/(?P<sid>[^/]+)/scenarios$")
@_api
def api_create_scenario(req: dict, sid: str):
    sc = A.create_scenario(session().repo, _set(sid), _body(req).get("name") or None)
    return ok(A.scenario_summary(sc))


@route("POST", r"^/api/allocation/scenarios$")
@_api
def api_create_scenario_body(req: dict):
    b = _body(req)
    sc = A.create_scenario(session().repo, _set(b.get("set")), b.get("name") or None)
    return ok(A.scenario_summary(sc))


@route("PATCH", r"^/api/allocation/scenarios/(?P<sid>[^/]+)$")
@_api
def api_rename_scenario(req: dict, sid: str):
    sc = scenario_ref(sid)
    b = _body(req)
    if "name" in b:
        A.rename_scenario(sc, b["name"])
    if "description" in b:
        A._set_doc(sc, b["description"])
    return ok(A.scenario_summary(sc))


@route("DELETE", r"^/api/allocation/scenarios/(?P<sid>[^/]+)$")
@_api
def api_delete_scenario(req: dict, sid: str):
    sc = scenario_ref(sid)
    A.delete_scenario(session().repo, sc)
    return ok({"deleted": sc.element_id})


@route("POST", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/duplicate$")
@_api
def api_duplicate_scenario(req: dict, sid: str):
    sc = A.duplicate_scenario(session().repo, scenario_ref(sid), _body(req).get("name") or None)
    return ok(A.scenario_summary(sc))


# --- allocations ---------------------------------------------------------

def _ends(b: dict):
    return _find(b.get("source"), "source element"), _find(b.get("target"), "target element")


@route("POST", r"^/api/allocation/allocate$")
@_api
def api_allocate(req: dict):
    b = _body(req)
    src, tgt = _ends(b)
    a = A.allocate(session().repo, scenario_ref(b.get("scenario")), src, tgt)
    return ok(A.allocation_summary(a))


@route("POST", r"^/api/allocation/deallocate$")
@_api
def api_deallocate(req: dict):
    b = _body(req)
    repo = session().repo
    if b.get("allocation"):
        a = _find(b["allocation"], "allocation")
        if not isinstance(a, A.ArchitectureAllocation):
            raise AllocationError(f"{a.qualified_name!r} is a {a.kind}, not an allocation")
        repo.remove(a)
        return ok({"deleted": a.element_id})
    src, tgt = _ends(b)
    A.deallocate(repo, scenario_ref(b.get("scenario")), src, tgt)
    return ok({"deallocated": True, "source_id": src.element_id, "target_id": tgt.element_id})


@route("POST", r"^/api/allocation/toggle$")
@_api
def api_toggle(req: dict):
    b = _body(req)
    src, tgt = _ends(b)
    a = A.toggle_allocation(session().repo, scenario_ref(b.get("scenario")), src, tgt)
    return ok({"allocated": a is not None, "allocation": A.allocation_summary(a) if a else None})


# --- queries -------------------------------------------------------------

@route("GET", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/matrix$")
@_api
def api_matrix(req: dict, sid: str):
    q = _query(req)
    return ok(A.matrix(scenario_ref(sid), rows=q.get("rows"), cols=q.get("cols"),
                       show=q.get("show"), col_show=q.get("col_show"),
                       text=q.get("q", ""), col_text=q.get("col_q", "")))


@route("GET", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/allocations$")
@_api
def api_allocations(req: dict, sid: str):
    return ok([A.allocation_summary(a) for a in A.allocations(scenario_ref(sid))])


@route("GET", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/coverage$")
@_api
def api_coverage(req: dict, sid: str):
    q = _query(req)
    return ok(A.coverage(scenario_ref(sid), kinds=q.get("kinds") or ("component", "function"),
                         leaves_only=_flag(q.get("leaves"), True)))


@route("GET", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/map$")
@_api
def api_map(req: dict, sid: str):
    return ok(A.allocation_map(scenario_ref(sid)))


@route("GET", r"^/api/allocation/allocated_to/(?P<eid>[^/]+)$")
@_api
def api_allocated_to(req: dict, eid: str):
    e = _find(eid, "element")
    return ok([A.element_ref(x) for x in A.allocated_to(e, _opt_scenario(req))])


@route("GET", r"^/api/allocation/allocated_from/(?P<eid>[^/]+)$")
@_api
def api_allocated_from(req: dict, eid: str):
    e = _find(eid, "element")
    return ok([A.element_ref(x) for x in A.allocated_from(e, _opt_scenario(req))])


@route("GET", r"^/api/allocation/element/(?P<eid>[^/]+)$")
@_api
def api_element(req: dict, eid: str):
    e = _find(eid, "element")
    both = A.allocations_of(e, _opt_scenario(req))
    return ok({"element": A.element_ref(e), "category": A.category_of(e),
               "to": [A.allocation_summary(a) for a in both["to"]],
               "from": [A.allocation_summary(a) for a in both["from"]]})


@route("GET", r"^/api/allocation/chain/(?P<eid>[^/]+)$")
@_api
def api_chain(req: dict, eid: str):
    return ok(A.allocation_chain(_find(eid, "element"), direction=_query(req).get("direction") or "LR"))


# --- element JSON, generic PATCH, stereotype applies-to -------------------

def _prop_hook(e, key: str, value: Any) -> bool:
    """Generic PATCH /api/element on a set: architecture refs go through the engine checks."""
    if isinstance(e, A.AllocationSet) and key in ("source_architecture", "target_architecture"):
        target = session().find(value) if isinstance(value, str) and value else None
        if target is None:
            raise AllocationError(f"architecture {value!r} not found", 404)
        A.update_allocation_set(session().repo, e,
                                **{("source" if key.startswith("source") else "target"): target})
        return True
    if isinstance(e, A.AllocationSet) and key == "name":
        A.update_allocation_set(session().repo, e, name=value)
        return True
    if isinstance(e, A.AllocationScenario) and key == "name":
        A.rename_scenario(e, value)
        return True
    return False


register_summary_hook(A.annotate_summary)
register_prop_hook(_prop_hook)
# Lets "Define stereotype" restrict a stereotype to allocations (applies_to: ["Allocation"]).
register_kind("Allocation", A.ArchitectureAllocation)
