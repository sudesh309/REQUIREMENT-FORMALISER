"""HTTP API for System Composer-style architecture modeling (see engine/architecture.py).

All ids may also be qualified names. Errors answer ``{"error": message}`` with
400 (invalid), 404 (not found) or 409 (conflict, e.g. a duplicate name or an
input that already has a driver).

Model
    GET   /api/arch/model-type                 {type, allowed_port_kinds, types, port_kinds}
    POST  /api/arch/model-type                 {type, force?}
    GET   /api/arch/roots                      {roots: [...], definitions: [...]}
    POST  /api/arch/architecture               {name?, package?}            -> new root architecture
Canvas
    GET   /api/arch/view/<composition>?path=id,id,...                      -> view model
    GET   /api/arch/tree/<composition>                                     -> model browser tree
    GET   /api/arch/can-connect?composition&source_component&source_port&target_component&target_port
    GET   /api/arch/connect-targets?composition&source_component&source_port  -> {source, targets}
    GET   /api/arch/locate/<id>                                            -> {composition, select}
Editing
    POST  /api/arch/component                  {composition, name?, definition?, layout?}
    PATCH /api/arch/component/<id>             {name?, definition? (id | null)} -> + merged_ports
    POST  /api/arch/port                       {owner, name?, direction?, kind?, interface?, usage_only?, side?, offset?}
    PATCH /api/arch/port/<id>                  {name?, direction?, kind?, interface? (id | null), force?}
    POST  /api/arch/connector                  {composition, source: {component?, port}, target: {component?, port}, name?}
                                               (one end may be {component?, new_port: true | {name?, side?, offset?}})
    PATCH /api/arch/connector/<id>             {name?, points? ([[x, y], ...] | null)}
    POST  /api/arch/delete                     {ids}
    POST  /api/arch/duplicate                  {ids, target?, offset?: [dx, dy]}
    POST  /api/arch/group                      {composition, component_ids, name?}
    POST  /api/arch/expand                     {component}
    POST  /api/arch/save-as-reference          {component, name?, package?}
    POST  /api/arch/inline                     {component}
    POST  /api/arch/auto-layout                {composition, view?: {w, h} (canvas size in px)}
    POST  /api/arch/layout                     {items: [{id, x, y, w?, h?} | {id, side, offset} | {id, points}]}
"""
from __future__ import annotations

import functools
import re
import traceback
from typing import Any, Callable, Optional

from engine import architecture as A
from kerml.elements import Element
from sysmlv2.definitions import PORT_KINDS, ConnectionUsage, PartUsage, PortUsage
from webapp.core import (
    err, ok, register_mutation_hook, register_prop_hook, register_summary_hook, route, session,
    summarize,
)


# --- automatic growth never covers a neighbour ---------------------------------

_REPLACES_MODEL = re.compile(r"^/api/(undo|redo|new|load|save|export|validate|plugins)(/|$)")


def _settle_growth_hook(method: str, path: str, body: Any) -> Optional[Callable[[int], None]]:
    """Any edit (from any feature) that makes a block grow pushes the neighbours it would
    cover (``A.settle_growth``). This module is imported before ``undo`` (alphabetical
    route loading), so the pushes are part of the same undo step."""
    if _REPLACES_MODEL.match(path):
        return None
    repo = session().repo
    try:
        before = A.box_snapshot(repo)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None

    def finish(status: int) -> None:
        if 200 <= status < 300 and session().repo is repo:
            try:
                A.settle_growth(repo, before)
            except Exception:  # noqa: BLE001 - layout tidying must never fail an edit
                traceback.print_exc()
    return finish


register_mutation_hook(_settle_growth_hook)


# --- helpers ------------------------------------------------------------------

def _handles_errors(fn):
    @functools.wraps(fn)
    def wrapper(req, **kw):
        try:
            return fn(req, **kw)
        except A.ArchitectureError as ex:
            return err(str(ex), ex.status)
    return wrapper


def arch_route(method: str, pattern: str):
    def deco(fn):
        return route(method, pattern)(_handles_errors(fn))
    return deco


def _body(req: dict) -> dict:
    body = req.get("body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise A.ArchitectureError("request body must be a JSON object")
    return body


def _find(ref: Any, what: str, required: bool = True) -> Optional[Element]:
    if ref in (None, ""):
        if required:
            raise A.ArchitectureError(f"{what} is required")
        return None
    if not isinstance(ref, str):
        raise A.ArchitectureError(f"{what} must be an id or qualified name")
    e = session().find(ref)
    if e is None:
        raise A.ArchitectureError(f"{what} {ref!r} not found", 404)
    return e


def _repo():
    return session().repo


def _decorate(e: Element) -> dict:
    return summarize(e)


def _component_json(c: Element) -> dict:
    return A.component_view(c, c.owner, _decorate)


def _port_json(p: PortUsage, owner: Optional[Element] = None) -> dict:
    """A port as the canvas sees it on `owner` (default: the element that owns it)."""
    owner = owner or p.owner
    layouts = A.port_layouts(owner)
    return A.port_view(p, owner, layouts.get(id(p)) or {"side": A.default_side(p), "offset": 0.5},
                       _decorate)


def _endpoint(spec: Any, what: str) -> dict:
    """{component?, port} with ids/qualified names -> engine endpoint dict."""
    if not isinstance(spec, dict):
        raise A.ArchitectureError(f"{what} must be an object {{component?, port}}")
    comp = _find(spec.get("component"), f"{what} component", required=False)
    port_ref = spec.get("port")
    if not port_ref or not isinstance(port_ref, str):
        raise A.ArchitectureError(f"{what} port is required (an id, qualified name or port name)")
    repo = _repo()
    # An id or a qualified name; a bare name is looked up among the owner's ports.
    port = repo.by_id(port_ref) or (repo.resolve(port_ref) if "::" in port_ref else None)
    return {"component": comp, "port": port if isinstance(port, PortUsage) else port_ref}


# --- model --------------------------------------------------------------------

@arch_route("GET", r"^/api/arch/model-type$")
def api_model_type(_req):
    repo = _repo()
    return ok({"type": A.model_type(repo), "allowed_port_kinds": list(A.allowed_port_kinds(repo)),
               "types": list(A.MODEL_TYPES), "port_kinds": list(PORT_KINDS)})


@arch_route("POST", r"^/api/arch/model-type$")
def api_set_model_type(req):
    b = _body(req)
    A.set_model_type(_repo(), b.get("type"), force=bool(b.get("force")))
    return api_model_type(req)


@arch_route("GET", r"^/api/arch/roots$")
def api_roots(_req):
    repo = _repo()

    def item(d):
        return {"id": d.element_id, "name": d.name, "qualified_name": d.qualified_name,
                "component_count": len(A.components_of(d))}
    return ok({"roots": [item(d) for d in A.architecture_roots(repo)],
               "definitions": [item(d) for d in A.part_definitions(repo)],
               "model_type": A.model_type(repo)})


@arch_route("POST", r"^/api/arch/architecture$")
def api_new_architecture(req):
    b = _body(req)
    pkg = _find(b.get("package"), "package", required=False)
    arch = A.create_architecture(_repo(), b.get("name"), pkg)
    return ok(summarize(arch))


# --- canvas -------------------------------------------------------------------

@arch_route("GET", r"^/api/arch/view/(?P<cid>[^/]+)$")
def api_view(req, cid):
    comp = _find(cid, "composition")
    path = None
    raw = (req.get("query") or {}).get("path")
    if raw:
        path = [session().find(x) for x in raw.split(",") if x]
        if any(p is None for p in path):
            path = None
    return ok(A.view(_repo(), comp, path=path, decorate=_decorate))


@arch_route("GET", r"^/api/arch/tree/(?P<cid>[^/]+)$")
def api_tree(_req, cid):
    return ok(A.model_tree(_find(cid, "composition"), decorate=_decorate))


@arch_route("GET", r"^/api/arch/can-connect$")
def api_can_connect(req):
    q = req.get("query") or {}
    comp = _find(q.get("composition"), "composition")
    src = _endpoint({"component": q.get("source_component"), "port": q.get("source_port")}, "source")
    dst = _endpoint({"component": q.get("target_component"), "port": q.get("target_port")}, "target")
    for ep, what in ((src, "source"), (dst, "target")):
        if not isinstance(ep["port"], PortUsage):
            owner = ep["component"] or comp
            ep["port"] = A.resolve_port(owner, ep["port"])
    return ok(A.can_connect(comp, (src["component"], src["port"]), (dst["component"], dst["port"])))


@arch_route("GET", r"^/api/arch/connect-targets$")
def api_connect_targets(req):
    """Every port of the view with whether a connector from the source may end there."""
    q = req.get("query") or {}
    comp = _find(q.get("composition"), "composition")
    src = _endpoint({"component": q.get("source_component"), "port": q.get("source_port")}, "source")
    port = src["port"] if isinstance(src["port"], PortUsage) else A.resolve_port(
        src["component"] or comp, src["port"])
    return ok({"source": {"component_id": src["component"].element_id if src["component"] else None,
                          "port_id": port.element_id},
               "targets": A.connect_targets(comp, (src["component"], port))})


@arch_route("GET", r"^/api/arch/locate/(?P<eid>[^/]+)$")
def api_locate(_req, eid):
    """The composition whose canvas view shows an element, and what to select there."""
    hit = A.locate(_find(eid, "element"))
    if hit is None:
        return ok({"composition": None, "select": None})
    sel = hit["select"]
    return ok({"composition": hit["composition"].element_id,
               "select": sel.element_id if sel is not None else None})


# --- components -----------------------------------------------------------------

@arch_route("POST", r"^/api/arch/component$")
def api_add_component(req):
    b = _body(req)
    comp = _find(b.get("composition"), "composition")
    definition = _find(b.get("definition"), "definition", required=False)
    c = A.add_component(_repo(), comp, b.get("name"), definition, b.get("layout"))
    return ok(_component_json(c))


@arch_route("PATCH", r"^/api/arch/component/(?P<eid>[^/]+)$")
def api_update_component(req, eid):
    b = _body(req)
    c = A.require_component(_find(eid, "component"))
    merged: list[str] = []
    if "definition" in b:
        d = _find(b["definition"], "definition", required=False)
        merged = [p.name for p, _ in A.merged_ports(c, d)]
        A.set_definition(_repo(), c, d)
    if b.get("name") is not None:
        A.rename(_repo(), c, b["name"])
    return ok({**_component_json(c), "merged_ports": merged})


@arch_route("POST", r"^/api/arch/delete$")
def api_delete(req):
    ids = _body(req).get("ids")
    if not isinstance(ids, list) or not ids:
        raise A.ArchitectureError("ids must be a non-empty list")
    return ok({"deleted": A.delete_elements(_repo(), [_find(i, "element") for i in ids])})


@arch_route("POST", r"^/api/arch/duplicate$")
def api_duplicate(req):
    b = _body(req)
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids:
        raise A.ArchitectureError("ids must be a non-empty list")
    target = _find(b.get("target"), "target", required=False)
    off = b.get("offset")              # default: beside the originals, on no other block
    if off is not None and not (isinstance(off, list) and len(off) == 2):
        raise A.ArchitectureError("offset must be [dx, dy]")
    copies = A.duplicate(_repo(), [_find(i, "component") for i in ids], target,
                         None if off is None else (A.number(off[0], "dx"), A.number(off[1], "dy")))
    return ok({"components": [_component_json(c) for c in copies]})


@arch_route("POST", r"^/api/arch/group$")
def api_group(req):
    b = _body(req)
    comp = _find(b.get("composition"), "composition")
    ids = b.get("component_ids")
    if not isinstance(ids, list):
        raise A.ArchitectureError("component_ids must be a list")
    g = A.group(_repo(), comp, [_find(i, "component") for i in ids], b.get("name"))
    return ok(_component_json(g))


@arch_route("POST", r"^/api/arch/expand$")
def api_expand(req):
    moved = A.expand(_repo(), _find(_body(req).get("component"), "component"))
    return ok({"components": [c.element_id for c in moved]})


@arch_route("POST", r"^/api/arch/save-as-reference$")
def api_save_as_reference(req):
    b = _body(req)
    c = _find(b.get("component"), "component")
    pkg = _find(b.get("package"), "package", required=False)
    d = A.save_as_reference(_repo(), c, b.get("name"), pkg)
    return ok({"definition": summarize(d), "component": _component_json(c)})


@arch_route("POST", r"^/api/arch/inline$")
def api_inline(req):
    c = A.inline_component(_repo(), _find(_body(req).get("component"), "component"))
    return ok(_component_json(c))


# --- ports ----------------------------------------------------------------------

@arch_route("POST", r"^/api/arch/port$")
def api_add_port(req):
    b = _body(req)
    owner = _find(b.get("owner"), "owner")
    iface = _find(b.get("interface"), "interface", required=False)
    layout = {"side": b["side"], "offset": b.get("offset", 0.5)} if b.get("side") else None
    p = A.add_port(_repo(), owner, b.get("name"), b.get("direction") or "in", b.get("kind") or "data",
                   iface, usage_only=bool(b.get("usage_only")), layout=layout)
    return ok(_port_json(p, owner))


@arch_route("PATCH", r"^/api/arch/port/(?P<eid>[^/]+)$")
def api_update_port(req, eid):
    b = _body(req)
    p = _find(eid, "port")
    kw = {k: b[k] for k in ("name", "direction", "kind") if b.get(k) is not None}
    if "interface" in b:
        kw["interface"] = _find(b["interface"], "interface", required=False)
    A.update_port(_repo(), p, force=bool(b.get("force")), **kw)
    return ok(_port_json(p))


# --- connectors -----------------------------------------------------------------

@arch_route("POST", r"^/api/arch/connector$")
def api_connect(req):
    b = _body(req)
    comp = _find(b.get("composition"), "composition")
    ends = {"source": b.get("source"), "target": b.get("target")}
    for what, spec in ends.items():
        if not isinstance(spec, dict):
            raise A.ArchitectureError(f"{what} must be an object {{component?, port}}")
    fresh = [w for w, spec in ends.items() if spec.get("new_port")]
    if len(fresh) > 1:
        raise A.ArchitectureError("only one end can be a new port")
    if fresh:
        return ok(_connect_new_port(b, comp, fresh[0], "target" if fresh[0] == "source" else "source"))
    conn = A.connect(_repo(), comp, _endpoint(ends["source"], "source"),
                     _endpoint(ends["target"], "target"), b.get("name"))
    return ok(A.connector_view(conn, comp, _decorate))


def _connect_new_port(b: dict, comp: Element, fresh: str, other: str) -> dict:
    """`{component?, new_port: true | {name?, side?, offset?}}` at one end: create that port."""
    spec = b[fresh]
    opts = spec["new_port"] if isinstance(spec["new_port"], dict) else {}
    component = _find(spec.get("component"), f"{fresh} component", required=False)
    layout = {"side": opts["side"], "offset": opts.get("offset", 0.5)} if opts.get("side") else None
    port_name = opts.get("name")
    if port_name is not None and not isinstance(port_name, str):
        raise A.ArchitectureError("new_port name must be a string")
    port, conn = A.connect_new_port(_repo(), comp, _endpoint(b[other], other), component,
                                    name=b.get("name"), port_name=port_name or None, layout=layout)
    out = A.connector_view(conn, comp, _decorate)
    out["created_port"] = _port_json(port, component or comp)
    return out


@arch_route("PATCH", r"^/api/arch/connector/(?P<eid>[^/]+)$")
def api_update_connector(req, eid):
    b = _body(req)
    conn = _find(eid, "connector")
    if not isinstance(conn, ConnectionUsage):
        raise A.ArchitectureError(f"{conn.qualified_name} is not a connector")
    if "points" in b:
        A.set_connector_points(conn, b["points"])
    if b.get("name") is not None:
        A.rename(_repo(), conn, b["name"])
    return ok(A.connector_view(conn, conn.owner, _decorate))


# --- layout -----------------------------------------------------------------------

@arch_route("POST", r"^/api/arch/auto-layout$")
def api_auto_layout(req):
    b = _body(req)
    comp = _find(b.get("composition"), "composition")
    return ok({"positions": A.auto_layout(_repo(), comp, b.get("view"))})


@arch_route("POST", r"^/api/arch/layout$")
def api_layout(req):
    return ok({"updated": A.apply_layout(_repo(), _body(req).get("items"))})


# --- element JSON: badges, port kind, connector contexts; PATCH validation -------

def _summary(e: Element, d: dict) -> None:
    d["badges"].extend(A.component_badges(e) + A.port_badges(e))
    if isinstance(e, PortUsage):
        d["port_kind"] = e.port_kind
    elif isinstance(e, ConnectionUsage):
        d["end_contexts"] = [c.element_id if c is not None else None
                             for c in (getattr(e, "end_contexts", ()) or ())]
    elif A.is_component(e) and A.definition_of(e) is not None:
        d["style"].setdefault("icon", "reference")


def _prop(e: Element, key: str, value: Any) -> bool:
    if key == "port_kind" and isinstance(e, PortUsage):
        A.check_port_kind(_repo(), value)
        e.port_kind = value
        if value != "data":
            e.direction = A.normalize_direction(None, value)
        return True
    if key == "name" and isinstance(value, str) and value and value != e.name and (
            A.is_component(e) or isinstance(e, PortUsage)):
        if value in A.sibling_names(e):
            raise ValueError(f"{e.owner.name} already has a member named {value!r}")
    return False


register_summary_hook(_summary)
register_prop_hook(_prop)
