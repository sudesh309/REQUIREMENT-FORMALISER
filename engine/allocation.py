"""System Composer style allocations: allocation sets, scenarios and allocations.

Data model (all ordinary model elements, persisted with the project)::

    Allocations                      Package at the project root (created on demand)
    └── <AllocationSet>              source_architecture -> target_architecture
        │                            require_complete_coverage, description (= documentation)
        └── <AllocationScenario>     "Scenario 1", ... (a set always keeps at least one)
            └── <Allocation>         source -> target, at most one per (source, target) pair

An *architecture* is a ``PartDefinition`` (see ``engine/structure.py``) or a
``Package`` (e.g. a functional architecture holding actions). Allocatable
elements are components (``PartUsage``/``PartDefinition``), ports
(``PortUsage``), connectors (``ConnectionUsage``) and functions (actions that
are not states, transitions or calculations, or any kind containing
"Function"). Allocations refer to their ends by object, so renames show up
everywhere at once; deleting an end removes its allocations (removal hook).

Analysis contract
-----------------
``allocation_map(scenario) -> {target_id: [source_id, ...]}`` is the stable
interface resource-budget analyses use: for every target element with at least
one allocation, the ids of the source elements allocated to it, in model order.

Queries: ``allocated_to(element, scenario=None)``, ``allocated_from(element,
scenario=None)``, ``allocations(scenario)``, ``coverage(scenario)``,
``allocation_chain(element)``; mutations raise :class:`AllocationError`
(a ``ValueError`` carrying an HTTP-style ``status``) with a readable message.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Iterator, Optional

from kerml.elements import Documentation, Element
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ActionDefinition, ActionUsage, CalculationDefinition, CalculationUsage,
    ConnectionUsage, PartDefinition, PartUsage, PortUsage,
    StateDefinition, StateUsage, TransitionUsage,
)

from . import graph_export
from .graph_export import register_edge_source
from .hooks import notify_created
from .repository import register_removal_hook
from .serializer import register_codec
from .structure import components_of, connectors_of, definition_of, ports_of
from .validator import Severity, ValidationIssue, register_repo_rule

__all__ = [
    "ALLOCATIONS_PACKAGE", "CATEGORIES", "AllocationError",
    "AllocationSet", "AllocationScenario", "ArchitectureAllocation",
    "category_of", "is_function", "architecture_rows", "architecture_candidates",
    "allocations_package", "allocation_sets", "find_set",
    "create_allocation_set", "update_allocation_set", "delete_allocation_set",
    "create_scenario", "rename_scenario", "delete_scenario", "duplicate_scenario",
    "allocate", "deallocate", "toggle_allocation", "find_allocation",
    "allocations", "iter_allocations", "allocated_to", "allocated_from", "allocations_of",
    "allocation_map", "coverage", "matrix", "allocation_chain",
    "set_summary", "scenario_summary", "allocation_summary", "element_ref", "annotate_summary",
]

ALLOCATIONS_PACKAGE = "Allocations"
CATEGORIES: tuple[str, ...] = ("component", "port", "connector", "function")
DEFAULT_ROW_KINDS: tuple[str, ...] = ("component", "function")
DEFAULT_COL_KINDS: tuple[str, ...] = ("component",)
SHOW_MODES: tuple[str, ...] = ("all", "allocated", "unallocated")


class AllocationError(ValueError):
    """A refused allocation edit; ``status`` is the matching HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Metamodel
# ---------------------------------------------------------------------------

def _doc(e: Element) -> str:
    return next((a.body for a in e.annotations if isinstance(a, Documentation)), "")


def _set_doc(e: Element, text: Optional[str]) -> None:
    e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
    if text:
        e.add_annotation(Documentation(body=str(text)))


class AllocationSet(Namespace):
    """Allocations from one architecture (source) to another (target), in scenarios."""

    kind = "AllocationSet"

    def __init__(self, name: Optional[str] = None, *,
                 source_architecture: Optional[Element] = None,
                 target_architecture: Optional[Element] = None,
                 require_complete_coverage: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.source_architecture: Optional[Element] = source_architecture
        self.target_architecture: Optional[Element] = target_architecture
        # When true, the validator warns about leaf source components left unallocated.
        self.require_complete_coverage: bool = bool(require_complete_coverage)

    @property
    def scenarios(self) -> list["AllocationScenario"]:
        return [c for c in self.owned_elements if isinstance(c, AllocationScenario)]

    # The set's description is its documentation, so the generic inspector edits it too.
    @property
    def description(self) -> str:
        return _doc(self)

    @description.setter
    def description(self, text: Optional[str]) -> None:
        _set_doc(self, text)


class AllocationScenario(Namespace):
    """One alternative assignment of source elements to target elements."""

    kind = "AllocationScenario"

    @property
    def allocation_set(self) -> Optional[AllocationSet]:
        return self.owner if isinstance(self.owner, AllocationSet) else None

    @property
    def allocations(self) -> list["ArchitectureAllocation"]:
        return [c for c in self.owned_elements if isinstance(c, ArchitectureAllocation)]


class ArchitectureAllocation(Element):
    """A directed allocation of one model element to another (kind ``Allocation``).

    A normal element: it can carry documentation, ``tool_data`` and stereotype
    applications (profiles' "Allocation" stereotypes match its kind).
    """

    kind = "Allocation"

    def __init__(self, name: Optional[str] = None, *, source: Optional[Element] = None,
                 target: Optional[Element] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.source: Optional[Element] = source
        self.target: Optional[Element] = target

    @property
    def scenario(self) -> Optional[AllocationScenario]:
        return self.owner if isinstance(self.owner, AllocationScenario) else None

    @property
    def label(self) -> str:
        return f"{_label(self.source)} → {_label(self.target)}"


def _label(e: Optional[Element]) -> str:
    if e is None:
        return "∅"
    return e.name or f"<{e.kind}>"


# ---------------------------------------------------------------------------
# Allocatable elements and architectures
# ---------------------------------------------------------------------------

_NOT_FUNCTIONS = (StateDefinition, StateUsage, TransitionUsage, CalculationDefinition, CalculationUsage)


def is_function(e: Element) -> bool:
    """Functions: actions that are not states/transitions/calculations, or 'Function' kinds."""
    kind = getattr(e, "kind", "") or ""
    if "Function" in kind and "Element" not in kind:
        return True
    return isinstance(e, (ActionDefinition, ActionUsage)) and not isinstance(e, _NOT_FUNCTIONS)


def category_of(e: Optional[Element]) -> Optional[str]:
    """'component' | 'port' | 'connector' | 'function', or None when `e` is not allocatable."""
    if e is None or isinstance(e, (ArchitectureAllocation, AllocationScenario, AllocationSet)):
        return None
    kind = getattr(e, "kind", "") or ""
    if "Function" in kind and "Element" not in kind:
        return "function"
    if isinstance(e, (PartUsage, PartDefinition)):
        return "component"
    if isinstance(e, PortUsage):
        return "port"
    if isinstance(e, ConnectionUsage):
        return "connector"
    if is_function(e):
        return "function"
    return None


def _is_allocation_container(e: Element) -> bool:
    return isinstance(e, (AllocationSet, AllocationScenario, ArchitectureAllocation)) or (
        isinstance(e, Package) and e.name == ALLOCATIONS_PACKAGE
        and e.owner is not None and e.owner.owner is None)


def architecture_rows(arch: Optional[Element]) -> list[dict]:
    """The allocatable elements of an architecture, as indented rows in model order.

    Each row: ``key`` (unique path), ``id``, ``name``, ``kind``, ``qualified_name``,
    ``category`` (None for package headers), ``depth``, ``parent_key``,
    ``allocatable``, ``leaf`` (no sub-components / sub-functions) and
    ``has_children``. Reference components list their definition's internals;
    such shared elements appear once per usage (same ``id``, different ``key``).
    """
    rows: list[dict] = []
    if arch is None:
        return rows

    def emit(e: Element, depth: int, parent_key: str, category: Optional[str]) -> dict:
        key = f"{parent_key}/{e.element_id}" if parent_key else e.element_id
        row = {
            "key": key, "id": e.element_id, "name": e.name or f"<{e.kind}>", "kind": e.kind,
            "qualified_name": e.qualified_name, "category": category, "depth": depth,
            "parent_key": parent_key or None, "allocatable": category is not None,
            "leaf": True, "has_children": False,
        }
        if parent_key:
            parent = by_key.get(parent_key)
            if parent is not None:
                parent["has_children"] = True
        by_key[key] = row
        rows.append(row)
        return row

    by_key: dict[str, dict] = {}

    def visit_function(f: Element, depth: int, parent_key: str) -> None:
        row = emit(f, depth, parent_key, "function")
        subs = [x for x in f.owned_elements if is_function(x) and not isinstance(x, PartUsage)]
        row["leaf"] = not subs
        for s in subs:
            visit_function(s, depth + 1, row["key"])

    def visit_internals(comp: Element, depth: int, parent_key: str, seen: frozenset) -> None:
        owners = [comp]
        d = definition_of(comp)
        if d is not None and d is not comp:
            owners.append(d)
        for o in owners:
            for c in o.owned_elements:
                if not isinstance(c, (PartUsage, PartDefinition)) and category_of(c) == "function":
                    visit_function(c, depth, parent_key)
        for p in ports_of(comp):
            emit(p, depth, parent_key, "port")
        for c in components_of(comp):
            visit_component(c, depth, parent_key, seen)
        for c in connectors_of(comp):
            emit(c, depth, parent_key, "connector")

    def visit_component(c: Element, depth: int, parent_key: str, seen: frozenset) -> None:
        row = emit(c, depth, parent_key, category_of(c) or "component")
        row["leaf"] = not components_of(c)
        d = definition_of(c)
        key = id(d) if d is not None else id(c)
        if key in seen:          # a definition that contains a usage of itself
            return
        visit_internals(c, depth + 1, row["key"], seen | {key})

    def visit_package(p: Element, depth: int, parent_key: str) -> None:
        for c in p.owned_elements:
            if _is_allocation_container(c):
                continue
            if isinstance(c, Package):
                header = emit(c, depth, parent_key, None)
                visit_package(c, depth + 1, header["key"])
            elif isinstance(c, (PartDefinition, PartUsage)):
                visit_component(c, depth, parent_key, frozenset())
            elif category_of(c) == "function":
                visit_function(c, depth, parent_key)
            elif isinstance(c, PortUsage):
                emit(c, depth, parent_key, "port")
            elif isinstance(c, ConnectionUsage):
                emit(c, depth, parent_key, "connector")

    if isinstance(arch, (PartDefinition, PartUsage)):
        visit_internals(arch, 0, "", frozenset({id(arch)}))
    elif isinstance(arch, Namespace):
        visit_package(arch, 0, "")
    return rows


def _allocatable_ids(arch: Optional[Element]) -> set[str]:
    return {r["id"] for r in architecture_rows(arch) if r["allocatable"]}


def _project_root(repo_or_root: Any) -> Element:
    return getattr(repo_or_root, "root_package", repo_or_root)


def architecture_candidates(repo: Any) -> list[dict]:
    """Elements usable as a set's source/target architecture (root PartDefinitions, Packages)."""
    root = _project_root(repo)
    out: list[dict] = []
    for e in root.walk():
        if e is root or _is_allocation_container(e):
            continue
        if any(_is_allocation_container(a) for a in _ancestors(e)):
            continue
        is_arch = isinstance(e, PartDefinition) and not isinstance(e.owner, (PartDefinition, PartUsage))
        if is_arch or (isinstance(e, Package) and type(e) is Package):
            out.append({"id": e.element_id, "name": e.name or f"<{e.kind}>", "kind": e.kind,
                        "qualified_name": e.qualified_name})
    return out


def _ancestors(e: Element) -> Iterator[Element]:
    node = e.owner
    while node is not None:
        yield node
        node = node.owner


def _check_architecture(repo: Any, e: Optional[Element], role: str) -> Element:
    if e is None:
        raise AllocationError(f"{role} architecture not found", 404)
    if not (isinstance(e, PartDefinition) or type(e) is Package) or _is_allocation_container(e):
        raise AllocationError(
            f"{role} architecture must be an architecture (PartDefinition) or a Package, "
            f"not {e.kind} {e.qualified_name!r}")
    if e.root() is not _project_root(repo):
        raise AllocationError(f"{role} architecture {e.qualified_name!r} is not part of this project")
    return e


# ---------------------------------------------------------------------------
# Sets and scenarios
# ---------------------------------------------------------------------------

def allocations_package(repo: Any, *, create: bool = False) -> Optional[Package]:
    """The project's 'Allocations' package (created and announced when `create`)."""
    root = repo.root_package
    pkg = next((c for c in root.owned_elements
                if isinstance(c, Package) and c.name == ALLOCATIONS_PACKAGE), None)
    if pkg is None and create:
        pkg = Package(name=ALLOCATIONS_PACKAGE)
        repo.add(pkg)
        notify_created(pkg, repo)
    return pkg


def allocation_sets(repo_or_root: Any) -> list[AllocationSet]:
    return [e for e in _project_root(repo_or_root).walk() if isinstance(e, AllocationSet)]


def find_set(repo: Any, name: str) -> Optional[AllocationSet]:
    return next((s for s in allocation_sets(repo) if s.name == name), None)


def _check_name(name: Any, what: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AllocationError(f"{what} name must be a non-empty string")
    name = name.strip()
    if "::" in name:
        raise AllocationError(f"{what} name must not contain '::'")
    return name


def _check_bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise AllocationError(f"{what} must be true or false")
    return value


def create_allocation_set(repo: Any, name: str, source: Optional[Element], target: Optional[Element],
                          *, description: str = "", require_complete_coverage: bool = False,
                          scenario_name: str = "Scenario 1") -> AllocationSet:
    """Create a set in the 'Allocations' package with one (default) scenario."""
    name = _check_name(name, "Allocation set")
    _check_architecture(repo, source, "Source")
    _check_architecture(repo, target, "Target")
    _check_bool(require_complete_coverage, "require_complete_coverage")
    scenario_name = _check_name(scenario_name or "Scenario 1", "Scenario")
    if find_set(repo, name) is not None:
        raise AllocationError(f"an allocation set named {name!r} already exists", 409)
    pkg = allocations_package(repo, create=True)
    s = AllocationSet(name=name, source_architecture=source, target_architecture=target,
                      require_complete_coverage=require_complete_coverage)
    s.description = description or ""
    pkg.own(s)
    sc = AllocationScenario(name=scenario_name)
    s.own(sc)
    repo.registry.register_tree(s)
    notify_created(s, repo)
    notify_created(sc, repo)
    return s


_UNSET: Any = object()


def update_allocation_set(repo: Any, s: AllocationSet, *, name: Any = _UNSET, description: Any = _UNSET,
                          source: Any = _UNSET, target: Any = _UNSET,
                          require_complete_coverage: Any = _UNSET, force: bool = False) -> AllocationSet:
    """Change a set's properties. Changing an architecture that existing allocations
    depend on is refused (409) unless `force`, which deletes those allocations."""
    if not isinstance(s, AllocationSet):
        raise AllocationError("not an allocation set", 404)
    if name is not _UNSET:
        name = _check_name(name, "Allocation set")
        other = find_set(repo, name)
        if other is not None and other is not s:
            raise AllocationError(f"an allocation set named {name!r} already exists", 409)
    if source is not _UNSET:
        _check_architecture(repo, source, "Source")
    if target is not _UNSET:
        _check_architecture(repo, target, "Target")
    if require_complete_coverage is not _UNSET:
        _check_bool(require_complete_coverage, "require_complete_coverage")
    stale: list[ArchitectureAllocation] = []
    if source is not _UNSET or target is not _UNSET:
        src_ids = _allocatable_ids(s.source_architecture if source is _UNSET else source)
        tgt_ids = _allocatable_ids(s.target_architecture if target is _UNSET else target)
        for sc in s.scenarios:
            for a in sc.allocations:
                if (a.source is None or a.source.element_id not in src_ids
                        or a.target is None or a.target.element_id not in tgt_ids):
                    stale.append(a)
        if stale and not force:
            raise AllocationError(
                f"{len(stale)} allocation(s) refer to elements outside the new architecture; "
                f"delete them first or pass force=true", 409)
    for a in stale:
        repo.remove(a)
    if name is not _UNSET:
        s.name = name
    if description is not _UNSET:
        s.description = description or ""
    if source is not _UNSET:
        s.source_architecture = source
    if target is not _UNSET:
        s.target_architecture = target
    if require_complete_coverage is not _UNSET:
        s.require_complete_coverage = require_complete_coverage
    return s


def delete_allocation_set(repo: Any, s: AllocationSet) -> None:
    if not isinstance(s, AllocationSet):
        raise AllocationError("not an allocation set", 404)
    repo.remove(s)


def _unique_scenario_name(s: AllocationSet, base: str) -> str:
    used = {sc.name for sc in s.scenarios}
    if base not in used:
        return base
    n = 2
    while f"{base} {n}" in used:
        n += 1
    return f"{base} {n}"


def _default_scenario_name(s: AllocationSet) -> str:
    used = {sc.name for sc in s.scenarios}
    n = 1
    while f"Scenario {n}" in used:
        n += 1
    return f"Scenario {n}"


def _check_scenario_name(s: AllocationSet, name: Any, exclude: Optional[AllocationScenario] = None) -> str:
    name = _check_name(name, "Scenario")
    if any(sc.name == name and sc is not exclude for sc in s.scenarios):
        raise AllocationError(f"allocation set {s.name!r} already has a scenario named {name!r}", 409)
    return name


def create_scenario(repo: Any, s: AllocationSet, name: Optional[str] = None) -> AllocationScenario:
    if not isinstance(s, AllocationSet):
        raise AllocationError("not an allocation set", 404)
    name = _check_scenario_name(s, name) if name else _default_scenario_name(s)
    sc = AllocationScenario(name=name)
    s.own(sc)
    repo.registry.register_tree(sc)
    notify_created(sc, repo)
    return sc


def _check_scenario(sc: Any) -> AllocationScenario:
    if not isinstance(sc, AllocationScenario) or sc.allocation_set is None:
        raise AllocationError("allocation scenario not found", 404)
    return sc


def rename_scenario(sc: AllocationScenario, name: str) -> AllocationScenario:
    _check_scenario(sc)
    sc.name = _check_scenario_name(sc.allocation_set, name, exclude=sc)
    return sc


def delete_scenario(repo: Any, sc: AllocationScenario) -> None:
    _check_scenario(sc)
    if len(sc.allocation_set.scenarios) <= 1:
        raise AllocationError("an allocation set needs at least one scenario; "
                              "delete the set instead", 409)
    repo.remove(sc)


def duplicate_scenario(repo: Any, sc: AllocationScenario, name: Optional[str] = None) -> AllocationScenario:
    """Copy a scenario with its allocations (documentation, tool data, stereotypes)."""
    _check_scenario(sc)
    s = sc.allocation_set
    name = _check_scenario_name(s, name) if name else _unique_scenario_name(s, f"{sc.name} copy")
    copy = AllocationScenario(name=name)
    _set_doc(copy, _doc(sc))
    s.own(copy)
    repo.registry.register_tree(copy)
    notify_created(copy, repo)
    for a in sc.allocations:
        if a.source is None or a.target is None:
            continue
        b = ArchitectureAllocation(source=a.source, target=a.target)
        _set_doc(b, _doc(a))
        b.tool_data = json.loads(json.dumps({k: v for k, v in a.tool_data.items() if _json_ok(v)}))
        copy.own(b)
        for app in stereotypes_on(a):
            if any(x.stereotype is app.stereotype for x in stereotypes_on(b)):
                continue
            try:
                app.stereotype.apply(b, dict(app.values))
            except (TypeError, KeyError, ValueError):
                pass        # e.g. the stereotype became abstract; the copy simply lacks it
        repo.registry.register_tree(b)
        notify_created(b, repo)
    return copy


def _json_ok(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

def allocations(scenario: AllocationScenario) -> list[ArchitectureAllocation]:
    """The allocations of a scenario, in creation order."""
    return list(_check_scenario(scenario).allocations)


def iter_allocations(repo_or_root: Any) -> Iterator[ArchitectureAllocation]:
    for e in _project_root(repo_or_root).walk():
        if isinstance(e, ArchitectureAllocation):
            yield e


def find_allocation(scenario: AllocationScenario, source: Element, target: Element
                    ) -> Optional[ArchitectureAllocation]:
    return next((a for a in scenario.allocations if a.source is source and a.target is target), None)


def _check_end(e: Optional[Element], role: str) -> Element:
    if e is None:
        raise AllocationError(f"{role} element not found", 404)
    if category_of(e) is None:
        raise AllocationError(
            f"{e.kind} {e.qualified_name!r} cannot be allocated; allocatable elements are "
            f"components, ports, connectors and functions")
    return e


def allocate(repo: Any, scenario: AllocationScenario, source: Optional[Element],
             target: Optional[Element]) -> ArchitectureAllocation:
    """Allocate `source` (in the set's source architecture) to `target` (in its target one)."""
    _check_scenario(scenario)
    _check_end(source, "Source")
    _check_end(target, "Target")
    s = scenario.allocation_set
    if s.source_architecture is None or s.target_architecture is None:
        raise AllocationError(f"allocation set {s.name!r} needs a source and a target architecture")
    if source.element_id not in _allocatable_ids(s.source_architecture):
        raise AllocationError(f"{source.qualified_name!r} is not part of source architecture "
                              f"{s.source_architecture.qualified_name!r}")
    if target.element_id not in _allocatable_ids(s.target_architecture):
        raise AllocationError(f"{target.qualified_name!r} is not part of target architecture "
                              f"{s.target_architecture.qualified_name!r}")
    if find_allocation(scenario, source, target) is not None:
        raise AllocationError(f"{_label(source)} is already allocated to {_label(target)} "
                              f"in {s.name}/{scenario.name}", 409)
    a = ArchitectureAllocation(source=source, target=target)
    scenario.own(a)
    repo.registry.register_tree(a)
    notify_created(a, repo)
    return a


def deallocate(repo: Any, scenario: AllocationScenario, source: Optional[Element],
               target: Optional[Element]) -> None:
    _check_scenario(scenario)
    if source is None or target is None:
        raise AllocationError("source/target element not found", 404)
    a = find_allocation(scenario, source, target)
    if a is None:
        raise AllocationError(f"{_label(source)} is not allocated to {_label(target)} "
                              f"in {scenario.allocation_set.name}/{scenario.name}", 404)
    repo.remove(a)


def toggle_allocation(repo: Any, scenario: AllocationScenario, source: Optional[Element],
                      target: Optional[Element]) -> Optional[ArchitectureAllocation]:
    """Allocate when not allocated yet, else deallocate; returns the new allocation or None."""
    _check_scenario(scenario)
    if source is not None and target is not None:
        existing = find_allocation(scenario, source, target)
        if existing is not None:
            repo.remove(existing)
            return None
    return allocate(repo, scenario, source, target)


def _scope(element: Element, scenario: Optional[AllocationScenario]) -> Iterable[ArchitectureAllocation]:
    if scenario is not None:
        return _check_scenario(scenario).allocations
    return iter_allocations(element.root())


def _unique(elements: Iterable[Optional[Element]]) -> list[Element]:
    out: list[Element] = []
    seen: set[int] = set()
    for e in elements:
        if e is not None and id(e) not in seen:
            seen.add(id(e))
            out.append(e)
    return out


def allocated_to(element: Element, scenario: Optional[AllocationScenario] = None) -> list[Element]:
    """Targets `element` is allocated to (in `scenario`, or in every scenario of the project)."""
    return _unique(a.target for a in _scope(element, scenario) if a.source is element)


def allocated_from(element: Element, scenario: Optional[AllocationScenario] = None) -> list[Element]:
    """Sources allocated to `element` (in `scenario`, or in every scenario of the project)."""
    return _unique(a.source for a in _scope(element, scenario) if a.target is element)


def allocations_of(element: Element, scenario: Optional[AllocationScenario] = None) -> dict:
    """Allocation elements with `element` as source ('to') or as target ('from')."""
    allocs = list(_scope(element, scenario))
    return {"to": [a for a in allocs if a.source is element],
            "from": [a for a in allocs if a.target is element]}


def allocation_map(scenario: AllocationScenario) -> dict[str, list[str]]:
    """Analysis contract: ``{target_id: [source_id, ...]}`` for every allocated target.

    Targets and sources follow the scenario's allocation order; a resource
    budget sums a property of the sources (or of the allocation) per target.
    """
    out: dict[str, list[str]] = {}
    for a in allocations(scenario):
        if a.source is None or a.target is None:
            continue
        srcs = out.setdefault(a.target.element_id, [])
        if a.source.element_id not in srcs:
            srcs.append(a.source.element_id)
    return out


# ---------------------------------------------------------------------------
# Summaries (JSON-able views shared by the web API and MCP tools)
# ---------------------------------------------------------------------------

def element_ref(e: Optional[Element]) -> Optional[dict]:
    if e is None:
        return None
    return {"id": e.element_id, "name": e.name or f"<{e.kind}>", "kind": e.kind,
            "qualified_name": e.qualified_name, "category": category_of(e)}


def allocation_summary(a: ArchitectureAllocation) -> dict:
    sc = a.scenario
    s = sc.allocation_set if sc is not None else None
    return {
        "id": a.element_id, "kind": a.kind, "label": a.label,
        "source_id": a.source.element_id if a.source else None,
        "target_id": a.target.element_id if a.target else None,
        "source": element_ref(a.source), "target": element_ref(a.target),
        "scenario_id": sc.element_id if sc else None, "scenario": sc.name if sc else None,
        "set_id": s.element_id if s else None, "set": s.name if s else None,
        "doc": _doc(a),
        "stereotypes": [{"name": app.stereotype.name, "values": app.values} for app in stereotypes_on(a)],
    }


def scenario_summary(sc: AllocationScenario) -> dict:
    s = sc.allocation_set
    return {"id": sc.element_id, "name": sc.name, "kind": sc.kind, "qualified_name": sc.qualified_name,
            "set_id": s.element_id if s else None, "set": s.name if s else None,
            "allocation_count": len(sc.allocations), "doc": _doc(sc)}


def annotate_summary(e: Element, d: dict) -> None:
    """Summary hook (web API and MCP): allocation fields, badges and style in element JSON."""
    if isinstance(e, ArchitectureAllocation):
        d["allocation"] = allocation_summary(e)
        d.setdefault("badges", []).append(e.label)
        d.setdefault("style", {}).setdefault("icon", "allocation")
    elif isinstance(e, AllocationSet):
        src, tgt = e.source_architecture, e.target_architecture
        d["allocation_set"] = {
            "source_architecture": element_ref(src), "target_architecture": element_ref(tgt),
            "require_complete_coverage": e.require_complete_coverage,
            "scenario_count": len(e.scenarios)}
        d.setdefault("badges", []).append(f"{_label(src)} → {_label(tgt)}")
    elif isinstance(e, AllocationScenario):
        d.setdefault("badges", []).append(f"{len(e.allocations)} alloc")
    else:
        cat = category_of(e)
        if cat:
            d["allocation_category"] = cat


def set_summary(s: AllocationSet) -> dict:
    return {
        "id": s.element_id, "name": s.name, "kind": s.kind, "qualified_name": s.qualified_name,
        "description": s.description,
        "source_architecture": element_ref(s.source_architecture),
        "target_architecture": element_ref(s.target_architecture),
        "require_complete_coverage": s.require_complete_coverage,
        "scenarios": [scenario_summary(sc) for sc in s.scenarios],
    }


# ---------------------------------------------------------------------------
# Matrix, coverage, chain
# ---------------------------------------------------------------------------

def _parse_kinds(kinds: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if kinds is None or kinds == "":
        return default
    if isinstance(kinds, str):
        kinds = [k.strip() for k in kinds.split(",") if k.strip()]
    out = []
    for k in kinds:
        k = str(k).lower().rstrip("s")
        if k not in CATEGORIES:
            raise AllocationError(f"unknown element kind {k!r}; use {', '.join(CATEGORIES)}")
        out.append(k)
    return tuple(out)


def _check_show(show: Any) -> str:
    show = (show or "all").lower()
    if show not in SHOW_MODES:
        raise AllocationError(f"show must be one of {', '.join(SHOW_MODES)}")
    return show


def _filter_rows(rows: list[dict], kinds: tuple[str, ...], show: str, text: str,
                 counts: dict[str, int]) -> list[dict]:
    needle = (text or "").strip().lower()
    by_key = {r["key"]: r for r in rows}
    matched: set[str] = set()
    for r in rows:
        r["count"] = counts.get(r["id"], 0) if r["allocatable"] else 0
        if not r["allocatable"] or r["category"] not in kinds:
            continue
        if show == "allocated" and not r["count"]:
            continue
        if show == "unallocated" and r["count"]:
            continue
        if needle and needle not in r["name"].lower() and needle not in r["qualified_name"].lower():
            continue
        matched.add(r["key"])
    keep = set(matched)
    for key in matched:                          # ancestors give hierarchy context
        parent = by_key[key]["parent_key"]
        while parent and parent not in keep:
            keep.add(parent)
            parent = by_key[parent]["parent_key"]
    out = []
    for r in rows:
        if r["key"] in keep:
            out.append({**r, "context": r["key"] not in matched})
    return out


def matrix(scenario: AllocationScenario, *, rows: Any = None, cols: Any = None, show: Any = "all",
           col_show: Any = "all", text: str = "", col_text: str = "") -> dict:
    """The allocation matrix of a scenario: filtered rows (sources) and columns (targets).

    `rows`/`cols`: element kinds to list (default components+functions / components);
    `show`/`col_show`: 'all' | 'allocated' | 'unallocated'; `text`/`col_text`: name filters.
    Ancestors of listed elements are included with ``context: true`` for hierarchy.
    """
    _check_scenario(scenario)
    s = scenario.allocation_set
    row_kinds = _parse_kinds(rows, DEFAULT_ROW_KINDS)
    col_kinds = _parse_kinds(cols, DEFAULT_COL_KINDS)
    show, col_show = _check_show(show), _check_show(col_show)
    allocs = [a for a in scenario.allocations if a.source is not None and a.target is not None]
    src_counts: dict[str, int] = {}
    tgt_counts: dict[str, int] = {}
    for a in allocs:
        src_counts[a.source.element_id] = src_counts.get(a.source.element_id, 0) + 1
        tgt_counts[a.target.element_id] = tgt_counts.get(a.target.element_id, 0) + 1
    row_list = _filter_rows(architecture_rows(s.source_architecture), row_kinds, show, text, src_counts)
    col_list = _filter_rows(architecture_rows(s.target_architecture), col_kinds, col_show, col_text,
                            tgt_counts)
    return {
        "set": set_summary(s), "scenario": scenario_summary(scenario),
        "row_kinds": list(row_kinds), "col_kinds": list(col_kinds),
        "show": show, "col_show": col_show,
        "rows": row_list, "columns": col_list,
        "allocations": [allocation_summary(a) for a in allocs],
    }


def coverage(scenario: AllocationScenario, *, kinds: Any = ("component", "function"),
             leaves_only: bool = True) -> dict:
    """Unallocated source elements and per-target allocation counts of a scenario."""
    _check_scenario(scenario)
    kinds = _parse_kinds(kinds, ("component", "function"))
    s = scenario.allocation_set
    allocs = [a for a in scenario.allocations if a.source is not None and a.target is not None]
    allocated_ids = {a.source.element_id for a in allocs}
    seen: set[str] = set()
    candidates: list[dict] = []
    for r in architecture_rows(s.source_architecture):
        if (r["allocatable"] and r["category"] in kinds and r["id"] not in seen
                and (r["leaf"] or not leaves_only)):
            seen.add(r["id"])
            candidates.append(r)
    unallocated = [{k: r[k] for k in ("id", "name", "kind", "qualified_name", "category")}
                   for r in candidates if r["id"] not in allocated_ids]
    per_target: list[dict] = []
    tseen: set[str] = set()
    for r in architecture_rows(s.target_architecture):
        if not r["allocatable"] or r["id"] in tseen:
            continue
        srcs = [a.source for a in allocs if a.target.element_id == r["id"]]
        if srcs or r["category"] == "component":
            tseen.add(r["id"])
            per_target.append({"id": r["id"], "name": r["name"], "kind": r["kind"],
                               "qualified_name": r["qualified_name"], "category": r["category"],
                               "count": len(srcs), "sources": [element_ref(x) for x in _unique(srcs)]})
    total = len(candidates)
    done = total - len(unallocated)
    return {
        "set": s.name, "scenario": scenario.name, "scenario_id": scenario.element_id,
        "kinds": list(kinds), "leaves_only": leaves_only,
        "total": total, "allocated": done, "ratio": (done / total) if total else 1.0,
        "unallocated": unallocated, "per_target": per_target,
        "allocation_count": len(allocs),
    }


_MERMAID_UNSAFE = re.compile(r'["<>{}\[\]|`#;&]')


def _mm(text: str) -> str:
    return _MERMAID_UNSAFE.sub(" ", text or "").strip() or "?"


def allocation_chain(element: Element, *, scenarios: Optional[Iterable[AllocationScenario]] = None,
                     direction: str = "LR") -> dict:
    """Follow allocations through every set (functional -> logical -> physical, ...).

    Walks forward (what `element` is allocated to, and onwards) and backward
    (what is allocated to it, and further back). Returns ``nodes``, ``edges``
    (one per allocation, labelled with set and scenario) and ``mermaid``, a
    flowchart (``direction`` LR or TB) grouping nodes by architecture.
    """
    direction = (direction or "LR").upper()
    if direction not in ("LR", "TB"):
        raise AllocationError("direction must be LR or TB")
    allowed = None if scenarios is None else {id(sc) for sc in scenarios}
    allocs = [a for a in iter_allocations(element.root())
              if a.source is not None and a.target is not None and a.scenario is not None
              and (allowed is None or id(a.scenario) in allowed)]
    fwd: dict[int, list[ArchitectureAllocation]] = {}
    bwd: dict[int, list[ArchitectureAllocation]] = {}
    for a in allocs:
        fwd.setdefault(id(a.source), []).append(a)
        bwd.setdefault(id(a.target), []).append(a)
    nodes: dict[int, dict] = {id(element): {**element_ref(element), "level": 0, "architecture": None}}
    order: list[int] = [id(element)]
    edges: list[ArchitectureAllocation] = []
    edge_ids: set[int] = set()

    def arch_of(a: ArchitectureAllocation, side: str) -> Optional[Element]:
        s = a.scenario.allocation_set
        return s.source_architecture if side == "source" else s.target_architecture

    def visit(start: Element, index: dict, end_attr: str, other_attr: str, step: int) -> None:
        queue = [start]
        while queue:
            cur = queue.pop(0)
            for a in index.get(id(cur), []):
                if id(a) not in edge_ids:
                    edge_ids.add(id(a))
                    edges.append(a)
                nxt = getattr(a, other_attr)
                here = nodes[id(cur)]
                if here["architecture"] is None:
                    here["architecture"] = element_ref(arch_of(a, end_attr))
                if id(nxt) not in nodes:
                    nodes[id(nxt)] = {**element_ref(nxt), "level": here["level"] + step,
                                      "architecture": element_ref(arch_of(a, other_attr))}
                    order.append(id(nxt))
                    queue.append(nxt)

    visit(element, fwd, "source", "target", 1)
    visit(element, bwd, "target", "source", -1)
    node_list = [nodes[k] for k in order]
    edge_list = [{"allocation_id": a.element_id, "source_id": a.source.element_id,
                  "target_id": a.target.element_id, "set": a.scenario.allocation_set.name,
                  "scenario": a.scenario.name} for a in edges]
    return {"focus": element_ref(element), "nodes": node_list, "edges": edge_list,
            "mermaid": _chain_mermaid(node_list, edge_list, element.element_id, direction)}


def _chain_mermaid(nodes: list[dict], edges: list[dict], focus_id: str, direction: str = "LR") -> str:
    alias = {n["id"]: f"n{i}" for i, n in enumerate(nodes)}
    lines = [f"flowchart {direction}"]
    groups: dict[str, list[dict]] = {}
    titles: dict[str, str] = {}
    for n in sorted(nodes, key=lambda n: n["level"]):
        arch = n.get("architecture")
        key = arch["id"] if arch else ""
        titles[key] = arch["name"] if arch else ""
        groups.setdefault(key, []).append(n)
    for gi, (key, members) in enumerate(groups.items()):
        indent = "  "
        if key:
            lines.append(f'  subgraph g{gi}["{_mm(titles[key])}"]')
            indent = "    "
        for n in members:
            lines.append(f'{indent}{alias[n["id"]]}["{_mm(n["name"])}<br/>{_mm(n["kind"])}"]')
        if key:
            lines.append("  end")
    for e in edges:
        lines.append(f'  {alias[e["source_id"]]} -->|{_mm(e["set"])} / {_mm(e["scenario"])}| '
                     f'{alias[e["target_id"]]}')
    lines.append("  classDef focus fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px")
    lines.append(f"  class {alias[focus_id]} focus")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence, synchronization, validation, knowledge graph
# ---------------------------------------------------------------------------

def _ref_id(e: Optional[Element]) -> Optional[str]:
    return e.element_id if e is not None else None


def _encode(e: Element) -> Any:
    if isinstance(e, AllocationSet):
        return {"source": _ref_id(e.source_architecture), "target": _ref_id(e.target_architecture),
                "require_complete_coverage": e.require_complete_coverage}
    if isinstance(e, ArchitectureAllocation):
        return {"source": _ref_id(e.source), "target": _ref_id(e.target)}
    return None


def _decode(e: Element, data: Any, by_id: dict) -> None:
    if isinstance(e, AllocationSet):
        e.source_architecture = by_id.get(data.get("source"))
        e.target_architecture = by_id.get(data.get("target"))
        e.require_complete_coverage = bool(data.get("require_complete_coverage"))
    elif isinstance(e, ArchitectureAllocation):
        e.source = by_id.get(data.get("source"))
        e.target = by_id.get(data.get("target"))


def _on_removed(repo: Any, removed: set[int]) -> None:
    """Drop allocations whose source or target was deleted (the core already nulled the refs)."""
    doomed = [a for a in iter_allocations(repo)
              if id(a) not in removed and (a.source is None or a.target is None
                                           or id(a.source) in removed or id(a.target) in removed)]
    for a in doomed:
        if a.owner is not None:
            repo.remove(a)


def _validate(repo: Any) -> Iterator[ValidationIssue]:
    E, W = Severity.ERROR, Severity.WARNING
    for s in allocation_sets(repo):
        if s.source_architecture is None:
            yield ValidationIssue(E, "allocation.set.source", "Allocation set has no source architecture", s)
        if s.target_architecture is None:
            yield ValidationIssue(E, "allocation.set.target", "Allocation set has no target architecture", s)
        if not s.scenarios:
            yield ValidationIssue(W, "allocation.set.scenarios", "Allocation set has no scenario", s)
        src_rows = architecture_rows(s.source_architecture)
        src_ids = {r["id"] for r in src_rows if r["allocatable"]}
        tgt_ids = _allocatable_ids(s.target_architecture)
        leaves: list[Element] = []
        if s.require_complete_coverage and s.source_architecture is not None:
            seen: set[str] = set()
            for r in src_rows:
                if r["category"] == "component" and r["leaf"] and r["id"] not in seen:
                    seen.add(r["id"])
                    leaves.append(repo.by_id(r["id"]))
        for sc in s.scenarios:
            pairs: set[tuple[int, int]] = set()
            for a in sc.allocations:
                if a.source is None or a.target is None:
                    yield ValidationIssue(E, "allocation.ends", "Allocation is missing its source or target", a)
                    continue
                if (id(a.source), id(a.target)) in pairs:
                    yield ValidationIssue(E, "allocation.duplicate",
                                          f"{a.label} is allocated twice in {s.name}/{sc.name}", a)
                pairs.add((id(a.source), id(a.target)))
                if s.source_architecture is not None and a.source.element_id not in src_ids:
                    yield ValidationIssue(E, "allocation.scope",
                                          f"Source {a.source.qualified_name!r} is not in source architecture "
                                          f"{s.source_architecture.qualified_name!r}", a)
                if s.target_architecture is not None and a.target.element_id not in tgt_ids:
                    yield ValidationIssue(E, "allocation.scope",
                                          f"Target {a.target.qualified_name!r} is not in target architecture "
                                          f"{s.target_architecture.qualified_name!r}", a)
            allocated = {id(a.source) for a in sc.allocations if a.source is not None}
            for leaf in leaves:
                if leaf is not None and id(leaf) not in allocated:
                    yield ValidationIssue(W, "allocation.coverage",
                                          f"Leaf component {leaf.qualified_name!r} is not allocated in "
                                          f"{s.name}/{sc.name} (complete coverage required)", leaf)
    for a in iter_allocations(repo):
        if a.scenario is None or a.scenario.allocation_set is None:
            yield ValidationIssue(E, "allocation.owner",
                                  "Allocation must be owned by a scenario of an allocation set", a)


def _edges(e: Element) -> Iterator[tuple[str, Element, Element, dict]]:
    if isinstance(e, ArchitectureAllocation) and e.source is not None and e.target is not None:
        sc = e.scenario
        s = sc.allocation_set if sc is not None else None
        yield ("allocatedTo", e.source, e.target,
               {"allocation": e.element_id, "scenario": sc.name if sc else "",
                "set": s.name if s else ""})


def install() -> None:
    """Register codecs, hooks, rules and the edge source (idempotent)."""
    register_codec("allocation", _encode, _decode)
    from . import repository, validator
    if _on_removed not in repository._REMOVAL_HOOKS:
        register_removal_hook(_on_removed)
    if _validate not in validator._REPO_RULES:
        register_repo_rule(_validate)
    if _edges not in graph_export._EDGE_SOURCES:
        register_edge_source(_edges)


install()
