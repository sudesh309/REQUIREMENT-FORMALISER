"""SysML memberships and exposes (SysML 8.3: requirements, states, transitions, views).

These memberships realize relationships the application used to keep as
attributes (ADR 0002 decision 6): a requirement's subject, actors,
stakeholders and assumed / required constraints, a transition's trigger,
guard and effect, a state's entry / do / exit actions and a view's exposed
elements. Their members are structural sub-elements: the application tree
(``walk()``, ``children``) does not show them; the compatibility attributes
of the owning elements read and write them.

Naming: the spec's ``kind`` properties are called after their enumeration
(``requirement_constraint_kind``, ``transition_feature_kind``,
``state_subaction_kind``, ``trigger_kind``) because ``kind`` is the class
discriminator.
"""
from __future__ import annotations

from typing import Optional

from kerml.behaviors import ParameterMembership
from kerml.elements import Element
from kerml.expressions import Invocation
from kerml.namespaces import PROTECTED, Import, MembershipImport, NamespaceImport
from kerml.types import FeatureMembership

REQUIREMENT_CONSTRAINT_KINDS = ("assumption", "requirement")
TRANSITION_FEATURE_KINDS = ("trigger", "guard", "effect")
STATE_SUBACTION_KINDS = ("entry", "do", "exit")
TRIGGER_KINDS = ("when", "at", "after")


def _check(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {list(allowed)}, not {value!r}")
    return value


class SubjectMembership(ParameterMembership):
    """Owns the subject parameter of a requirement or case."""

    kind = "SubjectMembership"
    _tree_owns = False

    @property
    def owned_subject_parameter(self):
        return self.owned_member_element


class ActorMembership(ParameterMembership):
    """Owns an actor parameter (a part usage) of a requirement or case."""

    kind = "ActorMembership"
    _tree_owns = False

    @property
    def owned_actor_parameter(self):
        return self.owned_member_element


class StakeholderMembership(ParameterMembership):
    """Owns a stakeholder parameter (a part usage) of a requirement."""

    kind = "StakeholderMembership"
    _tree_owns = False

    @property
    def owned_stakeholder_parameter(self):
        return self.owned_member_element


class RequirementConstraintMembership(FeatureMembership):
    """Owns an assumed (``assume``) or required (``require``) constraint of a requirement."""

    kind = "RequirementConstraintMembership"
    _tree_owns = False

    def __init__(self, namespace=None, member=None, *, requirement_constraint_kind: str = "requirement",
                 **kwargs):
        super().__init__(namespace, member, **kwargs)
        self.requirement_constraint_kind = _check(requirement_constraint_kind,
                                                  REQUIREMENT_CONSTRAINT_KINDS,
                                                  "requirement_constraint_kind")

    @property
    def owned_constraint(self):
        return self.owned_member_element

    @property
    def referenced_constraint(self):
        """The referenced constraint (``assume c;``), else the owned constraint itself."""
        c = self.owned_constraint
        rs = getattr(c, "owned_reference_subsetting", None)
        return rs.referenced_feature if rs is not None and rs.referenced_feature is not None else c


class TransitionFeatureMembership(FeatureMembership):
    """Owns the trigger, guard or effect of a transition."""

    kind = "TransitionFeatureMembership"
    _tree_owns = False

    def __init__(self, namespace=None, member=None, *, transition_feature_kind: str = "trigger",
                 **kwargs):
        super().__init__(namespace, member, **kwargs)
        self.transition_feature_kind = _check(transition_feature_kind, TRANSITION_FEATURE_KINDS,
                                              "transition_feature_kind")

    @property
    def transition_feature(self):
        return self.owned_member_element


class StateSubactionMembership(FeatureMembership):
    """Owns the entry, do or exit action of a state."""

    kind = "StateSubactionMembership"
    _tree_owns = False

    def __init__(self, namespace=None, member=None, *, state_subaction_kind: str = "entry", **kwargs):
        super().__init__(namespace, member, **kwargs)
        self.state_subaction_kind = _check(state_subaction_kind, STATE_SUBACTION_KINDS,
                                           "state_subaction_kind")

    @property
    def action(self):
        return self.owned_member_element


class Expose(Import):
    """Exposes model elements in a view (abstract); always protected and import-all."""

    kind = "Expose"

    def __init__(self, importing=None, imported=None, **kwargs):
        kwargs.setdefault("visibility", PROTECTED)
        kwargs.setdefault("is_import_all", True)
        super().__init__(importing, imported, **kwargs)


class MembershipExpose(MembershipImport, Expose):
    """``expose X::a`` (with ``::**`` when recursive)."""

    kind = "MembershipExpose"


class NamespaceExpose(Expose, NamespaceImport):
    """``expose X::*`` (with ``::**`` when recursive)."""

    kind = "NamespaceExpose"


class TriggerInvocationExpression(Invocation):
    """``when`` / ``at`` / ``after`` trigger of an accept action."""

    kind = "TriggerInvocationExpression"

    def __init__(self, *args, trigger_kind: str = "when", **kwargs):
        super().__init__(*args, **kwargs)
        self.trigger_kind = _check(trigger_kind, TRIGGER_KINDS, "trigger_kind")


def owned_membership(owner: Element, cls: type, **match) -> Optional[Element]:
    """The first owned membership of class `cls` whose attributes equal `match`."""
    for r in owner._owned_relationships:
        if isinstance(r, cls) and all(getattr(r, k) == v for k, v in match.items()):
            return r
    return None


__all__ = [
    "SubjectMembership", "ActorMembership", "StakeholderMembership",
    "RequirementConstraintMembership", "TransitionFeatureMembership", "StateSubactionMembership",
    "Expose", "MembershipExpose", "NamespaceExpose", "TriggerInvocationExpression",
    "REQUIREMENT_CONSTRAINT_KINDS", "TRANSITION_FEATURE_KINDS", "STATE_SUBACTION_KINDS",
    "TRIGGER_KINDS", "owned_membership",
]
