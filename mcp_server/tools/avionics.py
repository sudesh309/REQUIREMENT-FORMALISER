"""MCP tools of the avionics domain pack (see docs/features/avionics.md).

Projects     sysml_list_avionics_templates, sysml_create_avionics_project, sysml_avionics_overview
Profile      sysml_ensure_avionics_profile
Libraries    sysml_list_interface_library, sysml_import_interface_library,
             sysml_list_requirement_library, sysml_import_requirement_library
Safety       sysml_fha_list, sysml_fha_set_row, sysml_fha_delete_row, sysml_safety_check

Every editing tool applies the same checks as the web API and is one undo step (``sysml_undo``).
``sysml_create_avionics_project`` replaces the project like *New* does (a fresh history).
References are element ids, qualified names or FHA ids such as ``FHA-3``.
"""
from __future__ import annotations

from typing import Any, Optional

import engine.requirements as rq
from engine import interfaces as I
from engine import profiles as P
from engine.architecture import ArchitectureError
from engine.avionics import interfaces_lib, requirements_lib, safety as SF, templates
from engine.avionics import profile as AP
from engine.undo import tracked
from mcp_server.core import SESSION, _err, _ok


def _guard(label: Optional[str] = None):
    """Wrap a tool: errors become ``{"ok": False, "error": ...}``; ``label`` makes it one undo step."""
    def deco(fn):
        def wrapper(**kwargs):
            try:
                if label is None:
                    return _ok(fn(**kwargs))
                with tracked(SESSION, label):
                    return _ok(fn(**kwargs))
            except (SF.FhaError, I.InterfaceError, P.ProfileError, ArchitectureError, rq.RequirementsError,
                    ValueError) as ex:
                return _err(str(ex))
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco


def _csv(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v)]
    return [v for v in str(value or "").split(",") if v]


# --- projects ----------------------------------------------------------------------------------

@_guard()
def tool_list_templates(counts: bool = False) -> dict:
    return {"templates": templates.list_templates(counts=counts)}


@_guard()
def tool_create_project(template: str = "blank", name: Optional[str] = None) -> dict:
    repo = templates.create_project(template, name)
    SESSION.set_repo(repo)
    return {"name": repo.name, "template": template, "element_count": len(list(repo.all_elements())),
            **{k: v for k, v in templates.overview(repo).items() if k in ("architectures", "safety", "fha")}}


@_guard()
def tool_overview() -> dict:
    return templates.overview(SESSION.repo)


# --- profile and libraries ---------------------------------------------------------------------

@_guard("Add the Avionics profile")
def tool_ensure_profile() -> dict:
    existed = AP.find_profile(SESSION.repo) is not None
    prof = AP.ensure_profile(SESSION.repo)
    return {"id": prof.element_id, "created": not existed, "stereotypes": [s.name for s in prof.stereotypes]}


@_guard()
def tool_list_interface_library() -> dict:
    return interfaces_lib.library_status(SESSION.repo)


@_guard("Import the avionics interface library")
def tool_import_interface_library(names: Any = None, groups: Any = None, on_conflict: str = "skip") -> dict:
    return interfaces_lib.import_library(SESSION.repo, names=_csv(names), groups=_csv(groups),
                                         on_conflict=on_conflict)


@_guard()
def tool_list_requirement_library() -> dict:
    return requirements_lib.catalog()


@_guard("Import the requirement skeletons")
def tool_import_requirement_library(sets: Any = None, dal: Optional[str] = None) -> dict:
    results = requirements_lib.import_requirement_library(SESSION.repo, _csv(sets) or None, dal=dal or None)
    return {"sets": [{"id": r["set"].element_id, "name": r["set"].name, "key": r["key"],
                      "prefix": r["set"].id_prefix, "requirements": r["requirements"]} for r in results]}


# --- safety ------------------------------------------------------------------------------------

@_guard()
def tool_fha_list() -> dict:
    repo = SESSION.repo
    return {"rows": [SF.describe_row(repo, r) for r in SF.fha_rows(repo)],
            "classifications": list(SF.CLASSIFICATIONS), "dal_by_classification": SF.DAL_BY_CLASSIFICATION,
            "phases": list(SF.FLIGHT_PHASES), "functions": SF.function_choices(repo)}


@_guard("Edit the FHA")
def tool_fha_set_row(row: Optional[str] = None, failure_condition: Optional[str] = None,
                     function: Optional[str] = None, flight_phase: Optional[str] = None,
                     effect: Optional[str] = None, classification: Optional[str] = None,
                     notes: Optional[str] = None, fha_id: Optional[str] = None,
                     clear_function: bool = False) -> dict:
    """Add an FHA row (omit ``row``) or update the row ``row``; only the given fields change."""
    repo = SESSION.repo
    fields: dict[str, Any] = {}
    for key, value in (("failure_condition", failure_condition), ("flight_phase", flight_phase),
                       ("effect", effect), ("classification", classification), ("notes", notes),
                       ("fha_id", fha_id)):
        if value is not None:
            fields[key] = value
    if function is not None:
        fields["function"] = function
    if clear_function:
        fields["function"] = None
    if row:
        entry = SF.update_fha_row(repo, row, **fields)
    else:
        entry = SF.add_fha_row(repo, **{"failure_condition": "", **fields})
    return SF.describe_row(repo, entry)


@_guard("Delete an FHA row")
def tool_fha_delete_row(row: str) -> dict:
    return {"deleted": SF.delete_fha_row(SESSION.repo, row)}


@_guard()
def tool_safety_check(severity: Any = None, rule: Any = None, element: Optional[str] = None) -> dict:
    out = SF.safety_check(SESSION.repo, severities=_csv(severity) or None, rules=_csv(rule) or None)
    if element:
        e = SESSION.find(element)
        if e is None:
            raise ValueError(f"element {element!r} not found")
        out["issues"] = [i for i in out["issues"] if any(x["id"] == e.element_id for x in i["elements"])]
    return out


def _schema(props: dict, required: Optional[list] = None) -> dict:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


_S = {"type": "string"}
_B = {"type": "boolean"}
_LIST = {"type": "array", "items": {"type": "string"}}

TOOLS = [
    {"name": "sysml_list_avionics_templates",
     "description": "List the avionics project templates (blank avionics project, complete IMA avionics "
                    "example); counts=true adds what each builds.",
     "inputSchema": _schema({"counts": _B}), "handler": tool_list_templates},
    {"name": "sysml_create_avionics_project",
     "description": "Replace the current project with a new one from a template: 'blank' (Avionics profile, "
                    "interface library, ARP4754A / DO-178C requirement skeletons, empty FHA and system "
                    "architecture) or 'ima_example' (a complete IMA avionics model). Starts a fresh undo history.",
     "inputSchema": _schema({"template": {"type": "string", "enum": ["blank", "ima_example"]}, "name": _S}),
     "handler": tool_create_project},
    {"name": "sysml_avionics_overview",
     "description": "Overview of the avionics content of the project: profile, interface and requirement "
                    "libraries, FHA rows, safety rule counts, mass / power roll-up and architectures.",
     "inputSchema": _schema({}), "handler": tool_overview},
    {"name": "sysml_ensure_avionics_profile",
     "description": "Create the 'Avionics' profile (equipment, LRU, LRM, Sensor, Display, Actuator, Computer, "
                    "Switch, Gateway, Partition, SoftwareItem, DataBusPort, BusLink, AvionicsRequirement ...) or "
                    "add the stereotypes it lacks; existing ones are not changed.",
     "inputSchema": _schema({}), "handler": tool_ensure_profile},
    {"name": "sysml_list_interface_library",
     "description": "The avionics interface library (ARINC 429 label sets, ARINC 664 AFDX, MIL-STD-1553B, "
                    "discrete, analog, ARINC 825, ARINC 653, power) with a 'present' flag per item. Label "
                    "numbers are typical: verify them against the programme ICD.",
     "inputSchema": _schema({}), "handler": tool_list_interface_library},
    {"name": "sysml_import_interface_library",
     "description": "Import avionics interfaces into the interface dictionary (all by default, or 'names' / "
                    "'groups': types, a429, a664, m1553, discrete, analog, a825, a653, power). Value types the "
                    "selection needs come with it. Existing items are skipped (on_conflict 'skip') or imported "
                    "under a new name ('rename').",
     "inputSchema": _schema({"names": _LIST, "groups": _LIST, "on_conflict": {"type": "string",
                                                                              "enum": ["skip", "rename"]}}),
     "handler": tool_import_interface_library},
    {"name": "sysml_list_requirement_library",
     "description": "The requirement skeleton sets (arp4754a-system, arp4754a-item, do178c-hlr, do178c-llr) "
                    "and the verification guidance per DAL.",
     "inputSchema": _schema({}), "handler": tool_list_requirement_library},
    {"name": "sysml_import_requirement_library",
     "description": "Create requirement skeleton sets (all by default, or 'sets' keys) with type, DAL, derived, "
                    "safety related and verification method; 'dal' replaces the typical level of every entry.",
     "inputSchema": _schema({"sets": _LIST, "dal": {"type": "string", "enum": list(AP.DALS)}}),
     "handler": tool_import_requirement_library},
    {"name": "sysml_fha_list",
     "description": "The functional hazard assessment: rows (function, failure condition, flight phase, effect, "
                    "classification, assigned DAL, items the function is allocated to), vocabularies and the "
                    "functions a row can name.",
     "inputSchema": _schema({}), "handler": tool_fha_list},
    {"name": "sysml_fha_set_row",
     "description": "Add an FHA row (omit 'row') or update one ('row' = id or FHA id such as FHA-3). Fields: "
                    "failure_condition, function (element id / qualified name; clear_function removes it), "
                    "flight_phase (All, Ground, Takeoff, Climb, Cruise, Descent, Approach, Landing; comma "
                    "separated), effect, classification (Catastrophic, Hazardous, Major, Minor, No Safety "
                    "Effect: assigned DAL A, B, C, D, E), notes, fha_id.",
     "inputSchema": _schema({"row": _S, "failure_condition": _S, "function": _S, "flight_phase": _S,
                             "effect": _S, "classification": {"type": "string", "enum": list(SF.CLASSIFICATIONS)},
                             "notes": _S, "fha_id": _S, "clear_function": _B}),
     "handler": tool_fha_set_row},
    {"name": "sysml_fha_delete_row",
     "description": "Delete an FHA row (id or FHA id).",
     "inputSchema": _schema({"row": _S}, ["row"]), "handler": tool_fha_delete_row},
    {"name": "sysml_safety_check",
     "description": "Run the avionics safety / DAL rules: component DAL below its requirement's, function "
                    "allocated below its FHA DAL, mixed DAL without partitioning mark, host below hosted DAL, "
                    "DAL decomposition hints, FHA rows without an allocated function, verification guidance per "
                    "DAL. Each issue names the elements and the rule. Filter by severity, rule or element.",
     "inputSchema": _schema({"severity": _LIST, "rule": _LIST, "element": _S}),
     "handler": tool_safety_check},
]
