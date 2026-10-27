"""Well-formedness validator for KerML / SysML v2 models.

The rules implemented here are a useful subset of the OMG specification's
constraints — the kind a tool like Cameo enforces during model
development.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Iterable

from kerml.elements import Element
from kerml.features import Feature
from kerml.stereotypes import StereotypeTag
from kerml.types import Type
from sysmlv2.definitions import (
    ConnectionUsage,
    Definition,
    PortUsage,
    RequirementDefinition,
    RequirementUsage,
    Usage,
)

if TYPE_CHECKING:
    from .repository import Repository


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationIssue:
    severity: Severity
    rule: str
    message: str
    element: Element

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()}] {self.rule}: {self.message} ({self.element.qualified_name})"


# Feature modules add checks with register_rule(fn(element) -> iterable of
# ValidationIssue) or register_repo_rule(fn(repo) -> iterable of ValidationIssue).
_ELEMENT_RULES: list[Callable[[Element], Iterable["ValidationIssue"]]] = []
_REPO_RULES: list[Callable[["Repository"], Iterable["ValidationIssue"]]] = []


def register_rule(fn: Callable[[Element], Iterable["ValidationIssue"]]) -> None:
    _ELEMENT_RULES.append(fn)


def register_repo_rule(fn: Callable[["Repository"], Iterable["ValidationIssue"]]) -> None:
    _REPO_RULES.append(fn)


def element_label(e: Element) -> str:
    """How an issue message names an element: ``'ADIRU'``, a requirement's id, or the kind
    and owner of an unnamed element (``unnamed ConnectionUsage in 'FlightDeck'``)."""
    name = e.name or getattr(e, "req_id", None)
    if name:
        return repr(name)
    owner = e.owner.name if e.owner is not None and e.owner.name else None
    return f"unnamed {e.kind}" + (f" in {owner!r}" if owner else "")


class Validator:
    """Run a sequence of rules on a Repository and collect issues."""

    def validate(self, repo: "Repository") -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for elem in repo.all_elements():
            issues.extend(self._check_element(elem))
            for rule in _ELEMENT_RULES:
                issues.extend(rule(elem) or [])
        for rule in _REPO_RULES:
            issues.extend(rule(repo) or [])
        return issues

    # --- per-element rules -------------------------------------------
    def _check_element(self, e: Element) -> list[ValidationIssue]:
        out: list[ValidationIssue] = []
        out.extend(self._rule_unique_member_names(e))
        if isinstance(e, Feature):
            out.extend(self._rule_feature_typed(e))
            out.extend(self._rule_multiplicity_sane(e))
            out.extend(self._rule_redefinition_conformance(e))
        if isinstance(e, Usage):
            out.extend(self._rule_usage_typed_by_definition(e))
        if isinstance(e, ConnectionUsage):
            out.extend(self._rule_connection_has_two_ends(e))
        if isinstance(e, PortUsage):
            out.extend(self._rule_port_has_definition(e))
        if isinstance(e, (RequirementDefinition, RequirementUsage)):
            out.extend(self._rule_requirement_has_text_or_constraint(e))
        return out

    # ------------------------------------------------------------------
    def _rule_unique_member_names(self, e: Element) -> list[ValidationIssue]:
        from kerml.namespaces import Namespace
        if not isinstance(e, Namespace):
            return []
        seen: dict[str, Element] = {}
        issues: list[ValidationIssue] = []
        for m in e.memberships:
            name = m.alias or m.member.name
            if name is None:
                continue
            if name in seen and seen[name] is not m.member:
                issues.append(ValidationIssue(
                    Severity.ERROR, "name.unique",
                    f"Duplicate member name {name!r} in namespace {e.qualified_name!r}",
                    m.member,
                ))
            seen[name] = m.member
        return issues

    def _rule_feature_typed(self, f: Feature) -> list[ValidationIssue]:
        if f.is_abstract or f.feature_typings:
            return []
        # A SysML usage without a definition is implicitly typed by its library base
        # (Parts::Part, Ports::Port, Connections::Connection, Actions::Action,
        # Attributes::AttributeValue, ...), so inline components, connectors, ports without
        # an interface, inline functions, states and transitions are ordinary models, not
        # gaps; untyped ports have their own rule (port.typed). Stereotype tags are typed
        # by their property type. Only a plain KerML feature really defaults to Anything.
        if isinstance(f, (Usage, StereotypeTag)):
            return []
        if isinstance(f, Type) and f.specializations:
            return []
        return [ValidationIssue(
            Severity.WARNING, "feature.typed",
            f"Feature {element_label(f)} has no type (it defaults to Anything)",
            f,
        )]

    def _rule_multiplicity_sane(self, f: Feature) -> list[ValidationIssue]:
        m = f.multiplicity
        if m.lower < 0:
            return [ValidationIssue(Severity.ERROR, "multiplicity.lower",
                                    f"Lower bound of {element_label(f)} must be >= 0", f)]
        if m.upper is not None and m.upper < m.lower:
            return [ValidationIssue(Severity.ERROR, "multiplicity.upper",
                                    f"Upper bound of {element_label(f)} must be >= its lower "
                                    f"bound ({m.lower})", f)]
        return []

    def _rule_redefinition_conformance(self, f: Feature) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for r in f.redefinitions:
            redefined = r.target
            if not isinstance(redefined, Feature):
                continue
            for t_red in redefined.types:
                if not any(t.conforms_to(t_red) for t in f.types):
                    issues.append(ValidationIssue(
                        Severity.ERROR, "redefinition.conformance",
                        f"{element_label(f)} redefines {element_label(redefined)}, so it must be "
                        f"typed by a subtype of {t_red.qualified_name!r}", f,
                    ))
        return issues

    def _rule_usage_typed_by_definition(self, u: Usage) -> list[ValidationIssue]:
        if not u.feature_typings:
            return []
        if any(isinstance(t, Definition) for t in u.types):
            return []
        # Allow typing by primitive KerML types and abstract supertypes.
        if any(t.name in {"Boolean", "String", "Integer", "Real", "Natural"} for t in u.types):
            return []
        return [ValidationIssue(
            Severity.WARNING, "usage.typing",
            f"{u.kind} {element_label(u)} is typed by "
            f"{', '.join(repr(t.name or t.kind) for t in u.types)}; a usage is typically typed "
            "by a SysML definition",
            u,
        )]

    def _rule_connection_has_two_ends(self, c: ConnectionUsage) -> list[ValidationIssue]:
        if len(c.ends) >= 2:
            return []
        return [ValidationIssue(
            Severity.ERROR, "connection.ends",
            f"Connector {element_label(c)} must have at least 2 ends (has {len(c.ends)})", c,
        )]

    def _rule_port_has_definition(self, p: PortUsage) -> list[ValidationIssue]:
        if p.feature_typings:
            return []
        return [ValidationIssue(
            Severity.WARNING, "port.typed",
            f"Port {element_label(p)} has no interface (it should be typed by a port "
            "definition)", p,
        )]

    def _rule_requirement_has_text_or_constraint(self, r) -> list[ValidationIssue]:
        text = getattr(r, "text", None)
        constraints = getattr(r, "required_constraints", []) or []
        if text or constraints:
            return []
        return [ValidationIssue(
            Severity.INFO, "requirement.empty",
            f"Requirement {element_label(r)} has neither text nor required constraints", r,
        )]
