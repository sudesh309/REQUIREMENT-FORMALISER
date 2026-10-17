"""Interface editor API (System Composer interfaces and interface dictionary).

Endpoints
---------
GET    /api/interfaces                                 dictionary listing + metadata
POST   /api/interfaces                                 create {kind, name?, template?, elements?, ...fields}
GET    /api/interfaces/item/<ref>                      item detail (elements, ports using it)
PATCH  /api/interfaces/item/<ref>                      edit {name?, color?, description?, ...}
DELETE /api/interfaces/item/<ref>                      delete an item
POST   /api/interfaces/item/<ref>/elements             add element {name?, index?, ...fields}
PATCH  /api/interfaces/item/<ref>/elements/<el>        edit element fields (name renames)
DELETE /api/interfaces/item/<ref>/elements/<el>        delete element
POST   /api/interfaces/item/<ref>/elements/<el>/move   {delta} or {index}
GET    /api/interfaces/port/<ref>                      a port's interface, element paths, connectors
POST   /api/interfaces/assign                          {port, interface: ref | "owned" | null}
POST   /api/interfaces/make-shared                     {port, name?, on_conflict?}
POST   /api/interfaces/make-owned                      {port}
POST   /api/interfaces/move-owned                      {on_conflict?}
GET    /api/interfaces/compatibility?source=&target=&source_element=&target_element=  (or ?connector=)
GET    /api/interfaces/candidates/<port>               ports the port can be wired to, with compatibility
POST   /api/interfaces/connect                         {source, target, source_element?, target_element?, name?, parent?}
POST   /api/interfaces/connector-elements              {connector, source_element?, target_element?}
GET    /api/interfaces/dictionary/export               {filename, text, document}
POST   /api/interfaces/dictionary/import               {text | document, dry_run?, default?, resolution?}
POST   /api/interfaces/adapter                         {parent, name?}
GET    /api/interfaces/adapter/<ref>                   mappings + input/output element choices
PATCH  /api/interfaces/adapter/<ref>                   {mappings: [{target, source, note}]}

Errors answer ``{"error": message}`` with 400 (invalid), 404 (not found) or
409 (name collision; choose keep / replace / rename).
"""
from __future__ import annotations

import functools
import json
import urllib.parse
from typing import Any, Callable

from engine import interfaces as I
from engine.interfaces import InterfaceError
from kerml.elements import Element
from sysmlv2 import ConnectionUsage, PortUsage
from webapp.core import (
    err, ok, register_kind, register_prop_hook, register_summary_hook, route, session,
)


# --- registration ----------------------------------------------------------

for _name, _cls in I.ALL_CLASSES.items():
    register_kind(_name, _cls)
register_summary_hook(I.summary_fields)
register_prop_hook(lambda e, key, value: I.handle_property(session().repo, e, key, value, session().find))


# --- helpers ---------------------------------------------------------------

def _guard(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(req: dict, **kw):
        try:
            return fn(req, **{k: urllib.parse.unquote(v) for k, v in kw.items()})
        except InterfaceError as ex:
            return err(str(ex), ex.status)
        except (ValueError, TypeError) as ex:
            return err(str(ex))
    return wrapper


def _body(req: dict) -> dict:
    body = req.get("body") or {}
    if not isinstance(body, dict):
        raise InterfaceError("request body must be a JSON object")
    return body


def _repo():
    return session().repo


def _find(ref: Any, what: str = "Element") -> Element:
    e = session().find(ref) if isinstance(ref, str) and ref else None
    if e is None and isinstance(ref, str) and ref:
        e = I.find_item(_repo(), ref, session().find)
    if e is None:
        raise InterfaceError(f"{what} {ref!r} not found", 404)
    return e


def _item(ref: str) -> Element:
    e = _find(ref, "Interface")
    if I.item_kind(e) is None:
        raise InterfaceError(f"{e.qualified_name!r} is not an interface or dictionary item")
    return e


def _element(item: Element, ref: str) -> Element:
    el = next((c for c in I.elements_of(item) if c.name == ref or c.element_id == ref), None)
    if el is None:
        raise InterfaceError(f"{item.name!r} has no element {ref!r}", 404)
    return el


def _port(ref: Any, what: str = "Port") -> PortUsage:
    p = _find(ref, what)
    if not isinstance(p, PortUsage):
        raise InterfaceError(f"{p.qualified_name!r} is not a port")
    return p


def _detail(e: Element) -> dict:
    return I.describe_item(e, _repo(), detail=True)


# --- dictionary listing / items -------------------------------------------

@route("GET", r"^/api/interfaces$")
@_guard
def api_list(_req):
    return ok({**I.list_dictionary(_repo()), "meta": I.metadata()})


@route("POST", r"^/api/interfaces$")
@_guard
def api_create(req):
    body = dict(_body(req))
    repo = _repo()
    if body.get("template"):
        item = I.create_from_template(repo, body["template"], body.get("name") or None)
    else:
        kind = body.pop("kind", "DataInterface")
        name = body.pop("name", None) or None
        elements = body.pop("elements", None)
        literals = body.pop("literals", None)
        for key in ("elements", "literals"):
            value = elements if key == "elements" else literals
            if value is not None and not isinstance(value, list):
                raise InterfaceError(f"{key} must be a list")
        item = I.create_item(repo, kind, name, resolve=session().find,
                             elements=elements, literals=literals, **body)
    return ok(_detail(item))


@route("GET", r"^/api/interfaces/item/(?P<ref>[^/]+)$")
@_guard
def api_get_item(_req, ref):
    return ok(_detail(_item(ref)))


@route("PATCH", r"^/api/interfaces/item/(?P<ref>[^/]+)$")
@_guard
def api_patch_item(req, ref):
    item = _item(ref)
    warnings = I.set_fields(_repo(), item, _body(req), session().find)
    return ok({**_detail(item), "warnings": warnings})


@route("DELETE", r"^/api/interfaces/item/(?P<ref>[^/]+)$")
@_guard
def api_delete_item(_req, ref):
    item = _item(ref)
    ports = [p.qualified_name for p in I.ports_using(_repo(), item)]
    _repo().remove(item)
    return ok({"deleted": ref, "unassigned_ports": ports})


# --- elements ------------------------------------------------------------

@route("POST", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements$")
@_guard
def api_add_element(req, ref):
    item = _item(ref)
    body = dict(_body(req))
    name = body.pop("name", None) or None
    index = body.pop("index", None)
    el = I.add_element(_repo(), item, name, index=index, resolve=session().find, **body)
    return ok({"element": I.describe_element(el), "interface": _detail(item)})


@route("PATCH", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)$")
@_guard
def api_patch_element(req, ref, el):
    item = _item(ref)
    element = _element(item, el)
    warnings = I.set_fields(_repo(), element, _body(req), session().find)
    return ok({"element": I.describe_element(element), "warnings": warnings,
               "interface": _detail(item)})


@route("DELETE", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)$")
@_guard
def api_delete_element(_req, ref, el):
    item = _item(ref)
    I.remove_element(_repo(), _element(item, el))
    return ok({"interface": _detail(item)})


@route("POST", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)/move$")
@_guard
def api_move_element(req, ref, el):
    item = _item(ref)
    body = _body(req)
    if "delta" not in body and "index" not in body:
        raise InterfaceError("give 'delta' (e.g. -1 / 1) or 'index'")
    try:
        delta = int(body["delta"]) if "delta" in body else None
        index = int(body["index"]) if "index" in body else None
    except (TypeError, ValueError):
        raise InterfaceError("'delta' and 'index' must be integers") from None
    new_index = I.move_element(_element(item, el), delta, index=index)
    return ok({"index": new_index, "interface": _detail(item)})


# --- ports ---------------------------------------------------------------

@route("GET", r"^/api/interfaces/port/(?P<ref>[^/]+)$")
@_guard
def api_port(_req, ref):
    return ok(I.port_info(_repo(), _port(ref)))


@route("POST", r"^/api/interfaces/assign$")
@_guard
def api_assign(req):
    body = _body(req)
    port = _port(body.get("port"))
    if "interface" not in body:
        raise InterfaceError("give 'interface': a shared interface, \"owned\" or null")
    I.assign_interface(_repo(), port, body.get("interface"), resolve=session().find,
                       owned_kind=body.get("owned_kind") or "DataInterface")
    return ok(I.port_info(_repo(), port))


@route("POST", r"^/api/interfaces/make-shared$")
@_guard
def api_make_shared(req):
    body = _body(req)
    port = _port(body.get("port"))
    shared = I.make_shared(_repo(), port, body.get("name") or None, body.get("on_conflict") or "error")
    return ok({"interface": _detail(shared), "port": I.port_info(_repo(), port)})


@route("POST", r"^/api/interfaces/make-owned$")
@_guard
def api_make_owned(req):
    body = _body(req)
    port = _port(body.get("port"))
    I.make_owned(_repo(), port, kind=body.get("kind") or "DataInterface")
    return ok(I.port_info(_repo(), port))


@route("POST", r"^/api/interfaces/move-owned$")
@_guard
def api_move_owned(req):
    body = _body(req)
    return ok({"moved": I.move_owned_to_dictionary(_repo(), body.get("on_conflict") or "rename")})


# --- compatibility / connectors -------------------------------------------

@route("GET", r"^/api/interfaces/compatibility$")
@_guard
def api_compatibility(req):
    q = req.get("query") or {}
    if q.get("connector"):
        conn = _find(q["connector"], "Connector")
        if not isinstance(conn, ConnectionUsage) or len(conn.ends) < 2:
            raise InterfaceError(f"{conn.qualified_name!r} is not a connector with two ends")
        src, tgt = conn.ends[0], conn.ends[1]
        if not isinstance(src, PortUsage) or not isinstance(tgt, PortUsage):
            raise InterfaceError("connector ends are not ports")
        report = I.compatibility_report(src, tgt, getattr(conn, "source_element", None),
                                        getattr(conn, "target_element", None))
        report["connector"] = {"id": conn.element_id, "name": conn.name}
        return ok(report)
    if not q.get("source") or not q.get("target"):
        raise InterfaceError("give ?source=<port>&target=<port> or ?connector=<connector>")
    return ok(I.compatibility_report(_port(q["source"], "Source port"), _port(q["target"], "Target port"),
                                     q.get("source_element") or None, q.get("target_element") or None))


@route("GET", r"^/api/interfaces/candidates/(?P<ref>[^/]+)$")
@_guard
def api_candidates(_req, ref):
    port = _port(ref)
    out = []
    for other in I.connect_candidates(port):
        src, tgt = (other, port) if port.direction.value == "in" else (port, other)
        reasons = I.check_compatibility(src, tgt)
        out.append({"id": other.element_id, "label": I.port_label(other),
                    "qualified_name": other.qualified_name, "direction": other.direction.value,
                    "compatible": not reasons, "reasons": reasons,
                    "element_paths": I.element_paths(I.interface_of(other))})
    return ok({"port": {"id": port.element_id, "label": I.port_label(port),
                        "direction": port.direction.value,
                        "element_paths": I.element_paths(I.interface_of(port))},
               "candidates": out})


@route("POST", r"^/api/interfaces/connect$")
@_guard
def api_connect(req):
    body = _body(req)
    src = _port(body.get("source"), "Source port")
    tgt = _port(body.get("target"), "Target port")
    parent = _find(body["parent"], "Parent") if body.get("parent") else None
    conn = I.connect_ports(_repo(), src, tgt, name=body.get("name") or None, parent=parent,
                           source_element=body.get("source_element") or None,
                           target_element=body.get("target_element") or None)
    report = I.compatibility_report(src, tgt, conn.source_element, conn.target_element)
    return ok({"connector": {"id": conn.element_id, "name": conn.name,
                             "qualified_name": conn.qualified_name}, **report})


@route("POST", r"^/api/interfaces/connector-elements$")
@_guard
def api_connector_elements(req):
    body = _body(req)
    conn = _find(body.get("connector"), "Connector")
    kwargs = {k: body[k] for k in ("source_element", "target_element") if k in body}
    I.set_connector_elements(conn, **kwargs)
    src, tgt = conn.ends[0], conn.ends[1]
    return ok(I.compatibility_report(src, tgt, getattr(conn, "source_element", None),
                                     getattr(conn, "target_element", None)))


# --- dictionary exchange ---------------------------------------------------

@route("GET", r"^/api/interfaces/dictionary/export$")
@_guard
def api_export(_req):
    doc = I.export_dictionary(_repo())
    return ok({"filename": f"{doc['name']}.json", "document": doc,
               "text": json.dumps(doc, indent=2)})


@route("POST", r"^/api/interfaces/dictionary/import$")
@_guard
def api_import(req):
    body = _body(req)
    data = body.get("document", body.get("text"))
    if data is None:
        raise InterfaceError("give the dictionary file content as 'text' (or 'document')")
    resolution = body.get("resolution") or {}
    if not isinstance(resolution, dict):
        raise InterfaceError("resolution must map item names to keep / replace / rename")
    report = I.import_dictionary(_repo(), data, default=body.get("default") or "error",
                                 resolution=resolution, dry_run=bool(body.get("dry_run")))
    return ok(report)


# --- adapters ------------------------------------------------------------

def _adapter_info(a: I.Adapter) -> dict:
    inputs = I.adapter_input_interfaces(a)
    out_iface = I.adapter_output_interface(a)
    sources = []
    for pname, iface in inputs.items():
        paths = I.element_paths(iface)
        sources += paths if len(inputs) == 1 else [f"{pname}.{p}" for p in paths]
    return {"id": a.element_id, "name": a.name, "mappings": [dict(m) for m in a.mappings],
            "inputs": {k: (v.name if v is not None else None) for k, v in inputs.items()},
            "output": out_iface.name if out_iface is not None else None,
            "source_paths": sources,
            "target_paths": [e.name for e in I.elements_of(out_iface)]}


@route("POST", r"^/api/interfaces/adapter$")
@_guard
def api_create_adapter(req):
    body = _body(req)
    parent = _find(body.get("parent"), "Parent")
    a = I.create_adapter(_repo(), parent, body.get("name") or None)
    return ok(_adapter_info(a))


@route("GET", r"^/api/interfaces/adapter/(?P<ref>[^/]+)$")
@_guard
def api_get_adapter(_req, ref):
    a = _find(ref, "Adapter")
    if not isinstance(a, I.Adapter):
        raise InterfaceError(f"{a.qualified_name!r} is not an adapter")
    return ok(_adapter_info(a))


@route("PATCH", r"^/api/interfaces/adapter/(?P<ref>[^/]+)$")
@_guard
def api_patch_adapter(req, ref):
    a = _find(ref, "Adapter")
    I.set_adapter_mappings(a, _body(req).get("mappings"))
    return ok(_adapter_info(a))
