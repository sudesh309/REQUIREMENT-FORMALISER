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
from engine.diagram import bdd as bdd_dot, ibd as ibd_dot, requirements as req_dot
from engine.graph_export import EXPORTERS, export_knowledge_graph
from engine.links import (
    LINK_KINDS, create_link, describe_link, link_kind, links_of, list_link_kinds,
)
from engine.validator import Severity, Validator
from kerml.elements import Documentation, Element
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, stereotypes_on
from kerml.types import Type
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
from sysmlv2.relationships import Satisfy, Verify
from sysmlv2.state_machines import (
    StateMachineDefinition, StateMachineRunner, attach_state_machine,
    state_machines_of,
)

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
    "ParameterDefinition":   ParameterDefinition,
    "ParameterUsage":        ParameterUsage,
    "CalculationDefinition": CalculationDefinition,
    "CalculationUsage":      CalculationUsage,
    "Stereotype":            Stereotype,
}


# --- session -------------------------------------------------------------

class Session:
    """Holds the active repository for the duration of the MCP connection."""

    def __init__(self) -> None:
        self.repo: Repository = Repository(name="UntitledProject")
        # Active state-machine runners, keyed by SM element_id.
        self.runners: dict[str, StateMachineRunner] = {}

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


def tool_link(kind: str, source: str, target: str) -> dict:
    """Generic typed link between two elements. See `kind` enum."""
    src = SESSION.find(source); tgt = SESSION.find(target)
    if src is None or tgt is None:
        return _err("Both source and target must be resolvable (UUID or qualified name)")
    if link_kind(kind) is None:
        return _err(f"Unknown link kind {kind!r}. Known: {list_link_kinds()}")
    rel = create_link(kind, src, tgt)
    SESSION.repo.registry.register(rel)
    return _ok(describe_link(rel))


def tool_list_links(ref: Optional[str] = None,
                    direction: str = "both",
                    kind: Optional[str] = None) -> dict:
    if ref is None:
        # Project-wide scan.
        rels = []
        seen: set[str] = set()
        for e in SESSION.repo.all_elements():
            for r in links_of(e, direction="outgoing", kind=kind):
                if r.element_id not in seen:
                    rels.append(describe_link(r)); seen.add(r.element_id)
        return _ok(rels)
    e = SESSION.find(ref)
    if e is None:
        return _err(f"Element {ref!r} not found")
    return _ok([describe_link(r) for r in links_of(e, direction=direction, kind=kind)])


def tool_link_kinds() -> dict:
    return _ok([
        {"name": lk.name, "description": lk.description,
         "aliases": list(lk.aliases), "class": lk.cls.__name__}
        for lk in LINK_KINDS
    ])


def tool_add_parameter(owner: str, name: str,
                       parameter_kind: str = "in",
                       type_qname: Optional[str] = None,
                       multiplicity: Optional[list] = None) -> dict:
    """Add a ParameterUsage to an Action / Calculation / Constraint / Requirement."""
    owner_el = SESSION.find(owner)
    if owner_el is None:
        return _err(f"Owner {owner!r} not found")
    if parameter_kind not in {"in", "out", "inout", "return"}:
        return _err(f"parameter_kind must be one of in/out/inout/return, got {parameter_kind!r}")
    p = ParameterUsage(name=name, parameter_kind=parameter_kind)
    if type_qname:
        t = SESSION.find(type_qname)
        if not isinstance(t, Type):
            return _err(f"Type {type_qname!r} not found")
        p.add_type(t)
    if multiplicity is not None:
        lo, up = multiplicity
        up_v = None if up in (None, "*") else int(up)
        p.multiplicity = MultiplicityRange(int(lo), up_v)
    owner_el.own(p)
    SESSION.repo.registry.register_tree(p)
    return _ok(SESSION.element_summary(p))


def tool_create_requirement(name: str,
                            req_id: Optional[str] = None,
                            text: Optional[str] = None,
                            subject: Optional[str] = None,
                            stakeholders: Optional[list[str]] = None,
                            actors: Optional[list[str]] = None,
                            parent: Optional[str] = None,
                            as_usage: bool = False) -> dict:
    """Create a RequirementDefinition (or RequirementUsage), wire up subject/stakeholders/actors."""
    parent_el = SESSION.find(parent) if parent else SESSION.repo.root_package
    if not isinstance(parent_el, Namespace):
        return _err(f"Parent {parent!r} must be a Namespace")
    cls = RequirementUsage if as_usage else RequirementDefinition
    r = cls(name=name)
    r.req_id = req_id
    r.text = text
    parent_el.own(r)
    SESSION.repo.registry.register_tree(r)
    if subject:
        s = SESSION.find(subject)
        if s is None:
            return _err(f"Subject {subject!r} not found")
        rel = create_link("subject", r, s)
        SESSION.repo.registry.register(rel)
        if hasattr(r, "subject"):
            r.subject = s
    for ref in stakeholders or []:
        s = SESSION.find(ref)
        if s is None:
            return _err(f"Stakeholder {ref!r} not found")
        rel = create_link("stakeholder", r, s)
        SESSION.repo.registry.register(rel)
        if hasattr(r, "stakeholders"):
            r.stakeholders.append(s)
    for ref in actors or []:
        a = SESSION.find(ref)
        if a is None:
            return _err(f"Actor {ref!r} not found")
        rel = create_link("actor", r, a)
        SESSION.repo.registry.register(rel)
        if hasattr(r, "actors"):
            r.actors.append(a)
    return _ok(SESSION.element_summary(r))


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


def tool_define_stereotype(name: str,
                           applies_to: Optional[list[str]] = None,
                           tags: Optional[list[dict]] = None,
                           parent: Optional[str] = None) -> dict:
    parent_el = SESSION.find(parent) if parent else SESSION.repo.root_package
    if parent_el is None or not isinstance(parent_el, Namespace):
        return _err(f"Parent {parent!r} must be a Namespace")
    applies = []
    for kind_name in applies_to or []:
        cls = KIND_REGISTRY.get(kind_name)
        if cls is None:
            return _err(f"Unknown kind in applies_to: {kind_name!r}")
        applies.append(cls)
    s = Stereotype(name=name, applies_to=applies or None)
    parent_el.own(s)
    for t in tags or []:
        s.define_tag(t["name"], default=t.get("default"))
    SESSION.repo.registry.register_tree(s)
    return _ok(SESSION.element_summary(s))


def tool_apply_stereotype(stereotype: str, target: str,
                          values: Optional[dict] = None) -> dict:
    s = SESSION.find(stereotype)
    if not isinstance(s, Stereotype):
        return _err(f"{stereotype!r} is not a Stereotype")
    t = SESSION.find(target)
    if t is None:
        return _err(f"Target {target!r} not found")
    try:
        app = s.apply(t, values or {})
    except (TypeError, KeyError) as ex:
        return _err(str(ex))
    return _ok({"applied": s.name, "to": t.qualified_name, "values": app.values})


def tool_list_stereotypes(target: Optional[str] = None) -> dict:
    if target:
        t = SESSION.find(target)
        if t is None:
            return _err(f"Target {target!r} not found")
        return _ok([
            {"stereotype": a.stereotype.qualified_name, "values": a.values}
            for a in stereotypes_on(t)
        ])
    return _ok([
        {"qualified_name": s.qualified_name,
         "tags": [t.name for t in s.all_tags()],
         "applies_to": [c.__name__ for c in s.applies_to]}
        for s in SESSION.repo.all_elements() if isinstance(s, Stereotype)
    ])


def tool_export_graph(format: str = "turtle") -> dict:
    if format not in EXPORTERS:
        return _err(f"Unknown format {format!r}. Known: {sorted(EXPORTERS)}")
    text = export_knowledge_graph(SESSION.repo.root_package, format)
    return _ok({"format": format, "size": len(text), "text": text})


def tool_export_diagram(kind: str = "bdd", target: Optional[str] = None) -> dict:
    if kind == "ibd":
        t = SESSION.find(target) if target else None
        if not isinstance(t, PartDefinition):
            return _err("ibd requires a PartDefinition target")
        return _ok({"kind": "ibd", "format": "dot", "text": ibd_dot(t)})
    root = SESSION.find(target) if target else SESSION.repo.root_package
    if root is None or not isinstance(root, Namespace):
        return _err("Diagram root must be a Namespace")
    if kind == "bdd":
        return _ok({"kind": "bdd", "format": "dot", "text": bdd_dot(root)})
    if kind in ("requirements", "req"):
        return _ok({"kind": "requirements", "format": "dot", "text": req_dot(root)})
    return _err(f"Unknown diagram kind {kind!r}")


def _resolve_sm(ref: str) -> StateMachineDefinition | None:
    e = SESSION.find(ref)
    if isinstance(e, StateMachineDefinition):
        return e
    if isinstance(e, PartDefinition):
        sms = state_machines_of(e)
        return sms[0] if sms else None
    return None


def tool_attach_state_machine(part: str, name: str) -> dict:
    p = SESSION.find(part)
    if not isinstance(p, PartDefinition):
        return _err(f"{part!r} is not a PartDefinition")
    sm = attach_state_machine(p, name)
    SESSION.repo.registry.register_tree(sm)
    return _ok(SESSION.element_summary(sm))


def tool_add_state(state_machine: str, name: str,
                   entry: Optional[str] = None,
                   do: Optional[str] = None,
                   exit: Optional[str] = None,
                   is_initial: bool = False,
                   is_final: bool = False) -> dict:
    sm = _resolve_sm(state_machine)
    if sm is None:
        return _err(f"State machine {state_machine!r} not found")
    s = sm.add_state(name, entry=entry, do=do, exit=exit,
                     is_initial=is_initial, is_final=is_final)
    SESSION.repo.registry.register_tree(s)
    return _ok(SESSION.element_summary(s))


def tool_add_transition(state_machine: str, source: str, target: str,
                        trigger: Optional[str] = None,
                        guard: Optional[str] = None,
                        effect: Optional[str] = None,
                        name: Optional[str] = None) -> dict:
    sm = _resolve_sm(state_machine)
    if sm is None:
        return _err(f"State machine {state_machine!r} not found")
    # Resolve states by name within the SM, or globally.
    def _find_state(ref: str):
        for s in sm.states:
            if s.name == ref or s.element_id == ref:
                return s
        e = SESSION.find(ref)
        return e
    src = _find_state(source); tgt = _find_state(target)
    if src is None or tgt is None:
        return _err(f"State {source!r} or {target!r} not found in SM")
    t = sm.add_transition(src, tgt, trigger=trigger, guard=guard,
                          effect=effect, name=name)
    SESSION.repo.registry.register_tree(t)
    return _ok(SESSION.element_summary(t))


def tool_fire_event(state_machine: str, event: str,
                    payload: Optional[dict] = None) -> dict:
    sm = _resolve_sm(state_machine)
    if sm is None:
        return _err(f"State machine {state_machine!r} not found")
    runner = SESSION.runners.get(sm.element_id)
    if runner is None:
        runner = sm.runner()
        SESSION.runners[sm.element_id] = runner
    new = runner.fire(event, **(payload or {}))
    return _ok({
        "fired": event,
        "current_state": runner.current.name if runner.current else None,
        "transitioned_to": new.name if new is not None else None,
        "is_in_final": runner.is_in_final(),
        "trace_tail": runner.trace()[-5:],
    })


def tool_state_machine_status(state_machine: str) -> dict:
    sm = _resolve_sm(state_machine)
    if sm is None:
        return _err(f"State machine {state_machine!r} not found")
    runner = SESSION.runners.get(sm.element_id)
    return _ok({
        "state_machine": sm.qualified_name,
        "states": [s.name for s in sm.states],
        "initial": sm.initial_state.name if sm.initial_state else None,
        "finals": [s.name for s in sm.final_states],
        "transitions": [
            {"from": t.transition_source.name if t.transition_source else None,
             "to":   t.transition_target.name if t.transition_target else None,
             "trigger": t.trigger_event,
             "guard": t.guard if isinstance(t.guard, str) else (None if t.guard is None else "λ"),
             "effect": t.effect if isinstance(t.effect, str) else (None if t.effect is None else "λ")}
            for t in sm.transitions
        ],
        "current": runner.current.name if runner and runner.current else None,
        "trace": runner.trace() if runner else [],
    })


def tool_reset_state_machine(state_machine: str) -> dict:
    sm = _resolve_sm(state_machine)
    if sm is None:
        return _err(f"State machine {state_machine!r} not found")
    SESSION.runners[sm.element_id] = sm.runner()
    r = SESSION.runners[sm.element_id]
    return _ok({"reset": sm.qualified_name,
                "current": r.current.name if r.current else None})


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
        "name": "sysml_link",
        "description": (
            "Create a typed link between two model elements. `kind` is one of: "
            + ", ".join(list_link_kinds()) + "."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string", "enum": list_link_kinds()},
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["kind", "source", "target"],
        },
        "handler": tool_link,
    },
    {
        "name": "sysml_list_links",
        "description": "List typed links touching an element (or project-wide if no ref).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref":       {"type": "string"},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"]},
                "kind":      {"type": "string", "enum": list_link_kinds()},
            },
        },
        "handler": tool_list_links,
    },
    {
        "name": "sysml_link_kinds",
        "description": "Describe every available link kind (name, class, description, aliases).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_link_kinds,
    },
    {
        "name": "sysml_add_parameter",
        "description": (
            "Add a ParameterUsage to a behavior-like element (Action / Calculation / "
            "Constraint / Requirement Definition or Usage). parameter_kind is one of "
            "in / out / inout / return."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner":          {"type": "string"},
                "name":           {"type": "string"},
                "parameter_kind": {"type": "string",
                                   "enum": ["in", "out", "inout", "return"]},
                "type_qname":     {"type": "string"},
                "multiplicity":   {"type": "array", "minItems": 2, "maxItems": 2},
            },
            "required": ["owner", "name"],
        },
        "handler": tool_add_parameter,
    },
    {
        "name": "sysml_create_requirement",
        "description": (
            "Create a Requirement (Definition or Usage) and optionally wire its "
            "subject / stakeholders / actors via typed links."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":         {"type": "string"},
                "req_id":       {"type": "string"},
                "text":         {"type": "string"},
                "subject":      {"type": "string"},
                "stakeholders": {"type": "array", "items": {"type": "string"}},
                "actors":       {"type": "array", "items": {"type": "string"}},
                "parent":       {"type": "string"},
                "as_usage":     {"type": "boolean"},
            },
            "required": ["name"],
        },
        "handler": tool_create_requirement,
    },
    {
        "name": "sysml_validate",
        "description": "Run the well-formedness validator over the current project.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_validate,
    },
    {
        "name": "sysml_define_stereotype",
        "description": "Define a custom Stereotype with optional applies_to filter and typed tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":       {"type": "string"},
                "applies_to": {"type": "array", "items": {"type": "string"},
                               "description": "List of metaclass names this stereotype may decorate"},
                "tags":       {"type": "array",
                               "items": {"type": "object",
                                         "properties": {"name": {"type": "string"},
                                                        "default": {}},
                                         "required": ["name"]}},
                "parent":     {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": tool_define_stereotype,
    },
    {
        "name": "sysml_apply_stereotype",
        "description": "Apply a previously-defined Stereotype to a target element.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stereotype": {"type": "string"},
                "target":     {"type": "string"},
                "values":     {"type": "object"},
            },
            "required": ["stereotype", "target"],
        },
        "handler": tool_apply_stereotype,
    },
    {
        "name": "sysml_list_stereotypes",
        "description": "List defined stereotypes, or applications on a specific target.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
        },
        "handler": tool_list_stereotypes,
    },
    {
        "name": "sysml_export_graph",
        "description": "Export the project as a knowledge graph (turtle / json-ld / graphml / cypher).",
        "inputSchema": {
            "type": "object",
            "properties": {"format": {"type": "string",
                                      "enum": ["turtle", "json-ld", "graphml", "cypher"]}},
        },
        "handler": tool_export_graph,
    },
    {
        "name": "sysml_export_diagram",
        "description": "Export a Graphviz DOT diagram (bdd / ibd / requirements / statemachine).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string",
                           "enum": ["bdd", "ibd", "requirements", "statemachine"]},
                "target": {"type": "string",
                           "description": "Required for ibd/statemachine; optional namespace root otherwise"},
            },
        },
        "handler": tool_export_diagram,
    },
    {
        "name": "sysml_attach_state_machine",
        "description": "Attach a new StateMachine to a PartDefinition.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "part": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["part", "name"],
        },
        "handler": tool_attach_state_machine,
    },
    {
        "name": "sysml_add_state",
        "description": (
            "Add a state to a state machine, with optional entry/do/exit "
            "actions and initial/final flags."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_machine": {"type": "string"},
                "name":          {"type": "string"},
                "entry":         {"type": "string"},
                "do":            {"type": "string"},
                "exit":          {"type": "string"},
                "is_initial":    {"type": "boolean"},
                "is_final":      {"type": "boolean"},
            },
            "required": ["state_machine", "name"],
        },
        "handler": tool_add_state,
    },
    {
        "name": "sysml_add_transition",
        "description": "Add a transition between two states with optional trigger/guard/effect.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_machine": {"type": "string"},
                "source":        {"type": "string"},
                "target":        {"type": "string"},
                "trigger":       {"type": "string"},
                "guard":         {"type": "string", "description": "Python expression over the event payload"},
                "effect":        {"type": "string", "description": "Action descriptor (string)"},
                "name":          {"type": "string"},
            },
            "required": ["state_machine", "source", "target"],
        },
        "handler": tool_add_transition,
    },
    {
        "name": "sysml_fire_event",
        "description": "Fire an event into a state machine (creates a runner on first call).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_machine": {"type": "string"},
                "event":         {"type": "string"},
                "payload":       {"type": "object"},
            },
            "required": ["state_machine", "event"],
        },
        "handler": tool_fire_event,
    },
    {
        "name": "sysml_state_machine_status",
        "description": "Inspect a state machine: states, transitions, current state, trace.",
        "inputSchema": {
            "type": "object",
            "properties": {"state_machine": {"type": "string"}},
            "required": ["state_machine"],
        },
        "handler": tool_state_machine_status,
    },
    {
        "name": "sysml_reset_state_machine",
        "description": "Reset a state machine's runner back to the initial state.",
        "inputSchema": {
            "type": "object",
            "properties": {"state_machine": {"type": "string"}},
            "required": ["state_machine"],
        },
        "handler": tool_reset_state_machine,
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
