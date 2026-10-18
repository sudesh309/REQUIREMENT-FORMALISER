"""MCP tools of the Allocation Editor (see docs/features/allocation.md).

References are element ids or qualified names. Wherever a scenario is
expected, an allocation set may be given instead (its first scenario is used).
"""
from __future__ import annotations

from typing import Any, Optional

from engine import allocation as A
from engine.allocation import AllocationError
from mcp_server.core import SESSION, _err, _ok, register_kind, register_summary_hook


def _find(ref: Any, what: str):
    if not isinstance(ref, str) or not ref:
        raise AllocationError(f"{what} is required")
    e = SESSION.find(ref)
    if e is None:
        raise AllocationError(f"{what} {ref!r} not found", 404)
    return e


def _set(ref: Any) -> A.AllocationSet:
    e = _find(ref, "allocation set")
    if not isinstance(e, A.AllocationSet):
        raise AllocationError(f"{e.qualified_name!r} is a {e.kind}, not an allocation set")
    return e


def _scenario(ref: Any) -> A.AllocationScenario:
    e = _find(ref, "scenario")
    if isinstance(e, A.AllocationSet):
        if not e.scenarios:
            raise AllocationError(f"allocation set {e.name!r} has no scenario", 404)
        return e.scenarios[0]
    if not isinstance(e, A.AllocationScenario):
        raise AllocationError(f"{e.qualified_name!r} is a {e.kind}, not an allocation scenario")
    return e


def _guard(fn):
    def wrapper(**kwargs):
        try:
            return _ok(fn(**kwargs))
        except AllocationError as ex:
            return _err(str(ex))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_guard
def tool_list_allocation_sets() -> list:
    return [A.set_summary(s) for s in A.allocation_sets(SESSION.repo)]


@_guard
def tool_create_allocation_set(name: str, source: str, target: str, description: str = "",
                               require_complete_coverage: bool = False,
                               scenario: str = "Scenario 1") -> dict:
    s = A.create_allocation_set(SESSION.repo, name, _find(source, "source architecture"),
                                _find(target, "target architecture"), description=description,
                                require_complete_coverage=require_complete_coverage,
                                scenario_name=scenario or "Scenario 1")
    return A.set_summary(s)


@_guard
def tool_update_allocation_set(set: str, name: Optional[str] = None, description: Optional[str] = None,
                               source: Optional[str] = None, target: Optional[str] = None,
                               require_complete_coverage: Optional[bool] = None,
                               force: bool = False) -> dict:
    s = _set(set)
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = name
    if description is not None:
        changes["description"] = description
    if source is not None:
        changes["source"] = _find(source, "source architecture")
    if target is not None:
        changes["target"] = _find(target, "target architecture")
    if require_complete_coverage is not None:
        changes["require_complete_coverage"] = require_complete_coverage
    A.update_allocation_set(SESSION.repo, s, force=force, **changes)
    return A.set_summary(s)


@_guard
def tool_delete_allocation_set(set: str) -> dict:
    s = _set(set)
    A.delete_allocation_set(SESSION.repo, s)
    return {"deleted": s.element_id}


@_guard
def tool_create_allocation_scenario(set: str, name: Optional[str] = None) -> dict:
    return A.scenario_summary(A.create_scenario(SESSION.repo, _set(set), name or None))


@_guard
def tool_rename_allocation_scenario(scenario: str, name: str) -> dict:
    return A.scenario_summary(A.rename_scenario(_scenario(scenario), name))


@_guard
def tool_duplicate_allocation_scenario(scenario: str, name: Optional[str] = None) -> dict:
    return A.scenario_summary(A.duplicate_scenario(SESSION.repo, _scenario(scenario), name or None))


@_guard
def tool_delete_allocation_scenario(scenario: str) -> dict:
    sc = _scenario(scenario)
    A.delete_scenario(SESSION.repo, sc)
    return {"deleted": sc.element_id}


@_guard
def tool_allocate(scenario: str, source: str, target: str) -> dict:
    a = A.allocate(SESSION.repo, _scenario(scenario), _find(source, "source element"),
                   _find(target, "target element"))
    return A.allocation_summary(a)


@_guard
def tool_deallocate(scenario: str, source: str, target: str) -> dict:
    src, tgt = _find(source, "source element"), _find(target, "target element")
    A.deallocate(SESSION.repo, _scenario(scenario), src, tgt)
    return {"deallocated": True, "source_id": src.element_id, "target_id": tgt.element_id}


@_guard
def tool_allocated_to(element: str, scenario: Optional[str] = None) -> list:
    sc = _scenario(scenario) if scenario else None
    return [A.element_ref(x) for x in A.allocated_to(_find(element, "element"), sc)]


@_guard
def tool_allocated_from(element: str, scenario: Optional[str] = None) -> list:
    sc = _scenario(scenario) if scenario else None
    return [A.element_ref(x) for x in A.allocated_from(_find(element, "element"), sc)]


@_guard
def tool_allocation_coverage(scenario: str, kinds: Optional[list] = None, leaves_only: bool = True) -> dict:
    return A.coverage(_scenario(scenario), kinds=kinds or ("component", "function"),
                      leaves_only=leaves_only)


@_guard
def tool_allocation_matrix(scenario: str, rows: Optional[list] = None, cols: Optional[list] = None,
                           show: str = "all", text: str = "") -> dict:
    return A.matrix(_scenario(scenario), rows=rows, cols=cols, show=show, text=text)


@_guard
def tool_allocation_map(scenario: str) -> dict:
    return A.allocation_map(_scenario(scenario))


@_guard
def tool_allocation_chain(element: str, direction: str = "LR") -> dict:
    return A.allocation_chain(_find(element, "element"), direction=direction)


register_summary_hook(A.annotate_summary)
register_kind("Allocation", A.ArchitectureAllocation)

_REF = {"type": "string"}
_SCENARIO = {"type": "string", "description": "AllocationScenario id or qualified name "
                                              "(an AllocationSet means its first scenario)"}
_KINDS = {"type": "array", "items": {"type": "string", "enum": list(A.CATEGORIES)}}


def _tool(name: str, description: str, handler, properties: dict, required: list) -> dict:
    return {"name": name, "description": description, "handler": handler,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS = [
    _tool("sysml_list_allocation_sets",
          "List allocation sets (source/target architectures, scenarios with allocation counts).",
          tool_list_allocation_sets, {}, []),
    _tool("sysml_create_allocation_set",
          "Create an allocation set from a source architecture to a target architecture "
          "(PartDefinition or Package) in the 'Allocations' package, with a default scenario.",
          tool_create_allocation_set,
          {"name": _REF, "source": _REF, "target": _REF, "description": _REF,
           "require_complete_coverage": {"type": "boolean"}, "scenario": _REF},
          ["name", "source", "target"]),
    _tool("sysml_update_allocation_set",
          "Rename an allocation set or change its description, architectures or coverage flag. "
          "Changing an architecture used by existing allocations needs force=true (deletes them).",
          tool_update_allocation_set,
          {"set": _REF, "name": _REF, "description": _REF, "source": _REF, "target": _REF,
           "require_complete_coverage": {"type": "boolean"}, "force": {"type": "boolean"}},
          ["set"]),
    _tool("sysml_delete_allocation_set", "Delete an allocation set with its scenarios.",
          tool_delete_allocation_set, {"set": _REF}, ["set"]),
    _tool("sysml_create_allocation_scenario",
          "Add a scenario to an allocation set (default name 'Scenario N').",
          tool_create_allocation_scenario, {"set": _REF, "name": _REF}, ["set"]),
    _tool("sysml_rename_allocation_scenario", "Rename an allocation scenario.",
          tool_rename_allocation_scenario, {"scenario": _SCENARIO, "name": _REF}, ["scenario", "name"]),
    _tool("sysml_duplicate_allocation_scenario",
          "Copy a scenario with all its allocations (and their stereotypes).",
          tool_duplicate_allocation_scenario, {"scenario": _SCENARIO, "name": _REF}, ["scenario"]),
    _tool("sysml_delete_allocation_scenario",
          "Delete a scenario (a set keeps at least one).",
          tool_delete_allocation_scenario, {"scenario": _SCENARIO}, ["scenario"]),
    _tool("sysml_allocate",
          "Allocate a source element (component, port, connector or function of the set's source "
          "architecture) to a target element of its target architecture in a scenario.",
          tool_allocate, {"scenario": _SCENARIO, "source": _REF, "target": _REF},
          ["scenario", "source", "target"]),
    _tool("sysml_deallocate", "Remove the allocation of source to target in a scenario.",
          tool_deallocate, {"scenario": _SCENARIO, "source": _REF, "target": _REF},
          ["scenario", "source", "target"]),
    _tool("sysml_allocated_to",
          "Elements the given element is allocated to (one scenario, or every scenario).",
          tool_allocated_to, {"element": _REF, "scenario": _SCENARIO}, ["element"]),
    _tool("sysml_allocated_from",
          "Elements allocated to the given element (one scenario, or every scenario).",
          tool_allocated_from, {"element": _REF, "scenario": _SCENARIO}, ["element"]),
    _tool("sysml_allocation_coverage",
          "Coverage report of a scenario: unallocated source elements (leaf components and "
          "functions by default) and allocation counts per target.",
          tool_allocation_coverage,
          {"scenario": _SCENARIO, "kinds": _KINDS, "leaves_only": {"type": "boolean"}}, ["scenario"]),
    _tool("sysml_allocation_matrix",
          "Allocation matrix of a scenario: rows (sources), columns (targets) and allocations; "
          "filter by element kinds, show ('all'|'allocated'|'unallocated') and name text.",
          tool_allocation_matrix,
          {"scenario": _SCENARIO, "rows": _KINDS, "cols": _KINDS,
           "show": {"type": "string", "enum": list(A.SHOW_MODES)}, "text": _REF}, ["scenario"]),
    _tool("sysml_allocation_map",
          "Analysis contract: {target_id: [source ids]} for a scenario (resource budgets).",
          tool_allocation_map, {"scenario": _SCENARIO}, ["scenario"]),
    _tool("sysml_allocation_chain",
          "Follow allocations across sets (functional -> logical -> physical) from an element; "
          "returns nodes, edges and a Mermaid flowchart.",
          tool_allocation_chain,
          {"element": _REF, "direction": {"type": "string", "enum": ["LR", "TB"]}}, ["element"]),
]
