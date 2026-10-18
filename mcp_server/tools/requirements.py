"""MCP tools for requirements and traceability (System Composer Requirements Perspective).

Requirement sets hold hierarchical requirements (RequirementDefinition) with an ID,
summary, description, rationale, type, priority, status and verification method; trace
links are Implement / Verify / Refine / Derive / Relate / Confirm; links become *suspect*
when a linked requirement's text changes. See docs/features/requirements.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import engine.requirements as rq
from mcp_server.core import SESSION, _err, _ok, register_kind, register_summary_hook
from sysmlv2 import VerificationCaseDefinition

register_kind("RequirementSet", rq.RequirementSet)
register_kind("VerificationCaseDefinition", VerificationCaseDefinition)


def _summary_hook(e, d: dict) -> None:
    if rq.is_requirement(e):
        d["requirement"] = rq.requirement_fields(e)
    elif rq.is_test_case(e):
        d["verification_result"] = rq.test_result(e)
    elif isinstance(e, rq.RequirementSet):
        d["requirement_set"] = {"prefix": e.id_prefix}


register_summary_hook(_summary_hook)


class _Fail(Exception):
    pass


def _tool(fn):
    def wrapper(*args, **kwargs):
        try:
            return _ok(fn(*args, **kwargs))
        except (_Fail, rq.RequirementsError) as ex:
            return _err(str(ex))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _find(ref: Optional[str], what: str = "Element"):
    e = SESSION.find(ref) if ref else None
    if e is None:
        raise _Fail(f"{what} {ref!r} not found")
    return e


def _set(ref: Optional[str], *, optional: bool = False):
    if not ref:
        if optional:
            return None
        raise _Fail("A requirement set (UUID or qualified name) is required")
    e = _find(ref, "Requirement set")
    if not isinstance(e, rq.RequirementSet):
        raise _Fail(f"{ref!r} is not a requirement set")
    return e


def _fields(**kw: Any) -> dict:
    return {k: v for k, v in kw.items() if v is not None}


@_tool
def tool_create_requirement_set(name: str, prefix: Optional[str] = None,
                                parent: Optional[str] = None,
                                description: Optional[str] = None) -> dict:
    s = rq.create_requirement_set(SESSION.repo, name, prefix=prefix,
                                  parent=_find(parent, "Parent") if parent else None,
                                  description=description)
    return rq.set_summary(SESSION.repo, s)


@_tool
def tool_add_requirement(summary: Optional[str] = None, set: Optional[str] = None,
                         parent: Optional[str] = None, after: Optional[str] = None,
                         id: Optional[str] = None, description: Optional[str] = None,
                         rationale: Optional[str] = None, type: Optional[str] = None,
                         priority: Optional[str] = None, status: Optional[str] = None,
                         verification_method: Optional[str] = None) -> dict:
    container = _find(parent, "Parent") if parent else _set(set)
    req = rq.add_requirement(SESSION.repo, container,
                             _fields(summary=summary, id=id, description=description,
                                     rationale=rationale, type=type, priority=priority,
                                     status=status, verification_method=verification_method),
                             after=_find(after, "Sibling") if after else None)
    return rq.requirement_status(SESSION.repo, req)["requirement"]


@_tool
def tool_update_requirement(ref: str, id: Optional[str] = None, summary: Optional[str] = None,
                            description: Optional[str] = None, rationale: Optional[str] = None,
                            type: Optional[str] = None, priority: Optional[str] = None,
                            status: Optional[str] = None,
                            verification_method: Optional[str] = None,
                            move: Optional[str] = None) -> dict:
    req = _find(ref, "Requirement")
    fields = _fields(id=id, summary=summary, description=description, rationale=rationale,
                     type=type, priority=priority, status=status,
                     verification_method=verification_method)
    if fields:
        rq.update_requirement(SESSION.repo, req, fields)
    if move:
        rq.move_requirement(SESSION.repo, req, move)
    if not fields and not move:
        raise _Fail("Nothing to update: give at least one field or 'move'")
    return rq.requirement_status(SESSION.repo, req)["requirement"]


@_tool
def tool_link_requirement(type: str, source: str, target: str) -> dict:
    rel = rq.create_trace_link(SESSION.repo, type, _find(source, "Source"), _find(target, "Target"))
    return rq.link_info(rel)


@_tool
def tool_requirement_links(ref: Optional[str] = None, set: Optional[str] = None,
                           suspect_only: bool = False) -> dict:
    if ref:
        e = _find(ref)
        links = rq.links_for(SESSION.repo, e)
        if suspect_only:
            links = [l for l in links if l["suspect"]]
        return {"element": rq.element_info(e), "links": links}
    return {"element": None,
            "links": rq.all_links(SESSION.repo, _set(set, optional=True), suspect_only=suspect_only)}


@_tool
def tool_unlink_requirement(link: str) -> dict:
    rel = SESSION.repo.by_id(link)
    if not isinstance(rel, rq.TRACE_CLASSES):
        raise _Fail(f"Trace link {link!r} not found")
    rq.delete_trace_link(SESSION.repo, rel)
    return {"deleted": link}


@_tool
def tool_clear_suspect(link: Optional[str] = None, ref: Optional[str] = None) -> dict:
    if link:
        rel = SESSION.repo.by_id(link)
        if not isinstance(rel, rq.TRACE_CLASSES):
            raise _Fail(f"Trace link {link!r} not found")
        return rq.link_info(rq.clear_suspect(SESSION.repo, rel))
    return {"cleared": rq.clear_suspect_for(SESSION.repo, _find(ref) if ref else None)}


@_tool
def tool_add_test_case(name: str, set: Optional[str] = None, parent: Optional[str] = None,
                       description: Optional[str] = None, result: Optional[str] = None,
                       verifies: Optional[list] = None) -> dict:
    container = _find(parent, "Parent") if parent else _set(set)
    tc = rq.add_test_case(SESSION.repo, container, name, description=description, result=result)
    for ref in verifies or []:
        rq.create_trace_link(SESSION.repo, "verify", tc, _find(ref, "Requirement"))
    return rq.test_case_row(SESSION.repo, tc, rq.LinkIndex(SESSION.repo))


@_tool
def tool_set_test_result(ref: str, result: str) -> dict:
    tc = rq.update_test_case(SESSION.repo, _find(ref, "Test case"), {"result": result})
    return rq.test_case_row(SESSION.repo, tc, rq.LinkIndex(SESSION.repo))


@_tool
def tool_trace_matrix(set: Optional[str] = None, columns: str = "components",
                      column_set: Optional[str] = None, format: str = "json") -> dict:
    rset, cset = _set(set, optional=True), _set(column_set, optional=True)
    if format == "csv":
        return {"format": "csv", "text": rq.matrix_csv(SESSION.repo, rset, columns, cset)}
    m = rq.trace_matrix(SESSION.repo, rset, columns, cset)
    # Compact form for agents: one entry per linked cell.
    label = {r["id"]: f"{r['req_id'] or ''} {r['summary'] or ''}".strip() for r in m["rows"]}
    col = {c["id"]: c["qualified_name"] for c in m["columns"]}
    return {
        "rows": [f"{r['index']} {r['req_id']} {r['summary']}" for r in m["rows"]],
        "columns": [c["qualified_name"] for c in m["columns"]],
        "links": [{"requirement": label[c["row"]], "element": col[c["col"]],
                   "types": [f"{l['type']} ({l['direction']})" + (" suspect" if l["suspect"] else "")
                             for l in c["links"]]} for c in m["cells"]],
        "unlinked_requirements": [label[i] for i in m["unlinked_rows"]],
        "unlinked_elements": [col[i] for i in m["unlinked_columns"]],
    }


@_tool
def tool_requirement_status(ref: Optional[str] = None) -> dict:
    return rq.requirement_status(SESSION.repo, _find(ref) if ref else None)


@_tool
def tool_trace_diagram(ref: str, depth: int = 2) -> dict:
    return rq.trace_diagram(SESSION.repo, _find(ref), depth)


@_tool
def tool_import_requirements(format: str, content: Optional[str] = None,
                             path: Optional[str] = None, set: Optional[str] = None,
                             new_set: Optional[str] = None, prefix: Optional[str] = None) -> dict:
    if content is None and not path:
        raise _Fail("Give the file 'content' (preferred) or a 'path'")
    if content is None:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as ex:
            raise _Fail(f"Cannot read {path!r}: {ex}") from None
    return rq.import_requirements(SESSION.repo, format, content, rset=_set(set, optional=True),
                                  new_set=new_set, prefix=prefix)


@_tool
def tool_export_requirements(format: str = "csv", set: Optional[str] = None,
                             columns: str = "components", path: Optional[str] = None) -> dict:
    out = rq.export_requirements(SESSION.repo, format, _set(set, optional=True), columns=columns)
    if path:
        try:
            Path(path).write_text(out["text"], encoding="utf-8")
        except OSError as ex:
            raise _Fail(f"Cannot write {path!r}: {ex}") from None
        return {"format": out["format"], "path": path, "characters": len(out["text"])}
    return out


_TYPES = [t.name for t in rq.TRACE_TYPES]
_FIELD_PROPS = {
    "id":                  {"type": "string", "description": "Requirement ID (default: next '<prefix><n>' of the set)"},
    "summary":             {"type": "string", "description": "Short title (element name; unique among siblings)"},
    "description":         {"type": "string", "description": "Requirement text"},
    "rationale":           {"type": "string"},
    "type":                {"type": "string", "enum": list(rq.REQ_TYPES)},
    "priority":            {"type": "string", "enum": list(rq.PRIORITIES)},
    "status":              {"type": "string", "enum": list(rq.STATUSES)},
    "verification_method": {"type": "string", "enum": list(rq.VERIFICATION_METHODS)},
}

TOOLS = [
    {
        "name": "sysml_create_requirement_set",
        "description": "Create a requirement set (a package of hierarchical requirements). IDs of "
                       "new requirements are '<prefix><n>' (default prefix 'REQ-').",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}, "prefix": {"type": "string"},
            "parent": {"type": "string", "description": "Package UUID or qualified name (default: root)"},
            "description": {"type": "string"}}, "required": ["name"]},
        "handler": tool_create_requirement_set,
    },
    {
        "name": "sysml_add_requirement",
        "description": "Add a requirement to a set (top level) or under a parent requirement (child). "
                       "Returns the row with implementation/verification status.",
        "inputSchema": {"type": "object", "properties": {
            "set": {"type": "string", "description": "Requirement set (for a top-level requirement)"},
            "parent": {"type": "string", "description": "Parent requirement (for a child requirement)"},
            "after": {"type": "string", "description": "Insert right after this sibling requirement"},
            **_FIELD_PROPS}},
        "handler": tool_add_requirement,
    },
    {
        "name": "sysml_update_requirement",
        "description": "Edit requirement fields (validated; text edits make its links suspect) and/or "
                       "move it: up, down, indent (under previous sibling), outdent.",
        "inputSchema": {"type": "object", "properties": {
            "ref": {"type": "string", "description": "Requirement UUID or qualified name"},
            **_FIELD_PROPS,
            "move": {"type": "string", "enum": ["up", "down", "indent", "outdent"]}},
            "required": ["ref"]},
        "handler": tool_update_requirement,
    },
    {
        "name": "sysml_link_requirement",
        "description": "Create a trace link. implement: design element -> requirement; verify: test case "
                       "-> requirement; refine / derive: requirement -> requirement (source refines / is "
                       "derived from target); relate: any <-> any; confirm: any -> requirement.",
        "inputSchema": {"type": "object", "properties": {
            "type": {"type": "string", "enum": _TYPES},
            "source": {"type": "string"}, "target": {"type": "string"}},
            "required": ["type", "source", "target"]},
        "handler": tool_link_requirement,
    },
    {
        "name": "sysml_requirement_links",
        "description": "List trace links (type, direction, suspect flag and which end changed): those "
                       "touching an element (ref), or every link of a set / the whole project.",
        "inputSchema": {"type": "object", "properties": {
            "ref": {"type": "string", "description": "Element UUID or qualified name"},
            "set": {"type": "string", "description": "Without ref: only links of this requirement set"},
            "suspect_only": {"type": "boolean"}}},
        "handler": tool_requirement_links,
    },
    {
        "name": "sysml_unlink_requirement",
        "description": "Delete a trace link by its id.",
        "inputSchema": {"type": "object", "properties": {"link": {"type": "string"}}, "required": ["link"]},
        "handler": tool_unlink_requirement,
    },
    {
        "name": "sysml_clear_suspect",
        "description": "Clear the suspect flag of one link (link), of every link of an element or "
                       "requirement set (ref), or of the whole project (no arguments).",
        "inputSchema": {"type": "object", "properties": {"link": {"type": "string"}, "ref": {"type": "string"}}},
        "handler": tool_clear_suspect,
    },
    {
        "name": "sysml_add_test_case",
        "description": "Add a test case (VerificationCaseDefinition) with a result (unexecuted, passed, "
                       "failed), optionally creating Verify links to requirements.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}, "set": {"type": "string"}, "parent": {"type": "string"},
            "description": {"type": "string"},
            "result": {"type": "string", "enum": list(rq.TEST_RESULTS)},
            "verifies": {"type": "array", "items": {"type": "string"}}}, "required": ["name"]},
        "handler": tool_add_test_case,
    },
    {
        "name": "sysml_set_test_result",
        "description": "Set a test case result (unexecuted, passed, failed); drives verification status.",
        "inputSchema": {"type": "object", "properties": {
            "ref": {"type": "string"}, "result": {"type": "string", "enum": list(rq.TEST_RESULTS)}},
            "required": ["ref", "result"]},
        "handler": tool_set_test_result,
    },
    {
        "name": "sysml_trace_matrix",
        "description": "Traceability matrix: requirements of a set (rows) against components, ports, "
                       "connectors, interfaces, functions, requirements or test-cases (columns).",
        "inputSchema": {"type": "object", "properties": {
            "set": {"type": "string"},
            "columns": {"type": "string", "enum": [k for k, _l, _p in rq.CATEGORIES]},
            "column_set": {"type": "string", "description": "Limit requirement columns to this set"},
            "format": {"type": "string", "enum": ["json", "csv"]}}},
        "handler": tool_trace_matrix,
    },
    {
        "name": "sysml_requirement_status",
        "description": "Implementation and verification status roll-ups for a set, a requirement, or "
                       "every set (no ref).",
        "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}}},
        "handler": tool_requirement_status,
    },
    {
        "name": "sysml_trace_diagram",
        "description": "Mermaid graph of upstream/downstream trace links around an element (depth 1-3).",
        "inputSchema": {"type": "object", "properties": {
            "ref": {"type": "string"}, "depth": {"type": "integer", "minimum": 1, "maximum": 3}},
            "required": ["ref"]},
        "handler": tool_trace_diagram,
    },
    {
        "name": "sysml_import_requirements",
        "description": "Import requirements from CSV (columns id, summary, description, type, priority, "
                       "parent_id, ...) or ReqIF 1.2 XML into a set (or a new set). Existing IDs are updated.",
        "inputSchema": {"type": "object", "properties": {
            "format": {"type": "string", "enum": ["csv", "reqif"]},
            "content": {"type": "string", "description": "File content (preferred)"},
            "path": {"type": "string", "description": "Path of a local file to read instead"},
            "set": {"type": "string"}, "new_set": {"type": "string"}, "prefix": {"type": "string"}},
            "required": ["format"]},
        "handler": tool_import_requirements,
    },
    {
        "name": "sysml_export_requirements",
        "description": "Export requirements as csv or reqif, a traceability report (report-html, "
                       "report-csv) or a matrix (matrix-csv); returns text, or writes it to 'path'.",
        "inputSchema": {"type": "object", "properties": {
            "format": {"type": "string", "enum": ["csv", "reqif", "report-html", "report-csv", "matrix-csv"]},
            "set": {"type": "string"}, "columns": {"type": "string"}, "path": {"type": "string"}}},
        "handler": tool_export_requirements,
    },
]
