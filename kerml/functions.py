"""Result expressions of functions and expressions (KerML 8.3.4.7.7).

``Function``, ``Predicate`` and ``ReturnParameterMembership`` are in
:mod:`kerml.behaviors`; this module adds the membership through which a
Function or Expression owns the Expression that computes its result.
"""
from __future__ import annotations

from typing import Optional

from .types import FeatureMembership


class ResultExpressionMembership(FeatureMembership):
    """Owns the Expression that provides the result of its owning Function or Expression.

    The owner must also own a BindingConnector between its result parameter
    and the result of the owned expression (KerML 8.3.4.7.7).
    """

    kind = "ResultExpressionMembership"

    @property
    def owned_result_expression(self) -> Optional[object]:
        """The owned Expression (spec ``ownedResultExpression``)."""
        from .expressions import Expression
        m = self.owned_member_element
        return m if isinstance(m, Expression) else None


__all__ = ["ResultExpressionMembership"]
