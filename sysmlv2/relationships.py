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
