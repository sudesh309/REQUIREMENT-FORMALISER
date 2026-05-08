"""Type system: Type, Classifier, DataType, Class, Structure, Behavior, Association.

Specialization and Conjugation are the two structural relationships
through which one Type relates to another. SysML v2 definitions are all
KerML Classifiers (or subclasses thereof).
"""
from __future__ import annotations

from typing import Optional

from .elements import Relationship
from .namespaces import Namespace


class Specialization(Relationship):
    """`specific` specializes `general` (subtype-of)."""

    kind = "Specialization"

    def __init__(self, specific: "Type", general: "Type", **kwargs):
        super().__init__(source=specific, target=general, **kwargs)

    @property
    def specific(self) -> "Type": return self.source  # type: ignore[return-value]

    @property
    def general(self) -> "Type": return self.target  # type: ignore[return-value]


class Conjugation(Relationship):
    """Conjugation flips feature directions (used by InterfaceDefinition)."""

    kind = "Conjugation"

    def __init__(self, conjugated: "Type", original: "Type", **kwargs):
        super().__init__(source=conjugated, target=original, **kwargs)


class Type(Namespace):
    """A Type is a Namespace that can be specialized."""

    kind = "Type"

    def __init__(self, name: Optional[str] = None, *, is_abstract: bool = False,
                 is_sufficient: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_abstract = is_abstract
        self.is_sufficient = is_sufficient
        self.specializations: list[Specialization] = []
        self.conjugations: list[Conjugation] = []

    # --- specialization -----------------------------------------------
    def specialize(self, general: "Type") -> Specialization:
        s = Specialization(self, general)
        self.specializations.append(s)
        self.add_relationship(s)
        return s

    def conjugate(self, original: "Type") -> Conjugation:
        c = Conjugation(self, original)
        self.conjugations.append(c)
        self.add_relationship(c)
        return c

    def all_supertypes(self) -> list["Type"]:
        seen: dict[int, Type] = {}
        stack: list[Type] = [s.general for s in self.specializations]
        while stack:
            t = stack.pop()
            if id(t) in seen:
                continue
            seen[id(t)] = t
            stack.extend(s.general for s in t.specializations)
        return list(seen.values())

    def conforms_to(self, other: "Type") -> bool:
        return self is other or other in self.all_supertypes()

    # --- features ------------------------------------------------------
    @property
    def owned_features(self) -> list:
        from .features import Feature
        return [e for e in self.owned_elements if isinstance(e, Feature)]

    def inherited_features(self) -> list:
        from .features import Feature
        out: list[Feature] = []
        seen: set[int] = set()
        for t in self.all_supertypes():
            for f in t.owned_features:
                if id(f) not in seen:
                    out.append(f)
                    seen.add(id(f))
        return out

    def all_features(self) -> list:
        return self.owned_features + self.inherited_features()


class Classifier(Type):
    """Type whose instances are objects/values (as opposed to plain features).

    SysML v2 Definitions all derive from Classifier.
    """

    kind = "Classifier"


class DataType(Classifier):
    kind = "DataType"


class Class(Classifier):
    kind = "Class"


class Structure(Class):
    kind = "Structure"


class Behavior(Class):
    kind = "Behavior"


class Association(Classifier):
    """Classifier whose features are end-features (relationship classifier)."""

    kind = "Association"
