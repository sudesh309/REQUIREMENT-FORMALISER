"""MCP tools for import / export, reports, comparison, merge and Model Check.

File paths are read and written only where a tool takes a ``path`` argument (as
``sysml_open_project`` / ``sysml_save_project`` do); every tool also works on
content passed inline.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Optional

from engine.interop import InteropError
from engine.interop import checks as _checks  # noqa: F401  (registers the advisor rules)
from engine.interop.checks import run_model_check
from engine.interop.diff import compare, merge_to_repo, three_way_merge
from engine.interop.report import generate_report
from engine.interop.sysml_export import export_sysml, import_sysml
from engine.interop.tables import (
    export_tables, export_tables_file, import_tables, read_tables_file, tables_to_project,
)
from engine.interop.xmi_import import import_xmi, xmi_to_project
from engine.parser import ParseError
from mcp_server.core import SESSION, _err, _ok


def _summary() -> dict:
    repo = SESSION.repo
    return {"name": repo.name, "element_count": len(list(repo.all_elements()))}


def _safe(fn):
    def wrapper(**kwargs: Any) -> dict:
        try:
            return fn(**kwargs)
        except (InteropError, ParseError, ValueError, KeyError, OSError) as ex:
            return _err(str(ex))
    wrapper.__name__ = fn.__name__
    return wrapper


def _read_project(path: Optional[str], text: Optional[str], what: str) -> Any:
    """A project from a JSON file, inline JSON, or a tables file (.xlsx / .zip)."""
    if path:
        p = Path(path)
        if p.suffix.lower() in (".xlsx", ".zip"):
            repo, _ = tables_to_project(read_tables_file(p.read_bytes(), p.name))
            return repo
        return p.read_text(encoding="utf-8")
    if text:
        return text
    raise InteropError(f"{what}: give a path or the project JSON")


@_safe
def tool_export_tables(format: str = "xlsx", path: Optional[str] = None) -> dict:
    if format == "json":
        tables = export_tables(SESSION.repo)
        if path:
            Path(path).write_text(json.dumps(tables, indent=2), encoding="utf-8")
            return _ok({"path": path, "format": "json"})
        return _ok({"format": "json", "tables": tables})
    data, filename, _mime = export_tables_file(SESSION.repo, format)
    if path:
        Path(path).write_bytes(data)
        return _ok({"path": path, "format": format, "size": len(data)})
    return _ok({"format": format, "filename": filename,
                "base64": base64.b64encode(data).decode("ascii")})


@_safe
def tool_import_tables(path: Optional[str] = None, tables: Optional[dict] = None,
                       base64_data: Optional[str] = None, mode: str = "merge",
                       name: Optional[str] = None) -> dict:
    if path:
        p = Path(path)
        sheets: Any = (json.loads(p.read_text(encoding="utf-8")) if p.suffix.lower() == ".json"
                       else read_tables_file(p.read_bytes(), p.name))
    elif base64_data:
        sheets = read_tables_file(base64.b64decode(base64_data), "")
    elif tables:
        sheets = tables
    else:
        raise InteropError("give a path, base64_data or tables")
    if mode == "new":
        repo, report = tables_to_project(sheets, name)
        SESSION.set_repo(repo)
    elif mode == "merge":
        report = import_tables(SESSION.repo, sheets)
    else:
        raise InteropError("mode must be 'merge' or 'new'")
    return _ok({"mode": mode, "report": report.to_dict(), "project": _summary()})


@_safe
def tool_generate_report(path: Optional[str] = None, title: Optional[str] = None,
                         author: str = "", sections: Optional[list] = None,
                         mermaid: Optional[str] = None) -> dict:
    html = generate_report(SESSION.repo, title=title, author=author, sections=sections,
                           mermaid=mermaid or ("inline" if path else "link"))
    if path:
        Path(path).write_text(html, encoding="utf-8")
        return _ok({"path": path, "size": len(html)})
    return _ok({"html": html})


@_safe
def tool_compare_projects(other_path: Optional[str] = None, other_json: Optional[str] = None,
                          current_path: Optional[str] = None,
                          include_layout: bool = False) -> dict:
    other = _read_project(other_path, other_json, "other project")
    current = _read_project(current_path, None, "current") if current_path else SESSION.repo
    diff = compare(other, current, include_layout=include_layout,
                   old_label=other_path or "other", new_label=current_path or "current project")
    diff.pop("tree", None)          # the flat change list carries the same information
    return _ok(diff)


@_safe
def tool_merge_projects(base_path: Optional[str] = None, theirs_path: Optional[str] = None,
                        mine_path: Optional[str] = None, base_json: Optional[str] = None,
                        theirs_json: Optional[str] = None, choices: Optional[dict] = None,
                        default: str = "mine", apply: bool = True,
                        out_path: Optional[str] = None) -> dict:
    base = _read_project(base_path, base_json, "base")
    theirs = _read_project(theirs_path, theirs_json, "theirs")
    mine = _read_project(mine_path, None, "mine") if mine_path else SESSION.repo
    result = three_way_merge(base, theirs, mine)
    out = result.to_dict()
    if apply or out_path:
        repo = merge_to_repo(result, choices or {}, default)
        out["notes"] = list(getattr(result, "resolved_notes", []) or [])
        if out_path:
            from engine import to_json
            Path(out_path).write_text(to_json(repo), encoding="utf-8")
            out["out_path"] = out_path
        if apply:
            SESSION.set_repo(repo)
            out["project"] = _summary()
    out["applied"] = bool(apply)
    return _ok(out)


@_safe
def tool_export_sysml_text(path: Optional[str] = None) -> dict:
    text = export_sysml(SESSION.repo)
    if path:
        Path(path).write_text(text, encoding="utf-8")
        return _ok({"path": path, "size": len(text)})
    return _ok({"text": text})


@_safe
def tool_import_sysml_text(text: Optional[str] = None, path: Optional[str] = None,
                           mode: str = "merge", name: Optional[str] = None) -> dict:
    from engine.repository import Repository
    from engine.serializer import from_dict, to_dict
    source = Path(path).read_text(encoding="utf-8") if path else text
    if not source:
        raise InteropError("give text or a path")
    if mode == "new":
        repo = Repository(name=name or "ImportedText")
        created = import_sysml(repo, source)
        SESSION.set_repo(repo)
    else:
        import_sysml(from_dict(to_dict(SESSION.repo)), source)     # rehearsal
        created = import_sysml(SESSION.repo, source)
    return _ok({"mode": mode, "created": len(created), "project": _summary()})


@_safe
def tool_import_xmi(path: Optional[str] = None, text: Optional[str] = None,
                    mode: str = "new", name: Optional[str] = None) -> dict:
    data: Any = Path(path).read_bytes() if path else text
    if not data:
        raise InteropError("give a path or the XMI text")
    if mode == "new":
        repo, report = xmi_to_project(data, name)
        SESSION.set_repo(repo)
    elif mode == "merge":
        report = import_xmi(SESSION.repo, data)
    else:
        raise InteropError("mode must be 'merge' or 'new'")
    return _ok({"mode": mode, "report": report.to_dict(), "project": _summary()})


@_safe
def tool_model_check(severity: Optional[list] = None, rule: Optional[list] = None) -> dict:
    return _ok(run_model_check(SESSION.repo, severities=severity, rules=rule))


_MODE = {"type": "string", "enum": ["merge", "new"],
         "description": "'merge' updates the current project; 'new' replaces it"}

TOOLS = [
    {"name": "sysml_export_tables",
     "description": "Export the architecture as tables (components, ports, connections, "
                    "interfaces, requirements, links, stereotypes): xlsx workbook, csv (ZIP of "
                    "CSV files) or json. Writes `path` if given, else returns the content.",
     "inputSchema": {"type": "object", "properties": {
         "format": {"type": "string", "enum": ["xlsx", "csv", "json"], "default": "xlsx"},
         "path": {"type": "string"}}},
     "handler": tool_export_tables},
    {"name": "sysml_import_tables",
     "description": "Import tables (from sysml_export_tables or hand-written) into the current "
                    "project (matched by ID, else owner + name) or as a new project.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": ".xlsx, .zip of CSV, or .json tables"},
         "tables": {"type": "object", "description": "{table: [[header...], [row...]]}"},
         "base64_data": {"type": "string"}, "mode": _MODE, "name": {"type": "string"}}},
     "handler": tool_import_tables},
    {"name": "sysml_generate_report",
     "description": "Generate the HTML system architecture report (hierarchy, ports, interfaces, "
                    "requirements traceability, validation, Mermaid diagrams).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "title": {"type": "string"}, "author": {"type": "string"},
         "sections": {"type": "array", "items": {"type": "string"}},
         "mermaid": {"type": "string", "enum": ["link", "inline", "none"]}}},
     "handler": tool_generate_report},
    {"name": "sysml_compare_projects",
     "description": "Compare the current project (or current_path) with another project JSON or "
                    "tables file: added / removed / modified elements with property diffs.",
     "inputSchema": {"type": "object", "properties": {
         "other_path": {"type": "string"}, "other_json": {"type": "string"},
         "current_path": {"type": "string"}, "include_layout": {"type": "boolean"}}},
     "handler": tool_compare_projects},
    {"name": "sysml_merge_projects",
     "description": "Three-way merge: base + theirs + mine (default: the current project). "
                    "Non-conflicting changes merge automatically; conflicts take `choices` "
                    "({conflict id: 'mine'|'theirs'}) or `default`. With apply the result "
                    "becomes the current project; out_path writes it.",
     "inputSchema": {"type": "object", "properties": {
         "base_path": {"type": "string"}, "theirs_path": {"type": "string"},
         "mine_path": {"type": "string"}, "base_json": {"type": "string"},
         "theirs_json": {"type": "string"}, "choices": {"type": "object"},
         "default": {"type": "string", "enum": ["mine", "theirs"]},
         "apply": {"type": "boolean", "default": True}, "out_path": {"type": "string"}}},
     "handler": tool_merge_projects},
    {"name": "sysml_export_sysml_text",
     "description": "Export the project as SysML v2 textual notation (re-parsable).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
     "handler": tool_export_sysml_text},
    {"name": "sysml_import_sysml_text",
     "description": "Parse SysML v2 text into the current project (atomic) or a new one.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"}, "path": {"type": "string"}, "mode": _MODE,
         "name": {"type": "string"}}},
     "handler": tool_import_sysml_text},
    {"name": "sysml_import_xmi",
     "description": "Import a SysML 1.x XMI 2.5.1 file (Cameo / MagicDraw): blocks, parts, "
                    "ports, connectors, requirements, satisfy/verify/derive links.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "text": {"type": "string"},
         "mode": {**_MODE, "default": "new"}, "name": {"type": "string"}}},
     "handler": tool_import_xmi},
    {"name": "sysml_model_check",
     "description": "Run Model Check: the validator plus advisor checks (empty compositions, "
                    "unconnected ports, duplicate names, components without ports, missing "
                    "documentation). Returns issues with counts per severity and rule.",
     "inputSchema": {"type": "object", "properties": {
         "severity": {"type": "array", "items": {"type": "string",
                                                 "enum": ["error", "warning", "info"]}},
         "rule": {"type": "array", "items": {"type": "string"}}}},
     "handler": tool_model_check},
]
