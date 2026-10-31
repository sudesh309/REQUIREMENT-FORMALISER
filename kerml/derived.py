"""Derived properties installed from the metamodel registry (ADR 0002 decision 2).

Many derived properties of the abstract syntax are mechanical: a property
that subsets a collection and has a narrower type is "the elements of that
collection of the narrower type" (``Definition::ownedPart`` is
``ownedUsage->selectByKind(PartUsage)``), and a property that redefines
another with a narrower type is that property's value seen through the
narrower type (``Expression::function`` redefines ``Step::behavior``).
:func:`install` adds such properties to the element classes when a package is
imported (``kerml`` for the KerML metaclasses, ``sysmlv2`` for the SysML
ones), so they need not be written by hand in every class.

Rules
-----
For each owned derived property ``P`` of a metaclass ``M``, with ``C`` the
Python class that declares ``kind = M`` (see :func:`class_for`), in order:

1. **Hand-written code wins.** Nothing is installed when ``C`` or one of its
   ancestors already defines ``python_name(P)`` (a property, attribute or
   method), or when ``P`` is listed in the ``not_generated`` table.
2. **Explicit derivations.** ``P`` has an entry in the ``explicit`` table: a
   function written from the derivation in the specification (navigation
   through owned memberships of a kind, such as
   ``RequirementUsage::subjectParameter``). Explicit entries are installed
   first, so the rule below can build on them.
3. **Type filter.** The type ``T`` of ``P`` is a metaclass and ``P`` either
   subsets a property ``Q`` whose type is a *proper* supertype of ``T``, or
   redefines a property ``Q`` whose type is ``T`` or a supertype of it.
   Following such parents up to the first property that ``C`` implements by
   hand or by rule 2 (the *base*; a ``base_overrides`` entry names it instead
   where the specification filters another collection), the value of ``P`` is
   the value of the base filtered by ``isinstance(x, class_for(T))``: a list,
   or for a single-valued ``P`` the first match (or None).
   ``Definition::ownedPart`` subsets ``ownedItem``, which subsets
   ``ownedOccurrence``, then ``ownedUsage``, then ``Type::ownedFeature``: so
   ``owned_parts`` is ``owned_features`` filtered by ``PartUsage``. Filtering
   the base by the narrowest type gives the same elements as the
   specification's chain of ``selectByKind`` when the Python classes follow the
   spec generalizations, and it keeps working while an intermediate metaclass
   has no Python class yet.
4. Every other derived property is left to hand-written code
   (:func:`report` lists them).

The class of ``T`` is looked up when the property is read, so a metaclass
whose class is defined later (or not at all, which makes the filter empty)
needs no re-installation.

Installed properties are :class:`DerivedProperty` descriptors. They are
read-only in the sense of the conventions in :mod:`kerml.elements` (nothing
in the model changes when one is assigned), but they are *non-data*
descriptors: an instance attribute of the same name, such as a compatibility
attribute assigned in ``__init__`` (``Invocation.function``), takes precedence
for that instance, so installing never breaks an existing class.
:func:`shadowed` lists those cases.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from . import metamodel as mm
from .elements import Element

#: Packages whose classes provide the Python class of a metaclass.
CORE_PACKAGES: tuple[str, ...] = ("kerml", "sysmlv2")


# ---------------------------------------------------------------------------
# Python class of a metaclass
# ---------------------------------------------------------------------------

_CLASSES: dict[str, type] = {}
_SCANNED_AT = [-1]


def _in_core(cls: type) -> bool:
    mod = cls.__module__
    return any(mod == p or mod.startswith(p + ".") for p in CORE_PACKAGES)


def _scan() -> None:
    found: dict[str, list[type]] = {}
    seen: set[type] = set()
    stack = [Element]
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        stack.extend(c.__subclasses__())
        kind = vars(c).get("kind")
        if isinstance(kind, str) and _in_core(c) and mm.is_metaclass(kind):
            found.setdefault(kind, []).append(c)
    for kind, classes in found.items():
        # The most general class declaring the kind (a private helper subclass that
        # repeats the kind, like the transient root membership, is not chosen).
        general = [c for c in classes if not any(o is not c and issubclass(c, o) for o in classes)]
        general.sort(key=lambda c: (c.__module__, c.__qualname__))
        _CLASSES[kind] = general[0]


def class_for(metaclass: str) -> Optional[type]:
    """The Python class of a spec metaclass: the class in ``kerml`` / ``sysmlv2`` declaring it
    as its ``kind`` (the most general one when several do), or None."""
    cls = _CLASSES.get(metaclass)
    if cls is None and _SCANNED_AT[0] != len(sys.modules):
        _SCANNED_AT[0] = len(sys.modules)
        _scan()
        cls = _CLASSES.get(metaclass)
    return cls


def is_kind(element: object, metaclass: str) -> bool:
    """``element.oclIsKindOf(metaclass)``, through the Python class of the metaclass."""
    cls = class_for(metaclass)
    return cls is not None and isinstance(element, cls)


def select_by_kind(elements: Iterable, metaclass: str) -> list:
    """``elements->selectByKind(metaclass)``."""
    cls = class_for(metaclass)
    return [] if cls is None else [x for x in elements if isinstance(x, cls)]


def enum_value(value: object) -> object:
    """The literal of an enumeration value (a ``str`` Enum member or a plain string)."""
    return getattr(value, "value", value)


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

class DerivedProperty:
    """A derived property installed by :func:`install` (a non-data descriptor).

    ``spec`` is the property's ``Metaclass::name`` and ``rule`` how it is
    computed: ``"explicit"`` or ``"filter"`` (then ``base`` is the Python name
    of the filtered property and ``type`` the metaclass filtered by).
    """

    def __init__(self, fget: Callable, spec: str, rule: str, *, base: Optional[str] = None,
                 type: Optional[str] = None, doc: Optional[str] = None):
        self.fget = fget
        self.spec = spec
        self.rule = rule
        self.base = base
        self.type = type
        self.name = None
        self.__doc__ = doc or f"Spec ``{spec}`` (derived, installed by kerml.derived: {rule})."

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self.fget(instance)

    def __repr__(self) -> str:
        how = f"{self.base} filtered by {self.type}" if self.rule == "filter" else self.rule
        return f"<DerivedProperty {self.spec} ({how})>"


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Installed:
    """One installed property (``rule`` is "explicit" or "filter")."""

    cls: type
    name: str
    spec: str
    rule: str
    base: Optional[str] = None
    type: Optional[str] = None


_INSTALLED: list[Installed] = []
_SKIPPED: dict[str, str] = {}
_MISSING = object()


def _defined(cls: type, name: str, *, transparent_filters: bool = False) -> object:
    """What ``cls`` (or an ancestor) defines under ``name``, or ``_MISSING``.

    With ``transparent_filters`` an installed type filter does not count (the
    filter rule always filters the hand-written base).
    """
    for c in cls.__mro__:
        if name in vars(c):
            value = vars(c)[name]
            if transparent_filters and isinstance(value, DerivedProperty) and value.rule == "filter":
                return _MISSING
            return value
    return _MISSING


def _is_base(value: object) -> bool:
    """Can a defined attribute serve as the base of a filter (a property, not a method)?"""
    return isinstance(value, (property, DerivedProperty))


def _conforms(sub: str, sup: str, *, proper: bool) -> bool:
    if not (mm.is_metaclass(sub) and mm.is_metaclass(sup)):
        return False
    if sub == sup:
        return not proper
    return sup in mm.supertypes_closure(sub)


def _prop(qualified: str) -> Optional[mm.PropertySpec]:
    owner, _, name = qualified.rpartition("::")
    try:
        return mm.metaclass(owner).property(name)
    except KeyError:
        return None


def _filter_parents(p: mm.PropertySpec) -> list[mm.PropertySpec]:
    out = []
    for qn in p.redefines:
        q = _prop(qn)
        if q is not None and _conforms(p.type, q.type, proper=False):
            out.append(q)
    for qn in p.subsets:
        q = _prop(qn)
        if q is not None and _conforms(p.type, q.type, proper=True):
            out.append(q)
    return out


def filter_base(p: mm.PropertySpec, cls: type, base_overrides: Optional[dict] = None,
                _seen: Optional[set] = None) -> Optional[str]:
    """The Python name of the base that the type filter for `p` on `cls` filters, or None."""
    overrides = base_overrides or {}
    if p.qualified_name in overrides:
        return overrides[p.qualified_name]
    seen = _seen if _seen is not None else set()
    if p.qualified_name in seen:
        return None
    seen.add(p.qualified_name)
    for q in _filter_parents(p):
        name = mm.python_name(q)
        if _is_base(_defined(cls, name, transparent_filters=True)):
            return name
        base = filter_base(q, cls, overrides, seen)
        if base is not None:
            return base
    return None


def _make_filter(base: str, metaclass: str, single: bool) -> Callable:
    def fget(self):
        value = getattr(self, base)
        cls = class_for(metaclass)
        if isinstance(value, (list, tuple)):
            if cls is None:
                return None if single else []
            items = [x for x in value if isinstance(x, cls)]
            if single:
                return items[0] if items else None
            return items
        if cls is None or not isinstance(value, cls):
            return None if single else []
        return value if single else [value]
    return fget


def _set(cls: type, name: str, prop: DerivedProperty) -> None:
    setattr(cls, name, prop)
    prop.name = name


def install(language: str, explicit: Optional[dict[str, Callable]] = None,
            not_generated: Iterable[str] = (), base_overrides: Optional[dict[str, str]] = None
            ) -> list[Installed]:
    """Install the derived properties of `language`'s metaclasses (idempotent; see the module doc).

    `explicit` maps ``"Metaclass::property"`` to a function of the element;
    `not_generated` lists properties the type filter must not generate;
    `base_overrides` maps a property to the Python name of the base to filter.
    Returns what was installed by this call.
    """
    explicit = explicit or {}
    skip = set(not_generated)
    done: list[Installed] = []
    metas = mm.all_metaclasses(language)
    # Rule 2 first, so that type filters can use explicit derivations as their base.
    for m in metas:
        cls = class_for(m.name)
        for p in m.properties:
            if not p.derived or p.qualified_name not in explicit:
                continue
            if cls is None:
                _SKIPPED[p.qualified_name] = "no class"
                continue
            name = mm.python_name(p)
            if _defined(cls, name) is not _MISSING:
                continue
            fn = explicit[p.qualified_name]
            _set(cls, name, DerivedProperty(fn, p.qualified_name, "explicit",
                                            doc=fn.__doc__ or None))
            done.append(Installed(cls, name, p.qualified_name, "explicit"))
    for m in metas:
        cls = class_for(m.name)
        for p in m.properties:
            if not p.derived or p.qualified_name in explicit:
                continue
            name = mm.python_name(p)
            if cls is None:
                _SKIPPED[p.qualified_name] = "no class"
                continue
            if _defined(cls, name) is not _MISSING:
                continue
            if p.qualified_name in skip:
                _SKIPPED[p.qualified_name] = "not generated"
                continue
            base = filter_base(p, cls, base_overrides) if mm.is_metaclass(p.type) else None
            if base is None:
                _SKIPPED[p.qualified_name] = "no rule"
                continue
            single = p.upper == 1
            doc = (f"Spec ``{p.qualified_name}``: ``{base}`` that are ``{p.type}``"
                   + (" (the first, or None)." if single else ".")
                   + " Installed by kerml.derived (type filter).")
            _set(cls, name, DerivedProperty(_make_filter(base, p.type, single), p.qualified_name,
                                            "filter", base=base, type=p.type, doc=doc))
            done.append(Installed(cls, name, p.qualified_name, "filter", base, p.type))
    for item in done:
        _SKIPPED.pop(item.spec, None)
    _INSTALLED.extend(done)
    return done


def installed(language: Optional[str] = None) -> list[Installed]:
    """Everything installed so far (for one language)."""
    if language is None:
        return list(_INSTALLED)
    lang = language.lower()
    return [i for i in _INSTALLED if mm.metaclass(i.spec.split("::")[0]).language.lower() == lang]


def report() -> dict[str, str]:
    """``Metaclass::property`` -> why no property was installed (no class, no rule, not generated)."""
    out = {}
    for spec, why in _SKIPPED.items():
        owner, _, _name = spec.rpartition("::")
        cls = class_for(owner)
        p = _prop(spec)
        if cls is not None and p is not None and _defined(cls, mm.python_name(p)) is not _MISSING:
            continue
        out[spec] = why
    return dict(sorted(out.items()))


def shadowed(classes: Optional[Iterable[type]] = None) -> list[tuple[type, str]]:
    """``(class, name)`` where an instance attribute hides an installed property.

    Each class is built with no arguments; `classes` defaults to every element
    class of the discovery packages (``kerml.metamodel.python_classes()``).
    """
    out = []
    for cls in (classes if classes is not None else mm.python_classes()):
        try:
            inst = cls()
        except Exception:  # noqa: BLE001 - classes that need arguments are not checked
            continue
        for name, value in vars(inst).items():
            d = _defined(cls, name)
            if isinstance(d, DerivedProperty):
                out.append((cls, name))
    return out


# ---------------------------------------------------------------------------
# KerML
# ---------------------------------------------------------------------------

def _association_related_types(self) -> list:
    """Spec ``Association::relatedType``: the types of the association ends (``associationEnd.type``)."""
    return [t for end in self.association_ends for t in end.types]


def _association_source_type(self):
    """Spec ``Association::sourceType``: the first related type, if any."""
    related = self.related_types
    return related[0] if related else None


def _association_target_types(self) -> list:
    """Spec ``Association::targetType``: the related types after the first."""
    related = self.related_types
    out = []
    for t in related[1:]:
        if not any(t is x for x in out):
            out.append(t)
    return out


def _expression_result(self):
    """Spec ``Expression::result``: the parameter owned (possibly by a supertype) through a
    ReturnParameterMembership."""
    from .operator_expressions import result_parameter
    return result_parameter(self)


#: Explicit derivations of KerML derived properties (rule 2).
KERML_EXPLICIT: dict[str, Callable] = {
    "Association::relatedType": _association_related_types,
    "Association::sourceType": _association_source_type,
    "Association::targetType": _association_target_types,
    "Expression::result": _expression_result,
}

#: KerML derived properties the type filter must not generate.
KERML_NOT_GENERATED: tuple[str, ...] = ()


def install_kerml() -> list[Installed]:
    return install("KerML", KERML_EXPLICIT, KERML_NOT_GENERATED)


install_kerml()

__all__ = [
    "CORE_PACKAGES", "class_for", "is_kind", "select_by_kind", "enum_value", "DerivedProperty",
    "Installed", "install", "installed", "report", "shadowed", "filter_base",
    "KERML_EXPLICIT", "KERML_NOT_GENERATED",
]
