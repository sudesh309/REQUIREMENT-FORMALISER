"""Helpers shared by the interop modules (tables, report, diff, SysML text, XMI).

Everything here reads elements *generically* (``getattr`` with defaults) so
attributes added by features built in parallel (interfaces, profiles,
requirements, allocation, ...) are picked up without importing them.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
from typing import Any, Iterable, Iterator, Optional

from kerml.elements import Annotation, Documentation, Element, Relationship
from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, StereotypeTag, stereotypes_on
from sysmlv2.library import SYSML_LIBRARY


class InteropError(ValueError):
    """A user-facing problem with imported content (bad table, XMI, merge input...)."""


# --- library / project membership ------------------------------------------

LIBRARIES: tuple[Package, ...] = (KERML_LIBRARY, SYSML_LIBRARY)


def library_root(e: Element) -> Optional[Package]:
    root = e.root()
    return root if any(root is lib for lib in LIBRARIES) else None


def in_library(e: Element) -> bool:
    return library_root(e) is not None


def project_elements(repo) -> list[Element]:
    """Project elements in containment pre-order (root excluded, no relationships)."""
    return [e for e in repo.root_package.walk()
            if e is not repo.root_package and not isinstance(e, (Relationship, Annotation))]


def relative_qname(e: Element, repo=None) -> str:
    """Qualified name without the project root segment (``Pkg::Part``).

    Library elements keep their full name (``KerML::ScalarValues::Real``).
    """
    if in_library(e):
        return e.qualified_name
    parts: list[str] = []
    node: Optional[Element] = e
    root = repo.root_package if repo is not None else e.root()
    while node is not None and node is not root:
        parts.append(node.name if node.name is not None else f"<{node.element_id[:8]}>")
        node = node.owner
    return "::".join(reversed(parts))


def resolve_qname(repo, qname: str) -> Optional[Element]:
    """Resolve a project-relative or library qualified name."""
    if not qname:
        return None
    qname = qname.strip()
    for lib in LIBRARIES:
        prefix = f"{lib.name}::"
        if qname.startswith(prefix):
            hit = lib.resolve(qname[len(prefix):])
            if hit is not None:
                return hit
    hit = repo.root_package.resolve(qname)
    if hit is not None:
        return hit
    # A qualified name written with the project name in front.
    root_prefix = f"{repo.root_package.name}::"
    if repo.root_package.name and qname.startswith(root_prefix):
        return repo.root_package.resolve(qname[len(root_prefix):])
    # Bare library type names (Real, String, Part, ...).
    if "::" not in qname:
        for lib in LIBRARIES:
            for x in lib.walk():
                if x.name == qname and x is not lib:
                    return x
    return None


def library_by_id() -> dict[str, Element]:
    out: dict[str, Element] = {}
    for lib in LIBRARIES:
        for e in lib.walk():
            out[e.element_id] = e
    return out


# --- kinds -----------------------------------------------------------------

_EXTRA_KINDS: dict[str, type] = {}
_engine_modules_loaded = False


def register_table_kind(name: str, cls: type) -> None:
    """Make an element class creatable by kind name in table / builder imports."""
    _EXTRA_KINDS[name] = cls


def _walk_subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _walk_subclasses(sub)


def kind_classes() -> dict[str, type]:
    """Kind name -> creatable element class, for every element class loaded so far.

    Core KerML / SysML classes win over same-named classes from other modules.
    """
    out: dict[str, type] = {}
    later: dict[str, type] = {}
    for sub in _walk_subclasses(Element):
        k = sub.__dict__.get("kind")
        if not k or issubclass(sub, (Relationship, Annotation)):
            continue
        core = sub.__module__.split(".")[0] in ("kerml", "sysmlv2")
        target = out if core else later
        target.setdefault(k, sub)
    for k, cls in later.items():
        out.setdefault(k, cls)
    out.update(_EXTRA_KINDS)
    return out


def class_for_kind(kind: str) -> Optional[type]:
    """The class for `kind`; imports the engine's feature modules once if unknown."""
    global _engine_modules_loaded
    classes = kind_classes()
    if kind in classes:
        return classes[kind]
    if not _engine_modules_loaded:
        _engine_modules_loaded = True
        import engine
        for info in pkgutil.iter_modules(engine.__path__):
            if info.name.startswith("_") or info.name in ("cli",):
                continue
            try:
                importlib.import_module(f"engine.{info.name}")
            except Exception:  # noqa: BLE001 - a broken optional module must not stop imports
                continue
        classes = kind_classes()
    return classes.get(kind)


def new_element(cls: type, name: Optional[str], element_id: Optional[str] = None) -> Element:
    """Instantiate `cls` the way the web API does, then pin its id."""
    try:
        e = cls(name=name)
    except TypeError:
        e = cls()
        e.name = name
    if element_id:
        e.element_id = element_id
    return e


# --- attributes ------------------------------------------------------------

def documentation(e: Element) -> str:
    return next((a.body for a in e.annotations if isinstance(a, Documentation)), "") or ""


def set_documentation(e: Element, text: Optional[str]) -> None:
    e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
    if text:
        e.add_annotation(Documentation(body=str(text)))


def format_multiplicity(m: MultiplicityRange) -> str:
    if m.upper is None:
        return "*" if m.lower == 0 else f"{m.lower}..*"
    if m.lower == m.upper:
        return str(m.lower)
    return f"{m.lower}..{m.upper}"


_MULT = re.compile(r"^\s*\[?\s*(\d+|\*)\s*(?:\.\.\s*(\d+|\*)\s*)?\]?\s*$")


def parse_multiplicity(text: Any) -> MultiplicityRange:
    """``1``, ``0..1``, ``1..*``, ``*``, ``[2..4]`` -> MultiplicityRange (ValueError if bad)."""
    if isinstance(text, float) and text.is_integer():
        text = int(text)
    s = str(text)
    m = _MULT.match(s)
    if not m:
        raise ValueError(f"invalid multiplicity {s!r} (use 1, 0..1, 1..*, *, 2..4)")
    lo, hi = m.group(1), m.group(2)
    if hi is None:
        if lo == "*":
            return MultiplicityRange(0, None)
        return MultiplicityRange(int(lo), int(lo))
    if lo == "*":
        raise ValueError(f"invalid multiplicity {s!r}: lower bound cannot be *")
    return MultiplicityRange(int(lo), None if hi == "*" else int(hi))


DIRECTIONS = [d.value for d in FeatureDirection]


def parse_direction(value: Any) -> FeatureDirection:
    s = str(value or "none").strip().lower()
    aliases = {"": "none", "input": "in", "output": "out", "bidirectional": "inout",
               "in/out": "inout", "inout": "inout", "physical": "none"}
    s = aliases.get(s, s)
    try:
        return FeatureDirection(s)
    except ValueError:
        raise ValueError(f"invalid direction {value!r} (use in, out, inout or none)") from None


# Attributes that tables and diffs handle explicitly (or that are structural).
CORE_ATTRS = {
    "element_id", "name", "short_name", "owner", "owned_relationships", "owned_elements",
    "annotations", "is_abstract", "tool_data", "memberships", "imports", "specializations",
    "conjugations", "feature_typings", "subsettings", "redefinitions", "multiplicity",
    "direction", "featuring_type", "ends", "end_contexts", "req_id", "text", "body",
    "annotated_element", "kind",
}

_DEFAULTS: dict[type, Optional[dict]] = {}


def _class_defaults(cls: type) -> Optional[dict]:
    """Attribute values of a freshly created instance (None if it cannot be built)."""
    if cls not in _DEFAULTS:
        inst = None
        for attempt in (lambda: cls(), lambda: cls(name="x")):
            try:
                inst = attempt()
                break
            except Exception:  # noqa: BLE001 - classes with required arguments
                continue
        _DEFAULTS[cls] = dict(_public_vars(inst)) if inst is not None else None
    return _DEFAULTS[cls]


def _public_vars(e: Any) -> Iterator[tuple[str, Any]]:
    cls = type(e)
    for k, v in vars(e).items():
        if k.startswith("__"):
            continue
        if k.startswith("_"):
            # A property backed by `_name` (e.g. PortUsage.port_kind) is exposed by its public name.
            pub = k[1:]
            if isinstance(getattr(cls, pub, None), property):
                yield pub, getattr(e, pub)
            continue
        yield k, v


def _json_scalar_or_data(v: Any) -> bool:
    if v is None or isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, (list, dict)):
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            return False
        return True
    return False


def extra_attributes(e: Element) -> dict[str, Any]:
    """JSON-able attributes of `e` beyond the core ones whose value differs from the class default.

    This is how columns such as ``port_kind``, ``rationale``, ``units`` or
    ``priority`` (added by other features) appear in tables without this module
    knowing about them.
    """
    defaults = _class_defaults(type(e)) or {}
    out: dict[str, Any] = {}
    missing = object()
    for k, v in _public_vars(e):
        if k in CORE_ATTRS or callable(v) or not _json_scalar_or_data(v):
            continue
        default = defaults.get(k, getattr(type(e), k, missing))
        if default is not missing and default == v and type(default) is type(v):
            continue
        if default is missing and v in (None, "", [], {}):
            continue
        out[k] = v
    return out


def class_default(cls: type, attr: str) -> Any:
    return (_class_defaults(cls) or {}).get(attr)


def coerce_like(current: Any, value: Any, attr: str = "") -> Any:
    """Convert a table cell (text or typed) to the type of an attribute's current value."""
    if isinstance(value, str):
        s = value.strip()
    else:
        s = value
    if isinstance(current, bool):
        if isinstance(s, bool):
            return s
        t = str(s).strip().lower()
        if t in ("true", "1", "yes", "y", "on", "x"):
            return True
        if t in ("false", "0", "no", "n", "off", ""):
            return False
        raise ValueError(f"{attr or 'value'}: expected true/false, got {value!r}")
    if isinstance(current, int) and not isinstance(current, bool):
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            if float(s).is_integer():
                return int(s)
            raise ValueError(f"{attr or 'value'}: expected an integer, got {value!r}")
        try:
            return int(str(s))
        except ValueError:
            raise ValueError(f"{attr or 'value'}: expected an integer, got {value!r}") from None
    if isinstance(current, float):
        try:
            return float(s)
        except (TypeError, ValueError):
            raise ValueError(f"{attr or 'value'}: expected a number, got {value!r}") from None
    if isinstance(current, (list, dict)):
        if isinstance(s, (list, dict)):
            return s
        if s in ("", None):
            return type(current)()
        try:
            data = json.loads(str(s))
        except ValueError:
            raise ValueError(f"{attr or 'value'}: expected JSON, got {value!r}") from None
        if not isinstance(data, type(current)):
            raise ValueError(f"{attr or 'value'}: expected a JSON {type(current).__name__}")
        return data
    if current is None:
        if isinstance(s, str):
            if s == "":
                return None
            if s[:1] in "[{":
                try:
                    return json.loads(s)
                except ValueError:
                    return s
        return s
    return "" if s is None else str(s)


def infer_scalar(value: Any) -> Any:
    """Best-effort typing of a text cell: booleans, integers and decimals become values."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.fullmatch(r"[-+]?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


def cell_text(value: Any) -> str:
    """Render a value for a text cell (CSV)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)          # shortest text that reads back as the same float
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)


# --- stereotypes -----------------------------------------------------------

def stereotype_full_name(st: Stereotype) -> str:
    """``Profile.Stereotype`` when the stereotype lives in a profile, else its name."""
    full = getattr(st, "full_name", None)
    if isinstance(full, str) and full:
        return full
    owner = st.owner
    if isinstance(owner, Package) and owner.owner is not None and owner.name:
        return f"{owner.name}.{st.name}"
    return str(st.name)


def all_stereotypes(repo) -> list[Stereotype]:
    return [e for e in repo.root_package.walk() if isinstance(e, Stereotype)]


def stereotype_tags(st: Stereotype) -> list[StereotypeTag]:
    try:
        return list(st.all_tags())
    except Exception:  # noqa: BLE001
        return list(getattr(st, "tags", []))


def find_stereotype(repo, ref: str, extra: Optional[Iterable[Stereotype]] = None) -> Optional[Stereotype]:
    """By id, ``Profile.Stereotype`` full name, ``Profile::Stereotype`` or plain name."""
    ref = (ref or "").strip()
    if not ref:
        return None
    hit = repo.by_id(ref)
    if isinstance(hit, Stereotype):
        return hit
    pool = list(all_stereotypes(repo)) + list(extra or [])
    for st in pool:
        if stereotype_full_name(st) == ref:
            return st
    norm = ref.replace("::", ".")
    for st in pool:
        if stereotype_full_name(st) == norm:
            return st
    named = [st for st in pool if st.name == ref or st.name == norm.rsplit(".", 1)[-1]]
    return named[0] if len(named) == 1 else None


def stereotype_values(e: Element) -> list[tuple[Stereotype, dict]]:
    return [(app.stereotype, dict(getattr(app, "values", {}) or {})) for app in stereotypes_on(e)]


def is_profile_content(e: Element) -> bool:
    """Stereotypes, their properties and profile packages (exported in the Profiles table)."""
    node: Optional[Element] = e
    while node is not None:
        if isinstance(node, Stereotype) or getattr(node, "kind", "") == "Profile":
            return True
        node = node.owner
    return False


def namespace_ancestor(e: Element) -> Optional[Namespace]:
    n = e
    while n is not None and not isinstance(n, Namespace):
        n = n.owner
    return n


def move_element(e: Element, new_owner: Element) -> None:
    """Re-own `e`, dropping the stale membership in its previous namespace."""
    old = e.owner
    if old is new_owner:
        return
    if isinstance(old, Namespace):
        stale = [m for m in old.memberships if m.member is e]
        old.memberships = [m for m in old.memberships if m.member is not e]
        old.owned_relationships = [r for r in old.owned_relationships
                                   if not any(r is m for m in stale)]
    new_owner.own(e)


def feature_types(e: Element) -> list[Element]:
    return list(e.types) if isinstance(e, Feature) else []


def set_feature_types(e: Feature, types: list[Element]) -> bool:
    """Replace the types of `e`; returns True if they changed."""
    if [id(t) for t in e.types] == [id(t) for t in types]:
        return False
    from kerml.features import FeatureTyping
    e.feature_typings = []
    e.owned_relationships = [r for r in e.owned_relationships if not isinstance(r, FeatureTyping)]
    for t in types:
        e.add_type(t)
    return True


def set_specializations(e: Element, generals: list[Element]) -> bool:
    current = [s.target for s in getattr(e, "specializations", [])]
    if [id(t) for t in current] == [id(t) for t in generals]:
        return False
    from kerml.types import Specialization
    e.specializations = []
    e.owned_relationships = [r for r in e.owned_relationships if not isinstance(r, Specialization)]
    for g in generals:
        e.specialize(g)
    return True


def link_kind_name(rel: Relationship) -> str:
    from engine.links import LINK_KINDS
    for lk in LINK_KINDS:
        if type(rel) is lk.cls:
            return lk.name
    for lk in LINK_KINDS:
        if isinstance(rel, lk.cls):
            return lk.name
    return rel.kind


def model_links(repo) -> list[Relationship]:
    """Typed links (satisfy, verify, allocate, ...) owned anywhere in the project."""
    from engine.links import LINK_KINDS
    classes = tuple(lk.cls for lk in LINK_KINDS)
    out: list[Relationship] = []
    seen: set[int] = set()
    for e in repo.root_package.walk():
        for rel in e.owned_relationships:
            if isinstance(rel, classes) and rel.source is not None and rel.target is not None \
                    and id(rel) not in seen:
                seen.add(id(rel))
                out.append(rel)
    return out


def safe_filename(name: str, default: str = "model") -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")
    return s or default
