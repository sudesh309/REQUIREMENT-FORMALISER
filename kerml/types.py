"""Types and classifiers (KerML 8.3.3.1, 8.3.3.2, 8.3.4.1-8.3.4.3).

The relationships between types are first-class: ``Specialization`` (and
``Subclassification`` between classifiers), ``Conjugation``, ``Disjoining``,
``Unioning``, ``Intersecting`` and ``Differencing``. A type owns its
features through ``FeatureMembership`` (``Type.own`` picks it).

Inherited members follow the spec: the non-private memberships of the
supertypes, with redefined features removed (``inherited_memberships``).
"""
from __future__ import annotations

from typing import Iterable, Optional

from .elements import DerivedList, Element, Relationship, model_epoch
from .namespaces import (
    PRIVATE, PROTECTED, PUBLIC, Membership, Namespace, OwningMembership, _unique,
)


# ---------------------------------------------------------------------------
# Relationships between types
# ---------------------------------------------------------------------------

class Specialization(Relationship):
    """`specific` specializes `general` (spec ``source`` / ``target``)."""

    kind = "Specialization"

    def __init__(self, specific: Optional["Type"] = None, general: Optional["Type"] = None, **kwargs):
        super().__init__(source=specific, target=general, **kwargs)

    @property
    def specific(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @specific.setter
    def specific(self, value: Optional["Type"]) -> None:
        self.source = value

    @property
    def general(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]

    @general.setter
    def general(self, value: Optional["Type"]) -> None:
        self.target = value

    @property
    def owning_type(self) -> Optional["Type"]:
        o = self._owning_related_element
        return o if isinstance(o, Type) and o is self.specific else None


class Subclassification(Specialization):
    """A classifier specializes another classifier."""

    kind = "Subclassification"

    @property
    def subclassifier(self) -> Optional["Classifier"]:
        return self.specific  # type: ignore[return-value]

    @property
    def superclassifier(self) -> Optional["Classifier"]:
        return self.general  # type: ignore[return-value]

    @property
    def owning_classifier(self) -> Optional["Classifier"]:
        return self.owning_type  # type: ignore[return-value]


class Conjugation(Relationship):
    """The ``conjugated_type`` is the conjugate of ``original_type`` (directions flipped)."""

    kind = "Conjugation"

    def __init__(self, conjugated: Optional["Type"] = None, original: Optional["Type"] = None, **kwargs):
        super().__init__(source=conjugated, target=original, **kwargs)

    @property
    def conjugated_type(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @property
    def original_type(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]

    @property
    def owning_type(self) -> Optional["Type"]:
        o = self._owning_related_element
        return o if isinstance(o, Type) and o is self.conjugated_type else None


class Disjoining(Relationship):
    """``type_disjoined`` and ``disjoining_type`` have no instances in common."""

    kind = "Disjoining"

    def __init__(self, type_disjoined: Optional["Type"] = None, disjoining_type: Optional["Type"] = None,
                 **kwargs):
        super().__init__(source=type_disjoined, target=disjoining_type, **kwargs)

    @property
    def type_disjoined(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @property
    def disjoining_type(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]

    @property
    def owning_type(self) -> Optional["Type"]:
        o = self._owning_related_element
        return o if isinstance(o, Type) and o is self.type_disjoined else None


class _TypeOperandRelationship(Relationship):
    """Shared shape of Unioning, Intersecting, Differencing: the owning type is the source."""

    def __init__(self, owner_type: Optional["Type"] = None, operand: Optional["Type"] = None, **kwargs):
        super().__init__(source=owner_type, target=operand, **kwargs)

    @property
    def source(self) -> Optional[Element]:
        o = self._owning_related_element
        if o is not None:
            return o
        s = self._sources
        return s[0] if s else None

    @source.setter
    def source(self, value: Optional[Element]) -> None:
        Relationship.source.fset(self, value)


class Unioning(_TypeOperandRelationship):
    kind = "Unioning"

    @property
    def type_unioned(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @property
    def unioning_type(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]


class Intersecting(_TypeOperandRelationship):
    kind = "Intersecting"

    @property
    def type_intersected(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @property
    def intersecting_type(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]


class Differencing(_TypeOperandRelationship):
    kind = "Differencing"

    @property
    def type_differenced(self) -> Optional["Type"]:
        return self.source  # type: ignore[return-value]

    @property
    def differencing_type(self) -> Optional["Type"]:
        return self.target  # type: ignore[return-value]


class FeatureMembership(OwningMembership):
    """Owning membership of a feature in a type (``owned_member_feature``)."""

    kind = "FeatureMembership"

    @property
    def owning_type(self) -> Optional["Type"]:
        return self.membership_owning_namespace  # type: ignore[return-value]

    @property
    def owned_member_feature(self):
        return self.owned_member_element


_FLIP = {"in": "out", "out": "in"}
_LAZY: dict = {}      # classes of later modules, imported on first use


def _load_lazy() -> None:
    from .behaviors import ParameterMembership, ReturnParameterMembership
    from .features import EndFeatureMembership, Feature, FeatureDirection
    _LAZY["Feature"] = Feature
    _LAZY["End"] = EndFeatureMembership
    _LAZY["NONE"] = FeatureDirection.NONE
    _LAZY["Param"] = ParameterMembership
    _LAZY["Return"] = ReturnParameterMembership


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

class Type(Namespace):
    """A Namespace that classifies (KerML 8.3.3.1.10)."""

    kind = "Type"
    # True for Behaviors and Steps: their directed features are parameters.
    _is_behavioral = False
    # A type that is also a relationship (Connector, Association) is not a *pure* one.
    _pure_relationship = False

    def __init__(self, name: Optional[str] = None, *, is_abstract: bool = False,
                 is_sufficient: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_abstract = is_abstract
        self.is_sufficient: bool = is_sufficient

    # --- membership choice -------------------------------------------------------
    def _membership_class_for(self, child: Element) -> type:
        k = _LAZY
        if not k:
            _load_lazy()
        if not isinstance(child, k["Feature"]):
            return OwningMembership
        if child.is_end:
            return k["End"]
        if self._is_behavioral and child.direction is not k["NONE"]:
            if getattr(child, "parameter_kind", None) == "return":
                return k["Return"]
            return k["Param"]
        return FeatureMembership

    # --- specialization ------------------------------------------------------------
    @property
    def owned_specializations(self) -> list[Specialization]:
        return [r for r in self._owned_relationships
                if isinstance(r, Specialization) and r.source is self]

    @property
    def specializations(self) -> list[Specialization]:
        """Compatibility: the owned specializations made by :meth:`specialize`.

        Read-only view of the owned Specializations (and Subclassifications)
        that are not FeatureTypings or Subsettings, which features list in
        ``feature_typings`` and ``subsettings``.
        """
        from .features import FeatureTyping, Subsetting
        return [r for r in self.owned_specializations
                if not isinstance(r, (FeatureTyping, Subsetting))]

    @property
    def owned_conjugator(self) -> Optional[Conjugation]:
        return next((r for r in self._owned_relationships
                     if isinstance(r, Conjugation) and r.source is self), None)

    @property
    def conjugations(self) -> list[Conjugation]:
        """Compatibility: read-only view of the owned Conjugations."""
        return [r for r in self._owned_relationships if isinstance(r, Conjugation)]

    @property
    def is_conjugated(self) -> bool:
        return self.owned_conjugator is not None

    @property
    def owned_disjoinings(self) -> list[Disjoining]:
        return [r for r in self._owned_relationships if isinstance(r, Disjoining)]

    @property
    def owned_unionings(self) -> list[Unioning]:
        return [r for r in self._owned_relationships if isinstance(r, Unioning)]

    @property
    def unioning_types(self) -> list["Type"]:
        return [r.unioning_type for r in self.owned_unionings if r.unioning_type is not None]

    @property
    def owned_intersectings(self) -> list[Intersecting]:
        return [r for r in self._owned_relationships if isinstance(r, Intersecting)]

    @property
    def intersecting_types(self) -> list["Type"]:
        return [r.intersecting_type for r in self.owned_intersectings if r.intersecting_type is not None]

    @property
    def owned_differencings(self) -> list[Differencing]:
        return [r for r in self._owned_relationships if isinstance(r, Differencing)]

    @property
    def differencing_types(self) -> list["Type"]:
        return [r.differencing_type for r in self.owned_differencings if r.differencing_type is not None]

    def specialize(self, general: "Type", **kwargs) -> Specialization:
        """Specialize `general`: a Subclassification between classifiers, else a Specialization."""
        cls = Subclassification if isinstance(self, Classifier) and isinstance(general, Classifier) \
            else Specialization
        s = cls(self, general, **kwargs)
        self.add_relationship(s)
        return s

    def conjugate(self, original: "Type", **kwargs) -> Conjugation:
        c = Conjugation(self, original, **kwargs)
        self.add_relationship(c)
        return c

    def disjoin(self, other: "Type", **kwargs) -> Disjoining:
        d = Disjoining(self, other, **kwargs)
        self.add_relationship(d)
        return d

    def add_unioning(self, other: "Type", **kwargs) -> Unioning:
        r = Unioning(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def add_intersecting(self, other: "Type", **kwargs) -> Intersecting:
        r = Intersecting(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def add_differencing(self, other: "Type", **kwargs) -> Differencing:
        r = Differencing(self, other, **kwargs)
        self.add_relationship(r)
        return r

    def remove_specializations(self) -> None:
        """Remove the specializations made by :meth:`specialize` (not typings or subsettings)."""
        for r in self.specializations:
            self.remove_relationship(r)

    # --- supertypes ---------------------------------------------------------------
    def supertypes(self, exclude_implied: bool = False) -> list["Type"]:
        cj = self.owned_conjugator
        if cj is not None:
            return [cj.original_type] if cj.original_type is not None else []
        return [s.general for s in self.owned_specializations
                if s.general is not None and not (exclude_implied and s.is_implied)]

    def all_supertypes(self) -> list["Type"]:
        """This type and all its direct and indirect supertypes (spec ``allSupertypes()``)."""
        out: list[Type] = [self]
        seen = {id(self)}
        i = 0
        while i < len(out):
            for t in out[i].supertypes(False):
                if id(t) not in seen:
                    seen.add(id(t))
                    out.append(t)
            i += 1
        return out

    def specializes(self, supertype: "Type") -> bool:
        cj = self.owned_conjugator
        if cj is not None and cj.original_type is not None:
            return cj.original_type.specializes(supertype)
        return any(t is supertype for t in self.all_supertypes())

    def conforms_to(self, other: "Type") -> bool:
        """Compatibility: ``self is other`` or ``self.specializes(other)``."""
        return self is other or self.specializes(other)

    def is_compatible_with(self, other: "Type") -> bool:
        return self.specializes(other)

    # --- features -----------------------------------------------------------------
    @property
    def owned_feature_memberships(self) -> list[FeatureMembership]:
        return [r for r in self._owned_relationships if isinstance(r, FeatureMembership)]

    @property
    def owned_features(self) -> list:
        return [x for r in self._owned_relationships if isinstance(r, FeatureMembership)
                for x in r._owned_related_elements]

    @property
    def owned_end_features(self) -> list:
        return [f for f in self.owned_features if f.is_end]

    def _non_private_memberships(self, excluded_ns, excluded_types, exclude_implied) -> list[Membership]:
        out = self.memberships_of_visibility(PUBLIC, excluded_ns)
        out += self.memberships_of_visibility(PROTECTED, excluded_ns)
        out += self._inherited(excluded_ns, excluded_types, exclude_implied)
        return _unique(out)

    def _inheritable(self, excluded_ns, excluded_types, exclude_implied) -> list[Membership]:
        excluding = list(excluded_types) + [self]
        out: list[Membership] = []
        for t in self.supertypes(exclude_implied):
            if any(t is x for x in excluding):
                continue
            out += t._non_private_memberships(excluded_ns, excluding, exclude_implied)
        return out

    def _inherited(self, excluded_ns=(), excluded_types=(), exclude_implied: bool = False
                   ) -> list[Membership]:
        default = not excluded_ns and not excluded_types and not exclude_implied
        if default:
            cache = self.__dict__.get("_inh_cache")
            if cache is not None and cache[0] == model_epoch():
                return cache[1]
        out = self.remove_redefined_features(
            self._inheritable(excluded_ns, excluded_types, exclude_implied))
        if default:
            self.__dict__["_inh_cache"] = (model_epoch(), out)
        return out

    @property
    def inherited_memberships(self) -> DerivedList:
        """Memberships inherited from supertypes, redefined features removed.

        Callable as the spec operation ``inherited_memberships(excluded_namespaces,
        excluded_types, exclude_implied)``.
        """
        return DerivedList(self._inherited(), self._inherited)

    @staticmethod
    def all_redefined_features_of(membership: Membership) -> list:
        from .features import Feature
        m = membership.member_element
        return m.all_redefined_features() if isinstance(m, Feature) else []

    def remove_redefined_features(self, memberships: Iterable[Membership]) -> list[Membership]:
        ms = _unique(memberships)
        redefined_by = [(m, self.all_redefined_features_of(m)) for m in ms]
        reduced = []
        for m1, _ in redefined_by:
            el = m1.member_element
            if any(m2 is not m1 and any(f is el for f in rf) for m2, rf in redefined_by):
                continue
            reduced.append(m1)
        own_redefined = [r.redefined_feature for f in self.owned_features
                         for r in getattr(f, "owned_redefinitions", ())
                         if r.redefined_feature is not None]
        if not own_redefined:
            return reduced
        return [m for m in reduced
                if not any(any(f is g for g in own_redefined) for f in self.all_redefined_features_of(m))]

    def _all_memberships(self) -> list[Membership]:
        return _unique(self.owned_memberships + self._imported_memberships() + self._inherited())

    def visible_memberships(self, excluded=(), is_recursive: bool = False, include_all: bool = False
                            ) -> list[Membership]:
        out = super().visible_memberships(excluded, is_recursive, include_all)
        inherited = self._inherited(list(excluded) + [self], (), is_recursive)
        out += [m for m in inherited if include_all or m.visibility == PUBLIC]
        return _unique(out)

    @property
    def feature_memberships(self) -> list[FeatureMembership]:
        own = self.owned_feature_memberships
        inh = [m for m in self._inherited() if isinstance(m, FeatureMembership)
               and m.owning_type is not None and self.specializes(m.owning_type)]
        return _unique(own + inh)

    @property
    def features(self) -> list:
        return [m.owned_member_feature for m in self.feature_memberships
                if m.owned_member_feature is not None]

    def _inherited_features(self, *args, **kwargs) -> list:
        return [m.member_element for m in self._inherited(*args, **kwargs)
                if isinstance(m, FeatureMembership) and m.member_element is not None]

    @property
    def inherited_features(self) -> DerivedList:
        """Features of the inherited feature memberships (redefined ones hidden, private ones not
        inherited). Compatibility: still callable as ``inherited_features()``."""
        return DerivedList(self._inherited_features(), self._inherited_features)

    def all_features(self) -> list:
        """Compatibility: owned then inherited features (``features``)."""
        return self.owned_features + [f for f in self._inherited_features()
                                      if not any(f is g for g in self.owned_features)]

    @property
    def end_features(self) -> list:
        return [f for f in self.features if f.is_end]

    def direction_of(self, feature) -> Optional[str]:
        """The direction ('in', 'out', 'inout') of `feature` relative to this type, flipped by
        conjugation; None when it has none."""
        return self._direction_of_excluding(feature, [])

    def _direction_of_excluding(self, feature, excluded: list) -> Optional[str]:
        from .features import FeatureDirection
        excl = excluded + [self]
        if feature.owning_type is self:
            d = feature.direction
            return None if d is FeatureDirection.NONE else d.value
        for t in self.supertypes(False):
            if any(t is x for x in excl):
                continue
            d = t._direction_of_excluding(feature, excl)
            if d is not None:
                return _FLIP.get(d, d) if self.is_conjugated else d
        return None

    @property
    def directed_features(self) -> list:
        return [f for f in self.features if self.direction_of(f) is not None]

    @property
    def inputs(self) -> list:
        return [f for f in self.features if self.direction_of(f) in ("in", "inout")]

    @property
    def outputs(self) -> list:
        return [f for f in self.features if self.direction_of(f) in ("out", "inout")]


class Classifier(Type):
    """A type that classifies things (KerML 8.3.3.2.2). SysML definitions are classifiers."""

    kind = "Classifier"

    @property
    def owned_subclassifications(self) -> list[Subclassification]:
        return [r for r in self.owned_specializations if isinstance(r, Subclassification)]


class DataType(Classifier):
    kind = "DataType"


class Class(Classifier):
    kind = "Class"


class Structure(Class):
    kind = "Structure"


class Behavior(Class):
    """A class of performances; its directed features are ``parameters``."""

    kind = "Behavior"
    _is_behavioral = True

    @property
    def parameters(self) -> list:
        return self.directed_features

    @property
    def steps(self) -> list:
        from .behaviors import Step
        return [f for f in self.features if isinstance(f, Step)]


class Association(Classifier, Relationship):
    """A classifier of links, and a relationship between the types of its end features.

    ``related_types`` (and so ``sources`` / ``targets``) are derived from the
    ``association_ends``: the first end's type is the ``source_type``.
    """

    kind = "Association"

    @property
    def association_ends(self) -> list:
        return self.end_features

    @property
    def related_types(self) -> list["Type"]:
        out: list[Type] = []
        for end in self.association_ends:
            out += end.types
        return out

    @property
    def source_type(self) -> Optional["Type"]:
        rt = self.related_types
        return rt[0] if rt else None

    @property
    def target_types(self) -> list["Type"]:
        return self.related_types[1:]

    @property
    def sources(self) -> list[Element]:  # type: ignore[override]
        s = self.source_type
        return [s] if s is not None else []

    @property
    def targets(self) -> list[Element]:  # type: ignore[override]
        return list(self.target_types)

    @property
    def source(self) -> Optional[Element]:  # type: ignore[override]
        return self.source_type

    @property
    def target(self) -> Optional[Element]:  # type: ignore[override]
        t = self.target_types
        return t[0] if t else None

    @property
    def related_elements(self) -> list[Element]:
        return list(self.related_types)


__all__ = [
    "Specialization", "Subclassification", "Conjugation", "Disjoining", "Unioning",
    "Intersecting", "Differencing", "FeatureMembership",
    "Type", "Classifier", "DataType", "Class", "Structure", "Behavior", "Association",
    "PRIVATE", "PROTECTED", "PUBLIC",
]
