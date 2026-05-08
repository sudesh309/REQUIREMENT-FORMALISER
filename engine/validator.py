"""Well-formedness validator for KerML / SysML v2 models.

The rules implemented here are a useful subset of the OMG specification's
constraints — the kind a tool like Cameo enforces during model
development.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from kerml.elements import Element
from kerml.features import Feature
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


class Validator:
    """Run a sequence of rules on a Repository and collect issues."""

    def validate(self, repo: "Repository") -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for elem in repo.all_elements():
            issues.extend(self._check_element(elem))
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
        if isinstance(f, Type) and f.specializations:
            return []
        return [ValidationIssue(
            Severity.WARNING, "feature.typed",
            "Feature has no FeatureTyping (will default to Anything)",
            f,
        )]

    def _rule_multiplicity_sane(self, f: Feature) -> list[ValidationIssue]:
        m = f.multiplicity
        if m.lower < 0:
            return [ValidationIssue(Severity.ERROR, "multiplicity.lower",
                                    "Lower bound must be >= 0", f)]
        if m.upper is not None and m.upper < m.lower:
            return [ValidationIssue(Severity.ERROR, "multiplicity.upper",
                                    "Upper bound must be >= lower bound", f)]
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
                        f"Redefining feature must be typed by a subtype of "
                        f"{t_red.qualified_name!r}", f,
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
            "Usage is typically typed by a SysML Definition",
            u,
        )]

    def _rule_connection_has_two_ends(self, c: ConnectionUsage) -> list[ValidationIssue]:
        if len(c.ends) >= 2:
            return []
        return [ValidationIssue(
            Severity.ERROR, "connection.ends",
            f"ConnectionUsage must have at least 2 ends (has {len(c.ends)})", c,
        )]

    def _rule_port_has_definition(self, p: PortUsage) -> list[ValidationIssue]:
        if p.feature_typings:
            return []
        return [ValidationIssue(
            Severity.WARNING, "port.typed",
            "PortUsage should be typed by a PortDefinition", p,
        )]

    def _rule_requirement_has_text_or_constraint(self, r) -> list[ValidationIssue]:
        text = getattr(r, "text", None)
        constraints = getattr(r, "required_constraints", []) or []
        if text or constraints:
            return []
        return [ValidationIssue(
            Severity.INFO, "requirement.empty",
            "Requirement has neither text nor required constraints", r,
        )]
