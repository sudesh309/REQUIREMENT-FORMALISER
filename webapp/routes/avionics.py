"""HTTP API of the avionics domain pack (see docs/features/avionics.md).

Projects
    GET    /api/avionics/templates                     the project templates (counts with ?counts=1)
    POST   /api/new/avionics                           {template: blank|ima_example, name?} replaces the
                                                       project, like POST /api/new (no undo step: the
                                                       history starts afresh)
    GET    /api/avionics/info                          overview: profile, libraries, FHA, safety counts,
                                                       equipment roll-up, architectures
Profile and libraries
    GET    /api/avionics/profile                       is the Avionics profile there? its stereotypes
    POST   /api/avionics/profile                       create / complete the Avionics profile
    GET    /api/avionics/interfaces/library            catalog with a ``present`` flag per item
    POST   /api/avionics/interfaces/import            {names?, groups?, on_conflict?: skip|rename}
    GET    /api/avionics/requirements/library          skeleton sets + verification guidance per DAL
    POST   /api/avionics/requirements/import          {sets?: [key], dal?}
Safety
    GET    /api/avionics/fha                           rows, vocabularies, function choices
    POST   /api/avionics/fha                           {failure_condition, function?, flight_phase?,
                                                       effect?, classification?, fha_id?, notes?}
    PATCH  /api/avionics/fha/<row>                     any of the fields above
    DELETE /api/avionics/fha/<row>
    GET    /api/avionics/safety                        ?severity=&rule=&element= the avionics.* rule results

References are element ids, qualified names or (FHA rows) FHA ids such as ``FHA-3``.
"""
from __future__ import annotations

import functools
import urllib.parse
from typing import Any, Callable

import engine.requirements as rq
from engine import interfaces as I
from engine import profiles as P
from engine.architecture import ArchitectureError
from engine.avionics import interfaces_lib, requirements_lib, safety as SF, templates
from engine.avionics import profile as AP
from webapp.core import (
    err, ok, register_kind, register_prop_hook, register_summary_hook, register_undo_label as label, route,
    session,
)

_ERRORS = (SF.FhaError, I.InterfaceError, P.ProfileError, ArchitectureError)


def _api(fn: Callable) -> Callable:
    """URL-decode path parameters; turn the engine's errors into JSON errors with their status."""
    @functools.wraps(fn)
    def wrapper(req: dict, **path: str):
        try:
            return fn(req, **{k: urllib.parse.unquote(v) for k, v in path.items()})
        except _ERRORS as ex:
            return err(str(ex), getattr(ex, "status", 400))
        except (rq.RequirementsError, ValueError) as ex:
            return err(str(ex), 400)
    return wrapper


def _body(req: dict) -> dict:
    body = req.get("body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _query(req: dict) -> dict:
    return req.get("query") or {}


def _csv(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v)]
    return [v for v in str(value or "").split(",") if v]


def _flag(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


# --- templates and projects ----------------------------------------------------------------

@route("GET", r"^/api/avionics/templates$")
@_api
def api_templates(req: dict):
    return ok({"templates": templates.list_templates(counts=_flag(_query(req).get("counts")))})


@route("POST", r"^/api/new/avionics$")
@_api
def api_new_avionics(req: dict):
    b = _body(req)
    template = b.get("template") or "blank"
    repo = templates.create_project(template, b.get("name"))
    session().set_repo(repo)
    roots = [{"id": e.element_id, "name": e.name} for e in repo.root_package.children
             if e.kind == "PartDefinition" and (e.name or "").endswith("Architecture")]
    main = next((r for r in roots if r["name"] == "PhysicalArchitecture"), roots[0] if roots else None)
    return ok({"name": repo.name, "root_id": repo.root_package.element_id, "template": template,
               "architectures": roots, "open": main["id"] if main else None,
               "element_count": len(list(repo.all_elements()))})


@route("GET", r"^/api/avionics/info$")
@_api
def api_info(req: dict):
    return ok(templates.overview(session().repo))


# --- profile -------------------------------------------------------------------------------

def _profile_view(repo) -> dict:
    prof = AP.find_profile(repo)
    return {"present": prof is not None, "id": prof.element_id if prof else None,
            "version": prof.version if prof else None,
            "stereotypes": [{"name": s.name, "id": s.element_id, "abstract": s.is_abstract,
                             "base": s.base.name if s.base else None,
                             "applies_to": s.effective_category() or "all",
                             "properties": [t.name for t in s.all_tags()]} for s in prof.stereotypes]
            if prof else [], "expected": [s["name"] for s in AP.STEREOTYPES]}


@route("GET", r"^/api/avionics/profile$")
@_api
def api_profile(req: dict):
    return ok(_profile_view(session().repo))


@route("POST", r"^/api/avionics/profile$")
@_api
def api_ensure_profile(req: dict):
    repo = session().repo
    existed = AP.find_profile(repo) is not None
    before = len(P.stereotypes_of(repo))
    AP.ensure_profile(repo)
    out = _profile_view(repo)
    out["created"] = not existed
    out["added"] = len(P.stereotypes_of(repo)) - before
    return ok(out)


label("POST", r"^/api/avionics/profile$", "Add the Avionics profile")


# --- interface library ---------------------------------------------------------------------

@route("GET", r"^/api/avionics/interfaces/library$")
@_api
def api_interface_library(req: dict):
    return ok(interfaces_lib.library_status(session().repo))


@route("POST", r"^/api/avionics/interfaces/import$")
@_api
def api_interface_import(req: dict):
    b = _body(req)
    return ok(interfaces_lib.import_library(session().repo, names=_csv(b.get("names")),
                                            groups=_csv(b.get("groups")),
                                            on_conflict=b.get("on_conflict") or "skip"))


def _import_label(c) -> str:
    p = c.payload if isinstance(c.payload, dict) else {}
    n = len(p.get("created") or [])
    names = _csv(c.body.get("names"))
    what = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "") if names else None
    return f"Import {what or 'the avionics interface library'} ({n} item{'s' if n != 1 else ''})"


label("POST", r"^/api/avionics/interfaces/import$", _import_label)


# --- requirement library -------------------------------------------------------------------

@route("GET", r"^/api/avionics/requirements/library$")
@_api
def api_requirement_library(req: dict):
    repo = session().repo
    cat = requirements_lib.catalog()
    have = {s.name for s in rq.requirement_sets(repo)}
    for s in cat["sets"]:
        s["present"] = s["name"] in have
    return ok(cat)


@route("POST", r"^/api/avionics/requirements/import$")
@_api
def api_requirement_import(req: dict):
    b = _body(req)
    results = requirements_lib.import_requirement_library(session().repo, _csv(b.get("sets")) or None,
                                                          dal=b.get("dal") or None)
    return ok({"sets": [{"id": r["set"].element_id, "name": r["set"].name, "key": r["key"],
                         "prefix": r["set"].id_prefix, "requirements": r["requirements"]} for r in results],
               "requirements": sum(r["requirements"] for r in results)})


label("POST", r"^/api/avionics/requirements/import$",
      lambda c: "Import requirement sets " + ", ".join(s["name"] for s in (c.payload or {}).get("sets", [])))


# --- FHA -----------------------------------------------------------------------------------

def _fha_view() -> dict:
    repo = session().repo
    table = SF.fha_table(repo)
    rows = [SF.describe_row(repo, r) for r in SF.fha_rows(repo)]
    by_class: dict[str, int] = {}
    for r in rows:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
    return {"table": {"id": table.element_id, "name": table.name} if table else None, "rows": rows,
            "classifications": list(SF.CLASSIFICATIONS), "dal_by_classification": SF.DAL_BY_CLASSIFICATION,
            "probability": SF.PROBABILITY_TARGETS, "phases": list(SF.FLIGHT_PHASES),
            "functions": SF.function_choices(repo), "counts": by_class}


@route("GET", r"^/api/avionics/fha$")
@_api
def api_fha(req: dict):
    return ok(_fha_view())


def _row_fields(b: dict) -> dict:
    out = {}
    for key, arg in (("failure_condition", "failure_condition"), ("function", "function"),
                     ("flight_phase", "flight_phase"), ("effect", "effect"),
                     ("classification", "classification"), ("fha_id", "fha_id"), ("notes", "notes")):
        if key in b:
            out[arg] = b[key]
    if "id" in b and "fha_id" not in out:
        out["fha_id"] = b["id"]
    return out


@route("POST", r"^/api/avionics/fha$")
@_api
def api_fha_add(req: dict):
    repo = session().repo
    row = SF.add_fha_row(repo, **{"failure_condition": "", **_row_fields(_body(req))})
    return ok(SF.describe_row(repo, row))


@route("PATCH", r"^/api/avionics/fha/(?P<rid>[^/]+)$")
@_api
def api_fha_update(req: dict, rid: str):
    repo = session().repo
    row = SF.update_fha_row(repo, rid, **_row_fields(_body(req)))
    return ok(SF.describe_row(repo, row))


@route("DELETE", r"^/api/avionics/fha/(?P<rid>[^/]+)$")
@_api
def api_fha_delete(req: dict, rid: str):
    ident = SF.delete_fha_row(session().repo, rid)
    return ok({"deleted": ident})


def _row_label(c) -> str:
    rid = c.args["rid"]
    row = c.name(rid)
    keys = [k for k in c.body if k not in ("id",)]
    if keys == ["classification"]:
        return f"Set classification of {row} to {c.body['classification']}"
    if keys == ["function"]:
        fn = c.body["function"]
        return f"Set function of {row} to {c.name(fn)}" if fn else f"Clear the function of {row}"
    if keys == ["failure_condition"]:
        return f"Edit the failure condition of {row}"
    return f"Edit FHA row {row} " + ", ".join(k.replace("_", " ") for k in keys)


label("POST", r"^/api/avionics/fha$", lambda c: f"Add FHA row {(c.payload or {}).get('fha_id', '')}".strip())
label("PATCH", r"^/api/avionics/fha/(?P<rid>[^/]+)$", _row_label)
label("DELETE", r"^/api/avionics/fha/(?P<rid>[^/]+)$",
      lambda c: f"Delete FHA row {(c.payload or {}).get('deleted') or c.old_name(c.args['rid']) or ''}".strip())


# --- safety check --------------------------------------------------------------------------

@route("GET", r"^/api/avionics/safety$")
@_api
def api_safety(req: dict):
    q = _query(req)
    out = SF.safety_check(session().repo, severities=_csv(q.get("severity")) or None,
                          rules=_csv(q.get("rule")) or None)
    ref = q.get("element")
    if ref:
        e = session().find(ref)
        if e is None:
            return err(f"element {ref!r} not found", 404)
        out["issues"] = [i for i in out["issues"] if any(x["id"] == e.element_id for x in i["elements"])]
    return ok(out)


# --- element JSON, generic PATCH, creatable kinds ------------------------------------------

def _summary_hook(e, d: dict) -> None:
    kind = e.kind
    if kind == "FhaEntry":
        d["fha"] = {"classification": e.classification, "dal": e.dal, "failure_condition": e.failure_condition,
                    "flight_phase": e.flight_phase, "effect": e.effect,
                    "function": {"id": e.fha_function.element_id, "name": e.fha_function.name}
                    if e.fha_function is not None else None}
        d["badges"].append(e.classification)
        if e.dal:
            d["badges"].append(f"DAL {e.dal}")
        d["style"].setdefault("fill", {"Catastrophic": "#fecaca", "Hazardous": "#fed7aa", "Major": "#fde68a",
                                       "Minor": "#fef9c3", "No Safety Effect": "#dcfce7"}.get(e.classification, "#f1f5f9"))
        return
    if kind in ("PartUsage", "PartDefinition", "RequirementDefinition", "RequirementUsage"):
        dal = AP.effective_dal(e)
        if dal:
            d["badges"].append(f"DAL {dal}")
            d["avionics_dal"] = dal


def _prop_hook(e, key: str, value: Any) -> bool:
    """Generic PATCH /api/element on an FHA row goes through the FHA checks."""
    if not isinstance(e, SF.FhaEntry):
        return False
    repo = session().repo
    if key in ("classification", "failure_condition", "flight_phase", "effect"):
        SF.update_fha_row(repo, e, **{key: value})
        return True
    if key in ("fha_function", "function"):
        SF.update_fha_row(repo, e, function=value)
        return True
    return False


register_summary_hook(_summary_hook)
register_prop_hook(_prop_hook)
register_kind("FhaTable", SF.FhaTable)

# Model Check lists the rules with their titles.
try:
    from engine.interop import checks as _checks
    for _rid, _meta in SF.RULES.items():
        _checks.RULES.setdefault(_rid, {k: _meta[k] for k in ("title", "severity", "description")})
except ImportError:                                           # pragma: no cover
    pass
