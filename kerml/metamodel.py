"""The KerML / SysML metamodel registry (ADR 0002, decisions 1 and 2).

The registry is data generated from the reflective abstract-syntax models by
``python -m tools.metagen`` (``kerml/_metamodel_kerml.py``,
``sysmlv2/_metamodel_sysml.py``). This module loads the KerML part on import;
``import sysmlv2.metamodel`` registers the SysML part (``kerml`` never imports
``sysmlv2`` itself, except to discover classes in ``python_classes()``).

    metaclass("Subclassification").supertypes       # ('Specialization',)
    supertypes_closure("Subclassification")          # ['Specialization', 'Relationship', 'Element']
    properties("FeatureTyping", derived=False)       # owned + inherited, redefined ones hidden
    python_name(metaclass("Element").property("ownedRelationship"))   # 'owned_relationships'
    spec_metaclass_of(PartUsage)                     # 'PartUsage'

Python classes name their metaclass with ``kind``; application classes whose
``kind`` is not a spec metaclass set ``spec_metaclass`` to the metaclass they
are interchanged as.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Optional, Union

from . import _metamodel_kerml


# --- specs --------------------------------------------------------------------

@dataclass(frozen=True)
class PropertySpec:
    """A property of a metaclass, as declared in the reflective model."""

    owner: str                      # the metaclass that declares it
    name: str                       # spec (camelCase) name
    type: str                       # metaclass, enumeration or ScalarValues type
    lower: int
    upper: Optional[int]            # None is *
    ordered: bool = False
    unique: bool = True
    derived: bool = False
    composite: bool = False
    abstract: bool = False
    var: bool = False               # `var` written in the reflective model (KerML only)
    readonly: bool = False
    subsets: tuple[str, ...] = ()   # resolved "Metaclass::property" names
    redefines: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}::{self.name}"

    @property
    def multi_valued(self) -> bool:
        return self.upper is None or self.upper > 1

    @property
    def python_name(self) -> str:
        return python_name(self)


@dataclass(frozen=True)
class MetaclassSpec:
    name: str
    language: str                   # "KerML" or "SysML"
    package: str                    # "Root", "Core", "Kernel" or "Systems"
    is_abstract: bool
    supertypes: tuple[str, ...]     # direct, in declaration order
    properties: tuple[PropertySpec, ...]   # owned, in declaration order

    @property
    def qualified_name(self) -> str:
        return f"{self.language}::{self.package}::{self.name}"

    def property(self, name: str) -> Optional[PropertySpec]:
        """The owned property called ``name`` (spec name), or None."""
        return next((p for p in self.properties if p.name == name), None)


@dataclass(frozen=True)
class EnumSpec:
    name: str
    language: str
    package: str
    literals: tuple[str, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.language}::{self.package}::{self.name}"


# --- registry -----------------------------------------------------------------

_METACLASSES: dict[str, MetaclassSpec] = {}
_ENUMS: dict[str, EnumSpec] = {}
_LANGUAGES: dict[str, str] = {}             # "kerml" -> "KerML"
_CLOSURES: dict[str, tuple[str, ...]] = {}


def register(data: ModuleType) -> None:
    """Add a generated data module (``LANGUAGE``, ``METACLASSES``, ``ENUMS``). Idempotent."""
    language = data.LANGUAGE
    if language.lower() in _LANGUAGES:
        return
    metas = []
    for m in data.METACLASSES:
        props = tuple(PropertySpec(owner=m["name"], **p) for p in m["properties"])
        metas.append(MetaclassSpec(m["name"], language, m["package"], m["abstract"],
                                   tuple(m["supertypes"]), props))
    known = set(_METACLASSES) | {m.name for m in metas}
    for m in metas:
        missing = [s for s in m.supertypes if s not in known]
        if missing:
            raise ValueError(f"{language} metaclass {m.name} specializes unregistered {missing}")
    for m in metas:
        _METACLASSES[m.name] = m
    for e in data.ENUMS:
        _ENUMS[e["name"]] = EnumSpec(e["name"], language, e["package"], tuple(e["literals"]))
    _LANGUAGES[language.lower()] = language
    _CLOSURES.clear()


def languages() -> list[str]:
    """Registered languages, in registration order (``["KerML", "SysML"]``)."""
    return list(_LANGUAGES.values())


def _simple(name: str) -> str:
    return name.rsplit("::", 1)[-1]


def is_metaclass(name: object) -> bool:
    return isinstance(name, str) and _simple(name) in _METACLASSES


def metaclass(name: str) -> MetaclassSpec:
    """The metaclass called ``name`` (simple or qualified name)."""
    try:
        return _METACLASSES[_simple(name)]
    except KeyError:
        hint = "" if "sysml" in _LANGUAGES else " (import sysmlv2.metamodel for SysML metaclasses)"
        raise KeyError(f"no metaclass {name!r}{hint}") from None


def _language(language: Optional[str]) -> Optional[str]:
    if language is None:
        return None
    try:
        return _LANGUAGES[language.lower()]
    except KeyError:
        raise KeyError(f"unknown or unregistered language {language!r}; "
                       f"registered: {languages()}") from None


def all_metaclasses(language: Optional[str] = None) -> list[MetaclassSpec]:
    """Every registered metaclass (of one language), in declaration order."""
    lang = _language(language)
    return [m for m in _METACLASSES.values() if lang is None or m.language == lang]


def enum(name: str) -> EnumSpec:
    try:
        return _ENUMS[_simple(name)]
    except KeyError:
        raise KeyError(f"no enumeration {name!r}") from None


def all_enums(language: Optional[str] = None) -> list[EnumSpec]:
    lang = _language(language)
    return [e for e in _ENUMS.values() if lang is None or e.language == lang]


def supertypes_closure(name: str) -> list[str]:
    """All supertypes of ``name``, breadth first in declaration order, without ``name``."""
    key = metaclass(name).name
    if key not in _CLOSURES:
        out: list[str] = []
        queue = list(_METACLASSES[key].supertypes)
        while queue:
            n = queue.pop(0)
            if n not in out:
                out.append(n)
                queue.extend(_METACLASSES[n].supertypes)
        _CLOSURES[key] = tuple(out)
    return list(_CLOSURES[key])


def properties(name: str, inherited: bool = True,
               derived: Optional[bool] = None) -> list[PropertySpec]:
    """Properties of a metaclass: owned ones first, then each supertype's (closure order).

    With ``inherited``, a property redefined anywhere in the metaclass or its
    supertypes is replaced by the redefining one (KerML: redefined features are
    not inherited). ``derived`` True / False keeps only derived / non-derived ones.
    """
    meta = metaclass(name)
    if inherited:
        chain = [meta.name] + supertypes_closure(meta.name)
        candidates = [p for n in chain for p in _METACLASSES[n].properties]
        hidden = {r for p in candidates for r in p.redefines}
        props = [p for p in candidates if p.qualified_name not in hidden]
    else:
        props = list(meta.properties)
    if derived is not None:
        props = [p for p in props if p.derived == derived]
    return props


# --- Python names (ADR 0002, decision 2) --------------------------------------

#: The exceptions to the naming rule, by spec name or by "Metaclass::name"
#: (which wins). Everything else is snake_case, pluralized when multi-valued.
PYTHON_NAME_OVERRIDES: dict[str, str] = {
    # already plural
    "aliasIds": "alias_ids",
    # mass nouns: the plural is the singular
    "documentation": "documentation",
    "ownedMetadata": "owned_metadata",
    "nestedMetadata": "nested_metadata",
    # `kind` is every element class's metaclass discriminator, so the spec's
    # `kind` properties are named after their enumeration type
    "RequirementConstraintMembership::kind": "requirement_constraint_kind",
    "FramedConcernMembership::kind": "requirement_constraint_kind",
    "RequirementVerificationMembership::kind": "requirement_constraint_kind",
    "StateSubactionMembership::kind": "state_subaction_kind",
    "TransitionFeatureMembership::kind": "transition_feature_kind",
    "TriggerInvocationExpression::kind": "trigger_kind",
}

#: Python attributes of element classes that no spec property may take.
RESERVED_PYTHON_NAMES = frozenset({"kind", "spec_metaclass", "tool_data"})


def _snake(name: str) -> str:
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", name)     # ABCDef -> ABC_Def
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _plural(word: str) -> str:
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + "s"


def python_name(prop_or_name: Union[PropertySpec, str],
                multi_valued: Optional[bool] = None) -> str:
    """The Python attribute name of a spec property.

    ``prop_or_name`` is a ``PropertySpec`` (its multiplicity decides unless
    ``multi_valued`` is given), a spec name or a ``"Metaclass::name"``. A plain
    name is single-valued unless ``multi_valued``. ``isX`` booleans are never
    pluralized. Raises ValueError for a name reserved by the element classes
    (``kind`` without its metaclass).
    """
    if isinstance(prop_or_name, PropertySpec):
        qualified, name = prop_or_name.qualified_name, prop_or_name.name
        if multi_valued is None:
            multi_valued = prop_or_name.multi_valued
    else:
        qualified = prop_or_name if "::" in prop_or_name else None
        name = _simple(prop_or_name)
    if qualified is not None and qualified in PYTHON_NAME_OVERRIDES:
        return PYTHON_NAME_OVERRIDES[qualified]
    if name in PYTHON_NAME_OVERRIDES:
        return PYTHON_NAME_OVERRIDES[name]
    snake = _snake(name)
    if snake in RESERVED_PYTHON_NAMES:
        raise ValueError(f"{prop_or_name!r}: {snake!r} is reserved for element classes; "
                         f"add a 'Metaclass::{name}' entry to PYTHON_NAME_OVERRIDES")
    if multi_valued and not snake.startswith("is_"):
        head, _, last = snake.rpartition("_")
        snake = (head + "_" if head else "") + _plural(last)
    return snake


# --- Python classes -----------------------------------------------------------

#: Packages imported (recursively) by ``python_classes()``: the core and the
#: application's feature modules (``engine.requirements``, ``engine.interfaces``,
#: ``engine.allocation``, ``engine.avionics.safety``, ...).
DISCOVERY_PACKAGES: tuple[str, ...] = ("kerml", "sysmlv2", "engine")

_DISCOVERED: Optional[list[type]] = None
_DISCOVERY_ERRORS: dict[str, str] = {}


def spec_metaclass_of(py_class: type) -> Optional[str]:
    """The spec metaclass a Python element class is interchanged as, or None.

    A ``spec_metaclass`` class attribute wins, if set by the class or by an
    ancestor that shares its ``kind`` (a subclass that declares a new ``kind``
    must declare its own mapping); otherwise ``kind`` when it names a metaclass.
    SysML names are known once ``sysmlv2.metamodel`` is imported.
    """
    for cls in py_class.__mro__:
        declared = vars(cls).get("spec_metaclass")
        if declared:
            return metaclass(declared).name if is_metaclass(declared) else None
        if "kind" in vars(cls):
            break
    kind = getattr(py_class, "kind", None)
    return _simple(kind) if is_metaclass(kind) else None


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:200]


def _import_all(package: str) -> None:
    try:
        pkg = importlib.import_module(package)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - report, never crash the registry
        _DISCOVERY_ERRORS[package] = _error(exc)
        return

    def onerror(name: str) -> None:
        _DISCOVERY_ERRORS[name] = _error(sys.exc_info()[1] or ImportError(name))

    for info in pkgutil.walk_packages(getattr(pkg, "__path__", []), package + ".", onerror):
        if info.name.rsplit(".", 1)[-1] == "__main__" or info.name in sys.modules:
            continue
        try:
            importlib.import_module(info.name)
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            _DISCOVERY_ERRORS[info.name] = _error(exc)


def python_classes(refresh: bool = False) -> list[type]:
    """Every Element subclass defined in ``DISCOVERY_PACKAGES``, sorted by module and name.

    Imports those packages and all their modules first (once per process, or
    again with ``refresh``). Modules that fail to import are skipped and listed
    by ``discovery_errors()``. Classes defined elsewhere (tests, scripts) are
    left out so the result does not depend on what else was imported.
    """
    global _DISCOVERED
    if _DISCOVERED is None or refresh:
        _DISCOVERY_ERRORS.clear()
        for package in DISCOVERY_PACKAGES:
            _import_all(package)
        element = importlib.import_module("kerml").Element
        prefixes = tuple(p + "." for p in DISCOVERY_PACKAGES)
        seen: set[type] = set()
        stack = [element]
        while stack:
            cls = stack.pop()
            if cls in seen:
                continue
            seen.add(cls)
            stack.extend(cls.__subclasses__())
        _DISCOVERED = sorted((c for c in seen
                              if c.__module__ in DISCOVERY_PACKAGES
                              or c.__module__.startswith(prefixes)),
                             key=lambda c: (c.__module__, c.__qualname__))
    return list(_DISCOVERED)


def discovery_errors() -> dict[str, str]:
    """Module -> error for the modules ``python_classes()`` could not import."""
    return dict(_DISCOVERY_ERRORS)


register(_metamodel_kerml)

__all__ = [
    "PropertySpec", "MetaclassSpec", "EnumSpec", "register", "languages",
    "is_metaclass", "metaclass", "all_metaclasses", "enum", "all_enums",
    "supertypes_closure", "properties", "PYTHON_NAME_OVERRIDES", "RESERVED_PYTHON_NAMES",
    "python_name", "DISCOVERY_PACKAGES", "spec_metaclass_of", "python_classes",
    "discovery_errors",
]
