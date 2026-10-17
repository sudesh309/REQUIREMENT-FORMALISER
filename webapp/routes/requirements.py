"""HTTP API for requirements and traceability (System Composer Requirements Perspective).

All endpoints live under ``/api/req``; errors are ``400 {"error": "..."}`` with a message
meant for the user (``404`` when a referenced element does not exist).

    GET    /api/req/meta                         enumerations, link types, matrix column kinds
    GET    /api/req/sets                         requirement sets with roll-ups
    POST   /api/req/sets                         {name, prefix?, parent?, description?}
    PATCH  /api/req/sets/<sid>                   {name?, prefix?, description?}
    GET    /api/req/table?set=<sid>              sets + requirement rows + test cases (all sets without ?set)
    POST   /api/req/requirements                 {parent (set or requirement), after?, id?, summary?, ...}
    PATCH  /api/req/requirements/<rid>           {id?, summary?, description?, rationale?, type?, priority?,
                                                  status?, verification_method?}
    DELETE /api/req/requirements/<rid>
    POST   /api/req/requirements/<rid>/move      {direction: up|down|indent|outdent}
    POST   /api/req/test-cases                   {parent, name?, description?, result?}
    PATCH  /api/req/test-cases/<tid>             {name?, description?, result?}
    DELETE /api/req/test-cases/<tid>
    GET    /api/req/links?element=<id>           trace links touching an element (with suspect flags)
    POST   /api/req/links                        {type, source, target}
    POST   /api/req/links/batch                  {type, sources[], target} or {type, source, targets[]}
    DELETE /api/req/links/<lid>
    POST   /api/req/links/<lid>/clear-suspect
    POST   /api/req/clear-suspect                {element?}  every suspect link of an element / the project
    GET    /api/req/status?target=<id>           roll-up of a set / requirement (all sets without target)
    GET    /api/req/matrix?set=&columns=&column_set=
    GET    /api/req/diagram?element=&depth=      Mermaid traceability graph
    POST   /api/req/import                       {format: csv|reqif, text, set? | new_set?, prefix?}
    GET    /api/req/export?format=&set=&columns= {format, filename, text}
"""
from __future__ import annotations

from typing import Any, Callable

import engine.requirements as rq
from webapp.core import (
    err, ok, register_kind, register_prop_hook, register_summary_hook, route, session,
)
from sysmlv2 import VerificationCaseDefinition

register_kind("RequirementSet", rq.RequirementSet)
register_kind("VerificationCaseDefinition", VerificationCaseDefinition)


class _NotFound(Exception):
    pass


def _guard(fn: Callable) -> Callable:
    def wrapper(req: dict, **kw: Any):
        try:
            return fn(req, **kw)
        except _NotFound as ex:
            return err(str(ex), 404)
        except rq.RequirementsError as ex:
            return err(str(ex))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _repo():
    return session().repo


def _find(ref: Any, what: str = "element"):
    e = session().find(ref) if isinstance(ref, str) and ref else None
    if e is None:
        raise _NotFound(f"{what} {ref!r} not found")
    return e


def _set(ref: Any, *, optional: bool = False):
    if not ref:
        if optional:
            return None
        raise rq.RequirementsError("Choose a requirement set.")
    e = _find(ref, "requirement set")
    if not isinstance(e, rq.RequirementSet):
        raise rq.RequirementsError(f"{e.qualified_name} is not a requirement set.")
    return e


def _requirement(ref: Any):
    e = _find(ref, "requirement")
    if not rq.is_requirement(e):
        raise rq.RequirementsError(f"{e.qualified_name} is not a requirement.")
    return e


def _body(req: dict) -> dict:
    body = req.get("body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise rq.RequirementsError("The request body must be a JSON object.")
    return body


def _row(e) -> dict:
    """The table row for one requirement (statuses computed against its whole set)."""
    return rq.requirement_status(_repo(), e)["requirement"]


# --- meta + sets --------------------------------------------------------

@route("GET", r"^/api/req/meta$")
def api_meta(_req: dict):
    return ok(rq.meta())


@route("GET", r"^/api/req/sets$")
@_guard
def api_sets(_req: dict):
    repo = _repo()
    index = rq.LinkIndex(repo)
    return ok([rq.set_summary(repo, s, index) for s in rq.requirement_sets(repo)])


@route("POST", r"^/api/req/sets$")
@_guard
def api_create_set(req: dict):
    body = _body(req)
    parent = _find(body["parent"], "parent") if body.get("parent") else None
    s = rq.create_requirement_set(_repo(), body.get("name"), prefix=body.get("prefix"),
                                  parent=parent, description=body.get("description"))
    return ok(rq.set_summary(_repo(), s))


@route("PATCH", r"^/api/req/sets/(?P<sid>[^/]+)$")
@_guard
def api_update_set(req: dict, sid: str):
    body = _body(req)
    s = rq.update_requirement_set(_repo(), _set(sid), name=body.get("name"),
                                  prefix=body.get("prefix"), description=body.get("description"))
    return ok(rq.set_summary(_repo(), s))


@route("GET", r"^/api/req/table$")
@_guard
def api_table(req: dict):
    q = req.get("query") or {}
    return ok(rq.requirements_table(_repo(), _set(q.get("set"), optional=True)))


# --- requirements -------------------------------------------------------

@route("POST", r"^/api/req/requirements$")
@_guard
def api_add_requirement(req: dict):
    body = dict(_body(req))
    parent = _find(body.pop("parent", None) or body.pop("set", None), "parent")
    after_ref = body.pop("after", None)
    after = _requirement(after_ref) if after_ref else None
    r = rq.add_requirement(_repo(), parent, body, after=after)
    return ok(_row(r))


@route("PATCH", r"^/api/req/requirements/(?P<rid>[^/]+)$")
@_guard
def api_update_requirement(req: dict, rid: str):
    r = rq.update_requirement(_repo(), _requirement(rid), _body(req))
    return ok(_row(r))


@route("DELETE", r"^/api/req/requirements/(?P<rid>[^/]+)$")
@_guard
def api_delete_requirement(_req: dict, rid: str):
    return ok({"deleted": rq.delete_requirement(_repo(), _requirement(rid))})


@route("POST", r"^/api/req/requirements/(?P<rid>[^/]+)/move$")
@_guard
def api_move_requirement(req: dict, rid: str):
    r = rq.move_requirement(_repo(), _requirement(rid), _body(req).get("direction"))
    return ok(_row(r))


# --- test cases ---------------------------------------------------------

@route("POST", r"^/api/req/test-cases$")
@_guard
def api_add_test_case(req: dict):
    body = _body(req)
    parent = _find(body.get("parent") or body.get("set"), "parent")
    tc = rq.add_test_case(_repo(), parent, body.get("name"), description=body.get("description"),
                          result=body.get("result"))
    return ok(rq.test_case_row(_repo(), tc, rq.LinkIndex(_repo())))


@route("PATCH", r"^/api/req/test-cases/(?P<tid>[^/]+)$")
@_guard
def api_update_test_case(req: dict, tid: str):
    tc = rq.update_test_case(_repo(), _find(tid, "test case"), _body(req))
    return ok(rq.test_case_row(_repo(), tc, rq.LinkIndex(_repo())))


@route("DELETE", r"^/api/req/test-cases/(?P<tid>[^/]+)$")
@_guard
def api_delete_test_case(_req: dict, tid: str):
    rq.delete_test_case(_repo(), _find(tid, "test case"))
    return ok({"deleted": tid})


# --- links --------------------------------------------------------------

def _link(ref: str):
    rel = _repo().by_id(ref)
    if rel is None or not isinstance(rel, rq.TRACE_CLASSES):
        raise _NotFound(f"link {ref!r} not found")
    return rel


@route("GET", r"^/api/req/links$")
@_guard
def api_links(req: dict):
    e = _find((req.get("query") or {}).get("element"), "element")
    return ok({"element": rq.element_info(e), "traceable": rq.is_linkable(e),
               "links": rq.links_for(_repo(), e)})


@route("POST", r"^/api/req/links$")
@_guard
def api_create_link(req: dict):
    body = _body(req)
    rel = rq.create_trace_link(_repo(), body.get("type"), _find(body.get("source"), "source"),
                               _find(body.get("target"), "target"))
    return ok(rq.link_info(rel))


@route("POST", r"^/api/req/links/batch$")
@_guard
def api_create_links(req: dict):
    """One link per source (or per target); per-pair errors are reported, not raised."""
    body = _body(req)
    pairs = []
    if body.get("sources") is not None:
        target = _find(body.get("target"), "target")
        pairs = [(s, target) for s in body["sources"]]
    elif body.get("targets") is not None:
        source = _find(body.get("source"), "source")
        pairs = [(source, t) for t in body["targets"]]
    else:
        raise rq.RequirementsError("Give 'sources' (with a target) or 'targets' (with a source).")
    created, errors = [], []
    for s, t in pairs:
        try:
            src = s if not isinstance(s, str) else _find(s, "source")
            tgt = t if not isinstance(t, str) else _find(t, "target")
            created.append(rq.link_info(rq.create_trace_link(_repo(), body.get("type"), src, tgt)))
        except (rq.RequirementsError, _NotFound) as ex:
            errors.append(str(ex))
    if not created and errors:
        raise rq.RequirementsError("; ".join(errors))
    return ok({"created": created, "errors": errors})


@route("DELETE", r"^/api/req/links/(?P<lid>[^/]+)$")
@_guard
def api_delete_link(_req: dict, lid: str):
    rq.delete_trace_link(_repo(), _link(lid))
    return ok({"deleted": lid})


@route("POST", r"^/api/req/links/(?P<lid>[^/]+)/clear-suspect$")
@_guard
def api_clear_suspect(_req: dict, lid: str):
    return ok(rq.link_info(rq.clear_suspect(_repo(), _link(lid))))


@route("POST", r"^/api/req/clear-suspect$")
@_guard
def api_clear_all_suspect(req: dict):
    ref = _body(req).get("element")
    element = _find(ref, "element") if ref else None
    return ok({"cleared": rq.clear_suspect_for(_repo(), element)})


# --- status, matrix, diagram -------------------------------------------

@route("GET", r"^/api/req/status$")
@_guard
def api_status(req: dict):
    ref = (req.get("query") or {}).get("target")
    return ok(rq.requirement_status(_repo(), _find(ref) if ref else None))


@route("GET", r"^/api/req/matrix$")
@_guard
def api_matrix(req: dict):
    q = req.get("query") or {}
    return ok(rq.trace_matrix(_repo(), _set(q.get("set"), optional=True),
                              q.get("columns") or "components",
                              _set(q.get("column_set"), optional=True)))


@route("GET", r"^/api/req/diagram$")
@_guard
def api_diagram(req: dict):
    q = req.get("query") or {}
    return ok(rq.trace_diagram(_repo(), _find(q.get("element"), "element"), q.get("depth") or 2))


# --- import / export ----------------------------------------------------

@route("POST", r"^/api/req/import$")
@_guard
def api_import(req: dict):
    """Uploaded content only (the browser reads the file); server-side paths are not accepted."""
    body = _body(req)
    report = rq.import_requirements(_repo(), body.get("format"), body.get("text"),
                                    rset=_set(body.get("set"), optional=True),
                                    new_set=body.get("new_set"), prefix=body.get("prefix"))
    return ok(report)


@route("GET", r"^/api/req/export$")
@_guard
def api_export(req: dict):
    q = req.get("query") or {}
    return ok(rq.export_requirements(_repo(), q.get("format") or "csv",
                                     _set(q.get("set"), optional=True),
                                     columns=q.get("columns") or "components"))


# --- element JSON and generic property edits ---------------------------

def _summary_hook(e, d: dict) -> None:
    if rq.is_requirement(e):
        s = rq.set_of(e)
        d["requirement"] = {**rq.requirement_fields(e), "set_id": s.element_id if s else None}
        d["traceable"] = True
        if e.req_id:
            d["badges"].append(e.req_id)
    elif rq.is_test_case(e):
        d["verification_result"] = rq.test_result(e)
        d["traceable"] = True
        d["badges"].append(rq.test_result(e))
    elif isinstance(e, rq.RequirementSet):
        d["requirement_set"] = {"prefix": e.id_prefix}
        d["badges"].append("req set")
    elif rq.is_linkable(e):
        d["traceable"] = True
        n = sum(1 for r in e.owned_relationships
                if isinstance(r, rq.Satisfy) and r.source is e and rq.is_requirement(r.target))
        if n:
            d["badges"].append(f"{n} req")


register_summary_hook(_summary_hook)


def _prop_hook(e, key: str, value: Any) -> bool:
    """Validate requirement fields edited through PATCH /api/element (the Properties form)."""
    if rq.is_requirement(e):
        repo = _repo()
        if key in ("req_type", "priority", "req_status", "verification_method", "rationale"):
            rq.update_requirement(repo, e, {key: value})
            return True
        if key in ("req_id", "name"):
            new = rq._clean_text(key, value)
            if new == getattr(e, key, None):
                return True
            if rq.set_of(e) is not None:
                rq.update_requirement(repo, e, {key: value})
                return True
            rq.baseline_untracked(repo)
            return False
        if key == "text":
            if (value or None) != (e.text or None):
                rq.baseline_untracked(repo)
            return False
    if rq.is_test_case(e) and key == "verification_result":
        rq.update_test_case(_repo(), e, {"result": value})
        return True
    return False


register_prop_hook(_prop_hook)
