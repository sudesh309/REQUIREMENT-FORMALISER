"""Connectors (KerML 8.3.4.5): Connector, BindingConnector, Succession.

A Connector is both a Feature and a Relationship. Its ``connector_ends`` are
end features owned through ``EndFeatureMembership``; each end references the
connected feature through a ``ReferenceSubsetting``, either directly or
through an owned feature chain (``a.p``: the end references a chain feature
whose ``chaining_features`` are ``[a, p]``). The connector's
``related_features`` (and so its ``sources`` / ``targets``) are derived from
the ends.

:meth:`Connector.add_end` builds that structure; ``end_feature`` /
``end_context`` read it back.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .elements import Element, Relationship, derived_id
from .features import EndFeatureMembership, Feature, MultiplicityRange, ReferenceSubsetting


def referenced_feature(end: Feature) -> Optional[Feature]:
    """What a connector end references (the chain feature for ``a.p``)."""
    rs = end.owned_reference_subsetting
    return rs.referenced_feature if rs is not None else None


def end_feature(end: Feature) -> Optional[Feature]:
    """The connected feature of an end: the referenced feature, or the last link of its chain."""
    ref = referenced_feature(end)
    if ref is None:
        return None
    chain = ref.chaining_features
    return chain[-1] if chain else ref


def end_context(end: Feature) -> Optional[Feature]:
    """The feature through which the end is reached (``a`` for ``a.p``), or None."""
    ref = referenced_feature(end)
    if ref is None:
        return None
    chain = ref.chaining_features
    return chain[-2] if len(chain) >= 2 else None


class Connector(Feature, Relationship):
    """A feature that relates the values of its end features (KerML 8.3.4.5.2)."""

    kind = "Connector"
    _is_connector = True

    def __init__(self, name: Optional[str] = None, *,
                 related_features: Optional[Iterable[Feature]] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        for f in related_features or ():
            self.add_end(f)

    # --- ends ------------------------------------------------------------------
    def _new_end(self, **kwargs) -> Feature:
        """The kind of feature used for a new end (SysML connections use ReferenceUsage)."""
        return Feature(**kwargs)

    def add_end(self, feature: Optional[Feature], *, via: Optional[Feature] = None,
                name: Optional[str] = None, element_id: Optional[str] = None) -> Feature:
        """Add an end that references `feature` (through ``via.feature`` when `via` is given).

        Ids are deterministic when `element_id` is given: the reference
        subsetting, the chain feature and its chainings derive theirs from it.
        """
        eid = element_id
        end = self._new_end(element_id=eid) if eid else self._new_end()
        end.name = name
        end.is_end = True
        end.multiplicity = MultiplicityRange(1, 1)
        self._attach_reference(end, feature, via)
        self.own(end, membership=EndFeatureMembership)
        return end

    @staticmethod
    def _attach_reference(end: Feature, feature: Optional[Feature], via: Optional[Feature]) -> None:
        if feature is None:
            return
        eid = end.element_id
        if via is None:
            end.reference_subset(feature, element_id=derived_id(eid, "reference"))
            return
        chain = Feature(element_id=derived_id(eid, "chain"))
        chain.chain(via, feature, ids=[derived_id(eid, "chain/1"), derived_id(eid, "chain/2")])
        rs = ReferenceSubsetting(end, chain, element_id=derived_id(eid, "reference"))
        rs.add_owned_related_element(chain)
        old = end.owned_reference_subsetting
        if old is not None:
            end.remove_relationship(old)
        end.add_relationship(rs)

    def set_end_reference(self, end: Feature, feature: Optional[Feature], via: Optional[Feature] = None) -> None:
        """Point an existing end at `feature` (through `via`)."""
        old = end.owned_reference_subsetting
        if old is not None:
            end.remove_relationship(old)
        self._attach_reference(end, feature, via)

    def remove_ends(self) -> None:
        for end in self.connector_ends:
            end.detach()

    @property
    def connector_ends(self) -> list[Feature]:
        return [f for f in self.owned_features if f.is_end]

    @property
    def related_features(self) -> list[Feature]:
        out = []
        for end in self.connector_ends:
            ref = referenced_feature(end)
            if ref is not None:
                out.append(ref)
        return out

    @property
    def source_feature(self) -> Optional[Feature]:
        rf = self.related_features
        return rf[0] if rf else None

    @property
    def target_features(self) -> list[Feature]:
        return self.related_features[1:]

    @property
    def association(self) -> list:
        return self.types

    @property
    def default_featuring_type(self):
        return self.owning_type

    # --- Relationship view (derived) -------------------------------------------
    @property
    def sources(self) -> list[Element]:  # type: ignore[override]
        s = self.source_feature
        return [s] if s is not None else []

    @property
    def targets(self) -> list[Element]:  # type: ignore[override]
        return list(self.target_features)

    @property
    def source(self) -> Optional[Element]:  # type: ignore[override]
        return self.source_feature

    @property
    def target(self) -> Optional[Element]:  # type: ignore[override]
        t = self.target_features
        return t[0] if t else None

    @property
    def related_elements(self) -> list[Element]:
        return list(self.related_features)


class BindingConnector(Connector):
    """A connector asserting that its ends have the same values (``bind a = b``)."""

    kind = "BindingConnector"


class Succession(Connector):
    """A connector asserting that its source happens before its targets (``first a then b``)."""

    kind = "Succession"


__all__ = ["Connector", "BindingConnector", "Succession", "referenced_feature", "end_feature",
           "end_context"]
