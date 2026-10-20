"""HTTP API for import / export, reports, comparison, merge and Model Check.

Binary files travel as base64 inside JSON (the API only speaks JSON); uploads
are accepted as content, never as server-side paths.

GET  /api/interop/info                      report sections, table names, parser capabilities
GET  /api/interop/tables?format=xlsx|csv|json   export tables -> {filename, mime, base64} | {tables}
POST /api/interop/tables/import             {base64, filename | tables, mode: merge|new, name?}
GET  /api/interop/report?title&author&sections&mermaid   -> {html, filename}
GET  /api/interop/sysml                     SysML v2 text -> {text, filename}
POST /api/interop/sysml/import              {text, mode: merge|new, name?}
POST /api/interop/xmi/import                {text | base64, mode: merge|new, name?}
POST /api/interop/snapshot                  remember the current project (e.g. "last saved")
GET  /api/interop/snapshot                  the remembered snapshot's label / size
POST /api/interop/compare                   {text | base64 + filename | against: "snapshot"}
POST /api/interop/merge                     {base, theirs, mine?} -> {token, conflicts, auto, ...}
POST /api/interop/merge/resolve             {token, choices: {id: mine|theirs}, default?}
GET  /api/interop/check?severity=&rule=     Model Check (validator + advisor checks)
"""
from __future__ import annotations

import base64
import binascii
import time
import uuid
from typing import Any, Optional

from engine.interop import InteropError
from engine.interop import checks as _checks  # noqa: F401  (registers the advisor rules)
from engine.interop.checks import run_model_check
from engine.interop.diff import compare, merge_to_repo, project_data, three_way_merge
from engine.interop.report import SECTIONS, generate_report
from engine.interop.sysml_export import export_sysml, import_sysml, parser_capabilities
from engine.interop.tables import (
    TABLE_ORDER, export_tables, export_tables_file, import_tables, read_tables_file,
    tables_to_project,
)
from engine.interop.common import safe_filename
from engine.interop.xmi_import import import_xmi, xmi_to_project
from engine.parser import ParseError
from webapp.core import err, ok, route, session

MAX_UPLOAD_BYTES = 48 * 1024 * 1024


def _state() -> dict:
    return session().plugin_state.setdefault("interop", {})


def _body(req: dict) -> dict:
    body = req.get("body")
    return body if isinstance(body, dict) else {}


def _decode(body: dict) -> Optional[bytes]:
    data = body.get("base64")
    if data in (None, ""):
        return None
    if not isinstance(data, str):
        raise InteropError("base64 must be a string")
    if "," in data[:100] and data.startswith("data:"):
        data = data.split(",", 1)[1]
    if len(data) > MAX_UPLOAD_BYTES * 4 // 3 + 16:
        raise InteropError("upload is too large")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise InteropError("upload is not valid base64") from None


def _project_summary() -> dict:
    repo = session().repo
    return {"name": repo.name, "root_id": repo.root_package.element_id,
            "element_count": len(list(repo.all_elements()))}


def _mode(body: dict) -> str:
    mode = body.get("mode") or "merge"
    if mode not in ("merge", "new"):
        raise InteropError("mode must be 'merge' (into the current project) or 'new'")
    return mode


def _guard(fn):
    """Turn user-facing errors into 400 responses with the message."""
    def wrapper(req: dict, **kw: Any):
        try:
            return fn(req, **kw)
        except (InteropError, ParseError) as ex:
            return err(str(ex), 400)
        except (ValueError, KeyError) as ex:
            return err(str(ex).strip("'\""), 400)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# --- info -------------------------------------------------------------------------

@route("GET", r"^/api/interop/info$")
@_guard
def api_info(_req: dict):
    return ok({"report_sections": list(SECTIONS), "tables": list(TABLE_ORDER),
               "parser_capabilities": parser_capabilities(),
               "snapshot": _snapshot_info()})


# --- tables -----------------------------------------------------------------------

@route("GET", r"^/api/interop/tables$")
@_guard
def api_export_tables(req: dict):
    fmt = (req.get("query") or {}).get("format", "xlsx")
    repo = session().repo
    if fmt == "json":
        return ok({"format": "json", "tables": export_tables(repo)})
    data, filename, mime = export_tables_file(repo, fmt)
    return ok({"format": fmt, "filename": filename, "mime": mime,
               "base64": base64.b64encode(data).decode("ascii"), "size": len(data)})


def _tables_from(body: dict):
    data = _decode(body)
    if data is not None:
        return read_tables_file(data, body.get("filename") or "")
    if isinstance(body.get("tables"), (dict, list)):
        return body["tables"]
    raise InteropError("send the file as base64 (with its filename) or the tables as JSON")


@route("POST", r"^/api/interop/tables/import$")
@_guard
def api_import_tables(req: dict):
    body = _body(req)
    mode = _mode(body)
    sheets = _tables_from(body)
    if mode == "new":
        repo, report = tables_to_project(sheets, body.get("name") or None)
        session().set_repo(repo)
    else:
        report = import_tables(session().repo, sheets)
    return ok({"mode": mode, "report": report.to_dict(), "project": _project_summary()})


# --- report -----------------------------------------------------------------------

@route("GET", r"^/api/interop/report$")
@_guard
def api_report(req: dict):
    q = req.get("query") or {}
    sections = [s for s in (q.get("sections") or "").split(",") if s] or None
    html = generate_report(session().repo, title=q.get("title") or None,
                           author=q.get("author") or "", sections=sections,
                           mermaid=q.get("mermaid") or "link")
    name = safe_filename(session().repo.name)
    return ok({"html": html, "filename": f"{name}_report.html", "size": len(html)})


# --- SysML v2 text -----------------------------------------------------------------

@route("GET", r"^/api/interop/sysml$")
@_guard
def api_export_sysml(_req: dict):
    repo = session().repo
    return ok({"text": export_sysml(repo), "filename": f"{safe_filename(repo.name)}.sysml",
               "parser_capabilities": parser_capabilities()})


def _clone(repo):
    from engine.serializer import from_dict, to_dict
    return from_dict(to_dict(repo))


@route("POST", r"^/api/interop/sysml/import$")
@_guard
def api_import_sysml(req: dict):
    from engine.repository import Repository
    body = _body(req)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise InteropError("text (SysML v2 source) is required")
    mode = _mode(body)
    if mode == "new":
        repo = Repository(name=body.get("name") or "ImportedText")
        created = import_sysml(repo, text)
        session().set_repo(repo)
    else:
        import_sysml(_clone(session().repo), text)      # rehearsal: a syntax error changes nothing
        created = import_sysml(session().repo, text)
    return ok({"mode": mode, "created": len(created),
               "created_ids": [e.element_id for e in created], "project": _project_summary()})


# --- XMI ---------------------------------------------------------------------------

@route("POST", r"^/api/interop/xmi/import$")
@_guard
def api_import_xmi(req: dict):
    body = _body(req)
    data = _decode(body)
    if data is None:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise InteropError("send the XMI file as text or base64")
        data = text.encode("utf-8")
    mode = _mode(body)
    if mode == "new":
        repo, report = xmi_to_project(data, body.get("name") or None)
        session().set_repo(repo)
    else:
        report = import_xmi(session().repo, data, wrap=body.get("wrap", True) is not False)
    return ok({"mode": mode, "report": report.to_dict(), "project": _project_summary()})


# --- snapshots and comparison ------------------------------------------------------------

def _snapshot_info() -> Optional[dict]:
    snap = _state().get("snapshot")
    if not snap:
        return None
    return {"label": snap["label"], "taken": snap["taken"], "name": snap["data"].get("name"),
            "elements": len(snap["data"].get("elements", []))}


@route("POST", r"^/api/interop/snapshot$")
@_guard
def api_take_snapshot(req: dict):
    from engine.serializer import to_dict
    body = _body(req)
    _state()["snapshot"] = {"label": str(body.get("label") or "Last saved"),
                            "taken": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "data": to_dict(session().repo)}
    return ok(_snapshot_info())


@route("GET", r"^/api/interop/snapshot$")
@_guard
def api_get_snapshot(_req: dict):
    info = _snapshot_info()
    return ok(info if info else {"exists": False})


def _other_project(body: dict) -> tuple[dict, str]:
    """The project to compare with: uploaded JSON / tables, or the snapshot."""
    if body.get("against") == "snapshot":
        snap = _state().get("snapshot")
        if not snap:
            raise InteropError("no snapshot yet: save the project (or take a snapshot) first")
        return snap["data"], snap["label"]
    filename = str(body.get("filename") or "")
    data = _decode(body)
    if data is not None and (filename.lower().endswith((".xlsx", ".zip")) or data[:2] == b"PK"):
        repo, _report = tables_to_project(read_tables_file(data, filename))
        from engine.serializer import to_dict
        return to_dict(repo), filename or "tables"
    text = body.get("text")
    if data is not None:
        text = data.decode("utf-8-sig", errors="replace")
    if not isinstance(text, (str, dict)) or not text:
        raise InteropError("send a project JSON (text), a tables file (base64) or "
                           "against='snapshot'")
    return project_data(text), filename or "file"


@route("POST", r"^/api/interop/compare$")
@_guard
def api_compare(req: dict):
    body = _body(req)
    other, label = _other_project(body)
    diff = compare(other, session().repo, include_layout=bool(body.get("include_layout")),
                   old_label=label, new_label="current project")
    return ok(diff)


# --- three-way merge --------------------------------------------------------------------

def _merge_input(body: dict, key: str) -> Any:
    value = body.get(key)
    if isinstance(value, dict) and ("base64" in value or "text" in value):
        sub = value
        data = _decode(sub)
        if data is not None and (data[:2] == b"PK"):
            repo, _ = tables_to_project(read_tables_file(data, sub.get("filename") or ""))
            return repo
        value = data.decode("utf-8-sig") if data is not None else sub.get("text")
    if value in (None, "") and key == "mine":
        return session().repo
    if value in (None, ""):
        raise InteropError(f"{key} project is required")
    return value


@route("POST", r"^/api/interop/merge$")
@_guard
def api_merge(req: dict):
    body = _body(req)
    result = three_way_merge(_merge_input(body, "base"), _merge_input(body, "theirs"),
                             _merge_input(body, "mine"))
    token = uuid.uuid4().hex
    merges = _state().setdefault("merges", {})
    merges.clear()                                 # keep only the latest merge
    merges[token] = result
    return ok({"token": token, **result.to_dict()})


@route("POST", r"^/api/interop/merge/resolve$")
@_guard
def api_merge_resolve(req: dict):
    body = _body(req)
    result = _state().get("merges", {}).get(body.get("token") or "")
    if result is None:
        raise InteropError("unknown or expired merge: run the merge again")
    choices = body.get("choices") or {}
    if not isinstance(choices, dict):
        raise InteropError("choices must map conflict ids to 'mine' or 'theirs'")
    repo = merge_to_repo(result, choices, body.get("default") or "mine")
    notes = list(getattr(result, "resolved_notes", []) or [])
    session().set_repo(repo)
    return ok({"project": _project_summary(), "notes": notes,
               "conflicts_resolved": len(result.conflicts)})


# --- Model Check ---------------------------------------------------------------------------

@route("GET", r"^/api/interop/check$")
@_guard
def api_check(req: dict):
    q = req.get("query") or {}
    sev = [s for s in (q.get("severity") or "").split(",") if s] or None
    rules = [s for s in (q.get("rule") or "").split(",") if s] or None
    return ok(run_model_check(session().repo, severities=sev, rules=rules))
