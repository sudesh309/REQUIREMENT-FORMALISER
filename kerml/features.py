"""Feature, Multiplicity, FeatureTyping, Subsetting, Redefinition.

A Feature is a typed, directed, multiplicity-bounded slot of a Type.
SysML v2 Usages all derive from Feature.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from .elements import Element, Relationship
from .types import Type


class FeatureDirection(str, Enum):
    NONE = "none"
    IN = "in"
    OUT = "out"
    INOUT = "inout"


class MultiplicityRange:
    """`[lower..upper]` where upper may be `*` (unbounded)."""

    def __init__(self, lower: int = 0, upper: Optional[int] = None):
        if lower < 0:
            raise ValueError("lower bound must be >= 0")
        if upper is not None and upper < lower:
            raise ValueError("upper must be >= lower (or None for unbounded)")
        self.lower = lower
        self.upper = upper  # None == unbounded

    @classmethod
    def parse(cls, text: str) -> "MultiplicityRange":
        text = text.strip().strip("[]").strip()
        if ".." in text:
            lo, hi = (p.strip() for p in text.split("..", 1))
        else:
            lo = hi = text
        lower = int(lo)
        upper = None if hi == "*" else int(hi)
        return cls(lower, upper)

    def includes(self, count: int) -> bool:
        if count < self.lower:
            return False
        return self.upper is None or count <= self.upper

    def __repr__(self) -> str:
        hi = "*" if self.upper is None else str(self.upper)
        return f"[{self.lower}..{hi}]"


class Multiplicity(Element):
    """Element wrapper around a MultiplicityRange (so it can be owned)."""

    kind = "Multiplicity"

    def __init__(self, lower: int = 0, upper: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        self.range = MultiplicityRange(lower, upper)


class FeatureMembership(Relationship):
    """Special membership relationship for features inside a Type."""

    kind = "FeatureMembership"


class FeatureTyping(Relationship):
    """A Feature is typed by a Type."""

    kind = "FeatureTyping"

    def __init__(self, feature: "Feature", type_: Type, **kwargs):
        super().__init__(source=feature, target=type_, **kwargs)


class Subsetting(Relationship):
    """A Feature subsets another Feature (its values are a subset)."""

    kind = "Subsetting"

    def __init__(self, subsetting: "Feature", subsetted: "Feature", **kwargs):
        super().__init__(source=subsetting, target=subsetted, **kwargs)


class Redefinition(Subsetting):
    """A Feature redefines an inherited Feature."""

    kind = "Redefinition"


class Feature(Type):
    """A Feature is a slot: typed, directed, multiplicity-bounded."""

    kind = "Feature"

    def __init__(self, name: Optional[str] = None, *,
                 typed_by: Optional[Type] = None,
                 multiplicity: Optional[MultiplicityRange] = None,
                 direction: FeatureDirection = FeatureDirection.NONE,
                 is_composite: bool = False,
                 is_portion: bool = False,
                 is_readonly: bool = False,
                 is_derived: bool = False,
                 is_end: bool = False,
                 default_value=None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.feature_typings: list[FeatureTyping] = []
        self.subsettings: list[Subsetting] = []
        self.redefinitions: list[Redefinition] = []
        self.multiplicity = multiplicity or MultiplicityRange(0, None)
        self.direction = FeatureDirection(direction)
        self.is_composite = is_composite
        self.is_portion = is_portion
        self.is_readonly = is_readonly
        self.is_derived = is_derived
        self.is_end = is_end
        self.default_value = default_value
        if typed_by is not None:
            self.add_type(typed_by)

    # --- typing --------------------------------------------------------
    def add_type(self, t: Type) -> FeatureTyping:
        ft = FeatureTyping(self, t)
        self.feature_typings.append(ft)
        self.add_relationship(ft)
        return ft

    @property
    def types(self) -> list[Type]:
        return [ft.target for ft in self.feature_typings]  # type: ignore[list-item]

    # --- subsetting / redefinition ------------------------------------
    def subset(self, other: "Feature") -> Subsetting:
        s = Subsetting(self, other)
        self.subsettings.append(s)
        self.add_relationship(s)
        return s

    def redefine(self, other: "Feature") -> Redefinition:
        r = Redefinition(self, other)
        self.redefinitions.append(r)
        self.subsettings.append(r)
        self.add_relationship(r)
        return r
