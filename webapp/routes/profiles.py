"""HTTP API for profiles, stereotypes and stereotype property values.

All model logic lives in :mod:`engine.profiles`; handlers only translate
requests. Errors carry the engine's status (400 invalid, 404 not found,
409 conflict) and a readable message.

Profiles and stereotypes
    GET    /api/profiles/meta                       types, categories, icons, line styles, units
    GET    /api/profiles                            {profiles: [...], ungrouped: [...], imports: [...]}
    POST   /api/profiles                            {name, description?, version?}
    POST   /api/profiles/import                     {text, replace?, file_name?}
    GET    /api/profiles/<ref>                      profile with stereotypes
    PATCH  /api/profiles/<ref>                      {name?, description?, version?, root_stereotype?}
    DELETE /api/profiles/<ref>                      strips every application of its stereotypes
    GET    /api/profiles/<ref>/export               {file_name, text}
    POST   /api/profiles/<ref>/stereotypes          {name, description?, applies_to?, base?, abstract?, style?, defaults?}
    GET    /api/stereotypes/<ref>                   (ref: id, Profile.Stereotype or qualified name)
    PATCH  /api/stereotypes/<ref>                   {name?, description?, applies_to?, base?, abstract?, style?, defaults?, force?}
    DELETE /api/stereotypes/<ref>
    POST   /api/stereotypes/<ref>/properties        {name?, type?, unit?, default?, min?, max?, literals?, description?, index?}
    PATCH  /api/stereotypes/<ref>/properties/<p>    same keys (p: id or property name)
    DELETE /api/stereotypes/<ref>/properties/<p>
    POST   /api/stereotypes/<ref>/batch             {scope: selection|composition|model, ids?, root?, category?, values?}

Applied stereotypes
    GET    /api/elements/<id>/stereotypes           {element, applied: [...], applicable: [...]}
    POST   /api/elements/<id>/stereotypes           {stereotype, values?}
    PATCH  /api/elements/<id>/stereotypes           {values: {"Profile.Stereotype.prop": value, ...}}
                                                    or {property: "Profile.Stereotype.prop", value}
    DELETE /api/elements/<id>/stereotypes           remove all
    DELETE /api/elements/<id>/stereotypes/<ref>     remove one

Units
    GET    /api/units                               table of units
    GET    /api/units/convert?value=&from=&to=

Also: ``PATCH /api/element/<id>`` accepts ``{"props": {"Profile.Stereotype.prop": value}}``,
and edits of a Stereotype / StereotypeTag / Profile through that generic route
go through the same checks and propagation.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from engine import profiles as P
from engine import units
from kerml.elements import Element
from kerml.stereotypes import (
    Profile, Stereotype, StereotypeError, StereotypeTag, categories_of, stereotypes_on,
)
from webapp.core import err, ok, register_kind, register_prop_hook, register_summary_hook, \
    route, session, summarize


def _repo():
    return session().repo


def _ref(value: str) -> str:
    return urllib.parse.unquote(value or "")


def _body(req: dict) -> dict:
    body = req.get("body")
    return body if isinstance(body, dict) else {}


def _guard(fn: Callable) -> Callable:
    """Turn engine errors into HTTP errors with their status code."""
    def wrapper(req: dict, **kw: Any):
        try:
            return fn(req, **{k: _ref(v) for k, v in kw.items()})
        except P.ProfileError as ex:
            return err(str(ex), ex.status)
        except StereotypeError as ex:
            return err(str(ex), getattr(ex, "status", 400))
        except units.UnitError as ex:
            return err(str(ex), 400)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _pick(body: dict, *keys: str, rename: dict | None = None) -> dict:
    rename = rename or {}
    return {rename.get(k, k): body[k] for k in keys if k in body}


# --- profiles ----------------------------------------------------------------

@route("GET", r"^/api/profiles/meta$")
@_guard
def api_meta(_req: dict):
    return ok(P.meta())


@route("GET", r"^/api/profiles$")
@_guard
def api_list_profiles(_req: dict):
    repo = _repo()
    return ok({
        "profiles": [P.describe_profile(repo, p) for p in P.profiles_of(repo)],
        "ungrouped": [P.describe_stereotype(repo, s) for s in P.stereotypes_of(repo) if s.profile is None],
        "imports": P.import_log(repo),
    })


@route("POST", r"^/api/profiles$")
@_guard
def api_create_profile(req: dict):
    b = _body(req)
    p = P.create_profile(_repo(), b.get("name"), description=b.get("description") or "",
                         version=b.get("version") if b.get("version") is not None else "1.0",
                         parent=b.get("parent"))
    return ok(P.describe_profile(_repo(), p))


@route("POST", r"^/api/profiles/import$")
@_guard
def api_import_profile(req: dict):
    b = _body(req)
    text = b.get("text")
    if not isinstance(text, str) or not text.strip():
        return err("send the profile file content as 'text'")
    out = P.import_profile(_repo(), text, replace=bool(b.get("replace")),
                           file_name=str(b.get("file_name") or ""))
    return ok({"profile": P.describe_profile(_repo(), out["profile"]),
               "created": out["created"], "report": out["report"]})


@route("GET", r"^/api/profiles/(?P<ref>[^/]+)$")
@_guard
def api_get_profile(_req: dict, ref: str):
    return ok(P.describe_profile(_repo(), P.find_profile(_repo(), ref)))


@route("PATCH", r"^/api/profiles/(?P<ref>[^/]+)$")
@_guard
def api_update_profile(req: dict, ref: str):
    repo = _repo()
    out = P.update_profile(repo, P.find_profile(repo, ref),
                           **_pick(_body(req), "name", "description", "version", "root_stereotype"))
    return ok({**P.describe_profile(repo, out["profile"]), "root_applied": out["root_applied"]})


@route("DELETE", r"^/api/profiles/(?P<ref>[^/]+)$")
@_guard
def api_delete_profile(_req: dict, ref: str):
    repo = _repo()
    return ok(P.delete_profile(repo, P.find_profile(repo, ref)))


@route("GET", r"^/api/profiles/(?P<ref>[^/]+)/export$")
@_guard
def api_export_profile(_req: dict, ref: str):
    p = P.find_profile(_repo(), ref)
    return ok({"file_name": P.profile_file_name(p), "text": P.export_profile_json(p)})


_ST_KEYS = ("name", "description", "applies_to", "base", "abstract", "style", "defaults")


@route("POST", r"^/api/profiles/(?P<ref>[^/]+)/stereotypes$")
@_guard
def api_add_stereotype(req: dict, ref: str):
    repo = _repo()
    b = _body(req)
    st = P.add_stereotype(repo, P.find_profile(repo, ref), b.get("name"),
                          **_pick(b, *_ST_KEYS[1:]))
    return ok(P.describe_stereotype(repo, st))


# --- stereotypes -------------------------------------------------------------

@route("GET", r"^/api/stereotypes/(?P<ref>[^/]+)$")
@_guard
def api_get_stereotype(_req: dict, ref: str):
    repo = _repo()
    return ok(P.describe_stereotype(repo, P.find_stereotype(repo, ref)))


@route("PATCH", r"^/api/stereotypes/(?P<ref>[^/]+)$")
@_guard
def api_update_stereotype(req: dict, ref: str):
    repo = _repo()
    b = _body(req)
    out = P.update_stereotype(repo, P.find_stereotype(repo, ref), **_pick(b, *_ST_KEYS),
                              force=bool(b.get("force")))
    return ok({**P.describe_stereotype(repo, out["stereotype"]), "stripped": out["stripped"]})


@route("DELETE", r"^/api/stereotypes/(?P<ref>[^/]+)$")
@_guard
def api_delete_stereotype(_req: dict, ref: str):
    repo = _repo()
    return ok(P.delete_stereotype(repo, P.find_stereotype(repo, ref)))


_PROP_KEYS = ("name", "type", "unit", "default", "min", "max", "literals", "description", "index")
_PROP_RENAME = {"type": "prop_type", "min": "minimum", "max": "maximum"}


@route("POST", r"^/api/stereotypes/(?P<ref>[^/]+)/properties$")
@_guard
def api_add_property(req: dict, ref: str):
    repo = _repo()
    st = P.find_stereotype(repo, ref)
    kw = _pick(_body(req), *_PROP_KEYS, rename=_PROP_RENAME)
    tag = P.add_property(repo, st, kw.pop("name", None), kw.pop("prop_type", None) or "double", **kw)
    return ok({**tag.describe(), "stereotype": P.describe_stereotype(repo, st)})


@route("PATCH", r"^/api/stereotypes/(?P<ref>[^/]+)/properties/(?P<prop>[^/]+)$")
@_guard
def api_update_property(req: dict, ref: str, prop: str):
    repo = _repo()
    st = P.find_stereotype(repo, ref)
    tag = P.find_property(repo, prop, st)
    out = P.update_property(repo, tag, **_pick(_body(req), *_PROP_KEYS, rename=_PROP_RENAME))
    return ok({**tag.describe(), "converted": out["converted"], "reset": out["reset"],
               "stereotype": P.describe_stereotype(repo, st)})


@route("DELETE", r"^/api/stereotypes/(?P<ref>[^/]+)/properties/(?P<prop>[^/]+)$")
@_guard
def api_delete_property(_req: dict, ref: str, prop: str):
    repo = _repo()
    st = P.find_stereotype(repo, ref)
    out = P.delete_property(repo, P.find_property(repo, prop, st))
    return ok({**out, "stereotype": P.describe_stereotype(repo, st)})


@route("POST", r"^/api/stereotypes/(?P<ref>[^/]+)/batch$")
@_guard
def api_batch_apply(req: dict, ref: str):
    repo = _repo()
    b = _body(req)
    return ok(P.batch_apply(repo, P.find_stereotype(repo, ref), scope=b.get("scope") or "model",
                            root=b.get("root"), elements=b.get("ids"), category=b.get("category"),
                            values=b.get("values")))


# --- applied stereotypes -------------------------------------------------------

def _element_view(e: Element) -> dict:
    repo = _repo()
    return {
        "element": {"id": e.element_id, "name": e.name, "kind": e.kind,
                    "qualified_name": e.qualified_name, "categories": categories_of(e)},
        "applied": P.element_stereotypes(e),
        "applicable": [{"id": s.element_id, "qualified_name": s.full_name, "name": s.name,
                        "profile": s.profile.name if s.profile else None,
                        "applies_to": s.effective_category(), "description": s.description}
                       for s in P.applicable_stereotypes(repo, e)],
    }


@route("GET", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$")
@_guard
def api_element_stereotypes(_req: dict, eid: str):
    return ok(_element_view(P.find_element(_repo(), eid)))


@route("POST", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$")
@_guard
def api_apply(req: dict, eid: str):
    repo = _repo()
    b = _body(req)
    e = P.find_element(repo, eid)
    st = P.find_stereotype(repo, b.get("stereotype"))
    P.apply_stereotype(repo, e, st, b.get("values") or {})
    return ok(_element_view(e))


@route("PATCH", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$")
@_guard
def api_set_values(req: dict, eid: str):
    repo = _repo()
    b = _body(req)
    e = P.find_element(repo, eid)
    values = dict(b.get("values") or {})
    if "property" in b:
        values[b["property"]] = b.get("value")
    if not values:
        return err("send {values: {'Profile.Stereotype.property': value}} or {property, value}")
    stored = P.set_property_values(repo, e, values)
    return ok({**_element_view(e), "stored": stored})


@route("DELETE", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$")
@_guard
def api_remove_all(_req: dict, eid: str):
    repo = _repo()
    e = P.find_element(repo, eid)
    n = P.remove_all_stereotypes(repo, e)
    return ok({**_element_view(e), "removed": n})


@route("DELETE", r"^/api/elements/(?P<eid>[^/]+)/stereotypes/(?P<ref>[^/]+)$")
@_guard
def api_remove_one(_req: dict, eid: str, ref: str):
    repo = _repo()
    e = P.find_element(repo, eid)
    P.remove_stereotype(repo, e, P.find_stereotype(repo, ref))
    return ok(_element_view(e))


# --- units -------------------------------------------------------------------

@route("GET", r"^/api/units$")
@_guard
def api_units(_req: dict):
    return ok({"units": units.list_units()})


@route("GET", r"^/api/units/convert$")
@_guard
def api_convert(req: dict):
    q = req.get("query") or {}
    value = q.get("value", "")
    num, unit = units.parse_quantity(value)
    src = q.get("from") or unit
    if not src:
        return err("give the source unit as 'from' or inside 'value' (e.g. 3 lb)")
    return ok({"value": units.convert(num, src, q.get("to") or src), "unit": units.normalize_unit(q.get("to") or src)})


# --- element JSON + generic PATCH -----------------------------------------------

def _summary(e: Element, d: dict) -> None:
    badges, style = P.display_fields(e)
    d.setdefault("badges", []).extend(badges)
    d.setdefault("style", {}).update(style)
    for entry, app in zip(d.get("stereotypes") or [], stereotypes_on(e)):
        st = app.stereotype
        entry.update(id=st.element_id, qualified_name=st.full_name,
                     profile=st.profile.name if st.profile else None,
                     style=st.effective_style())
    if isinstance(e, StereotypeTag):
        d["stereotype_property"] = e.describe()
    elif isinstance(e, Stereotype):
        d["stereotype_definition"] = {"qualified_name": e.full_name,
                                      "applies_to": e.effective_category(),
                                      "abstract": e.is_abstract}
    elif isinstance(e, Profile):
        d["profile"] = {"version": e.version, "description": e.description,
                        "stereotypes": [s.full_name for s in e.stereotypes]}


_TAG_PROPS = {"name": "name", "default_value": "default", "default": "default", "unit": "unit",
              "minimum": "minimum", "maximum": "maximum", "min": "minimum", "max": "maximum",
              "prop_type": "prop_type", "type": "prop_type", "literals": "literals",
              "description": "description"}
_ST_PROPS = {"name": "name", "description": "description", "category": "applies_to",
             "applies_to": "applies_to", "is_abstract": "abstract", "style": "style"}
_PROFILE_PROPS = {"name": "name", "description": "description", "version": "version"}


def _prop_hook(e: Element, key: str, value: Any) -> bool:
    """Route generic PATCH edits of profile elements and dotted value keys through the engine."""
    repo = _repo()
    if isinstance(e, StereotypeTag) and key in _TAG_PROPS and e.stereotype is not None:
        P.update_property(repo, e, **{_TAG_PROPS[key]: value})
        return True
    if isinstance(e, Stereotype) and key in _ST_PROPS:
        P.update_stereotype(repo, e, **{_ST_PROPS[key]: value})
        return True
    if isinstance(e, Profile) and key in _PROFILE_PROPS:
        P.update_profile(repo, e, **{_PROFILE_PROPS[key]: value})
        return True
    if isinstance(key, str) and "." in key and stereotypes_on(e):
        P.set_property_value(repo, e, key, value)
        return True
    return False


register_summary_hook(_summary)
register_prop_hook(_prop_hook)
register_kind("Profile", Profile)
