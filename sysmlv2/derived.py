"""SysML derived properties installed from the metamodel registry.

Imported last by :mod:`sysmlv2`; runs :func:`kerml.derived.install` for the
SysML metaclasses, whose module docstring states the rules: hand-written code
wins, then the explicit derivations below, then the *type filter* that
generates the filter properties of the spec (``Definition::ownedPart`` is
``owned_features`` filtered by ``PartUsage``, ``Usage::nestedAction``
``owned_features`` filtered by ``ActionUsage``, ``PartUsage::partDefinition``
``types`` filtered by ``PartDefinition``, ``PortDefinition::conjugatedPortDefinition``
the first owned member that is a ``ConjugatedPortDefinition``, ...).

:data:`SYSML_EXPLICIT` holds the derivations of the specification that are not
type filters, written from the SysML 2.0 abstract syntax clauses. Most
navigate owned memberships of a kind (``featureMembership->
selectByKind(SubjectMembership).ownedSubjectParameter``); the membership
classes are looked up by metaclass name when the property is read, so an entry
whose membership class is not defined yet reads as empty. A class that
defines the property itself is left alone.

Not generated (left to hand-written code): ``Usage::mayTimeVary`` (needs the
library: ``specializesFromLibrary``), ``TransitionUsage::source`` /
``target`` (the transition structure), ``ViewUsage::exposedElement`` (needs
``Expose``), ``ConjugatedPortTyping::portDefinition`` and the others listed
by ``kerml.derived.report()``.
"""
from __future__ import annotations

from typing import Callable, Optional

from kerml.derived import class_for, enum_value, install, is_kind

from . import metamodel  # noqa: F401 - registers the SysML metaclasses


def _navigate(collection: str, membership: str, member: str, *, kind: Optional[tuple] = None,
              of_type: Optional[str] = None, single: bool = False, spec: str = "") -> Callable:
    """``collection->selectByKind(membership)[->select(kind = k)].member[->selectByKind(of_type)]``."""
    def fget(self):
        mcls = class_for(membership)
        out = []
        if mcls is not None:
            for m in getattr(self, collection):
                if not isinstance(m, mcls):
                    continue
                if kind is not None and enum_value(getattr(m, kind[0], None)) != kind[1]:
                    continue
                v = getattr(m, member, None)
                if v is None or (of_type is not None and not is_kind(v, of_type)):
                    continue
                out.append(v)
        if single:
            return out[0] if out else None
        return out
    sel = f"->select(kind = {kind[1]})" if kind else ""
    typ = f"->selectByKind({of_type})" if of_type else ""
    fget.__doc__ = (f"Spec ``{spec}``: ``{collection}->selectByKind({membership}){sel}.{member}{typ}``"
                    + (" (the first, or None)." if single else ".")
                    + " Installed by sysmlv2.derived.")
    return fget


def _nav(spec: str, collection: str, membership: str, member: str, **kw) -> tuple[str, Callable]:
    return spec, _navigate(collection, membership, member, spec=spec, **kw)


def _individual_definition(self):
    """Spec ``OccurrenceUsage::individualDefinition``: the first type that is an
    OccurrenceDefinition with ``is_individual``."""
    cls = class_for("OccurrenceDefinition")
    return next((t for t in self.types
                 if cls is not None and isinstance(t, cls) and getattr(t, "is_individual", False)),
                None)


def _verified_requirements(self) -> list:
    """Spec ``verifiedRequirement``: the verified requirements of the RequirementVerificationMemberships
    of the objective requirement."""
    objective = getattr(self, "objective_requirement", None)
    cls = class_for("RequirementVerificationMembership")
    if objective is None or cls is None:
        return []
    out: list = []
    for m in objective.feature_memberships:
        if isinstance(m, cls):
            r = m.verified_requirement
            if r is not None and not any(r is x for x in out):
                out.append(r)
    return out


def _included_use_cases(self) -> list:
    """Spec ``includedUseCase``: the use cases included by the owned IncludeUseCaseUsages."""
    cls = class_for("IncludeUseCaseUsage")
    if cls is None:
        return []
    return [u.use_case_included for u in self.owned_features
            if isinstance(u, cls) and u.use_case_included is not None]


def _satisfied_viewpoints(self) -> list:
    """Spec ``satisfiedViewpoint``: the owned requirements that are composite ViewpointUsages."""
    cls = class_for("ViewpointUsage")
    if cls is None:
        return []
    return [r for r in self.owned_features if isinstance(r, cls) and r.is_composite]


def _viewpoint_stakeholders(self) -> list:
    """Spec ``viewpointStakeholder``: the stakeholder parameters of the framed concerns
    (``framedConcern.featureMembership->selectByKind(StakeholderMembership).ownedStakeholderParameter``)."""
    cls = class_for("StakeholderMembership")
    if cls is None:
        return []
    out = []
    for concern in getattr(self, "framed_concerns", ()) or ():
        for m in concern.feature_memberships:
            if isinstance(m, cls):
                p = getattr(m, "owned_stakeholder_parameter", None)
                if p is not None:
                    out.append(p)
    return out


def _texts(self) -> list:
    """Spec ``text``: the bodies of the documentation (``documentation.body``)."""
    return [d.body for d in self.documentation]


def _accept_parameter(self):
    """Spec ``AcceptActionUsage::payloadParameter``: the first parameter."""
    params = self.parameters
    return params[0] if params else None


def _argument(i: int, spec: str) -> Callable:
    def fget(self):
        from .actions import argument
        return argument(self, i)
    fget.__doc__ = f"Spec ``{spec}``: ``argument({i})``. Installed by sysmlv2.derived."
    return fget


#: Explicit derivations of SysML derived properties (rule 2 of kerml.derived).
SYSML_EXPLICIT: dict[str, Callable] = dict([
    # Variability
    _nav("Definition::variant", "owned_memberships", "VariantMembership", "owned_variant_usage"),
    _nav("Usage::variant", "owned_memberships", "VariantMembership", "owned_variant_usage"),
    ("OccurrenceUsage::individualDefinition", _individual_definition),
    # Subjects, actors, stakeholders
    *[_nav(f"{m}::subjectParameter", "feature_memberships", "SubjectMembership",
           "owned_subject_parameter", single=True)
      for m in ("CaseDefinition", "CaseUsage", "RequirementDefinition", "RequirementUsage")],
    *[_nav(f"{m}::actorParameter", "feature_memberships", "ActorMembership",
           "owned_actor_parameter")
      for m in ("CaseDefinition", "CaseUsage", "RequirementDefinition", "RequirementUsage")],
    *[_nav(f"{m}::stakeholderParameter", "feature_memberships", "StakeholderMembership",
           "owned_stakeholder_parameter")
      for m in ("RequirementDefinition", "RequirementUsage")],
    # Requirement constraints and concerns
    *[_nav(f"{m}::assumedConstraint", "owned_feature_memberships",
           "RequirementConstraintMembership", "owned_constraint",
           kind=("requirement_constraint_kind", "assumption"))
      for m in ("RequirementDefinition", "RequirementUsage")],
    *[_nav(f"{m}::requiredConstraint", "owned_feature_memberships",
           "RequirementConstraintMembership", "owned_constraint",
           kind=("requirement_constraint_kind", "requirement"))
      for m in ("RequirementDefinition", "RequirementUsage")],
    *[_nav(f"{m}::framedConcern", "feature_memberships", "FramedConcernMembership",
           "owned_concern")
      for m in ("RequirementDefinition", "RequirementUsage")],
    ("RequirementDefinition::text", _texts),
    ("RequirementUsage::text", _texts),
    ("ViewpointDefinition::viewpointStakeholder", _viewpoint_stakeholders),
    ("ViewpointUsage::viewpointStakeholder", _viewpoint_stakeholders),
    # Cases
    *[_nav(f"{m}::objectiveRequirement", "feature_memberships", "ObjectiveMembership",
           "owned_objective_requirement", single=True)
      for m in ("CaseDefinition", "CaseUsage")],
    *[_nav(f"{m}::resultExpression", "feature_memberships", "ResultExpressionMembership",
           "owned_result_expression", single=True)
      for m in ("AnalysisCaseDefinition", "AnalysisCaseUsage")],
    ("VerificationCaseDefinition::verifiedRequirement", _verified_requirements),
    ("VerificationCaseUsage::verifiedRequirement", _verified_requirements),
    ("UseCaseDefinition::includedUseCase", _included_use_cases),
    ("UseCaseUsage::includedUseCase", _included_use_cases),
    # States and transitions
    *[_nav(f"{m}::{prop}Action", "owned_memberships", "StateSubactionMembership", "action",
           kind=("state_subaction_kind", prop), single=True)
      for m in ("StateDefinition", "StateUsage") for prop in ("entry", "do", "exit")],
    _nav("TransitionUsage::triggerAction", "owned_feature_memberships",
         "TransitionFeatureMembership", "transition_feature",
         kind=("transition_feature_kind", "trigger"), of_type="AcceptActionUsage"),
    _nav("TransitionUsage::guardExpression", "owned_feature_memberships",
         "TransitionFeatureMembership", "transition_feature",
         kind=("transition_feature_kind", "guard"), of_type="Expression"),
    _nav("TransitionUsage::effectAction", "owned_feature_memberships",
         "TransitionFeatureMembership", "transition_feature",
         kind=("transition_feature_kind", "effect"), of_type="ActionUsage"),
    # Accept actions
    ("AcceptActionUsage::payloadParameter", _accept_parameter),
    ("AcceptActionUsage::payloadArgument", _argument(1, "AcceptActionUsage::payloadArgument")),
    ("AcceptActionUsage::receiverArgument", _argument(2, "AcceptActionUsage::receiverArgument")),
    # Views
    *[_nav(f"{m}::viewRendering", "feature_memberships", "ViewRenderingMembership",
           "referenced_rendering", single=True)
      for m in ("ViewDefinition", "ViewUsage")],
    *[_nav(f"{m}::viewCondition", "owned_memberships", "ElementFilterMembership", "condition")
      for m in ("ViewDefinition", "ViewUsage")],
    ("ViewDefinition::satisfiedViewpoint", _satisfied_viewpoints),
    ("ViewUsage::satisfiedViewpoint", _satisfied_viewpoints),
])

#: SysML derived properties the type filter must not generate.
SYSML_NOT_GENERATED: tuple[str, ...] = ()

#: Bases that differ from the subsetted property (``ownedMember->selectByKind(MetadataUsage)``).
SYSML_BASE_OVERRIDES: dict[str, str] = {
    "Definition::ownedMetadata": "owned_members",
    "Usage::nestedMetadata": "owned_members",
}


def install_sysml():
    return install("SysML", SYSML_EXPLICIT, SYSML_NOT_GENERATED, SYSML_BASE_OVERRIDES)


install_sysml()

__all__ = ["SYSML_EXPLICIT", "SYSML_NOT_GENERATED", "SYSML_BASE_OVERRIDES", "install_sysml"]
