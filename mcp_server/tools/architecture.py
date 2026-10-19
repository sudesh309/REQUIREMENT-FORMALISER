"""MCP tools for System Composer-style architecture modeling (engine/architecture.py).

Every editing tool applies the same validation as the web API and is recorded
as one undo step (``sysml_undo`` / ``sysml_redo``). Edits made by the core
tools in between are detected and undone as one step of their own.
Element references may be ids or qualified names; ports may also be given by
name relative to their component.
"""
from __future__ import annotations

from typing import Any, Optional

from engine import architecture as A
from engine.undo import history_for, redo, tracked, undo
from kerml.elements import Element
from mcp_server.core import SESSION, _err, _ok, register_summary_hook
from sysmlv2.definitions import ConnectionUsage, PortUsage


def _find(ref: Optional[str], what: str, required: bool = True) -> Optional[Element]:
    if not ref:
        if required:
            raise A.ArchitectureError(f"{what} is required")
        return None
    e = SESSION.find(ref)
    if e is None:
        raise A.ArchitectureError(f"{what} {ref!r} not found", 404)
    return e


def _port_ref(ref: str) -> Any:
    """A PortUsage when `ref` is an id or qualified name, else the bare port name."""
    hit = SESSION.repo.by_id(ref) or (SESSION.repo.resolve(ref) if "::" in (ref or "") else None)
    return hit if isinstance(hit, PortUsage) else ref


def _run(label: Optional[str], fn) -> dict:
    try:
        if label is None:
            return _ok(fn())
        with tracked(SESSION, label):
            return _ok(fn())
    except A.ArchitectureError as ex:
        return _err(f"{ex} (status {ex.status})")


def _comp_json(c: Element) -> dict:
    return A.component_view(c, c.owner)


# --- tools ------------------------------------------------------------------

def tool_set_model_type(type: str, force: bool = False) -> dict:
    return _run("Change model type", lambda: {
        "type": A.set_model_type(SESSION.repo, type, force=force),
        "allowed_port_kinds": list(A.allowed_port_kinds(SESSION.repo))})


def tool_new_architecture(name: Optional[str] = None, package: Optional[str] = None) -> dict:
    def go():
        a = A.create_architecture(SESSION.repo, name, _find(package, "package", False))
        return SESSION.element_summary(a)
    return _run("New architecture", go)


def tool_add_component(composition: str, name: Optional[str] = None,
                       definition: Optional[str] = None) -> dict:
    def go():
        c = A.add_component(SESSION.repo, _find(composition, "composition"), name,
                            _find(definition, "definition", False))
        return _comp_json(c)
    return _run("Add component", go)


def tool_rename(element: str, name: str) -> dict:
    return _run("Rename", lambda: SESSION.element_summary(
        A.rename(SESSION.repo, _find(element, "element"), name)))


def tool_add_port(owner: str, name: Optional[str] = None, direction: str = "in",
                  kind: str = "data", interface: Optional[str] = None,
                  usage_only: bool = False) -> dict:
    def go():
        o = _find(owner, "owner")
        p = A.add_port(SESSION.repo, o, name, direction, kind, _find(interface, "interface", False),
                       usage_only=usage_only)
        return A.port_view(p, o, A.port_layouts(o)[id(p)])
    return _run("Add port", go)


def tool_update_port(port: str, name: Optional[str] = None, direction: Optional[str] = None,
                     kind: Optional[str] = None, interface: Optional[str] = None,
                     clear_interface: bool = False, force: bool = False) -> dict:
    def go():
        p = _find(port, "port")
        kw: dict[str, Any] = {"name": name, "direction": direction, "kind": kind, "force": force}
        if interface or clear_interface:
            kw["interface"] = None if clear_interface else _find(interface, "interface")
        A.update_port(SESSION.repo, p, **kw)
        return A.port_view(p, p.owner, A.port_layouts(p.owner)[id(p)])
    return _run("Edit port", go)


def tool_connect_ports(composition: str, source_port: str, target_port: str,
                       source_component: Optional[str] = None,
                       target_component: Optional[str] = None,
                       name: Optional[str] = None,
                       source_element: Optional[str] = None,
                       target_element: Optional[str] = None) -> dict:
    def go():
        comp = _find(composition, "composition")
        conn = A.connect(
            SESSION.repo, comp,
            {"component": _find(source_component, "source component", False), "port": _port_ref(source_port)},
            {"component": _find(target_component, "target component", False), "port": _port_ref(target_port)},
            name)
        if source_element or target_element:
            from engine import interfaces as I   # bus-element selection on the new connector
            try:
                I.set_connector_elements(conn, source_element or None, target_element or None)
            except I.InterfaceError as ex:
                SESSION.repo.remove(conn)
                raise A.ArchitectureError(str(ex)) from None
        return A.connector_view(conn, comp)
    return _run("Connect", go)


def tool_connect_to_new_port(composition: str, source_port: str,
                             source_component: Optional[str] = None,
                             target_component: Optional[str] = None,
                             port_name: Optional[str] = None, name: Optional[str] = None,
                             side: Optional[str] = None, offset: float = 0.5) -> dict:
    def go():
        comp = _find(composition, "composition")
        layout = {"side": side, "offset": offset} if side else None
        port, conn = A.connect_new_port(
            SESSION.repo, comp,
            {"component": _find(source_component, "source component", False), "port": _port_ref(source_port)},
            _find(target_component, "target component", False),
            name=name, port_name=port_name, layout=layout)
        end = 1 if conn.ends[1] is port else 0
        owner = conn.end_contexts[end] or comp         # the component (or composition) showing it
        out = A.connector_view(conn, comp)
        out["created_port"] = A.port_view(port, owner, A.port_layouts(owner)[id(port)])
        return out
    return _run("Connect", go)


def tool_connect_targets(composition: str, source_port: str,
                         source_component: Optional[str] = None) -> dict:
    def go():
        comp = _find(composition, "composition")
        ctx = _find(source_component, "source component", False)
        port = A.resolve_port(ctx or comp, _port_ref(source_port))
        targets = A.connect_targets(comp, (ctx, port))
        names = {(c.element_id if c is not None else None, p.element_id): A._label((c, p))
                 for c, p in A.view_ports(comp)}
        for t in targets:
            t["label"] = names.get((t["component_id"], t["port_id"]))
        return {"targets": targets}
    return _run(None, go)


def tool_set_layout(items: list) -> dict:
    return _run("Move", lambda: {"updated": A.apply_layout(SESSION.repo, items)})


def tool_locate(element: str) -> dict:
    def go():
        hit = A.locate(_find(element, "element"))
        if hit is None:
            return {"composition": None, "select": None}
        return {"composition": hit["composition"].element_id,
                "select": hit["select"].element_id if hit["select"] is not None else None}
    return _run(None, go)


def tool_arrange(composition: str) -> dict:
    return _run("Arrange", lambda: {"positions": A.auto_layout(
        SESSION.repo, _find(composition, "composition"))})


def tool_group(composition: str, components: list, name: Optional[str] = None) -> dict:
    def go():
        g = A.group(SESSION.repo, _find(composition, "composition"),
                    [_find(c, "component") for c in components or []], name)
        return _comp_json(g)
    return _run("Create component from selection", go)


def tool_expand(component: str) -> dict:
    return _run("Expand component", lambda: {"components": [
        c.element_id for c in A.expand(SESSION.repo, _find(component, "component"))]})


def tool_save_as_reference(component: str, name: Optional[str] = None,
                           package: Optional[str] = None) -> dict:
    def go():
        c = _find(component, "component")
        d = A.save_as_reference(SESSION.repo, c, name, _find(package, "package", False))
        return {"definition": SESSION.element_summary(d), "component": _comp_json(c)}
    return _run("Save as reference", go)


def tool_inline_component(component: str) -> dict:
    return _run("Inline component", lambda: _comp_json(
        A.inline_component(SESSION.repo, _find(component, "component"))))


def tool_duplicate(components: list, target: Optional[str] = None) -> dict:
    def go():
        copies = A.duplicate(SESSION.repo, [_find(c, "component") for c in components or []],
                             _find(target, "target", False))
        return {"components": [_comp_json(c) for c in copies]}
    return _run("Duplicate", go)


def tool_delete(elements: list) -> dict:
    return _run("Delete", lambda: {"deleted": A.delete_elements(
        SESSION.repo, [_find(e, "element") for e in elements or []])})


def tool_arch_view(composition: str) -> dict:
    return _run(None, lambda: A.view(SESSION.repo, _find(composition, "composition")))


def tool_arch_tree(root: str) -> dict:
    return _run(None, lambda: A.model_tree(_find(root, "root")))


def tool_undo() -> dict:
    done = undo(SESSION)
    return _ok({"undone": done, **history_for(SESSION).state()})


def tool_redo() -> dict:
    done = redo(SESSION)
    return _ok({"redone": done, **history_for(SESSION).state()})


# --- summaries ----------------------------------------------------------------

def _summary(e: Element, d: dict) -> None:
    badges = A.component_badges(e) + A.port_badges(e)
    if badges:
        d.setdefault("badges", []).extend(badges)
    if isinstance(e, PortUsage):
        d["port_kind"] = e.port_kind
        d["direction"] = e.direction.value
    elif isinstance(e, ConnectionUsage) and getattr(e, "end_contexts", ()):
        d["end_contexts"] = [c.element_id if c is not None else None for c in e.end_contexts]


register_summary_hook(_summary)


def _schema(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required}


_S = {"type": "string"}
_REF = {"type": "string", "description": "Element id or qualified name"}
_LIST = {"type": "array", "items": {"type": "string"}, "description": "Element ids or qualified names"}

TOOLS = [
    {"name": "sysml_set_model_type",
     "description": "Set the architecture model type: 'system' (data + physical ports) or "
                    "'software' (data + client/server ports). Refused when existing ports conflict "
                    "unless force=true.",
     "inputSchema": _schema({"type": {"type": "string", "enum": list(A.MODEL_TYPES)},
                             "force": {"type": "boolean"}}, ["type"]),
     "handler": tool_set_model_type},
    {"name": "sysml_new_architecture",
     "description": "Create a root architecture (PartDefinition) to hold components.",
     "inputSchema": _schema({"name": _S, "package": _REF}, []),
     "handler": tool_new_architecture},
    {"name": "sysml_add_component",
     "description": "Add a component to an architecture or component. Names are unique among "
                    "siblings (auto-numbered Component, Component1, ...). Give 'definition' "
                    "(a PartDefinition) to add a reference component.",
     "inputSchema": _schema({"composition": _REF, "name": _S, "definition": _REF}, ["composition"]),
     "handler": tool_add_component},
    {"name": "sysml_rename_element",
     "description": "Rename a component, port, connector or architecture (names must stay unique).",
     "inputSchema": _schema({"element": _REF, "name": _S}, ["element", "name"]),
     "handler": tool_rename},
    {"name": "sysml_add_port",
     "description": "Add a port to a component or architecture (an architecture's own ports are the "
                    "boundary ports seen from inside). direction: in|out|inout; kind: "
                    "data|physical|client|server (allowed kinds depend on the model type). On a "
                    "reference component the port goes to its definition unless usage_only.",
     "inputSchema": _schema({"owner": _REF, "name": _S,
                             "direction": {"type": "string", "enum": list(A.DIRECTIONS)},
                             "kind": {"type": "string", "enum": ["data", "physical", "client", "server"]},
                             "interface": _REF, "usage_only": {"type": "boolean"}}, ["owner"]),
     "handler": tool_add_port},
    {"name": "sysml_update_port",
     "description": "Change a port's name, direction, kind or interface; refused when that breaks "
                    "existing connectors unless force=true.",
     "inputSchema": _schema({"port": _REF, "name": _S, "direction": _S, "kind": _S, "interface": _REF,
                             "clear_interface": {"type": "boolean"}, "force": {"type": "boolean"}},
                            ["port"]),
     "handler": tool_update_port},
    {"name": "sysml_connect_ports",
     "description": "Connect two ports inside a composition with System Composer rules: data goes "
                    "output -> input (a boundary input acts as a source inside), an input has one "
                    "driver, outputs may branch, physical <-> physical, client <-> server. Omit a "
                    "component to use a boundary port of the composition; a component deeper in the "
                    "hierarchy gets boundary ports added on the way (cross-hierarchy). Ports may be "
                    "ids or port names. Optionally select a bus interface element at either end "
                    "(source_element / target_element, e.g. 'position.lat').",
     "inputSchema": _schema({"composition": _REF, "source_component": _REF, "source_port": _S,
                             "target_component": _REF, "target_port": _S, "name": _S,
                             "source_element": _S, "target_element": _S},
                            ["composition", "source_port", "target_port"]),
     "handler": tool_connect_ports},
    {"name": "sysml_connect_to_new_port",
     "description": "Connect a port to a NEW port created for it (System Composer: drop a connector "
                    "on a block): on 'target_component' (a direct sub-component; on a reference "
                    "component the port goes to its definition) or, without it, a new boundary port of "
                    "the composition. The new port mirrors the source's kind and interface with the "
                    "opposite role and is named after it unless port_name is given. side/offset place it.",
     "inputSchema": _schema({"composition": _REF, "source_component": _REF, "source_port": _S,
                             "target_component": _REF, "port_name": _S, "name": _S,
                             "side": {"type": "string", "enum": list(A.SIDES)},
                             "offset": {"type": "number", "minimum": 0, "maximum": 1}},
                            ["composition", "source_port"]),
     "handler": tool_connect_to_new_port},
    {"name": "sysml_connect_targets",
     "description": "Which ports of a composition's view a connector from the given source port may "
                    "end at: every port with ok, the reason when not, the connector kind and whether "
                    "the connection would be turned around. Changes nothing.",
     "inputSchema": _schema({"composition": _REF, "source_component": _REF, "source_port": _S},
                            ["composition", "source_port"]),
     "handler": tool_connect_targets},
    {"name": "sysml_set_layout",
     "description": "Move/resize components ({id, x, y, w?, h?}; w/h null = automatic size), move ports "
                    "along their block border ({id, side: left|right|top|bottom, offset: 0..1}) or route "
                    "connectors ({id, points: [[x, y], ...] | null}). Validated before anything is written.",
     "inputSchema": _schema({"items": {"type": "array", "items": {"type": "object"}}}, ["items"]),
     "handler": tool_set_layout},
    {"name": "sysml_arch_locate",
     "description": "The composition whose canvas view shows an element, and what to select there "
                    "(a component, port or connector; an architecture opens itself).",
     "inputSchema": _schema({"element": _REF}, ["element"]),
     "handler": tool_locate},
    {"name": "sysml_arrange",
     "description": "Auto-layout a composition left to right in layers following connector direction.",
     "inputSchema": _schema({"composition": _REF}, ["composition"]),
     "handler": tool_arrange},
    {"name": "sysml_group",
     "description": "Create Component from Selection: move components into a new inline component "
                    "and re-route crossing connectors through new boundary ports.",
     "inputSchema": _schema({"composition": _REF, "components": _LIST, "name": _S},
                            ["composition", "components"]),
     "handler": tool_group},
    {"name": "sysml_expand",
     "description": "Inverse of sysml_group: move an inline component's children up one level, merge "
                    "connectors through its ports and delete it.",
     "inputSchema": _schema({"component": _REF}, ["component"]),
     "handler": tool_expand},
    {"name": "sysml_save_as_reference",
     "description": "Turn an inline component into a reusable PartDefinition (in the model's package) "
                    "and make the component reference it.",
     "inputSchema": _schema({"component": _REF, "name": _S, "package": _REF}, ["component"]),
     "handler": tool_save_as_reference},
    {"name": "sysml_inline_component",
     "description": "Copy a reference component's definition internals into this component only and "
                    "drop the reference.",
     "inputSchema": _schema({"component": _REF}, ["component"]),
     "handler": tool_inline_component},
    {"name": "sysml_duplicate",
     "description": "Deep-copy components (ports, sub-components, internal connectors, stereotypes) "
                    "into their composition or 'target', with fresh unique names; connectors "
                    "between the copied components are copied too.",
     "inputSchema": _schema({"components": _LIST, "target": _REF}, ["components"]),
     "handler": tool_duplicate},
    {"name": "sysml_delete_elements",
     "description": "Delete components, ports or connectors as one undoable step (connectors that "
                    "depend on them go too).",
     "inputSchema": _schema({"elements": _LIST}, ["elements"]),
     "handler": tool_delete},
    {"name": "sysml_arch_view",
     "description": "Canvas view of a composition: breadcrumbs, boundary ports, components with "
                    "ports and layout, connectors with endpoints, kinds and issues.",
     "inputSchema": _schema({"composition": _REF}, ["composition"]),
     "handler": tool_arch_view},
    {"name": "sysml_arch_tree",
     "description": "Model browser: the component hierarchy under an architecture, through "
                    "reference components, with ports.",
     "inputSchema": _schema({"root": _REF}, ["root"]),
     "handler": tool_arch_tree},
    {"name": "sysml_undo",
     "description": "Undo the last model change (up to 50 steps).",
     "inputSchema": _schema({}, []),
     "handler": tool_undo},
    {"name": "sysml_redo",
     "description": "Redo the last undone change.",
     "inputSchema": _schema({}, []),
     "handler": tool_redo},
]
