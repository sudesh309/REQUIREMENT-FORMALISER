"""SysML v2 modeling relationships.

These are KerML Relationships that carry SysML-specific semantics:
- Satisfy: a part / behavior satisfies a requirement
- Verify: a verification case verifies a requirement
- Refine, Trace, DeriveRequirement, Copy: requirements traceability
"""
from __future__ import annotations

from kerml.elements import Element, Relationship


class Satisfy(Relationship):
    kind = "Satisfy"

    def __init__(self, satisfier: Element, requirement: Element, **kwargs):
        super().__init__(source=satisfier, target=requirement, **kwargs)


class Verify(Relationship):
    kind = "Verify"

    def __init__(self, verifier: Element, requirement: Element, **kwargs):
        super().__init__(source=verifier, target=requirement, **kwargs)


class Refine(Relationship):
    kind = "Refine"

    def __init__(self, refining: Element, refined: Element, **kwargs):
        super().__init__(source=refining, target=refined, **kwargs)


class Trace(Relationship):
    kind = "Trace"


class DeriveRequirement(Relationship):
    kind = "DeriveRequirement"


class Copy(Relationship):
    kind = "Copy"


class Allocation(Relationship):
    """Generic allocation (logical -> physical, behavior -> structure, ...)."""
    kind = "Allocation"

    def __init__(self, source: Element, target: Element, **kwargs):
        super().__init__(source=source, target=target, **kwargs)


class SubjectOf(Relationship):
    """Names the subject of a requirement / case / view."""
    kind = "SubjectOf"


class StakeholderOf(Relationship):
    """Records a stakeholder for a requirement."""
    kind = "StakeholderOf"


class ActorOf(Relationship):
    """Records an actor for a requirement / use case."""
    kind = "ActorOf"


class FramedConcern(Relationship):
    """A Concern framed by a Requirement / Viewpoint."""
    kind = "FramedConcern"


class ParameterBinding(Relationship):
    """Binds two parameters (matching their values across an invocation)."""
    kind = "ParameterBinding"


class AssumeConstraint(Relationship):
    """Requirement assumes a Constraint."""
    kind = "AssumeConstraint"


class RequireConstraint(Relationship):
    """Requirement requires a Constraint."""
    kind = "RequireConstraint"


class Exposes(Relationship):
    """View exposes a model element."""
    kind = "Exposes"
