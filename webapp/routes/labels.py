"""Human-readable undo step labels for every feature's routes.

The Undo / Redo buttons, their tooltips and the Output log name each step,
e.g. "Set Avionics.LRU.mass of FMS", "Allocate ComputeNavigation → CPM1",
"Edit SYS-3 summary", "Assign A429Word to ADIRU.airData". Labels are computed
after the request ran (``webapp.core.LabelContext``): ``ctx.name(ref)`` finds
an element now or, when it was deleted, before the request. A route without a
label gets a generic one ("Edit allocation"), never a route or an id.

New routes register their label next to the route with
``webapp.core.register_undo_label``; the ones below are grouped by feature.
"""
from __future__ import annotations

from typing import Any, Optional

from engine import profiles as P
from engine import requirements as rq
from webapp.core import LabelContext as Ctx
from webapp.core import register_undo_label as label
from webapp.core import session

ARROW = "→"


def _fields(keys: Any, skip: tuple = ()) -> str:
    """'summary, status' from changed body keys."""
    words = [str(k).replace("_", " ") for k in keys if k not in skip]
    return ", ".join(words)


def _kind(kind: Optional[str]) -> str:
    """'PartDefinition' -> 'part definition'."""
    out = ""
    for ch in str(kind or "element"):
        out += (" " + ch.lower()) if ch.isupper() and out else ch.lower()
    return out


def _rename(c: Ctx, ref: Any, new: Any) -> str:
    old = c.old_name(ref)
    return f"Rename {old} to {new}" if old and old != new else f"Rename {c.name(ref)}"


# --- core element editing (webapp/server.py) -------------------------------------

def _create_element(c: Ctx) -> str:
    p = c.payload if isinstance(c.payload, dict) else {}
    return f"Add {_kind(p.get('kind') or c.body.get('kind'))} {c.name(p.get('id'), c.body.get('name') or '')}"


def _edit_element(c: Ctx) -> str:
    props = c.body.get("props") or {}
    eid = c.args["eid"]
    if set(props) == {"name"}:
        return _rename(c, eid, props["name"])
    dotted = [k for k in props if "." in str(k)]
    if len(props) == 1 and dotted:
        return f"Set {dotted[0]} of {c.name(eid)}"
    return f"Edit {c.name(eid)} {_fields(props)}".strip()


label("POST", r"^/api/element$", _create_element)
label("PATCH", r"^/api/element/(?P<eid>[^/]+)$", _edit_element)
label("DELETE", r"^/api/element/(?P<eid>[^/]+)$", lambda c: f"Delete {c.name(c.args['eid'])}")
label("POST", r"^/api/link$",
      lambda c: f"Add «{c.body.get('kind')}» link {c.name(c.body.get('source'))} {ARROW} {c.name(c.body.get('target'))}")
label("POST", r"^/api/parse$", "Import SysML text")
label("POST", r"^/api/stereotype/define$", lambda c: f"Define stereotype {c.body.get('name')}")
label("POST", r"^/api/stereotype/apply$",
      lambda c: f"Apply «{c.name(c.body.get('stereotype'))}» to {c.name(c.body.get('target'))}")
label("POST", r"^/api/sm/attach$",
      lambda c: f"Add state machine {c.body.get('name') or 'SM'} to {c.name(c.body.get('part'))}")
label("POST", r"^/api/sm/state$", lambda c: f"Add state {c.body.get('name')}")
label("POST", r"^/api/sm/transition$",
      lambda c: f"Add transition {c.body.get('source')} {ARROW} {c.body.get('target')}")


# --- architecture (webapp/routes/architecture.py) --------------------------------

def _edit_component(c: Ctx) -> str:
    eid = c.args["eid"]
    if "definition" in c.body:
        d = c.body.get("definition")
        return f"Make {c.name(eid)} reference {c.name(d)}" if d else f"Make {c.name(eid)} inline"
    if c.body.get("name") is not None:
        return _rename(c, eid, c.body["name"])
    return f"Edit {c.name(eid)}"


def _edit_port(c: Ctx) -> str:
    eid, b = c.args["eid"], c.body
    if b.get("name") is not None and len([k for k in b if k != "force"]) == 1:
        return _rename(c, eid, b["name"])
    if "interface" in b:
        return (f"Assign {c.name(b['interface'])} to {c.port(eid)}" if b["interface"]
                else f"Remove interface from {c.port(eid)}")
    if b.get("direction"):
        return f"Set {c.port(eid)} direction to {b['direction']}"
    if b.get("kind"):
        return f"Set {c.port(eid)} kind to {b['kind']}"
    return f"Edit port {c.port(eid)}"


def _end(c: Ctx, ep: Any) -> str:
    if not isinstance(ep, dict):
        return "port"
    comp, port = ep.get("component_id"), ep.get("port_id")
    if port and comp:
        return f"{c.name(comp)}.{c.name(port)}"
    return c.name(port or comp, "port")


def _connect(c: Ctx) -> str:
    p = c.payload if isinstance(c.payload, dict) else {}
    return f"Connect {_end(c, p.get('source'))} {ARROW} {_end(c, p.get('target'))}"


def _edit_connector(c: Ctx) -> str:
    eid = c.args["eid"]
    if c.body.get("name") is not None:
        return _rename(c, eid, c.body["name"])
    if "points" in c.body:
        return f"Reset route of {c.name(eid)}" if c.body["points"] is None else f"Route {c.name(eid)}"
    return f"Edit {c.name(eid)}"


def _duplicate(c: Ctx) -> str:
    what = c.names(c.body.get("ids"))
    target = c.body.get("target")
    return f"Paste {what} into {c.name(target)}" if target else f"Duplicate {what}"


def _group(c: Ctx) -> str:
    return f"Group {c.names(c.body.get('component_ids'))} into {c.name(c.pid(), 'a component')}"


def _save_ref(c: Ctx) -> str:
    p = c.payload if isinstance(c.payload, dict) else {}
    d = (p.get("definition") or {}).get("id")
    return f"Save {c.name(c.body.get('component'))} as reference {c.name(d, 'definition')}"


# "New architecture", "Arrange" and "Move" stay short: the canvas tests of the architecture
# feature name these steps so.
label("POST", r"^/api/arch/architecture$", "New architecture")
label("POST", r"^/api/arch/model-type$", lambda c: f"Change model type to {c.body.get('type')}")
label("POST", r"^/api/arch/component$", lambda c: f"Add component {c.name(c.pid())}")
label("PATCH", r"^/api/arch/component/(?P<eid>[^/]+)$", _edit_component)
label("POST", r"^/api/arch/delete$", lambda c: f"Delete {c.names(c.body.get('ids'))}")
label("POST", r"^/api/arch/duplicate$", _duplicate)
label("POST", r"^/api/arch/group$", _group)
label("POST", r"^/api/arch/expand$", lambda c: f"Expand {c.name(c.body.get('component'))}")
label("POST", r"^/api/arch/save-as-reference$", _save_ref)
label("POST", r"^/api/arch/inline$", lambda c: f"Make {c.name(c.body.get('component'))} inline")
label("POST", r"^/api/arch/port$", lambda c: f"Add port {c.port(c.pid())}")
label("PATCH", r"^/api/arch/port/(?P<eid>[^/]+)$", _edit_port)
label("POST", r"^/api/arch/connector$", _connect)
label("PATCH", r"^/api/arch/connector/(?P<eid>[^/]+)$", _edit_connector)
label("POST", r"^/api/arch/auto-layout$", "Arrange")
label("POST", r"^/api/arch/layout$", "Move")


# --- interfaces (webapp/routes/interfaces.py) ------------------------------------

def _item(c: Ctx) -> str:
    return c.name(c.args.get("ref"), "interface")


def _iface_element(c: Ctx) -> str:
    return f"{_item(c)}.{c.name(c.args.get('el'), 'element')}"


def _edit_item(c: Ctx) -> str:
    if set(c.body) == {"name"}:
        return _rename(c, c.args["ref"], c.body["name"])
    return f"Edit {_item(c)} {_fields(c.body)}".strip()


def _edit_iface_element(c: Ctx) -> str:
    if set(c.body) == {"name"}:
        old = c.old_name(c.args["el"])
        return f"Rename {_item(c)}.{old} to {c.body['name']}" if old else f"Rename {_iface_element(c)}"
    return f"Edit {_iface_element(c)} {_fields(c.body)}".strip()


def _assign(c: Ctx) -> str:
    port, iface = c.port(c.body.get("port")), c.body.get("interface")
    if iface is None:
        return f"Remove interface from {port}"
    if iface == "owned":
        return f"Give {port} an owned interface"
    return f"Assign {c.name(iface, 'interface')} to {port}"


def _new_item(c: Ctx) -> str:
    p = c.payload if isinstance(c.payload, dict) else {}
    return f"Add {_kind(p.get('kind'))} {c.name(p.get('id'), p.get('name') or '')}"


def _iface_connect(c: Ctx) -> str:
    return f"Connect {c.port(c.body.get('source'))} {ARROW} {c.port(c.body.get('target'))}"


label("POST", r"^/api/interfaces$", _new_item)
label("PATCH", r"^/api/interfaces/item/(?P<ref>[^/]+)$", _edit_item)
label("DELETE", r"^/api/interfaces/item/(?P<ref>[^/]+)$", lambda c: f"Delete {_item(c)}")
label("POST", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements$",
      lambda c: f"Add element {_item(c)}.{c.name((c.pid('element') or {}).get('id'), 'element')}")
label("PATCH", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)$", _edit_iface_element)
label("DELETE", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)$",
      lambda c: f"Delete {_iface_element(c)}")
label("POST", r"^/api/interfaces/item/(?P<ref>[^/]+)/elements/(?P<el>[^/]+)/move$",
      lambda c: f"Reorder {_iface_element(c)}")
label("POST", r"^/api/interfaces/assign$", _assign)
label("POST", r"^/api/interfaces/make-shared$",
      lambda c: f"Share the interface of {c.port(c.body.get('port'))}")
label("POST", r"^/api/interfaces/make-owned$",
      lambda c: f"Make the interface of {c.port(c.body.get('port'))} owned")
label("POST", r"^/api/interfaces/move-owned$", "Move owned interfaces to the dictionary")
label("POST", r"^/api/interfaces/connect$", _iface_connect)
label("POST", r"^/api/interfaces/connector-elements$",
      lambda c: f"Map the interface elements of {c.name(c.body.get('connector'), 'connector')}")
label("POST", r"^/api/interfaces/dictionary/import$", "Import interface dictionary")
label("POST", r"^/api/interfaces/adapter$", lambda c: f"Add adapter {c.name(c.pid(), 'Adapter')}")
label("PATCH", r"^/api/interfaces/adapter/(?P<ref>[^/]+)$",
      lambda c: f"Edit the mappings of {c.name(c.args['ref'], 'adapter')}")


# --- profiles (webapp/routes/profiles.py) ----------------------------------------

def _repo():
    return session().repo


def _stereo(c: Ctx, ref: Any) -> str:
    """'Avionics.LRU' (the profiles feature's name for a stereotype)."""
    try:
        return P.find_stereotype(_repo(), ref).full_name
    except Exception:          # noqa: BLE001 - deleted or unknown: fall back to the name
        return c.name(ref, "stereotype")


def _set_values(c: Ctx) -> str:
    values = dict(c.body.get("values") or {})
    if "property" in c.body:
        values[c.body["property"]] = c.body.get("value")
    who = c.name(c.args["eid"])
    if len(values) == 1:
        return f"Set {next(iter(values))} of {who}"
    return f"Set {len(values)} stereotype values of {who}"


def _reset_values(c: Ctx) -> str:
    paths = list(c.body.get("properties") or [])
    if c.body.get("property"):
        paths.append(c.body["property"])
    who = c.name(c.args["eid"])
    if len(paths) == 1:
        return f"Reset {paths[0]} of {who} to the inherited value"
    return f"Reset {len(paths)} stereotype values of {who} to the inherited values"


def _property(c: Ctx) -> str:
    try:
        tag = P.find_property(_repo(), c.args["prop"], P.find_stereotype(_repo(), c.args["ref"]))
        return f"{tag.stereotype.full_name}.{tag.name}"
    except Exception:          # noqa: BLE001
        return f"{_stereo(c, c.args['ref'])}.{c.name(c.args['prop'], 'property')}"


def _batch(c: Ctx) -> str:
    n = c.payload.get("count") if isinstance(c.payload, dict) else None
    return f"Apply «{_stereo(c, c.args['ref'])}» to {n if n is not None else 'several'} element(s)"


label("POST", r"^/api/profiles$", lambda c: f"Add profile {c.name(c.pid())}")
label("POST", r"^/api/profiles/import$",
      lambda c: f"Import profile {((c.pid('profile') or {}).get('name')) or ''}")
label("PATCH", r"^/api/profiles/(?P<ref>[^/]+)$",
      lambda c: (_rename(c, c.args["ref"], c.body["name"]) if set(c.body) == {"name"}
                 else f"Edit profile {c.name(c.args['ref'])} {_fields(c.body)}"))
label("DELETE", r"^/api/profiles/(?P<ref>[^/]+)$", lambda c: f"Delete profile {c.name(c.args['ref'])}")
label("POST", r"^/api/profiles/(?P<ref>[^/]+)/stereotypes$",
      lambda c: f"Add stereotype {_stereo(c, c.pid())}")
label("PATCH", r"^/api/stereotypes/(?P<ref>[^/]+)$",
      lambda c: f"Edit stereotype {_stereo(c, c.args['ref'])} {_fields(c.body, ('force',))}")
label("DELETE", r"^/api/stereotypes/(?P<ref>[^/]+)$",
      lambda c: f"Delete stereotype {c.name(c.args['ref'])}")
label("POST", r"^/api/stereotypes/(?P<ref>[^/]+)/properties$",
      lambda c: f"Add property {_stereo(c, c.args['ref'])}.{c.pid('name') or ''}")
label("PATCH", r"^/api/stereotypes/(?P<ref>[^/]+)/properties/(?P<prop>[^/]+)$",
      lambda c: f"Edit property {_property(c)} {_fields(c.body, ('force',))}")
label("DELETE", r"^/api/stereotypes/(?P<ref>[^/]+)/properties/(?P<prop>[^/]+)$",
      lambda c: f"Delete property {_stereo(c, c.args['ref'])}.{c.name(c.args['prop'], 'property')}")
label("POST", r"^/api/stereotypes/(?P<ref>[^/]+)/batch$", _batch)
label("POST", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$",
      lambda c: f"Apply «{_stereo(c, c.body.get('stereotype'))}» to {c.name(c.args['eid'])}")
label("PATCH", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$", _set_values)
label("POST", r"^/api/elements/(?P<eid>[^/]+)/stereotypes/reset$", _reset_values)
label("DELETE", r"^/api/elements/(?P<eid>[^/]+)/stereotypes$",
      lambda c: f"Remove all stereotypes from {c.name(c.args['eid'])}")
label("DELETE", r"^/api/elements/(?P<eid>[^/]+)/stereotypes/(?P<ref>[^/]+)$",
      lambda c: f"Remove «{_stereo(c, c.args['ref'])}» from {c.name(c.args['eid'])}")


# --- requirements (webapp/routes/requirements.py) --------------------------------

def _req_name(c: Ctx, ref: Any) -> str:
    return c.old_name(ref) or c.name(ref, "requirement")


def _edit_requirement(c: Ctx) -> str:
    return f"Edit {_req_name(c, c.args['rid'])} {_fields(c.body)}".strip()


def _trace(c: Ctx) -> str:
    try:
        verb = rq.trace_type(c.body.get("type")).verb
    except Exception:          # noqa: BLE001
        verb = "links to"
    return f"Add link {c.name(c.body.get('source'))} {verb} {c.name(c.body.get('target'))}"


def _trace_batch(c: Ctx) -> str:
    n = len((c.payload or {}).get("created") or []) if isinstance(c.payload, dict) else 0
    end = c.body.get("target") or c.body.get("source")
    return f"Add {n} {c.body.get('type') or 'trace'} link(s) to {c.name(end)}"


def _delete_link(c: Ctx) -> str:
    d = c.old(c.args["lid"])
    if d and d.get("source") and d.get("target"):
        return f"Delete link {c.name(d['source'])} {ARROW} {c.name(d['target'])}"
    return "Delete trace link"


label("POST", r"^/api/req/sets$", lambda c: f"Add requirement set {c.name(c.pid())}")
label("PATCH", r"^/api/req/sets/(?P<sid>[^/]+)$",
      lambda c: f"Edit requirement set {c.old_name(c.args['sid']) or c.name(c.args['sid'])} {_fields(c.body)}")
label("POST", r"^/api/req/requirements$",
      lambda c: f"Add requirement {(c.payload or {}).get('req_id') or c.name(c.pid())}")
label("PATCH", r"^/api/req/requirements/(?P<rid>[^/]+)$", _edit_requirement)
label("DELETE", r"^/api/req/requirements/(?P<rid>[^/]+)$",
      lambda c: f"Delete requirement {_req_name(c, c.args['rid'])}")
label("POST", r"^/api/req/requirements/(?P<rid>[^/]+)/move$",
      lambda c: f"Move {_req_name(c, c.args['rid'])} {c.body.get('direction') or ''}")
label("POST", r"^/api/req/test-cases$", lambda c: f"Add test case {c.name(c.pid())}")
label("PATCH", r"^/api/req/test-cases/(?P<tid>[^/]+)$",
      lambda c: f"Edit test case {c.old_name(c.args['tid']) or c.name(c.args['tid'])} {_fields(c.body)}")
label("DELETE", r"^/api/req/test-cases/(?P<tid>[^/]+)$",
      lambda c: f"Delete test case {c.name(c.args['tid'])}")
label("POST", r"^/api/req/links$", _trace)
label("POST", r"^/api/req/links/batch$", _trace_batch)
label("DELETE", r"^/api/req/links/(?P<lid>[^/]+)$", _delete_link)
label("POST", r"^/api/req/links/(?P<lid>[^/]+)/clear-suspect$", "Clear suspect link")
label("POST", r"^/api/req/clear-suspect$",
      lambda c: f"Clear suspect links of {c.name(c.body['element'])}" if c.body.get("element")
      else "Clear all suspect links")
label("POST", r"^/api/req/import$", lambda c: f"Import requirements ({c.body.get('format') or 'file'})")


# --- allocation (webapp/routes/allocation.py) ------------------------------------

def _pair(c: Ctx) -> str:
    return f"{c.name(c.body.get('source'))} {ARROW} {c.name(c.body.get('target'))}"


def _toggle(c: Ctx) -> str:
    on = isinstance(c.payload, dict) and c.payload.get("allocated")
    return f"Allocate {_pair(c)}" if on else f"Remove allocation {_pair(c)}"


def _deallocate(c: Ctx) -> str:
    if c.body.get("allocation"):
        d = c.old(c.body["allocation"])
        return f"Remove allocation {d.get('name')}" if d and d.get("name") else "Remove allocation"
    return f"Remove allocation {_pair(c)}"


label("POST", r"^/api/allocation/sets$", lambda c: f"Add allocation set {c.name(c.pid())}")
label("PATCH", r"^/api/allocation/sets/(?P<sid>[^/]+)$",
      lambda c: f"Edit allocation set {c.old_name(c.args['sid']) or c.name(c.args['sid'])} {_fields(c.body, ('force',))}")
label("DELETE", r"^/api/allocation/sets/(?P<sid>[^/]+)$",
      lambda c: f"Delete allocation set {c.name(c.args['sid'])}")
label("POST", r"^/api/allocation/sets/(?P<sid>[^/]+)/scenarios$",
      lambda c: f"Add scenario {c.name(c.pid())}")
label("POST", r"^/api/allocation/scenarios$", lambda c: f"Add scenario {c.name(c.pid())}")
label("PATCH", r"^/api/allocation/scenarios/(?P<sid>[^/]+)$",
      lambda c: (_rename(c, c.args["sid"], c.body["name"]) if set(c.body) == {"name"}
                 else f"Edit scenario {c.name(c.args['sid'])}"))
label("DELETE", r"^/api/allocation/scenarios/(?P<sid>[^/]+)$",
      lambda c: f"Delete scenario {c.name(c.args['sid'])}")
label("POST", r"^/api/allocation/scenarios/(?P<sid>[^/]+)/duplicate$",
      lambda c: f"Duplicate scenario {c.name(c.args['sid'])}")
label("POST", r"^/api/allocation/allocate$", lambda c: f"Allocate {_pair(c)}")
label("POST", r"^/api/allocation/deallocate$", _deallocate)
label("POST", r"^/api/allocation/toggle$", _toggle)


# --- interop (webapp/routes/interop.py) ------------------------------------------

def _import(what: str):
    def fn(c: Ctx) -> str:
        new = c.body.get("mode") == "new"
        return f"Import {what} as a new project" if new else f"Import {what}"
    return fn


label("POST", r"^/api/interop/tables/import$", _import("model tables"))
label("POST", r"^/api/interop/sysml/import$", _import("SysML text"))
label("POST", r"^/api/interop/xmi/import$", _import("XMI"))
label("POST", r"^/api/interop/merge/resolve$", "Merge model")
