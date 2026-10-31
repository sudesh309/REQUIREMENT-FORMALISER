"""Instantiation, invocation, operator and metadata access expressions (KerML 8.3.4.8).

The literal, null and feature reference expressions are in
:mod:`kerml.expressions`; this module adds the rest of the Expressions
package:

* :class:`InstantiationExpression` (abstract): its ``instantiated_type`` is the
  member of its first owned membership that is not a FeatureMembership.
  :class:`InvocationExpression` binds its arguments to the input parameters of
  that type; :class:`ConstructorExpression` to the features of its result.
* :class:`OperatorExpression` is an invocation whose type is the library
  function named by its ``operator`` (``BaseFunctions``, ``DataFunctions`` or
  ``ControlFunctions``); :class:`FeatureChainExpression` (``.``),
  :class:`SelectExpression` (``select``), :class:`CollectExpression`
  (``collect``) and :class:`IndexExpression` (``#``) fix the operator.
* :class:`MetadataAccessExpression` (``x.metadata``) references an element.

Arguments are the value expressions of the ``FeatureValue``\\ s of owned
features (:func:`value_expression`); :meth:`InvocationExpression.add_argument`
and :meth:`ConstructorExpression.add_argument` build that structure.
Evaluation is Phase 3.
"""
from __future__ import annotations

from typing import Any, Optional

from .elements import Element, escape_name
from .expressions import Expression, literal_for
from .features import Feature, FeatureDirection
from .types import FeatureMembership, Type


# ---------------------------------------------------------------------------
# Helpers shared with the SysML action usages
# ---------------------------------------------------------------------------

def value_expression(feature: Feature) -> Optional[Expression]:
    """The value Expression of the FeatureValue of `feature`, or None (spec ``valuation.value``).

    An owned ``FeatureValue`` wins; a literal ``default_value`` is materialized
    (ADR 0002 decision 5).
    """
    from .values import FeatureValue
    for r in feature.owned_relationships:
        if isinstance(r, FeatureValue):
            return r.value  # type: ignore[return-value]
    fv = feature.value_membership()
    return fv.value if fv is not None else None  # type: ignore[return-value]


def set_value_expression(feature: Feature, value: Any) -> Expression:
    """Make `value` (an Expression, or a Python literal) the value of `feature` via a FeatureValue."""
    from .values import FeatureValue
    for r in feature.owned_relationships:
        if isinstance(r, FeatureValue):
            feature.remove_relationship(r)
    expr = value if isinstance(value, Element) else literal_for(value)
    feature.own(expr, membership=FeatureValue)
    return expr  # type: ignore[return-value]


def result_parameter(expression: Type) -> Optional[Feature]:
    """The result parameter of a Function or Expression (spec ``result``).

    The member of the first (owned or inherited) ReturnParameterMembership.
    """
    from .behaviors import ReturnParameterMembership
    for m in expression.feature_memberships:
        if isinstance(m, ReturnParameterMembership):
            return m.owned_member_element  # type: ignore[return-value]
    return None


def _first_member_not(namespace, excluded: type) -> Optional[Element]:
    for m in namespace.owned_memberships:
        if not isinstance(m, excluded):
            return m.member_element
    return None


def _values_redefining(features: list, targets: list) -> list:
    """For each target in order, the values of the features that redefine it."""
    out = []
    for target in targets:
        for f in features:
            if f.redefines(target):
                v = value_expression(f)
                if v is not None:
                    out.append(v)
    return out


# ---------------------------------------------------------------------------
# Instantiation and invocation
# ---------------------------------------------------------------------------

class InstantiationExpression(Expression):
    """An Expression that instantiates its ``instantiated_type`` (KerML 8.3.4.8.7; abstract).

    ``instantiated_type=`` makes the type the member of a (non-owning)
    Membership of the expression.
    """

    kind = "InstantiationExpression"

    def __init__(self, name: Optional[str] = None, *, instantiated_type: Optional[Type] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        if instantiated_type is not None:
            self.add_member(instantiated_type, owned=False)

    def _instantiated_type(self) -> Optional[Type]:
        """The spec operation ``instantiatedType()`` (overridden by OperatorExpression)."""
        t = _first_member_not(self, FeatureMembership)
        return t if isinstance(t, Type) else None

    @property
    def instantiated_type(self) -> Optional[Type]:
        """The Type being instantiated (spec ``instantiatedType``, given by ``instantiatedType()``)."""
        return self._instantiated_type()

    @property
    def arguments(self) -> list[Expression]:
        """The argument Expressions (spec ``argument``); see the subclasses."""
        return []

    def _owned_input_parameters(self) -> list[Feature]:
        return [f for f in self.owned_features
                if f.direction in (FeatureDirection.IN, FeatureDirection.INOUT)]


class InvocationExpression(InstantiationExpression):
    """Invokes a Behavior (or a Feature typed by one) with argument values (KerML 8.3.4.8.8).

    ``arguments`` are the values of the owned features that redefine the
    inputs of the instantiated type, in the order of those inputs. When no
    owned feature redefines an input (for example while the library function
    is not loaded) they are the values of the owned input parameters in order.
    """

    kind = "InvocationExpression"

    @property
    def arguments(self) -> list[Expression]:
        owned = self.owned_features
        t = self.instantiated_type
        if t is not None:
            inputs = t.inputs
            if any(f.redefines(inp) for f in owned for inp in inputs):
                return _values_redefining(owned, inputs)
        out = []
        for p in self._owned_input_parameters():
            v = value_expression(p)
            if v is not None:
                out.append(v)
        return out

    def add_argument(self, value: Any, *, parameter: Optional[Feature] = None,
                     name: Optional[str] = None) -> Feature:
        """Bind `value` (an Expression or a Python literal) to an owned input parameter.

        The parameter redefines `parameter`, or else the next input of the
        instantiated type that no owned parameter redefines yet (if any).
        """
        if parameter is None:
            t = self.instantiated_type
            if t is not None:
                taken = [f for f in self.owned_features]
                parameter = next((inp for inp in t.inputs
                                  if not any(f.redefines(inp) for f in taken)), None)
        p = Feature(name, direction=FeatureDirection.IN)
        if parameter is not None:
            p.redefine(parameter)
        self.own(p)
        set_value_expression(p, value)
        return p


class ConstructorExpression(InstantiationExpression):
    """Instantiates its type with features bound to argument values (KerML 8.3.4.8.3).

    ``arguments`` are the values of the owned features of the result parameter
    that redefine features of the instantiated type, in the order of those
    features (the values of the result's owned features in order when none
    redefines one).
    """

    kind = "ConstructorExpression"

    @property
    def arguments(self) -> list[Expression]:
        result = result_parameter(self)
        if result is None:
            return []
        owned = result.owned_features
        t = self.instantiated_type
        if t is not None:
            features = t.features
            if any(f.redefines(g) for f in owned for g in features):
                return _values_redefining(owned, features)
        return [v for v in (value_expression(f) for f in owned) if v is not None]

    def ensure_result(self) -> Feature:
        """The result parameter, created (``out``, through a ReturnParameterMembership) if missing."""
        from .behaviors import ReturnParameterMembership
        result = result_parameter(self)
        if result is None:
            result = Feature(direction=FeatureDirection.OUT)
            self.own(result, membership=ReturnParameterMembership)
        return result

    def add_argument(self, value: Any, *, feature: Optional[Feature] = None,
                     name: Optional[str] = None) -> Feature:
        """Bind `value` to an owned feature of the result that redefines `feature`."""
        inner = Feature(name)
        if feature is not None:
            inner.redefine(feature)
        self.ensure_result().own(inner)
        set_value_expression(inner, value)
        return inner


# ---------------------------------------------------------------------------
# Operator expressions
# ---------------------------------------------------------------------------

class OperatorExpression(InvocationExpression):
    """An invocation of the library function named by ``operator`` (KerML 8.3.4.8.17).

    The instantiated type is the resolution of ``operator`` in the global
    packages ``BaseFunctions``, ``DataFunctions`` and ``ControlFunctions``
    (None until those library packages are loaded).
    """

    kind = "OperatorExpression"
    #: The packages ``operator`` is resolved in, in order.
    LIBRARY_PACKAGES: tuple[str, ...] = ("BaseFunctions", "DataFunctions", "ControlFunctions")
    _default_operator: Optional[str] = None

    def __init__(self, name: Optional[str] = None, *, operator: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.operator: Optional[str] = operator if operator is not None else self._default_operator

    def _instantiated_type(self) -> Optional[Type]:
        if not self.operator:
            return None
        for package in self.LIBRARY_PACKAGES:
            m = self.resolve_global(f"{package}::{escape_name(self.operator)}")
            if m is not None and m.member_element is not None:
                el = m.member_element
                return el if isinstance(el, Type) else None
        return None


class FeatureChainExpression(OperatorExpression):
    """``a.b``: chains the result of its argument with its ``target_feature`` (KerML 8.3.4.8.4)."""

    kind = "FeatureChainExpression"
    _default_operator = "."

    def __init__(self, name: Optional[str] = None, *, target_feature: Optional[Feature] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        if target_feature is not None:
            self.add_member(target_feature, owned=False)

    @property
    def target_feature(self) -> Optional[Feature]:
        """The member of the first owned membership that is not a ParameterMembership, if a Feature
        (spec ``targetFeature``)."""
        from .behaviors import ParameterMembership
        f = _first_member_not(self, ParameterMembership)
        return f if isinstance(f, Feature) else None

    def source_target_feature(self) -> Optional[Feature]:
        """The first owned feature of the first owned input parameter (spec ``sourceTargetFeature()``)."""
        inputs = [f for f in self.owned_features if f.direction is FeatureDirection.IN]
        if not inputs:
            return None
        owned = inputs[0].owned_features
        return owned[0] if owned else None


class SelectExpression(OperatorExpression):
    """``s->select {...}`` (KerML 8.3.4.8.18)."""

    kind = "SelectExpression"
    _default_operator = "select"


class CollectExpression(OperatorExpression):
    """``s->collect {...}`` (KerML 8.3.4.8.2)."""

    kind = "CollectExpression"
    _default_operator = "collect"


class IndexExpression(OperatorExpression):
    """``s#(i)`` (KerML 8.3.4.8.6)."""

    kind = "IndexExpression"
    _default_operator = "#"


# ---------------------------------------------------------------------------
# Metadata access
# ---------------------------------------------------------------------------

class MetadataAccessExpression(Expression):
    """``x.metadata``: the metadata of its ``referenced_element`` (KerML 8.3.4.8.15)."""

    kind = "MetadataAccessExpression"

    def __init__(self, name: Optional[str] = None, *, referenced_element: Optional[Element] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        if referenced_element is not None:
            self.add_member(referenced_element, owned=False)

    @property
    def referenced_element(self) -> Optional[Element]:
        """The member of the first owned membership that is not a FeatureMembership
        (spec ``referencedElement``)."""
        return _first_member_not(self, FeatureMembership)


__all__ = [
    "InstantiationExpression", "InvocationExpression", "ConstructorExpression",
    "OperatorExpression", "FeatureChainExpression", "SelectExpression", "CollectExpression",
    "IndexExpression", "MetadataAccessExpression",
    "value_expression", "set_value_expression", "result_parameter",
]
