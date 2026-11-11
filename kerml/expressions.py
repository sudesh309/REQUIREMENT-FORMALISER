"""KerML expressions (KerML 8.3.4.8): literals, feature references, invocations.

Expressions are steps that evaluate to a value. They are used by constraint
definitions, calculation definitions, feature values and filter conditions.
Phase 1 keeps the small Python evaluator below; model-level evaluation over
the Kernel Function Library comes with Phase 3.
"""
from __future__ import annotations

from typing import Any, Optional

from .behaviors import Step
from .features import Feature
from .types import Type


class Expression(Step):
    """An expression is a Step whose values are produced by evaluation."""

    kind = "Expression"

    def evaluate(self, context: Optional[dict] = None) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError


class BooleanExpression(Expression):
    kind = "BooleanExpression"


class Invariant(BooleanExpression):
    kind = "Invariant"

    def __init__(self, name: Optional[str] = None, *, is_negated: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_negated: bool = is_negated


class LiteralExpression(Expression):
    """Literal value (boolean, integer, real, string, null).

    The typed subclasses (:class:`LiteralBoolean`, :class:`LiteralInteger`,
    :class:`LiteralRational`, :class:`LiteralString`, :class:`LiteralInfinity`)
    are the spec metaclasses; :func:`literal_for` picks one for a Python value.
    """

    kind = "LiteralExpression"

    def __init__(self, value: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def evaluate(self, context: Optional[dict] = None) -> Any:
        return self.value


class LiteralBoolean(LiteralExpression):
    kind = "LiteralBoolean"


class LiteralInteger(LiteralExpression):
    kind = "LiteralInteger"


class LiteralRational(LiteralExpression):
    kind = "LiteralRational"


class LiteralString(LiteralExpression):
    kind = "LiteralString"


class LiteralInfinity(LiteralExpression):
    """``*`` (an unbounded upper multiplicity)."""

    kind = "LiteralInfinity"

    def __init__(self, **kwargs):
        kwargs.pop("value", None)
        super().__init__(None, **kwargs)


class NullExpression(Expression):
    kind = "NullExpression"

    def evaluate(self, context: Optional[dict] = None) -> Any:
        return None


def literal_for(value: Any, **kwargs) -> Expression:
    """The literal expression for a Python value (None -> NullExpression)."""
    if value is None:
        return NullExpression(**kwargs)
    if isinstance(value, bool):
        return LiteralBoolean(value, **kwargs)
    if isinstance(value, int):
        return LiteralInteger(value, **kwargs)
    if isinstance(value, float):
        return LiteralRational(value, **kwargs)
    if isinstance(value, str):
        return LiteralString(value, **kwargs)
    return LiteralExpression(value, **kwargs)


def is_literal_value(value: Any) -> bool:
    """Can `value` be written as a literal expression?"""
    return value is None or isinstance(value, (bool, int, float, str))


class FeatureReferenceExpression(Expression):
    """Reference to another Feature; evaluates by looking it up in `context`."""

    kind = "FeatureReferenceExpression"

    def __init__(self, referent: Optional[Feature] = None, **kwargs):
        super().__init__(**kwargs)
        self.referent = referent

    def evaluate(self, context: Optional[dict] = None) -> Any:
        ctx = context or {}
        if self.referent.element_id in ctx:
            return ctx[self.referent.element_id]
        return ctx.get(self.referent.qualified_name, self.referent.default_value)


class Invocation(Expression):
    """Invocation of a Function/Behavior with positional argument expressions."""

    kind = "Invocation"
    spec_metaclass = "InvocationExpression"

    def __init__(self, function: Optional[Type] = None, arguments: Optional[list[Expression]] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.function = function
        self.arguments: list[Expression] = arguments or []

    def evaluate(self, context: Optional[dict] = None) -> Any:
        impl = getattr(self.function, "python_impl", None)
        if impl is None:
            raise RuntimeError(f"No evaluator bound to {self.function.qualified_name!r}")
        return impl(*[a.evaluate(context) for a in self.arguments])


# Built-in operator functions ------------------------------------------------

def _make_builtin(name: str, fn) -> Type:
    t = Type(name=name)
    t.python_impl = fn  # type: ignore[attr-defined]
    return t


BUILTINS: dict[str, Type] = {
    "+":  _make_builtin("+",  lambda a, b: a + b),
    "-":  _make_builtin("-",  lambda a, b: a - b),
    "*":  _make_builtin("*",  lambda a, b: a * b),
    "/":  _make_builtin("/",  lambda a, b: a / b),
    "==": _make_builtin("==", lambda a, b: a == b),
    "!=": _make_builtin("!=", lambda a, b: a != b),
    "<":  _make_builtin("<",  lambda a, b: a < b),
    "<=": _make_builtin("<=", lambda a, b: a <= b),
    ">":  _make_builtin(">",  lambda a, b: a > b),
    ">=": _make_builtin(">=", lambda a, b: a >= b),
    "and": _make_builtin("and", lambda a, b: bool(a) and bool(b)),
    "or":  _make_builtin("or",  lambda a, b: bool(a) or bool(b)),
    "not": _make_builtin("not", lambda a: not bool(a)),
}
