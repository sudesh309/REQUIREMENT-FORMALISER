"""JSON (de)serialization of repositories and metamodel elements.

Serialization is structural: every Element is captured by `kind`, id,
name, owner-id, and a kind-specific payload. References to other
elements are stored by id and re-bound on load.
"""
from __future__ import annotations

import importlib
import json
from typing import Any, Callable, TYPE_CHECKING

from kerml.elements import Documentation, Element, Relationship, is_pure_relationship
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package
from kerml.types import Type
from kerml.stereotypes import Stereotype, StereotypeTag, stereotypes_on
from sysmlv2.definitions import StateUsage, TransitionUsage
from sysmlv2.state_machines import StateMachineDefinition

if TYPE_CHECKING:
    from .repository import Repository


def is_pure_relationship_class(cls: type) -> bool:
    from kerml.types import Type
    return issubclass(cls, Relationship) and not issubclass(cls, Type)


_STORED: dict = {}


def _stored_attr(e: object, attr: str) -> bool:
    """Is `attr` a stored (assignable) attribute of `e`, not a derived property?"""
    cls = type(e)
    kind = _STORED.get((cls, attr))
    if kind is None:
        prop = getattr(cls, attr, None)
        if isinstance(prop, property):
            kind = 1 if prop.fset is not None else 0
        else:
            kind = 2 if prop is None else 1
        _STORED[(cls, attr)] = kind
    if kind == 2:
        return attr in getattr(e, "__dict__", {})
    return kind == 1


def _fqcn(obj: object) -> str:
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


_CLASSES: dict[str, type] = {}


def _resolve_class(fqcn: str) -> type:
    cls = _CLASSES.get(fqcn)
    if cls is None:
        mod, _, name = fqcn.rpartition(".")
        cls = _CLASSES[fqcn] = getattr(importlib.import_module(mod), name)
    return cls


# -- extension codecs ----------------------------------------------------
#
# Feature modules persist extra state without editing this file:
#
#   register_codec("variants", encode, decode)
#       encode(element) -> JSON-able data, or None when the element has nothing to save
#       decode(element, data, by_id) runs after every element, link and stereotype
#       application is restored; by_id maps saved ids to restored elements.
#
#   register_repo_codec("allocations", encode, decode)
#       project-level state: encode(repo) -> data|None, decode(repo, data, by_id).
#
# The registering module's name is saved next to the data and imported on load,
# so a project loads correctly even if that module was not imported yet.

_CODECS: dict[str, tuple[str, Callable, Callable]] = {}
_REPO_CODECS: dict[str, tuple[str, Callable, Callable]] = {}


def register_codec(name: str, encode: Callable[[Element], Any],
                   decode: Callable[[Element, Any, dict], None]) -> None:
    _CODECS[name] = (encode.__module__, encode, decode)


def register_repo_codec(name: str, encode: Callable[["Repository"], Any],
                        decode: Callable[["Repository", Any, dict], None]) -> None:
    _REPO_CODECS[name] = (encode.__module__, encode, decode)


def _encode_ext(codecs: dict, target: Any) -> dict:
    out = {}
    for name, (module, encode, _decode) in codecs.items():
        data = encode(target)
        if data is not None:
            out[name] = {"module": module, "data": data}
    return out


def _decode_ext(codecs: dict, ext: dict, target: Any, by_id: dict) -> None:
    for name, entry in ext.items():
        if name not in codecs:
            importlib.import_module(entry["module"])
        codecs[name][2](target, entry["data"], by_id)


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


