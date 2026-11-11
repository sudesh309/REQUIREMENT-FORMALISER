"""Feature values and multiplicity ranges, materialized from Python values (ADR 0002 decision 5).

In memory a feature's ``multiplicity`` is a :class:`kerml.features.MultiplicityRange`
value and its ``default_value`` a Python value. When a spec view is needed
(interchange, API, derived properties) they are materialized as elements:

* :func:`multiplicity_element` -> an ``OwningMembership`` owning a
  :class:`MultiplicityRangeElement` (spec ``MultiplicityRange``) whose bounds are
  ``LiteralInteger`` / ``LiteralInfinity`` expressions;
* :func:`feature_value` -> a :class:`FeatureValue` (an owning membership)
  owning a literal expression.

The materialized elements are not added to the feature's
``owned_relationships`` (the live tree stays free of trivial elements); their
membership names the feature as its source. Ids are deterministic (UUID v5 of
the feature's id and a role name), so the interchange view of an unchanged
model is stable. :func:`absorb_multiplicity` and :func:`absorb_feature_value`
turn such elements back into values when a model is loaded.
"""
from __future__ import annotations

from typing import Any, Optional

from .elements import Element, derived_id
from .features import Feature, Multiplicity, MultiplicityRange
from .namespaces import OwningMembership


class MultiplicityRangeElement(Multiplicity):
    """Spec ``MultiplicityRange``: a multiplicity with ``lower_bound`` / ``upper_bound`` expressions.

    (Named so because :class:`kerml.features.MultiplicityRange` is the value.)
    """

    kind = "MultiplicityRange"

    @property
    def bounds(self) -> list:
        from .expressions import Expression
        return [x for x in self.owned_members if isinstance(x, Expression)]

    @property
    def lower_bound(self):
        b = self.bounds
        return b[0] if len(b) == 2 else None

    @property
    def upper_bound(self):
        b = self.bounds
        return b[-1] if b else None

    def has_bounds(self, lower: int, upper: Optional[int]) -> bool:
        return self.as_range() == MultiplicityRange(lower, upper)

    def as_range(self) -> Optional[MultiplicityRange]:
        """The value these bounds stand for, or None when a bound is not a literal."""
        from .expressions import LiteralInfinity, LiteralInteger
        ub = self.upper_bound
        lb = self.lower_bound
        if isinstance(ub, LiteralInfinity):
            upper = None
        elif isinstance(ub, LiteralInteger) and isinstance(ub.value, int):
            upper = ub.value
        else:
            return None
        if lb is None:
            lower = 0 if upper is None else upper
        elif isinstance(lb, LiteralInteger) and isinstance(lb.value, int):
            lower = lb.value
        else:
            return None
        try:
            return MultiplicityRange(lower, upper)
        except ValueError:
            return None


class FeatureValue(OwningMembership):
    """Binds a feature to the value of an owned expression (``= v``, ``:= v``, ``default v``)."""

    kind = "FeatureValue"
    _tree_owns = False

    def __init__(self, namespace=None, member=None, *, is_initial: bool = False,
                 is_default: bool = False, **kwargs):
        super().__init__(namespace, member, **kwargs)
        self.is_initial: bool = is_initial
        self.is_default: bool = is_default

    @property
    def feature_with_value(self) -> Optional[Feature]:
        return self.membership_owning_namespace  # type: ignore[return-value]

    @property
    def value(self):
        return self.owned_member_element


def multiplicity_element(feature: Feature) -> OwningMembership:
    """Materialize ``feature.multiplicity`` as a membership owning a MultiplicityRange element."""
    from .expressions import LiteralInfinity, LiteralInteger
    rng = feature.multiplicity
    fid = feature.element_id
    mult = MultiplicityRangeElement(element_id=derived_id(fid, "multiplicity"))
    lower = LiteralInteger(rng.lower, element_id=derived_id(fid, "multiplicity/lower"))
    upper = (LiteralInfinity(element_id=derived_id(fid, "multiplicity/upper")) if rng.upper is None
             else LiteralInteger(rng.upper, element_id=derived_id(fid, "multiplicity/upper")))
    mult.own(lower, membership=OwningMembership)
    mult.own(upper, membership=OwningMembership)
    m = OwningMembership(feature, mult, element_id=derived_id(fid, "multiplicity/membership"))
    return m


def feature_value(feature: Feature) -> Optional[FeatureValue]:
    """Materialize ``feature.default_value`` as a FeatureValue (None when there is no value)."""
    from .expressions import literal_for
    v = feature.default_value
    if v is None:
        return None
    fid = feature.element_id
    expr = literal_for(v, element_id=derived_id(fid, "value/expression"))
    return FeatureValue(feature, expr, element_id=derived_id(fid, "value"))


def absorb_multiplicity(feature: Feature, element: Element) -> bool:
    """Set ``feature.multiplicity`` from a MultiplicityRange element with literal bounds."""
    if isinstance(element, MultiplicityRangeElement):
        rng = element.as_range()
        if rng is not None:
            feature.multiplicity = rng
            return True
    return False


def absorb_feature_value(feature: Feature, membership: Element) -> bool:
    """Set ``feature.default_value`` from a FeatureValue owning a literal expression."""
    from .expressions import LiteralExpression, NullExpression
    if not isinstance(membership, FeatureValue):
        return False
    v = membership.value
    if isinstance(v, NullExpression):
        feature.default_value = None
        return True
    if isinstance(v, LiteralExpression) and type(v).__name__ != "LiteralInfinity":
        feature.default_value = v.value
        return True
    return False


def multiplicity_of(element: Any) -> Optional[MultiplicityRange]:
    return getattr(element, "multiplicity", None)
