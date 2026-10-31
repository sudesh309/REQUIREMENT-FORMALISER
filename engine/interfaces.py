"""System Composer interfaces on SysML v2.

This module adds the interface layer of a System Composer style
architecture model on top of the SysML v2 metamodel:

- **Data interfaces** (``DataInterface``, a ``PortDefinition``) made of
  ordered **data elements** (``DataElement``, an ``AttributeUsage``) with a
  type, dimensions, units, complexity, minimum, maximum and description.
- **Value types** (``ValueType``, an ``AttributeDefinition``): named atomic
  types usable as element types and as port interfaces.
- **Nested interfaces**: a data element typed by another data interface
  (cycles are rejected).
- **Physical interfaces** (``PhysicalInterface``) with **physical
  elements** (``PhysicalElement``) that carry a physical *domain*.
- **Service interfaces** (``ServiceInterface``) with **function elements**
  (``FunctionElement``: prototype, arguments, asynchronous flag).
- **Enumerations** (``EnumerationDefinition``) and **named constants**
  (``NamedConstant``) for the architectural data editor.
- The **interface dictionary** (``InterfaceDictionary``, a ``Package``)
  holding *shared* interfaces; *owned* interfaces live under one port.
- **Port assignment**, **connector compatibility** (including bus element
  selection at either connector end), **adapters** with element mappings,
  and dictionary **export / import** with collision resolution.

All edits go through the functions below so the web API, the MCP tools and
tests share one set of validation rules; they raise ``InterfaceError``
(a ``ValueError`` carrying an HTTP-style ``status``) with a clear message.

Conventions (see docs/EXTENDING.md "Cross-feature contracts"): a port's
interface is its type; a connector is a ``ConnectionUsage`` with
``ends[0]`` the source port and ``ends[1]`` the destination port.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional

from kerml.elements import Documentation, Element
from kerml.features import Feature, FeatureDirection
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Namespace, Package
from kerml.types import Type
from sysmlv2.definitions import (
    AttributeDefinition, AttributeUsage, ConnectionUsage, Definition,
    EnumerationDefinition, EnumerationUsage, PartDefinition, PartUsage,
    PortDefinition, PortUsage,
)

from .hooks import notify_created, register_created_hook
from .properties import register_scalar_property
from .repository import register_removal_hook
from .serializer import register_codec
from .structure import (
    components_of, connectors_of, definition_of, owning_component, ports_of,
    register_connector_warning_source,
)
from .validator import Severity, ValidationIssue, register_repo_rule

Resolver = Callable[[str], Optional[Element]]


class InterfaceError(ValueError):
    """A rejected interface edit. ``status`` is the matching HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Metamodel
# ---------------------------------------------------------------------------

class InterfaceDictionary(Package):
    """The project's interface dictionary (System Composer ``.sldd``)."""

    kind = "InterfaceDictionary"


class DataInterface(PortDefinition):
    """A data interface (System Composer: bus object) made of data elements."""

    kind = "DataInterface"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.color: Optional[str] = None


class PhysicalInterface(PortDefinition):
    """A physical interface (Simscape connection bus) made of physical elements."""

    kind = "PhysicalInterface"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.color: Optional[str] = None


class ServiceInterface(PortDefinition):
    """A client/server service interface made of function elements."""

    kind = "ServiceInterface"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.color: Optional[str] = None


class ValueType(AttributeDefinition):
    """A named atomic type: base type, units, dimensions, range."""

    kind = "ValueType"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.base_type: str = "double"
        self.units: str = ""
        self.dimensions: str = "1"
        self.complexity: str = "real"
        self.minimum: Optional[float] = None
        self.maximum: Optional[float] = None
        self.color: Optional[str] = None


class DataElement(AttributeUsage):
    """One signal of a data interface.

    The type is either a primitive (``primitive_type``; the feature is then
    typed by the matching KerML scalar so SysML typing stays meaningful) or
    a ``ValueType`` / ``DataInterface`` (nesting) / ``EnumerationDefinition``
    held as the feature's SysML type.
    """

    kind = "DataElement"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.primitive_type: Optional[str] = "double"
        self.dimensions: str = "1"
        self.units: str = ""
        self.complexity: str = "real"
        self.minimum: Optional[float] = None
        self.maximum: Optional[float] = None


class PhysicalElement(AttributeUsage):
    """One physical conserving connection of a physical interface."""

    kind = "PhysicalElement"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.domain: str = "electrical"


class FunctionElement(AttributeUsage):
    """One function of a service interface: ``[y1, y2] = name(u1, u2)``."""

    kind = "FunctionElement"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.prototype: str = ""
        self.arguments: list[dict] = []
        self.asynchronous: bool = False


class NamedConstant(AttributeUsage):
    """A named constant in the architectural data dictionary."""

    kind = "NamedConstant"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.value: str = "0"
        self.primitive_type: Optional[str] = "double"
        self.units: str = ""


class Adapter(PartUsage):
    """An interface adapter component mapping output elements from input elements.

    ``mappings`` is a list of ``{"target", "source", "note"}``: output element
    ``target`` is produced from input element ``source``; ``note`` documents a
    unit conversion when the units differ.
    """

    kind = "Adapter"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.mappings: list[dict] = []


INTERFACE_CLASSES = (DataInterface, PhysicalInterface, ServiceInterface)
ELEMENT_CLASSES = (DataElement, PhysicalElement, FunctionElement)
ITEM_CLASSES = (DataInterface, PhysicalInterface, ServiceInterface, ValueType,
                EnumerationDefinition, NamedConstant)

# Kind names other features (profiles / stereotypes) can target.
INTERFACE_KINDS = ("DataInterface", "ValueType", "PhysicalInterface", "ServiceInterface")
INTERFACE_ELEMENT_KINDS = ("DataElement", "PhysicalElement", "FunctionElement")
ITEM_KINDS = ("DataInterface", "ValueType", "PhysicalInterface", "ServiceInterface",
              "Enumeration", "Constant")

ALL_CLASSES = {
    "InterfaceDictionary": InterfaceDictionary, "DataInterface": DataInterface,
    "DataElement": DataElement, "ValueType": ValueType,
    "PhysicalInterface": PhysicalInterface, "PhysicalElement": PhysicalElement,
    "ServiceInterface": ServiceInterface, "FunctionElement": FunctionElement,
    "NamedConstant": NamedConstant, "Adapter": Adapter,
}


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

PRIMITIVE_TYPES = ("double", "single", "half", "int8", "uint8", "int16", "uint16",
                   "int32", "uint32", "int64", "uint64", "boolean", "string")

_PRIMITIVE_TO_KERML = {
    "double": "Real", "single": "Real", "half": "Real",
    "int8": "Integer", "int16": "Integer", "int32": "Integer", "int64": "Integer",
    "uint8": "Natural", "uint16": "Natural", "uint32": "Natural", "uint64": "Natural",
    "boolean": "Boolean", "string": "String",
}

COMPLEXITIES = ("real", "complex", "auto")

PHYSICAL_DOMAINS = {
    "electrical": "Electrical (voltage, current)",
    "electrical-three-phase": "Three-phase electrical",
    "mechanical-translational": "Mechanical translational (force, velocity)",
    "mechanical-rotational": "Mechanical rotational (torque, angular velocity)",
    "hydraulic": "Hydraulic (pressure, flow rate)",
    "isothermal-liquid": "Isothermal liquid",
    "thermal-liquid": "Thermal liquid",
    "thermal": "Thermal (temperature, heat flow)",
    "magnetic": "Magnetic (MMF, flux)",
    "gas": "Gas",
    "moist-air": "Moist air",
    "two-phase-fluid": "Two-phase fluid",
    "pneumatic": "Pneumatic",
}

# Unit symbols accepted without a warning. Compound units are checked token by
# token, e.g. "m/s^2", "N*m", "kg/h".
KNOWN_UNITS = (
    # length / area / volume
    "m", "km", "cm", "mm", "um", "nm", "ft", "in", "yd", "mi", "nmi", "NM",
    "L", "mL", "gal",
    # time / frequency
    "s", "ms", "us", "ns", "min", "h", "hr", "d", "day",
    "Hz", "kHz", "MHz", "GHz", "rpm",
    # angle / rate
    "rad", "mrad", "deg", "arcmin", "arcsec", "rev",
    # speed
    "kn", "kt", "kts", "mph", "kph", "fpm", "Mach",
    # mass / force / pressure
    "kg", "g", "mg", "lb", "lbm", "slug", "t", "N", "kN", "lbf",
    "Pa", "kPa", "MPa", "hPa", "bar", "mbar", "psi", "inHg", "mmHg", "atm",
    # temperature
    "K", "degC", "degF", "degR",
    # electrical / magnetic
    "V", "mV", "kV", "A", "mA", "uA", "W", "mW", "kW", "MW", "VA", "kVA", "VAR",
    "Ohm", "ohm", "kOhm", "MOhm", "F", "uF", "nF", "pF", "H", "mH", "C", "Ah", "mAh",
    "S", "T", "Wb",
    # energy
    "J", "kJ", "MJ", "Wh", "kWh", "cal", "BTU",
    # data / communication
    "bit", "bits", "byte", "bytes", "B", "kB", "MB", "GB", "kbit", "Mbit",
    "bps", "kbps", "Mbps", "Gbps", "word", "words",
    # misc
    "%", "ppm", "dB", "dBm", "1", "count", "cycles", "lux", "cd", "mol", "gn",
)
_KNOWN_UNITS = set(KNOWN_UNITS)

PALETTE = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
           "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f")

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PROTO_RE = re.compile(
    r"^\s*(?:(?:\[(?P<outs>[^\]]*)\]|(?P<out>[A-Za-z]\w*))\s*=\s*)?"
    r"(?P<name>[A-Za-z]\w*)\s*\((?P<ins>[^)]*)\)\s*$")

DICTIONARY_NAME = "Interfaces"
EXPORT_FORMAT = "sysml-interface-dictionary/1"

# Avionics bus / signal templates for "New from template".
TEMPLATES: dict[str, dict] = {
    "arinc429": {
        "label": "ARINC 429 word", "kind": "DataInterface", "name": "A429Word",
        "description": "32-bit ARINC 429 word: label, SDI, data field, SSM and parity.",
        "elements": [
            {"name": "label", "type": "uint8", "description": "Octal label (bits 1-8)"},
            {"name": "sdi", "type": "uint8", "minimum": 0, "maximum": 3,
             "description": "Source/destination identifier (bits 9-10)"},
            {"name": "data", "type": "uint32", "minimum": 0, "maximum": 524287,
             "description": "Data field (bits 11-29), BNR / BCD / discrete"},
            {"name": "ssm", "type": "uint8", "minimum": 0, "maximum": 3,
             "description": "Sign/status matrix (bits 30-31)"},
            {"name": "parity", "type": "boolean", "description": "Odd parity (bit 32)"},
        ],
    },
    "arinc664": {
        "label": "ARINC 664 (AFDX) message", "kind": "DataInterface", "name": "AfdxMessage",
        "description": "ARINC 664 part 7 virtual-link message.",
        "elements": [
            {"name": "vl_id", "type": "uint16", "description": "Virtual link identifier"},
            {"name": "bag", "type": "double", "units": "ms", "minimum": 1, "maximum": 128,
             "description": "Bandwidth allocation gap"},
            {"name": "max_frame_size", "type": "uint16", "units": "byte", "minimum": 64,
             "maximum": 1518, "description": "Lmax"},
            {"name": "sequence_number", "type": "uint8", "description": "Frame sequence number"},
            {"name": "payload", "type": "uint8", "dimensions": "1471", "units": "byte",
             "description": "Application payload"},
        ],
    },
    "milstd1553": {
        "label": "MIL-STD-1553 message", "kind": "DataInterface", "name": "M1553Message",
        "description": "MIL-STD-1553B command/data/status message.",
        "elements": [
            {"name": "rt_address", "type": "uint8", "minimum": 0, "maximum": 31,
             "description": "Remote terminal address"},
            {"name": "subaddress", "type": "uint8", "minimum": 0, "maximum": 31,
             "description": "Subaddress / mode code"},
            {"name": "word_count", "type": "uint8", "minimum": 1, "maximum": 32,
             "description": "Data word count"},
            {"name": "data", "type": "uint16", "dimensions": "32", "description": "Data words"},
            {"name": "status_word", "type": "uint16", "description": "RT status word"},
        ],
    },
    "discrete": {
        "label": "Discrete signal", "kind": "DataInterface", "name": "DiscreteSignal",
        "description": "28V/open or ground/open discrete.",
        "elements": [
            {"name": "state", "type": "boolean", "description": "Asserted state"},
            {"name": "valid", "type": "boolean", "description": "Signal validity"},
        ],
    },
    "analog": {
        "label": "Analog signal", "kind": "DataInterface", "name": "AnalogSignal",
        "description": "Analog voltage signal with validity.",
        "elements": [
            {"name": "value", "type": "double", "units": "V", "description": "Measured voltage"},
            {"name": "valid", "type": "boolean", "description": "Signal validity"},
        ],
    },
    "power28vdc": {
        "label": "28 VDC power", "kind": "PhysicalInterface", "name": "Power28VDC",
        "description": "28 VDC aircraft power feed.",
        "elements": [
            {"name": "positive", "domain": "electrical", "description": "+28 VDC"},
            {"name": "ret", "domain": "electrical", "description": "Power return"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _in_library(e: Element) -> bool:
    return e.root().name in {"KerML", "SysML"}


def _doc(e: Element) -> str:
    return next((a.body for a in e.annotations if isinstance(a, Documentation)), "")


def _set_doc(e: Element, text: Optional[str]) -> None:
    e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
    if text:
        e.add_annotation(Documentation(body=str(text)))


def _kerml_scalar(primitive: str) -> Optional[Type]:
    t = KERML_LIBRARY.resolve(f"ScalarValues::{_PRIMITIVE_TO_KERML.get(primitive, 'Real')}")
    return t if isinstance(t, Type) else None


def _set_typing(feature: Feature, target: Optional[Type]) -> None:
    """Replace the SysML typing of `feature` with `target` (or none)."""
    feature.remove_types()
    if target is not None:
        feature.add_type(target)


def _model_type(f: Feature) -> Optional[Type]:
    """The first non-library type of a feature (its interface / value type / ...)."""
    return next((t for t in f.types if not _in_library(t)), None)


def _type_primitive(e: Feature, primitive: str) -> None:
    e.primitive_type = primitive
    _set_typing(e, _kerml_scalar(primitive))


def _type_attribute(e: Feature) -> None:
    """Type physical / function elements by SysML's Attribute so they validate cleanly."""
    if not e.types:
        from sysmlv2.library import SYSML_LIBRARY
        base = SYSML_LIBRARY.resolve("Attributes::Attribute")
        if isinstance(base, Type):
            e.add_type(base)


def _check_name(name: Any, what: str = "Name") -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise InterfaceError(
            f"{what} {name!r} is not valid: start with a letter and use only letters, "
            f"digits and underscores (max 63 characters)")
    return name


def _sibling(owner: Optional[Element], name: str, exclude: Optional[Element] = None) -> Optional[Element]:
    if owner is None:
        return None
    return next((c for c in owner.children if c.name == name and c is not exclude), None)


def _unique_name(owner: Element, base: str, start: int = 0, *, always_number: bool = True) -> str:
    if not always_number and _sibling(owner, base) is None:
        return base
    i = start
    while _sibling(owner, f"{base}{i}") is not None:
        i += 1
    return f"{base}{i}"


def _unique_rename(owner: Element, base: str) -> str:
    """`base_1`, `base_2`, ... (System Composer style rename on collision)."""
    i = 1
    while _sibling(owner, f"{base}_{i}") is not None:
        i += 1
    return f"{base}_{i}"


def _reparent(child: Element, new_owner: Namespace, repo=None) -> None:
    """Move `child` to `new_owner`, dropping the old owner's membership."""
    if child.owner is new_owner:
        return
    stale = child.owning_relationship
    child.detach()
    if repo is not None and stale is not None:
        repo.registry.unregister(stale)
    new_owner.own(child)
    if repo is not None:
        repo.registry.register_tree(child)
        repo.registry.register(child.owning_relationship)


def _reorder(ns: Element, ordered: list[Element]) -> None:
    """Put `ordered` (a subset of ns' children) first, in that order, then the rest."""
    ids = {id(e) for e in ordered}
    ns.owned_elements = list(ordered) + [c for c in ns.children if id(c) not in ids]


def parse_dimensions(text: Any) -> tuple[int, ...]:
    """'1', '3', '[3 3]', '[1,3]' -> tuple of positive ints."""
    if isinstance(text, int) and not isinstance(text, bool):
        text = str(text)
    if isinstance(text, (list, tuple)):
        text = "[" + " ".join(str(x) for x in text) + "]"
    s = str(text if text is not None else "").strip()
    if not s:
        return (1,)
    inner = s[1:-1] if s.startswith("[") and s.endswith("]") else s
    parts = [p for p in re.split(r"[\s,;]+", inner.strip()) if p]
    if not parts or not all(re.fullmatch(r"\d+", p) and int(p) >= 1 for p in parts):
        raise InterfaceError(
            f"Invalid dimensions {text!r}: use a positive integer such as 1 or 3, "
            f"or a size vector such as [3 3]")
    return tuple(int(p) for p in parts)


def _norm_dims(dims: tuple[int, ...]) -> tuple[int, ...]:
    d = list(dims)
    while len(d) > 1 and d[-1] == 1:
        d.pop()
    return tuple(d)


def format_dimensions(dims: tuple[int, ...]) -> str:
    return str(dims[0]) if len(dims) == 1 else "[" + " ".join(str(d) for d in dims) + "]"


def _safe_dims(text: Any) -> tuple[int, ...]:
    try:
        return _norm_dims(parse_dimensions(text))
    except InterfaceError:
        return (-1,)


def parse_bound(value: Any, what: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InterfaceError(f"{what} must be a number")
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        s = str(value).strip()
        if s in ("", "[]"):
            return None
        try:
            num = float(s)
        except ValueError:
            raise InterfaceError(f"{what} {value!r} is not a number") from None
    if num != num:  # NaN
        raise InterfaceError(f"{what} must be a number")
    return int(num) if num.is_integer() and abs(num) < 2 ** 53 else num


def unit_problem(units: str) -> Optional[str]:
    """None when every token of `units` is a known unit, else a message."""
    s = (units or "").strip()
    if not s:
        return None
    tokens = [t for t in re.split(r"[*/·\s()^.\-]+|\d+", s) if t]
    unknown = [t for t in tokens if t not in _KNOWN_UNITS]
    if unknown:
        return f"unknown unit {', '.join(repr(u) for u in unknown)} in {units!r}"
    return None


def parse_prototype(text: str) -> tuple[str, list[str], list[str]]:
    """'[y1, y2] = f(u1, u2)' -> ('f', ['u1', 'u2'], ['y1', 'y2'])."""
    m = _PROTO_RE.match(text or "")
    if not m:
        raise InterfaceError(
            f"Invalid function prototype {text!r}: use the form 'y = name(u)', "
            f"'[y1, y2] = name(u1, u2)' or 'name()'")

    def names(group: Optional[str]) -> list[str]:
        out = [p.strip() for p in (group or "").split(",") if p.strip()]
        for n in out:
            _check_name(n, "Argument name")
        return out

    outs = names(m.group("outs")) if m.group("outs") is not None else names(m.group("out"))
    ins = names(m.group("ins"))
    dup = {n for n in ins + outs if (ins + outs).count(n) > 1}
    if dup:
        raise InterfaceError(f"Function prototype {text!r} repeats argument {sorted(dup)[0]!r}")
    return m.group("name"), ins, outs


def _format_prototype(name: str, ins: list[str], outs: list[str]) -> str:
    lhs = ""
    if len(outs) == 1:
        lhs = f"{outs[0]} = "
    elif outs:
        lhs = f"[{', '.join(outs)}] = "
    return f"{lhs}{name}({', '.join(ins)})"


def _norm_proto(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


# ---------------------------------------------------------------------------
# Classification and lookup
# ---------------------------------------------------------------------------

def item_kind(e: Element) -> Optional[str]:
    """System Composer kind of a dictionary item, or None."""
    if isinstance(e, DataInterface):
        return "DataInterface"
    if isinstance(e, PhysicalInterface):
        return "PhysicalInterface"
    if isinstance(e, ServiceInterface):
        return "ServiceInterface"
    if isinstance(e, ValueType):
        return "ValueType"
    if isinstance(e, EnumerationDefinition):
        return "Enumeration"
    if isinstance(e, NamedConstant):
        return "Constant"
    if type(e) is PortDefinition:
        return "PortDefinition"
    return None


def is_owned(iface: Optional[Element]) -> bool:
    """True when `iface` is an owned (anonymous) interface of one port."""
    return iface is not None and isinstance(iface.owner, PortUsage)


def get_dictionary(repo, create: bool = True) -> Optional[InterfaceDictionary]:
    """The project's interface dictionary package (created on first use)."""
    root = repo.root_package
    hit = next((c for c in root.children if isinstance(c, InterfaceDictionary)), None)
    if hit is None:
        hit = next((e for e in root.walk() if isinstance(e, InterfaceDictionary)), None)
    if hit is not None or not create:
        return hit
    name = DICTIONARY_NAME if _sibling(root, DICTIONARY_NAME) is None \
        else _unique_name(root, "InterfaceDictionary", 1, always_number=False)
    d = InterfaceDictionary(name=name)
    root.own(d)
    notify_created(d, repo)
    return d


def shared_items(repo) -> list[Element]:
    """Dictionary items that are not owned by a port, dictionary first."""
    dic = get_dictionary(repo, create=False)
    first = [c for c in (dic.children if dic else []) if isinstance(c, ITEM_CLASSES)]
    seen = {id(e) for e in first}
    rest = [e for e in repo.root_package.walk()
            if isinstance(e, ITEM_CLASSES) and id(e) not in seen and not is_owned(e)]
    # Constants count as dictionary items only when they sit in a package.
    return first + [e for e in rest if not isinstance(e, NamedConstant)
                    or isinstance(e.owner, Package)]


def owned_interfaces(repo) -> list[Element]:
    return [e for e in repo.root_package.walk()
            if isinstance(e, (*INTERFACE_CLASSES, PortDefinition)) and is_owned(e)]


def plain_port_definitions(repo) -> list[PortDefinition]:
    return [e for e in repo.root_package.walk() if type(e) is PortDefinition and not is_owned(e)]


def find_item(repo, ref: str, resolve: Optional[Resolver] = None,
              classes: tuple = ITEM_CLASSES) -> Optional[Element]:
    """Find a dictionary item by id, qualified name or plain name."""
    if not ref:
        return None
    hit = repo.by_id(ref) if hasattr(repo, "by_id") else None
    if hit is None and resolve is not None:
        hit = resolve(ref)
    if hit is None and "::" in ref:
        hit = repo.resolve(ref)
    if isinstance(hit, classes):
        return hit
    for e in shared_items(repo):
        if e.name == ref and isinstance(e, classes):
            return e
    return None


def interface_of(port: Element) -> Optional[Element]:
    """The interface (port definition / value type) assigned to a port, or None."""
    if not isinstance(port, Feature):
        return None
    t = _model_type(port)
    return t if isinstance(t, (PortDefinition, AttributeDefinition)) else None


def elements_of(iface: Optional[Element]) -> list[Element]:
    """Ordered elements of an interface (data/physical/function elements, literals)."""
    if iface is None:
        return []
    if isinstance(iface, EnumerationDefinition):
        return [c for c in iface.children if isinstance(c, EnumerationUsage)]
    if isinstance(iface, INTERFACE_CLASSES):
        return [c for c in iface.children if isinstance(c, ELEMENT_CLASSES)]
    if isinstance(iface, PortDefinition):
        return [c for c in iface.children if isinstance(c, AttributeUsage)]
    return []


def find_element(iface: Optional[Element], path: str) -> Optional[Element]:
    """Resolve a dotted element path (``nav.position.lat``) through nested interfaces."""
    node = iface
    el = None
    for part in [p for p in (path or "").split(".") if p]:
        if node is None:
            return None
        el = next((c for c in elements_of(node) if c.name == part), None)
        if el is None:
            return None
        nested = _model_type(el) if isinstance(el, Feature) else None
        node = nested if isinstance(nested, PortDefinition) else None
    return el


def element_paths(iface: Optional[Element], depth: int = 4) -> list[str]:
    """Selectable element paths of an interface, including nested ones."""
    out: list[str] = []

    def walk(node: Element, prefix: str, level: int, seen: frozenset) -> None:
        for el in elements_of(node):
            path = f"{prefix}{el.name}"
            out.append(path)
            nested = _model_type(el) if isinstance(el, Feature) else None
            if isinstance(nested, PortDefinition) and level < depth and id(nested) not in seen:
                walk(nested, path + ".", level + 1, seen | {id(nested)})

    if iface is not None and not isinstance(iface, EnumerationDefinition):
        walk(iface, "", 1, frozenset({id(iface)}))
    return out


def ports_using(repo, iface: Element) -> list[PortUsage]:
    return [e for e in repo.root_package.walk()
            if isinstance(e, PortUsage) and any(t is iface for t in e.types)]


def elements_using(repo, item: Element) -> list[Element]:
    """Data elements / constants / value types whose type is `item`."""
    return [e for e in repo.root_package.walk()
            if isinstance(e, (DataElement, NamedConstant)) and any(t is item for t in e.types)]


def next_color(repo) -> str:
    used = [getattr(e, "color", None) for e in repo.root_package.walk()
            if isinstance(e, (*INTERFACE_CLASSES, ValueType))]
    for c in PALETTE:
        if c not in used:
            return c
    return PALETTE[len(used) % len(PALETTE)]


# ---------------------------------------------------------------------------
# Types of data elements
# ---------------------------------------------------------------------------

_PREFIXES = {
    "valuetype": (ValueType,), "bus": (DataInterface,), "interface": (DataInterface,),
    "datainterface": (DataInterface,), "enum": (EnumerationDefinition,),
    "enumeration": (EnumerationDefinition,),
}


def describe_type(e: Feature) -> str:
    """System Composer type string: 'double', 'ValueType: X', 'Bus: X', 'Enum: X'."""
    t = _model_type(e)
    if isinstance(t, ValueType):
        return f"ValueType: {t.name}"
    if isinstance(t, DataInterface) or type(t) is PortDefinition:
        return f"Bus: {t.name}"
    if isinstance(t, EnumerationDefinition):
        return f"Enum: {t.name}"
    if t is not None:
        return t.qualified_name
    prim = getattr(e, "primitive_type", None)
    if prim:
        return prim
    lib = next(iter(e.types), None)
    return lib.name.lower() if lib is not None else ""


def resolve_type_spec(repo, spec: Any, resolve: Optional[Resolver] = None,
                      name_map: Optional[dict] = None) -> tuple[str, Any]:
    """('primitive', 'double') or ('element', <ValueType|DataInterface|EnumerationDefinition>)."""
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        return ("primitive", "double")
    if isinstance(spec, Element):
        target = spec
    else:
        s = str(spec).strip()
        if s.lower() in PRIMITIVE_TYPES:
            return ("primitive", s.lower())
        target = None
        m = re.match(r"^\s*([A-Za-z]+)\s*:\s*(.+?)\s*$", s)
        if m and m.group(1).lower() in _PREFIXES:
            classes = _PREFIXES[m.group(1).lower()]
            name = m.group(2)
            if name_map and isinstance(name_map.get(name), classes):
                target = name_map[name]
            else:
                target = find_item(repo, name, resolve, classes)
            if target is None:
                raise InterfaceError(f"Type {s!r} not found in the interface dictionary", 404)
        else:
            if name_map and name_map.get(s) is not None:
                target = name_map[s]
            else:
                target = find_item(repo, s, resolve, (ValueType, DataInterface, EnumerationDefinition,
                                                      PortDefinition))
            if target is None:
                raise InterfaceError(
                    f"Unknown type {s!r}: use a primitive ({', '.join(PRIMITIVE_TYPES)}), "
                    f"'ValueType: <name>', 'Bus: <name>' or 'Enum: <name>'", 404)
    if not isinstance(target, (ValueType, PortDefinition, EnumerationDefinition)) \
            or isinstance(target, (PhysicalInterface, ServiceInterface)):
        raise InterfaceError(
            f"{target.qualified_name!r} cannot type a data element: use a value type, "
            f"a data interface or an enumeration")
    if is_owned(target):
        raise InterfaceError(
            f"Interface {target.name!r} is owned by port {target.owner.name!r}; "
            f"convert it to a shared interface before using it as an element type")
    return ("element", target)


def _nesting_path(start: Element, goal: Element, seen: Optional[set] = None) -> Optional[list[Element]]:
    """Interfaces from `start` down to `goal` through nested element types, or None."""
    if start is goal:
        return [start]
    seen = seen if seen is not None else set()
    if id(start) in seen:
        return None
    seen.add(id(start))
    for el in elements_of(start):
        t = _model_type(el) if isinstance(el, Feature) else None
        if isinstance(t, PortDefinition):
            sub = _nesting_path(t, goal, seen)
            if sub is not None:
                return [start] + sub
    return None


def _apply_type(repo, el: Feature, spec: Any, resolve: Optional[Resolver] = None,
                name_map: Optional[dict] = None) -> None:
    kind, value = resolve_type_spec(repo, spec, resolve, name_map)
    if kind == "primitive":
        _type_primitive(el, value)
        return
    owner = el.owner
    if isinstance(value, PortDefinition) and owner is not None:
        path = _nesting_path(value, owner)
        if path is not None:
            chain = " -> ".join(p.name or "?" for p in [owner] + path)
            raise InterfaceError(f"Nesting {value.name!r} in {owner.name!r} creates a cycle: {chain}")
    el.primitive_type = None
    _set_typing(el, value)


# ---------------------------------------------------------------------------
# Field editing (validated, atomic per call)
# ---------------------------------------------------------------------------

_DATA_FIELDS = ("name", "type", "dimensions", "units", "complexity", "minimum", "maximum",
                "description")
FIELDS: dict[str, tuple[str, ...]] = {
    "DataElement": _DATA_FIELDS,
    "PhysicalElement": ("name", "domain", "description"),
    "FunctionElement": ("name", "prototype", "asynchronous", "arguments", "description"),
    "EnumerationLiteral": ("name", "value", "description"),
    "ValueType": ("name", "base_type", "dimensions", "units", "complexity", "minimum",
                  "maximum", "description", "color"),
    "NamedConstant": ("name", "value", "type", "units", "description"),
    "Interface": ("name", "color", "description"),
    "Enumeration": ("name", "default", "description"),
}


def _fields_for_class(cls: type) -> tuple[str, ...]:
    for base, key in ((DataElement, "DataElement"), (PhysicalElement, "PhysicalElement"),
                      (FunctionElement, "FunctionElement"), (EnumerationUsage, "EnumerationLiteral"),
                      (ValueType, "ValueType"), (NamedConstant, "NamedConstant"),
                      (PortDefinition, "Interface"), (EnumerationDefinition, "Enumeration")):
        if issubclass(cls, base):
            return FIELDS[key]
    return ()


def fields_for(e: Element) -> tuple[str, ...]:
    return _fields_for_class(type(e))


def _check_rename(e: Element, name: str) -> None:
    _check_name(name, "Element name" if isinstance(e, AttributeUsage) else "Name")
    other = _sibling(e.owner, name, exclude=e)
    if other is not None:
        where = e.owner.name or "the model"
        raise InterfaceError(f"An element named {name!r} already exists in {where!r}", 409)


def _coerce_arguments(value: Any, ins: list[str], outs: list[str], old: list[dict]) -> list[dict]:
    """Argument table derived from a prototype; keeps properties of same-named args."""
    given = {a.get("name"): a for a in (value if isinstance(value, list) else []) if isinstance(a, dict)}
    previous = {a.get("name"): a for a in old}
    out = []
    for direction, names in (("in", ins), ("out", outs)):
        for n in names:
            src = given.get(n) or previous.get(n) or {}
            arg = {
                "name": n, "direction": direction,
                "type": str(src.get("type") or "double"),
                "dimensions": format_dimensions(parse_dimensions(src.get("dimensions", "1"))),
                "units": str(src.get("units") or ""),
                "description": str(src.get("description") or ""),
            }
            if arg["type"].lower() in PRIMITIVE_TYPES:
                arg["type"] = arg["type"].lower()
            out.append(arg)
    unknown = [n for n in given if n not in ins + outs]
    if unknown:
        raise InterfaceError(f"Argument {unknown[0]!r} is not in the function prototype")
    return out


def set_fields(repo, e: Element, fields: dict, resolve: Optional[Resolver] = None) -> list[str]:
    """Validate then apply `fields` on an interface, item or element.

    Returns warnings (e.g. unknown units). Raises InterfaceError, leaving `e`
    unchanged, when any field is invalid.
    """
    allowed = fields_for(e)
    if not allowed:
        raise InterfaceError(f"{e.kind} {e.name!r} is not an interface item or element")
    unknown = [k for k in fields if k not in allowed]
    if unknown:
        raise InterfaceError(f"{e.kind} has no field {unknown[0]!r}; fields: {', '.join(allowed)}")
    warnings: list[str] = []
    apply: list[Callable[[], None]] = []

    if "name" in fields and fields["name"] != e.name:
        new = fields["name"]
        _check_rename(e, new)
        apply.append(lambda: rename(repo, e, new, _checked=True))

    if "description" in fields:
        apply.append(lambda: _set_doc(e, fields["description"] or ""))

    if "color" in fields:
        c = fields["color"]
        if not isinstance(e, (*INTERFACE_CLASSES, ValueType)):
            raise InterfaceError(
                f"{e.kind} {e.name!r} has no colour: only data, physical and service interfaces "
                f"and value types carry one")
        if c in (None, ""):
            apply.append(lambda: setattr(e, "color", None))
        elif not isinstance(c, str) or not _COLOR_RE.match(c):
            raise InterfaceError(f"Colour {c!r} must be a hex colour such as #1f77b4")
        else:
            apply.append(lambda: setattr(e, "color", c.lower()))

    if "dimensions" in fields:
        dims = format_dimensions(parse_dimensions(fields["dimensions"]))
        apply.append(lambda: setattr(e, "dimensions", dims))

    if "units" in fields:
        units = str(fields["units"] or "").strip()
        problem = unit_problem(units)
        if problem:
            warnings.append(problem)
        apply.append(lambda: setattr(e, "units", units))

    if "complexity" in fields:
        cx = str(fields["complexity"] or "real").lower()
        if cx not in COMPLEXITIES:
            raise InterfaceError(f"Complexity must be one of {', '.join(COMPLEXITIES)}")
        apply.append(lambda: setattr(e, "complexity", cx))

    if "minimum" in fields or "maximum" in fields:
        lo = parse_bound(fields["minimum"], "Minimum") if "minimum" in fields else getattr(e, "minimum", None)
        hi = parse_bound(fields["maximum"], "Maximum") if "maximum" in fields else getattr(e, "maximum", None)
        if lo is not None and hi is not None and lo > hi:
            raise InterfaceError(f"Minimum ({lo}) must not exceed maximum ({hi})")
        apply.append(lambda: (setattr(e, "minimum", lo), setattr(e, "maximum", hi)))

    if "base_type" in fields:
        bt = str(fields["base_type"] or "double").lower()
        if bt not in PRIMITIVE_TYPES:
            raise InterfaceError(f"Base type must be one of {', '.join(PRIMITIVE_TYPES)}")
        apply.append(lambda: setattr(e, "base_type", bt))

    if "type" in fields:
        if isinstance(e, NamedConstant):
            prim = str(fields["type"] or "double").lower()
            if prim not in PRIMITIVE_TYPES:
                raise InterfaceError(f"Constant type must be one of {', '.join(PRIMITIVE_TYPES)}")
            apply.append(lambda: _type_primitive(e, prim))
        else:
            spec = fields["type"]
            # Validate now (including cycle detection), apply with the rest.
            kind, value = resolve_type_spec(repo, spec, resolve)
            if kind == "element" and isinstance(value, PortDefinition) and e.owner is not None:
                path = _nesting_path(value, e.owner)
                if path is not None:
                    chain = " -> ".join(p.name or "?" for p in [e.owner] + path)
                    raise InterfaceError(
                        f"Nesting {value.name!r} in {e.owner.name!r} creates a cycle: {chain}")
            apply.append(lambda: _apply_type(repo, e, spec, resolve))

    if "domain" in fields:
        dom = str(fields["domain"] or "").strip().lower().replace(".", "-").replace("_", "-")
        if dom not in PHYSICAL_DOMAINS:
            raise InterfaceError(f"Physical domain must be one of {', '.join(PHYSICAL_DOMAINS)}")
        apply.append(lambda: setattr(e, "domain", dom))

    if "asynchronous" in fields:
        flag = fields["asynchronous"]
        if isinstance(flag, str):
            flag = flag.strip().lower() in ("1", "true", "yes", "on")
        apply.append(lambda: setattr(e, "asynchronous", bool(flag)))

    if "prototype" in fields or "arguments" in fields:
        new_name = fields.get("name", e.name)
        proto = fields.get("prototype", getattr(e, "prototype", "") or f"y = {new_name}(u)")
        fname, ins, outs = parse_prototype(proto)
        if fname != new_name:
            raise InterfaceError(
                f"Prototype function name {fname!r} must match the element name {new_name!r}")
        args = _coerce_arguments(fields.get("arguments"), ins, outs, getattr(e, "arguments", []))
        canonical = _format_prototype(fname, ins, outs)
        apply.append(lambda: (setattr(e, "prototype", canonical), setattr(e, "arguments", args)))

    if "value" in fields:
        v = fields["value"]
        if isinstance(e, EnumerationUsage):
            if v in (None, ""):
                apply.append(lambda: setattr(e, "default_value", None))
            else:
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    raise InterfaceError(f"Enumeration value {v!r} must be an integer") from None
                apply.append(lambda: setattr(e, "default_value", iv))
        else:
            apply.append(lambda: setattr(e, "value", "" if v is None else str(v)))

    if "default" in fields:
        d = fields["default"] or None
        if d is not None and not any(c.name == d for c in elements_of(e)):
            raise InterfaceError(f"Enumeration {e.name!r} has no literal {d!r}")
        apply.append(lambda: e.tool_data.__setitem__("default_literal", d) if d
                     else e.tool_data.pop("default_literal", None))

    for fn in apply:
        fn()
    return warnings


def rename(repo, e: Element, new_name: str, *, _checked: bool = False) -> None:
    """Rename an interface, item or element; references by name follow the rename."""
    if not _checked:
        _check_rename(e, new_name)
    old = e.name
    e.name = new_name
    if isinstance(e, FunctionElement) and e.prototype:
        try:
            _fname, ins, outs = parse_prototype(e.prototype)
            e.prototype = _format_prototype(new_name, ins, outs)
        except InterfaceError:
            pass
    if isinstance(e, EnumerationUsage) and isinstance(e.owner, EnumerationDefinition) \
            and e.owner.tool_data.get("default_literal") == old:
        e.owner.tool_data["default_literal"] = new_name
    if repo is None or old is None or not isinstance(e, AttributeUsage):
        return
    iface = e.owner
    # Connector element selections and adapter mappings refer to elements by path.
    for c in repo.root_package.walk():
        if isinstance(c, ConnectionUsage):
            for idx, attr in ((0, "source_element"), (1, "target_element")):
                path = getattr(c, attr, None)
                if path and len(c.ends) > idx:
                    setattr(c, attr, _renamed_path(interface_of(c.ends[idx]), path, iface, old, new_name))
        if isinstance(c, Adapter) and c.mappings:
            out_iface = adapter_output_interface(c)
            inputs = adapter_input_interfaces(c)
            for m in c.mappings:
                m["target"] = _renamed_path(out_iface, m["target"], iface, old, new_name)
                src = m["source"]
                first = src.split(".")[0]
                if first in inputs and len(src.split(".")) > 1:
                    rest = _renamed_path(inputs[first], src[len(first) + 1:], iface, old, new_name)
                    m["source"] = f"{first}.{rest}"
                else:
                    for in_iface in inputs.values():
                        src = _renamed_path(in_iface, src, iface, old, new_name)
                    m["source"] = src


def _renamed_path(root: Optional[Element], path: str, iface: Element, old: str, new: str) -> str:
    """`path` (resolved from interface `root`) with segment `old` of `iface` renamed to `new`."""
    parts = path.split(".")
    node = root
    for i, part in enumerate(parts):
        if node is None:
            break
        if node is iface and part == old:
            parts[i] = new
            break
        el = next((x for x in elements_of(node) if x.name == part), None)
        nested = _model_type(el) if isinstance(el, Feature) else None
        node = nested if isinstance(nested, PortDefinition) else None
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Creating items and elements
# ---------------------------------------------------------------------------

_ITEM_CLASS = {"DataInterface": DataInterface, "PhysicalInterface": PhysicalInterface,
               "ServiceInterface": ServiceInterface, "ValueType": ValueType,
               "Enumeration": EnumerationDefinition, "Constant": NamedConstant}
_DEFAULT_ITEM_NAME = {"DataInterface": "interface", "PhysicalInterface": "physicalInterface",
                      "ServiceInterface": "serviceInterface", "ValueType": "valueType",
                      "Enumeration": "Enum", "Constant": "constant"}


def _normalize_item_kind(kind: str) -> str:
    k = (kind or "DataInterface").strip()
    aliases = {"data": "DataInterface", "interface": "DataInterface", "bus": "DataInterface",
               "valuetype": "ValueType", "value_type": "ValueType", "value-type": "ValueType",
               "physical": "PhysicalInterface", "service": "ServiceInterface",
               "enum": "Enumeration", "enumeration": "Enumeration",
               "enumerationdefinition": "Enumeration",
               "constant": "Constant", "namedconstant": "Constant"}
    k = aliases.get(k.lower(), k)
    if k not in _ITEM_CLASS:
        raise InterfaceError(f"Unknown interface kind {kind!r}; use one of {', '.join(ITEM_KINDS)}")
    return k


def create_item(repo, kind: str = "DataInterface", name: Optional[str] = None, *,
                parent: Optional[Namespace] = None, resolve: Optional[Resolver] = None,
                elements: Optional[list[dict]] = None, literals: Optional[list[dict]] = None,
                **fields) -> Element:
    """Create a shared dictionary item (interface, value type, enumeration, constant)."""
    k = _normalize_item_kind(kind)
    owner = parent if parent is not None else get_dictionary(repo)
    if not isinstance(owner, Namespace):
        raise InterfaceError("Interfaces must be created in a package")
    if name is None or name == "":
        name = _unique_name(owner, _DEFAULT_ITEM_NAME[k])
    _check_name(name, "Interface name")
    if _sibling(owner, name) is not None:
        raise InterfaceError(f"An item named {name!r} already exists in {owner.name!r}", 409)
    cls = _ITEM_CLASS[k]
    item = cls(name=name)
    owner.own(item)
    repo.registry.register(item)        # keep save order = containment order
    try:
        if isinstance(item, NamedConstant):
            _type_primitive(item, "double")
        later = {k: fields.pop(k) for k in ("default",) if k in fields}
        if fields:
            set_fields(repo, item, fields, resolve)
        if getattr(item, "color", "missing") is None and isinstance(item, (*INTERFACE_CLASSES, ValueType)):
            item.color = next_color(repo)
        for spec in (elements or []) + (literals or []):
            if not isinstance(spec, dict):
                raise InterfaceError("each element must be an object with a name and fields")
            add_element(repo, item, resolve=resolve, **spec)
        if later:
            set_fields(repo, item, later, resolve)
    except Exception:
        repo.remove(item)
        raise
    notify_created(item, repo)
    return item


def create_value_type(repo, name: Optional[str] = None, **fields) -> ValueType:
    return create_item(repo, "ValueType", name, **fields)  # type: ignore[return-value]


def create_from_template(repo, template: str, name: Optional[str] = None) -> Element:
    spec = TEMPLATES.get(template)
    if spec is None:
        raise InterfaceError(f"Unknown template {template!r}; use one of {', '.join(TEMPLATES)}", 404)
    dic = get_dictionary(repo)
    base = name or spec["name"]
    if name is None and _sibling(dic, base) is not None:
        base = _unique_rename(dic, base)
    return create_item(repo, spec["kind"], base, description=spec.get("description", ""),
                       elements=[dict(e) for e in spec["elements"]])


def _element_class(owner: Element) -> type:
    if isinstance(owner, PhysicalInterface):
        return PhysicalElement
    if isinstance(owner, ServiceInterface):
        return FunctionElement
    if isinstance(owner, EnumerationDefinition):
        return EnumerationUsage
    if isinstance(owner, PortDefinition):
        return DataElement
    raise InterfaceError(f"{owner.kind} {owner.name!r} cannot hold interface elements")


def add_element(repo, owner: Element, name: Optional[str] = None, *, index: Optional[int] = None,
                resolve: Optional[Resolver] = None, **fields) -> Element:
    """Add an element (or enumeration literal) to an interface, optionally at `index`."""
    cls = _element_class(owner)
    base = {PhysicalElement: "elem", FunctionElement: "fcn", EnumerationUsage: "literal"}.get(cls, "elem")
    if name is None or name == "":
        name = _unique_name(owner, base)
    _check_name(name, "Element name")
    if _sibling(owner, name) is not None:
        raise InterfaceError(f"An element named {name!r} already exists in {owner.name!r}", 409)
    el = cls(name=name)
    owner.own(el)
    try:
        if isinstance(el, EnumerationUsage):
            el.add_type(owner)
            if "value" not in fields:
                values = [c.default_value for c in elements_of(owner) if c is not el
                          and isinstance(c.default_value, int)]
                el.default_value = (max(values) + 1) if values else 0
        if isinstance(el, DataElement) and "type" not in fields:
            _type_primitive(el, "double")
        if isinstance(el, FunctionElement) and "prototype" not in fields:
            fields = {**fields, "prototype": f"y = {name}(u)"}
        if fields:
            set_fields(repo, el, fields, resolve)
        if index is not None:
            move_element(el, index=int(index))
    except Exception:
        repo.remove(el)
        raise
    notify_created(el, repo)
    return el


def remove_element(repo, el: Element) -> None:
    if not isinstance(el, (*ELEMENT_CLASSES, EnumerationUsage, AttributeUsage)):
        raise InterfaceError(f"{el.kind} {el.name!r} is not an interface element")
    repo.remove(el)


def move_element(el: Element, delta: Optional[int] = None, *, index: Optional[int] = None) -> int:
    """Move an element within its interface by `delta` or to `index`; returns the new index."""
    owner = el.owner
    if owner is None:
        raise InterfaceError("Element has no owner")
    siblings = elements_of(owner)
    cur = siblings.index(el)
    target = cur + int(delta) if delta is not None else int(index if index is not None else cur)
    target = max(0, min(len(siblings) - 1, target))
    siblings.pop(cur)
    siblings.insert(target, el)
    _reorder(owner, siblings)
    return target


# ---------------------------------------------------------------------------
# Ports: assignment, owned <-> shared
# ---------------------------------------------------------------------------

def _drop_owned(repo, port: PortUsage, keep: Optional[Element] = None) -> None:
    for c in list(port.children):
        if isinstance(c, (*INTERFACE_CLASSES, PortDefinition)) and c is not keep:
            repo.remove(c)


def assign_interface(repo, port: Element, ref: Any, *, resolve: Optional[Resolver] = None,
                     owned_kind: str = "DataInterface") -> Optional[Element]:
    """Assign an interface to a port.

    `ref` is a shared interface / value type (element, id, qualified name or
    dictionary name), ``"owned"`` / ``"<owned>"`` for an owned interface (a
    copy of the current shared one, or a new empty one), or ``None`` /
    ``""`` / ``"<empty>"`` to clear the port's interface.
    """
    if not isinstance(port, PortUsage):
        raise InterfaceError(f"{getattr(port, 'name', port)!r} is not a port")
    if ref is None or (isinstance(ref, str) and ref.strip().lower() in ("", "<empty>", "empty", "none")):
        _set_typing(port, None)
        _drop_owned(repo, port)
        return None
    if isinstance(ref, str) and ref.strip().lower() in ("owned", "<owned>"):
        return make_owned(repo, port, kind=owned_kind)
    target = ref if isinstance(ref, Element) else find_item(
        repo, ref, resolve, (PortDefinition, ValueType))
    if target is None:
        cur = interface_of(port)
        if cur is not None and isinstance(ref, str) and ref == cur.qualified_name:
            return cur
        raise InterfaceError(f"Interface {ref!r} not found", 404)
    if not isinstance(target, (PortDefinition, ValueType)) or _in_library(target):
        raise InterfaceError(f"{target.qualified_name!r} is not an interface or value type")
    if is_owned(target) and target.owner is not port:
        raise InterfaceError(
            f"Interface {target.name!r} is owned by port {target.owner.name!r}; "
            f"convert it to a shared interface first")
    if interface_of(port) is target:
        return target
    _set_typing(port, target)
    _drop_owned(repo, port, keep=target)
    return target


def _copy_contents(repo, src: Element, dst: Element) -> None:
    """Copy description, colour and elements of `src` into the (empty) `dst`."""
    _set_doc(dst, _doc(src))
    if hasattr(src, "color") and hasattr(dst, "color"):
        dst.color = src.color
    for el in elements_of(src):
        copy = add_element(repo, dst, el.name)
        _copy_element_fields(el, copy)


def _copy_element_fields(src: Element, dst: Element) -> None:
    _set_doc(dst, _doc(src))
    if isinstance(src, DataElement) and isinstance(dst, DataElement):
        for a in ("dimensions", "units", "complexity", "minimum", "maximum"):
            setattr(dst, a, getattr(src, a))
        t = _model_type(src)
        if t is not None:
            dst.primitive_type = None
            _set_typing(dst, t)
        else:
            _type_primitive(dst, src.primitive_type or "double")
    elif isinstance(src, PhysicalElement) and isinstance(dst, PhysicalElement):
        dst.domain = src.domain
    elif isinstance(src, FunctionElement) and isinstance(dst, FunctionElement):
        dst.prototype, dst.asynchronous = src.prototype, src.asynchronous
        dst.arguments = [dict(a) for a in src.arguments]
    elif isinstance(src, EnumerationUsage):
        dst.default_value = src.default_value


def make_owned(repo, port: PortUsage, *, kind: str = "DataInterface") -> Element:
    """Give the port an owned interface: a copy of its shared one, or a new empty one."""
    if not isinstance(port, PortUsage):
        raise InterfaceError(f"{getattr(port, 'name', port)!r} is not a port")
    cur = interface_of(port)
    if cur is not None and cur.owner is port:
        return cur
    if cur is not None and not isinstance(cur, PortDefinition):
        raise InterfaceError("Only interfaces (not value types) can be converted to owned")
    cls = type(cur) if isinstance(cur, INTERFACE_CLASSES) else _ITEM_CLASS[_normalize_item_kind(kind)]
    if cls not in INTERFACE_CLASSES:
        raise InterfaceError("Owned interfaces must be data, physical or service interfaces")
    base = f"{port.name or 'port'}Interface"
    name = base if _NAME_RE.match(base) and _sibling(port, base) is None else _unique_name(port, "ownedInterface")
    owned = cls(name=name)
    port.own(owned)
    repo.registry.register(owned)
    if cur is not None:
        _copy_contents(repo, cur, owned)
    else:
        owned.color = next_color(repo)
    _set_typing(port, owned)
    notify_created(owned, repo)
    return owned


def make_shared(repo, port: PortUsage, name: Optional[str] = None,
                on_conflict: str = "error") -> Element:
    """Move a port's owned interface into the dictionary ("save to dictionary").

    On a name collision, `on_conflict` decides: ``"error"`` (raise 409),
    ``"keep"`` (use the existing shared interface, discard the owned one),
    ``"replace"`` (overwrite the existing one's contents) or ``"rename"``
    (save under a new unique name).
    """
    if not isinstance(port, PortUsage):
        raise InterfaceError(f"{getattr(port, 'name', port)!r} is not a port")
    owned = interface_of(port)
    if owned is None:
        raise InterfaceError(f"Port {port.name!r} has no interface")
    if not is_owned(owned):
        raise InterfaceError(f"Port {port.name!r} already uses the shared interface {owned.name!r}")
    if on_conflict not in ("error", "keep", "replace", "rename"):
        raise InterfaceError("on_conflict must be one of error, keep, replace, rename")
    dic = get_dictionary(repo)
    target_name = _check_name(name or owned.name, "Interface name")
    existing = _sibling(dic, target_name)
    if existing is not None:
        if on_conflict == "error":
            raise InterfaceError(
                f"An interface named {target_name!r} already exists in the dictionary; "
                f"choose keep, replace or rename", 409)
        if on_conflict == "keep":
            if not isinstance(existing, (PortDefinition, ValueType)):
                raise InterfaceError(f"{target_name!r} in the dictionary is not an interface")
            _set_typing(port, existing)
            repo.remove(owned)
            return existing
        if on_conflict == "replace":
            if type(existing) is type(owned):
                for el in list(elements_of(existing)):
                    repo.remove(el)
                _copy_contents(repo, owned, existing)
                _set_typing(port, existing)
                repo.remove(owned)
                return existing
            for user in ports_using(repo, existing) + elements_using(repo, existing):
                _set_typing(user, owned)
            repo.remove(existing)
        if on_conflict == "rename":
            target_name = _unique_rename(dic, target_name)
    _reparent(owned, dic, repo)
    owned.name = target_name
    return owned


def move_owned_to_dictionary(repo, on_conflict: str = "rename") -> list[dict]:
    """Save every port-owned interface into the dictionary."""
    report = []
    for iface in owned_interfaces(repo):
        port = iface.owner
        if not isinstance(iface, INTERFACE_CLASSES) or interface_of(port) is not iface:
            continue
        before = iface.name
        shared = make_shared(repo, port, before, on_conflict)
        report.append({"port": port.qualified_name, "interface": shared.name, "from": before})
    return report


# ---------------------------------------------------------------------------
# Connectors: element selection, creation
# ---------------------------------------------------------------------------

_UNSET = object()


def set_connector_elements(conn: Element, source_element: Any = _UNSET,
                           target_element: Any = _UNSET) -> None:
    """Select a bus element at either connector end ('' / None clears)."""
    if not isinstance(conn, ConnectionUsage):
        raise InterfaceError(f"{getattr(conn, 'name', conn)!r} is not a connector")
    updates = {}
    for idx, attr, value in ((0, "source_element", source_element), (1, "target_element", target_element)):
        if value is _UNSET:
            continue
        path = (value or "").strip() if isinstance(value, str) else value
        if not path:
            updates[attr] = None
            continue
        if len(conn.ends) <= idx:
            raise InterfaceError(f"Connector {conn.name!r} has no {'source' if idx == 0 else 'target'} end")
        port = conn.ends[idx]
        iface = interface_of(port)
        if iface is None:
            raise InterfaceError(f"Port {port.name!r} has no interface, so no element can be selected")
        if find_element(iface, path) is None:
            raise InterfaceError(f"Interface {iface.name!r} of port {port.name!r} has no element {path!r}")
        updates[attr] = path
    for attr, value in updates.items():
        setattr(conn, attr, value)


def _connector_owner(a: PortUsage, b: PortUsage) -> Optional[Element]:
    ca, cb = owning_component(a), owning_component(b)
    if ca is None or cb is None:
        return None

    def wires(comp: Element, holder: Element) -> bool:
        return holder is comp or holder is definition_of(comp) or holder in components_of(comp) \
            or any(definition_of(c) is holder for c in components_of(comp))

    for cand in (ca.owner, ca, cb.owner, cb):
        if isinstance(cand, (PartDefinition, PartUsage)) and wires(cand, ca) and wires(cand, cb):
            return cand
    return ca.owner if isinstance(ca.owner, Namespace) else None


def connect_ports(repo, source: Element, target: Element, *, name: Optional[str] = None,
                  parent: Optional[Element] = None, source_element: Optional[str] = None,
                  target_element: Optional[str] = None) -> ConnectionUsage:
    """Create a connector source -> target (optionally selecting bus elements)."""
    for p, what in ((source, "source"), (target, "target")):
        if not isinstance(p, PortUsage):
            raise InterfaceError(f"The connector {what} must be a port")
    if source is target:
        raise InterfaceError("Cannot connect a port to itself")
    owner = parent or _connector_owner(source, target) or repo.root_package
    if not isinstance(owner, Namespace):
        raise InterfaceError("Connector parent must be a component or architecture")
    # Connector creation and its System Composer rules (direction, single driver,
    # port kinds, usage context) belong to the architecture engine.
    from . import architecture as A

    def endpoint(port: PortUsage) -> dict:
        comp = owning_component(port)
        if comp is owner:
            return {"component": None, "port": port}
        if isinstance(comp, PartDefinition):
            # A definition port is reached through the usage of that definition here.
            comp = next((u for u in components_of(owner) if definition_of(u) is comp), comp)
        return {"component": comp, "port": port}

    try:
        conn = A.connect(repo, owner, endpoint(source), endpoint(target), name)
    except A.ArchitectureError as ex:
        raise InterfaceError(str(ex)) from None
    conn.source_element = getattr(conn, "source_element", None)
    conn.target_element = getattr(conn, "target_element", None)
    if source_element or target_element:
        set_connector_elements(conn, source_element or None, target_element or None)
    return conn


def connect_candidates(port: PortUsage) -> list[PortUsage]:
    """Ports a port can sensibly be wired to (siblings, parent boundary, children)."""
    comp = owning_component(port)
    if comp is None:
        return []
    out: list[PortUsage] = []
    scopes = []
    if isinstance(comp.owner, (PartDefinition, PartUsage)):
        scopes.append(comp.owner)
    scopes.append(comp)
    for scope in scopes:
        out += [p for p in ports_of(scope) if p is not port]
        for child in components_of(scope):
            out += [p for p in ports_of(child) if p is not port]
    seen: set[int] = set()
    uniq = []
    for p in out:
        if id(p) not in seen and owning_component(p) is not comp:
            seen.add(id(p))
            uniq.append(p)
    return uniq


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def create_adapter(repo, parent: Element, name: Optional[str] = None) -> Adapter:
    """Create an Adapter component (with In / Out ports) inside a composition."""
    if not isinstance(parent, (PartDefinition, PartUsage)):
        raise InterfaceError("An adapter must be created inside an architecture or component")
    nm = name or _unique_name(parent, "Adapter", 1, always_number=False)
    _check_name(nm, "Adapter name")
    if _sibling(parent, nm) is not None:
        raise InterfaceError(f"An element named {nm!r} already exists in {parent.name!r}", 409)
    a = Adapter(name=nm)
    parent.own(a)
    notify_created(a, repo)
    return a


def _ensure_adapter_ports(a: Adapter, repo) -> None:
    if any(isinstance(c, PortUsage) for c in a.children):
        return
    for pname, direction in (("In", FeatureDirection.IN), ("Out", FeatureDirection.OUT)):
        p = PortUsage(name=pname, direction=direction)
        a.own(p)
        notify_created(p, repo)


def set_adapter_mappings(adapter: Element, mappings: Any) -> list[dict]:
    if not isinstance(adapter, Adapter):
        raise InterfaceError(f"{getattr(adapter, 'name', adapter)!r} is not an adapter")
    if not isinstance(mappings, list):
        raise InterfaceError("mappings must be a list of {target, source, note}")
    clean: list[dict] = []
    seen: set[str] = set()
    for m in mappings:
        if not isinstance(m, dict):
            raise InterfaceError("each mapping must be an object {target, source, note}")
        tgt, src = str(m.get("target") or "").strip(), str(m.get("source") or "").strip()
        if not tgt or not src:
            raise InterfaceError("each mapping needs a target element and a source element")
        for p in tgt.split(".") + src.split("."):
            _check_name(p, "Element name")
        if tgt in seen:
            raise InterfaceError(f"Output element {tgt!r} is mapped twice")
        seen.add(tgt)
        clean.append({"target": tgt, "source": src, "note": str(m.get("note") or "")})
    adapter.mappings = clean
    return clean


def _adapter_ports(a: Adapter) -> tuple[list[PortUsage], list[PortUsage]]:
    ports = ports_of(a)
    ins = [p for p in ports if p.direction == FeatureDirection.IN]
    outs = [p for p in ports if p.direction != FeatureDirection.IN]
    return ins, outs


def _peer_interface(port: PortUsage) -> Optional[Element]:
    """Interface of the port wired to `port` (for an adapter port without its own)."""
    comp = owning_component(port)
    scope = comp.owner if comp is not None else None
    if scope is None:
        return None
    for c in connectors_of(scope):
        if port in c.ends:
            for other in c.ends:
                if other is not port and interface_of(other) is not None:
                    return interface_of(other)
    return None


def adapter_input_interfaces(a: Adapter) -> dict[str, Optional[Element]]:
    ins, _ = _adapter_ports(a)
    return {p.name: interface_of(p) or _peer_interface(p) for p in ins}


def adapter_output_interface(a: Adapter) -> Optional[Element]:
    _, outs = _adapter_ports(a)
    for p in outs:
        iface = interface_of(p) or _peer_interface(p)
        if iface is not None:
            return iface
    return None


def _resolve_adapter_source(inputs: dict[str, Optional[Element]], path: str) -> Optional[Element]:
    parts = path.split(".")
    if len(parts) > 1 and parts[0] in inputs and inputs[parts[0]] is not None:
        hit = find_element(inputs[parts[0]], ".".join(parts[1:]))
        if hit is not None:
            return hit
    for iface in inputs.values():
        if iface is not None:
            hit = find_element(iface, path)
            if hit is not None:
                return hit
    return None


def _adapter_reasons(a: Adapter, out_iface: Optional[Element]) -> list[str]:
    if out_iface is None:
        return []
    shape = _shape(out_iface)
    if shape.kind != "data-bus":
        return []
    inputs = adapter_input_interfaces(a)
    by_target = {m["target"]: m for m in a.mappings}
    reasons: list[str] = []
    for el in elements_of(out_iface):
        m = by_target.get(el.name)
        label = f"adapter {a.name!r} output element {el.name!r}"
        if m is not None:
            src = _resolve_adapter_source(inputs, m["source"])
            if src is None:
                reasons.append(f"{label}: mapped from {m['source']!r}, which is not in the adapter input")
                continue
            reasons += _compare_shapes(_shape(src), _shape(el), label,
                                       allow_unit_conversion=bool(m.get("note")))
        else:
            src = _resolve_adapter_source(inputs, el.name)
            if src is None:
                reasons.append(f"{label} has no mapping and no same-named input element")
            else:
                reasons += _compare_shapes(_shape(src), _shape(el), label)
    known = {e.name for e in elements_of(out_iface)}
    for m in a.mappings:
        if m["target"] not in known:
            reasons.append(f"adapter {a.name!r} maps {m['target']!r}, which is not an output element")
    return reasons


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------

@dataclass
class _Leaf:
    type: str
    units: str = ""
    dims: tuple = (1,)
    complexity: str = "real"
    enum: Optional[Element] = None


@dataclass
class _Shape:
    kind: str                     # data-bus | leaf | physical-bus | physical-leaf | service-bus | function | empty
    iface: Optional[Element] = None
    leaf: Optional[_Leaf] = None
    element: Optional[Element] = None
    label: str = ""


_KIND_TEXT = {"data-bus": "a data interface", "leaf": "a signal element",
              "physical-bus": "a physical interface", "physical-leaf": "a physical element",
              "service-bus": "a service interface", "function": "a function element"}


def _leaf_of(el: Element) -> _Leaf:
    t = _model_type(el) if isinstance(el, Feature) else None
    if isinstance(t, ValueType):
        return _Leaf(t.base_type, t.units, _safe_dims(t.dimensions), t.complexity)
    if isinstance(t, EnumerationDefinition):
        return _Leaf(f"Enum: {t.name}", "", _safe_dims(getattr(el, "dimensions", "1")), "real", t)
    if isinstance(el, DataElement):
        return _Leaf(el.primitive_type or describe_type(el), el.units, _safe_dims(el.dimensions),
                     el.complexity)
    if isinstance(el, ValueType):
        return _Leaf(el.base_type, el.units, _safe_dims(el.dimensions), el.complexity)
    if isinstance(el, EnumerationDefinition):
        return _Leaf(f"Enum: {el.name}", "", (1,), "real", el)
    return _Leaf(describe_type(el) if isinstance(el, Feature) else (el.name or "?"))


def _shape(thing: Element) -> _Shape:
    if isinstance(thing, PhysicalInterface):
        return _Shape("physical-bus", iface=thing, label=thing.name or "")
    if isinstance(thing, ServiceInterface):
        return _Shape("service-bus", iface=thing, label=thing.name or "")
    if isinstance(thing, PortDefinition):
        return _Shape("data-bus", iface=thing, label=thing.name or "")
    if isinstance(thing, (ValueType, EnumerationDefinition)):
        return _Shape("leaf", leaf=_leaf_of(thing), label=thing.name or "")
    if isinstance(thing, PhysicalElement):
        return _Shape("physical-leaf", element=thing, label=thing.name or "")
    if isinstance(thing, FunctionElement):
        return _Shape("function", element=thing, label=thing.name or "")
    if isinstance(thing, Feature):
        t = _model_type(thing)
        if isinstance(t, PortDefinition) and not isinstance(t, (PhysicalInterface, ServiceInterface)):
            return _Shape("data-bus", iface=t, element=thing, label=thing.name or "")
        return _Shape("leaf", leaf=_leaf_of(thing), element=thing, label=thing.name or "")
    return _Shape("empty")


def _same_enum(a: Optional[Element], b: Optional[Element]) -> bool:
    if a is b:
        return True
    if a is None or b is None:
        return False
    la = [(c.name, c.default_value) for c in elements_of(a)]
    lb = [(c.name, c.default_value) for c in elements_of(b)]
    return la == lb


def _compare_leaf(a: _Leaf, b: _Leaf, label: str, allow_unit_conversion: bool = False) -> list[str]:
    out = []
    if a.enum is not None or b.enum is not None:
        if not _same_enum(a.enum, b.enum):
            out.append(f"{label}: type {a.type} vs {b.type}")
    elif a.type != b.type:
        out.append(f"{label}: type {a.type} vs {b.type}")
    if a.dims != b.dims:
        fa = "?" if a.dims == (-1,) else format_dimensions(a.dims)
        fb = "?" if b.dims == (-1,) else format_dimensions(b.dims)
        out.append(f"{label}: dimensions {fa} vs {fb}")
    ua, ub = re.sub(r"\s+", "", a.units or ""), re.sub(r"\s+", "", b.units or "")
    if ua != ub and not allow_unit_conversion:
        out.append(f"{label}: units {a.units or '(none)'} vs {b.units or '(none)'}")
    if a.complexity != b.complexity and "auto" not in (a.complexity, b.complexity):
        out.append(f"{label}: complexity {a.complexity} vs {b.complexity}")
    return out


def _compare_data(a: Element, b: Element, prefix: str, seen: set) -> list[str]:
    if a is b:
        return []
    key = (id(a), id(b))
    if key in seen:
        return []
    seen.add(key)
    ea = {e.name: e for e in elements_of(a)}
    eb = {e.name: e for e in elements_of(b)}
    out = []
    for n in ea:
        if n not in eb:
            out.append(f"element '{prefix}{n}' is in {a.name!r} but not in {b.name!r}")
    for n in eb:
        if n not in ea:
            out.append(f"element '{prefix}{n}' is in {b.name!r} but not in {a.name!r}")
    for n in ea:
        if n in eb:
            sa, sb = _shape(ea[n]), _shape(eb[n])
            label = f"element '{prefix}{n}'"
            if sa.kind != sb.kind:
                out.append(f"{label}: {_KIND_TEXT.get(sa.kind, sa.kind)} vs {_KIND_TEXT.get(sb.kind, sb.kind)}")
            elif sa.kind == "data-bus":
                out += _compare_data(sa.iface, sb.iface, f"{prefix}{n}.", seen)
            else:
                out += _compare_leaf(sa.leaf, sb.leaf, label)
    return out


def _compare_physical(a: Element, b: Element) -> list[str]:
    if a is b:
        return []
    ea = {e.name: e for e in elements_of(a)}
    eb = {e.name: e for e in elements_of(b)}
    out = [f"physical element {n!r} is in {a.name!r} but not in {b.name!r}" for n in ea if n not in eb]
    out += [f"physical element {n!r} is in {b.name!r} but not in {a.name!r}" for n in eb if n not in ea]
    for n in ea:
        if n in eb and ea[n].domain != eb[n].domain:
            out.append(f"physical element {n!r}: domain {ea[n].domain} vs {eb[n].domain}")
    return out


def _compare_function(c: FunctionElement, s: FunctionElement, label: str) -> list[str]:
    out = []
    if _norm_proto(c.prototype) != _norm_proto(s.prototype):
        out.append(f"{label}: prototype {c.prototype!r} vs {s.prototype!r}")
    elif c.asynchronous != s.asynchronous:
        out.append(f"{label}: asynchronous {str(c.asynchronous).lower()} vs {str(s.asynchronous).lower()}")
    else:
        sa = {a["name"]: a for a in s.arguments}
        for arg in c.arguments:
            other = sa.get(arg["name"])
            if other is None:
                continue
            for key in ("type", "dimensions", "units"):
                if str(arg.get(key) or "") != str(other.get(key) or ""):
                    out.append(f"{label}: argument {arg['name']!r} {key} "
                               f"{arg.get(key) or '(none)'} vs {other.get(key) or '(none)'}")
    return out


def service_role(port: Element) -> Optional[str]:
    """'client' for an out port, 'server' for an in port, else None."""
    d = getattr(port, "direction", None)
    if d == FeatureDirection.OUT:
        return "client"
    if d == FeatureDirection.IN:
        return "server"
    return None


def _compare_service(a: Element, b: Element, role_a: Optional[str], role_b: Optional[str]) -> list[str]:
    out = []
    if role_a and role_b and role_a == role_b:
        return [f"both ports are {role_a}s; connect a client (out) port to a server (in) port"]
    if role_a == "server" or role_b == "client":
        a, b = b, a
        role_a, role_b = role_b, role_a
    if a is b:
        return []
    fa = {e.name: e for e in elements_of(a)}
    fb = {e.name: e for e in elements_of(b)}
    for n, f in fa.items():
        if n not in fb:
            out.append(f"function {n!r} required by {a.name!r} is not provided by {b.name!r}")
        else:
            out += _compare_function(f, fb[n], f"function {n!r}")
    if not (role_a and role_b):
        out += [f"function {n!r} is in {b.name!r} but not in {a.name!r}" for n in fb if n not in fa]
    return out


def _compare_shapes(sa: _Shape, sb: _Shape, label: str = "selected elements", *,
                    roles: tuple = (None, None), allow_unit_conversion: bool = False) -> list[str]:
    if sa.kind == "empty" or sb.kind == "empty":
        return []
    if sa.kind != sb.kind:
        return [f"{_KIND_TEXT.get(sa.kind, sa.kind)} ({sa.label}) cannot connect to "
                f"{_KIND_TEXT.get(sb.kind, sb.kind)} ({sb.label})"]
    if sa.kind == "data-bus":
        return _compare_data(sa.iface, sb.iface, "", set())
    if sa.kind == "leaf":
        return _compare_leaf(sa.leaf, sb.leaf, label, allow_unit_conversion)
    if sa.kind == "physical-bus":
        return _compare_physical(sa.iface, sb.iface)
    if sa.kind == "physical-leaf":
        if sa.element.domain != sb.element.domain:
            return [f"{label}: domain {sa.element.domain} vs {sb.element.domain}"]
        return []
    if sa.kind == "service-bus":
        return _compare_service(sa.iface, sb.iface, *roles)
    if sa.kind == "function":
        return _compare_function(sa.element, sb.element, label)
    return []


def _end_shape(port: PortUsage, path: Optional[str]) -> tuple[Optional[_Shape], list[str]]:
    iface = interface_of(port)
    if not path:
        return (_shape(iface) if iface is not None else _Shape("empty")), []
    if iface is None:
        return None, [f"port {port.name!r} has no interface, so element {path!r} cannot be selected"]
    el = find_element(iface, path)
    if el is None:
        return None, [f"interface {iface.name!r} of port {port.name!r} has no element {path!r}"]
    return _shape(el), []


def check_compatibility(source_port: Element, target_port: Element,
                        source_element: Optional[str] = None,
                        target_element: Optional[str] = None) -> list[str]:
    """Reasons why a connector source -> target is incompatible (empty when compatible).

    Ports are compatible when they share the interface, or when the interfaces
    (or the selected bus elements) are structurally compatible: same element
    names, types, units, dimensions and complexity, recursively for nested
    interfaces. A port without an interface is compatible with anything.
    Physical elements must share a domain; service ports must connect a client
    to a server whose functions have matching prototypes. A connector to an
    adapter's output checks the adapter's element mappings instead.
    """
    for p, what in ((source_port, "source"), (target_port, "target")):
        if not isinstance(p, PortUsage):
            return [f"the {what} end is not a port"]
    reasons: list[str] = []
    sa, ra = _end_shape(source_port, source_element)
    sb, rb = _end_shape(target_port, target_element)
    reasons += ra + rb
    if sa is None or sb is None:
        return reasons
    for port, other, other_path in ((source_port, target_port, target_element),
                                    (target_port, source_port, source_element)):
        adapter = port.owner if isinstance(port.owner, Adapter) else None
        if adapter is None or port.direction == FeatureDirection.IN:
            continue
        out_iface = interface_of(port) or (find_element(interface_of(other), other_path)
                                           if other_path else interface_of(other))
        if isinstance(out_iface, Feature):
            out_iface = _model_type(out_iface)
        extra = _adapter_reasons(adapter, out_iface if isinstance(out_iface, PortDefinition) else None)
        if interface_of(port) is None:
            return reasons + extra
        reasons += extra
    for port in (source_port, target_port):
        if isinstance(port.owner, Adapter) and port.direction == FeatureDirection.IN \
                and interface_of(port) is None:
            return reasons
    label = (f"'{source_element or source_port.name}' vs '{target_element or target_port.name}'"
             if source_element or target_element else "port types")
    return reasons + _compare_shapes(sa, sb, label,
                                     roles=(service_role(source_port), service_role(target_port)))


def connector_compatibility(conn: ConnectionUsage) -> Optional[list[str]]:
    """Reasons for a connector between two ports, or None when it is not port-to-port."""
    if not isinstance(conn, ConnectionUsage) or len(conn.ends) < 2:
        return None
    src, tgt = conn.ends[0], conn.ends[1]
    if not isinstance(src, PortUsage) or not isinstance(tgt, PortUsage):
        return None
    return check_compatibility(src, tgt, getattr(conn, "source_element", None),
                               getattr(conn, "target_element", None))


def require_port_connector(conn: Any) -> ConnectionUsage:
    """`conn` when it is a connector joining two ports, else InterfaceError."""
    if not isinstance(conn, ConnectionUsage):
        raise InterfaceError(f"{getattr(conn, 'qualified_name', conn)!r} is not a connector")
    if len(conn.ends) < 2 or not all(isinstance(p, PortUsage) for p in conn.ends[:2]):
        raise InterfaceError(f"Connector {conn.name!r} does not join two ports")
    return conn


def connector_report(conn: Any) -> dict:
    """``compatibility_report`` for an existing port-to-port connector."""
    c = require_port_connector(conn)
    report = compatibility_report(c.ends[0], c.ends[1], getattr(c, "source_element", None),
                                  getattr(c, "target_element", None))
    report["connector"] = {"id": c.element_id, "name": c.name}
    return report


def port_label(port: Element) -> str:
    comp = owning_component(port) if isinstance(port, PortUsage) else None
    base = f"{comp.name}.{port.name}" if comp is not None and comp.name else (port.name or "?")
    iface = interface_of(port)
    return f"{base} ({iface.name if iface is not None else 'no interface'})"


# ---------------------------------------------------------------------------
# Describing (shared by the web API, MCP tools and summaries)
# ---------------------------------------------------------------------------

def describe_element(el: Element) -> dict:
    d: dict[str, Any] = {"id": el.element_id, "name": el.name, "kind": el.kind,
                         "description": _doc(el)}
    if isinstance(el, DataElement):
        t = _model_type(el)
        leaf = _leaf_of(el)
        d.update({
            "type": describe_type(el),
            "type_kind": ("value_type" if isinstance(t, ValueType) else
                          "interface" if isinstance(t, PortDefinition) else
                          "enum" if isinstance(t, EnumerationDefinition) else "primitive"),
            "type_id": t.element_id if t is not None else None,
            "dimensions": el.dimensions, "units": el.units, "complexity": el.complexity,
            "minimum": el.minimum, "maximum": el.maximum,
            "effective": {"type": leaf.type, "units": leaf.units,
                          "dimensions": el.dimensions if not isinstance(t, ValueType) else t.dimensions,
                          "complexity": leaf.complexity,
                          "minimum": t.minimum if isinstance(t, ValueType) else el.minimum,
                          "maximum": t.maximum if isinstance(t, ValueType) else el.maximum},
        })
        units = d["effective"]["units"]
        problem = unit_problem(units)
        if problem:
            d["units_warning"] = problem
    elif isinstance(el, PhysicalElement):
        d["domain"] = el.domain
    elif isinstance(el, FunctionElement):
        d.update({"prototype": el.prototype, "asynchronous": el.asynchronous,
                  "arguments": [dict(a) for a in el.arguments]})
    elif isinstance(el, EnumerationUsage):
        d.update({"kind": "EnumerationLiteral", "value": el.default_value})
    elif isinstance(el, Feature):
        d["type"] = describe_type(el)
    return d


def describe_item(e: Element, repo=None, *, detail: bool = False) -> dict:
    owned = is_owned(e)
    d: dict[str, Any] = {
        "id": e.element_id, "name": e.name, "kind": item_kind(e) or e.kind,
        "qualified_name": e.qualified_name, "description": _doc(e),
        "color": getattr(e, "color", None), "owned": owned,
        "location": e.owner.qualified_name if e.owner is not None else None,
        "element_count": len(elements_of(e)),
    }
    if owned:
        d["owner_port"] = {"id": e.owner.element_id, "name": e.owner.name,
                           "qualified_name": e.owner.qualified_name}
    if isinstance(e, ValueType):
        d.update({"base_type": e.base_type, "units": e.units, "dimensions": e.dimensions,
                  "complexity": e.complexity, "minimum": e.minimum, "maximum": e.maximum})
        problem = unit_problem(e.units)
        if problem:
            d["units_warning"] = problem
    if isinstance(e, NamedConstant):
        d.update({"value": e.value, "type": e.primitive_type or describe_type(e), "units": e.units})
    if isinstance(e, EnumerationDefinition):
        d["default"] = e.tool_data.get("default_literal")
    if detail:
        d["elements"] = [describe_element(c) for c in elements_of(e)]
        if repo is not None:
            d["ports"] = [{"id": p.element_id, "name": p.name, "qualified_name": p.qualified_name,
                           "component": (owning_component(p).name if owning_component(p) else None),
                           "direction": p.direction.value}
                          for p in ports_using(repo, e)]
            d["used_by"] = [{"id": u.element_id, "name": u.name, "qualified_name": u.qualified_name,
                             "interface": u.owner.name if u.owner is not None else None}
                            for u in elements_using(repo, e)]
    return d


def list_dictionary(repo) -> dict:
    dic = get_dictionary(repo, create=False)
    return {
        "dictionary": ({"id": dic.element_id, "name": dic.name, "qualified_name": dic.qualified_name}
                       if dic is not None else None),
        "items": [describe_item(e) for e in shared_items(repo)],
        "owned": [describe_item(e) for e in owned_interfaces(repo)],
        "port_definitions": [describe_item(e) for e in plain_port_definitions(repo)],
    }


def metadata() -> dict:
    return {
        "primitive_types": list(PRIMITIVE_TYPES), "complexities": list(COMPLEXITIES),
        "physical_domains": [{"id": k, "label": v} for k, v in PHYSICAL_DOMAINS.items()],
        "units": list(KNOWN_UNITS), "palette": list(PALETTE),
        "templates": [{"id": k, "label": v["label"], "kind": v["kind"]} for k, v in TEMPLATES.items()],
        "item_kinds": list(ITEM_KINDS), "fields": {k: list(v) for k, v in FIELDS.items()},
    }


def port_info(repo, port: PortUsage) -> dict:
    iface = interface_of(port)
    conns = []
    for c in repo.root_package.walk():
        if isinstance(c, ConnectionUsage) and port in c.ends:
            reasons = connector_compatibility(c)
            other = next((x for x in c.ends if x is not port), None)
            conns.append({"id": c.element_id, "name": c.name,
                          "other": port_label(other) if other is not None else None,
                          "other_id": other.element_id if other is not None else None,
                          "compatible": not reasons, "reasons": reasons or []})
    return {
        "port": {"id": port.element_id, "name": port.name, "qualified_name": port.qualified_name,
                 "direction": port.direction.value, "role": service_role(port)},
        "interface": describe_item(iface, repo, detail=True) if iface is not None else None,
        "element_paths": element_paths(iface),
        "connectors": conns,
    }


def compatibility_report(source: PortUsage, target: PortUsage, source_element: Optional[str] = None,
                         target_element: Optional[str] = None) -> dict:
    reasons = check_compatibility(source, target, source_element, target_element)

    def end(p: Element, path: Optional[str]) -> dict:
        iface = interface_of(p) if isinstance(p, PortUsage) else None
        return {"id": p.element_id, "name": p.name, "label": port_label(p),
                "interface": ({"id": iface.element_id, "name": iface.name, "kind": item_kind(iface),
                               "color": getattr(iface, "color", None), "owned": is_owned(iface)}
                              if iface is not None else None),
                "element": path or None, "element_paths": element_paths(iface)}

    return {"compatible": not reasons, "reasons": reasons,
            "source": end(source, source_element), "target": end(target, target_element)}


# ---------------------------------------------------------------------------
# Dictionary export / import
# ---------------------------------------------------------------------------

def _element_to_json(el: Element) -> dict:
    d = describe_element(el)
    out = {"name": d["name"], "description": d["description"]}
    if isinstance(el, DataElement):
        out.update({k: d[k] for k in ("type", "dimensions", "units", "complexity", "minimum", "maximum")})
    elif isinstance(el, PhysicalElement):
        out["domain"] = el.domain
    elif isinstance(el, FunctionElement):
        out.update({"prototype": el.prototype, "asynchronous": el.asynchronous,
                    "arguments": [dict(a) for a in el.arguments]})
    elif isinstance(el, EnumerationUsage):
        out["value"] = el.default_value
    return out


def _item_to_json(e: Element) -> dict:
    kind = item_kind(e)
    out: dict[str, Any] = {"kind": kind, "name": e.name, "description": _doc(e)}
    if isinstance(e, (*INTERFACE_CLASSES, ValueType)):
        out["color"] = e.color
    if isinstance(e, ValueType):
        out.update({"base_type": e.base_type, "units": e.units, "dimensions": e.dimensions,
                    "complexity": e.complexity, "minimum": e.minimum, "maximum": e.maximum})
    elif isinstance(e, NamedConstant):
        out.update({"value": e.value, "type": e.primitive_type or "double", "units": e.units})
    elif isinstance(e, EnumerationDefinition):
        out["literals"] = [_element_to_json(c) for c in elements_of(e)]
        out["default"] = e.tool_data.get("default_literal")
    else:
        out["elements"] = [_element_to_json(c) for c in elements_of(e)]
    return out


def export_dictionary(repo) -> dict:
    """The interface dictionary as a standalone JSON-able document."""
    dic = get_dictionary(repo, create=False)
    items = [c for c in (dic.children if dic is not None else []) if item_kind(c) in ITEM_KINDS]
    order = {k: i for i, k in enumerate(("ValueType", "Enumeration", "Constant", "DataInterface",
                                         "PhysicalInterface", "ServiceInterface"))}
    items.sort(key=lambda e: order.get(item_kind(e) or "", 99))
    return {"format": EXPORT_FORMAT, "name": dic.name if dic is not None else DICTIONARY_NAME,
            "source_project": repo.name, "items": [_item_to_json(e) for e in items]}


def _validate_import(data: Any) -> list[dict]:
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except ValueError as ex:
            raise InterfaceError(f"Dictionary file is not valid JSON: {ex}") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise InterfaceError("Dictionary file must be a JSON object with an 'items' list "
                             f"(format {EXPORT_FORMAT!r})")
    fmt = data.get("format")
    if fmt is not None and fmt != EXPORT_FORMAT:
        raise InterfaceError(f"Unsupported dictionary format {fmt!r}; expected {EXPORT_FORMAT!r}")
    items = []
    names: set[str] = set()
    for i, raw in enumerate(data["items"]):
        if not isinstance(raw, dict):
            raise InterfaceError(f"Dictionary item #{i + 1} must be an object")
        kind = _normalize_item_kind(str(raw.get("kind") or ""))
        name = _check_name(raw.get("name"), f"Dictionary item #{i + 1} name")
        if name in names:
            raise InterfaceError(f"Dictionary file defines {name!r} twice")
        names.add(name)
        for key in ("elements", "literals", "arguments"):
            if key in raw and not isinstance(raw[key], list):
                raise InterfaceError(f"{name!r}: {key} must be a list")
        items.append({**raw, "kind": kind})
    return items


def import_preview(repo, data: Any) -> dict:
    items = _validate_import(data)
    dic = get_dictionary(repo, create=False)
    collisions = []
    for it in items:
        existing = _sibling(dic, it["name"]) if dic is not None else None
        if existing is not None:
            collisions.append({"name": it["name"], "incoming_kind": it["kind"],
                               "existing_kind": item_kind(existing) or existing.kind,
                               "suggested_rename": _unique_rename(dic, it["name"])})
    return {"items": [{"name": it["name"], "kind": it["kind"]} for it in items],
            "collisions": collisions}


def import_dictionary(repo, data: Any, *, default: str = "error",
                      resolution: Optional[dict] = None, dry_run: bool = False) -> dict:
    """Merge a dictionary document into the project's dictionary.

    Name collisions are resolved per item by ``resolution[name]`` or else
    ``default``: ``"keep"`` (keep the existing item; references in the file
    point to it), ``"replace"`` (overwrite it in place so ports keep their
    assignment), ``"rename"`` (import as ``name_1``...), or ``"error"``.
    The import is all-or-nothing: it is rehearsed on a copy first.
    """
    preview = import_preview(repo, data)
    if dry_run:
        return {"dry_run": True, **preview}
    choices = dict(resolution or {})
    for k, v in list(choices.items()) + [("<default>", default)]:
        if v not in ("error", "keep", "replace", "rename"):
            raise InterfaceError(f"Invalid choice {v!r} for {k!r}: use keep, replace or rename")
    unresolved = [c["name"] for c in preview["collisions"]
                  if choices.get(c["name"], default) == "error"]
    if unresolved:
        raise InterfaceError(
            f"{len(unresolved)} item(s) already exist in the dictionary: {', '.join(unresolved)}; "
            f"choose keep, replace or rename for each", 409)
    items = _validate_import(data)
    from .serializer import from_dict, to_dict
    rehearsal = from_dict(to_dict(repo))
    _apply_import(rehearsal, items, choices, default)
    cycles = [i for i in _cycle_issues(rehearsal)]
    if cycles:
        raise InterfaceError(f"Import would create nested interface cycles: {cycles[0].message}")
    return _apply_import(repo, items, choices, default)


def _apply_import(repo, items: list[dict], choices: dict, default: str) -> dict:
    dic = get_dictionary(repo)
    report: dict[str, Any] = {"added": [], "replaced": [], "renamed": {}, "kept": []}
    name_map: dict[str, Element] = {}
    fill: list[tuple[dict, Element]] = []
    deferred_removals: list[tuple[Element, Element, str]] = []
    for it in items:
        name = it["name"]
        existing = _sibling(dic, name)
        choice = choices.get(name, default) if existing is not None else "add"
        cls = _ITEM_CLASS[it["kind"]]
        if choice == "keep":
            name_map[name] = existing
            report["kept"].append(name)
            continue
        if choice == "replace" and type(existing) is cls:
            for el in list(elements_of(existing)):
                repo.remove(el)
            name_map[name] = existing
            fill.append((it, existing))
            report["replaced"].append(name)
            continue
        if choice == "replace":
            tmp = _unique_rename(dic, f"{name}_import")
            new = create_item(repo, it["kind"], tmp)
            deferred_removals.append((existing, new, name))
            name_map[name] = new
            fill.append((it, new))
            report["replaced"].append(name)
            continue
        final = _unique_rename(dic, name) if choice == "rename" else name
        new = create_item(repo, it["kind"], final)
        if final != name:
            report["renamed"][name] = final
        else:
            report["added"].append(name)
        name_map[name] = new
        fill.append((it, new))
    for old, new, name in deferred_removals:
        for p in ports_using(repo, old):
            _set_typing(p, new)
        for u in elements_using(repo, old):
            _set_typing(u, new)
        repo.remove(old)
        new.name = name
    for it, item in fill:
        _fill_item(repo, item, it, name_map)
    return report


def _fill_item(repo, item: Element, it: dict, name_map: dict) -> None:
    fields: dict[str, Any] = {"description": it.get("description") or ""}
    if isinstance(item, (*INTERFACE_CLASSES, ValueType)) and it.get("color"):
        fields["color"] = it["color"]
    if isinstance(item, ValueType):
        for k in ("base_type", "units", "dimensions", "complexity", "minimum", "maximum"):
            if k in it:
                fields[k] = it[k]
    if isinstance(item, NamedConstant):
        for k in ("value", "type", "units"):
            if k in it:
                fields[k] = it[k]
    set_fields(repo, item, fields)
    specs = it.get("literals") if isinstance(item, EnumerationDefinition) else it.get("elements")
    for spec in specs or []:
        if not isinstance(spec, dict):
            raise InterfaceError(f"{item.name!r}: each element must be an object")
        spec = dict(spec)
        name = spec.pop("name", None)
        type_spec = spec.pop("type", None) if isinstance(item, DataInterface) else None
        allowed = set(_fields_for_class(_element_class(item)))
        clean = {k: v for k, v in spec.items() if k in allowed and k != "name"}
        el = add_element(repo, item, name, **clean)
        if type_spec is not None:
            _apply_type(repo, el, type_spec, None, name_map)
    if isinstance(item, EnumerationDefinition) and it.get("default"):
        set_fields(repo, item, {"default": it["default"]})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _cycle_issues(repo) -> Iterator[ValidationIssue]:
    reported: set[frozenset] = set()
    for e in repo.root_package.walk():
        if not isinstance(e, PortDefinition):
            continue
        for el in elements_of(e):
            t = _model_type(el) if isinstance(el, Feature) else None
            if not isinstance(t, PortDefinition):
                continue
            path = _nesting_path(t, e)
            if path is None:
                continue
            key = frozenset(id(p) for p in path)
            if key in reported:
                continue
            reported.add(key)
            chain = " -> ".join(p.name or "?" for p in [e] + path)
            yield ValidationIssue(Severity.ERROR, "interfaces.cycle",
                                  f"Nested interfaces form a cycle: {chain}", e)


def validate_repo(repo) -> Iterator[ValidationIssue]:
    yield from _cycle_issues(repo)
    for e in repo.root_package.walk():
        if isinstance(e, ConnectionUsage):
            reasons = connector_compatibility(e)
            if reasons:
                src, tgt = e.ends[0], e.ends[1]
                yield ValidationIssue(
                    Severity.ERROR, "interfaces.compatibility",
                    f"Connector {e.name!r} from {port_label(src)} to {port_label(tgt)} is "
                    f"incompatible: {'; '.join(reasons)}", e)
            continue
        if isinstance(e, (DataElement, ValueType, NamedConstant)):
            problem = unit_problem(getattr(e, "units", ""))
            if problem:
                yield ValidationIssue(Severity.WARNING, "interfaces.units", problem.capitalize(), e)
        if isinstance(e, (DataElement, ValueType)):
            try:
                parse_dimensions(e.dimensions)
            except InterfaceError as ex:
                yield ValidationIssue(Severity.ERROR, "interfaces.dimensions", str(ex), e)
            lo, hi = e.minimum, e.maximum
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                yield ValidationIssue(Severity.ERROR, "interfaces.range",
                                      f"Minimum ({lo}) exceeds maximum ({hi})", e)
            if e.complexity not in COMPLEXITIES:
                yield ValidationIssue(Severity.ERROR, "interfaces.complexity",
                                      f"Complexity {e.complexity!r} is not one of {', '.join(COMPLEXITIES)}", e)
        if isinstance(e, (*ELEMENT_CLASSES, *INTERFACE_CLASSES, ValueType, NamedConstant)) \
                and e.name and not _NAME_RE.match(e.name):
            yield ValidationIssue(Severity.WARNING, "interfaces.name",
                                  f"{e.name!r} is not a valid identifier", e)
        if isinstance(e, FunctionElement):
            try:
                fname, _i, _o = parse_prototype(e.prototype)
                if fname != e.name:
                    yield ValidationIssue(Severity.ERROR, "interfaces.prototype",
                                          f"Prototype {e.prototype!r} does not name function {e.name!r}", e)
            except InterfaceError as ex:
                yield ValidationIssue(Severity.ERROR, "interfaces.prototype", str(ex), e)
        if isinstance(e, PhysicalElement) and e.domain not in PHYSICAL_DOMAINS:
            yield ValidationIssue(Severity.ERROR, "interfaces.domain",
                                  f"Unknown physical domain {e.domain!r}", e)


# ---------------------------------------------------------------------------
# Element JSON (summary hooks) and generic property edits
# ---------------------------------------------------------------------------

def summary_fields(e: Element, d: dict) -> None:
    """Add interface information, badges and style to an element summary.

    Follows the display contract: append to ``badges``, set keys in ``style``.
    """
    badges = d.setdefault("badges", [])
    style = d.setdefault("style", {})
    if isinstance(e, PortUsage):
        iface = interface_of(e)
        if iface is not None:
            owned = is_owned(iface)
            color = getattr(iface, "color", None)
            d["interface"] = {"id": iface.element_id, "name": iface.name, "kind": item_kind(iface),
                              "color": color, "owned": owned}
            badges.append("owned" if owned else (iface.name or "?"))
            if color:
                style["stroke"] = color
        else:
            d["interface"] = None
        if isinstance(e.owner, Adapter):
            d["adapter_port"] = True
        return
    kind = item_kind(e)
    if kind is not None and kind != "PortDefinition" or isinstance(e, INTERFACE_CLASSES):
        d["interface_category"] = "Interface" if kind in INTERFACE_KINDS else "DictionaryItem"
        d["interface_kind"] = kind
        d["owned"] = is_owned(e)
        color = getattr(e, "color", None)
        if color:
            d["color"] = color
            style["stroke"] = color
        if isinstance(e, ValueType):
            d.update({"base_type": e.base_type, "units": e.units, "dimensions": e.dimensions})
        return
    if isinstance(e, ELEMENT_CLASSES):
        d["interface_category"] = "InterfaceElement"
        info = describe_element(e)
        for k in ("type", "dimensions", "units", "complexity", "minimum", "maximum",
                  "domain", "prototype", "asynchronous"):
            if k in info:
                d[k] = info[k]
        return
    if isinstance(e, Adapter):
        badges.append("Adapter")
        style.setdefault("icon", "adapter")
        d["mappings"] = [dict(m) for m in e.mappings]
        return
    if isinstance(e, InterfaceDictionary):
        badges.append("dictionary")
        return
    if isinstance(e, ConnectionUsage):
        reasons = connector_compatibility(e)
        d["source_element"] = getattr(e, "source_element", None)
        d["target_element"] = getattr(e, "target_element", None)
        if reasons is None:
            return
        d["compatibility"] = {"compatible": not reasons, "reasons": reasons}
        if reasons:
            badges.append("incompatible")
            style["stroke"] = "#dc2626"
            style["dash"] = "6 3"
        else:
            src_iface = interface_of(e.ends[0])
            color = getattr(src_iface, "color", None) if src_iface is not None else None
            if color:
                style["stroke"] = color


_PROP_FIELDS = {"type", "dimensions", "units", "complexity", "minimum", "maximum", "domain",
                "prototype", "asynchronous", "arguments", "base_type", "color", "value",
                "default", "description"}


def handle_property(repo, e: Element, key: str, value: Any, resolve: Optional[Resolver]) -> bool:
    """Generic PATCH support: validate interface-related edits; True when handled.

    Raises InterfaceError for invalid values so the API answers 400 / 409.
    """
    if isinstance(e, PortUsage) and key == "typed_by":
        ref = value if isinstance(value, str) or value is None else (value[0] if value else None)
        if ref is None or ref.strip().lower() in ("", "<empty>", "owned", "<owned>"):
            assign_interface(repo, e, ref, resolve=resolve)
            return True
        current = interface_of(e)
        if current is not None and ref in (current.qualified_name, current.element_id):
            return True
        target = find_item(repo, ref, resolve, (PortDefinition, ValueType))
        if target is None:
            return False                # not an interface: the core handles other types
        assign_interface(repo, e, target, resolve=resolve)
        return True
    if isinstance(e, ConnectionUsage) and key in ("source_element", "target_element"):
        set_connector_elements(e, **{key: value})
        return True
    if isinstance(e, Adapter) and key == "mappings":
        set_adapter_mappings(e, value)
        return True
    allowed = fields_for(e)
    if not allowed or not (isinstance(e, (*ELEMENT_CLASSES, *ITEM_CLASSES))
                           or (isinstance(e, EnumerationUsage) and isinstance(e.owner, EnumerationDefinition))):
        return False
    if key == "typed_by" and isinstance(e, DataElement):
        ref = value if isinstance(value, str) or value is None else (value[0] if value else None)
        current = _model_type(e) or next(iter(e.types), None)
        if ref and current is not None and ref in (current.qualified_name, current.element_id):
            return True
        set_fields(repo, e, {"type": ref}, resolve)
        return True
    if key == "name" or (key in _PROP_FIELDS and key in allowed):
        if key == "name" and not value:
            raise InterfaceError("Interface items and elements need a name")
        set_fields(repo, e, {key: value}, resolve)
        return True
    return False


# ---------------------------------------------------------------------------
# Persistence, hooks and registration
# ---------------------------------------------------------------------------

_PERSISTED: tuple[tuple[type, tuple[str, ...]], ...] = (
    (DataElement, ("primitive_type", "dimensions", "units", "complexity", "minimum", "maximum")),
    (ValueType, ("base_type", "dimensions", "units", "complexity", "minimum", "maximum", "color")),
    (PhysicalElement, ("domain",)),
    (FunctionElement, ("prototype", "arguments", "asynchronous")),
    (NamedConstant, ("value", "primitive_type", "units")),
    (Adapter, ("mappings",)),
    (DataInterface, ("color",)),
    (PhysicalInterface, ("color",)),
    (ServiceInterface, ("color",)),
)


def _encode(e: Element) -> Optional[dict]:
    data: dict[str, Any] = {}
    for cls, attrs in _PERSISTED:
        if isinstance(e, cls):
            for a in attrs:
                v = getattr(e, a, None)
                data[a] = [dict(x) for x in v] if isinstance(v, list) else v
    if isinstance(e, (PortDefinition, EnumerationDefinition)) and not _in_library(e):
        kids = elements_of(e)
        if len(kids) > 1:
            data["order"] = [c.element_id for c in kids]
    if isinstance(e, ConnectionUsage):
        for a in ("source_element", "target_element"):
            if getattr(e, a, None):
                data[a] = getattr(e, a)
    return data or None


def _decode(e: Element, data: Any, by_id: dict) -> None:
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        if k == "order":
            ordered = [by_id[i] for i in v if i in by_id and by_id[i].owner is e]
            _reorder(e, ordered)
        else:
            setattr(e, k, v)
    if isinstance(e, (DataElement, NamedConstant)) and e.primitive_type and _model_type(e) is None:
        _type_primitive(e, e.primitive_type)
    if isinstance(e, (PhysicalElement, FunctionElement)):
        _type_attribute(e)


def _on_created(e: Element, repo) -> None:
    if isinstance(e, (DataElement, NamedConstant)) and e.primitive_type and not e.types:
        _type_primitive(e, e.primitive_type)
    if isinstance(e, (PhysicalElement, FunctionElement)):
        _type_attribute(e)
    if isinstance(e, (*INTERFACE_CLASSES, ValueType)) and not getattr(e, "color", None):
        e.color = next_color(repo)
    if isinstance(e, FunctionElement) and not e.prototype and e.name and _NAME_RE.match(e.name):
        e.prototype = f"y = {e.name}(u)"
        e.arguments = _coerce_arguments(None, ["u"], ["y"], [])
    if isinstance(e, EnumerationUsage) and isinstance(e.owner, EnumerationDefinition) and not e.types:
        e.add_type(e.owner)
    if isinstance(e, Adapter):
        _ensure_adapter_ports(e, repo)


def _on_removed(repo, removed: set[int]) -> None:
    for e in repo.root_package.walk():
        if id(e) in removed:
            continue
        if isinstance(e, DataElement) and not e.types:
            _type_primitive(e, e.primitive_type or "double")
        elif isinstance(e, EnumerationDefinition):
            d = e.tool_data.get("default_literal")
            if d and not any(c.name == d for c in elements_of(e)):
                e.tool_data.pop("default_literal", None)


def incompatibility_warnings(conn: Element) -> list[str]:
    """The canvas / port-edit warning about a connector whose interfaces are incompatible
    (``Incompatible interfaces AirDataWord → InertialData: element 'x' is missing …``)."""
    reasons = connector_compatibility(conn)
    if not reasons:
        return []
    names = [getattr(interface_of(p), "name", None) or "(none)" for p in conn.ends[:2]]
    return [f"Incompatible interfaces {names[0]} → {names[1]}: {'; '.join(reasons)}"]


_INSTALLED = False


def install() -> None:
    """Register codecs, hooks and validation rules (idempotent)."""
    global _INSTALLED
    from . import hooks, repository, validator
    register_codec("interfaces", _encode, _decode)          # replaces by name
    register_connector_warning_source(incompatibility_warnings)   # idempotent
    if validate_repo not in validator._REPO_RULES:
        register_repo_rule(validate_repo)
    if _on_created not in hooks._CREATED_HOOKS:
        register_created_hook(_on_created)
    if _on_removed not in repository._REMOVAL_HOOKS:
        register_removal_hook(_on_removed)
    if not _INSTALLED:
        for prop in ("minimum", "maximum"):
            register_scalar_property(prop)
        _INSTALLED = True


install()
