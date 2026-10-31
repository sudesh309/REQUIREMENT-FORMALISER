"""Features (KerML 8.3.3.3): typing, subsetting, redefinition, chaining, featuring.

A Feature is a typed, directed, multiplicity-bounded slot of a Type. SysML
usages are features.

Relationships: ``FeatureTyping`` (``add_type``), ``Subsetting`` (``subset``),
``Redefinition`` (``redefine``), ``ReferenceSubsetting`` (``reference_subset``),
``CrossSubsetting`` (``cross_subset``), ``FeatureChaining`` (``chain``),
``FeatureInverting`` (``invert``) and ``TypeFeaturing``
(``add_featuring_type``). ``feature_typings``, ``subsettings`` and
``redefinitions`` are read-only compatibility views of the owned ones.

Value-like parts (ADR 0002 decision 5): ``multiplicity`` is a
:class:`MultiplicityRange` value and ``default_value`` a Python value; the
spec elements (``MultiplicityRange`` with literal bounds, ``FeatureValue``)
are materialized on demand by :mod:`kerml.values`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Optional

from .elements import Element, Relationship
from .namespaces import OwningMembership
from .types import Conjugation, FeatureMembership, Specialization, Type


class FeatureDirection(str, Enum):
    """Spec ``FeatureDirectionKind``; ``NONE`` stands for a null direction."""

    NONE = "none"
    IN = "in"
    OUT = "out"
    INOUT = "inout"


class MultiplicityRange:
    """`[lower..upper]` where upper may be `*` (unbounded). A value, not an element.

    The spec element (``MultiplicityRange`` with bound expressions) is
    materialized from it by :func:`kerml.values.multiplicity_element`.
    """

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

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MultiplicityRange) and (self.lower, self.upper) == (other.lower, other.upper)

    def __hash__(self) -> int:
        return hash((self.lower, self.upper))

    def __repr__(self) -> str:
        hi = "*" if self.upper is None else str(self.upper)
        return f"[{self.lower}..{hi}]"


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

class FeatureTyping(Specialization):
    """The ``typed_feature`` is typed by ``type``."""

    kind = "FeatureTyping"

    def __init__(self, feature: Optional["Feature"] = None, type_: Optional[Type] = None, **kwargs):
        super().__init__(feature, type_, **kwargs)

    @property
    def typed_feature(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def type(self) -> Optional[Type]:
        return self.target  # type: ignore[return-value]

    @type.setter
    def type(self, value: Optional[Type]) -> None:
        self.target = value

    @property
    def owning_feature(self) -> Optional["Feature"]:
        return self.owning_type  # type: ignore[return-value]


class Subsetting(Specialization):
    """The ``subsetting_feature``'s values are a subset of the ``subsetted_feature``'s."""

    kind = "Subsetting"

    def __init__(self, subsetting: Optional["Feature"] = None, subsetted: Optional["Feature"] = None,
                 **kwargs):
        super().__init__(subsetting, subsetted, **kwargs)

    @property
    def subsetting_feature(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def subsetted_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]

    @subsetted_feature.setter
    def subsetted_feature(self, value: Optional["Feature"]) -> None:
        self.target = value

    @property
    def owning_feature(self) -> Optional["Feature"]:
        return self.owning_type  # type: ignore[return-value]


class Redefinition(Subsetting):
    """The ``redefining_feature`` redefines (replaces) the ``redefined_feature``."""

    kind = "Redefinition"

    @property
    def redefining_feature(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def redefined_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]


class ReferenceSubsetting(Subsetting):
    """The ``referencing_feature`` references ``referenced_feature`` (``::>``).

    The referenced feature may be a feature chain owned by the relationship
    (``a.b.c``), as for connector ends.
    """

    kind = "ReferenceSubsetting"

    @property
    def referencing_feature(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def referenced_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]

    @referenced_feature.setter
    def referenced_feature(self, value: Optional["Feature"]) -> None:
        self.target = value


class CrossSubsetting(Subsetting):
    """The ``crossing_feature`` (an end) subsets the ``crossed_feature`` (a chain)."""

    kind = "CrossSubsetting"

    @property
    def crossing_feature(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def crossed_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]


class _OwnedSourceRelationship(Relationship):
    """A relationship whose source is the feature that owns it."""

    def __init__(self, owner_feature: Optional["Feature"] = None, target: Optional["Feature"] = None,
                 **kwargs):
        super().__init__(source=owner_feature, target=target, **kwargs)

    @property
    def source(self) -> Optional[Element]:
        s = self._sources
        if s:
            return s[0]
        return self._owning_related_element

    @source.setter
    def source(self, value: Optional[Element]) -> None:
        Relationship.source.fset(self, value)


class FeatureChaining(_OwnedSourceRelationship):
    """Makes ``chaining_feature`` the next link of the chain of ``feature_chained``."""

    kind = "FeatureChaining"

    @property
    def feature_chained(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def chaining_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]


class FeatureInverting(Relationship):
    """``feature_inverted`` is the inverse of ``inverting_feature``."""

    kind = "FeatureInverting"

    def __init__(self, inverted: Optional["Feature"] = None, inverting: Optional["Feature"] = None,
                 **kwargs):
        super().__init__(source=inverted, target=inverting, **kwargs)

    @property
    def feature_inverted(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def inverting_feature(self) -> Optional["Feature"]:
        return self.target  # type: ignore[return-value]

    @property
    def owning_feature(self) -> Optional["Feature"]:
        o = self._owning_related_element
        return o if o is not None and o is self.feature_inverted else None  # type: ignore[return-value]


class TypeFeaturing(Relationship):
    """``feature_of_type`` is featured by ``featuring_type`` (its domain)."""

    kind = "TypeFeaturing"

    def __init__(self, feature: Optional["Feature"] = None, featuring_type: Optional[Type] = None,
                 **kwargs):
        super().__init__(source=feature, target=featuring_type, **kwargs)

    @property
    def feature_of_type(self) -> Optional["Feature"]:
        return self.source  # type: ignore[return-value]

    @property
    def featuring_type(self) -> Optional[Type]:
        return self.target  # type: ignore[return-value]

    @property
    def owning_feature_of_type(self) -> Optional["Feature"]:
        o = self._owning_related_element
        return o if o is not None and o is self.feature_of_type else None  # type: ignore[return-value]


class EndFeatureMembership(FeatureMembership):
    """Owning membership of an end feature (``end`` features, connector ends).

    The application tree hides the ends of connectors (they realize the
    ``ends`` compatibility attribute); other end features are shown.
    """

    kind = "EndFeatureMembership"

    @property
    def _tree_owns(self) -> bool:  # type: ignore[override]
        return not getattr(self._owning_related_element, "_is_connector", False)


# ---------------------------------------------------------------------------
# Feature
# ---------------------------------------------------------------------------

def _remove_redundant(types: list[Type]) -> list[Type]:
    out: list[Type] = []
    seen: set[int] = set()
    for t in types:
        if id(t) not in seen:
            seen.add(id(t))
            out.append(t)
    if len(out) < 2:
        return out
    return [t1 for t1 in out if not any(t2 is not t1 and t2.specializes(t1) for t2 in out)]


class Feature(Type):
    """A typed, directed, multiplicity-bounded slot of a Type (KerML 8.3.3.3.4)."""

    kind = "Feature"

    def __init__(self, name: Optional[str] = None, *,
                 typed_by: Optional[Type] = None,
                 multiplicity: Optional[MultiplicityRange] = None,
                 direction: FeatureDirection = FeatureDirection.NONE,
                 is_composite: bool = False,
                 is_portion: bool = False,
                 is_readonly: bool = False,
                 is_constant: Optional[bool] = None,
                 is_derived: bool = False,
                 is_end: bool = False,
                 is_unique: bool = True,
                 is_ordered: bool = False,
                 is_variable: bool = False,
                 default_value: Any = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.multiplicity: MultiplicityRange = multiplicity or MultiplicityRange(0, None)
        self.direction: FeatureDirection = FeatureDirection(direction or FeatureDirection.NONE)
        self.is_composite: bool = is_composite
        self.is_portion: bool = is_portion
        self.is_constant: bool = bool(is_readonly if is_constant is None else is_constant)
        self.is_derived: bool = is_derived
        self.is_end: bool = is_end
        self.is_unique: bool = is_unique
        self.is_ordered: bool = is_ordered
        self.is_variable: bool = is_variable
        self.default_value = default_value
        if typed_by is not None:
            self.add_type(typed_by)

    # --- names ----------------------------------------------------------------
    @property
    def name(self) -> Optional[str]:
        """Effective name: the declared name, else that of the first redefined feature."""
        n = self._declared_name
        if n is not None or self._declared_short_name is not None:
            return n
        return self.effective_name()

    @name.setter
    def name(self, value: Optional[str]) -> None:
        self._declared_name = value

    @property
    def short_name(self) -> Optional[str]:
        s = self._declared_short_name
        if s is not None or self._declared_name is not None:
            return s
        return self.effective_short_name()

    @short_name.setter
    def short_name(self, value: Optional[str]) -> None:
        self._declared_short_name = value

    def naming_feature(self) -> Optional["Feature"]:
        r = next((r for r in self._owned_relationships
                  if isinstance(r, Redefinition) and r.source is self), None)
        return r.redefined_feature if r is not None else None

    def effective_name(self, _seen: Optional[set] = None) -> Optional[str]:
        if self._declared_short_name is not None or self._declared_name is not None:
            return self._declared_name
        seen = _seen or set()
        if id(self) in seen:
            return None
        seen.add(id(self))
        nf = self.naming_feature()
        return nf.effective_name(seen) if isinstance(nf, Feature) else None

    def effective_short_name(self, _seen: Optional[set] = None) -> Optional[str]:
        if self._declared_short_name is not None or self._declared_name is not None:
            return self._declared_short_name
        seen = _seen or set()
        if id(self) in seen:
            return None
        seen.add(id(self))
        nf = self.naming_feature()
        return nf.effective_short_name(seen) if isinstance(nf, Feature) else None

    # --- flags ------------------------------------------------------------------
    @property
    def is_readonly(self) -> bool:
        """Compatibility alias of ``is_constant``."""
        return self.is_constant

    @is_readonly.setter
    def is_readonly(self, value: bool) -> None:
        self.is_constant = bool(value)

    # --- ownership context --------------------------------------------------------
    @property
    def owning_feature_membership(self) -> Optional[FeatureMembership]:
        r = self._owning_relationship
        return r if isinstance(r, FeatureMembership) else None

    @property
    def owning_type(self) -> Optional[Type]:
        m = self.owning_feature_membership
        return m.owning_type if m is not None else None

    @property
    def end_owning_type(self) -> Optional[Type]:
        r = self._owning_relationship
        return r.owning_type if isinstance(r, EndFeatureMembership) else None

    # --- typing ---------------------------------------------------------------
    @property
    def owned_typings(self) -> list[FeatureTyping]:
        return [r for r in self._owned_relationships if isinstance(r, FeatureTyping) and r.source is self]

    @property
    def feature_typings(self) -> list[FeatureTyping]:
        """Compatibility: read-only view of ``owned_typings``."""
        return self.owned_typings

    def add_type(self, t: Type, **kwargs) -> FeatureTyping:
        ft = FeatureTyping(self, t, **kwargs)
        self.add_relationship(ft)
        return ft

    def remove_types(self, t: Optional[Type] = None) -> None:
        """Remove the owned typings (to `t` only, when given)."""
        for r in self.owned_typings:
            if t is None or r.type is t:
                self.remove_relationship(r)

    def typing_features(self) -> list["Feature"]:
        cj = self.owned_conjugator
        if cj is not None:
            return [cj.original_type] if isinstance(cj.original_type, Feature) else []
        out = [r.subsetted_feature for r in self.owned_subsettings
               if not isinstance(r, CrossSubsetting) and isinstance(r.subsetted_feature, Feature)]
        chain = self.chaining_features
        if chain and not any(f is chain[-1] for f in out):
            out.append(chain[-1])
        return out

    @property
    def types(self) -> list[Type]:
        """Types of this feature: its typings and those of the features it subsets
        (and of the last feature of its chain), redundant supertypes removed."""
        typings: list = []
        other = False
        for r in self._owned_relationships:
            if isinstance(r, FeatureTyping):
                if r.source is self and r.target is not None:
                    typings.append(r.target)
            elif isinstance(r, (Subsetting, FeatureChaining, Conjugation)):
                other = True
        if not other:
            return _remove_redundant(typings) if len(typings) > 1 else typings
        found: list[Type] = []
        visited = {id(self)}
        queue = [self]
        while queue:
            f = queue.pop(0)
            found += [r.target for r in f.owned_typings if r.target is not None]
            for g in f.typing_features():
                if id(g) not in visited:
                    visited.add(id(g))
                    queue.append(g)
        return _remove_redundant(found)

    # --- subsetting / redefinition ----------------------------------------------
    @property
    def owned_subsettings(self) -> list[Subsetting]:
        return [r for r in self._owned_relationships if isinstance(r, Subsetting) and r.source is self]

    @property
    def subsettings(self) -> list[Subsetting]:
        """Compatibility: read-only view of ``owned_subsettings`` (redefinitions included)."""
        return self.owned_subsettings

    @property
    def owned_redefinitions(self) -> list[Redefinition]:
        return [r for r in self.owned_subsettings if isinstance(r, Redefinition)]

    @property
    def redefinitions(self) -> list[Redefinition]:
        """Compatibility: read-only view of ``owned_redefinitions``."""
        return self.owned_redefinitions

    @property
    def owned_reference_subsetting(self) -> Optional[ReferenceSubsetting]:
        return next((r for r in self.owned_subsettings if isinstance(r, ReferenceSubsetting)), None)

    @property
    def owned_cross_subsetting(self) -> Optional[CrossSubsetting]:
        return next((r for r in self.owned_subsettings if isinstance(r, CrossSubsetting)), None)

    def subset(self, other: "Feature", **kwargs) -> Subsetting:
        s = Subsetting(self, other, **kwargs)
        self.add_relationship(s)
        return s

    def redefine(self, other: "Feature", **kwargs) -> Redefinition:
        r = Redefinition(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def reference_subset(self, other: "Feature", **kwargs) -> ReferenceSubsetting:
        """Reference `other` (at most one per feature: an existing one is replaced)."""
        old = self.owned_reference_subsetting
        if old is not None:
            self.remove_relationship(old)
        r = ReferenceSubsetting(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def cross_subset(self, other: "Feature", **kwargs) -> CrossSubsetting:
        old = self.owned_cross_subsetting
        if old is not None:
            self.remove_relationship(old)
        r = CrossSubsetting(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def remove_subsettings(self, kind: type = Subsetting) -> None:
        for r in self.owned_subsettings:
            if isinstance(r, kind):
                self.remove_relationship(r)

    def redefines(self, feature: "Feature") -> bool:
        return any(r.redefined_feature is feature for r in self.owned_redefinitions)

    def all_redefined_features(self) -> list["Feature"]:
        out: list[Feature] = [self]
        seen = {id(self)}
        i = 0
        while i < len(out):
            for r in out[i].owned_redefinitions:
                g = r.redefined_feature
                if isinstance(g, Feature) and id(g) not in seen:
                    seen.add(id(g))
                    out.append(g)
            i += 1
        return out

    # --- chaining / inverting / featuring -----------------------------------------
    @property
    def owned_feature_chainings(self) -> list[FeatureChaining]:
        return [r for r in self._owned_relationships if isinstance(r, FeatureChaining)]

    @property
    def chaining_features(self) -> list["Feature"]:
        return [r.chaining_feature for r in self.owned_feature_chainings if r.chaining_feature is not None]

    def chain(self, *features: "Feature", ids: Optional[Iterable[str]] = None) -> list[FeatureChaining]:
        """Make this feature the chain ``features[0].features[1]...`` (``a.b.c``)."""
        id_list = list(ids or ())
        out = []
        for i, f in enumerate(features):
            kw = {"element_id": id_list[i]} if i < len(id_list) else {}
            fc = FeatureChaining(self, f, **kw)
            self.add_relationship(fc)
            out.append(fc)
        return out

    @property
    def feature_target(self) -> "Feature":
        chain = self.chaining_features
        return chain[-1] if chain else self

    @property
    def owned_feature_invertings(self) -> list[FeatureInverting]:
        return [r for r in self._owned_relationships
                if isinstance(r, FeatureInverting) and r.feature_inverted is self]

    def invert(self, other: "Feature", **kwargs) -> FeatureInverting:
        r = FeatureInverting(self, other, **kwargs)
        self.add_relationship(r)
        return r

    @property
    def owned_type_featurings(self) -> list[TypeFeaturing]:
        return [r for r in self._owned_relationships
                if isinstance(r, TypeFeaturing) and r.feature_of_type is self]

    def add_featuring_type(self, t: Type, **kwargs) -> TypeFeaturing:
        r = TypeFeaturing(self, t, **kwargs)
        self.add_relationship(r)
        return r

    @property
    def featuring_types(self) -> list[Type]:
        """The owning type (as the implied TypeFeaturing of Phase 3 would add), the featuring
        types of the type featurings, and those of the first chaining feature."""
        out: list[Type] = []
        ot = self.owning_type
        if ot is not None:
            out.append(ot)
        for r in self.owned_type_featurings:
            t = r.featuring_type
            if t is not None and not any(t is x for x in out):
                out.append(t)
        chain = self.chaining_features
        if chain:
            for t in chain[0].featuring_types:
                if not any(t is x for x in out):
                    out.append(t)
        return out

    @property
    def cross_feature(self) -> Optional["Feature"]:
        cs = self.owned_cross_subsetting
        if cs is None or not isinstance(cs.crossed_feature, Feature):
            return None
        chain = cs.crossed_feature.chaining_features
        return chain[1] if len(chain) >= 2 else None

    def supertypes(self, exclude_implied: bool = False) -> list[Type]:
        out = super().supertypes(exclude_implied)
        target = self.feature_target
        if target is not self and not any(t is target for t in out):
            out = out + [target]
        return out

    # --- value-like parts (ADR 0002 decision 5) ------------------------------------
    def multiplicity_element(self):
        """The spec ``MultiplicityRange`` element for ``multiplicity`` (materialized)."""
        from .values import multiplicity_element
        return multiplicity_element(self)

    def value_membership(self):
        """The spec ``FeatureValue`` for ``default_value`` (materialized; None without a value)."""
        from .values import feature_value
        return feature_value(self)


class Multiplicity(Feature):
    """A feature constraining the cardinality of a type (KerML 8.3.3.1.9)."""

    kind = "Multiplicity"


__all__ = [
    "FeatureDirection", "MultiplicityRange", "FeatureTyping", "Subsetting", "Redefinition",
    "ReferenceSubsetting", "CrossSubsetting", "FeatureChaining", "FeatureInverting", "TypeFeaturing",
    "EndFeatureMembership", "FeatureMembership", "Feature", "Multiplicity",
]
