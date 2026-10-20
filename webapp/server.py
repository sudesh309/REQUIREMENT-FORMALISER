"""Zero-dependency HTTP backend for the SysML v2 web frontend.

Stdlib only — no FastAPI, Flask, uvicorn, npm, or build pipeline. Boots
in a few hundred ms, serves the SPA, and exposes the engine over a small
JSON-REST API.

Endpoints
---------
GET    /                      → SPA shell (static/index.html)
GET    /static/<path>         → static assets

GET    /api/plugins           → frontend plugin modules to load
GET    /api/state             → repo name + counts
POST   /api/new               → new project    {name, type: system|software}
POST   /api/parse             → parse .sysml   {source}
GET    /api/save              → save → JSON
POST   /api/load              → load from JSON {text}

GET    /api/tree              → containment tree (nested)
GET    /api/element/<id>      → element details + outgoing links
POST   /api/element           → create         {kind, name, parent}
PATCH  /api/element/<id>      → update props   {props}
DELETE /api/element/<id>      → delete

POST   /api/link              → create link    {kind, source, target}
GET    /api/links/<id>        → links touching element
GET    /api/link_kinds        → registry

GET    /api/validate          → severity-tagged issues

GET    /api/diagram/mermaid?kind&target  → Mermaid syntax (live render)
GET    /api/diagram/dot?kind&target      → Graphviz DOT

POST   /api/stereotype/define → {name, applies_to[], tags[]}
POST   /api/stereotype/apply  → {stereotype, target, values}

POST   /api/sm/attach         → {part, name}
POST   /api/sm/state          → {state_machine, name, entry, do, exit, is_initial, is_final}
POST   /api/sm/transition     → {state_machine, source, target, trigger, guard, effect}
POST   /api/sm/fire           → {state_machine, event, payload}
GET    /api/sm/status/<ref>   → current state, trace, structure

GET    /api/export/<format>   → knowledge graph (turtle, json-ld, graphml, cypher)

Feature routes live in ``webapp/routes/*.py`` and register through
``webapp.core.route``; see ``webapp/core.py``.
"""
from __future__ import annotations

import http.server
import json
import re
import socketserver
import sys
import traceback
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from engine import (
    EXPORTERS,
    Repository,
    Validator,
    bdd, bdd_mermaid,
    create_link, describe_link,
    export_knowledge_graph,
    from_json,
    ibd, ibd_mermaid,
    link_kind, links_of, list_link_kinds,
    parse,
    requirements as req_dot, requirements_mermaid,
    state_machine as sm_dot, state_machine_mermaid,
    to_json,
)
from engine.hooks import notify_created
from engine.validator import Severity
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
from sysmlv2.state_machines import (
    StateMachineDefinition, StateMachineRunner,
    attach_state_machine, state_machines_of,
)
from webapp import routes as _route_plugins
from webapp.core import (
    KIND_REGISTRY, PLUGIN_ROUTES, SESSION, Body, Session, apply_props, begin_mutation,
    reset_session, summarize, tree,
)
from webapp.core import err as _err, ok as _ok


STATIC_DIR = Path(__file__).resolve().parent / "static"
PLUGIN_DIR = STATIC_DIR / "plugins"


def api_state(_req: dict) -> Body:
    return _ok({
        "name": SESSION.repo.name,
        "element_count": len(list(SESSION.repo.all_elements())),
        "revision": SESSION.revision,
    })


def api_new(req: dict) -> Body:
    from engine.architecture import ArchitectureError, model_type, set_model_type
    body = req.get("body") or {}
    repo = Repository(name=body.get("name") or "UntitledProject")
    if body.get("type"):            # architecture model type: 'system' (default) or 'software'
        try:
            set_model_type(repo, body["type"])
        except ArchitectureError as ex:
            return _err(str(ex), ex.status)
    SESSION.set_repo(repo)
    return _ok({"name": SESSION.repo.name,
                "root_id": SESSION.repo.root_package.element_id,
                "type": model_type(repo)})


def api_parse(req: dict) -> Body:
    src = (req.get("body") or {}).get("source", "")
    parse(src, into=SESSION.repo.root_package, repo=SESSION.repo)
    SESSION.repo.registry.register_tree(SESSION.repo.root_package)
    return _ok({"element_count": len(list(SESSION.repo.all_elements()))})


def api_save(_req: dict) -> Body:
    return _ok({"text": to_json(SESSION.repo)})


def api_load(req: dict) -> Body:
    text = (req.get("body") or {}).get("text", "")
    SESSION.set_repo(from_json(text))
    return _ok({"name": SESSION.repo.name,
                "element_count": len(list(SESSION.repo.all_elements()))})


def api_tree(_req: dict) -> Body:
    return _ok(tree(SESSION.repo.root_package))


def api_get_element(req: dict, eid: str) -> Body:
    e = SESSION.find(eid)
    if e is None:
        return _err(f"{eid!r} not found", 404)
    summary = summarize(e)
    summary["links"] = [describe_link(r) for r in links_of(e, direction="both")]
    return _ok(summary)


def api_create_element(req: dict) -> Body:
    body = req.get("body") or {}
    cls = KIND_REGISTRY.get(body.get("kind"))
    if cls is None:
        return _err(f"Unknown kind {body.get('kind')!r}")
    parent = SESSION.find(body.get("parent") or "") or SESSION.repo.root_package
    if not isinstance(parent, Namespace):
        n = parent
        while n is not None and not isinstance(n, Namespace):
            n = n.owner
        parent = n or SESSION.repo.root_package
    try:
        elem = cls(name=body.get("name") or "new")
    except TypeError:
        elem = cls()
        elem.name = body.get("name") or "new"
    parent.own(elem)
    SESSION.repo.registry.register_tree(elem)
    notify_created(elem, SESSION.repo)
    if body.get("properties"):
        try:
            apply_props(elem, body["properties"])
        except ValueError as ex:
            SESSION.repo.remove(elem)
            return _err(str(ex))
    return _ok(summarize(elem))


def api_update_element(req: dict, eid: str) -> Body:
    e = SESSION.find(eid)
    if e is None:
        return _err(f"{eid!r} not found", 404)
    try:
        apply_props(e, (req.get("body") or {}).get("props") or {})
    except ValueError as ex:
        return _err(str(ex))
    return _ok(summarize(e))


def api_delete_element(req: dict, eid: str) -> Body:
    e = SESSION.find(eid)
    if e is None:
        return _err(f"{eid!r} not found", 404)
    if e is SESSION.repo.root_package:
        return _err("cannot delete root", 400)
    SESSION.repo.remove(e)
    return _ok({"deleted": eid})


def api_link(req: dict) -> Body:
    body = req.get("body") or {}
    kind, src_ref, tgt_ref = body.get("kind"), body.get("source"), body.get("target")
    if link_kind(kind or "") is None:
        return _err(f"Unknown link kind {kind!r}")
    src, tgt = SESSION.find(src_ref or ""), SESSION.find(tgt_ref or "")
    if src is None or tgt is None:
        return _err("source/target not found", 404)
    rel = create_link(kind, src, tgt)
    SESSION.repo.registry.register(rel)
    return _ok(describe_link(rel))


def api_links(_req: dict, eid: str) -> Body:
    e = SESSION.find(eid)
    if e is None:
        return _err(f"{eid!r} not found", 404)
    return _ok([describe_link(r) for r in links_of(e, direction="both")])


def api_link_kinds(_req: dict) -> Body:
    from engine.links import LINK_KINDS
    return _ok([
        {"name": lk.name, "description": lk.description, "aliases": list(lk.aliases)}
        for lk in LINK_KINDS
    ])


def api_validate(_req: dict) -> Body:
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


def _resolve_diagram_target(kind: str, ref: Optional[str]) -> Element | None:
    if kind in ("ibd", "statemachine"):
        return SESSION.find(ref or "")
    if ref:
        e = SESSION.find(ref)
        return e if isinstance(e, Namespace) else None
    return SESSION.repo.root_package


def _render(kind: str, target: Element, fmt: str) -> str:
    if fmt == "mermaid":
        from engine.diagram_mermaid import (
            bdd_mermaid, ibd_mermaid, requirements_mermaid, state_machine_mermaid,
        )
        if kind == "bdd":          return bdd_mermaid(target)         # type: ignore[arg-type]
        if kind == "ibd":          return ibd_mermaid(target)         # type: ignore[arg-type]
        if kind == "requirements": return requirements_mermaid(target)  # type: ignore[arg-type]
        if kind == "statemachine": return state_machine_mermaid(target)  # type: ignore[arg-type]
    if kind == "bdd":          return bdd(target)
    if kind == "ibd":          return ibd(target)
    if kind == "requirements": return req_dot(target)
    if kind == "statemachine": return sm_dot(target)
    raise ValueError(f"Unknown diagram kind {kind!r}")


def api_diagram(req: dict, fmt: str) -> Body:
    q = req.get("query") or {}
    kind = q.get("kind", "bdd")
    target = _resolve_diagram_target(kind, q.get("target"))
    if target is None:
        return _err("target not found", 404)
    try:
        text = _render(kind, target, fmt)
    except (TypeError, ValueError) as ex:
        return _err(str(ex))
    return _ok({"kind": kind, "format": fmt, "text": text})


def api_export(_req: dict, fmt: str) -> Body:
    if fmt not in EXPORTERS:
        return _err(f"Unknown format {fmt!r}")
    return _ok({"format": fmt,
                "text": export_knowledge_graph(SESSION.repo.root_package, fmt)})


def api_define_stereotype(req: dict) -> Body:
    body = req.get("body") or {}
    applies = []
    for kname in body.get("applies_to") or []:
        cls = KIND_REGISTRY.get(kname)
        if cls is None:
            return _err(f"Unknown applies_to kind {kname!r}")
        applies.append(cls)
    s = Stereotype(name=body["name"], applies_to=applies or None)
    SESSION.repo.root_package.own(s)
    for t in body.get("tags") or []:
        s.define_tag(t["name"], default=t.get("default"))
    SESSION.repo.registry.register_tree(s)
    return _ok(summarize(s))


def api_apply_stereotype(req: dict) -> Body:
    body = req.get("body") or {}
    s = SESSION.find(body.get("stereotype") or "")
    t = SESSION.find(body.get("target") or "")
    if not isinstance(s, Stereotype):
        return _err("stereotype not found", 404)
    if t is None:
        return _err("target not found", 404)
    try:
        app = s.apply(t, body.get("values") or {})
    except (TypeError, KeyError) as ex:
        return _err(str(ex))
    return _ok({"applied": s.name, "to": t.qualified_name, "values": app.values})


def api_sm_attach(req: dict) -> Body:
    body = req.get("body") or {}
    p = SESSION.find(body.get("part") or "")
    if not isinstance(p, PartDefinition):
        return _err("part must be a PartDefinition", 400)
    sm = attach_state_machine(p, body.get("name") or "SM")
    SESSION.repo.registry.register_tree(sm)
    return _ok(summarize(sm))


def _resolve_sm(ref: str) -> StateMachineDefinition | None:
    e = SESSION.find(ref)
    if isinstance(e, StateMachineDefinition):
        return e
    if isinstance(e, PartDefinition):
        sms = state_machines_of(e)
        return sms[0] if sms else None
    return None


def api_sm_state(req: dict) -> Body:
    body = req.get("body") or {}
    sm = _resolve_sm(body.get("state_machine") or "")
    if sm is None:
        return _err("state machine not found", 404)
    s = sm.add_state(
        body["name"],
        entry=body.get("entry"), do=body.get("do"), exit=body.get("exit"),
        is_initial=bool(body.get("is_initial")),
        is_final=bool(body.get("is_final")),
    )
    SESSION.repo.registry.register_tree(s)
    return _ok(summarize(s))


def api_sm_transition(req: dict) -> Body:
    body = req.get("body") or {}
    sm = _resolve_sm(body.get("state_machine") or "")
    if sm is None:
        return _err("state machine not found", 404)
    src = next((s for s in sm.states if s.name == body.get("source")), None)
    tgt = next((s for s in sm.states if s.name == body.get("target")), None)
    if src is None or tgt is None:
        return _err("source/target state not found", 404)
    t = sm.add_transition(src, tgt,
                          trigger=body.get("trigger"),
                          guard=body.get("guard"),
                          effect=body.get("effect"),
                          name=body.get("name"))
    SESSION.repo.registry.register_tree(t)
    return _ok(summarize(t))


def api_sm_fire(req: dict) -> Body:
    body = req.get("body") or {}
    sm = _resolve_sm(body.get("state_machine") or "")
    if sm is None:
        return _err("state machine not found", 404)
    runner = SESSION.runners.setdefault(sm.element_id, sm.runner())
    new = runner.fire(body.get("event") or "", **(body.get("payload") or {}))
    return _ok({
        "current": runner.current.name if runner.current else None,
        "transitioned_to": new.name if new else None,
        "is_in_final": runner.is_in_final(),
        "trace_tail": runner.trace()[-10:],
    })


def api_sm_status(_req: dict, ref: str) -> Body:
    sm = _resolve_sm(ref)
    if sm is None:
        return _err("state machine not found", 404)
    return _ok(summarize(sm))


# ---------------------------------------------------------------------------
# Tiny router.
# ---------------------------------------------------------------------------

def api_plugins(_req: dict) -> Body:
    """Frontend plugin modules the SPA should import, in load order."""
    files = sorted(f.name for f in PLUGIN_DIR.glob("*.js")) if PLUGIN_DIR.is_dir() else []
    return _ok([f"/static/plugins/{name}" for name in files])


ROUTES: list[tuple[str, str, Callable]] = [
    ("GET",    r"^/api/plugins$",                  api_plugins),
    ("GET",    r"^/api/state$",                    api_state),
    ("POST",   r"^/api/new$",                      api_new),
    ("POST",   r"^/api/parse$",                    api_parse),
    ("GET",    r"^/api/save$",                     api_save),
    ("POST",   r"^/api/load$",                     api_load),
    ("GET",    r"^/api/tree$",                     api_tree),
    ("GET",    r"^/api/element/(?P<eid>[^/]+)$",   api_get_element),
    ("POST",   r"^/api/element$",                  api_create_element),
    ("PATCH",  r"^/api/element/(?P<eid>[^/]+)$",   api_update_element),
    ("DELETE", r"^/api/element/(?P<eid>[^/]+)$",   api_delete_element),
    ("POST",   r"^/api/link$",                     api_link),
    ("GET",    r"^/api/links/(?P<eid>[^/]+)$",     api_links),
    ("GET",    r"^/api/link_kinds$",               api_link_kinds),
    ("GET",    r"^/api/validate$",                 api_validate),
    ("GET",    r"^/api/diagram/(?P<fmt>mermaid|dot)$", api_diagram),
    ("GET",    r"^/api/export/(?P<fmt>[a-z\-]+)$", api_export),
    ("POST",   r"^/api/stereotype/define$",        api_define_stereotype),
    ("POST",   r"^/api/stereotype/apply$",         api_apply_stereotype),
    ("POST",   r"^/api/sm/attach$",                api_sm_attach),
    ("POST",   r"^/api/sm/state$",                 api_sm_state),
    ("POST",   r"^/api/sm/transition$",            api_sm_transition),
    ("POST",   r"^/api/sm/fire$",                  api_sm_fire),
    ("GET",    r"^/api/sm/status/(?P<ref>[^/]+)$", api_sm_status),
]


# Route plugins register themselves into PLUGIN_ROUTES on import.
_route_plugins.load_plugins()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "sysmlv2-webapp/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # --- static + SPA ---------------------------------------------------
    def _serve_static(self, rel: str) -> None:
        path = (STATIC_DIR / rel).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            self.send_error(404); return
        ext = path.suffix.lower()
        ct = {
            ".html": "text/html; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".css":  "text/css; charset=utf-8",
            ".svg":  "image/svg+xml",
            ".json": "application/json",
        }.get(ext, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    # --- routing --------------------------------------------------------
    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if method == "GET" and path == "/":
            self._serve_static("index.html"); return
        if method == "GET" and path.startswith("/static/"):
            self._serve_static(path[len("/static/"):]); return
        for verb, pattern, fn in [*ROUTES, *PLUGIN_ROUTES]:
            if verb != method:
                continue
            m = re.match(pattern, path)
            if not m:
                continue
            finish = None
            try:
                body = None
                if method in ("POST", "PATCH", "PUT", "DELETE"):
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b""
                    body = json.loads(raw.decode("utf-8")) if raw else None
                request = {
                    "body":  body,
                    "query": dict(urllib.parse.parse_qsl(parsed.query)),
                }
                if method != "GET":   # undo/redo snapshots (webapp.core.register_mutation_hook)
                    finish = begin_mutation(method, path, body)
                status, payload = fn(request, **m.groupdict()) if m.groupdict() else fn(request)
            except Exception as ex:  # noqa: BLE001
                status, payload = 500, {"error": str(ex),
                                        "traceback": traceback.format_exc()}
            if finish is not None:
                finish(status)
            data = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            # Lets the studio notice any model change, whichever request made it.
            self.send_header("X-Model-Revision", str(SESSION.revision))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_PATCH(self):  self._dispatch("PATCH")
    def do_DELETE(self): self._dispatch("DELETE")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SysML v2 web frontend ready at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
