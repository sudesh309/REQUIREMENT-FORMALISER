"""KerML expressions: literals, feature references, invocations.

Expressions are model elements that evaluate to a value. They are used by
constraint definitions, calculation definitions, default-value bindings,
and requirement assumed/required predicates.
"""
from __future__ import annotations

from typing import Any, Optional

from .features import Feature
from .types import Type


class Expression(Feature):
    """An expression is a Feature whose values are produced by evaluation."""

    kind = "Expression"

    def evaluate(self, context: Optional[dict] = None) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError


class LiteralExpression(Expression):
    """Literal value (boolean, integer, real, string, null)."""

    kind = "LiteralExpression"

    def __init__(self, value: Any, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def evaluate(self, context: Optional[dict] = None) -> Any:
        return self.value


class FeatureReferenceExpression(Expression):
    """Reference to another Feature; evaluates by looking it up in `context`."""

    kind = "FeatureReferenceExpression"

    def __init__(self, referent: Feature, **kwargs):
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

    def __init__(self, function: Type, arguments: Optional[list[Expression]] = None, **kwargs):
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
