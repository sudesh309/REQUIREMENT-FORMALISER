"""User-defined Stereotypes and Profiles: the SysML v2 successor of UML profiles.

In SysML v2 customization is done through KerML *MetadataDefinitions*; we
expose the friendlier System Composer vocabulary on top of it:

- a :class:`Profile` (a Package) owns :class:`Stereotype` elements and has a
  description and a version; stereotypes are addressed as ``Profile.Stereotype``;
- a Stereotype declares typed *properties* (:class:`StereotypeTag`): ``double``,
  ``single``, ``int8`` .. ``uint64``, ``boolean``, ``string`` or ``enumeration``
  with a unit, a default, a min/max range and a description; it may inherit
  from a *base* stereotype, be *abstract*, carry a display *style* and say which
  element *category* it applies to (Component, Port, Connector, Interface, ...);
- *applying* a stereotype to an element attaches a :class:`StereotypeApplication`
  whose values are checked and coerced on assignment (``'2.5 lb'`` into a kg
  property is converted, ``'2*0.75'`` is evaluated, out-of-range values and
  unknown enumeration literals are rejected with a clear message).

- stereotype values are *inherited* by usages from the definition they are typed
  by: a reference component (a ``PartUsage`` typed by a ``PartDefinition``) reads
  the values of the stereotypes applied to its definition unless it overrides
  them with an application of its own (:func:`inheritance_source`,
  :func:`effective_applications`, :meth:`StereotypeApplication.get`);

The pre-profile API keeps working: ``Stereotype(name, applies_to=[cls])``,
``define_tag(name, tag_type, default)`` (an untyped property that accepts any
value), ``apply(target, values)`` and :func:`stereotypes_on`.

Repository-level operations (profile CRUD with change propagation, import /
export, batch application, default stereotypes, persistence of the extra
attributes and validation) live in :mod:`engine.profiles`.
"""
from __future__ import annotations

import math
import re
import sys
from typing import Any, Iterable, Optional

from .elements import AnnotatingElement, Element
from .features import Feature, MultiplicityRange
from .namespaces import Namespace, Package
from .types import Type

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

PROPERTY_TYPES: tuple[str, ...] = (
    "double", "single", "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64", "boolean", "string", "enumeration",
)
INT_RANGES: dict[str, tuple[int, int]] = {
    "int8": (-2 ** 7, 2 ** 7 - 1), "int16": (-2 ** 15, 2 ** 15 - 1),
    "int32": (-2 ** 31, 2 ** 31 - 1), "int64": (-2 ** 63, 2 ** 63 - 1),
    "uint8": (0, 2 ** 8 - 1), "uint16": (0, 2 ** 16 - 1),
    "uint32": (0, 2 ** 32 - 1), "uint64": (0, 2 ** 64 - 1),
}
NUMERIC_TYPES = frozenset({"double", "single", *INT_RANGES})
_SINGLE_MAX = 3.4028234663852886e38

# Element categories a stereotype can be restricted to ('' = any element).
CATEGORIES: tuple[str, ...] = (
    "", "Component", "Port", "Connector", "Interface", "InterfaceElement",
    "Requirement", "Allocation", "AllocationSet", "Function", "Architecture",
)
# Small fixed icon set for stereotype styling (rendered by the web UI).
ICONS: tuple[str, ...] = (
    "", "component", "sensor", "actuator", "computer", "display", "network",
    "power", "antenna", "software", "storage", "controller",
)
LINE_STYLES: tuple[str, ...] = ("", "solid", "dashed", "dotted", "dashdot")
# Line style -> SVG stroke-dasharray, the ``dash`` key of the summary style contract.
DASH_PATTERNS: dict[str, str] = {"dashed": "6 4", "dotted": "2 3", "dashdot": "8 3 2 3"}
STYLE_KEYS: tuple[str, ...] = ("fill", "stroke", "text", "icon", "line")
DEFAULT_SLOTS: tuple[str, ...] = ("component", "port", "connector")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_TRUE = {"true", "1", "yes", "on", "y", "t"}
_FALSE = {"false", "0", "no", "off", "n", "f"}


class StereotypeError(TypeError, ValueError):
    """Invalid stereotype definition, application or property value.

    Subclasses both TypeError (what ``apply`` historically raised for a
    stereotype that does not fit the target) and ValueError (what the property
    APIs raise), so existing ``except`` clauses keep working.
    """

    status = 400


class UnknownPropertyError(StereotypeError, KeyError):
    """A value was given for a property the stereotype does not declare."""

    def __str__(self) -> str:  # KeyError would quote the message
        return str(self.args[0]) if self.args else ""


def check_name(name: Any, what: str = "name") -> str:
    """Names must be identifiers so ``Profile.Stereotype.property`` stays unambiguous."""
    if not isinstance(name, str) or not _NAME_RE.match(name.strip()):
        raise StereotypeError(
            f"{what} {name!r} is not valid: use letters, digits and '_' and start with a letter")
    return name.strip()


def check_color(value: Any, what: str = "colour") -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _COLOR_RE.match(value.strip()):
        raise StereotypeError(f"{what} {value!r} must be a hex colour such as #1f77b4")
    return value.strip().lower()


def normalize_style(style: Optional[dict]) -> dict:
    """Validate a stereotype style dict; empty entries are dropped."""
    out: dict[str, str] = {}
    for key, value in (style or {}).items():
        if key not in STYLE_KEYS:
            raise StereotypeError(f"unknown style key {key!r}; use {list(STYLE_KEYS)}")
        if key in ("fill", "stroke", "text"):
            value = check_color(value, f"{key} colour")
        elif key == "icon":
            if value not in ICONS:
                raise StereotypeError(f"icon {value!r} is not one of {[i for i in ICONS if i]}")
        elif key == "line":
            if value not in LINE_STYLES:
                raise StereotypeError(f"line style {value!r} is not one of {[s for s in LINE_STYLES if s]}")
        if value:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Element categories (matched by kind names so features built later fit in)
# ---------------------------------------------------------------------------

_KIND_CACHE: dict[type, frozenset[str]] = {}
_ALLOCATION_CONTAINERS = ("AllocationSet", "AllocationScenario")


def kind_names(e: Any) -> frozenset[str]:
    """Kind strings and class names along an element's class hierarchy."""
    cls = type(e)
    hit = _KIND_CACHE.get(cls)
    if hit is None:
        names: set[str] = set()
        for c in cls.__mro__:
            names.add(c.__name__)
            if "kind" in c.__dict__ and isinstance(c.__dict__["kind"], str):
                names.add(c.__dict__["kind"])
        hit = _KIND_CACHE[cls] = frozenset(names)
    return hit | {getattr(e, "kind", "")}


# In the spec connections and views are part usages / definitions; for the application's
# categories (Component, Architecture) and value inheritance they are not components.
_NOT_COMPONENT_KINDS = frozenset({"ConnectorAsUsage", "ViewUsage", "ConnectionDefinition",
                                  "ViewDefinition"})


def is_component_usage_kind(k: frozenset) -> bool:
    """Kind names (:func:`kind_names`) of a component: a part usage, not a connection or view."""
    return "PartUsage" in k and not (k & _NOT_COMPONENT_KINDS)


def is_component_definition_kind(k: frozenset) -> bool:
    return "PartDefinition" in k and not (k & _NOT_COMPONENT_KINDS)


def _is_interface(e: Any) -> bool:
    if e is None:
        return False
    kind = getattr(e, "kind", "")
    return ("Interface" in kind and not kind.endswith("Dictionary")) or "PortDefinition" in kind_names(e)


def matches_category(e: Any, category: str) -> bool:
    """Does element ``e`` belong to a stereotype category (see :data:`CATEGORIES`)?"""
    if not category:
        return True
    k = kind_names(e)
    kind = getattr(e, "kind", "")
    if category == "Component":
        return is_component_usage_kind(k) or is_component_definition_kind(k)
    if category == "Port":
        return "PortUsage" in k
    if category == "Connector":
        return "ConnectionUsage" in k and "AllocationUsage" not in k
    if category == "Interface":
        return _is_interface(e)
    if category == "InterfaceElement":
        return bool(k & {"DataElement", "PhysicalElement", "FunctionElement"}) or (
            "AttributeUsage" in k and _is_interface(getattr(e, "owner", None)))
    if category == "Requirement":
        return bool(k & {"RequirementDefinition", "RequirementUsage"})
    if category == "Allocation":
        # Allocations only (an allocation object, an AllocationUsage / AllocationDefinition):
        # the sets and scenarios that group them have their own category / none.
        return any(x.startswith("Allocation") and not x.startswith(_ALLOCATION_CONTAINERS) for x in k)
    if category == "AllocationSet":
        return any(x.startswith("AllocationSet") for x in k)
    if category == "Function":
        if "Function" in kind and "Element" not in kind:
            return True
        return bool(k & {"ActionDefinition", "ActionUsage"}) and not (
            k & {"CalculationDefinition", "CalculationUsage", "StateDefinition",
                 "StateUsage", "TransitionUsage"})
    if category == "Architecture":
        owner = getattr(e, "owner", None)
        return is_component_definition_kind(k) and (
            owner is None or not (is_component_usage_kind(kind_names(owner))
                                  or is_component_definition_kind(kind_names(owner))))
    return False


def categories_of(e: Any) -> list[str]:
    return [c for c in CATEGORIES if c and matches_category(e, c)]


# ---------------------------------------------------------------------------
# Typed property values
# ---------------------------------------------------------------------------

def _units():
    # engine.units is a leaf module; imported lazily so kerml keeps no import-time
    # dependency on the engine package.
    from engine import units
    return units


def format_value(value: Any, unit: str = "") -> str:
    """Human form of a stored property value, e.g. ``'1.36077711 kg'``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        text = _units().format_number(value)
        return f"{text} {unit}" if unit else text
    return str(value)


def format_short(value: Any, unit: str = "") -> str:
    """Rounded human form for compact displays (``4.5359237 kg`` -> ``'4.54 kg'``); the
    stored value keeps its full precision. Same as :func:`format_value` for anything but
    non-integer numbers (see ``engine.units.format_short``)."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return format_value(value, unit)
    text = _units().format_short(value)
    return f"{text} {unit}" if unit else text


class StereotypeTag(Feature):
    """A (typed) property declared by a Stereotype.

    ``prop_type`` is one of :data:`PROPERTY_TYPES`, or ``''`` for the untyped
    tags created by the legacy :meth:`Stereotype.define_tag` (any value goes).
    Numeric values are stored in ``unit``; ``minimum`` / ``maximum`` bound them.
    """

    kind = "StereotypeTag"

    def __init__(self, name: Optional[str] = None, tag_type: Optional[Type] = None,
                 default: Any = None, *, prop_type: str = "", unit: str = "",
                 minimum: Optional[float] = None, maximum: Optional[float] = None,
                 literals: Optional[Iterable[str]] = None, description: str = "",
                 **kwargs):
        super().__init__(name=name, typed_by=tag_type,
                         multiplicity=MultiplicityRange(0, 1), **kwargs)
        self.default_value = default
        self.prop_type: str = prop_type or ""
        self.unit: str = unit or ""
        self.minimum: Optional[float] = minimum
        self.maximum: Optional[float] = maximum
        self.literals: list[str] = list(literals or [])
        self.description: str = description or ""

    # --- metadata ----------------------------------------------------------
    @property
    def stereotype(self) -> Optional["Stereotype"]:
        return self.owner if isinstance(self.owner, Stereotype) else None

    @property
    def path(self) -> str:
        """``Profile.Stereotype.property`` address of this property."""
        st = self.stereotype
        return f"{st.full_name}.{self.name}" if st else str(self.name)

    @property
    def is_numeric(self) -> bool:
        return self.prop_type in NUMERIC_TYPES

    def type_label(self) -> str:
        return self.prop_type or "any"

    # --- coercion ----------------------------------------------------------
    def parse_number(self, value: Any, label: Optional[str] = None) -> Optional[float]:
        """A number in this property's unit from a number or text such as ``'2.5 lb'``."""
        label = label or self.path
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, bool):
            raise StereotypeError(f"{label} expects a number, not {str(value).lower()}")
        units = _units()
        if isinstance(value, (int, float)):
            num, unit = value, None
        elif isinstance(value, str):
            try:
                num, unit = units.parse_quantity(value)
            except units.UnitError as ex:
                raise StereotypeError(f"{label}: {ex}") from None
        else:
            raise StereotypeError(f"{label} expects a number, got {type(value).__name__}")
        if unit and unit != "1":
            if not self.unit:
                raise StereotypeError(
                    f"{label} has no unit; enter a plain number instead of {value!r}")
            try:
                num = units.convert(num, unit, self.unit)
            except units.UnitError as ex:
                raise StereotypeError(f"{label}: {ex}") from None
        if not math.isfinite(num):
            raise StereotypeError(f"{label} must be a finite number")
        if isinstance(value, str) and isinstance(num, float):
            num = float(f"{num:.15g}")      # drop conversion noise (1.3607771100000001)
        return num

    def coerce(self, value: Any, label: Optional[str] = None) -> Any:
        """Check ``value`` against this property's type and range; return the stored form.

        Raises :class:`StereotypeError` with a message naming the property.
        """
        t = self.prop_type
        label = label or self.path
        if not t:
            return value
        if t == "string":
            if value is None:
                return ""
            if isinstance(value, (dict, list, tuple, set)):
                raise StereotypeError(f"{label} expects text, got {type(value).__name__}")
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)
        if t == "boolean":
            if value is None or value == "":
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
                return value.strip().lower() in _TRUE
            raise StereotypeError(f"{label} expects true or false, got {value!r}")
        if t == "enumeration":
            if value is None or (isinstance(value, str) and not value.strip()):
                return None
            if isinstance(value, str):
                s = value.strip()
                if s in self.literals:
                    return s
                folded = [lit for lit in self.literals if lit.lower() == s.lower()]
                if len(folded) == 1:
                    return folded[0]
            raise StereotypeError(
                f"{label}: {value!r} is not one of the literals {self.literals}")
        if t not in NUMERIC_TYPES:
            raise StereotypeError(f"{label} has unknown type {t!r}")
        num = self.parse_number(value, label)
        if num is None:
            return None
        unit = f" {self.unit}" if self.unit else ""
        fmt = _units().format_number
        if t in INT_RANGES:
            r = round(num)
            if abs(num - r) > 1e-9 * max(1.0, abs(num)):
                raise StereotypeError(f"{label} must be a whole number ({t}), got {fmt(num)}{unit}")
            lo, hi = INT_RANGES[t]
            if not lo <= r <= hi:
                raise StereotypeError(f"{label} = {r} is outside the {t} range [{lo}, {hi}]")
            num = int(r)
        else:
            if t == "single" and abs(num) > _SINGLE_MAX:
                raise StereotypeError(f"{label} = {fmt(num)} is outside the single-precision range")
            num = float(num)
        tol = 1e-12 * max(1.0, abs(num))
        if self.minimum is not None and num < self.minimum - tol:
            raise StereotypeError(
                f"{label} = {fmt(num)}{unit} is below the minimum {fmt(self.minimum)}{unit}")
        if self.maximum is not None and num > self.maximum + tol:
            raise StereotypeError(
                f"{label} = {fmt(num)}{unit} is above the maximum {fmt(self.maximum)}{unit}")
        return num

    def type_default(self) -> Any:
        """Default used when a new typed property gets no explicit default."""
        if self.prop_type == "boolean":
            return False
        if self.prop_type == "string":
            return ""
        if self.prop_type == "enumeration":
            return self.literals[0] if self.literals else None
        return None

    def problems(self) -> list[str]:
        """Definition problems (for the validator): type, unit, range, literals, default."""
        out: list[str] = []
        t = self.prop_type
        if t and t not in PROPERTY_TYPES:
            out.append(f"unknown type {t!r}")
            return out
        if self.unit:
            if t and t not in NUMERIC_TYPES:
                out.append(f"unit {self.unit!r} on a {t} property")
            elif not _units().is_unit(self.unit):
                out.append(f"unknown unit {self.unit!r}")
        if t == "enumeration" and not self.literals:
            out.append("enumeration has no literals")
        if len(set(self.literals)) != len(self.literals):
            out.append("duplicate enumeration literals")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            out.append(f"minimum {self.minimum} is above maximum {self.maximum}")
        if t and self.default_value is not None:
            try:
                if self.coerce(self.default_value) != self.default_value:
                    out.append(f"default {self.default_value!r} is not in canonical form")
            except StereotypeError as ex:
                out.append(f"invalid default: {ex}")
        return out

    def describe(self) -> dict:
        return {
            "id": self.element_id, "name": self.name, "path": self.path,
            "type": self.type_label(), "unit": self.unit,
            "default": self.default_value,
            "default_display": format_value(self.default_value, self.unit),
            "min": self.minimum, "max": self.maximum, "literals": list(self.literals),
            "description": self.description,
            "owner": self.stereotype.full_name if self.stereotype else None,
            "index": self.stereotype.tags.index(self) if self.stereotype and self in self.stereotype.tags else None,
        }


# ---------------------------------------------------------------------------
# Stereotype
# ---------------------------------------------------------------------------

class Stereotype(Namespace):
    """A user-defined stereotype that can be applied to elements.

    Stereotypes are KerML metaobjects: each declaration adds a typed property
    namespace; each *application* records (stereotype, {property: value}) on an
    annotated element via a :class:`StereotypeApplication`.
    """

    kind = "Stereotype"

    def __init__(self, name: Optional[str] = None, *,
                 applies_to: Optional[list[type]] = None,
                 base: Optional["Stereotype"] = None,
                 category: str = "", description: str = "",
                 style: Optional[dict] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        # Which Element subclasses this stereotype may decorate; empty = any.
        self.applies_to: list[type] = list(applies_to or [])
        self.base: Optional[Stereotype] = base
        self.tags: list[StereotypeTag] = []
        if category not in CATEGORIES:
            raise StereotypeError(f"applies-to {category!r} is not one of {list(CATEGORIES)}")
        self.category: str = category
        self.description: str = description or ""
        self.style: dict = normalize_style(style)
        self.default_component_stereotype: Optional[Stereotype] = None
        self.default_port_stereotype: Optional[Stereotype] = None
        self.default_connector_stereotype: Optional[Stereotype] = None
        self.__dict__.setdefault("_applications", [])
        _ensure_engine_support()

    # --- abstractness (guarded: an applied stereotype cannot become abstract) ----
    @property
    def is_abstract(self) -> bool:  # type: ignore[override]
        return self.__dict__.get("_is_abstract", False)

    @is_abstract.setter
    def is_abstract(self, value: bool) -> None:
        value = bool(value)
        if value and not self.__dict__.get("_is_abstract", False):
            live = self.live_applications()
            if live:
                names = ", ".join(a.annotated_element.qualified_name for a in live[:3])
                raise StereotypeError(
                    f"«{self.full_name}» is applied to {len(live)} element(s) ({names}); "
                    f"remove those applications before making it abstract")
        self.__dict__["_is_abstract"] = value

    def live_applications(self) -> list["StereotypeApplication"]:
        apps = [a for a in self.__dict__.get("_applications", [])
                if a.annotated_element is not None
                and any(x is a for x in a.annotated_element.annotations)]
        self.__dict__["_applications"] = apps
        return list(apps)

    # --- naming ------------------------------------------------------------
    @property
    def profile(self) -> Optional["Profile"]:
        return self.owner if isinstance(self.owner, Profile) else None

    @property
    def full_name(self) -> str:
        """``Profile.Stereotype`` (just the name for a stereotype outside a profile)."""
        p = self.profile
        return f"{p.name}.{self.name}" if p is not None else str(self.name)

    # --- inheritance -------------------------------------------------------
    def ancestors(self) -> list["Stereotype"]:
        """``[self, base, base.base, ...]``; stops at a cycle."""
        out: list[Stereotype] = []
        node: Optional[Stereotype] = self
        while node is not None and not any(n is node for n in out):
            out.append(node)
            node = node.base
        return out

    def has_base_cycle(self) -> bool:
        node, seen = self.base, {id(self)}
        while node is not None:
            if id(node) in seen:
                return True
            seen.add(id(node))
            node = node.base
        return False

    def is_kind_of(self, other: "Stereotype") -> bool:
        return any(s is other for s in self.ancestors())

    # --- properties --------------------------------------------------------
    def define_tag(self, name: str, tag_type: Optional[Type] = None,
                   default: Any = None) -> StereotypeTag:
        """Legacy API: an untyped property (any value accepted)."""
        tag = StereotypeTag(name=name, tag_type=tag_type, default=default)
        self.own(tag)
        self.tags.append(tag)
        return tag

    def define_property(self, name: str, prop_type: str = "double", *, unit: str = "",
                        default: Any = None, minimum: Any = None, maximum: Any = None,
                        literals: Optional[Iterable[str]] = None, description: str = "",
                        index: Optional[int] = None) -> StereotypeTag:
        """Declare a typed property; every argument is checked before anything changes."""
        tag = build_property(name, prop_type, unit=unit, default=default, minimum=minimum,
                             maximum=maximum, literals=literals, description=description,
                             label=f"{self.full_name}.{name}")
        if any(t.name == tag.name for t in self.all_tags()):
            raise StereotypeError(f"«{self.full_name}» already has a property named {tag.name!r}")
        self.own(tag)
        if index is None or not 0 <= index <= len(self.tags):
            self.tags.append(tag)
        else:
            self.tags.insert(index, tag)
        return tag

    def all_tags(self) -> list[StereotypeTag]:
        """Own properties first, then inherited ones (nearest base first)."""
        out: list[StereotypeTag] = []
        seen: set[str] = set()
        for node in self.ancestors():
            for t in node.tags:
                if t.name and t.name not in seen:
                    out.append(t)
                    seen.add(t.name)
        return out

    def property_groups(self) -> list[tuple["Stereotype", list[StereotypeTag]]]:
        """Properties grouped by the stereotype that declares them, root base first."""
        seen: set[str] = set()
        groups = []
        for node in reversed(self.ancestors()):
            props = [t for t in node.tags if t.name and t.name not in seen]
            seen.update(t.name for t in props)
            groups.append((node, props))
        return groups

    def find_tag(self, name: str) -> Optional[StereotypeTag]:
        return next((t for t in self.all_tags() if t.name == name), None)

    # --- inherited settings -------------------------------------------------
    def effective_category(self) -> str:
        for node in self.ancestors():
            if node.category:
                return node.category
        return ""

    def effective_style(self) -> dict:
        style: dict = {}
        for node in reversed(self.ancestors()):
            style.update(node.style)
        return style

    def effective_default(self, slot: str) -> Optional["Stereotype"]:
        attr = f"default_{slot}_stereotype"
        for node in self.ancestors():
            d = getattr(node, attr, None)
            if d is not None:
                return d
        return None

    # --- application ---------------------------------------------------
    def can_apply_to(self, e: Element) -> bool:
        if self.applies_to and not any(isinstance(e, t) for t in self.applies_to):
            return False
        return matches_category(e, self.effective_category())

    def check_applicable(self, target: Element) -> None:
        """Raise StereotypeError unless this stereotype may be applied to ``target`` now."""
        if self.is_abstract:
            raise StereotypeError(f"«{self.full_name}» is abstract and cannot be applied")
        if not self.can_apply_to(target):
            cat = self.effective_category()
            what = f"applies to {cat} elements" if cat else \
                f"applies to {[c.__name__ for c in self.applies_to]}"
            raise StereotypeError(
                f"Stereotype {self.name!r} cannot be applied to {target.kind} "
                f"{target.qualified_name!r} (it {what})")
        if any(a.stereotype is self for a in stereotypes_on(target)):
            raise StereotypeError(f"«{self.full_name}» is already applied to {target.qualified_name!r}")

    def apply(self, target: Element, values: Optional[dict[str, Any]] = None
              ) -> "StereotypeApplication":
        """Apply to ``target`` with optional initial values (checked and coerced).

        When the project loader (``engine.serializer``) restores a saved
        application, nothing is refused: a saved file may hold state the
        editing APIs would reject (an out-of-range value, a duplicate or an
        abstract application written by hand or by an older version). Such
        state is kept as saved, so the project still opens and the validator
        reports it instead.
        """
        if _called_by_loader():
            return self.restore(target, values or {})
        self.check_applicable(target)
        app = StereotypeApplication(self, values or {})
        target.add_annotation(app)
        return app

    def restore(self, target: Element, values: dict[str, Any]) -> "StereotypeApplication":
        """Re-attach a saved application without checks (see :meth:`apply`).

        Values are coerced when possible and kept as saved otherwise; values
        of properties the stereotype no longer declares are dropped.
        """
        app = StereotypeApplication(self, {})
        declared = {t.name: t for t in self.all_tags()}
        for k, v in (values or {}).items():
            tag = declared.get(k)
            if tag is None:
                continue
            try:
                app.raw_slots()[tag] = tag.coerce(v)
            except (StereotypeError, ValueError, TypeError):
                app.raw_slots()[tag] = v
            # Files saved before values were inherited do not say which were set: a value that
            # differs from the default was (``engine.profiles`` restores the exact set otherwise).
            if app.raw_slots()[tag] != tag.default_value:
                app._explicit.add(tag)
        target.add_annotation(app)
        return app

    def describe(self) -> dict:
        p = self.profile
        return {
            "id": self.element_id, "name": self.name, "qualified_name": self.full_name,
            "profile": p.name if p else None, "profile_id": p.element_id if p else None,
            "description": self.description,
            "applies_to": self.category, "effective_applies_to": self.effective_category(),
            "legacy_applies_to": [c.__name__ for c in self.applies_to],
            "base": self.base.full_name if self.base else None,
            "base_id": self.base.element_id if self.base else None,
            "abstract": self.is_abstract,
            "style": dict(self.style), "effective_style": self.effective_style(),
            "defaults": {slot: (getattr(self, f"default_{slot}_stereotype").full_name
                                if getattr(self, f"default_{slot}_stereotype") else None)
                         for slot in DEFAULT_SLOTS},
            "properties": [t.describe() for t in self.tags],
            "groups": [{"stereotype": s.full_name, "id": s.element_id,
                        "properties": [t.describe() for t in props]}
                       for s, props in self.property_groups()],
        }


def build_property(name: str, prop_type: str = "double", *, unit: str = "", default: Any = None,
                   minimum: Any = None, maximum: Any = None,
                   literals: Optional[Iterable[str]] = None, description: str = "",
                   label: Optional[str] = None) -> StereotypeTag:
    """A detached, fully checked typed property (raises StereotypeError)."""
    name = check_name(name, "property name")
    label = label or name
    if prop_type not in PROPERTY_TYPES:
        raise StereotypeError(f"{label}: type {prop_type!r} is not one of {list(PROPERTY_TYPES)}")
    units = _units()
    if unit:
        if prop_type not in NUMERIC_TYPES:
            raise StereotypeError(f"{label}: only numeric properties have units ({prop_type} given)")
        try:
            unit = units.normalize_unit(unit)
        except units.UnitError as ex:
            raise StereotypeError(f"{label}: {ex}") from None
    lits = normalize_literals(literals) if prop_type == "enumeration" else []
    if prop_type == "enumeration" and not lits:
        raise StereotypeError(f"{label}: an enumeration needs at least one literal")
    tag = StereotypeTag(name=name, prop_type=prop_type, unit=unit or "",
                        literals=lits, description=description or "")
    if prop_type in NUMERIC_TYPES:
        tag.minimum = tag.parse_number(minimum, f"{label} minimum")
        tag.maximum = tag.parse_number(maximum, f"{label} maximum")
        if tag.minimum is not None and tag.maximum is not None and tag.minimum > tag.maximum:
            raise StereotypeError(f"{label}: minimum {tag.minimum} is above maximum {tag.maximum}")
    elif minimum not in (None, "") or maximum not in (None, ""):
        raise StereotypeError(f"{label}: only numeric properties have a minimum/maximum")
    tag.default_value = tag.coerce(default, f"{label} default") if default not in (None, "") \
        else tag.type_default()
    return tag


def normalize_literals(literals: Any) -> list[str]:
    if literals is None:
        return []
    if isinstance(literals, str):
        literals = literals.split(",")
    out: list[str] = []
    for lit in literals:
        s = str(lit).strip()
        if not s:
            continue
        if s in out:
            raise StereotypeError(f"duplicate enumeration literal {s!r}")
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class StereotypeApplication(AnnotatingElement):
    """One application of a Stereotype to an Element.

    ``values`` is a fresh dict ``{property name: value}`` covering every
    property of the stereotype (own and inherited); properties never set show
    their default. Values are keyed internally by the property *object*, so
    renaming a property never orphans a value and deleting one drops it.

    **Inheritance.** On a usage typed by a definition that carries the same
    stereotype, a value that was not set on the usage itself is read from the
    definition's application (``parent()``); the values set on the usage
    (``is_explicit``) override it, and :meth:`reset` goes back to inheriting.
    Without such a definition the explicit / default distinction changes nothing:
    a property reads its stored value or its default.
    """

    kind = "StereotypeApplication"
    spec_metaclass = "MetadataFeature"
    # Phase 1 keeps applications as extension annotations on the element (ADR 0002
    # decision 6); Phase 4 maps them to metadata usages.
    _extension = True
    inherited = False          # a real application, not the view of a definition's

    def __init__(self, stereotype: Stereotype, values: Optional[dict[str, Any]] = None, **kwargs):
        self.stereotype = stereotype
        super().__init__(**kwargs)
        self._slots: dict[StereotypeTag, Any] = {}
        self._explicit: set[StereotypeTag] = set()      # the properties set on this application
        declared = {t.name: t for t in stereotype.all_tags()}
        for k, v in (values or {}).items():
            tag = declared.get(k)
            if tag is None:
                raise UnknownPropertyError(
                    f"Stereotype {stereotype.name!r} has no tag {k!r}; known: {sorted(declared)}")
            self._slots[tag] = tag.coerce(v, f"{stereotype.full_name}.{k}")
            self._explicit.add(tag)
        # Fill in declared defaults so consumers don't have to.
        for tag in declared.values():
            self._slots.setdefault(tag, tag.default_value)
        stereotype.__dict__.setdefault("_applications", []).append(self)

    @property
    def body(self) -> str:  # type: ignore[override]
        st = self.__dict__.get("stereotype")
        return f"<<{st.name}>>" if st is not None else self.__dict__.get("_body", "")

    @body.setter
    def body(self, value: str) -> None:
        self.__dict__["_body"] = value

    # --- inheritance ---------------------------------------------------------
    def parent(self) -> Optional["StereotypeApplication"]:
        """The same stereotype's application on the definition this element inherits from."""
        if self.stereotype.profile is None:         # the legacy API (a plain package): no inheritance
            return None
        d = inheritance_source(self.annotated_element)
        return None if d is None else application_of(d, self.stereotype)

    def is_explicit(self, tag: "StereotypeTag") -> bool:
        """Was ``tag`` set on this application (as opposed to inherited or defaulted)?"""
        return tag in self._explicit

    def explicit_tags(self) -> list["StereotypeTag"]:
        """The properties set on this application, in declaration order."""
        return [t for t in self.stereotype.all_tags() if t in self._explicit]

    def origin(self, name: str) -> str:
        """Where a value comes from: ``'own'`` (set here), ``'inherited'`` (the definition's)
        or ``'default'``."""
        tag = self.tag(name)
        if tag in self._explicit:
            return "own"
        return "inherited" if self.parent() is not None else "default"

    def _read(self, tag: "StereotypeTag", parent: Optional["StereotypeApplication"]) -> Any:
        if tag not in self._explicit and parent is not None:
            return parent._read(tag, None)
        return self._slots[tag] if tag in self._slots else tag.default_value

    @property
    def values(self) -> dict[str, Any]:
        parent = self.parent()
        return {t.name: self._read(t, parent) for t in self.stereotype.all_tags()}

    @values.setter
    def values(self, new: dict[str, Any]) -> None:
        declared = {t.name: t for t in self.stereotype.all_tags()}
        slots = {}
        for k, v in (new or {}).items():
            tag = declared.get(k)
            if tag is None:
                raise UnknownPropertyError(f"«{self.stereotype.full_name}» has no property {k!r}")
            slots[tag] = tag.coerce(v, f"{self.stereotype.full_name}.{k}")
        self._slots = slots
        self._explicit = set(slots)

    def own_values(self) -> dict[str, Any]:
        """Only the values set on this application (what copying it should carry over)."""
        return {t.name: self._slots[t] for t in self.explicit_tags() if t in self._slots}

    def stored(self, name: str) -> Any:
        """The value stored on this application (its default when none was set), without what
        the definition would supply: ``get`` is what the element reads."""
        tag = self.tag(name)
        return self._slots[tag] if tag in self._slots else tag.default_value

    def tag(self, name: str) -> StereotypeTag:
        tag = self.stereotype.find_tag(name)
        if tag is None:
            raise UnknownPropertyError(
                f"«{self.stereotype.full_name}» has no property {name!r}; "
                f"known: {[t.name for t in self.stereotype.all_tags()]}")
        return tag

    def get(self, name: str) -> Any:
        return self._read(self.tag(name), self.parent())

    def set(self, name: str, value: Any) -> Any:
        """Check, coerce and store one value (an override when the definition has one);
        returns the stored form."""
        tag = self.tag(name)
        stored = tag.coerce(value, f"{self.stereotype.full_name}.{name}")
        self.assign(tag, stored)
        return stored

    def assign(self, tag: "StereotypeTag", stored: Any) -> None:
        """Store an already checked value as this application's own."""
        self._slots[tag] = stored
        self._explicit.add(tag)

    def reset(self, name: str) -> bool:
        """Forget the value set here: inherit the definition's again (the default when there
        is none). False when nothing was set."""
        tag = self.tag(name)
        had = tag in self._explicit
        self._explicit.discard(tag)
        self._slots[tag] = tag.default_value
        return had

    def forget(self, tag: "StereotypeTag") -> None:
        """The property was deleted: drop what was recorded for it."""
        self._slots.pop(tag, None)
        self._explicit.discard(tag)

    def restore_explicit(self, tags: Iterable["StereotypeTag"]) -> None:
        """Loader: which properties were set here; every other value goes back to its default."""
        declared = self.stereotype.all_tags()
        keep = {t for t in tags if t in declared}
        for t in declared:
            if t not in keep:
                self._slots[t] = t.default_value
        self._explicit = keep

    def raw_slots(self) -> dict[StereotypeTag, Any]:
        return self._slots

    def __repr__(self) -> str:
        return f"<<{self.stereotype.name} {self.values}>>"


class InheritedApplication:
    """A definition's application of a stereotype, seen from a usage typed by that definition.

    Not an element and not stored: :func:`effective_applications` builds it for a
    stereotype the usage inherits and has no application of its own. It reads
    through to the definition's application (``source``); changing a value
    goes through ``engine.profiles``, which gives the usage an application of
    its own that overrides it.
    """

    inherited = True

    def __init__(self, element: Element, source: StereotypeApplication):
        self.annotated_element = element
        self.source = source
        self.stereotype = source.stereotype

    @property
    def definition(self) -> Element:
        return self.source.annotated_element        # type: ignore[return-value]

    def parent(self) -> StereotypeApplication:
        return self.source

    @property
    def values(self) -> dict[str, Any]:
        return self.source.values

    def own_values(self) -> dict[str, Any]:
        return {}

    def explicit_tags(self) -> list[StereotypeTag]:
        return []

    def is_explicit(self, tag: StereotypeTag) -> bool:
        return False

    def origin(self, name: str) -> str:
        self.source.tag(name)
        return "inherited"

    def tag(self, name: str) -> StereotypeTag:
        return self.source.tag(name)

    def get(self, name: str) -> Any:
        return self.source.get(name)

    def raw_slots(self) -> dict[StereotypeTag, Any]:
        return {}

    def set(self, name: str, value: Any) -> Any:
        raise StereotypeError(
            f"«{self.stereotype.full_name}» on {self.annotated_element.qualified_name!r} is "
            f"inherited from {self.definition.qualified_name!r}; override a value through the "
            f"profiles API (engine.profiles.set_property_value)")

    def __repr__(self) -> str:
        return f"<<{self.stereotype.name} inherited from {self.definition.name} {self.values}>>"


def _called_by_loader() -> bool:
    """Is the caller of :meth:`Stereotype.apply` the project loader (engine.serializer)?"""
    try:
        frame = sys._getframe(2)      # 0: this helper, 1: Stereotype.apply, 2: its caller
    except ValueError:                # pragma: no cover - shallow stack
        return False
    return frame.f_globals.get("__name__") == "engine.serializer"


def stereotypes_on(e: Element) -> list[StereotypeApplication]:
    return [a for a in e.annotations if isinstance(a, StereotypeApplication)]


def application_of(e: Element, stereotype: Stereotype) -> Optional[StereotypeApplication]:
    return next((a for a in stereotypes_on(e) if a.stereotype is stereotype), None)


def inheritance_source(e: Optional[Element]) -> Optional[Element]:
    """The definition whose stereotype values ``e`` inherits.

    A reference component (a ``PartUsage`` typed by a ``PartDefinition``) inherits from
    that definition; nothing else does (an inline component has no definition, and a
    definition inherits from nowhere). Matched by kind name, like the categories.
    """
    if e is None or not is_component_usage_kind(kind_names(e)):
        return None
    return next((t for t in getattr(e, "types", None) or []
                 if is_component_definition_kind(kind_names(t))), None)


def effective_applications(e: Element) -> list:
    """The stereotypes ``e`` carries: its own applications, then the ones it inherits.

    Each item has ``stereotype``, ``values``, ``get``, ``origin`` and ``inherited``:
    False for a :class:`StereotypeApplication` of ``e`` itself, True for an
    :class:`InheritedApplication` (a stereotype of the definition ``e`` is typed by, applicable
    to ``e``, that ``e`` has no application of). Use :func:`stereotypes_on` for the stored ones.
    Only stereotypes of a profile are inherited; the legacy API (a stereotype in a plain package,
    untyped tags) keeps its values per element.
    """
    own = stereotypes_on(e)
    d = inheritance_source(e)
    if d is None:
        return own
    have = {id(a.stereotype) for a in own}
    return own + [InheritedApplication(e, a) for a in stereotypes_on(d)
                  if id(a.stereotype) not in have and a.stereotype.profile is not None
                  and a.stereotype.can_apply_to(e)]


def effective_application_of(e: Element, stereotype: Stereotype):
    """``e``'s own application of ``stereotype``, else the inherited one, else None."""
    return next((a for a in effective_applications(e) if a.stereotype is stereotype), None)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class Profile(Package):
    """A named, versioned set of stereotypes (System Composer profile)."""

    kind = "Profile"

    def __init__(self, name: Optional[str] = None, *, description: str = "",
                 version: str = "1.0", **kwargs):
        super().__init__(name=name, **kwargs)
        self.description: str = description or ""
        self.version: str = version or ""
        # Applied to new root architectures (and existing ones when set or imported).
        self.root_stereotype: Optional[Stereotype] = None
        # Provenance of an imported profile: {"file", "imported_at", "format"}.
        self.source: dict = {}
        _ensure_engine_support()

    @property
    def stereotypes(self) -> list[Stereotype]:
        return [c for c in self.owned_elements if isinstance(c, Stereotype)]

    def stereotype(self, name: str) -> Optional[Stereotype]:
        return next((s for s in self.stereotypes if s.name == name), None)


_ENGINE_LOADED = False


def _ensure_engine_support() -> None:
    """Load engine.profiles (persistence codecs, validator rules, hooks) on first use.

    The extra attributes defined here are saved by codecs registered in that
    module; importing it lazily means a project using stereotypes always saves
    them, even if the caller never imported engine.profiles itself.
    """
    global _ENGINE_LOADED
    if _ENGINE_LOADED:
        return
    _ENGINE_LOADED = True
    try:
        import importlib
        importlib.import_module("engine.profiles")
    except ImportError:  # pragma: no cover - kerml used without the engine package
        _ENGINE_LOADED = False
