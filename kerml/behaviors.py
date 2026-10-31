"""Behaviors, steps and functions (KerML 8.3.4.6, 8.3.4.7) and parameter memberships.

``Behavior`` lives in :mod:`kerml.types` with the other classifiers. A
Behavior or Step owns its directed features through
``ParameterMembership`` (``ReturnParameterMembership`` for a feature whose
``parameter_kind`` is ``'return'``); ``Type.own`` picks them.
"""
from __future__ import annotations

from typing import Optional

from .features import Feature
from .types import Behavior, FeatureMembership


class ParameterMembership(FeatureMembership):
    """Owning membership of a parameter (a directed feature of a behavior or step)."""

    kind = "ParameterMembership"

    @property
    def owned_member_parameter(self) -> Optional[Feature]:
        return self.owned_member_element  # type: ignore[return-value]


class ReturnParameterMembership(ParameterMembership):
    """Owning membership of the result parameter of a function or expression."""

    kind = "ReturnParameterMembership"


class Step(Feature):
    """A feature typed by behaviors (a performance within an occurrence)."""

    kind = "Step"
    _is_behavioral = True

    @property
    def behaviors(self) -> list:
        return [t for t in self.types if isinstance(t, Behavior)]

    @property
    def parameters(self) -> list:
        return self.directed_features


class Function(Behavior):
    """A behavior with a single ``result`` parameter."""

    kind = "Function"

    @property
    def result(self) -> Optional[Feature]:
        return next((m.owned_member_element for m in self.owned_feature_memberships
                     if isinstance(m, ReturnParameterMembership)), None)

    @property
    def expressions(self) -> list:
        from .expressions import Expression
        return [f for f in self.features if isinstance(f, Expression)]


class Predicate(Function):
    """A function whose result is Boolean."""

    kind = "Predicate"


__all__ = ["ParameterMembership", "ReturnParameterMembership", "Step", "Function", "Predicate"]
