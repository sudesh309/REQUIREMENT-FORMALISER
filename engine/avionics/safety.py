"""Functional Hazard Assessment (FHA) table and the avionics safety / DAL rules.

FHA model data
--------------
The assessment is an ordinary part of the model: a package of kind ``FhaTable`` (named ``FHA``)
owning one ``FhaEntry`` element per failure condition::

    FHA                        FhaTable
    +-- FHA-1                  FhaEntry  function, failure condition, flight phase(s), effect,
    +-- FHA-2                            classification; the assigned DAL follows from it

so the rows are saved with the project (registered codec ``avionics.fha``), appear in the
containment tree, in Compare, in Model Tables (the *Elements* sheet) and are one undo step per
edit. The function is a reference to a model element: a component of the functional
architecture, or an action. The classification gives the assigned DAL through the standard
mapping::

    Catastrophic -> A    Hazardous -> B    Major -> C    Minor -> D    No Safety Effect -> E

(the *function* DAL of a function with several failure conditions is the most stringent one).

Rules (``avionics.*``, registered with the validator and shown by Model Check)
------------------------------------------------------------------------------
* ``avionics.dal.requirement``   a component implements a requirement of DAL X but has a lower DAL
* ``avionics.dal.allocation``    a function is allocated to an item of lower DAL than its FHA demands
* ``avionics.dal.partitioning``  items of different DAL share an IMA module / partition without a
                                 partitioning mark
* ``avionics.dal.hosting``       a module / partition has a lower DAL than what it hosts
* ``avionics.dal.decomposition`` hints: a valid decomposition candidate, or a chance to decompose
* ``avionics.fha.unallocated``   a failure condition without a function, or whose function is not
                                 allocated to any item
* ``avionics.fha.invalid``       an FHA row holds an unknown classification or flight phase
* ``avionics.equipment.reliability``  MTBF and failure rate of an equipment disagree
* ``avionics.req.*``             verification guidance per DAL (see :mod:`requirements_lib`)

Each issue names the elements involved and the rule. DAL decomposition follows the options of
ARP4754A section 5.2.3 (A -> A + C or B + B, B -> B + D or C + C, C -> C + E or D + D) and
needs independence between the items; the studio can only hint at it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional

from engine import allocation as AL
import engine.requirements as rq
from engine.hooks import notify_created
from engine.serializer import register_codec
from engine.structure import components_of, definition_of
from engine.validator import Severity, ValidationIssue, _REPO_RULES, register_repo_rule
from kerml.elements import Documentation, Element
from kerml.namespaces import Package
from sysmlv2.definitions import PartDefinition, PartUsage, PortUsage

from . import profile as AP
from . import requirements_lib as RL

__all__ = [
    "CLASSIFICATIONS", "DAL_BY_CLASSIFICATION", "FLIGHT_PHASES", "PROBABILITY_TARGETS", "RULES",
    "FhaError", "FhaTable", "FhaEntry", "SafetyIssue", "fha_table", "fha_rows", "find_row",
    "add_fha_row", "update_fha_row", "delete_fha_row", "describe_row", "function_choices",
    "resolve_function", "function_dal", "classification_dal", "valid_decomposition", "check_avionics",
    "safety_check", "rule_catalog",
]

CLASSIFICATIONS = ("Catastrophic", "Hazardous", "Major", "Minor", "No Safety Effect")
DAL_BY_CLASSIFICATION = {"Catastrophic": "A", "Hazardous": "B", "Major": "C", "Minor": "D",
                         "No Safety Effect": "E"}
#: Quantitative objective of the classification (CS / FAR 25.1309, AC 25.1309), per flight hour.
PROBABILITY_TARGETS = {"Catastrophic": "< 1E-9", "Hazardous": "< 1E-7", "Major": "< 1E-5",
                       "Minor": "no probability requirement", "No Safety Effect": "no requirement"}
FLIGHT_PHASES = ("All", "Ground", "Takeoff", "Climb", "Cruise", "Descent", "Approach", "Landing")
_PHASE_ALIASES = {"all phases": "All", "any": "All", "taxi": "Ground", "ground": "Ground",
                  "take-off": "Takeoff", "take off": "Takeoff", "takeoff": "Takeoff",
                  "go-around": "Landing", "go around": "Landing", "enroute": "Cruise",
                  "en-route": "Cruise", "en route": "Cruise", "flare": "Landing"}
_CLASS_ALIASES = {"cat": "Catastrophic", "catastrophic": "Catastrophic", "haz": "Hazardous",
                  "hazardous": "Hazardous", "maj": "Major", "major": "Major", "min": "Minor",
                  "minor": "Minor", "nse": "No Safety Effect", "none": "No Safety Effect",
                  "no effect": "No Safety Effect", "no safety effect": "No Safety Effect"}

TABLE_NAME = "FHA"
ID_PREFIX = "FHA-"


class FhaError(ValueError):
    """A refused FHA edit; ``status`` is the matching HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Metamodel
# ---------------------------------------------------------------------------

class FhaTable(Package):
    """The functional hazard assessment of the project."""

    kind = "FhaTable"


class FhaEntry(Element):
    """One failure condition of the FHA. Its name is its identifier (``FHA-3``)."""

    kind = "FhaEntry"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.failure_condition: str = ""
        self.flight_phase: str = "All"
        self.effect: str = ""
        self.classification: str = "Major"
        self.fha_function: Optional[Element] = None

    @property
    def dal(self) -> Optional[str]:
        """Assigned DAL: the standard mapping of the classification (None when it is invalid)."""
        return DAL_BY_CLASSIFICATION.get(self.classification)

    @property
    def phases(self) -> list[str]:
        return [p.strip() for p in (self.flight_phase or "").split(",") if p.strip()]

    @property
    def notes(self) -> str:
        return next((a.body for a in self.annotations if isinstance(a, Documentation)), "")

    @notes.setter
    def notes(self, text: Optional[str]) -> None:
        self.annotations = [a for a in self.annotations if not isinstance(a, Documentation)]
        if text:
            self.add_annotation(Documentation(body=str(text)))


# ---------------------------------------------------------------------------
# Normalisation of field values
# ---------------------------------------------------------------------------

def normalize_classification(value: Any) -> str:
    key = str(value or "").strip().lower()
    for c in CLASSIFICATIONS:
        if c.lower() == key:
            return c
    if key in _CLASS_ALIASES:
        return _CLASS_ALIASES[key]
    raise FhaError(f"classification {value!r} is not one of: {', '.join(CLASSIFICATIONS)}")


def normalize_phases(value: Any) -> str:
    """Canonical comma-separated flight phases (``Climb,Cruise``); ``All`` stands for every phase."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "All"
    parts = value if isinstance(value, (list, tuple)) else str(value).replace(";", ",").replace("/", ",").split(",")
    out: list[str] = []
    for part in parts:
        key = str(part).strip()
        if not key:
            continue
        canon = next((p for p in FLIGHT_PHASES if p.lower() == key.lower()), None) \
            or _PHASE_ALIASES.get(key.lower())
        if canon is None:
            raise FhaError(f"flight phase {key!r} is not one of: {', '.join(FLIGHT_PHASES)}")
        if canon not in out:
            out.append(canon)
    if not out or "All" in out:
        return "All"
    return ",".join(p for p in FLIGHT_PHASES if p in out)


def classification_dal(classification: str) -> Optional[str]:
    return DAL_BY_CLASSIFICATION.get(classification)


def _clean_text(value: Any, what: str) -> str:
    text = " ".join(str(value or "").split())
    if "::" in text and what == "id":
        raise FhaError("an FHA id cannot contain '::'")
    return text


# ---------------------------------------------------------------------------
# Table and rows
# ---------------------------------------------------------------------------

def fha_table(repo, *, create: bool = False) -> Optional[FhaTable]:
    """The project's FHA table (created at the project root when ``create``)."""
    hit = next((e for e in repo.root_package.walk() if isinstance(e, FhaTable)), None)
    if hit is not None or not create:
        return hit
    taken = {c.name for c in repo.root_package.owned_elements}
    name = TABLE_NAME if TABLE_NAME not in taken else next(
        f"{TABLE_NAME}_{i}" for i in range(2, 100) if f"{TABLE_NAME}_{i}" not in taken)
    table = FhaTable(name=name)
    repo.root_package.own(table)
    repo.registry.register_tree(table)
    notify_created(table, repo)
    return table


def fha_rows(repo) -> list[FhaEntry]:
    table = fha_table(repo)
    return [e for e in table.owned_elements if isinstance(e, FhaEntry)] if table is not None else []


def find_row(repo, ref: Any) -> FhaEntry:
    """An FHA row by element id, qualified name or FHA id (``FHA-3``)."""
    if isinstance(ref, FhaEntry):
        return ref
    text = str(ref or "").strip()
    hit = repo.by_id(text) or (repo.resolve(text) if text else None)
    if not isinstance(hit, FhaEntry):
        hit = next((r for r in fha_rows(repo) if r.name == text), None)
    if not isinstance(hit, FhaEntry):
        raise FhaError(f"FHA row {ref!r} not found", 404)
    return hit


def _next_id(table: FhaTable) -> str:
    highest = 0
    for e in table.owned_elements:
        name = e.name or ""
        if name.startswith(ID_PREFIX) and name[len(ID_PREFIX):].isdigit():
            highest = max(highest, int(name[len(ID_PREFIX):]))
    return f"{ID_PREFIX}{highest + 1}"


def resolve_function(repo, ref: Any) -> Optional[Element]:
    """A function reference (element, id or qualified name) for an FHA row; None clears it."""
    if ref in (None, ""):
        return None
    e = ref if isinstance(ref, Element) else (repo.by_id(str(ref)) or repo.resolve(str(ref)))
    if e is None:
        raise FhaError(f"function {ref!r} not found", 404)
    if AL.category_of(e) not in ("function", "component"):
        raise FhaError(f"{e.qualified_name!r} is a {e.kind}: an FHA function is a function (action) or a "
                       "component of the functional architecture")
    return e


def add_fha_row(repo, *, failure_condition: str, function: Any = None, flight_phase: Any = "All",
                effect: str = "", classification: Any = "Major", fha_id: Optional[str] = None,
                notes: str = "") -> FhaEntry:
    """Append a failure condition to the FHA (the table is created on first use)."""
    text = _clean_text(failure_condition, "failure condition")
    if not text:
        raise FhaError("a failure condition needs a description")
    cls = normalize_classification(classification)
    phases = normalize_phases(flight_phase)
    func = resolve_function(repo, function)
    table = fha_table(repo, create=True)
    ident = _clean_text(fha_id, "id") if fha_id else _next_id(table)
    if not ident:
        ident = _next_id(table)
    if any(c.name == ident for c in table.owned_elements):
        raise FhaError(f"{ident} already exists in {table.name}", 409)
    row = FhaEntry(name=ident)
    row.failure_condition, row.flight_phase, row.classification = text, phases, cls
    row.effect, row.fha_function = _clean_text(effect, "effect"), func
    if notes:
        row.notes = notes
    table.own(row)
    repo.registry.register_tree(row)
    notify_created(row, repo)
    return row


_UNSET: Any = object()


def update_fha_row(repo, row: Any, *, failure_condition: Any = _UNSET, function: Any = _UNSET,
                   flight_phase: Any = _UNSET, effect: Any = _UNSET, classification: Any = _UNSET,
                   fha_id: Any = _UNSET, notes: Any = _UNSET) -> FhaEntry:
    """Edit an FHA row; every value is checked before anything changes."""
    r = find_row(repo, row)
    changes: dict[str, Any] = {}
    if failure_condition is not _UNSET:
        text = _clean_text(failure_condition, "failure condition")
        if not text:
            raise FhaError("a failure condition needs a description")
        changes["failure_condition"] = text
    if classification is not _UNSET:
        changes["classification"] = normalize_classification(classification)
    if flight_phase is not _UNSET:
        changes["flight_phase"] = normalize_phases(flight_phase)
    if effect is not _UNSET:
        changes["effect"] = _clean_text(effect, "effect")
    if function is not _UNSET:
        changes["fha_function"] = resolve_function(repo, function)
    if fha_id is not _UNSET:
        ident = _clean_text(fha_id, "id")
        if not ident:
            raise FhaError("an FHA id cannot be empty")
        if any(c is not r and c.name == ident for c in (r.owner.owned_elements if r.owner else [])):
            raise FhaError(f"{ident} already exists in {r.owner.name}", 409)
        changes["name"] = ident
    for attr, value in changes.items():
        setattr(r, attr, value)
    if notes is not _UNSET:
        r.notes = str(notes or "")
    return r


def delete_fha_row(repo, row: Any) -> str:
    r = find_row(repo, row)
    ident = r.name
    repo.remove(r)
    return ident


def _ref(e: Optional[Element]) -> Optional[dict]:
    if e is None:
        return None
    return {"id": e.element_id, "name": e.name or f"<{e.kind}>", "kind": e.kind,
            "qualified_name": e.qualified_name}


def function_dal(repo, function: Optional[Element]) -> Optional[str]:
    """The most stringent assigned DAL among the FHA rows of a function (None without rows)."""
    if function is None:
        return None
    dals = [r.dal for r in fha_rows(repo) if r.fha_function is function and r.dal]
    return min(dals, key=AP.dal_rank) if dals else None


def describe_row(repo, row: FhaEntry) -> dict:
    """JSON view of one row, including what its function is allocated to."""
    layers = _allocation_layers(row.fha_function) if row.fha_function is not None else []
    return {
        "id": row.element_id, "fha_id": row.name, "function": _ref(row.fha_function),
        "failure_condition": row.failure_condition, "flight_phase": row.flight_phase,
        "phases": row.phases, "effect": row.effect, "classification": row.classification,
        "dal": row.dal, "probability": PROBABILITY_TARGETS.get(row.classification, ""),
        "notes": row.notes, "allocated": bool(layers),
        "items": [{**_ref(t), "dal": AP.effective_dal(t), "layer": i + 1}
                  for i, layer in enumerate(layers) for t in layer],
        "valid": row.classification in DAL_BY_CLASSIFICATION and _phases_valid(row),
    }


def _phases_valid(row: FhaEntry) -> bool:
    return all(p in FLIGHT_PHASES for p in row.phases)


def function_choices(repo) -> list[dict]:
    """Elements an FHA row can name as its function: actions, and the components of the source
    architecture of an allocation set or of architectures named like a functional one."""
    seen: set[int] = set()
    out: list[Element] = []

    def add(e: Element) -> None:
        if id(e) not in seen and AL.category_of(e) in ("function", "component"):
            seen.add(id(e))
            out.append(e)
    sources = [s.source_architecture for s in AL.allocation_sets(repo) if s.source_architecture is not None]
    for e in repo.root_package.walk():
        if AL.is_function(e):
            add(e)
    for arch in sources:
        for c in arch.walk():
            if isinstance(c, PartUsage) and c is not arch:
                add(c)
    if not out:
        for arch in repo.root_package.walk():
            if isinstance(arch, PartDefinition) and "function" in (arch.name or "").lower():
                for c in components_of(arch):
                    add(c)
    return [_ref(e) | {"category": AL.category_of(e)} for e in out]


# ---------------------------------------------------------------------------
# Allocation chains and DAL decomposition
# ---------------------------------------------------------------------------

def _allocation_layers(function: Optional[Element], depth: int = 4) -> list[list[Element]]:
    """Items a function is allocated to: layer 1 directly, layer 2 what those are allocated to, ..."""
    if function is None:
        return []
    layers: list[list[Element]] = []
    frontier, seen = [function], {id(function)}
    for _ in range(depth):
        nxt: list[Element] = []
        for e in frontier:
            for t in AL.allocated_to(e):
                if id(t) not in seen:
                    seen.add(id(t))
                    nxt.append(t)
        if not nxt:
            break
        layers.append(nxt)
        frontier = nxt
    return layers


def valid_decomposition(required: Any, dals: Iterable[Any]) -> bool:
    """Do two or more independent items with levels ``dals`` satisfy an ARP4754A decomposition of
    ``required``? (A -> A + C or B + B; B -> B + D or C + C; C -> C + E or D + D.)"""
    r = AP.dal_rank(required)
    ranks = sorted(k for k in (AP.dal_rank(d) for d in dals) if k is not None)
    if r is None or r > 2 or len(ranks) < 2:
        return False
    a, b = ranks[0], ranks[1]
    return (a <= r and b <= r + 2) or (a <= r + 1 and b <= r + 1)


# ---------------------------------------------------------------------------
# Issues and rules
# ---------------------------------------------------------------------------

@dataclass
class SafetyIssue(ValidationIssue):
    """A validator issue that also lists the other elements it names."""

    related: tuple = field(default_factory=tuple)


RULES: dict[str, dict] = {
    "avionics.dal.requirement": {
        "title": "Component DAL below its requirement's", "severity": "error",
        "description": "A component implements a requirement of DAL X but is assigned a lower DAL."},
    "avionics.dal.allocation": {
        "title": "Function allocated below its FHA DAL", "severity": "error",
        "description": "A function is allocated to an item of lower DAL than its FHA classification "
                       "demands, and the items do not form a valid DAL decomposition."},
    "avionics.dal.partitioning": {
        "title": "Mixed DAL without partitioning mark", "severity": "warning",
        "description": "Items of different DAL share an IMA module or partition that is not marked as "
                       "providing robust partitioning."},
    "avionics.dal.hosting": {
        "title": "Host DAL below hosted DAL", "severity": "error",
        "description": "An IMA module or partition has a lower DAL than an item it hosts."},
    "avionics.dal.decomposition": {
        "title": "DAL decomposition hint", "severity": "info",
        "description": "Items allocated to a function form a valid decomposition (needs independence "
                       "evidence), or could be decomposed to lower the DAL of the items."},
    "avionics.fha.unallocated": {
        "title": "FHA failure condition without allocated function", "severity": "warning",
        "description": "A failure condition names no function, or its function is not allocated to any item."},
    "avionics.fha.invalid": {
        "title": "Invalid FHA row", "severity": "error",
        "description": "An FHA row holds a classification or flight phase that is not in the standard list."},
    "avionics.equipment.reliability": {
        "title": "MTBF and failure rate disagree", "severity": "info",
        "description": "An equipment gives both MTBF and failure rate (FIT) and they differ by more than 5 %."},
    **RL.RULES,
}


def rule_catalog() -> list[dict]:
    return [{"id": rid, **meta} for rid, meta in RULES.items()]


_SEV = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}


def _issue(sev: str, rule: str, message: str, element: Element, related: Iterable[Element] = ()) -> SafetyIssue:
    rel = tuple(e for e in related if e is not None and e is not element)
    return SafetyIssue(_SEV[sev], rule, message, element, rel)


def _name(e: Optional[Element]) -> str:
    return (getattr(e, "req_id", None) or e.name or f"<{e.kind}>") if e is not None else "?"


def _item_for(source: Element) -> Optional[Element]:
    """The component whose DAL counts for something that implements a requirement."""
    if isinstance(source, (PartUsage, PartDefinition)):
        return source
    if isinstance(source, PortUsage) and isinstance(source.owner, (PartUsage, PartDefinition)):
        return source.owner
    return None


def _check_requirement_dal(repo) -> Iterator[SafetyIssue]:
    index = rq.LinkIndex(repo)
    for req in rq.all_requirements(repo):
        need = AP.normalize_dal(AP.read(req, "dal"))
        rank = AP.dal_rank(need)
        if rank is None or rank >= 4:
            continue
        for link in index.incoming_of_type(req, "implement"):
            item = _item_for(link.source)
            if item is None:
                continue
            have = AP.effective_dal(item)
            if have is None:
                yield _issue("warning", "avionics.dal.requirement",
                             f"{_name(item)} implements {_name(req)} (DAL {need}) but has no DAL assigned: "
                             f"apply an Avionics stereotype and set its dal", item, [req])
            elif not AP.dal_at_least(have, need):
                yield _issue("error", "avionics.dal.requirement",
                             f"{_name(item)} (DAL {have}) implements {_name(req)} which needs DAL {need}: "
                             f"raise the DAL of {_name(item)} to {need} or lower the requirement's", item, [req])


def _compositions(repo) -> Iterator[Element]:
    """Definitions and inline components: where hosted items are owned (usages of a definition
    share the definition's)."""
    for e in repo.root_package.walk():
        if isinstance(e, PartDefinition) or (isinstance(e, PartUsage) and definition_of(e) is None):
            yield e


def _check_hosting(repo) -> Iterator[SafetyIssue]:
    for host in _compositions(repo):
        mark = AP.read(host, "partitioningMark")
        if mark is None:
            continue                    # not an IMA module / partition
        hosted = [(c, AP.effective_dal(c)) for c in components_of(host)]
        hosted = [(c, d) for c, d in hosted if d is not None]
        if not hosted:
            continue
        host_dal = AP.effective_dal(host)
        kind = "partition" if AP.read(host, "partitionId") is not None else "module"
        if host_dal is not None:
            for c, d in hosted:
                if not AP.dal_at_least(host_dal, d):
                    yield _issue("error", "avionics.dal.hosting",
                                 f"{_name(host)} (DAL {host_dal}) hosts {_name(c)} (DAL {d}): a {kind} must be "
                                 f"developed to the highest level it hosts", host, [c])
        levels = sorted({d for _c, d in hosted})
        if len(levels) > 1 and not mark:
            listing = ", ".join(f"{_name(c)} ({d})" for c, d in hosted)
            yield _issue("warning", "avionics.dal.partitioning",
                         f"{_name(host)} hosts items of different DAL ({listing}) without a partitioning "
                         f"mark: tick partitioningMark when robust partitioning is demonstrated, or separate "
                         f"the items", host, [c for c, _d in hosted])


def _check_fha(repo) -> Iterator[SafetyIssue]:
    rows = fha_rows(repo)
    by_function: dict[int, list[FhaEntry]] = {}
    for row in rows:
        if row.classification not in DAL_BY_CLASSIFICATION:
            yield _issue("error", "avionics.fha.invalid",
                         f"{row.name}: classification {row.classification!r} is not one of "
                         f"{', '.join(CLASSIFICATIONS)}", row)
        if not _phases_valid(row):
            yield _issue("error", "avionics.fha.invalid",
                         f"{row.name}: flight phase {row.flight_phase!r} is not a list of "
                         f"{', '.join(FLIGHT_PHASES)}", row)
        if row.fha_function is None:
            yield _issue("warning", "avionics.fha.unallocated",
                         f"{row.name} '{row.failure_condition}' names no function: allocate the failure "
                         f"condition to the function that can cause it", row)
            continue
        by_function.setdefault(id(row.fha_function), []).append(row)
        if not _allocation_layers(row.fha_function, 1):
            yield _issue("warning", "avionics.fha.unallocated",
                         f"{row.name} '{row.failure_condition}': its function {_name(row.fha_function)} is "
                         f"not allocated to any item", row, [row.fha_function])
    done: set[int] = set()
    for row in rows:
        f = row.fha_function
        if f is None or id(f) in done or not row.dal:
            continue
        done.add(id(f))
        group = by_function[id(f)]
        need = function_dal(repo, f)
        ids = ", ".join(r.name for r in group)
        for i, layer in enumerate(_allocation_layers(f), 1):
            items = [(t, AP.effective_dal(t)) for t in layer]
            items = [(t, d) for t, d in items if d is not None]
            if not items:
                continue
            bad = [(t, d) for t, d in items if not AP.dal_at_least(d, need)]
            channels = _channel_groups(items)
            listing = ", ".join(f"{_name(t)} ({d})" for t, d in items)
            if bad:
                # A bad item is fine when it belongs to redundant channels (usages of one
                # definition) whose levels form a valid decomposition of the function's level.
                lone = [(t, d) for t, d in bad
                        if not valid_decomposition(need, [dd for g in channels if any(t is m for m, _x in g)
                                                          for _m, dd in g])]
                if not lone:
                    yield _issue("info", "avionics.dal.decomposition",
                                 f"{_name(f)} needs DAL {need} ({ids}) and is allocated to {listing}: a valid "
                                 f"DAL decomposition if the channels are independent (ARP4754A 5.2.3)",
                                 bad[0][0], [f] + [t for t, _d in items] + group)
                else:
                    names = ", ".join(f"{_name(t)} (DAL {d})" for t, d in lone)
                    yield _issue("error", "avionics.dal.allocation",
                                 f"{_name(f)} needs DAL {need} ({ids}) but is allocated to {names}: raise the "
                                 f"DAL of the item(s) or decompose the function over independent redundant "
                                 f"items", lone[0][0], [f] + [t for t, _d in lone[1:]] + group)
            elif AP.dal_rank(need) is not None and AP.dal_rank(need) <= 1:
                redundant = [g for g in channels if len(g) >= 2]
                if redundant:
                    names = "; ".join(", ".join(f"{_name(t)} ({d})" for t, d in g) for g in redundant)
                    yield _issue("info", "avionics.dal.decomposition",
                                 f"{_name(f)} needs DAL {need} ({ids}) and is allocated to redundant items "
                                 f"{names}: if they are independent, ARP4754A 5.2.3 allows decomposing the level "
                                 f"(for example {_example_split(need)}) and lowering the DAL of the items",
                                 redundant[0][0][0], [f] + [t for g in redundant for t, _d in g][1:] + group)


def _channel_groups(items: list) -> list[list]:
    """Items grouped into redundant channels: usages of one definition form a group."""
    groups: dict[int, list] = {}
    for t, d in items:
        key = definition_of(t) or t
        groups.setdefault(id(key), []).append((t, d))
    return list(groups.values())


def _example_split(level: str) -> str:
    return {"A": "A = A + C or B + B", "B": "B = B + D or C + C", "C": "C = C + E or D + D"}.get(level, "")


def _check_equipment(repo) -> Iterator[SafetyIssue]:
    for e in repo.root_package.walk():
        mtbf, fit = AP.read(e, "mtbf"), AP.read(e, "failureRate")
        if isinstance(mtbf, (int, float)) and isinstance(fit, (int, float)) and mtbf > 0 and fit > 0:
            expected = 1e9 / mtbf
            if abs(fit - expected) > 0.05 * expected:
                yield _issue("info", "avionics.equipment.reliability",
                             f"{_name(e)}: MTBF {mtbf:g} h corresponds to {expected:g} FIT but the failure "
                             f"rate is {fit:g} FIT", e)


def check_avionics(repo) -> Iterator[SafetyIssue]:
    """Every avionics rule, as validator issues (registered with ``register_repo_rule``)."""
    yield from _check_requirement_dal(repo)
    yield from _check_hosting(repo)
    yield from _check_fha(repo)
    yield from _check_equipment(repo)
    for sev, rule, message, element, related in RL.check_requirements(repo):
        yield _issue(sev, rule, message, element, related)


def safety_check(repo, *, severities: Optional[Iterable[str]] = None,
                 rules: Optional[Iterable[str]] = None) -> dict:
    """Run the avionics rules and describe the issues (the Safety / DAL panel and ``sysml_safety_check``).

    Each issue lists the elements it names (``elements``: the main one first) and its rule.
    """
    sev = set(severities) if severities else None
    rset = set(rules) if rules else None
    order = {"error": 0, "warning": 1, "info": 2}
    rows = []
    for i in check_avionics(repo):
        rows.append({
            "severity": i.severity.value, "rule": i.rule, "title": RULES.get(i.rule, {}).get("title", i.rule),
            "message": i.message, "element_id": i.element.element_id, "name": _name(i.element),
            "kind": i.element.kind, "qualified_name": i.element.qualified_name,
            "elements": [_ref(i.element)] + [_ref(e) for e in i.related if e is not i.element],
        })
    rows.sort(key=lambda r: (order.get(r["severity"], 9), r["rule"], r["qualified_name"], r["message"]))
    counts = {s: sum(1 for r in rows if r["severity"] == s) for s in order}
    by_rule: dict[str, int] = {}
    for r in rows:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
    shown = [r for r in rows if (sev is None or r["severity"] in sev) and (rset is None or r["rule"] in rset)]
    return {"issues": shown, "total": len(rows), "counts": counts, "by_rule": by_rule,
            "rules": [{**r, "count": by_rule.get(r["id"], 0)} for r in rule_catalog()]}


# ---------------------------------------------------------------------------
# Persistence and registration
# ---------------------------------------------------------------------------

def _encode(e: Element) -> Any:
    if isinstance(e, FhaEntry):
        return {"function": e.fha_function.element_id if e.fha_function is not None else None,
                "failure_condition": e.failure_condition, "flight_phase": e.flight_phase,
                "effect": e.effect, "classification": e.classification}
    return None


def _decode(e: Element, data: Any, by_id: dict) -> None:
    if isinstance(e, FhaEntry) and isinstance(data, dict):
        e.fha_function = by_id.get(data.get("function") or "")
        e.failure_condition = str(data.get("failure_condition") or "")
        e.flight_phase = str(data.get("flight_phase") or "All")
        e.effect = str(data.get("effect") or "")
        e.classification = str(data.get("classification") or "Major")


def install() -> None:
    """Register the FHA codec, the validator rule and the table reference column (idempotent)."""
    register_codec("avionics.fha", _encode, _decode)
    if check_avionics not in _REPO_RULES:
        register_repo_rule(check_avionics)
    try:                                         # element-valued attribute -> "fha_function ID" column
        from engine.interop.tables import register_reference_attribute
        register_reference_attribute("fha_function")
    except ImportError:                          # pragma: no cover - interop is part of the engine
        pass


install()
