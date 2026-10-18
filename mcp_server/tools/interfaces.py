"""MCP tools for System Composer interfaces and the interface dictionary.

Tools: sysml_list_interfaces, sysml_create_interface, sysml_add_interface_element,
sysml_set_interface_element, sysml_remove_interface_element, sysml_create_value_type,
sysml_assign_interface, sysml_make_interface_shared, sysml_check_compatibility,
sysml_connect_ports, sysml_set_connector_elements, sysml_create_adapter,
sysml_set_adapter_mappings, sysml_export_dictionary, sysml_import_dictionary.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from engine import interfaces as I
from engine.interfaces import InterfaceError
from mcp_server.core import SESSION, _err, _ok, register_kind, register_summary_hook
from sysmlv2 import PortUsage

for _name, _cls in I.ALL_CLASSES.items():
    register_kind(_name, _cls)
register_summary_hook(I.summary_fields)


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (InterfaceError, ValueError) as ex:
            return _err(str(ex))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _find(ref: str, what: str = "Element"):
    e = SESSION.find(ref) if ref else None
    if e is None and ref:
        e = I.find_item(SESSION.repo, ref, SESSION.find)
    if e is None:
        raise InterfaceError(f"{what} {ref!r} not found", 404)
    return e


def _port(ref: str, what: str = "Port") -> PortUsage:
    p = _find(ref, what)
    if not isinstance(p, PortUsage):
        raise InterfaceError(f"{p.qualified_name!r} is not a port")
    return p


def _item(ref: str):
    e = _find(ref, "Interface")
    if I.item_kind(e) is None:
        raise InterfaceError(f"{e.qualified_name!r} is not an interface or dictionary item")
    return e


def _fields(**kw) -> dict:
    return {k: v for k, v in kw.items() if v is not None}


@_safe
def tool_list_interfaces() -> dict:
    return _ok({**I.list_dictionary(SESSION.repo), "meta": I.metadata()})


@_safe
def tool_create_interface(name: Optional[str] = None, kind: str = "DataInterface",
                          color: Optional[str] = None, description: Optional[str] = None,
                          elements: Optional[list] = None, template: Optional[str] = None) -> dict:
    repo = SESSION.repo
    if template:
        item = I.create_from_template(repo, template, name)
    else:
        item = I.create_item(repo, kind, name, resolve=SESSION.find, elements=elements,
                             **_fields(color=color, description=description))
    return _ok(I.describe_item(item, repo, detail=True))


@_safe
def tool_add_interface_element(interface: str, name: Optional[str] = None, type: Optional[str] = None,
                               dimensions: Optional[str] = None, units: Optional[str] = None,
                               complexity: Optional[str] = None, minimum: Any = None, maximum: Any = None,
                               description: Optional[str] = None, domain: Optional[str] = None,
                               prototype: Optional[str] = None, asynchronous: Optional[bool] = None,
                               value: Any = None, index: Optional[int] = None) -> dict:
    item = _item(interface)
    el = I.add_element(SESSION.repo, item, name, index=index, resolve=SESSION.find,
                       **_fields(type=type, dimensions=dimensions, units=units, complexity=complexity,
                                 minimum=minimum, maximum=maximum, description=description,
                                 domain=domain, prototype=prototype, asynchronous=asynchronous,
                                 value=value))
    return _ok(I.describe_element(el))


@_safe
def tool_set_interface_element(interface: str, element: str, new_name: Optional[str] = None,
                               type: Optional[str] = None, dimensions: Optional[str] = None,
                               units: Optional[str] = None, complexity: Optional[str] = None,
                               minimum: Any = None, maximum: Any = None, description: Optional[str] = None,
                               domain: Optional[str] = None, prototype: Optional[str] = None,
                               asynchronous: Optional[bool] = None, value: Any = None,
                               clear_range: bool = False, move: Optional[int] = None) -> dict:
    item = _item(interface)
    el = next((c for c in I.elements_of(item) if c.name == element or c.element_id == element), None)
    if el is None:
        return _err(f"{item.name!r} has no element {element!r}")
    fields = _fields(name=new_name, type=type, dimensions=dimensions, units=units,
                     complexity=complexity, minimum=minimum, maximum=maximum, description=description,
                     domain=domain, prototype=prototype, asynchronous=asynchronous, value=value)
    if clear_range:
        fields.update(minimum=None, maximum=None)
    warnings = I.set_fields(SESSION.repo, el, fields, SESSION.find) if fields else []
    if move:
        I.move_element(el, int(move))
    return _ok({"element": I.describe_element(el), "warnings": warnings,
                "order": [c.name for c in I.elements_of(item)]})


@_safe
def tool_remove_interface_element(interface: str, element: str) -> dict:
    item = _item(interface)
    el = next((c for c in I.elements_of(item) if c.name == element or c.element_id == element), None)
    if el is None:
        return _err(f"{item.name!r} has no element {element!r}")
    I.remove_element(SESSION.repo, el)
    return _ok(I.describe_item(item, SESSION.repo, detail=True))


@_safe
def tool_create_value_type(name: Optional[str] = None, base_type: str = "double", units: str = "",
                           dimensions: str = "1", complexity: str = "real", minimum: Any = None,
                           maximum: Any = None, description: str = "") -> dict:
    vt = I.create_value_type(SESSION.repo, name, base_type=base_type, units=units, dimensions=dimensions,
                             complexity=complexity, minimum=minimum, maximum=maximum,
                             description=description)
    return _ok(I.describe_item(vt, SESSION.repo, detail=True))


@_safe
def tool_assign_interface(port: str, interface: Optional[str] = None) -> dict:
    p = _port(port)
    I.assign_interface(SESSION.repo, p, interface, resolve=SESSION.find)
    return _ok(I.port_info(SESSION.repo, p))


@_safe
def tool_make_interface_shared(port: str, name: Optional[str] = None, on_conflict: str = "error") -> dict:
    p = _port(port)
    shared = I.make_shared(SESSION.repo, p, name, on_conflict)
    return _ok(I.describe_item(shared, SESSION.repo, detail=True))


@_safe
def tool_check_compatibility(source: Optional[str] = None, target: Optional[str] = None,
                             source_element: Optional[str] = None, target_element: Optional[str] = None,
                             connector: Optional[str] = None) -> dict:
    if connector:
        return _ok(I.connector_report(_find(connector, "Connector")))
    if not source or not target:
        return _err("give source and target ports (or a connector)")
    return _ok(I.compatibility_report(_port(source, "Source port"), _port(target, "Target port"),
                                      source_element, target_element))


@_safe
def tool_set_connector_elements(connector: str, source_element: Optional[str] = None,
                                target_element: Optional[str] = None) -> dict:
    c = I.require_port_connector(_find(connector, "Connector"))
    I.set_connector_elements(c, **_fields(source_element=source_element, target_element=target_element))
    return _ok(I.connector_report(c))


@_safe
def tool_create_adapter(parent: str, name: Optional[str] = None) -> dict:
    a = I.create_adapter(SESSION.repo, _find(parent, "Parent"), name)
    return _ok(SESSION.element_summary(a))


@_safe
def tool_set_adapter_mappings(adapter: str, mappings: list) -> dict:
    a = _find(adapter, "Adapter")
    return _ok({"mappings": I.set_adapter_mappings(a, mappings)})


@_safe
def tool_export_dictionary(path: Optional[str] = None) -> dict:
    doc = I.export_dictionary(SESSION.repo)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        return _ok({"saved": path, "items": len(doc["items"])})
    return _ok(doc)


@_safe
def tool_import_dictionary(path: Optional[str] = None, text: Optional[str] = None,
                           on_conflict: str = "error", resolution: Optional[dict] = None,
                           dry_run: bool = False) -> dict:
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    if text is None:
        return _err("give the dictionary file path or its JSON text")
    return _ok(I.import_dictionary(SESSION.repo, text, default=on_conflict, resolution=resolution,
                                   dry_run=dry_run))


_STR = {"type": "string"}
_ELEMENT_FIELDS = {
    "type": {"type": "string", "description": "double, single, int8..uint64, boolean, string, "
                                              "'ValueType: <name>', 'Bus: <name>' (nested) or 'Enum: <name>'"},
    "dimensions": {"type": "string", "description": "e.g. '1', '3' or '[3 3]'"},
    "units": {"type": "string", "description": "e.g. ft, kn, deg, m/s^2"},
    "complexity": {"type": "string", "enum": list(I.COMPLEXITIES)},
    "minimum": {"type": ["number", "string", "null"]},
    "maximum": {"type": ["number", "string", "null"]},
    "description": _STR,
    "domain": {"type": "string", "enum": list(I.PHYSICAL_DOMAINS),
               "description": "physical elements only"},
    "prototype": {"type": "string", "description": "function elements only, e.g. 'y = f(u)'"},
    "asynchronous": {"type": "boolean", "description": "function elements only"},
    "value": {"type": ["integer", "string"], "description": "enumeration literal value"},
}

TOOLS = [
    {"name": "sysml_list_interfaces",
     "description": "List the interface dictionary (shared interfaces, value types, enumerations, "
                    "constants), port-owned interfaces, and the vocabularies (primitive types, "
                    "physical domains, units, templates).",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": tool_list_interfaces},
    {"name": "sysml_create_interface",
     "description": "Create a shared interface in the interface dictionary: DataInterface, "
                    "PhysicalInterface, ServiceInterface, ValueType, Enumeration or Constant, "
                    "optionally with elements, or from an avionics template "
                    "(arinc429, arinc664, milstd1553, discrete, analog, power28vdc).",
     "inputSchema": {"type": "object", "properties": {
         "name": _STR, "kind": {"type": "string", "enum": list(I.ITEM_KINDS)},
         "color": {"type": "string", "description": "#rrggbb"}, "description": _STR,
         "elements": {"type": "array", "items": {"type": "object"},
                      "description": "[{name, type, dimensions, units, ...}]"},
         "template": {"type": "string", "enum": list(I.TEMPLATES)}}},
     "handler": tool_create_interface},
    {"name": "sysml_add_interface_element",
     "description": "Add an element to an interface (data element, physical element, function "
                    "element or enumeration literal), optionally at a position.",
     "inputSchema": {"type": "object", "properties": {
         "interface": _STR, "name": _STR, "index": {"type": "integer"}, **_ELEMENT_FIELDS},
         "required": ["interface"]},
     "handler": tool_add_interface_element},
    {"name": "sysml_set_interface_element",
     "description": "Edit an interface element: rename (new_name), change type/dimensions/units/"
                    "complexity/range/description/domain/prototype, or move it up/down (move=-1/+1).",
     "inputSchema": {"type": "object", "properties": {
         "interface": _STR, "element": _STR, "new_name": _STR, "clear_range": {"type": "boolean"},
         "move": {"type": "integer"}, **_ELEMENT_FIELDS},
         "required": ["interface", "element"]},
     "handler": tool_set_interface_element},
    {"name": "sysml_remove_interface_element",
     "description": "Delete an element from an interface.",
     "inputSchema": {"type": "object", "properties": {"interface": _STR, "element": _STR},
                     "required": ["interface", "element"]},
     "handler": tool_remove_interface_element},
    {"name": "sysml_create_value_type",
     "description": "Create a value type (named atomic type with base type, units, dimensions, "
                    "range) in the interface dictionary.",
     "inputSchema": {"type": "object", "properties": {
         "name": _STR, "base_type": {"type": "string", "enum": list(I.PRIMITIVE_TYPES)},
         "units": _STR, "dimensions": _STR, "complexity": {"type": "string", "enum": list(I.COMPLEXITIES)},
         "minimum": {"type": ["number", "null"]}, "maximum": {"type": ["number", "null"]},
         "description": _STR}},
     "handler": tool_create_value_type},
    {"name": "sysml_assign_interface",
     "description": "Assign an interface to a port: a shared interface or value type (name, id or "
                    "qualified name), 'owned' for a port-owned copy, or null/'' to clear it.",
     "inputSchema": {"type": "object", "properties": {"port": _STR, "interface": {"type": ["string", "null"]}},
                     "required": ["port"]},
     "handler": tool_assign_interface},
    {"name": "sysml_make_interface_shared",
     "description": "Save a port's owned interface into the dictionary. on_conflict: error, keep, "
                    "replace or rename.",
     "inputSchema": {"type": "object", "properties": {
         "port": _STR, "name": _STR,
         "on_conflict": {"type": "string", "enum": ["error", "keep", "replace", "rename"]}},
         "required": ["port"]},
     "handler": tool_make_interface_shared},
    {"name": "sysml_check_compatibility",
     "description": "Check whether two ports (optionally selected bus elements) or an existing "
                    "connector are interface-compatible; returns the reasons when not.",
     "inputSchema": {"type": "object", "properties": {
         "source": _STR, "target": _STR, "source_element": _STR, "target_element": _STR,
         "connector": _STR}},
     "handler": tool_check_compatibility},
    {"name": "sysml_set_connector_elements",
     "description": "Select (or clear with '') the bus element used at a connector's source and target.",
     "inputSchema": {"type": "object", "properties": {
         "connector": _STR, "source_element": _STR, "target_element": _STR},
         "required": ["connector"]},
     "handler": tool_set_connector_elements},
    {"name": "sysml_create_adapter",
     "description": "Create an interface Adapter component (with In and Out ports) inside an "
                    "architecture or component.",
     "inputSchema": {"type": "object", "properties": {"parent": _STR, "name": _STR},
                     "required": ["parent"]},
     "handler": tool_create_adapter},
    {"name": "sysml_set_adapter_mappings",
     "description": "Set an adapter's element mappings: [{target, source, note}] where target is an "
                    "output element, source an input element and note documents unit conversion.",
     "inputSchema": {"type": "object", "properties": {
         "adapter": _STR, "mappings": {"type": "array", "items": {"type": "object"}}},
         "required": ["adapter", "mappings"]},
     "handler": tool_set_adapter_mappings},
    {"name": "sysml_export_dictionary",
     "description": "Export the interface dictionary as a standalone JSON document (written to "
                    "`path` when given, else returned).",
     "inputSchema": {"type": "object", "properties": {"path": _STR}},
     "handler": tool_export_dictionary},
    {"name": "sysml_import_dictionary",
     "description": "Import an interface dictionary JSON file (path or text) into the project. "
                    "Name collisions: on_conflict (error, keep, replace, rename) or per-item "
                    "`resolution` {name: choice}; dry_run lists the collisions first.",
     "inputSchema": {"type": "object", "properties": {
         "path": _STR, "text": _STR,
         "on_conflict": {"type": "string", "enum": ["error", "keep", "replace", "rename"]},
         "resolution": {"type": "object"}, "dry_run": {"type": "boolean"}}},
     "handler": tool_import_dictionary},
]
