"""MCP server exposing the SysML v2 core engine as tools.

Implements MCP protocol 2024-11-05 over stdio (JSON-RPC 2.0).
No external dependencies — uses only the Python standard library.

Tools exposed:
  - sysml_new_project        : start a fresh project repository
  - sysml_open_project       : load a project from JSON
  - sysml_save_project       : save the project to JSON
  - sysml_parse_sysml        : parse a .sysml source string into the model
  - sysml_list_elements      : list elements (optionally filtered by kind / parent)
  - sysml_get_element        : fetch element details by id or qualified name
  - sysml_create_element     : create an element of a given SysML kind
  - sysml_delete_element     : delete an element and its descendants
  - sysml_set_property       : set a scalar property on an element
  - sysml_set_feature_type   : (re)bind a Feature/Usage's type by qualified name
  - sysml_connect            : create a ConnectionUsage between two features
  - sysml_satisfy            : create a Satisfy relationship
  - sysml_verify             : create a Verify relationship
  - sysml_validate           : run the well-formedness validator
  - sysml_tree               : return the containment tree as nested JSON

Resources exposed:
  - sysml://project          : the current project as JSON
  - sysml://library/kerml    : the KerML standard library
  - sysml://library/sysml    : the SysML v2 standard library
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Optional

from engine import Repository, from_json, parse, to_json
from engine.validator import Severity, Validator
from kerml.elements import Documentation, Element
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package
from kerml.types import Type
from sysmlv2 import (
    ActionDefinition, ActionUsage,
    AttributeDefinition, AttributeUsage,
    ConnectionDefinition, ConnectionUsage,
    ConstraintDefinition, ConstraintUsage,
    EnumerationDefinition,
    InterfaceDefinition, InterfaceUsage,
    ItemDefinition, ItemUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage,
    StateDefinition, StateUsage,
)
from sysmlv2.relationships import Satisfy, Verify

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sysmlv2-core-engine"
SERVER_VERSION = "0.1.0"


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
}


# --- session -------------------------------------------------------------

class Session:
    """Holds the active repository for the duration of the MCP connection."""

    def __init__(self) -> None:
        self.repo: Repository = Repository(name="UntitledProject")

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
        return out

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


def tool_new_project(name: str = "UntitledProject") -> dict:
    SESSION.repo = Repository(name=name)
    return _ok({"name": name, "root_id": SESSION.repo.root_package.element_id})


def tool_open_project(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        SESSION.repo = from_json(f.read())
    return _ok({"loaded": path, "element_count": len(list(SESSION.repo.all_elements()))})


def tool_save_project(path: str) -> dict:
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(SESSION.repo))
    return _ok({"saved": path})


def tool_parse_sysml(source: str) -> dict:
    parse(source, into=SESSION.repo.root_package)
    SESSION.repo.registry.register_tree(SESSION.repo.root_package)
    return _ok({"element_count": len(list(SESSION.repo.all_elements()))})


def tool_list_elements(kind: Optional[str] = None,
                       parent: Optional[str] = None) -> dict:
    elements = list(SESSION.repo.all_elements())
    if kind:
        elements = [e for e in elements if e.kind == kind]
    if parent:
        parent_el = SESSION.find(parent)
        if parent_el is None:
            return _err(f"Parent {parent!r} not found")
        parent_ids = {e.element_id for e in parent_el.walk()}
        elements = [e for e in elements if e.element_id in parent_ids and e is not parent_el]
    return _ok([SESSION.element_summary(e) for e in elements])


def tool_get_element(ref: str) -> dict:
    e = SESSION.find(ref)
    if e is None:
        return _err(f"Element {ref!r} not found")
    return _ok(SESSION.element_summary(e))


def tool_create_element(kind: str, name: str,
                        parent: Optional[str] = None,
                        properties: Optional[dict] = None) -> dict:
    cls = KIND_REGISTRY.get(kind)
    if cls is None:
        return _err(f"Unknown kind {kind!r}. Known: {sorted(KIND_REGISTRY)}")
    parent_el: Element = SESSION.find(parent) if parent else SESSION.repo.root_package
    if parent_el is None:
        return _err(f"Parent {parent!r} not found")
    if not isinstance(parent_el, Namespace):
        n = parent_el
        while n is not None and not isinstance(n, Namespace):
            n = n.owner
        if n is None:
            return _err("Cannot find a Namespace ancestor for parent")
        parent_el = n
    try:
        elem = cls(name=name)  # type: ignore[call-arg]
    except TypeError:
        elem = cls()  # type: ignore[call-arg]
        elem.name = name
    parent_el.own(elem)
    SESSION.repo.registry.register_tree(elem)
    if properties:
        _apply_properties(elem, properties)
    return _ok(SESSION.element_summary(elem))


def tool_delete_element(ref: str) -> dict:
    e = SESSION.find(ref)
    if e is None:
        return _err(f"Element {ref!r} not found")
    if e is SESSION.repo.root_package:
        return _err("Cannot delete the project root")
    SESSION.repo.remove(e)
    return _ok({"deleted": ref})


def tool_set_property(ref: str, key: str, value: Any) -> dict:
    e = SESSION.find(ref)
    if e is None:
        return _err(f"Element {ref!r} not found")
    _apply_properties(e, {key: value})
    return _ok(SESSION.element_summary(e))


def tool_set_feature_type(ref: str, type_qname: str,
                          multiplicity: Optional[list] = None) -> dict:
    e = SESSION.find(ref)
    if not isinstance(e, Feature):
        return _err(f"{ref!r} is not a Feature/Usage")
    tgt = SESSION.find(type_qname)
    if not isinstance(tgt, Type):
        return _err(f"Type {type_qname!r} not found")
    e.feature_typings = []
    e.add_type(tgt)
    if multiplicity is not None:
        lo, up = multiplicity
        up_v = None if up in (None, "*") else int(up)
        e.multiplicity = MultiplicityRange(int(lo), up_v)
    return _ok(SESSION.element_summary(e))


def tool_connect(end_a: str, end_b: str,
                 name: Optional[str] = None,
                 parent: Optional[str] = None) -> dict:
    a = SESSION.find(end_a)
    b = SESSION.find(end_b)
    if not isinstance(a, Feature) or not isinstance(b, Feature):
        return _err("Both ends must be Features (Usages, Ports, etc.)")
    parent_el = SESSION.find(parent) if parent else SESSION.repo.root_package
    if parent_el is None:
        return _err(f"Parent {parent!r} not found")
    cu = ConnectionUsage(name=name or f"conn_{a.name}_{b.name}", ends=[a, b])
    parent_el.own(cu)
    SESSION.repo.registry.register_tree(cu)
    return _ok(SESSION.element_summary(cu))


def tool_satisfy(satisfier: str, requirement: str) -> dict:
    s = SESSION.find(satisfier); r = SESSION.find(requirement)
    if s is None or r is None:
        return _err("Both satisfier and requirement must be resolvable")
    rel = Satisfy(s, r)
    s.add_relationship(rel)
    SESSION.repo.registry.register(rel)
    return _ok({"satisfier": s.qualified_name, "requirement": r.qualified_name,
                "relationship_id": rel.element_id})


def tool_verify(verifier: str, requirement: str) -> dict:
    v = SESSION.find(verifier); r = SESSION.find(requirement)
    if v is None or r is None:
        return _err("Both verifier and requirement must be resolvable")
    rel = Verify(v, r)
    v.add_relationship(rel)
    SESSION.repo.registry.register(rel)
    return _ok({"verifier": v.qualified_name, "requirement": r.qualified_name,
                "relationship_id": rel.element_id})


def tool_validate() -> dict:
    issues = Validator().validate(SESSION.repo)
    return _ok({
        "issue_count": len(issues),
        "errors":   sum(1 for i in issues if i.severity is Severity.ERROR),
        "warnings": sum(1 for i in issues if i.severity is Severity.WARNING),
        "issues": [
            {"severity": i.severity.value, "rule": i.rule, "message": i.message,
             "element_id": i.element.element_id,
             "qualified_name": i.element.qualified_name}
            for i in issues
        ],
    })


def tool_tree(root: Optional[str] = None) -> dict:
    r = SESSION.find(root) if root else SESSION.repo.root_package
    if r is None:
        return _err(f"Root {root!r} not found")
    return _ok(SESSION.tree(r))


def _apply_properties(e: Element, props: dict) -> None:
    for k, v in props.items():
        if k == "name":
            e.name = v
        elif k == "short_name":
            e.short_name = v
        elif k == "is_abstract" and hasattr(e, "is_abstract"):
            e.is_abstract = bool(v)
        elif k == "multiplicity" and isinstance(e, Feature):
            lo, up = v
            up_v = None if up in (None, "*") else int(up)
            e.multiplicity = MultiplicityRange(int(lo), up_v)
        elif k == "doc":
            for a in list(e.annotations):
                if isinstance(a, Documentation):
                    e.annotations.remove(a)
            if v:
                e.add_annotation(Documentation(body=str(v)))
        elif hasattr(e, k):
            setattr(e, k, v)


# --- tool schema (MCP) ---------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "sysml_new_project",
        "description": "Start a fresh SysML v2 project, discarding the current one.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        "handler": tool_new_project,
    },
    {
        "name": "sysml_open_project",
        "description": "Load a SysML v2 project from a JSON file on disk.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "handler": tool_open_project,
    },
    {
        "name": "sysml_save_project",
        "description": "Save the current project to a JSON file on disk.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "handler": tool_save_project,
    },
    {
        "name": "sysml_parse_sysml",
        "description": "Parse a SysML v2 textual source string into the current project.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
        "handler": tool_parse_sysml,
    },
    {
        "name": "sysml_list_elements",
        "description": "List elements in the project, optionally filtered by kind and/or parent (UUID or qualified name).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string", "description": "Metaclass name, e.g. 'PartDefinition'"},
                "parent": {"type": "string", "description": "Parent element UUID or qualified name"},
            },
        },
        "handler": tool_list_elements,
    },
    {
        "name": "sysml_get_element",
        "description": "Fetch a single element by UUID or qualified name.",
        "inputSchema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
        "handler": tool_get_element,
    },
    {
        "name": "sysml_create_element",
        "description": (
            "Create a SysML v2 element. `kind` must be one of: "
            + ", ".join(sorted(KIND_REGISTRY)) + "."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string", "enum": sorted(KIND_REGISTRY)},
                "name":   {"type": "string"},
                "parent": {"type": "string", "description": "Parent UUID or qualified name (default: project root)"},
                "properties": {"type": "object", "description": "Optional name/short_name/is_abstract/multiplicity/doc/req_id/text"},
            },
            "required": ["kind", "name"],
        },
        "handler": tool_create_element,
    },
    {
        "name": "sysml_delete_element",
        "description": "Delete an element (and its descendants) by UUID or qualified name.",
        "inputSchema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
        "handler": tool_delete_element,
    },
    {
        "name": "sysml_set_property",
        "description": "Set a single property (name, short_name, is_abstract, multiplicity, doc, req_id, text, ...) on an element.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref":   {"type": "string"},
                "key":   {"type": "string"},
                "value": {},
            },
            "required": ["ref", "key", "value"],
        },
        "handler": tool_set_property,
    },
    {
        "name": "sysml_set_feature_type",
        "description": "Bind (or rebind) the type of a Feature/Usage by qualified name, optionally setting multiplicity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref":          {"type": "string"},
                "type_qname":   {"type": "string"},
                "multiplicity": {"type": "array", "items": {}, "minItems": 2, "maxItems": 2,
                                 "description": "[lower, upper] (use '*' for unbounded)"},
            },
            "required": ["ref", "type_qname"],
        },
        "handler": tool_set_feature_type,
    },
    {
        "name": "sysml_connect",
        "description": "Create a ConnectionUsage between two feature ends.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "end_a":  {"type": "string"},
                "end_b":  {"type": "string"},
                "name":   {"type": "string"},
                "parent": {"type": "string"},
            },
            "required": ["end_a", "end_b"],
        },
        "handler": tool_connect,
    },
    {
        "name": "sysml_satisfy",
        "description": "Create a Satisfy relationship from a part/behavior to a requirement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "satisfier":   {"type": "string"},
                "requirement": {"type": "string"},
            },
            "required": ["satisfier", "requirement"],
        },
        "handler": tool_satisfy,
    },
    {
        "name": "sysml_verify",
        "description": "Create a Verify relationship from a verification case to a requirement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "verifier":    {"type": "string"},
                "requirement": {"type": "string"},
            },
            "required": ["verifier", "requirement"],
        },
        "handler": tool_verify,
    },
    {
        "name": "sysml_validate",
        "description": "Run the well-formedness validator over the current project.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_validate,
    },
    {
        "name": "sysml_tree",
        "description": "Return the containment tree (rooted at the project or a given element) as nested JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
        },
        "handler": tool_tree,
    },
]


TOOL_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}


# --- MCP wire protocol ---------------------------------------------------

def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _reply(req_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id,
           "error": {"code": code, "message": message}})


def _handle(req: dict) -> None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        _reply(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return

    if method in ("notifications/initialized", "initialized"):
        return  # one-way notification, no response

    if method == "tools/list":
        _reply(req_id, {
            "tools": [
                {"name": t["name"], "description": t["description"],
                 "inputSchema": t["inputSchema"]}
                for t in TOOLS
            ]
        })
        return

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOL_BY_NAME.get(name)
        if tool is None:
            _error(req_id, -32601, f"Unknown tool {name!r}")
            return
        try:
            result = tool["handler"](**args)
        except TypeError as ex:
            _error(req_id, -32602, f"Invalid arguments for {name!r}: {ex}")
            return
        except Exception as ex:  # noqa: BLE001
            tb = traceback.format_exc()
            _reply(req_id, {
                "isError": True,
                "content": [{"type": "text", "text": f"{type(ex).__name__}: {ex}\n{tb}"}],
            })
            return
        _reply(req_id, {
            "isError": not result.get("ok", True),
            "content": [
                {"type": "text",
                 "text": json.dumps(result.get("result") if result.get("ok") else result.get("error"),
                                    indent=2, default=str)}
            ],
        })
        return

    if method == "resources/list":
        _reply(req_id, {"resources": [
            {"uri": "sysml://project",       "name": "Current project",
             "description": "JSON snapshot of the active project", "mimeType": "application/json"},
            {"uri": "sysml://library/kerml", "name": "KerML standard library",
             "description": "Built-in KerML library contents",     "mimeType": "application/json"},
            {"uri": "sysml://library/sysml", "name": "SysML v2 standard library",
             "description": "Built-in SysML v2 library contents",  "mimeType": "application/json"},
        ]})
        return

    if method == "resources/read":
        uri = params.get("uri", "")
        if uri == "sysml://project":
            text = to_json(SESSION.repo)
        elif uri == "sysml://library/kerml":
            from kerml.library import KERML_LIBRARY
            text = json.dumps(SESSION.tree(KERML_LIBRARY), indent=2, default=str)
        elif uri == "sysml://library/sysml":
            from sysmlv2.library import SYSML_LIBRARY
            text = json.dumps(SESSION.tree(SYSML_LIBRARY), indent=2, default=str)
        else:
            _error(req_id, -32602, f"Unknown resource {uri!r}")
            return
        _reply(req_id, {"contents": [
            {"uri": uri, "mimeType": "application/json", "text": text}
        ]})
        return

    if method == "ping":
        _reply(req_id, {})
        return

    _error(req_id, -32601, f"Method {method!r} not implemented")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as ex:
            _error(None, -32700, f"Parse error: {ex}")
            continue
        try:
            _handle(req)
        except Exception as ex:  # noqa: BLE001 — top-level safety net
            _error(req.get("id"), -32603, f"Internal error: {ex}")


if __name__ == "__main__":
    main()
