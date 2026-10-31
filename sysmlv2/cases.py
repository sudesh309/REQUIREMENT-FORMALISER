"""Asserted constraints, satisfied requirements, concerns, objectives and included use cases.

SysML 8.3.20.2 (AssertConstraintUsage), 8.3.21 (SatisfyRequirementUsage,
FramedConcernMembership), 8.3.22.4 (ObjectiveMembership), 8.3.24.2
(RequirementVerificationMembership) and 8.3.25.2 (IncludeUseCaseUsage).

``assert c``, ``satisfy r by f`` and ``include u`` reference the asserted,
satisfied or included usage through an owned ReferenceSubsetting (the
constructor keywords build it); without one the usage is its own target.
The memberships own the objective of a case, a framed concern or a verified
requirement.
"""
from __future__ import annotations

from typing import Optional

from kerml.connectors import BindingConnector
from kerml.expressions import Invariant
from kerml.features import Feature
from kerml.types import FeatureMembership

from .actions import PerformActionUsage, referenced_feature_target
from .definitions import ConcernUsage, ConstraintUsage, RequirementUsage, UseCaseUsage

REQUIREMENT_CONSTRAINT_KINDS = ("assumption", "requirement")


class AssertConstraintUsage(ConstraintUsage, Invariant):
    """``assert c``: asserts a constraint (``not`` when ``is_negated``) (SysML 8.3.20.2)."""

    kind = "AssertConstraintUsage"

    def __init__(self, name: Optional[str] = None, *,
                 asserted_constraint: Optional[Feature] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if asserted_constraint is not None:
            self.reference_subset(asserted_constraint)

    @property
    def asserted_constraint(self) -> Optional[ConstraintUsage]:
        """The feature target of the owned ReferenceSubsetting if a ConstraintUsage (None if not),
        else this usage itself (spec ``assertedConstraint``)."""
        target = referenced_feature_target(self)
        if target is None:
            return self
        return target if isinstance(target, ConstraintUsage) else None


class SatisfyRequirementUsage(RequirementUsage, AssertConstraintUsage):
    """``satisfy r by f``: asserts that `f` satisfies requirement `r` (SysML 8.3.21.10).

    The satisfying feature is bound to the subject parameter by an owned
    BindingConnector.
    """

    kind = "SatisfyRequirementUsage"

    def __init__(self, name: Optional[str] = None, *,
                 satisfied_requirement: Optional[Feature] = None, **kwargs):
        super().__init__(name=name, asserted_constraint=satisfied_requirement, **kwargs)

    @property
    def satisfied_requirement(self) -> Optional[RequirementUsage]:
        """The asserted constraint, if a RequirementUsage (spec ``satisfiedRequirement``)."""
        c = self.asserted_constraint
        return c if isinstance(c, RequirementUsage) else None

    @property
    def satisfying_feature(self) -> Optional[Feature]:
        """The feature an owned BindingConnector binds the subject parameter to
        (spec ``satisfyingFeature``)."""
        subject = getattr(self, "subject_parameter", None)
        if subject is None:
            return None
        for b in self.owned_members:
            if isinstance(b, BindingConnector):
                related = b.related_elements
                if any(r is subject for r in related):
                    return next((r for r in related if r is not subject), None)
        return None


def _referenced(owned: Optional[Feature], cls: type) -> Optional[Feature]:
    """``RequirementConstraintMembership::referencedConstraint`` for a member of type `cls`."""
    if owned is None:
        return None
    target = referenced_feature_target(owned)
    if target is None:
        return owned if isinstance(owned, cls) else None
    return target if isinstance(target, cls) else None


class _RequirementKindFixed:
    """The ``kind`` of these memberships is always ``requirement``.

    Assigning ``requirement`` (or None, as a constructor without a kind may) is
    accepted and changes nothing; ``assumption`` is refused.
    """

    @property
    def requirement_constraint_kind(self) -> str:
        """Spec ``kind`` (a RequirementConstraintKind): always ``requirement``."""
        return "requirement"

    @requirement_constraint_kind.setter
    def requirement_constraint_kind(self, value) -> None:
        if getattr(value, "value", value) not in (None, "requirement"):
            raise ValueError(f"the kind of a {type(self).__name__} is 'requirement', not {value!r}")


# TODO(A3 merge): base RequirementConstraintMembership (spec supertype) instead of
# FeatureMembership; it provides owned_constraint / referenced_constraint.
class FramedConcernMembership(_RequirementKindFixed, FeatureMembership):
    """Owns a concern framed by a requirement (``frame c;``, SysML 8.3.21.5)."""

    kind = "FramedConcernMembership"

    @property
    def owned_concern(self) -> Optional[ConcernUsage]:
        """The owned ConcernUsage (spec ``ownedConcern``)."""
        m = self.owned_member_element
        return m if isinstance(m, ConcernUsage) else None

    @property
    def referenced_concern(self) -> Optional[ConcernUsage]:
        """The concern the owned concern references, else the owned concern
        (spec ``referencedConcern``)."""
        return _referenced(self.owned_member_element, ConcernUsage)  # type: ignore[return-value]


# TODO(A3 merge): base RequirementConstraintMembership (spec supertype) instead of
# FeatureMembership.
class RequirementVerificationMembership(_RequirementKindFixed, FeatureMembership):
    """Owns a requirement verified by a verification case objective (``verify r;``,
    SysML 8.3.24.2)."""

    kind = "RequirementVerificationMembership"

    @property
    def owned_requirement(self) -> Optional[RequirementUsage]:
        """The owned RequirementUsage (spec ``ownedRequirement``)."""
        m = self.owned_member_element
        return m if isinstance(m, RequirementUsage) else None

    @property
    def verified_requirement(self) -> Optional[RequirementUsage]:
        """The requirement the owned requirement references, else the owned requirement
        (spec ``verifiedRequirement``)."""
        return _referenced(self.owned_member_element, RequirementUsage)  # type: ignore[return-value]


class ObjectiveMembership(FeatureMembership):
    """Owns the objective requirement of a case (``objective { ... }``, SysML 8.3.22.4)."""

    kind = "ObjectiveMembership"

    @property
    def owned_objective_requirement(self) -> Optional[RequirementUsage]:
        """The owned RequirementUsage (spec ``ownedObjectiveRequirement``)."""
        m = self.owned_member_element
        return m if isinstance(m, RequirementUsage) else None


class IncludeUseCaseUsage(UseCaseUsage, PerformActionUsage):
    """``include u;``: performs a use case within another (SysML 8.3.25.2)."""

    kind = "IncludeUseCaseUsage"

    def __init__(self, name: Optional[str] = None, *,
                 use_case_included: Optional[Feature] = None, **kwargs):
        super().__init__(name=name, performed_action=use_case_included, **kwargs)

    @property
    def use_case_included(self) -> Optional[UseCaseUsage]:
        """The performed action, if a UseCaseUsage (spec ``useCaseIncluded``)."""
        a = self.performed_action
        return a if isinstance(a, UseCaseUsage) else None


__all__ = ["AssertConstraintUsage", "SatisfyRequirementUsage", "FramedConcernMembership",
           "RequirementVerificationMembership", "ObjectiveMembership", "IncludeUseCaseUsage",
           "REQUIREMENT_CONSTRAINT_KINDS"]
