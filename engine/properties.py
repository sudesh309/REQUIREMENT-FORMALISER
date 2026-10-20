"""Setting element properties from untyped input (web API, MCP, tables).

Both front ends funnel property edits through ``set_property`` so values are
coerced the same way everywhere. Unknown keys and non-scalar attributes are
rejected with ``ValueError`` instead of being written blindly: a raw
``setattr`` of, say, a string into ``direction`` or ``ends`` corrupts the
element so it can no longer be serialized.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from kerml.elements import Documentation, Element
from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.types import Type

Resolver = Callable[[str], Optional[Element]]

_PROTECTED = {"owner", "element_id", "kind", "tool_data", "annotations"}

# Optional scalar attributes that start out as None and may be set by name.
# Feature modules add theirs with register_scalar_property().
_NULLABLE_SCALARS = {
    "req_id", "text", "default_value",
    "trigger_event", "guard", "effect", "entry_action", "do_action", "exit_action",
}


def register_scalar_property(name: str) -> None:
    _NULLABLE_SCALARS.add(name)


def _same_scalar_family(current: Any, value: Any) -> bool:
    if isinstance(current, bool) or isinstance(value, bool):
        return isinstance(current, bool) and isinstance(value, bool)
    if isinstance(current, (int, float)):
        return isinstance(value, (int, float))
    return isinstance(current, str) and isinstance(value, str)


def set_property(e: Element, key: str, value: Any, resolve: Resolver) -> None:
    """Set one property on `e`; `resolve` maps an id or qualified name to an element."""
    if key == "name":
        e.name = value or None
    elif key == "short_name":
        e.short_name = value or None
    elif key == "is_abstract":
        e.is_abstract = bool(value)
    elif key == "multiplicity":
        if not isinstance(e, Feature):
            raise ValueError(f"{e.kind} has no multiplicity")
        lo, up = value
        e.multiplicity = MultiplicityRange(int(lo), None if up in (None, "*", "") else int(up))
    elif key == "direction":
        if not isinstance(e, Feature):
            raise ValueError(f"{e.kind} has no direction")
        try:
            e.direction = FeatureDirection(value or "none")
        except ValueError:
            raise ValueError(f"direction must be one of {[d.value for d in FeatureDirection]}") from None
    elif key == "doc":
        e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
        if value:
            e.add_annotation(Documentation(body=str(value)))
    elif key == "typed_by":
        if not isinstance(e, Feature):
            raise ValueError(f"{e.kind} cannot be typed")
        ref = value if isinstance(value, str) else (value[0] if value else None)
        e.feature_typings = []
        e.owned_relationships = [r for r in e.owned_relationships if r.kind != "FeatureTyping"]
        if ref:
            t = resolve(ref)
            if not isinstance(t, Type):
                raise ValueError(f"type {ref!r} not found")
            e.add_type(t)
    elif key == "tool_data":
        if not isinstance(value, dict):
            raise ValueError("tool_data must be an object")
        # Merge so independent UI features (layout, colours, ...) don't clobber each other.
        e.tool_data.update(value)
    elif key in _PROTECTED or not hasattr(e, key):
        raise ValueError(f"cannot set {key!r} on {e.kind}")
    else:
        current = getattr(e, key)
        # Allow-listed optional scalars may be set from or cleared back to None.
        settable = (key in _NULLABLE_SCALARS
                    and (current is None or value is None or _same_scalar_family(current, value))
                    and (value is None or isinstance(value, (str, int, float, bool))))
        if not (settable or _same_scalar_family(current, value)):
            raise ValueError(f"cannot set {key!r} on {e.kind} to {type(value).__name__}")
        setattr(e, key, value)


def set_properties(e: Element, props: dict, resolve: Resolver) -> None:
    for key, value in props.items():
        set_property(e, key, value, resolve)
