"""Requirements and traceability: the System Composer Requirements Perspective on SysML v2.

Model
-----
- A ``RequirementSet`` (a ``Package``) holds hierarchical requirements:
  ``RequirementDefinition`` elements whose children are nested by ownership.
- Requirement fields (public name -> attribute):

  ===================  =======================  ==========================================
  id                   ``req_id``               auto-numbered per set (prefix + n), unique in the set
  summary              ``name``                 unique among siblings
  description          ``text``
  rationale            ``rationale``
  type                 ``req_type``             functional, performance, interface, safety,
                                                environmental, design-constraint, other
  priority             ``priority``             high, medium, low
  status               ``req_status``           draft, reviewed, approved, implemented, verified
  verification_method  ``verification_method``  test, analysis, inspection, demonstration
  ===================  =======================  ==========================================

  The optional scalars are class-level ``None`` defaults on the requirement
  classes, registered with ``engine.properties.register_scalar_property`` (so
  the generic property editors can set them) and persisted by the
  ``requirements`` codec. Custom attributes come from stereotypes (profiles).
- Test cases are ``VerificationCaseDefinition`` elements with a
  ``verification_result`` (unexecuted / passed / failed).

Trace links
-----------
System Composer link types map onto SysML v2 relationships:

=========  ======================  ===============================================
Implement  ``Satisfy`` (satisfy)   design element -> requirement
Verify     ``Verify``              test case -> requirement
Refine     ``Refine``              requirement -> requirement (source refines destination)
Derive     ``DeriveRequirement``   requirement -> requirement (source derived from destination)
Relate     ``Trace`` (trace)       any linkable element <-> any linkable element
Confirm    ``Confirm`` (new)       any linkable element -> requirement
=========  ======================  ===============================================

Change tracking: when a link is created the hash of each requirement end's
text fields (summary, description, rationale) is stored on the link; when a
requirement changes afterwards the link is *suspect* until cleared. Links made
elsewhere (generic link APIs) are baselined before the next requirement edit
made through this module or the web property editor.

Status: a requirement is *implemented* when it has an Implement link (or all
of its children are implemented); verification status comes from Verify links
from test cases (passed / failed / unexecuted / missing). Both roll up as
leaf percentages per parent and per set.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import sys as _sys
import types as _types
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Optional

from kerml.elements import Documentation, Element, Relationship
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ActionDefinition, ActionUsage,
    AttributeUsage,
    CalculationDefinition, CalculationUsage,
    ConnectionUsage,
    InterfaceDefinition, InterfaceUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage,
    StateDefinition, StateUsage, TransitionUsage,
    VerificationCaseDefinition, VerificationCaseUsage,
)
from sysmlv2.relationships import DeriveRequirement, Refine, Satisfy, Trace, Verify

from .diagram import requirements as _dot_requirements
from .graph_export import _EDGE_SOURCES, register_edge_source
from .hooks import _CREATED_HOOKS, notify_created, register_created_hook
from .links import LinkKind, create_link, link_kind, register_link_kind
from .properties import register_scalar_property
from .serializer import register_codec, register_repo_codec
from .validator import _REPO_RULES, Severity, ValidationIssue, register_repo_rule


class RequirementsError(ValueError):
    """A requirement operation was rejected; the message is meant for the user."""


# ---------------------------------------------------------------------------
# Metamodel
# ---------------------------------------------------------------------------

DEFAULT_PREFIX = "REQ-"


class RequirementSet(Package):
    """A requirement set (System Composer: requirement set / .slreqx file)."""

    kind = "RequirementSet"

    def __init__(self, name: Optional[str] = None, *, prefix: str = DEFAULT_PREFIX, **kwargs):
        super().__init__(name=name, **kwargs)
        self.id_prefix: str = prefix


class Confirm(Relationship):
    """The source (analysis, review record, stakeholder, ...) confirms the destination requirement."""

    kind = "Confirm"

    def __init__(self, source: Element, target: Element, **kwargs):
        super().__init__(source=source, target=target, **kwargs)


REQ_TYPES = ("functional", "performance", "interface", "safety", "environmental",
             "design-constraint", "other")
PRIORITIES = ("high", "medium", "low")
STATUSES = ("draft", "reviewed", "approved", "implemented", "verified")
VERIFICATION_METHODS = ("test", "analysis", "inspection", "demonstration")
TEST_RESULTS = ("unexecuted", "passed", "failed")

ENUMS: dict[str, tuple[str, ...]] = {
    "req_type": REQ_TYPES,
    "priority": PRIORITIES,
    "req_status": STATUSES,
    "verification_method": VERIFICATION_METHODS,
    "verification_result": TEST_RESULTS,
}

_SYNONYMS: dict[str, dict[str, str]] = {
    "req_type": {"func": "functional", "perf": "performance", "if": "interface",
                 "constraint": "design-constraint", "design": "design-constraint",
                 "env": "environmental", "environment": "environmental",
                 "container": "other", "informational": "other", "info": "other"},
    "priority": {"h": "high", "m": "medium", "l": "low", "1": "high", "2": "medium", "3": "low",
                 "critical": "high", "normal": "medium", "med": "medium"},
    "req_status": {"new": "draft", "proposed": "draft", "in-review": "reviewed",
                   "accepted": "approved", "done": "implemented"},
    "verification_method": {"t": "test", "a": "analysis", "i": "inspection", "d": "demonstration",
                            "review": "inspection", "demo": "demonstration", "testing": "test"},
    "verification_result": {"pass": "passed", "ok": "passed", "fail": "failed", "error": "failed",
                            "not-run": "unexecuted", "notrun": "unexecuted", "pending": "unexecuted",
                            "none": "unexecuted"},
}

FIELD_LABELS = {
    "req_id": "ID", "name": "summary", "text": "description", "rationale": "rationale",
    "req_type": "type", "priority": "priority", "req_status": "status",
    "verification_method": "verification method", "verification_result": "test result",
}

# Public field name (and attribute name) -> attribute.
_FIELD_ATTR = {
    "id": "req_id", "req_id": "req_id",
    "summary": "name", "name": "name",
    "description": "text", "text": "text",
    "rationale": "rationale",
    "type": "req_type", "req_type": "req_type",
    "priority": "priority",
    "status": "req_status", "req_status": "req_status",
    "verification_method": "verification_method", "verification": "verification_method",
}
PUBLIC_FIELDS = ("id", "summary", "description", "rationale", "type", "priority", "status",
                 "verification_method")
TEXT_ATTRS = ("name", "text", "rationale")
_EXTRA_ATTRS = ("rationale", "req_type", "priority", "req_status", "verification_method")

# Optional scalars start as class-level None so generic editors (PATCH /api/element,
# sysml_set_property) can set them through engine.properties.
for _cls in (RequirementDefinition, RequirementUsage):
    for _attr in _EXTRA_ATTRS:
        if not hasattr(_cls, _attr):
            setattr(_cls, _attr, None)
for _cls in (VerificationCaseDefinition, VerificationCaseUsage):
    if not hasattr(_cls, "verification_result"):
        setattr(_cls, "verification_result", None)
for _attr in (*_EXTRA_ATTRS, "verification_result"):
    register_scalar_property(_attr)


def is_requirement(e: Any) -> bool:
    return isinstance(e, (RequirementDefinition, RequirementUsage))


def is_test_case(e: Any) -> bool:
    return isinstance(e, (VerificationCaseDefinition, VerificationCaseUsage))


def _is_function(e: Any) -> bool:
    return (isinstance(e, (ActionDefinition, ActionUsage))
            and not isinstance(e, (CalculationDefinition, CalculationUsage, StateDefinition,
                                   StateUsage, TransitionUsage)))


def _is_interface(e: Any) -> bool:
    """Interfaces (port / interface definitions and usages) and their elements (attributes
    owned by an interface definition, e.g. the data elements of an interface dictionary entry)."""
    if isinstance(e, (PortDefinition, InterfaceDefinition, InterfaceUsage)):
        return True
    return isinstance(e, AttributeUsage) and isinstance(e.owner, (PortDefinition, InterfaceDefinition))


# Element categories, in matching order (requirements and test cases are also
# ActionDefinitions, so they must be tested before "functions").
CATEGORIES: list[tuple[str, str, Any]] = [
    ("requirements", "Requirements", is_requirement),
    ("test-cases", "Test cases", is_test_case),
    ("components", "Components", lambda e: isinstance(e, (PartUsage, PartDefinition))),
    ("ports", "Ports", lambda e: isinstance(e, PortUsage)),
    ("connectors", "Connectors", lambda e: isinstance(e, ConnectionUsage)),
    ("interfaces", "Interfaces", _is_interface),
    ("functions", "Functions", _is_function),
]
_CATEGORY_PRED = {key: pred for key, _label, pred in CATEGORIES}


def category_of(e: Any) -> Optional[str]:
    for key, _label, pred in CATEGORIES:
        if pred(e):
            return key
    return None


def is_linkable(e: Any) -> bool:
    return isinstance(e, Element) and category_of(e) is not None


def _describe(e: Element) -> str:
    if is_requirement(e) and getattr(e, "req_id", None):
        return f"{e.req_id} '{e.name or ''}'"
    return f"{e.kind} '{e.name or e.qualified_name}'"


# ---------------------------------------------------------------------------
# Link types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceType:
    name: str            # public name
    label: str           # UI label
    core_kind: str       # engine.links kind used to create it
    cls: type            # relationship class
    verb: str            # "<source> <verb> <target>"
    icon: str
    source: str          # endpoint rule: requirement | test | design | any
    target: str
    description: str


TRACE_TYPES: list[TraceType] = [
    TraceType("implement", "Implement", "satisfy", Satisfy, "implements", "⚙", "design", "requirement",
              "A design element (component, port, connector, interface, function) implements the requirement."),
    TraceType("verify", "Verify", "verify", Verify, "verifies", "✓", "test", "requirement",
              "A test case verifies the requirement."),
    TraceType("refine", "Refine", "refine", Refine, "refines", "⇣", "requirement", "requirement",
              "The source requirement refines (adds detail to) the destination requirement."),
    TraceType("derive", "Derive", "derive", DeriveRequirement, "derives from", "⇡", "requirement",
              "requirement", "The source requirement is derived from the destination requirement."),
    TraceType("relate", "Relate", "trace", Trace, "relates to", "↔", "any", "any",
              "A non-committal relationship between two linkable elements."),
    TraceType("confirm", "Confirm", "confirm", Confirm, "confirms", "☑", "any", "requirement",
              "The source (analysis, review, stakeholder, ...) confirms the destination requirement."),
]
_TYPE_BY_NAME = {t.name: t for t in TRACE_TYPES}
_TYPE_ALIASES = {
    "implements": "implement", "satisfy": "implement", "satisfies": "implement",
    "verifies": "verify", "refines": "refine", "derives_from": "derive", "derive_requirement": "derive",
    "derives": "derive", "trace": "relate", "relates": "relate", "relate_to": "relate",
    "confirms": "confirm",
}
TRACE_CLASSES = tuple(t.cls for t in TRACE_TYPES)

_RULE_TEXT = {
    "requirement": "a requirement",
    "test": "a test case (VerificationCaseDefinition)",
    "design": "a design element (component, port, connector, interface or function)",
    "any": "a linkable element",
}


def trace_type(name: Any) -> TraceType:
    key = str(name or "").strip().lower()
    key = _TYPE_ALIASES.get(key, key)
    tt = _TYPE_BY_NAME.get(key)
    if tt is None:
        raise RequirementsError(f"Unknown link type {name!r}; expected one of: "
                                + ", ".join(t.name for t in TRACE_TYPES))
    return tt


def type_of(rel: Relationship) -> Optional[TraceType]:
    for t in TRACE_TYPES:
        if isinstance(rel, t.cls):
            return t
    return None


def _fits(rule: str, e: Element) -> bool:
    cat = category_of(e)
    if cat is None:
        return False
    if rule == "requirement":
        return cat == "requirements"
    if rule == "test":
        return cat == "test-cases"
    if rule == "design":
        return cat not in ("requirements", "test-cases")
    return True


def _endpoint_problem(tt: TraceType, source: Element, target: Element) -> Optional[str]:
    if source is target:
        return "An element cannot be linked to itself."
    for end, rule, e in (("source", tt.source, source), ("destination", tt.target, target)):
        if not _fits(rule, e):
            hint = ""
            if tt.name == "implement" and is_requirement(e) and end == "source":
                hint = " Use Derive or Refine between requirements."
            elif tt.name == "verify" and end == "source":
                hint = " Add a test case and link it instead."
            return (f"{tt.label} links need {_RULE_TEXT[rule]} as {end}; "
                    f"got {_describe(e)}.{hint}")
    return None


def meta() -> dict:
    """Enumerations, link types and matrix column kinds, for front ends."""
    return {
        "types": list(REQ_TYPES), "priorities": list(PRIORITIES), "statuses": list(STATUSES),
        "verification_methods": list(VERIFICATION_METHODS), "test_results": list(TEST_RESULTS),
        "fields": list(PUBLIC_FIELDS),
        "link_types": [{"name": t.name, "label": t.label, "verb": t.verb, "icon": t.icon,
                        "source": t.source, "target": t.target, "core_kind": t.core_kind,
                        "description": t.description,
                        "source_text": _RULE_TEXT[t.source], "target_text": _RULE_TEXT[t.target]}
                       for t in TRACE_TYPES],
        "column_kinds": [{"key": k, "label": label} for k, label, _p in CATEGORIES],
        "export_formats": ["csv", "reqif", "report-html", "report-csv", "matrix-csv"],
        "import_formats": ["csv", "reqif"],
    }


def _install_link_kinds() -> None:
    if link_kind("confirm") is None:
        register_link_kind(LinkKind("confirm", Confirm,
                                    "Source (analysis, review, ...) confirms the destination requirement.",
                                    aliases=("confirms",)))
    if link_kind("implement") is None:
        register_link_kind(LinkKind("implement", Satisfy,
                                    "System Composer 'Implement': a design element implements a "
                                    "requirement (same relationship as satisfy).",
                                    aliases=("implements",), target_list="satisfied_by"))
    if link_kind("relate") is None:
        register_link_kind(LinkKind("relate", Trace,
                                    "System Composer 'Relate': non-committal link (same relationship "
                                    "as trace).", aliases=("relates",)))


_install_link_kinds()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _doc(e: Element) -> Optional[str]:
    return next((a.body for a in e.annotations if isinstance(a, Documentation)), None)


def _set_doc(e: Element, text: Optional[str]) -> None:
    e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
    if text:
        e.add_annotation(Documentation(body=str(text)))


def _in_repo(repo, e: Element) -> bool:
    return e.root() is repo.root_package


def _unique_name(base: str, taken: set) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"


def _sibling_names(owner: Optional[Element], exclude: Optional[Element] = None) -> set:
    if owner is None:
        return set()
    return {c.name for c in owner.children if c is not exclude and c.name}


def child_requirements(e: Element) -> list[Element]:
    return [c for c in e.children if is_requirement(c)]


def set_of(e: Element) -> Optional[RequirementSet]:
    node = e.owner
    while node is not None:
        if isinstance(node, RequirementSet):
            return node
        node = node.owner
    return None


def requirement_sets(repo) -> list[RequirementSet]:
    return [e for e in repo.root_package.walk() if isinstance(e, RequirementSet)]


def walk_requirements(container: Element, _depth: int = 0, _prefix: str = ""
                      ) -> Iterator[tuple[Element, int, str]]:
    """Pre-order (requirement, depth, index) under a set or requirement; index is '1.2.1'."""
    for i, r in enumerate(child_requirements(container), start=1):
        index = f"{_prefix}{i}"
        yield r, _depth, index
        yield from walk_requirements(r, _depth + 1, index + ".")


def test_cases_in(container: Element) -> list[Element]:
    return [e for e in container.walk() if is_test_case(e) and e is not container]


def all_requirements(repo) -> list[Element]:
    return [e for e in repo.root_package.walk() if is_requirement(e)]


def text_hash(req: Element) -> str:
    payload = json.dumps([req.name or "", getattr(req, "text", None) or "",
                          getattr(req, "rationale", None) or ""])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _detach(repo, e: Element) -> None:
    """Remove `e` from its owner (owned_elements, memberships) without deleting it."""
    m = e.owning_relationship
    if m is None:
        return
    e.detach()
    if m.owning_related_element is None:
        repo.registry.unregister(m)


def _place(repo, e: Element, owner: Element, index: Optional[int] = None) -> None:
    """Move `e` under `owner` (keeping its id, contents and links) at `index` among owned elements."""
    if e.owner is not owner:
        _detach(repo, e)
        owner.own(e)
        repo.registry.register_tree(e)
        if e.owning_relationship is not None:
            repo.registry.register(e.owning_relationship)
    if index is not None:
        items = [x for x in owner.children if x is not e]
        items.insert(max(0, min(index, len(items))), e)
        owner.owned_elements = items


def _position(owner: Element, e: Element) -> int:
    return next(i for i, x in enumerate(owner.children) if x is e)


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------

def normalize_enum(attr: str, value: Any) -> Optional[str]:
    """Validate and normalise an enumerated field (case/spacing/synonyms); '' or None clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequirementsError(f"The {FIELD_LABELS[attr]} must be text, not {type(value).__name__}.")
    v = re.sub(r"[\s_]+", "-", value.strip().lower())
    if not v:
        return None
    v = _SYNONYMS.get(attr, {}).get(v, v)
    if v not in ENUMS[attr]:
        raise RequirementsError(f"Invalid {FIELD_LABELS[attr]} {value!r}; expected one of: "
                                + ", ".join(ENUMS[attr]) + ".")
    return v


def _clean_text(attr: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise RequirementsError(f"The {FIELD_LABELS[attr]} must be text.")
    text = str(value)
    if attr in ("req_id", "name"):
        text = " ".join(text.split())
    return text if text.strip() else None


def _clean_field(attr: str, value: Any) -> Optional[str]:
    if attr in ENUMS:
        return normalize_enum(attr, value)
    return _clean_text(attr, value)


def _field_changes(fields: dict) -> dict:
    changes: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        attr = _FIELD_ATTR.get(key)
        if attr is None:
            raise RequirementsError(f"Unknown requirement field {key!r}; known fields: "
                                    + ", ".join(PUBLIC_FIELDS) + ".")
        changes[attr] = _clean_field(attr, value)
    return changes


def _check_id(req: Element, new_id: Optional[str], rset: Optional[RequirementSet]) -> None:
    if new_id is None:
        raise RequirementsError("The requirement ID cannot be empty.")
    if rset is None:
        return
    for other, _d, _i in walk_requirements(rset):
        if other is not req and (other.req_id or "") == new_id:
            raise RequirementsError(f"ID {new_id!r} is already used by requirement "
                                    f"'{other.name}' in set '{rset.name}'.")


def _check_summary(req: Element, owner: Optional[Element], summary: Optional[str]) -> None:
    if summary is None:
        raise RequirementsError("The requirement summary cannot be empty.")
    if "::" in summary:
        raise RequirementsError("The summary cannot contain '::' (it separates qualified names).")
    if summary in _sibling_names(owner, exclude=req):
        where = owner.name if owner is not None else "the project"
        raise RequirementsError(f"Another element under '{where}' is already called {summary!r}; "
                                "summaries must be unique among siblings.")


def next_req_id(rset: Optional[RequirementSet]) -> str:
    prefix = (rset.id_prefix if rset is not None else DEFAULT_PREFIX) or ""
    highest = 0
    if rset is not None:
        pattern = re.compile(re.escape(prefix) + r"(\d+)$")
        for r, _d, _i in walk_requirements(rset):
            m = pattern.match(r.req_id or "")
            if m:
                highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1}"


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------

def create_requirement_set(repo, name: str, *, prefix: Optional[str] = None,
                           parent: Optional[Element] = None,
                           description: Optional[str] = None) -> RequirementSet:
    name = _clean_text("name", name)
    if not name:
        raise RequirementsError("A requirement set needs a name.")
    if "::" in name:
        raise RequirementsError("The set name cannot contain '::'.")
    owner = parent or repo.root_package
    if not isinstance(owner, Package) or isinstance(owner, RequirementSet):
        raise RequirementsError("Requirement sets live in a package (or the project root), "
                                "not inside another set.")
    if not _in_repo(repo, owner):
        raise RequirementsError("The parent package is not part of this project.")
    if name in _sibling_names(owner):
        raise RequirementsError(f"'{owner.name}' already contains an element called {name!r}.")
    rset = RequirementSet(name=name, prefix=_clean_prefix(prefix))
    if description:
        _set_doc(rset, description)
    owner.own(rset)
    repo.registry.register_tree(rset)
    notify_created(rset, repo)
    return rset


def _clean_prefix(prefix: Any) -> str:
    if prefix is None:
        return DEFAULT_PREFIX
    if not isinstance(prefix, str):
        raise RequirementsError("The ID prefix must be text.")
    prefix = prefix.strip()
    if len(prefix) > 24 or any(c.isspace() for c in prefix):
        raise RequirementsError("The ID prefix must be at most 24 characters without spaces.")
    return prefix


def update_requirement_set(repo, rset: RequirementSet, *, name: Any = None, prefix: Any = None,
                           description: Any = None) -> RequirementSet:
    if not isinstance(rset, RequirementSet):
        raise RequirementsError("Not a requirement set.")
    if name is not None:
        clean = _clean_text("name", name)
        if not clean or "::" in clean:
            raise RequirementsError("The set name cannot be empty or contain '::'.")
        if clean in _sibling_names(rset.owner, exclude=rset):
            raise RequirementsError(f"Another element is already called {clean!r}.")
        rset.name = clean
    if prefix is not None:
        rset.id_prefix = _clean_prefix(prefix)
    if description is not None:
        _set_doc(rset, description or None)
    return rset


def add_requirement(repo, parent: Element, fields: Optional[dict] = None, *,
                    after: Optional[Element] = None) -> Element:
    """Add a requirement under a set or another requirement (optionally right after a sibling)."""
    if not (isinstance(parent, RequirementSet) or is_requirement(parent)):
        raise RequirementsError("Requirements are added to a requirement set or under another "
                                "requirement.")
    if not _in_repo(repo, parent):
        raise RequirementsError("The parent is not part of this project.")
    if after is not None and after.owner is not parent:
        raise RequirementsError("'after' must be a requirement directly under the parent.")
    changes = _field_changes(fields or {})
    rset = parent if isinstance(parent, RequirementSet) else set_of(parent)
    req = RequirementDefinition(name=None)
    req_id = changes.pop("req_id", None) or next_req_id(rset)
    _check_id(req, req_id, rset)
    summary = changes.pop("name", None)
    if summary is None:
        summary = _unique_name("New requirement", _sibling_names(parent))
    _check_summary(req, parent, summary)
    req.req_id, req.name = req_id, summary
    for attr, value in changes.items():
        setattr(req, attr, value)
    parent.own(req)
    if after is not None:
        _place(repo, req, parent, _position(parent, after) + 1)
    repo.registry.register_tree(req)
    notify_created(req, repo)
    return req


def update_requirement(repo, req: Element, fields: dict) -> Element:
    """Validate all `fields` first, then apply them (atomically)."""
    if not is_requirement(req):
        raise RequirementsError(f"{_describe(req)} is not a requirement.")
    changes = _field_changes(fields)
    if "req_id" in changes:
        _check_id(req, changes["req_id"], set_of(req))
    if "name" in changes:
        _check_summary(req, req.owner, changes["name"])
    if any(a in TEXT_ATTRS and changes[a] != getattr(req, a, None) for a in changes):
        baseline_untracked(repo)
    for attr, value in changes.items():
        setattr(req, attr, value)
    return req


def delete_requirement(repo, req: Element) -> list[str]:
    """Delete a requirement with its children and every link touching them (Repository.remove)."""
    if not is_requirement(req) or not _in_repo(repo, req):
        raise RequirementsError("Not a requirement of this project.")
    ids = [e.element_id for e in req.walk() if is_requirement(e)]
    repo.remove(req)
    return ids


def delete_test_case(repo, tc: Element) -> None:
    if not is_test_case(tc) or not _in_repo(repo, tc):
        raise RequirementsError("Not a test case of this project.")
    repo.remove(tc)


def requirement_fields(req: Element) -> dict:
    return {
        "req_id": req.req_id, "summary": req.name, "description": getattr(req, "text", None),
        "rationale": getattr(req, "rationale", None), "type": getattr(req, "req_type", None),
        "priority": getattr(req, "priority", None), "status": getattr(req, "req_status", None),
        "verification_method": getattr(req, "verification_method", None),
    }


def move_requirement(repo, req: Element, direction: str) -> Element:
    """Reorder: 'up' / 'down' among siblings, 'indent' under the previous sibling, 'outdent'."""
    if not is_requirement(req) or req.owner is None:
        raise RequirementsError("Only requirements inside a set can be moved.")
    owner = req.owner
    siblings = child_requirements(owner)
    i = next(k for k, s in enumerate(siblings) if s is req)
    direction = (direction or "").lower()
    if direction == "up":
        if i == 0:
            raise RequirementsError("The requirement is already first among its siblings.")
        _place(repo, req, owner, _position(owner, siblings[i - 1]))
    elif direction == "down":
        if i == len(siblings) - 1:
            raise RequirementsError("The requirement is already last among its siblings.")
        # `req` precedes `nxt`, so nxt's index in the full list is the slot right after nxt
        # once `req` has been taken out (which _place does before inserting).
        nxt = siblings[i + 1]
        _place(repo, req, owner, _position(owner, nxt))
    elif direction == "indent":
        if i == 0:
            raise RequirementsError("Indent needs a previous sibling to become the parent.")
        new_parent = siblings[i - 1]
        if req.name in _sibling_names(new_parent):
            raise RequirementsError(f"'{new_parent.name}' already has a child called {req.name!r}.")
        _place(repo, req, new_parent)
    elif direction == "outdent":
        if not is_requirement(owner) or owner.owner is None:
            raise RequirementsError("Top-level requirements cannot be outdented.")
        grand = owner.owner
        if req.name in _sibling_names(grand):
            raise RequirementsError(f"'{grand.name}' already has a child called {req.name!r}.")
        _place(repo, req, grand, _position(grand, owner) + 1)
    else:
        raise RequirementsError("direction must be one of: up, down, indent, outdent.")
    return req


def add_test_case(repo, parent: Element, name: Any, *, description: Any = None,
                  result: Any = None) -> VerificationCaseDefinition:
    if not isinstance(parent, Package):
        raise RequirementsError("Test cases are added to a requirement set or package.")
    if not _in_repo(repo, parent):
        raise RequirementsError("The parent is not part of this project.")
    clean = _clean_text("name", name) or _unique_name("Test case", _sibling_names(parent))
    if "::" in clean:
        raise RequirementsError("The test case name cannot contain '::'.")
    if clean in _sibling_names(parent):
        raise RequirementsError(f"'{parent.name}' already contains an element called {clean!r}.")
    tc = VerificationCaseDefinition(name=clean)
    tc.verification_result = normalize_enum("verification_result", result) or "unexecuted"
    if description:
        _set_doc(tc, str(description))
    parent.own(tc)
    repo.registry.register_tree(tc)
    notify_created(tc, repo)
    return tc


def update_test_case(repo, tc: Element, fields: dict) -> Element:
    if not is_test_case(tc):
        raise RequirementsError(f"{_describe(tc)} is not a test case.")
    updates: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if key == "name":
            clean = _clean_text("name", value)
            if not clean or "::" in clean:
                raise RequirementsError("The test case name cannot be empty or contain '::'.")
            if clean in _sibling_names(tc.owner, exclude=tc):
                raise RequirementsError(f"Another element is already called {clean!r}.")
            updates["name"] = clean
        elif key == "description":
            updates["description"] = value
        elif key in ("result", "verification_result"):
            updates["result"] = normalize_enum("verification_result", value) or "unexecuted"
        else:
            raise RequirementsError(f"Unknown test case field {key!r}; known: name, description, result.")
    if "name" in updates:
        tc.name = updates["name"]
    if "description" in updates:
        _set_doc(tc, updates["description"] or None)
    if "result" in updates:
        tc.verification_result = updates["result"]
    return tc


def test_result(tc: Element) -> str:
    return getattr(tc, "verification_result", None) or "unexecuted"


# ---------------------------------------------------------------------------
# Trace links and change tracking
# ---------------------------------------------------------------------------

def trace_links(repo) -> list[Relationship]:
    out = []
    for e in repo.root_package.walk():
        for r in e.owned_relationships:
            if isinstance(r, TRACE_CLASSES) and r.source is not None and r.target is not None:
                out.append(r)
    return out


class LinkIndex:
    """All trace links of a project, indexed by endpoint (build once per request)."""

    def __init__(self, repo):
        self.links = trace_links(repo)
        self.incoming: dict[int, list[Relationship]] = defaultdict(list)
        self.outgoing: dict[int, list[Relationship]] = defaultdict(list)
        for r in self.links:
            self.incoming[id(r.target)].append(r)
            self.outgoing[id(r.source)].append(r)

    def touching(self, e: Element) -> list[Relationship]:
        seen, out = set(), []
        for r in self.outgoing.get(id(e), []) + self.incoming.get(id(e), []):
            if id(r) not in seen:
                seen.add(id(r))
                out.append(r)
        return out

    def incoming_of_type(self, e: Element, name: str) -> list[Relationship]:
        tt = _TYPE_BY_NAME[name]
        return [r for r in self.incoming.get(id(e), []) if isinstance(r, tt.cls)]


def _baseline(rel: Relationship) -> dict:
    return {"source": text_hash(rel.source) if is_requirement(rel.source) else None,
            "target": text_hash(rel.target) if is_requirement(rel.target) else None}


def suspect_ends(rel: Relationship) -> list[str]:
    """Which requirement ends ('source' / 'target') changed since the link baseline."""
    base = getattr(rel, "req_baseline", None)
    if not base:
        return []
    out = []
    for end in ("source", "target"):
        e = getattr(rel, end)
        if base.get(end) is not None and is_requirement(e) and text_hash(e) != base[end]:
            out.append(end)
    return out


def is_suspect(rel: Relationship) -> bool:
    return bool(suspect_ends(rel))


def baseline_untracked(repo) -> int:
    """Record the current requirement text for links that have no baseline yet."""
    n = 0
    for rel in trace_links(repo):
        if getattr(rel, "req_baseline", None) is None:
            rel.req_baseline = _baseline(rel)
            n += 1
    return n


def clear_suspect(repo, rel: Relationship) -> Relationship:
    if not isinstance(rel, TRACE_CLASSES):
        raise RequirementsError("Not a trace link.")
    rel.req_baseline = _baseline(rel)
    return rel


def _set_scope(rset: "RequirementSet") -> set[int]:
    """id()s of the requirements and test cases of a set (for link filtering)."""
    return {id(e) for e in rset.walk() if is_requirement(e) or is_test_case(e)}


def clear_suspect_for(repo, element: Optional[Element] = None) -> int:
    """Clear every suspect link touching `element`, the requirements and test cases of a set,
    or the whole project (no element); returns the count."""
    scope = _set_scope(element) if isinstance(element, RequirementSet) else None
    n = 0
    for rel in trace_links(repo):
        if scope is not None:
            if id(rel.source) not in scope and id(rel.target) not in scope:
                continue
        elif element is not None and element is not rel.source and element is not rel.target:
            continue
        if is_suspect(rel):
            clear_suspect(repo, rel)
            n += 1
    return n


def find_link(source: Element, target: Element, tt: TraceType) -> Optional[Relationship]:
    return next((r for r in source.owned_relationships
                 if isinstance(r, tt.cls) and r.source is source and r.target is target), None)


def create_trace_link(repo, link_type: Any, source: Element, target: Element) -> Relationship:
    """Create a validated trace link and record its change-tracking baseline."""
    tt = trace_type(link_type)
    if source is None or target is None:
        raise RequirementsError("Both the source and the destination must exist.")
    for e in (source, target):
        if not _in_repo(repo, e):
            raise RequirementsError(f"{_describe(e)} is not part of this project.")
    problem = _endpoint_problem(tt, source, target)
    if problem:
        raise RequirementsError(problem)
    if find_link(source, target, tt):
        raise RequirementsError(f"{_describe(source)} already {tt.verb} {_describe(target)}.")
    rel = create_link(tt.core_kind, source, target)
    repo.registry.register(rel)
    rel.req_baseline = _baseline(rel)
    return rel


def delete_trace_link(repo, rel: Relationship) -> None:
    if not isinstance(rel, TRACE_CLASSES) or rel.owner is None:
        raise RequirementsError("Not a trace link of this project.")
    src, tgt = rel.source, rel.target
    repo.remove(rel)
    # Keep the convenience back-reference lists (filled by create_link) in step.
    for cls, attr in ((Satisfy, "satisfied_by"), (Verify, "verified_by")):
        if isinstance(rel, cls) and isinstance(getattr(tgt, attr, None), list):
            still = any(isinstance(r, cls) and r.target is tgt for r in src.owned_relationships)
            if not still:
                lst = getattr(tgt, attr)
                for k, x in enumerate(lst):
                    if x is src:
                        del lst[k]
                        break


def link_info(rel: Relationship, perspective: Optional[Element] = None) -> dict:
    tt = type_of(rel)
    ends = suspect_ends(rel)
    out = {
        "id": rel.element_id,
        "type": tt.name if tt else rel.kind.lower(),
        "label": tt.label if tt else rel.kind,
        "verb": tt.verb if tt else "links to",
        "icon": tt.icon if tt else "•",
        "source": element_info(rel.source),
        "target": element_info(rel.target),
        "suspect": bool(ends),
        "suspect_ends": ends,
        "tracked": getattr(rel, "req_baseline", None) is not None,
    }
    if perspective is not None:
        out["direction"] = "outgoing" if rel.source is perspective else "incoming"
        other = rel.target if rel.source is perspective else rel.source
        out["other"] = element_info(other)
    return out


def element_info(e: Element) -> dict:
    d = {"id": e.element_id, "name": e.name, "kind": e.kind, "qualified_name": e.qualified_name,
         "category": category_of(e)}
    if is_requirement(e):
        d["req_id"] = e.req_id
    if is_test_case(e):
        d["result"] = test_result(e)
    return d


def links_for(repo, element: Element, index: Optional[LinkIndex] = None) -> list[dict]:
    index = index or LinkIndex(repo)
    return [link_info(r, element) for r in index.touching(element)]


def all_links(repo, rset: Optional["RequirementSet"] = None, *, suspect_only: bool = False,
              index: Optional[LinkIndex] = None) -> list[dict]:
    """Every trace link of the project, or those touching the requirements / test cases of `rset`
    (System Composer's link list with change information)."""
    index = index or LinkIndex(repo)
    links = index.links
    if rset is not None:
        scope = _set_scope(rset)
        links = [r for r in links if id(r.source) in scope or id(r.target) in scope]
    out = [link_info(r) for r in links]
    return [l for l in out if l["suspect"]] if suspect_only else out


# ---------------------------------------------------------------------------
# Implementation and verification status
# ---------------------------------------------------------------------------

def _ver_state(tests: list[Element]) -> str:
    if not tests:
        return "missing"
    results = [test_result(t) for t in tests]
    if "failed" in results:
        return "failed"
    if all(r == "passed" for r in results):
        return "passed"
    return "unexecuted"


def _pct(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def _status_of(index: LinkIndex, container: Element) -> tuple[dict, dict, dict]:
    """Return (rows by element id, implementation rollup, verification rollup) for a container."""
    rows: dict[str, dict] = {}

    def visit(req: Element, covered: bool, inherited: Optional[list]) -> tuple[int, int, dict]:
        direct = bool(index.incoming_of_type(req, "implement"))
        tests = [r.source for r in index.incoming_of_type(req, "verify") if is_test_case(r.source)]
        covered = covered or direct
        effective = tests if tests else inherited
        kids = child_requirements(req)
        if kids:
            done = total = 0
            counts = {"passed": 0, "failed": 0, "unexecuted": 0, "missing": 0}
            for k in kids:
                d, t, c = visit(k, covered, effective)
                done += d
                total += t
                for key in counts:
                    counts[key] += c[key]
        else:
            done, total = (1 if covered else 0), 1
            counts = {"passed": 0, "failed": 0, "unexecuted": 0, "missing": 0}
            counts[_ver_state(effective or [])] += 1
        if tests:
            state = _ver_state(tests)
        elif counts["failed"]:
            state = "failed"
        elif counts["passed"] == total:
            state = "passed"
        elif counts["missing"] == total:
            state = "missing"
        elif counts["missing"]:
            state = "partial"
        else:
            state = "unexecuted"
        links = index.touching(req)
        rows[req.element_id] = {
            "implementation": {"done": done, "total": total, "pct": _pct(done, total),
                               "implemented": done == total, "direct": direct},
            "verification": {**counts, "total": total, "pct": _pct(counts["passed"], total),
                             "state": state, "direct": bool(tests)},
            "link_count": len(links),
            "suspect_count": sum(1 for r in links if is_suspect(r)),
        }
        return done, total, counts

    done = total = 0
    counts = {"passed": 0, "failed": 0, "unexecuted": 0, "missing": 0}
    for r in child_requirements(container):
        d, t, c = visit(r, False, None)
        done += d
        total += t
        for key in counts:
            counts[key] += c[key]
    impl = {"done": done, "total": total, "pct": _pct(done, total)}
    ver = {**counts, "total": total, "pct": _pct(counts["passed"], total)}
    return rows, impl, ver


def _stereo(e: Element) -> list[dict]:
    return [{"name": a.stereotype.name, "values": a.values} for a in stereotypes_on(e)]


def set_summary(repo, rset: RequirementSet, index: Optional[LinkIndex] = None) -> dict:
    index = index or LinkIndex(repo)
    rows, impl, ver = _status_of(index, rset)
    return {
        "id": rset.element_id, "name": rset.name, "prefix": rset.id_prefix,
        "description": _doc(rset), "qualified_name": rset.qualified_name,
        "count": len(rows), "implementation": impl, "verification": ver,
        "test_case_count": len(test_cases_in(rset)),
        "suspect_count": sum(1 for r in rows.values() if r["suspect_count"]),
    }


def requirement_row(req: Element, depth: int, index_label: str, status: dict) -> dict:
    parent = req.owner
    rset = set_of(req)
    return {
        "id": req.element_id,
        "set_id": rset.element_id if rset else None,
        "parent_id": parent.element_id if is_requirement(parent) else None,
        "depth": depth, "index": index_label,
        "has_children": bool(child_requirements(req)),
        **requirement_fields(req),
        "qualified_name": req.qualified_name,
        "stereotypes": _stereo(req),
        **status,
    }


def test_case_row(repo, tc: Element, index: LinkIndex) -> dict:
    rset = set_of(tc)
    verifies = []
    for r in index.outgoing.get(id(tc), []):
        if isinstance(r, Verify) and is_requirement(r.target):
            verifies.append({"link_id": r.element_id, "id": r.target.element_id,
                             "req_id": r.target.req_id, "summary": r.target.name,
                             "suspect": is_suspect(r)})
    return {"id": tc.element_id, "name": tc.name, "description": _doc(tc),
            "result": test_result(tc), "set_id": rset.element_id if rset else None,
            "qualified_name": tc.qualified_name, "verifies": verifies}


def requirements_table(repo, rset: Optional[RequirementSet] = None) -> dict:
    """Everything the Requirements perspective shows: sets, requirement rows and test cases."""
    index = LinkIndex(repo)
    sets = requirement_sets(repo)
    shown = [rset] if rset is not None else sets
    rows: list[dict] = []
    tests: list[dict] = []
    for s in shown:
        status, _impl, _ver = _status_of(index, s)
        for req, depth, label in walk_requirements(s):
            rows.append(requirement_row(req, depth, label, status[req.element_id]))
        tests += [test_case_row(repo, t, index) for t in test_cases_in(s)]
    links = all_links(repo, rset, index=index)
    return {"sets": [set_summary(repo, s, index) for s in sets],
            "set_id": rset.element_id if rset is not None else None,
            "rows": rows, "test_cases": tests,
            "link_count": len(links), "suspect_link_count": sum(1 for l in links if l["suspect"])}


def requirement_status(repo, target: Optional[Element] = None) -> dict:
    """Roll-up for one set, one requirement (and its subtree) or every set."""
    index = LinkIndex(repo)
    if target is None:
        return {"sets": [set_summary(repo, s, index) for s in requirement_sets(repo)]}
    if isinstance(target, RequirementSet):
        status, _i, _v = _status_of(index, target)
        rows = [requirement_row(r, d, i, status[r.element_id]) for r, d, i in walk_requirements(target)]
        return {"set": set_summary(repo, target, index), "requirements": rows}
    if is_requirement(target):
        # Roll up from the set so coverage inherited from implemented ancestors is counted.
        container = set_of(target) or target.owner
        status, _i, _v = _status_of(index, container)
        out = requirement_row(target, 0, "", status[target.element_id])
        out["links"] = links_for(repo, target, index)
        return {"requirement": out}
    raise RequirementsError(f"{_describe(target)} is neither a requirement set nor a requirement.")


# ---------------------------------------------------------------------------
# Traceability matrix and diagram
# ---------------------------------------------------------------------------

def column_elements(repo, kind: str, column_set: Optional[RequirementSet] = None) -> list[Element]:
    pred = _CATEGORY_PRED.get(kind)
    if pred is None:
        raise RequirementsError(f"Unknown column kind {kind!r}; expected one of: "
                                + ", ".join(k for k, _l, _p in CATEGORIES) + ".")
    if kind == "requirements" and column_set is not None:
        return [r for r, _d, _i in walk_requirements(column_set)]
    return [e for e in repo.root_package.walk() if category_of(e) == kind]


def _label(e: Element) -> str:
    if is_requirement(e):
        return f"{e.req_id or '?'} {e.name or ''}".strip()
    return e.name or f"<{e.kind}>"


def trace_matrix(repo, rset: Optional[RequirementSet] = None, columns: str = "components",
                 column_set: Optional[RequirementSet] = None) -> dict:
    index = LinkIndex(repo)
    if rset is not None:
        row_items = list(walk_requirements(rset))
    else:
        row_items = [x for s in requirement_sets(repo) for x in walk_requirements(s)]
    cols = column_elements(repo, columns, column_set)
    col_ids = {id(c) for c in cols}
    cells: list[dict] = []
    linked_rows, linked_cols = set(), set()
    for req, _d, _i in row_items:
        by_col: dict[str, list] = defaultdict(list)
        for rel in index.touching(req):
            other = rel.target if rel.source is req else rel.source
            if id(other) in col_ids:
                by_col[other.element_id].append(link_info(rel, req))
        for col_id, links in by_col.items():
            cells.append({"row": req.element_id, "col": col_id, "links": links})
            linked_rows.add(req.element_id)
            linked_cols.add(col_id)
    rows = [{"id": r.element_id, "req_id": r.req_id, "summary": r.name, "depth": d, "index": i,
             "linked": r.element_id in linked_rows} for r, d, i in row_items]
    columns_out = [{"id": c.element_id, "name": c.name, "label": _label(c), "kind": c.kind,
                    "qualified_name": c.qualified_name,
                    "context": c.owner.name if c.owner is not None else None,
                    "linked": c.element_id in linked_cols} for c in cols]
    return {
        "set_id": rset.element_id if rset is not None else None,
        "columns_kind": columns,
        "rows": rows, "columns": columns_out, "cells": cells,
        "unlinked_rows": [r["id"] for r in rows if not r["linked"]],
        "unlinked_columns": [c["id"] for c in columns_out if not c["linked"]],
    }


def matrix_csv(repo, rset: Optional[RequirementSet] = None, columns: str = "components",
               column_set: Optional[RequirementSet] = None) -> str:
    m = trace_matrix(repo, rset, columns, column_set)
    cell = {(c["row"], c["col"]): c["links"] for c in m["cells"]}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Index", "ID", "Summary"] + [c["label"] for c in m["columns"]])
    for r in m["rows"]:
        values = []
        for c in m["columns"]:
            links = cell.get((r["id"], c["id"]), [])
            values.append("; ".join(
                f"{'→' if l['direction'] == 'outgoing' else '←'} {l['label']}"
                + (" (suspect)" if l["suspect"] else "") for l in links))
        w.writerow([r["index"], r["req_id"] or "", r["summary"] or ""] + values)
    return buf.getvalue()


_MM_ESCAPES = {"#": "#35;", '"': "#quot;", "<": "#lt;", ">": "#gt;", ";": "#59;", "&": "#38;",
               "|": "#124;", "[": "#91;", "]": "#93;", "{": "#123;", "}": "#125;"}


def _mm(text: Any) -> str:
    """Escape text for a quoted Mermaid label (single pass, so entities are not re-escaped)."""
    s = " ".join(str(text or "").split())
    return re.sub(r'[#"<>;&|\[\]{}]', lambda m: _MM_ESCAPES[m.group(0)], s)


def trace_diagram(repo, element: Element, depth: int = 2, *, max_nodes: int = 120) -> dict:
    """Mermaid flowchart of the trace links around `element` (both directions, depth 1-3)."""
    try:
        depth = max(1, min(3, int(depth)))
    except (TypeError, ValueError):
        raise RequirementsError("depth must be 1, 2 or 3.") from None
    if not _in_repo(repo, element):
        raise RequirementsError("The element is not part of this project.")
    index = LinkIndex(repo)
    order: list[Element] = [element]
    seen = {id(element)}
    frontier = [element]
    truncated = False
    for _ in range(depth):
        nxt = []
        for n in frontier:
            for rel in index.touching(n):
                other = rel.target if rel.source is n else rel.source
                if id(other) not in seen:
                    if len(order) >= max_nodes:
                        truncated = True
                        continue
                    seen.add(id(other))
                    order.append(other)
                    nxt.append(other)
        frontier = nxt
    nid = {id(e): f"n{i}" for i, e in enumerate(order)}
    lines = ["flowchart LR"]
    nodes = []
    for e in order:
        n = nid[id(e)]
        if is_requirement(e):
            lines.append(f'    {n}["{_mm(e.req_id or "REQ")}<br/>{_mm(e.name)}"]')
            cls = "req"
        elif is_test_case(e):
            lines.append(f'    {n}(["Test: {_mm(e.name)}<br/>{_mm(test_result(e))}"])')
            cls = "test_" + test_result(e)
        else:
            lines.append(f'    {n}[["«{_mm(e.kind)}»<br/>{_mm(e.name)}"]]')
            cls = "design"
        lines.append(f"    class {n} {cls}")
        nodes.append({"id": e.element_id, "node": n, "label": _label(e), "kind": e.kind,
                      "category": category_of(e)})
    edges = []
    suspect_idx = []
    for rel in index.links:
        if id(rel.source) in nid and id(rel.target) in nid:
            tt = type_of(rel)
            sus = is_suspect(rel)
            label = ("⚠ " if sus else "") + (tt.verb if tt else rel.kind)
            arrow = "-.->" if sus else "-->"
            lines.append(f'    {nid[id(rel.source)]} {arrow}|"{_mm(label)}"| {nid[id(rel.target)]}')
            if sus:
                suspect_idx.append(len(edges))
            edges.append({"id": rel.element_id, "type": tt.name if tt else None, "suspect": sus,
                          "source": rel.source.element_id, "target": rel.target.element_id})
    lines.append("    classDef req fill:#eef2ff,stroke:#6366f1,color:#1e1b4b")
    lines.append("    classDef design fill:#f8fafc,stroke:#64748b,color:#0f172a")
    lines.append("    classDef test_passed fill:#dcfce7,stroke:#16a34a,color:#14532d")
    lines.append("    classDef test_failed fill:#fee2e2,stroke:#dc2626,color:#7f1d1d")
    lines.append("    classDef test_unexecuted fill:#fef9c3,stroke:#ca8a04,color:#713f12")
    lines.append("    classDef focus stroke-width:3px,stroke:#f59e0b")
    lines.append(f"    class {nid[id(element)]} focus")
    for i in suspect_idx:
        lines.append(f"    linkStyle {i} stroke:#f59e0b,stroke-width:2px")
    return {"element": element.element_id, "depth": depth, "text": "\n".join(lines) + "\n",
            "nodes": nodes, "edges": edges, "truncated": truncated}


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------

MAX_IMPORT_CHARS = 5_000_000

_HEADER_ALIASES = {
    "id": "id", "reqid": "id", "requirementid": "id", "identifier": "id", "foreignid": "id",
    "key": "id", "uid": "id",
    "summary": "summary", "name": "summary", "title": "summary", "chaptername": "summary",
    "heading": "summary",
    "description": "description", "text": "description", "body": "description",
    "requirementtext": "description", "details": "description",
    "rationale": "rationale", "justification": "rationale",
    "type": "type", "requirementtype": "type", "category": "type", "kind": "type",
    "priority": "priority",
    "status": "status", "state": "status",
    "verificationmethod": "verification_method", "verification": "verification_method",
    "method": "verification_method",
    "parentid": "parent_id", "parent": "parent_id",
}
_ENUM_FIELDS = {"type": "req_type", "priority": "priority", "status": "req_status",
                "verification_method": "verification_method"}


def _norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    if h.startswith("reqif."):
        h = h[6:]
    return re.sub(r"[^a-z0-9]", "", h)


def _check_size(text: Any) -> str:
    if not isinstance(text, str):
        raise RequirementsError("The import content must be text.")
    if len(text) > MAX_IMPORT_CHARS:
        raise RequirementsError(f"The import file is too large (limit {MAX_IMPORT_CHARS:,} characters).")
    if not text.strip():
        raise RequirementsError("The import file is empty.")
    return text.lstrip("﻿")


def parse_csv(text: str) -> tuple[list[dict], list[str]]:
    """CSV -> records with canonical keys (id, summary, description, type, priority, parent_id, ...)."""
    text = _check_size(text)
    # Delimiter from the header line only (Excel in many locales writes ';').
    header = text.splitlines()[0] if text.splitlines() else ""
    delimiter = max((",", ";", "\t"), key=header.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter if header.count(delimiter) else ",")
    if not reader.fieldnames:
        raise RequirementsError("The CSV has no header row; expected columns such as "
                                "id, summary, description, type, priority, parent_id.")
    colmap: dict[str, str] = {}
    ignored = []
    for h in reader.fieldnames:
        canon = _HEADER_ALIASES.get(_norm_header(h))
        if canon and canon not in colmap:
            colmap[canon] = h
        elif h and h.strip():
            ignored.append(h)
    if "id" not in colmap and "summary" not in colmap:
        raise RequirementsError("The CSV needs at least an 'id' or a 'summary' column; found: "
                                + ", ".join(reader.fieldnames) + ".")
    records = []
    try:
        for lineno, row in enumerate(reader, start=2):
            rec = {canon: (row.get(h) or "").strip() for canon, h in colmap.items()}
            if not any(rec.values()):
                continue
            rec["_line"] = f"line {lineno}"
            rec["_key"] = rec.get("id") or f"#line{lineno}"
            rec["_parent_key"] = rec.get("parent_id") or None
            rec["_has_parent_col"] = "parent_id" in colmap
            records.append(rec)
    except csv.Error as ex:
        raise RequirementsError(f"Malformed CSV: {ex}") from None
    return records, ignored


def _import_records(repo, records: list[dict], rset: RequirementSet, *, fmt: str,
                    relations: Optional[list[tuple[str, str, str]]] = None) -> dict:
    if not isinstance(rset, RequirementSet):
        raise RequirementsError("Imports go into a requirement set.")
    warnings: list[str] = []
    by_id = {r.req_id: r for r, _d, _i in walk_requirements(rset) if r.req_id}
    by_key: dict[str, Element] = {}
    created = updated = 0
    baseline_untracked(repo)
    for rec in records:
        where = rec.get("_line", "")
        values: dict[str, Any] = {}
        for field in ("summary", "description", "rationale"):
            if rec.get(field):
                values[field] = rec[field]
        if "summary" in values:
            values["summary"] = " ".join(values["summary"].replace("::", ":").split())
        for field, attr in _ENUM_FIELDS.items():
            raw = rec.get(field)
            if raw:
                try:
                    values[field] = normalize_enum(attr, raw)
                except RequirementsError as ex:
                    warnings.append(f"{where}: {ex} The value was ignored.")
        req_id = " ".join((rec.get("id") or "").split()) or None
        existing = by_id.get(req_id) if req_id else None
        try:
            if existing is not None:
                taken = _sibling_names(existing.owner, exclude=existing)
                if values.get("summary") in taken:
                    new = _unique_name(values["summary"], taken)
                    warnings.append(f"{where}: summary {values['summary']!r} renamed to {new!r} "
                                    "(duplicate).")
                    values["summary"] = new
                update_requirement(repo, existing, values)
                req = existing
                updated += 1
            else:
                summary = values.pop("summary", None) or req_id or "Imported requirement"
                taken = _sibling_names(rset)
                if summary in taken:
                    new = _unique_name(summary, taken)
                    warnings.append(f"{where}: summary {summary!r} renamed to {new!r} (duplicate).")
                    summary = new
                fields = {**values, "summary": summary}
                if req_id:
                    fields["id"] = req_id
                req = add_requirement(repo, rset, fields)
                by_id[req.req_id] = req
                created += 1
        except RequirementsError as ex:
            warnings.append(f"{where}: {ex} Row skipped.")
            continue
        by_key[rec["_key"]] = req
    # Hierarchy pass: parents may come after their children in the file.
    for rec in records:
        req = by_key.get(rec["_key"])
        if req is None or not rec.get("_has_parent_col"):
            continue
        pkey = rec.get("_parent_key")
        parent = rset
        if pkey:
            parent = by_key.get(pkey) or by_id.get(pkey)
            if parent is None:
                warnings.append(f"{rec.get('_line', '')}: parent {pkey!r} not found; "
                                f"{req.req_id} stays where it is.")
                continue
        if parent is req or (is_requirement(parent) and any(a is req for a in _ancestors(parent))):
            warnings.append(f"{rec.get('_line', '')}: parent {pkey!r} would create a cycle; ignored.")
            continue
        if req.owner is not parent:
            taken = _sibling_names(parent)
            if req.name in taken:
                new = _unique_name(req.name, taken)
                warnings.append(f"{rec.get('_line', '')}: summary {req.name!r} renamed to {new!r} "
                                "(duplicate under its parent).")
                req.name = new
            _place(repo, req, parent)
    linked = 0
    for type_name, src_key, tgt_key in relations or []:
        src, tgt = by_key.get(src_key), by_key.get(tgt_key)
        if src is None or tgt is None:
            continue
        try:
            create_trace_link(repo, type_name, src, tgt)
            linked += 1
        except RequirementsError as ex:
            warnings.append(f"relation {type_name}: {ex}")
    return {"format": fmt, "set_id": rset.element_id, "set": rset.name, "created": created,
            "updated": updated, "linked": linked, "warnings": warnings}


def _ancestors(e: Element) -> Iterator[Element]:
    node = e.owner
    while node is not None:
        yield node
        node = node.owner


def import_csv(repo, text: str, rset: RequirementSet) -> dict:
    records, ignored = parse_csv(text)
    report = _import_records(repo, records, rset, fmt="csv")
    report["ignored_columns"] = ignored
    return report


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _safe_xml(text: str) -> ET.Element:
    """Parse XML with DTDs and entity declarations forbidden (no XXE / entity expansion)."""
    text = _check_size(text)
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise RequirementsError("ReqIF import refuses XML containing a DOCTYPE or ENTITY "
                                "declaration (entities are not allowed).")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as ex:
        raise RequirementsError(f"Malformed XML: {ex}") from None


def _children(e: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in e if _local(c.tag) == name]


def _child(e: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    if e is None:
        return None
    return next((c for c in e if _local(c.tag) == name), None)


def _ref_text(e: Optional[ET.Element]) -> Optional[str]:
    """Text of the single *-REF child of e (e.g. <TYPE><SPEC-OBJECT-TYPE-REF>x</...></TYPE>)."""
    if e is None:
        return None
    for c in e.iter():
        if _local(c.tag).endswith("-REF") and c.text:
            return c.text.strip()
    return None


def _iter_local(e: ET.Element, name: str) -> Iterator[ET.Element]:
    for c in e.iter():
        if _local(c.tag) == name:
            yield c


def parse_reqif(text: str) -> dict:
    """Minimal ReqIF 1.2 reader: SPEC-OBJECTs with attribute values and SPEC-HIERARCHY nesting."""
    root = _safe_xml(text)
    if _local(root.tag) != "REQ-IF":
        raise RequirementsError(f"Not a ReqIF document (root element is {_local(root.tag)!r}).")
    enum_names = {ev.get("IDENTIFIER"): ev.get("LONG-NAME") or ev.get("IDENTIFIER")
                  for ev in _iter_local(root, "ENUM-VALUE")}
    attr_names: dict[str, str] = {}
    for el in root.iter():
        tag = _local(el.tag)
        if tag.startswith("ATTRIBUTE-DEFINITION-") and not tag.endswith("-REF") and el.get("IDENTIFIER"):
            attr_names[el.get("IDENTIFIER")] = el.get("LONG-NAME") or el.get("IDENTIFIER")
    rel_type_names = {t.get("IDENTIFIER"): t.get("LONG-NAME") or ""
                      for t in _iter_local(root, "SPEC-RELATION-TYPE")}
    objects: dict[str, dict] = {}
    ignored: set[str] = set()
    for so in _iter_local(root, "SPEC-OBJECT"):
        ident = so.get("IDENTIFIER")
        if not ident:
            continue
        rec: dict[str, Any] = {"_key": ident}
        values = _child(so, "VALUES")
        for av in (list(values) if values is not None else []):
            tag = _local(av.tag)
            if not tag.startswith("ATTRIBUTE-VALUE-"):
                continue
            ad = _ref_text(_child(av, "DEFINITION"))
            long_name = attr_names.get(ad or "", ad or "")
            if tag == "ATTRIBUTE-VALUE-XHTML":
                tv = _child(av, "THE-VALUE")
                value = " ".join("".join(tv.itertext()).split()) if tv is not None else ""
            elif tag == "ATTRIBUTE-VALUE-ENUMERATION":
                vals = _child(av, "VALUES")
                refs = [c.text.strip() for c in (vals.iter() if vals is not None else [])
                        if _local(c.tag) == "ENUM-VALUE-REF" and c.text]
                value = ", ".join(enum_names.get(r, r) for r in refs)
            else:
                value = av.get("THE-VALUE") or ""
            canon = _HEADER_ALIASES.get(_norm_header(long_name))
            if canon and canon != "parent_id":
                rec[canon] = value.strip()
            elif long_name:
                ignored.add(long_name)
        if not rec.get("summary") and so.get("LONG-NAME"):
            rec["summary"] = so.get("LONG-NAME")
        objects[ident] = rec
    # Hierarchy (first SPECIFICATION wins the title).
    title = None
    ordered: list[dict] = []
    placed: set[str] = set()

    def walk(container: ET.Element, parent_key: Optional[str]) -> None:
        children = _child(container, "CHILDREN")
        for sh in (_children(children, "SPEC-HIERARCHY") if children is not None else []):
            ref = _ref_text(_child(sh, "OBJECT"))
            if ref in objects and ref not in placed:
                rec = dict(objects[ref])
                rec["_parent_key"] = parent_key
                rec["_has_parent_col"] = True
                rec["_line"] = f"SPEC-OBJECT {ref}"
                ordered.append(rec)
                placed.add(ref)
                walk(sh, ref)
            else:
                walk(sh, parent_key)

    for spec in _iter_local(root, "SPECIFICATION"):
        if title is None:
            title = spec.get("LONG-NAME")
        walk(spec, None)
    for ident, rec in objects.items():
        if ident not in placed:
            ordered.append({**rec, "_parent_key": None, "_has_parent_col": False,
                            "_line": f"SPEC-OBJECT {ident}"})
    if title is None:
        t = next(_iter_local(root, "TITLE"), None)
        title = t.text.strip() if t is not None and t.text else None
    relations = []
    for sr in _iter_local(root, "SPEC-RELATION"):
        tname = rel_type_names.get(_ref_text(_child(sr, "TYPE")) or "", "")
        src, tgt = _ref_text(_child(sr, "SOURCE")), _ref_text(_child(sr, "TARGET"))
        try:
            tt = trace_type(tname)
        except RequirementsError:
            continue
        if src and tgt:
            relations.append((tt.name, src, tgt))
    return {"title": title, "records": ordered, "relations": relations,
            "ignored_attributes": sorted(ignored)}


def import_reqif(repo, text: str, rset: RequirementSet) -> dict:
    parsed = parse_reqif(text)
    report = _import_records(repo, parsed["records"], rset, fmt="reqif",
                             relations=parsed["relations"])
    report["ignored_attributes"] = parsed["ignored_attributes"]
    report["title"] = parsed["title"]
    return report


def import_requirements(repo, fmt: str, text: str, *, rset: Optional[RequirementSet] = None,
                        new_set: Optional[str] = None, prefix: Optional[str] = None) -> dict:
    """Import CSV or ReqIF into `rset`, or into a new set named `new_set` (or the ReqIF title)."""
    fmt = (fmt or "").lower()
    if fmt not in ("csv", "reqif"):
        raise RequirementsError("format must be 'csv' or 'reqif'.")
    if fmt == "reqif":
        parse_reqif(text)  # fail before creating a set for a broken file
    else:
        parse_csv(text)
    if rset is None:
        name = new_set
        if not name and fmt == "reqif":
            name = parse_reqif(text)["title"]
        name = _unique_name((name or "Imported requirements").replace("::", ":"),
                            _sibling_names(repo.root_package))
        rset = create_requirement_set(repo, name, prefix=prefix)
    return import_csv(repo, text, rset) if fmt == "csv" else import_reqif(repo, text, rset)


_EXPORT_COLUMNS = ["id", "summary", "description", "rationale", "type", "priority", "status",
                   "verification_method", "parent_id", "set", "implementation_pct",
                   "verification_status"]


def export_csv(repo, rset: Optional[RequirementSet] = None) -> str:
    index = LinkIndex(repo)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_EXPORT_COLUMNS)
    for s in ([rset] if rset is not None else requirement_sets(repo)):
        status, _i, _v = _status_of(index, s)
        for req, _d, _idx in walk_requirements(s):
            f = requirement_fields(req)
            st = status[req.element_id]
            parent = req.owner if is_requirement(req.owner) else None
            w.writerow([f["req_id"] or "", f["summary"] or "", f["description"] or "", f["rationale"] or "",
                        f["type"] or "", f["priority"] or "", f["status"] or "",
                        f["verification_method"] or "", (parent.req_id or "") if parent else "",
                        s.name, st["implementation"]["pct"], st["verification"]["state"]])
    return buf.getvalue()


REQIF_NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
_REQIF_ATTRS = [("AD-ID", "ReqIF.ForeignID", "req_id"), ("AD-NAME", "ReqIF.Name", "summary"),
                ("AD-TEXT", "ReqIF.Text", "description"), ("AD-RATIONALE", "Rationale", "rationale"),
                ("AD-TYPE", "Type", "type"), ("AD-PRIORITY", "Priority", "priority"),
                ("AD-STATUS", "Status", "status"),
                ("AD-VERIFICATION", "VerificationMethod", "verification_method")]


def _xid(e: Element) -> str:
    return "_" + e.element_id


def export_reqif(repo, rset: Optional[RequirementSet] = None) -> str:
    """ReqIF 1.2 (schema 20110401) document: string attributes, hierarchy and req->req relations."""
    sets = [rset] if rset is not None else requirement_sets(repo)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sub = ET.SubElement
    root = ET.Element("REQ-IF", {"xmlns": REQIF_NS})
    header = sub(sub(root, "THE-HEADER"), "REQ-IF-HEADER", {"IDENTIFIER": "_header"})
    sub(header, "CREATION-TIME").text = now
    sub(header, "REQ-IF-TOOL-ID").text = "SysML v2 Studio"
    sub(header, "REQ-IF-VERSION").text = "1.0"
    sub(header, "SOURCE-TOOL-ID").text = "SysML v2 Studio"
    sub(header, "TITLE").text = sets[0].name if len(sets) == 1 else repo.name
    content = sub(sub(root, "CORE-CONTENT"), "REQ-IF-CONTENT")
    dts = sub(content, "DATATYPES")
    sub(dts, "DATATYPE-DEFINITION-STRING", {"IDENTIFIER": "DT-STRING", "LONG-NAME": "String",
                                            "MAX-LENGTH": "100000", "LAST-CHANGE": now})
    types = sub(content, "SPEC-TYPES")
    sot = sub(types, "SPEC-OBJECT-TYPE", {"IDENTIFIER": "SOT-REQUIREMENT", "LONG-NAME": "Requirement",
                                          "LAST-CHANGE": now})
    attrs = sub(sot, "SPEC-ATTRIBUTES")
    for ident, long_name, _f in _REQIF_ATTRS:
        ad = sub(attrs, "ATTRIBUTE-DEFINITION-STRING", {"IDENTIFIER": ident, "LONG-NAME": long_name,
                                                        "LAST-CHANGE": now})
        sub(sub(ad, "TYPE"), "DATATYPE-DEFINITION-STRING-REF").text = "DT-STRING"
    for tt in TRACE_TYPES:
        sub(types, "SPEC-RELATION-TYPE", {"IDENTIFIER": f"SRT-{tt.name.upper()}", "LONG-NAME": tt.label,
                                          "LAST-CHANGE": now})
    sub(types, "SPECIFICATION-TYPE", {"IDENTIFIER": "ST-SET", "LONG-NAME": "Requirement set",
                                      "LAST-CHANGE": now})
    objs = sub(content, "SPEC-OBJECTS")
    exported: set[int] = set()
    for s in sets:
        for req, _d, _i in walk_requirements(s):
            exported.add(id(req))
            so = sub(objs, "SPEC-OBJECT", {"IDENTIFIER": _xid(req), "LAST-CHANGE": now})
            sub(sub(so, "TYPE"), "SPEC-OBJECT-TYPE-REF").text = "SOT-REQUIREMENT"
            vals = sub(so, "VALUES")
            fields = requirement_fields(req)
            for ident, _ln, field in _REQIF_ATTRS:
                if fields.get(field):
                    av = sub(vals, "ATTRIBUTE-VALUE-STRING", {"THE-VALUE": str(fields[field])})
                    sub(sub(av, "DEFINITION"), "ATTRIBUTE-DEFINITION-STRING-REF").text = ident
    rels = sub(content, "SPEC-RELATIONS")
    for rel in trace_links(repo):
        tt = type_of(rel)
        if tt and id(rel.source) in exported and id(rel.target) in exported:
            sr = sub(rels, "SPEC-RELATION", {"IDENTIFIER": _xid(rel), "LAST-CHANGE": now})
            sub(sub(sr, "TYPE"), "SPEC-RELATION-TYPE-REF").text = f"SRT-{tt.name.upper()}"
            sub(sub(sr, "SOURCE"), "SPEC-OBJECT-REF").text = _xid(rel.source)
            sub(sub(sr, "TARGET"), "SPEC-OBJECT-REF").text = _xid(rel.target)
    specs = sub(content, "SPECIFICATIONS")
    for s in sets:
        spec = sub(specs, "SPECIFICATION", {"IDENTIFIER": _xid(s), "LONG-NAME": s.name or "",
                                            "LAST-CHANGE": now})
        sub(sub(spec, "TYPE"), "SPECIFICATION-TYPE-REF").text = "ST-SET"

        def nest(parent_xml: ET.Element, container: Element) -> None:
            kids = child_requirements(container)
            if not kids:
                return
            holder = sub(parent_xml, "CHILDREN")
            for k in kids:
                sh = sub(holder, "SPEC-HIERARCHY", {"IDENTIFIER": "_h" + k.element_id,
                                                    "LAST-CHANGE": now})
                sub(sub(sh, "OBJECT"), "SPEC-OBJECT-REF").text = _xid(k)
                nest(sh, k)
        nest(spec, s)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export_requirements(repo, fmt: str, rset: Optional[RequirementSet] = None, *,
                        columns: str = "components") -> dict:
    """Export as csv, reqif, report-html, report-csv or matrix-csv; returns {format, filename, text}."""
    fmt = (fmt or "").lower()
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", (rset.name if rset is not None else repo.name) or "requirements")
    if fmt == "csv":
        return {"format": fmt, "filename": f"{base}.csv", "text": export_csv(repo, rset)}
    if fmt == "reqif":
        return {"format": fmt, "filename": f"{base}.reqif", "text": export_reqif(repo, rset)}
    if fmt in ("report-html", "html"):
        return {"format": "report-html", "filename": f"{base}_traceability.html",
                "text": report_html(repo, rset)}
    if fmt == "report-csv":
        return {"format": fmt, "filename": f"{base}_traceability.csv", "text": report_csv(repo, rset)}
    if fmt == "matrix-csv":
        return {"format": fmt, "filename": f"{base}_matrix_{columns}.csv",
                "text": matrix_csv(repo, rset, columns)}
    raise RequirementsError("format must be one of: csv, reqif, report-html, report-csv, matrix-csv.")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def report_csv(repo, rset: Optional[RequirementSet] = None) -> str:
    """One row per (requirement, link); requirements without links get one empty row."""
    index = LinkIndex(repo)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["set", "index", "id", "summary", "implementation_pct", "verification_status",
                "link_type", "direction", "linked_element", "linked_kind", "suspect"])
    for s in ([rset] if rset is not None else requirement_sets(repo)):
        status, _i, _v = _status_of(index, s)
        for req, _d, idx in walk_requirements(s):
            st = status[req.element_id]
            base = [s.name, idx, req.req_id or "", req.name or "", st["implementation"]["pct"],
                    st["verification"]["state"]]
            links = [link_info(r, req) for r in index.touching(req)]
            if not links:
                w.writerow(base + ["", "", "", "", ""])
            for l in links:
                w.writerow(base + [l["label"], l["direction"], _label_of(l["other"]),
                                   l["other"]["kind"], "yes" if l["suspect"] else ""])
    return buf.getvalue()


def _label_of(info: dict) -> str:
    if info.get("req_id"):
        return f"{info['req_id']} {info.get('name') or ''}".strip()
    return info.get("qualified_name") or info.get("name") or ""


_REPORT_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px;color:#0f172a}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}
.meta{color:#64748b;font-size:12px} table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}
th,td{border:1px solid #e2e8f0;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#f1f5f9} .bar{display:inline-block;width:90px;height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;vertical-align:middle}
.bar i{display:block;height:100%;background:#2563eb} .ok{color:#15803d} .bad{color:#b91c1c} .warn{color:#b45309}
.tag{display:inline-block;padding:0 4px;border-radius:3px;background:#eef2ff;color:#3730a3;margin:1px 2px 1px 0}
.cards{display:flex;gap:12px;flex-wrap:wrap} .card{border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;min-width:150px}
.card b{display:block;font-size:18px}
"""


def report_html(repo, rset: Optional[RequirementSet] = None) -> str:
    """Self-contained HTML traceability report (statuses, links, suspect and unlinked items)."""
    esc = html.escape
    index = LinkIndex(repo)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sets = [rset] if rset is not None else requirement_sets(repo)
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>Traceability report - "
             f"{esc(repo.name)}</title><style>{_REPORT_CSS}</style></head><body>",
             f"<h1>Requirements traceability report</h1><div class='meta'>Project {esc(repo.name)} · "
             f"generated {esc(now)}</div>"]
    suspects: dict[str, str] = {}   # link id -> description (a req->req link shows on both rows)
    for s in sets:
        summ = set_summary(repo, s, index)
        status, _i, _v = _status_of(index, s)
        impl, ver = summ["implementation"], summ["verification"]
        parts.append(f"<h2>{esc(s.name)} <span class='meta'>({summ['count']} requirements, "
                     f"{summ['test_case_count']} test cases)</span></h2>")
        parts.append("<div class='cards'>"
                     f"<div class='card'>Implemented<b>{impl['pct']}%</b>{impl['done']} / {impl['total']}</div>"
                     f"<div class='card'>Verified (passed)<b>{ver['pct']}%</b>{ver['passed']} / {ver['total']}</div>"
                     f"<div class='card'>Failed<b class='bad'>{ver['failed']}</b></div>"
                     f"<div class='card'>Not verified<b class='warn'>{ver['missing']}</b></div>"
                     f"<div class='card'>Suspect<b class='warn'>{summ['suspect_count']}</b></div></div>")
        parts.append("<table><tr><th>#</th><th>ID</th><th>Summary</th><th>Type</th><th>Status</th>"
                     "<th>Implementation</th><th>Verification</th><th>Links</th></tr>")
        unlinked = []
        for req, depth, idx in walk_requirements(s):
            st = status[req.element_id]
            links = [link_info(r, req) for r in index.touching(req)]
            if not links:
                unlinked.append(req)
            cells = []
            for l in links:
                arrow = "→" if l["direction"] == "outgoing" else "←"
                flag = " <span class='warn'>⚠ suspect</span>" if l["suspect"] else ""
                cells.append(f"<span class='tag'>{esc(l['label'])}</span>{arrow} "
                             f"{esc(_label_of(l['other']))}{flag}")
                if l["suspect"]:
                    suspects.setdefault(l["id"], f"{esc(_label_of(l['source']))} {esc(l['verb'])} "
                                                 f"{esc(_label_of(l['target']))}")
            vstate = st["verification"]["state"]
            vcls = {"passed": "ok", "failed": "bad"}.get(vstate, "warn")
            parts.append(
                f"<tr><td>{esc(idx)}</td><td>{esc(req.req_id or '')}</td>"
                f"<td style='padding-left:{6 + 14 * depth}px'>{esc(req.name or '')}</td>"
                f"<td>{esc(req.req_type or '')}</td><td>{esc(req.req_status or '')}</td>"
                f"<td><span class='bar'><i style='width:{st['implementation']['pct']}%'></i></span> "
                f"{st['implementation']['pct']}%</td>"
                f"<td class='{vcls}'>{esc(vstate)} ({st['verification']['pct']}%)</td>"
                f"<td>{'<br>'.join(cells) or '<span class=warn>none</span>'}</td></tr>")
        parts.append("</table>")
        if unlinked:
            parts.append("<p class='warn'>Unlinked requirements: "
                         + ", ".join(esc(f"{r.req_id} {r.name}") for r in unlinked) + "</p>")
        tcs = test_cases_in(s)
        if tcs:
            parts.append("<table><tr><th>Test case</th><th>Result</th><th>Verifies</th></tr>")
            for tc in tcs:
                row = test_case_row(repo, tc, index)
                res = row["result"]
                parts.append(f"<tr><td>{esc(tc.name or '')}</td><td class='"
                             f"{ {'passed': 'ok', 'failed': 'bad'}.get(res, 'warn') }'>{esc(res)}</td><td>"
                             + ", ".join(esc(f"{v['req_id']} {v['summary']}") for v in row["verifies"])
                             + "</td></tr>")
            parts.append("</table>")
    parts.append("<h2>Suspect links</h2>")
    parts.append("<ul>" + "".join(f"<li>{s}</li>" for s in suspects.values()) + "</ul>"
                 if suspects else "<p class='ok'>No suspect links.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Persistence, validation, knowledge graph
# ---------------------------------------------------------------------------

def _req_order(e: Element) -> Optional[list[str]]:
    kids = [c.element_id for c in e.children if is_requirement(c) or is_test_case(c)]
    return kids if len(kids) > 1 else None


def _encode(e: Element) -> Optional[dict]:
    out: dict[str, Any] = {}
    if isinstance(e, RequirementSet):
        out["prefix"] = e.id_prefix
    if is_requirement(e):
        for attr in _EXTRA_ATTRS:
            value = e.__dict__.get(attr)
            if value is not None:
                out[attr] = value
    if is_test_case(e) and e.__dict__.get("verification_result") is not None:
        out["verification_result"] = e.verification_result
    if isinstance(e, RequirementSet) or is_requirement(e):
        order = _req_order(e)
        if order:
            out["order"] = order
    return out or None


def _decode(e: Element, data: dict, by_id: dict) -> None:
    if isinstance(e, RequirementSet) and "prefix" in data:
        e.id_prefix = data["prefix"]
    for attr in (*_EXTRA_ATTRS, "verification_result"):
        if attr in data:
            setattr(e, attr, data[attr])
    order = data.get("order")
    if order:
        wanted = [by_id[i] for i in order if i in by_id and by_id[i].owner is e]
        wanted_ids = {id(x) for x in wanted}
        slots = [k for k, x in enumerate(e.children) if id(x) in wanted_ids]
        items = list(e.children)
        for slot, x in zip(slots, wanted):
            items[slot] = x
        e.owned_elements = items


def _encode_links(repo) -> Optional[dict]:
    out = {}
    for rel in trace_links(repo):
        base = getattr(rel, "req_baseline", None)
        if base is not None:
            out[rel.element_id] = base
    return out or None


def _decode_links(repo, data: dict, by_id: dict) -> None:
    for rel_id, base in (data or {}).items():
        rel = repo.by_id(rel_id)
        if isinstance(rel, Relationship) and isinstance(base, dict):
            rel.req_baseline = {"source": base.get("source"), "target": base.get("target")}


def _validation_problem(tt: Optional[TraceType], rel: Relationship) -> Optional[str]:
    """Endpoint rules for links made elsewhere (e.g. the generic link dialog).

    Only the requirement-specific ends are checked: generic SysML satisfy/trace links from
    arbitrary model elements stay legal, but a link that cannot count toward status is flagged.
    """
    if tt is None or tt.name == "relate":
        return None
    for end, rule, e in (("source", tt.source, rel.source), ("destination", tt.target, rel.target)):
        if rule in ("requirement", "test") and not _fits(rule, e):
            return (f"{tt.label} links need {_RULE_TEXT[rule]} as {end}; got {_describe(e)}. "
                    "It does not count toward requirement status.")
    return None


def validate_repo(repo) -> Iterator[ValidationIssue]:
    index = LinkIndex(repo)
    for rel in index.links:
        tt = type_of(rel)
        ends = suspect_ends(rel)
        if ends:
            changed = getattr(rel, ends[0])
            yield ValidationIssue(
                Severity.WARNING, "requirements.suspect-link",
                f"{tt.label} link {_describe(rel.source)} {tt.verb} {_describe(rel.target)} is "
                f"suspect: {_describe(changed)} changed after the link was made. Review the link "
                "and clear the suspect flag.", changed)
        problem = _validation_problem(tt, rel)
        if problem:
            yield ValidationIssue(Severity.WARNING, "requirements.link-endpoint", problem, rel.source)
    for rset in requirement_sets(repo):
        seen: dict[str, Element] = {}
        status, _i, _v = _status_of(index, rset)
        for req, _d, _idx in walk_requirements(rset):
            rid = req.req_id
            if not rid:
                yield ValidationIssue(Severity.WARNING, "requirements.missing-id",
                                      "Requirement has no ID.", req)
            elif rid in seen:
                yield ValidationIssue(Severity.ERROR, "requirements.duplicate-id",
                                      f"ID {rid!r} is used more than once in set '{rset.name}'.", req)
            else:
                seen[rid] = req
            st = status[req.element_id]
            claimed = getattr(req, "req_status", None)
            if claimed in ("implemented", "verified") and not st["implementation"]["implemented"]:
                yield ValidationIssue(Severity.WARNING, "requirements.status-mismatch",
                                      f"Status is '{claimed}' but the requirement is only "
                                      f"{st['implementation']['pct']}% implemented.", req)
            if claimed == "verified" and st["verification"]["state"] != "passed":
                yield ValidationIssue(Severity.WARNING, "requirements.status-mismatch",
                                      f"Status is 'verified' but verification is "
                                      f"'{st['verification']['state']}'.", req)
    for e in repo.root_package.walk():
        attrs = _EXTRA_ATTRS if is_requirement(e) else ("verification_result",) if is_test_case(e) else ()
        for attr in attrs:
            if attr not in ENUMS:
                continue
            value = getattr(e, attr, None)
            if value is not None and value not in ENUMS[attr]:
                yield ValidationIssue(Severity.ERROR, "requirements.invalid-value",
                                      f"Invalid {FIELD_LABELS[attr]} {value!r}; expected one of: "
                                      + ", ".join(ENUMS[attr]) + ".", e)


def _on_created(element: Element, repo) -> None:
    """Requirements created inside a set by generic paths (core toolbar, POST /api/element,
    sysml_create_element) get the set's next ID, as if added in the Requirements editor."""
    if is_requirement(element) and not getattr(element, "req_id", None):
        rset = set_of(element)
        if rset is not None:
            element.req_id = next_req_id(rset)


def _confirm_edges(e: Element):
    for r in e.owned_relationships:
        if isinstance(r, Confirm) and r.source is not None and r.target is not None:
            yield ("confirms", r.source, r.target, {})


def install() -> None:
    """Register codecs, rules and graph edges (idempotent; safe to call again)."""
    _install_link_kinds()
    register_codec("requirements", _encode, _decode)
    register_repo_codec("requirements-links", _encode_links, _decode_links)
    if validate_repo not in _REPO_RULES:
        register_repo_rule(validate_repo)
    if _confirm_edges not in _EDGE_SOURCES:
        register_edge_source(_confirm_edges)
    if _on_created not in _CREATED_HOOKS:
        register_created_hook(_on_created)


install()


# ``engine/__init__.py`` re-exports the DOT requirements diagram as ``engine.requirements``;
# importing this submodule rebinds that package attribute to the module (Python import
# semantics). Make the module callable so ``from engine import requirements;
# requirements(root)`` keeps returning the DOT diagram whatever the import order.
# Use ``import engine.requirements as rq`` (not ``from engine import requirements``) for this API.
class _CallableModule(_types.ModuleType):
    def __call__(self, *args, **kwargs):
        return _dot_requirements(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableModule
