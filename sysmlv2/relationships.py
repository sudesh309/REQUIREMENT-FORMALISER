"""SysML v2 traceability links of the application.

These are KerML Dependencies (``source`` = client, ``target`` = supplier) that
carry the application's link semantics, interchanged as ``Dependency`` with
their class in ``ext`` (Phase 4c maps satisfy / verify / derive / refine /
trace to the standard requirement constructs):

- Satisfy: a part / behavior satisfies a requirement
- Verify: a verification case verifies a requirement
- Refine, Trace, DeriveRequirement, Copy: requirements traceability
- Allocation, SubjectOf, StakeholderOf, ActorOf, FramedConcern, ParameterBinding,
  AssumeConstraint, RequireConstraint, Exposes: the earlier link kinds
"""
from __future__ import annotations

from typing import Optional

from kerml.elements import Dependency, Element


class _Link(Dependency):
    """A binary application link: ``_Link(source, target)``."""

    spec_metaclass = "Dependency"

    def __init__(self, source: Optional[Element] = None, target: Optional[Element] = None, **kwargs):
        super().__init__(source, target, **kwargs)


class Satisfy(_Link):
    kind = "Satisfy"


class Verify(_Link):
    kind = "Verify"


class Refine(_Link):
    kind = "Refine"


class Trace(_Link):
    kind = "Trace"


class DeriveRequirement(_Link):
    kind = "DeriveRequirement"


class Copy(_Link):
    kind = "Copy"


class Allocation(_Link):
    """Generic allocation (logical -> physical, behavior -> structure, ...)."""
    kind = "Allocation"


class SubjectOf(_Link):
    """Names the subject of a requirement / case / view."""
    kind = "SubjectOf"


class StakeholderOf(_Link):
    """Records a stakeholder for a requirement."""
    kind = "StakeholderOf"


class ActorOf(_Link):
    """Records an actor for a requirement / use case."""
    kind = "ActorOf"


class FramedConcern(_Link):
    """A Concern framed by a Requirement / Viewpoint."""
    kind = "FramedConcern"


class ParameterBinding(_Link):
    """Binds two parameters (matching their values across an invocation)."""
    kind = "ParameterBinding"


class AssumeConstraint(_Link):
    """Requirement assumes a Constraint."""
    kind = "AssumeConstraint"


class RequireConstraint(_Link):
    """Requirement requires a Constraint."""
    kind = "RequireConstraint"


class Exposes(_Link):
    """View exposes a model element."""
    kind = "Exposes"
