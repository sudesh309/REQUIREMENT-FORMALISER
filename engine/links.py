"""Centralized link registry + helpers for creating typed relationships.

This is the single place that knows the full set of SysML v2 link kinds
and how to create them. Useful from:

- the GUI's "Link..." dialog (lists all kinds in a combobox),
- the MCP server's `sysml_link` tool (LLMs can ask for any link by name),
- the parser, builder, validator, KG-export, and DOT-export modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from kerml.elements import Element, Relationship
from kerml.features import Feature, FeatureTyping, Redefinition, Subsetting
from kerml.namespaces import Import, Membership
from kerml.types import Specialization, Conjugation
from sysmlv2.definitions import (
    AllocationUsage as _AllocationUsage,
    RequirementDefinition,
    RequirementUsage,
)
from sysmlv2.relationships import (
    ActorOf,
    Allocation,
    AssumeConstraint,
    Copy,
    DeriveRequirement,
    Exposes,
    FramedConcern,
    ParameterBinding,
    Refine,
    RequireConstraint,
    Satisfy,
    StakeholderOf,
    SubjectOf,
    Trace,
    Verify,
)


@dataclass(frozen=True)
class LinkKind:
    """One row in the link registry."""
    name: str                       # public name (used by GUI / MCP / parser)
    cls: type[Relationship]         # relationship class
    description: str                # human-readable summary
    aliases: tuple[str, ...] = ()
    # Optional side-effect: also append to a list-attribute on `source` / `target`.
    source_list: Optional[str] = None   # attribute on source receiving target
    target_list: Optional[str] = None   # attribute on target receiving source


LINK_KINDS: list[LinkKind] = [
    LinkKind("satisfy",       Satisfy,
             "A model element satisfies a Requirement.",
             aliases=("satisfies",),
             target_list="satisfied_by"),
    LinkKind("verify",        Verify,
             "A VerificationCase verifies a Requirement.",
             aliases=("verifies",),
             target_list="verified_by"),
    LinkKind("refine",        Refine,
             "A model element refines another (less to more detailed).",
             aliases=("refines",)),
    LinkKind("trace",         Trace,
             "A non-committal traceability link between two elements."),
    LinkKind("derive",        DeriveRequirement,
             "A derived Requirement obtained from a source.",
             aliases=("derive_requirement", "derives_from")),
    LinkKind("copy",          Copy,
             "Source is a textual copy of target."),
    LinkKind("allocate",      Allocation,
             "Allocates source to target (logical→physical, function→component, ...).",
             aliases=("allocation",)),
    LinkKind("subject",       SubjectOf,
             "Marks the subject of a requirement / case / view.",
             aliases=("subject_of",),
             source_list="subject_links",
             target_list="subject_of_requirements"),
    LinkKind("stakeholder",   StakeholderOf,
             "Records a stakeholder for a requirement.",
             aliases=("stakeholder_of",)),
    LinkKind("actor",         ActorOf,
             "Records an actor for a requirement / use case.",
             aliases=("actor_of",)),
    LinkKind("framed_concern", FramedConcern,
             "Identifies a Concern framed by a requirement / viewpoint."),
    LinkKind("parameter_binding", ParameterBinding,
             "Binds two parameters across an invocation."),
    LinkKind("assume",        AssumeConstraint,
             "Requirement assumes a Constraint.",
             aliases=("assume_constraint",)),
    LinkKind("require",       RequireConstraint,
             "Requirement requires a Constraint.",
             aliases=("require_constraint",)),
    LinkKind("expose",        Exposes,
             "View exposes a model element.",
             aliases=("exposes",)),
]


# Lookup helpers -------------------------------------------------------------

_BY_NAME: dict[str, LinkKind] = {}
for lk in LINK_KINDS:
    _BY_NAME[lk.name] = lk
    for alias in lk.aliases:
        _BY_NAME[alias] = lk


def list_link_kinds() -> list[str]:
    return [lk.name for lk in LINK_KINDS]


def link_kind(name: str) -> Optional[LinkKind]:
    return _BY_NAME.get(name.lower())


def create_link(kind: str, source: Element, target: Element,
                *, container: Optional[Element] = None) -> Relationship:
    """Create a relationship of the given kind from source to target.

    The relationship is owned by `container` (default: `source`), so that
    deleting the source also removes its outgoing links.
    """
    lk = link_kind(kind)
    if lk is None:
        raise ValueError(f"Unknown link kind {kind!r}. "
                         f"Known: {sorted(_BY_NAME)}")
    rel = lk.cls(source, target)
    owner = container or source
    owner.add_relationship(rel)
    if lk.source_list and hasattr(source, lk.source_list):
        getattr(source, lk.source_list).append(target)
    if lk.target_list and hasattr(target, lk.target_list):
        getattr(target, lk.target_list).append(source)
    return rel


def links_of(element: Element,
             *, direction: str = "outgoing",
             kind: Optional[str] = None) -> list[Relationship]:
    """Return relationships touching `element`.

    direction: 'outgoing' | 'incoming' | 'both'
    """
    wanted = link_kind(kind).cls if kind else Relationship
    # Structural relationships handled elsewhere; exclude unless asked by kind.
    structural = (Membership, Import, Specialization, Conjugation,
                  FeatureTyping, Subsetting, Redefinition)
    out: list[Relationship] = []
    seen: set[str] = set()

    def _take(rel: Relationship) -> None:
        if rel.element_id in seen:
            return
        if not isinstance(rel, wanted):
            return
        if kind is None and isinstance(rel, structural):
            return
        out.append(rel)
        seen.add(rel.element_id)

    if direction in ("outgoing", "both"):
        for r in getattr(element, "owned_relationships", []):
            if isinstance(r, Relationship) and r.source is element:
                _take(r)
    if direction in ("incoming", "both"):
        # Walk the whole project root looking for relationships pointing here.
        root = element
        while root.owner is not None:
            root = root.owner
        for e in root.walk():
            for r in getattr(e, "owned_relationships", []):
                if isinstance(r, Relationship) and r.target is element:
                    _take(r)
    return out


def describe_link(rel: Relationship) -> dict:
    """JSON-friendly summary of a relationship."""
    name = None
    for lk in LINK_KINDS:
        if isinstance(rel, lk.cls):
            name = lk.name
            break
    return {
        "id": rel.element_id,
        "kind": name or rel.kind,
        "source_id": rel.source.element_id if rel.source else None,
        "source": rel.source.qualified_name if rel.source else None,
        "target_id": rel.target.element_id if rel.target else None,
        "target": rel.target.qualified_name if rel.target else None,
    }
