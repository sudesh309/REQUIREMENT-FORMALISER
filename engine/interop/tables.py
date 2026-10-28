"""Architecture <-> tables (System Composer ``exportModel`` / ``importModel``).

``export_tables(repo)`` returns ordered sheets (first row = header):

=============  ==============================================================
Model          Format, Name and Root ID of the exported project
Profiles       stereotypes and their properties (one row per property)
Components     architectures (``PartDefinition``) and components (``PartUsage``)
               with parent and reference definition
Ports          ports with direction, owning component and interface
Interfaces     interfaces (``PortDefinition`` / ``InterfaceDefinition`` and the
               kinds derived from them) and their elements
Connections    connectors with source / target component and port
Requirements   requirements with Req ID and text
Elements       every other model element (packages, attributes, actions, ...)
Links          typed links (satisfy, verify, derive, allocate, ...)
=============  ==============================================================

Every element row has an ``ID``; reference columns come in pairs (``X ID`` holds
element ids, ``X`` the qualified names, ``;``-separated when there are several).
Applied stereotypes are listed in ``Stereotypes`` and their property values in
``Profile.Stereotype.property`` columns, named as the profiles feature names them
(``Stereotype.full_name``: ``Avionics.LRU``; a stereotype kept in a plain package
is just ``LRU``). Further columns are discovered from the elements themselves
(any JSON-able attribute whose value differs from the default, e.g. ``port_kind``
or ``rationale``), so attributes added by other features round-trip without
changes here.

``import_tables(repo, sheets)`` creates or updates elements matched by ``ID``
(falling back to owner + name), so export -> import preserves ids; it is atomic
(a dry run on a copy of the project must succeed first). Profiles, stereotypes,
properties and stereotype values go through ``engine.profiles`` (checks, unit
conversion, change propagation). ``ModelBuilder`` builds the same tables
incrementally from Python and then the model.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional

from engine import profiles as P
from kerml.elements import Element, Relationship
from kerml.features import Feature, FeatureDirection
from kerml.namespaces import Package
from kerml.stereotypes import (
    CATEGORIES, DEFAULT_SLOTS, NUMERIC_TYPES, STYLE_KEYS, Profile, Stereotype, StereotypeError,
    StereotypeTag, build_property, effective_applications, inheritance_source, normalize_style,
    stereotypes_on,
)
from sysmlv2.definitions import (
    ConnectionUsage, Definition, InterfaceDefinition, PartDefinition, PartUsage,
    PortDefinition, PortUsage, RequirementDefinition, RequirementUsage,
)

from .common import (
    InteropError, cell_text, class_default, class_for_kind, coerce_like, decode_untyped_cell,
    documentation, extra_attributes, find_stereotype, format_multiplicity, in_library,
    is_profile_content, link_kind_name, model_links, move_element, new_element,
    parse_direction, parse_multiplicity, project_elements, relative_qname, resolve_qname,
    set_documentation, set_feature_types, set_specializations,
)

FORMAT = "sysml-studio-tables/1"
TOOL_DATA = "Tool Data"
TABLE_ORDER = ["Model", "Profiles", "Components", "Ports", "Interfaces", "Connections",
               "Requirements", "Elements", "Links", TOOL_DATA]
ELEMENT_TABLES = ["Components", "Ports", "Interfaces", "Connections", "Requirements", "Elements"]
# Tool Data sheet: one row per Element.tool_data entry (canvas layout, port sides, connector
# waypoints, ...), the value as JSON.
TOOL_DATA_COLUMNS = ["ID", "Name", "Kind", "Key", "Value"]
# Model sheet rows carrying project-level feature state (engine.register_repo_codec data,
# e.g. suspect-link baselines or the architecture type) as JSON, split over several rows
# with the same Property when longer than one spreadsheet cell holds.
PROJECT_DATA_PREFIX = "Data: "
_CELL_CHUNK = 32000            # below Excel's 32767 characters per cell
# An attribute column cell meaning "no value" where the attribute has a non-empty
# default (an empty cell keeps the default).
NULL_CELL = "null"

# Element-valued attributes exported as "<attr> ID" columns (features may add theirs).
REFERENCE_ATTRIBUTES: list[str] = [
    "transition_source", "transition_target", "initial_state", "final_states",
    "allocate_from", "allocate_to", "payload_type", "flow_source", "flow_target",
    # Allocation sets (source / target architecture) and allocations (source / target).
    "source_architecture", "target_architecture", "source", "target",
]


def register_reference_attribute(name: str) -> None:
    """Export/import an Element-valued attribute as an ``<name> ID`` column."""
    if name not in REFERENCE_ATTRIBUTES:
        REFERENCE_ATTRIBUTES.append(name)


# Base columns of each element table; extra attribute columns and stereotype
# property columns are appended after them.
BASE_COLUMNS: dict[str, list[str]] = {
    "Components": ["ID", "Name", "Kind", "Parent ID", "Parent", "Reference ID", "Reference",
                   "Specializes ID", "Specializes", "Multiplicity", "Abstract", "Short Name",
                   "Documentation", "Stereotypes"],
    "Ports": ["ID", "Name", "Kind", "Component ID", "Component", "Direction", "Interface ID",
              "Interface", "Multiplicity", "Short Name", "Documentation", "Stereotypes"],
    "Interfaces": ["ID", "Name", "Kind", "Owner ID", "Owner", "Type ID", "Type", "Direction",
                   "Multiplicity", "Specializes ID", "Specializes", "Abstract", "Short Name",
                   "Documentation", "Stereotypes"],
    "Connections": ["ID", "Name", "Kind", "Owner ID", "Owner", "Source Component ID",
                    "Source Component", "Source Port ID", "Source Port", "Target Component ID",
                    "Target Component", "Target Port ID", "Target Port", "Type ID", "Type",
                    "Short Name", "Documentation", "Stereotypes"],
    "Requirements": ["ID", "Req ID", "Name", "Kind", "Owner ID", "Owner", "Text", "Type ID",
                     "Type", "Specializes ID", "Specializes", "Short Name", "Documentation",
                     "Stereotypes"],
    "Elements": ["ID", "Name", "Kind", "Owner ID", "Owner", "Type ID", "Type", "Specializes ID",
                 "Specializes", "Multiplicity", "Direction", "Abstract", "Short Name",
                 "Documentation", "Stereotypes"],
}
LINK_COLUMNS = ["ID", "Kind", "Source ID", "Source", "Target ID", "Target"]
# One row per stereotype property (a stereotype without properties, or a profile without
# stereotypes, gets one row); profile and stereotype columns repeat on each of their rows.
PROFILE_COLUMNS = ["Profile ID", "Profile", "Profile Version", "Profile Description",
                   "Root Stereotype", "Stereotype ID", "Stereotype", "Base", "Applies To",
                   "Abstract", "Stereotype Description", "Style", "Defaults",
                   "Property ID", "Property", "Type", "Unit", "Default", "Min", "Max",
                   "Literals", "Description"]
OWNER_COLUMNS = {"Components": ("Parent ID", "Parent"), "Ports": ("Component ID", "Component")}
TYPE_COLUMNS = {"Components": ("Reference ID", "Reference"), "Ports": ("Interface ID", "Interface")}
DEFAULT_KIND = {"Ports": "PortUsage", "Connections": "ConnectionUsage",
                "Requirements": "RequirementDefinition"}
TABLE_FAMILY: dict[str, tuple[type, ...]] = {
    "Components": (PartDefinition, PartUsage),
    "Ports": (PortUsage,),
    "Connections": (ConnectionUsage,),
    "Requirements": (RequirementDefinition, RequirementUsage),
}

Sheets = dict[str, list[list[Any]]]


# =============================================================================
# Export
# =============================================================================

def _is_interface(e: Element) -> bool:
    if isinstance(e, (PortDefinition, InterfaceDefinition)):
        return True
    k = getattr(e, "kind", "")
    return isinstance(e, Definition) and "Interface" in k and "Dictionary" not in k


def _inside_interface(e: Element) -> bool:
    node = e.owner
    while node is not None and not isinstance(node, Package):
        if _is_interface(node):
            return True
        node = node.owner
    return False


def table_of(e: Element) -> Optional[str]:
    """Which table an element is exported to (None for profile content)."""
    if is_profile_content(e):
        return None
    if isinstance(e, ConnectionUsage):
        return "Connections"
    if isinstance(e, PortUsage):
        return "Ports"
    if isinstance(e, (PartDefinition, PartUsage)):
        return "Components"
    if isinstance(e, (RequirementDefinition, RequirementUsage)):
        return "Requirements"
    if _is_interface(e) or _inside_interface(e):
        return "Interfaces"
    return "Elements"


def _ref_ids(repo, elements: Iterable[Optional[Element]]) -> str:
    return ";".join("" if (x is None or in_library(x)) else x.element_id for x in elements)


def _ref_names(repo, elements: Iterable[Optional[Element]]) -> str:
    return ";".join("" if x is None else relative_qname(x, repo) for x in elements)


def _owner_cells(repo, e: Element) -> tuple[str, str]:
    o = e.owner
    if o is None or o is repo.root_package:
        return repo.root_package.element_id, ""
    return o.element_id, relative_qname(o, repo)


def _connection_end(conn: ConnectionUsage, i: int) -> tuple[Optional[Element], Optional[Element]]:
    """(component, port) of end `i`: the stored end context if any, else the port's owner."""
    ends = [x for x in conn.ends if x is not None]
    if i >= len(ends):
        return None, None
    port = ends[i]
    ctx = tuple(getattr(conn, "end_contexts", ()) or ())
    comp = ctx[i] if len(ctx) == len(ends) and ctx[i] is not None else port.owner
    return comp, port


def _element_row(repo, e: Element, table: str) -> dict[str, Any]:
    row: dict[str, Any] = {"ID": e.element_id, "Name": e.name or "", "Kind": e.kind,
                           "Short Name": e.short_name or "", "Documentation": documentation(e)}
    owner_id_col, owner_col = OWNER_COLUMNS.get(table, ("Owner ID", "Owner"))
    row[owner_id_col], row[owner_col] = _owner_cells(repo, e)
    types = list(e.types) if isinstance(e, Feature) else []
    type_id_col, type_col = TYPE_COLUMNS.get(table, ("Type ID", "Type"))
    row[type_id_col], row[type_col] = _ref_ids(repo, types), _ref_names(repo, types)
    gens = [s.target for s in getattr(e, "specializations", []) if s.target is not None]
    row["Specializes ID"], row["Specializes"] = _ref_ids(repo, gens), _ref_names(repo, gens)
    if isinstance(e, Feature):
        row["Multiplicity"] = format_multiplicity(e.multiplicity)
        row["Direction"] = e.direction.value if e.direction is not FeatureDirection.NONE else ""
    row["Abstract"] = True if getattr(e, "is_abstract", False) else ""
    if table == "Requirements":
        row["Req ID"] = getattr(e, "req_id", None) or ""
        row["Text"] = getattr(e, "text", None) or ""
    if table == "Connections":
        for i, side in enumerate(("Source", "Target")):
            comp, port = _connection_end(e, i)  # type: ignore[arg-type]
            row[f"{side} Component ID"] = _ref_ids(repo, [comp]) if comp is not None else ""
            row[f"{side} Component"] = _ref_names(repo, [comp]) if comp is not None else ""
            row[f"{side} Port ID"] = _ref_ids(repo, [port]) if port is not None else ""
            row[f"{side} Port"] = _ref_names(repo, [port]) if port is not None else ""
        others = [x for x in e.ends if x is not None][2:]  # type: ignore[attr-defined]
        if others:
            row["Other End IDs"] = _ref_ids(repo, others)
    # What the element reads: its own stereotypes, then the ones a reference component inherits
    # from its definition (SU-15), with the values it reads (an override or the definition's).
    apps = effective_applications(e)
    row["Stereotypes"] = ";".join(a.stereotype.full_name for a in apps)
    for a in apps:
        # Stored (canonical) values: numbers are in the property's unit (Profiles sheet).
        for name, v in a.values.items():
            row[f"{a.stereotype.full_name}.{name}"] = v
    for attr in REFERENCE_ATTRIBUTES:
        if not hasattr(e, attr):
            continue
        v = getattr(e, attr)
        if isinstance(v, Element):
            row[f"{attr} ID"] = _reference_cell(v)
        elif isinstance(v, list) and v and all(isinstance(x, Element) for x in v):
            row[f"{attr} ID"] = ";".join(_reference_cell(x) for x in v)
    allowed = set(BASE_COLUMNS[table]) | ({"Other End IDs"} if table == "Connections" else set())
    row = {k: v for k, v in row.items() if k in allowed or k not in _ALL_BASE}
    for k, v in extra_attributes(e).items():
        # None only appears here when the attribute's default is a value (a DataElement
        # typed by a value type has no primitive type): say so, an empty cell keeps the default.
        row.setdefault(k, NULL_CELL if v is None else v)
    return row


def _reference_cell(e: Element) -> str:
    """An element in a ``<attr> ID`` cell: its id, or the qualified name of a library element
    (library ids change in every process)."""
    return e.qualified_name if in_library(e) else e.element_id


_ALL_BASE = {c for cols in BASE_COLUMNS.values() for c in cols} | {"Other End IDs"}


def _columns(base: list[str], rows: list[dict]) -> list[str]:
    extra, stereo = set(), set()
    for r in rows:
        for k in r:
            if k in base:
                continue
            (stereo if "." in k else extra).add(k)
    return list(base) + sorted(extra) + sorted(stereo)


def _sheet(columns: list[str], rows: list[dict]) -> list[list[Any]]:
    out: list[list[Any]] = [list(columns)]
    for r in rows:
        out.append([r.get(c, "") if r.get(c) is not None else "" for c in columns])
    return out


def _pairs(d: dict) -> str:
    """``{"fill": "#fff", "icon": "computer"}`` -> ``"fill=#fff; icon=computer"``."""
    return "; ".join(f"{k}={v}" for k, v in d.items() if v not in (None, ""))


def _parse_pairs(text: Any, keys: Iterable[str], what: str) -> dict[str, str]:
    """The inverse of :func:`_pairs`; unknown keys are an error."""
    out: dict[str, str] = {}
    allowed = list(keys)
    for part in _text(text).split(";"):
        if not part.strip():
            continue
        key, sep, value = part.partition("=")
        key = key.strip()
        if not sep or key not in allowed:
            raise InteropError(f"{what} {part.strip()!r}: use key=value pairs with keys {allowed}")
        out[key] = value.strip()
    return out


def _container_cells(repo, container: Optional[Element]) -> dict:
    if container is None or container is repo.root_package:
        return {"Profile ID": "", "Profile": ""}
    cells = {"Profile ID": container.element_id, "Profile": container.name or ""}
    if isinstance(container, Profile):
        root = container.root_stereotype
        cells.update({"Profile Version": container.version,
                      "Profile Description": container.description,
                      "Root Stereotype": root.full_name if root is not None else ""})
    return cells


def _stereotype_cells(st: Stereotype) -> dict:
    applies = st.category or ";".join(getattr(c, "kind", c.__name__) for c in st.applies_to)
    defaults = {slot: getattr(st, f"default_{slot}_stereotype") for slot in DEFAULT_SLOTS}
    return {"Stereotype ID": st.element_id, "Stereotype": st.name or "",
            "Base": st.base.full_name if st.base is not None else "",
            "Applies To": applies, "Abstract": True if st.is_abstract else "",
            "Stereotype Description": st.description,
            "Style": _pairs({k: st.style.get(k) for k in STYLE_KEYS}),
            "Defaults": _pairs({s: d.full_name for s, d in defaults.items() if d is not None})}


def _property_cells(t: StereotypeTag) -> dict:
    return {"Property ID": t.element_id, "Property": t.name or "", "Type": t.prop_type,
            "Unit": t.unit, "Default": t.default_value, "Min": t.minimum, "Max": t.maximum,
            "Literals": ", ".join(t.literals), "Description": t.description}


def _profile_rows(repo) -> list[dict]:
    """Profiles sheet rows: every stereotype (with its own properties) and empty profiles."""
    rows: list[dict] = []
    for e in repo.root_package.walk():
        if isinstance(e, Profile) and not e.stereotypes:
            rows.append(_container_cells(repo, e))
        if not isinstance(e, Stereotype):
            continue
        head = {**_container_cells(repo, e.owner), **_stereotype_cells(e)}
        if not e.tags:
            rows.append({**head, "Property ID": "", "Property": ""})
        rows += [{**head, **_property_cells(t)} for t in e.tags]
    return rows


def export_tables(repo) -> Sheets:
    """The model as ordered sheets ``{table: [header, row, ...]}``."""
    buckets: dict[str, list[dict]] = {t: [] for t in ELEMENT_TABLES}
    for e in project_elements(repo):
        table = table_of(e)
        if table is not None:
            buckets[table].append(_element_row(repo, e, table))
    sheets: Sheets = {
        "Model": [["Property", "Value"], ["Format", FORMAT], ["Name", repo.name],
                  ["Root ID", repo.root_package.element_id]]
                 + ([["Documentation", documentation(repo.root_package)]]
                    if documentation(repo.root_package) else [])
                 + _project_data_rows(repo),
        "Profiles": _sheet(PROFILE_COLUMNS, _profile_rows(repo)),
    }
    for t in ELEMENT_TABLES:
        sheets[t] = _sheet(_columns(BASE_COLUMNS[t], buckets[t]), buckets[t])
    links = []
    for rel in model_links(repo):
        links.append({"ID": rel.element_id, "Kind": link_kind_name(rel),
                      "Source ID": _ref_ids(repo, [rel.source]),
                      "Source": _ref_names(repo, [rel.source]),
                      "Target ID": _ref_ids(repo, [rel.target]),
                      "Target": _ref_names(repo, [rel.target])})
    sheets["Links"] = _sheet(LINK_COLUMNS, links)
    sheets[TOOL_DATA] = _sheet(TOOL_DATA_COLUMNS, _tool_data_rows(repo))
    return sheets


def _json_cell(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _project_data_rows(repo) -> list[list[Any]]:
    """Model sheet rows with the project-level state features persist through
    ``register_repo_codec`` (``Data: requirements-links`` -> JSON), so a project rebuilt
    from the tables keeps it (suspect-link baselines, the architecture type, ...)."""
    from engine.serializer import _REPO_CODECS, _encode_ext
    rows: list[list[Any]] = []
    for name, entry in sorted(_encode_ext(_REPO_CODECS, repo).items()):
        text = _json_cell(entry["data"])
        for i in range(0, len(text), _CELL_CHUNK):
            rows.append([f"{PROJECT_DATA_PREFIX}{name}", text[i:i + _CELL_CHUNK]])
    return rows


def _tool_data_rows(repo) -> list[dict]:
    """``Element.tool_data`` (canvas layout, port sides, waypoints, ...), one row per entry."""
    from engine.serializer import _json_safe
    rows: list[dict] = []
    for e in [repo.root_package] + project_elements(repo):
        for key, value in sorted(e.tool_data.items()):
            if _json_safe(value):
                rows.append({"ID": e.element_id, "Name": e.name or "", "Kind": e.kind,
                             "Key": key, "Value": _json_cell(value)})
    return rows


def export_tables_file(repo, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    """(content, filename, mime type) for ``xlsx`` or ``csv`` (a ZIP of CSV files)."""
    from .common import safe_filename
    from .xlsx import write_csv_zip, write_xlsx
    sheets = export_tables(repo)
    base = safe_filename(repo.name)
    if fmt == "xlsx":
        return (write_xlsx(sheets), f"{base}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt in ("csv", "zip"):
        return write_csv_zip(sheets), f"{base}_tables.zip", "application/zip"
    raise InteropError(f"unknown table format {fmt!r} (use xlsx or csv)")


def read_tables_file(data: bytes, filename: str = "") -> Sheets:
    from .xlsx import read_any
    return read_any(data, filename)


# =============================================================================
# Import
# =============================================================================

@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    links_created: int = 0
    links_unchanged: int = 0
    stereotypes_created: int = 0
    stereotypes_applied: int = 0
    warnings: list[str] = field(default_factory=list)
    # Profiles sheet: profiles, stereotypes and properties created or changed.
    profile_changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"created": len(self.created), "updated": len(self.updated),
                "unchanged": len(self.unchanged), "links_created": self.links_created,
                "links_unchanged": self.links_unchanged,
                "stereotypes_created": self.stereotypes_created,
                "stereotypes_applied": self.stereotypes_applied,
                "profile_changes": list(self.profile_changes),
                "created_ids": list(self.created), "updated_ids": list(self.updated),
                "warnings": list(self.warnings)}


@dataclass
class _Spec:
    table: str
    rownum: int
    row: dict
    id: str
    name: str
    kind: str
    cls: type
    existing: Optional[Element] = None
    element: Optional[Element] = None
    created: bool = False
    before: Optional[dict] = None

    @property
    def where(self) -> str:
        label = self.name or self.id
        return f"{self.table} row {self.rownum}" + (f" ({label})" if label else "")


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return cell_text(v).strip()


def _split(v: Any) -> list[str]:
    s = _text(v)
    return [p.strip() for p in s.split(";")] if s else []


def _truthy(v: Any, what: str = "Abstract") -> bool:
    if v in (None, ""):
        return False
    try:
        return coerce_like(False, v, what)
    except ValueError as ex:
        raise InteropError(str(ex)) from None


_MISSING = object()
_PROFILE_LEVEL = ("Profile Version", "Profile Description", "Root Stereotype")
_STEREOTYPE_LEVEL = ("Base", "Applies To", "Abstract", "Stereotype Description", "Style",
                     "Defaults")


def _profile_key(row: dict) -> str:
    return _text(row.get("Profile ID")) or "name:" + _text(row.get("Profile"))


def _stereotype_key(row: dict) -> str:
    return _text(row.get("Stereotype ID")) or f"{_profile_key(row)}/{_text(row.get('Stereotype'))}"


def _ident(e: Optional[Element]) -> Optional[str]:
    return e.element_id if e is not None else None


def _same(a: Any, b: Any) -> bool:
    """Equal values of the same type (an int and a float of equal value count as equal)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a == b and type(a) is type(b)


def _number_cell(v: Any) -> Any:
    """A Min / Max cell for ``engine.profiles`` (numbers, or text such as ``'0 kg'``)."""
    return None if v is None or (isinstance(v, str) and not v.strip()) else v


@contextmanager
def _profile_errors(where: str) -> Iterator[None]:
    """Report profile and stereotype errors with the table row they come from."""
    try:
        yield
    except InteropError as ex:
        msg = str(ex)
        raise InteropError(msg if msg.startswith(where) else f"{where}: {msg}") from None
    except (StereotypeError, ValueError) as ex:      # ProfileError, unit errors, ...
        raise InteropError(f"{where}: {ex}") from None


def normalize_sheets(sheets: Any) -> dict[str, list[tuple[int, dict]]]:
    """``{table: [(row number, {column: value})]}`` from rows-with-header, dict rows or JSON."""
    if isinstance(sheets, dict) and "tables" in sheets and isinstance(sheets["tables"], dict):
        sheets = sheets["tables"]
    if not isinstance(sheets, dict):
        raise InteropError("tables must be an object {table name: rows}")
    out: dict[str, list[tuple[int, dict]]] = {}
    for name, rows in sheets.items():
        if isinstance(rows, dict) and "columns" in rows:
            header = [str(c).strip() for c in rows["columns"]]
            body = rows.get("rows") or []
            rows = [header] + list(body)
        if not isinstance(rows, list):
            raise InteropError(f"table {name!r}: expected a list of rows")
        parsed: list[tuple[int, dict]] = []
        if rows and isinstance(rows[0], dict):
            for i, r in enumerate(rows):
                parsed.append((i + 2, {str(k).strip(): v for k, v in r.items()}))
        elif rows:
            header = [_text(h) for h in rows[0]]
            for i, r in enumerate(rows[1:]):
                if not isinstance(r, (list, tuple)):
                    raise InteropError(f"table {name!r} row {i + 2}: expected a list of cells")
                d = {header[c]: r[c] for c in range(min(len(header), len(r))) if header[c]}
                if all(v in (None, "") for v in d.values()):
                    continue
                parsed.append((i + 2, d))
        out[str(name).strip()] = parsed
    return out


def _canonical_table(name: str) -> Optional[str]:
    key = name.lower().replace(" ", "").replace("_", "")
    for t in TABLE_ORDER:
        low = t.lower().replace(" ", "")
        if low == key or low == key.rstrip("s") + "s":
            return t
    aliases = {"component": "Components", "port": "Ports", "connection": "Connections",
               "connectors": "Connections", "interface": "Interfaces",
               "portinterfaces": "Interfaces", "requirement": "Requirements",
               "element": "Elements", "link": "Links", "requirementlinks": "Links",
               "stereotypes": "Profiles", "profile": "Profiles", "layout": TOOL_DATA}
    return aliases.get(key)


def _canonical_columns(table: str, row: dict) -> dict:
    """Column names in their canonical case, against the columns of *this* table only
    (so an extra attribute column such as ``style`` is not taken for the Profiles one)."""
    known = {"Profiles": PROFILE_COLUMNS, "Links": LINK_COLUMNS, TOOL_DATA: TOOL_DATA_COLUMNS,
             "Model": ["Property", "Value"]}.get(table, BASE_COLUMNS.get(table, []))
    by_low = {c.lower(): c for c in known}
    return {by_low.get(k.lower(), k): v for k, v in row.items()}


class _Importer:
    def __init__(self, repo, sheets: Any, *, restore: bool = False):
        self.repo = repo
        # restore: the tables describe a whole project being rebuilt (tables_to_project),
        # so every cell is authoritative; otherwise rows are merged into a live project.
        self.restore = restore
        raw = normalize_sheets(sheets)
        self.tables: dict[str, list[tuple[int, dict]]] = {}
        self.warnings: list[str] = []
        for name, rows in raw.items():
            canon = _canonical_table(name)
            if canon is None:
                self.warnings.append(f"table {name!r} is not recognised and was ignored")
                continue
            self.tables.setdefault(canon, []).extend(
                (n, _canonical_columns(canon, r)) for n, r in rows)
        info = {_text(r.get("Property")): r.get("Value") for _, r in self.tables.get("Model", [])}
        self.model_name = _text(info.get("Name"))
        self.root_ids = {repo.root_package.element_id}
        if _text(info.get("Root ID")):
            self.root_ids.add(_text(info.get("Root ID")))
        self.specs: list[_Spec] = []
        self.by_id: dict[str, _Spec] = {}
        self.report = ImportReport(warnings=self.warnings)
        self._warned: set[str] = set()
        self._orig: dict[tuple[int, str], Any] = {}     # see _wants
        self._orig_values: dict[tuple[int, int, int], Any] = {}
        self._names_before: dict[str, Stereotype] = {}
        self._props_before: dict[tuple[int, str], StereotypeTag] = {}
        self._filled: set[tuple[str, str]] = set()      # see import_profiles

    # --- helpers ------------------------------------------------------------
    def warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.warnings.append(message)

    def lookup(self, ident: str, name: str = "", *, allow_root: bool = True) -> Optional[Element]:
        """Element by imported/model id, else by qualified name."""
        if ident:
            if allow_root and ident in self.root_ids:
                return self.repo.root_package
            spec = self.by_id.get(ident)
            if spec is not None and spec.element is not None:
                return spec.element
            hit = self.repo.by_id(ident)
            if hit is not None and not isinstance(hit, Relationship):
                return hit
        if name:
            return resolve_qname(self.repo, name)
        return None

    def refs(self, spec: _Spec, id_col: str, name_col: str) -> Optional[list[Element]]:
        """Resolve a reference column pair; None when neither column is present."""
        if id_col not in spec.row and name_col not in spec.row:
            return None
        ids, names = _split(spec.row.get(id_col)), _split(spec.row.get(name_col))
        n = max(len(ids), len(names))
        out: list[Element] = []
        for i in range(n):
            ident = ids[i] if i < len(ids) else ""
            name = names[i] if i < len(names) else ""
            if not ident and not name:
                continue
            hit = self.lookup(ident, name, allow_root=False)
            if hit is None:
                raise InteropError(f"{spec.where}: {name_col} {name or ident!r} not found")
            out.append(hit)
        return out

    # --- phase 1: parse rows ------------------------------------------------
    def parse_rows(self) -> None:
        errors: list[str] = []
        component_ids = {_text(r.get("ID")) for _, r in self.tables.get("Components", [])}
        interface_defs = {_text(r.get("ID")) for _, r in self.tables.get("Interfaces", [])
                          if not _text(r.get("Owner ID")) or _text(r.get("Kind")).endswith(
                              ("Definition", "Interface"))}
        for table in ELEMENT_TABLES:
            for rownum, row in self.tables.get(table, []):
                ident, name = _text(row.get("ID")), _text(row.get("Name"))
                where = f"{table} row {rownum}"
                if not ident and not name:
                    errors.append(f"{where}: needs an ID or a Name")
                    continue
                kind = _text(row.get("Kind")) or self._default_kind(table, row, component_ids,
                                                                     interface_defs)
                if not kind:
                    errors.append(f"{where}: Kind is required in the {table} table")
                    continue
                cls = class_for_kind(kind)
                if cls is None:
                    errors.append(f"{where}: unknown kind {kind!r}")
                    continue
                family = TABLE_FAMILY.get(table)
                if family and not issubclass(cls, family):
                    errors.append(f"{where}: kind {kind!r} does not belong in the {table} table")
                    continue
                if ident and ident in self.by_id:
                    errors.append(f"{where}: duplicate ID {ident!r} "
                                  f"(also {self.by_id[ident].where})")
                    continue
                existing = self.repo.by_id(ident) if ident else None
                if existing is self.repo.root_package or ident in self.root_ids:
                    errors.append(f"{where}: ID {ident!r} is the project root")
                    continue
                if isinstance(existing, Relationship):
                    errors.append(f"{where}: ID {ident!r} belongs to a link, not an element")
                    continue
                if existing is not None and type(existing) is not cls:
                    errors.append(f"{where}: ID {ident!r} is a {existing.kind} in the model, "
                                  f"not a {kind}")
                    continue
                for col, check in (("Multiplicity", parse_multiplicity),
                                   ("Direction", parse_direction)):
                    if _text(row.get(col)):
                        if not issubclass(cls, Feature):
                            errors.append(f"{where}: a {kind} has no {col.lower()}")
                            continue
                        try:
                            check(_text(row.get(col)))
                        except ValueError as ex:
                            errors.append(f"{where}: {ex}")
                spec = _Spec(table, rownum, row, ident, name, kind, cls, existing)
                self.specs.append(spec)
                if ident:
                    self.by_id[ident] = spec
        if errors:
            raise InteropError(_join_errors(errors))

    def _default_kind(self, table: str, row: dict, component_ids: set, interface_defs: set) -> str:
        if table in DEFAULT_KIND:
            return DEFAULT_KIND[table]
        if table == "Components":
            if _text(row.get("Reference ID")) or _text(row.get("Reference")):
                return "PartUsage"
            pid = _text(row.get("Parent ID"))
            parent = self.repo.by_id(pid) if pid else None
            if parent is None and not pid and _text(row.get("Parent")):
                parent = resolve_qname(self.repo, _text(row.get("Parent")))
            if (pid and pid in component_ids) or isinstance(parent, (PartDefinition, PartUsage)):
                return "PartUsage"
            return "PartDefinition"
        if table == "Interfaces":
            oid = _text(row.get("Owner ID"))
            owner = self.repo.by_id(oid) if oid else None
            if (oid and oid in interface_defs) or (owner is not None and _is_interface(owner)):
                return "AttributeUsage"
            return "PortDefinition"
        return ""

    # --- phase 2: profiles ----------------------------------------------------
    # Profiles, stereotypes and typed properties are created and edited through the
    # profiles feature (engine.profiles): its checks, unit handling and change
    # propagation apply exactly as in the Profile Editor. Stereotypes kept in plain
    # packages (the legacy API) have no profile operations and are handled directly.

    def import_profiles(self) -> None:
        deferred: list[tuple[int, str, Callable[[], None]]] = []   # (phase, where, fn)
        rows = self.tables.get("Profiles", [])
        # Profile / stereotype columns repeat on every row of their profile / stereotype:
        # a blank cell only counts (clears the value) when no row of it fills that column.
        self._filled = {(key, col) for _, row in rows
                        for key, cols in ((_profile_key(row), _PROFILE_LEVEL),
                                          (_stereotype_key(row), _STEREOTYPE_LEVEL))
                        for col in cols if _text(row.get(col))}
        for rownum, row in rows:
            where = f"Profiles row {rownum}"
            with _profile_errors(where):
                self._profile_row(row, where, deferred)
        # References between stereotypes once all exist: bases, then defaults, then roots.
        for _phase, where, fn in sorted(deferred, key=lambda d: d[0]):
            with _profile_errors(where):
                fn()

    def _profile_row(self, row: dict, where: str, deferred: list) -> None:
        container = self._container(row, where, deferred)
        sname, sid = _text(row.get("Stereotype")), _text(row.get("Stereotype ID"))
        if not sname and not sid:
            if _text(row.get("Property")) or _text(row.get("Property ID")):
                raise InteropError(f"{where}: a property row needs its Stereotype")
            return                                      # profile without stereotypes
        st = self._stereotype_row(container, row, sname, sid, where)
        if self._given(row, "Base"):
            ref = _text(row["Base"])
            deferred.append((0, where, lambda: self._set_base(st, ref)))
        if self._given(row, "Defaults"):
            refs = _parse_pairs(row["Defaults"], DEFAULT_SLOTS, "Defaults")
            deferred.append((1, where, lambda: self._set_defaults(st, refs)))
        pname, pid = _text(row.get("Property")), _text(row.get("Property ID"))
        if pname or pid:
            self._property_row(st, row, pname, pid, where)

    _CHANGE_LABELS = {"prop_type": "type", "minimum": "min", "maximum": "max",
                      "applies_to": "applies to", "root_stereotype": "root stereotype"}

    def _note(self, what: str, keys: Iterable[str] = ()) -> None:
        """Record a Profiles-sheet change for the import report."""
        labels = [self._CHANGE_LABELS.get(k, k) for k in keys]
        self.report.profile_changes.append(f"{what}: {', '.join(labels)}" if labels else what)

    def _given(self, row: dict, col: str) -> bool:
        """Does the row set the profile- or stereotype-level column ``col``? (see import_profiles)"""
        if col not in row:
            return False
        if _text(row[col]):
            return True
        key = _profile_key(row) if col in _PROFILE_LEVEL else _stereotype_key(row)
        return (key, col) not in self._filled

    def _wants(self, obj: Element, key: str, current: Any, new: Any) -> bool:
        """Does a profile / stereotype cell ask for a change?

        Those cells repeat on every row of their profile or stereotype. A row that
        still holds the value from before the import does not undo an edit made in
        another row (edit one row of a full workbook and the edit is applied).
        """
        orig = self._orig.setdefault((id(obj), key), current)
        return not _same(new, current) and not _same(new, orig)

    def _pin_id(self, e: Element, ident: str, where: str) -> None:
        """Give an element created by the profiles API the id from the table."""
        if ident and e.element_id != ident:
            other = self.repo.by_id(ident)
            if other is not None and other is not e:
                raise InteropError(f"{where}: ID {ident!r} is already used by {other.kind} "
                                   f"{other.qualified_name!r}")
            self.repo.registry.unregister(e)
            e.element_id = ident
        self.repo.registry.register_tree(e)

    def _container(self, row: dict, where: str, deferred: list) -> Element:
        """The profile (or, for legacy stereotypes, the package) a row belongs to."""
        pid, pname = _text(row.get("Profile ID")), _text(row.get("Profile"))
        if not pid and not pname:
            return self.repo.root_package
        hit = self.repo.by_id(pid) if pid else None
        if hit is not None and not isinstance(hit, Package):
            raise InteropError(f"{where}: Profile ID {pid!r} belongs to a {hit.kind}, "
                               "not to a profile")
        if hit is None and pname:
            hit = next((p for p in P.profiles_of(self.repo) if p.name == pname), None) or \
                next((e for e in self.repo.root_package.owned_elements
                      if isinstance(e, Package) and e.name == pname), None)
        if hit is None:
            if not pname:
                raise InteropError(f"{where}: profile {pid!r} not found (give its name to create it)")
            version = _text(row.get("Profile Version")) if self._given(row, "Profile Version") \
                else "1.0"
            hit = P.create_profile(self.repo, pname, version=version,
                                   description=cell_text(row.get("Profile Description")))
            self._pin_id(hit, pid, where)
            self._note(f"created profile {hit.name}")
        if isinstance(hit, Profile):
            changes: dict[str, Any] = {}
            if pname and self._wants(hit, "name", hit.name, pname):
                changes["name"] = pname
            if self._given(row, "Profile Version") and \
                    self._wants(hit, "version", hit.version, _text(row["Profile Version"])):
                changes["version"] = _text(row["Profile Version"])
            if self._given(row, "Profile Description") and self._wants(
                    hit, "description", hit.description, cell_text(row["Profile Description"])):
                changes["description"] = cell_text(row["Profile Description"])
            if changes:
                P.update_profile(self.repo, hit, **changes)
                self._note(f"updated profile {hit.name}", changes)
            if self._given(row, "Root Stereotype"):
                ref = _text(row["Root Stereotype"])
                deferred.append((2, where, lambda: self._set_root(hit, ref)))
        return hit

    def _applies_to(self, value: Any) -> tuple[str, list[type]]:
        """``Applies To``: a profiles category (``Component``) or legacy kinds (``PartUsage;...``)."""
        text = _text(value)
        if text in CATEGORIES:
            return text, []
        classes = [class_for_kind(k.strip()) for k in text.split(";") if k.strip()]
        if None in classes:
            raise InteropError(f"unknown Applies To {text!r}: use one of "
                               f"{[c for c in CATEGORIES if c]} or element kinds")
        return "", classes      # type: ignore[return-value]

    def _stereotype_row(self, container: Element, row: dict, sname: str, sid: str,
                        where: str) -> Stereotype:
        st = self.repo.by_id(sid) if sid else None
        if st is not None and not isinstance(st, Stereotype):
            raise InteropError(f"{where}: Stereotype ID {sid!r} belongs to a {st.kind}")
        if st is None and sname:
            st = next((s for s in container.owned_elements
                       if isinstance(s, Stereotype) and s.name == sname), None)
        category, classes = self._applies_to(row.get("Applies To"))
        style = _parse_pairs(row.get("Style"), STYLE_KEYS, "Style")
        description = cell_text(row.get("Stereotype Description"))
        abstract = _truthy(row.get("Abstract"))
        if st is None:
            if not sname:
                raise InteropError(f"{where}: Stereotype name is required")
            if isinstance(container, Profile):
                st = P.add_stereotype(self.repo, container, sname, description=description,
                                      applies_to=category, abstract=abstract, style=style)
                st.applies_to = classes
            else:                       # legacy stereotype in a plain package (or at the root)
                from engine.hooks import notify_created
                st = Stereotype(sname, applies_to=classes, category=category,
                                description=description, style=style)
                st.is_abstract = abstract
                container.own(st)
                notify_created(st, self.repo)
            self._pin_id(st, sid, where)
            self.report.stereotypes_created += 1
            self._note(f"created stereotype «{st.full_name}»")
            return st
        # An existing stereotype: columns present in the row are applied (checked by
        # engine.profiles; a change that would strip applications is refused).
        changes: dict[str, Any] = {}
        given = lambda col: self._given(row, col)          # noqa: E731
        if sname and self._wants(st, "name", st.name, sname):
            changes["name"] = sname
        if given("Stereotype Description") and \
                self._wants(st, "description", st.description, description):
            changes["description"] = description
        if given("Applies To") and self._wants(st, "applies_to", st.category, category):
            changes["applies_to"] = category
        if given("Abstract") and self._wants(st, "abstract", st.is_abstract, abstract):
            changes["abstract"] = abstract
        if given("Style") and self._wants(st, "style", st.style, normalize_style(style)):
            changes["style"] = style
        if changes:
            P.update_stereotype(self.repo, st, **changes)
        kinds = tuple(id(c) for c in classes)
        if given("Applies To") and \
                self._wants(st, "kinds", tuple(id(c) for c in st.applies_to), kinds):
            st.applies_to = classes
            changes["applies_to"] = classes
        if changes:
            self._note(f"updated «{st.full_name}»", changes)
        return st

    def _set_base(self, st: Stereotype, ref: str) -> None:
        base = self._find_stereotype(ref, "base stereotype") if ref else None
        if self._wants(st, "base", _ident(st.base), _ident(base)):
            P.update_stereotype(self.repo, st, base=base)
            self._note(f"updated «{st.full_name}»", ["base"])

    def _set_defaults(self, st: Stereotype, refs: dict[str, str]) -> None:
        wanted = {slot: self._find_stereotype(refs[slot], f"default {slot} stereotype")
                  if refs.get(slot) else None for slot in DEFAULT_SLOTS}
        current = tuple(_ident(getattr(st, f"default_{s}_stereotype")) for s in DEFAULT_SLOTS)
        if self._wants(st, "defaults", current, tuple(_ident(wanted[s]) for s in DEFAULT_SLOTS)):
            P.update_stereotype(self.repo, st, defaults=wanted)
            self._note(f"updated «{st.full_name}»", ["defaults"])

    def _set_root(self, profile: Profile, ref: str) -> None:
        root = self._find_stereotype(ref, "model root stereotype") if ref else None
        if self._wants(profile, "root", _ident(profile.root_stereotype), _ident(root)):
            P.update_profile(self.repo, profile, root_stereotype=root)
            self._note(f"updated profile {profile.name}", ["root_stereotype"])

    def _find_stereotype(self, ref: str, what: str) -> Stereotype:
        st = self.stereotype(ref)
        if st is None:
            raise InteropError(f"{what} {ref!r} not found")
        return st

    def _property_row(self, st: Stereotype, row: dict, pname: str, pid: str, where: str) -> None:
        tag = self.repo.by_id(pid) if pid else None
        if tag is not None and not (isinstance(tag, StereotypeTag) and tag.stereotype is st):
            raise InteropError(f"{where}: Property ID {pid!r} is not a property of "
                               f"«{st.full_name}»")
        if tag is None and pname:
            tag = next((t for t in st.tags if t.name == pname), None)
        default = row.get("Default")
        default = None if default in (None, "") else default
        if tag is None:
            if not pname:
                raise InteropError(f"{where}: Property name is required")
            ptype = _text(row.get("Type"))
            if ptype:                       # a typed property: checked by engine.profiles
                tag = P.add_property(self.repo, st, pname, ptype, unit=_text(row.get("Unit")),
                                     default=default, minimum=_number_cell(row.get("Min")),
                                     maximum=_number_cell(row.get("Max")),
                                     literals=_text(row.get("Literals")) or None,
                                     description=cell_text(row.get("Description")))
            else:                           # legacy untyped property: any value goes
                if st.find_tag(pname) is not None:
                    raise InteropError(f"{where}: «{st.full_name}» already has a property "
                                       f"named {pname!r}")
                if any(_text(row.get(c)) for c in ("Unit", "Min", "Max", "Literals")):
                    raise InteropError(f"{where}: {pname}: give a Type for a property with a "
                                       "unit, a range or literals")
                from engine.hooks import notify_created
                tag = st.define_tag(pname, default=decode_untyped_cell(None, default))
                tag.description = cell_text(row.get("Description"))
                notify_created(tag, self.repo)
            self._pin_id(tag, pid, where)
            self._note(f"created property {tag.path}")
            return
        changes = self._update_property(tag, row, pname, default)
        if changes:
            self._note(f"updated property {tag.path}", changes)

    def _update_property(self, tag: StereotypeTag, row: dict, pname: str, default: Any) -> list[str]:
        """Apply the definition columns present in the row through ``update_property``.

        The row is checked and put in canonical form by the profiles feature
        (``build_property``); only fields that differ are passed, so an unchanged unit
        cell never overrides the conversion of default / min / max / stored values
        that a unit change makes. Returns the changed fields.
        """
        changes: dict[str, Any] = {}
        name = pname or tag.name
        if name != tag.name:
            changes["name"] = name
        ptype = _text(row["Type"]) if "Type" in row else tag.prop_type
        if ptype != tag.prop_type:
            changes["prop_type"] = ptype            # '' is refused by engine.profiles
        if "Description" in row and cell_text(row["Description"]) != tag.description:
            changes["description"] = cell_text(row["Description"])
        if not ptype:                               # legacy untyped: only the default
            if "Default" in row:
                value = decode_untyped_cell(tag.default_value, default)
                if not _same(value, tag.default_value):
                    changes["default"] = value
            if changes:
                P.update_property(self.repo, tag, **changes)
            return list(changes)
        # Columns missing from the row keep the current definition (what still fits the
        # type); a missing Default is left to update_property, which converts it.
        numeric, same_type = ptype in NUMERIC_TYPES, ptype == tag.prop_type
        cand = build_property(
            name, ptype,
            unit=_text(row["Unit"]) if "Unit" in row else (tag.unit if numeric else ""),
            default=default if "Default" in row else (tag.default_value if same_type else None),
            minimum=_number_cell(row["Min"]) if "Min" in row else (tag.minimum if numeric else None),
            maximum=_number_cell(row["Max"]) if "Max" in row else (tag.maximum if numeric else None),
            literals=(_text(row["Literals"]) or None) if "Literals" in row
            else (tag.literals if ptype == "enumeration" else None),
            label=f"{tag.stereotype.full_name}.{name}" if tag.stereotype else name)
        compared = [("unit", "unit"), ("literals", "literals"), ("minimum", "minimum"),
                    ("maximum", "maximum")] + ([("default", "default_value")] if "Default" in row else [])
        for key, attr in compared:
            new, old = getattr(cand, attr), getattr(tag, attr)
            if not _same(new, old):
                changes[key] = new
        if changes:
            P.update_property(self.repo, tag, **changes)
        return list(changes)

    def stereotype(self, ref: str) -> Optional[Stereotype]:
        """A stereotype named in a table (profiles lookup; legacy ``Package.Stereotype`` too).

        A name the Profiles sheet just changed still finds its stereotype, so element
        rows exported together with the sheet keep working after a rename.
        """
        st = find_stereotype(self.repo, ref)
        if st is None:
            st = self._names_before.get((ref or "").strip())
        return st

    # --- phase 3: create / match elements ------------------------------------
    def owner_of(self, spec: _Spec) -> Optional[Element]:
        id_col, name_col = OWNER_COLUMNS.get(spec.table, ("Owner ID", "Owner"))
        ident, name = _text(spec.row.get(id_col)), _text(spec.row.get(name_col))
        if not ident and not name:
            return self.repo.root_package
        return self.lookup(ident, name)

    def create_all(self) -> None:
        state: dict[int, str] = {}

        def ensure(spec: _Spec) -> None:
            if state.get(id(spec)) == "done":
                return
            if state.get(id(spec)) == "busy":
                raise InteropError(f"{spec.where}: ownership cycle")
            state[id(spec)] = "busy"
            id_col, name_col = OWNER_COLUMNS.get(spec.table, ("Owner ID", "Owner"))
            oid = _text(spec.row.get(id_col))
            if oid and oid in self.by_id:
                ensure(self.by_id[oid])
            owner = self.owner_of(spec)
            if owner is None:
                ref = _text(spec.row.get(name_col)) or oid
                raise InteropError(f"{spec.where}: {name_col.replace(' ID', '').lower()} "
                                   f"{ref!r} not found")
            self._place(spec, owner)
            state[id(spec)] = "done"

        for spec in self.specs:
            ensure(spec)

    def _place(self, spec: _Spec, owner: Element) -> None:
        from engine.serializer import _encode_element
        e = spec.existing
        if e is None and not spec.id:
            e = next((c for c in owner.owned_elements
                      if c.name == spec.name and type(c) is spec.cls), None)
        if e is not None:
            spec.before = _snapshot(e)
            if e.owner is not owner:
                if any(x is owner for x in e.walk()):
                    raise InteropError(f"{spec.where}: cannot move an element into itself")
                move_element(e, owner)
            if spec.name and e.name != spec.name:
                e.name = spec.name
        else:
            e = new_element(spec.cls, spec.name or None, spec.id or None)
            owner.own(e)
            spec.created = True
        spec.element = e
        self.repo.registry.register_tree(e)

    # --- phase 4: attributes and references ----------------------------------
    def set_fields(self, spec: _Spec) -> None:
        e, row = spec.element, spec.row
        assert e is not None
        if "Short Name" in row:
            e.short_name = _text(row["Short Name"]) or None
        if "Abstract" in row and _text(row["Abstract"]):
            e.is_abstract = coerce_like(False, row["Abstract"], "Abstract")
        elif "Abstract" in row and not spec.created:
            e.is_abstract = False
        if "Documentation" in row:
            set_documentation(e, cell_text(row["Documentation"]))
        if isinstance(e, Feature):
            if _text(row.get("Multiplicity")):
                e.multiplicity = parse_multiplicity(_text(row["Multiplicity"]))
            if "Direction" in row:
                e.direction = parse_direction(_text(row.get("Direction")))
        if spec.table == "Requirements":
            for col, attr in (("Req ID", "req_id"), ("Text", "text")):
                if col in row and hasattr(e, attr):
                    setattr(e, attr, _text(row[col]) or None if attr == "req_id"
                            else (cell_text(row[col]) if row[col] not in (None, "") else None))
        known = set(BASE_COLUMNS.get(spec.table, [])) | {"Other End IDs"}
        for col, value in row.items():
            if col in known or "." in col:
                continue
            if col.endswith(" ID") and col[:-3] in REFERENCE_ATTRIBUTES:
                continue
            self._set_extra(spec, col, value)

    def _set_extra(self, spec: _Spec, attr: str, value: Any) -> None:
        e = spec.element
        if not hasattr(e, attr) or attr.startswith("_") or attr in (
                "owner", "element_id", "kind", "owned_elements", "owned_relationships",
                "annotations", "tool_data", "memberships"):
            if value not in (None, ""):
                self.warn_once(f"{spec.table}:{attr}:{spec.kind}",
                               f"{spec.table}: column {attr!r} does not apply to {spec.kind} "
                               "and was ignored")
            return
        current = getattr(e, attr)
        if callable(current) or isinstance(current, Element):
            return
        if value in (None, "") and (spec.created or not isinstance(current, (str, int, float, bool,
                                                                            list, dict))):
            return
        if isinstance(value, str) and value.strip() == NULL_CELL:
            new = None          # no value (an empty cell keeps the default)
        elif value in (None, ""):
            new = class_default(type(e), attr)
        else:
            try:
                new = coerce_like(current if current is not None else class_default(type(e), attr),
                                  value, attr)
            except ValueError as ex:
                raise InteropError(f"{spec.where}: {ex}") from None
        if new == current and type(new) is type(current):
            return
        try:
            setattr(e, attr, new)
        except (ValueError, TypeError) as ex:
            raise InteropError(f"{spec.where}: {attr}: {ex}") from None

    def set_references(self, spec: _Spec) -> None:
        e = spec.element
        assert e is not None
        type_id_col, type_col = TYPE_COLUMNS.get(spec.table, ("Type ID", "Type"))
        types = self.refs(spec, type_id_col, type_col)
        if types is not None and isinstance(e, Feature):
            set_feature_types(e, types)
        elif types:
            raise InteropError(f"{spec.where}: a {spec.kind} cannot have a {type_col.lower()}")
        gens = self.refs(spec, "Specializes ID", "Specializes")
        if gens is not None and hasattr(e, "specializations"):
            set_specializations(e, gens)
        if spec.table == "Connections":
            self._set_ends(spec)
        for attr in REFERENCE_ATTRIBUTES:
            col = f"{attr} ID"
            if col not in spec.row or not hasattr(e, attr):
                continue
            current = getattr(e, attr)
            if not (current is None or isinstance(current, (Element, list))):
                continue            # same name, not a reference here (Profile.source is a dict)
            ids = _split(spec.row[col])
            targets = []
            for ident in ids:
                # An id, or the qualified name of a library element (see _reference_cell).
                hit = self.lookup(ident, ident if "::" in ident else "", allow_root=False)
                if hit is None:
                    raise InteropError(f"{spec.where}: {col} {ident!r} not found")
                targets.append(hit)
            if isinstance(getattr(e, attr), list):
                setattr(e, attr, targets)
            else:
                setattr(e, attr, targets[0] if targets else None)

    def _set_ends(self, spec: _Spec) -> None:
        e, row = spec.element, spec.row
        cols = ("Source Port ID", "Source Port", "Target Port ID", "Target Port")
        if not any(c in row for c in cols):
            return
        ends: list[Element] = []
        comps: list[Optional[Element]] = []
        for side in ("Source", "Target"):
            port = self.refs(spec, f"{side} Port ID", f"{side} Port") or []
            comp = self.refs(spec, f"{side} Component ID", f"{side} Component") or []
            if not port:
                raise InteropError(f"{spec.where}: {side.lower()} port is required")
            ends.append(port[0])
            comps.append(comp[0] if comp else None)
        for ident in _split(row.get("Other End IDs")):
            hit = self.lookup(ident, allow_root=False)
            if hit is None:
                raise InteropError(f"{spec.where}: end {ident!r} not found")
            ends.append(hit)
            comps.append(None)
        if not isinstance(e, ConnectionUsage):
            return
        e.ends = ends  # type: ignore[assignment]
        if hasattr(e, "end_contexts"):
            # The context is the sub-component usage an end is reached through; a
            # boundary port of the composition itself (or a definition) has none.
            composition = e.owner
            ctx = [comp if isinstance(comp, PartUsage) and comp is not composition else None
                   for comp in comps]
            e.end_contexts = tuple(ctx) if any(c is not None for c in ctx) else ()  # type: ignore[attr-defined]

    # --- phase 5: stereotypes -------------------------------------------------
    def apply_stereotypes(self, spec: _Spec) -> None:
        """Make the element's stereotypes those of the ``Stereotypes`` cell, then set values.

        The cell is authoritative, in its order (the first stereotype's style wins).
        One exception, so table rows follow the profiles feature's contract for new
        elements: a row that *adds* an element to an existing project with an empty
        cell keeps the default stereotypes the profiles feature applied on creation.
        """
        e, row = spec.element, spec.row
        assert e is not None
        with _profile_errors(spec.where):
            refs = _split(row.get("Stereotypes"))
            if "Stereotypes" in row and (refs or not spec.created or self.restore):
                wanted: list[Stereotype] = []
                for ref in refs:
                    st = self.stereotype(ref)
                    if st is None:
                        raise InteropError(f"stereotype {ref!r} not found")
                    wanted.append(st)
                for app in stereotypes_on(e):
                    if not any(app.stereotype is st for st in wanted):
                        P.remove_stereotype(self.repo, e, app.stereotype)
                for st in wanted:
                    if not any(a.stereotype is st for a in effective_applications(e)):
                        P.apply_stereotype(self.repo, e, st)
                        self.report.stereotypes_applied += 1
                for a in effective_applications(e):
                    if a.inherited and not any(a.stereotype is st for st in wanted):
                        self.warn_once(f"{spec.where}:inherit:{a.stereotype.element_id}",
                                       f"{spec.where}: «{a.stereotype.full_name}» is inherited from "
                                       f"{a.definition.qualified_name} and stays; remove it there")
                _order_applications(e, wanted)
            # Every value is checked (and converted) by the profiles metamodel when set.
            for app, prop, value in self._stereotype_values(spec):
                # A cell that shows what the element reads anyway (a value inherited from the
                # definition, or the default) sets nothing: only a changed value is an override.
                tag = app.tag(prop)
                stored = tag.coerce(value, f"{app.stereotype.full_name}.{prop}")
                if not app.is_explicit(tag) and stored == app.get(prop):
                    continue
                P.own_application(self.repo, e, app).assign(tag, stored)

    def _stereotype_values(self, spec: _Spec) -> list[tuple[Any, str, Any]]:
        """``Profile.Stereotype.property`` columns of a row as ``(application, property, value)``.

        The column may name the applied stereotype or one of its bases, by any name
        ``engine.profiles`` resolves (and the legacy ``Package.Stereotype``). Typed
        values are converted by profiles on assignment (``'3 lb'`` into a kg property);
        text for a legacy untyped property is read like its current value.
        """
        e, row = spec.element, spec.row
        out: list[tuple[Any, str, Any]] = []
        for col, value in row.items():
            if "." not in col or value in (None, ""):
                continue
            st_ref, prop = col.rsplit(".", 1)
            st = self.stereotype(st_ref)
            app = next((a for a in effective_applications(e)
                        if st is not None and a.stereotype.is_kind_of(st)), None)
            if app is None:
                if st is None:
                    self.warn_once(f"col:{col}", f"column {col!r}: stereotype {st_ref!r} "
                                   "not found; values ignored")
                else:
                    self.warn_once(f"{spec.where}:{col}",
                                   f"{spec.where}: value for {col} ignored because "
                                   f"«{st.full_name}» is not applied")
                continue
            tag = st.find_tag(prop) or self._props_before.get((id(st), prop))
            if tag is None or tag not in st.all_tags():
                raise InteropError(f"«{st.full_name}» has no property {prop!r}")
            prop = tag.name                     # the current name (a rename in the Profiles sheet)
            # A cell still showing the value from before the import is left alone, so a
            # unit or type change made in the Profiles sheet (which converts the stored
            # values) is not undone by the old numbers in an unedited value column.
            before = self._orig_values.get((id(e), id(app.stereotype), id(tag)), _MISSING)
            if before is not _MISSING and (_same(value, before) or (
                    isinstance(value, str) and value.strip() == cell_text(before))):
                continue
            if not tag.prop_type:
                value = decode_untyped_cell(app.get(prop), value)
            out.append((app, prop, value))
        return out

    # --- phase 6: links -------------------------------------------------------
    def import_links(self) -> None:
        from engine.links import create_link, link_kind
        from engine.repository import _detach_relationship
        for rownum, row in self.tables.get("Links", []):
            where = f"Links row {rownum}"
            kind = _text(row.get("Kind"))
            lk = link_kind(kind) if kind else None
            if lk is None:
                raise InteropError(f"{where}: unknown link kind {kind!r}")
            src = self.lookup(_text(row.get("Source ID")), _text(row.get("Source")),
                              allow_root=False)
            tgt = self.lookup(_text(row.get("Target ID")), _text(row.get("Target")),
                              allow_root=False)
            if src is None or tgt is None:
                missing = "source" if src is None else "target"
                ref = _text(row.get(f"{missing.title()}")) or _text(row.get(f"{missing.title()} ID"))
                raise InteropError(f"{where}: {missing} {ref!r} not found")
            ident = _text(row.get("ID"))
            existing = self.repo.by_id(ident) if ident else None
            if existing is not None and not isinstance(existing, Relationship):
                raise InteropError(f"{where}: ID {ident!r} belongs to an element, not a link")
            if isinstance(existing, Relationship):
                if type(existing) is lk.cls and existing.source is src and existing.target is tgt:
                    self.report.links_unchanged += 1
                    continue
                if existing.owner is not None:
                    _detach_relationship(existing.owner, existing)
                self.repo.registry.unregister(existing)
            dup = next((r for r in src.owned_relationships
                        if type(r) is lk.cls and r.source is src and r.target is tgt), None)
            if dup is not None:
                self.report.links_unchanged += 1
                continue
            rel = create_link(kind, src, tgt)
            if ident:
                rel.element_id = ident
            self.repo.registry.register(rel)
            self.report.links_created += 1

    # --- phase 7: tool data and project data -------------------------------------
    def import_tool_data(self) -> None:
        """``Tool Data`` rows set ``Element.tool_data`` (layout, port sides, waypoints, ...).

        A project rebuilt from tables (``restore``) takes every row, and elements without
        rows get none; an import into the current project only gives tool data to the
        elements it creates, so a workbook exported earlier does not move existing blocks
        back to where they were then.
        """
        rows = self.tables.get(TOOL_DATA)
        if rows is None:
            return
        created = {id(s.element) for s in self.specs if s.created and s.element is not None}
        data: dict[int, tuple[Element, dict]] = {}
        for rownum, row in rows:
            where = f"{TOOL_DATA} row {rownum}"
            ident, key = _text(row.get("ID")), _text(row.get("Key"))
            if not ident or not key:
                raise InteropError(f"{where}: needs an ID and a Key")
            e = self.lookup(ident)
            if e is None:
                self.warn_once(f"tool:{ident}", f"{where}: element {ident!r} not found; "
                                                "its tool data was ignored")
                continue
            raw = row.get("Value")
            try:
                value = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                raise InteropError(f"{where} ({key}): Value is not valid JSON") from None
            data.setdefault(id(e), (e, {}))[1][key] = value
        if self.restore:
            # The sheet lists all tool data of the project: elements without rows have none.
            for e in self.repo.root_package.walk():
                if not isinstance(e, Relationship):
                    e.tool_data = dict(data[id(e)][1]) if id(e) in data else {}
            return
        for key, (e, values) in data.items():
            if key in created:
                e.tool_data = dict(values)

    def import_project_data(self) -> None:
        """Model sheet ``Data: <codec>`` rows: project-level feature state (suspect-link
        baselines, the architecture type, ...) of a project rebuilt from tables."""
        from engine.serializer import _REPO_CODECS, _library_index
        chunks: dict[str, list[str]] = {}
        for _rownum, row in self.tables.get("Model", []):
            prop = _text(row.get("Property"))
            if prop.startswith(PROJECT_DATA_PREFIX):
                chunks.setdefault(prop[len(PROJECT_DATA_PREFIX):].strip(), []).append(
                    cell_text(row.get("Value")))
        if not chunks:
            return
        by_id = _library_index()
        by_id.update({e.element_id: e for e in self.repo.root_package.walk()})
        for name, parts in chunks.items():
            try:
                data = json.loads("".join(parts))
            except ValueError:
                raise InteropError(f"Model sheet: {PROJECT_DATA_PREFIX}{name} is not valid JSON") \
                    from None
            codec = _REPO_CODECS.get(name)
            if codec is None:
                self.warnings.append(f"Model sheet: project data {name!r} was ignored "
                                     "(no feature of this studio stores it)")
                continue
            codec[2](self.repo, data, by_id)

    # --- sibling order --------------------------------------------------------------
    def restore_order(self) -> None:
        """Order new elements among their siblings as the table rows imply.

        Rows of each table are in containment (walk) order, but owners are created on
        demand, so a package referenced by an early row can land ahead of siblings listed
        before it. Consecutive rows of a table give "branch A before branch B" at their
        common ancestor; each owner that received new elements is sorted to satisfy those
        constraints (stable, so unconstrained siblings keep their order). This makes
        export -> import -> export reproduce the same rows in the same order.
        """
        touched = {id(s.element.owner) for s in self.specs
                   if s.created and s.element is not None and s.element.owner is not None}
        if not touched:
            return

        def chain(e: Element) -> list[Element]:
            out: list[Element] = []
            while e is not None:
                out.append(e)
                e = e.owner
            return out[::-1]

        edges: dict[int, dict[int, set[int]]] = {}
        owners: dict[int, Element] = {}
        for table in ELEMENT_TABLES:
            seq = [s.element for s in self.specs if s.table == table and s.element is not None]
            for a, b in zip(seq, seq[1:]):
                ca, cb = chain(a), chain(b)
                i = 0
                while i < min(len(ca), len(cb)) and ca[i] is cb[i]:
                    i += 1
                if i == 0 or i >= len(ca) or i >= len(cb):
                    continue                  # different trees, or one contains the other
                owner = ca[i - 1]
                if id(owner) in touched:
                    owners[id(owner)] = owner
                    edges.setdefault(id(owner), {}).setdefault(id(ca[i]), set()).add(id(cb[i]))
        import heapq
        for key, owner in owners.items():
            children = list(owner.owned_elements)
            pos = {id(c): n for n, c in enumerate(children)}
            succ = edges[key]
            indeg = dict.fromkeys(pos, 0)
            for a, bs in succ.items():
                for b in bs:
                    if a in pos and b in pos:
                        indeg[b] += 1
            heap = [(pos[k], k) for k, d in indeg.items() if d == 0]
            heapq.heapify(heap)
            ordered: list[Element] = []
            while heap:
                _, k = heapq.heappop(heap)
                ordered.append(children[pos[k]])
                for b in succ.get(k, ()):
                    if b in indeg:
                        indeg[b] -= 1
                        if indeg[b] == 0:
                            heapq.heappush(heap, (pos[b], b))
            if len(ordered) != len(children) or ordered == children:
                continue                      # inconsistent rows (cycle) or already in order
            owner.owned_elements[:] = ordered
            rank = {id(c): n for n, c in enumerate(ordered)}
            if isinstance(getattr(owner, "memberships", None), list):
                owner.memberships.sort(key=lambda m: rank.get(id(m.member), len(rank)))

    # --- driver -----------------------------------------------------------------
    def run(self) -> ImportReport:
        from engine.hooks import notify_created
        self.parse_rows()
        # Stereotype values and names before the import (see _stereotype_values, stereotype).
        self._orig_values = {(id(e), id(a.stereotype), id(t)): a.get(t.name)
                             for e in P.model_elements(self.repo)
                             for a in effective_applications(e) for t in a.stereotype.all_tags()}
        names: dict[str, list[Stereotype]] = {}
        for st in P.stereotypes_of(self.repo):
            names.setdefault(st.full_name, []).append(st)
            self._props_before.update({(id(st), t.name): t for t in st.all_tags()})
        self._names_before = {n: sts[0] for n, sts in names.items() if len(sts) == 1}
        self.create_all()
        self.import_profiles()          # after elements: a profile may be a package row
        for spec in self.specs:
            self.set_fields(spec)
        for spec in self.specs:
            self.set_references(spec)
        for spec in self.specs:
            if spec.created:
                notify_created(spec.element, self.repo)  # type: ignore[arg-type]
        # Definitions before the usages typed by them: a reference component reads (and a cell
        # equal to it leaves inherited) the values its definition gets in this very import.
        for spec in sorted(self.specs, key=lambda sp: inheritance_source(sp.element) is not None):
            self.apply_stereotypes(spec)
        self.import_links()
        self.restore_order()
        self.repo.registry.register_tree(self.repo.root_package)
        self.import_tool_data()
        if self.restore:
            self.import_project_data()
        for spec in self.specs:
            eid = spec.element.element_id  # type: ignore[union-attr]
            if spec.created:
                self.report.created.append(eid)
            elif spec.before != _snapshot(spec.element):  # type: ignore[arg-type]
                self.report.updated.append(eid)
            else:
                self.report.unchanged.append(eid)
        return self.report


def _order_applications(e: Element, order: list[Stereotype]) -> None:
    """Put the element's stereotype applications in ``order`` (other annotations stay put)."""
    apps = stereotypes_on(e)
    rank = {id(st): i for i, st in enumerate(order)}
    ordered = sorted(apps, key=lambda a: rank.get(id(a.stereotype), len(rank)))
    if [id(a) for a in ordered] == [id(a) for a in apps]:
        return
    slots = iter(ordered)
    e.annotations = [next(slots) if any(a is x for x in apps) else a for a in e.annotations]


def _snapshot(e: Element) -> str:
    """Serialized form of one element (a detached copy, to detect updates)."""
    import json
    from engine.serializer import _encode_element
    return json.dumps(_encode_element(e), sort_keys=True, default=str)


def _join_errors(errors: list[str], limit: int = 25) -> str:
    more = f"\n... and {len(errors) - limit} more" if len(errors) > limit else ""
    return "\n".join(errors[:limit]) + more


def _restore(repo, data: dict) -> None:
    """Put `repo` back (in place, the same object) to a state saved with ``to_dict``."""
    from engine.serializer import from_dict
    fresh = from_dict(data)
    repo.__dict__.clear()
    repo.__dict__.update(fresh.__dict__)


def import_tables(repo, sheets: Any, *, atomic: bool = True) -> ImportReport:
    """Create or update elements of `repo` from tables; raises InteropError on bad input.

    With ``atomic`` (default) the import is first rehearsed on a copy of the
    project, so a failing import leaves `repo` untouched; should the real run still
    fail, the project is restored from a snapshot taken just before it.
    """
    if not atomic:
        return _Importer(repo, sheets).run()
    from engine.serializer import from_dict, to_dict
    before = to_dict(repo)
    _Importer(from_dict(before), sheets).run()      # rehearsal on a copy
    try:
        return _Importer(repo, sheets).run()
    except BaseException:
        _restore(repo, before)
        raise


def tables_to_project(sheets: Any, name: Optional[str] = None):
    """Build a new Repository from tables (keeps the exported root id). Returns (repo, report)."""
    from engine.repository import Repository
    probe = _Importer(Repository("probe"), sheets)
    repo = Repository(name=name or probe.model_name or "ImportedProject")
    info = {_text(r.get("Property")): r.get("Value") for _, r in probe.tables.get("Model", [])}
    root_id = _text(info.get("Root ID"))
    if root_id:
        repo.registry.unregister(repo.root_package)
        repo.root_package.element_id = root_id
        repo.registry.register(repo.root_package)
    if _text(info.get("Documentation")):
        set_documentation(repo.root_package, cell_text(info.get("Documentation")))
    report = _Importer(repo, sheets, restore=True).run()
    return repo, report


# =============================================================================
# ModelBuilder
# =============================================================================

class ModelBuilder:
    """Build architecture tables incrementally, then the model (``systemcomposer.io.ModelBuilder``).

        b = ModelBuilder("Avionics")
        sys = b.add_component("FlightDeck")                 # architecture (PartDefinition)
        fms = b.add_component("FMS", parent_id=sys)          # component (PartUsage)
        out = b.add_port("navOut", "out", fms)
        ...
        repo = b.build()                                     # or b.build(existing_repo)

    Every ``add_*`` returns the new row's ID, used to reference it from later rows.
    """

    def __init__(self, name: str = "Model"):
        self.name = name
        self.root_id = str(uuid.uuid4())
        self.rows: dict[str, list[dict]] = {t: [] for t in TABLE_ORDER if t != "Model"}
        self._kinds: dict[str, str] = {}

    @staticmethod
    def _id(given: Optional[str]) -> str:
        return given or str(uuid.uuid4())

    def _stereo_cols(self, row: dict, stereotypes: Optional[Iterable[str]],
                     values: Optional[dict]) -> dict:
        if stereotypes:
            row["Stereotypes"] = ";".join(stereotypes)
        for k, v in (values or {}).items():
            row[k] = v
        return row

    def add_component(self, name: str, *, parent_id: Optional[str] = None,
                      reference_id: Optional[str] = None, kind: Optional[str] = None,
                      id: Optional[str] = None, multiplicity: Optional[str] = None,
                      doc: str = "", stereotypes: Optional[Iterable[str]] = None,
                      values: Optional[dict] = None, **extra: Any) -> str:
        """A component; without `parent_id` (and `reference_id`) it is an architecture."""
        ident = self._id(id)
        if kind is None:
            if reference_id or self._kinds.get(parent_id or "") in ("PartDefinition", "PartUsage"):
                kind = "PartUsage"
            elif not parent_id or parent_id in self._kinds:
                kind = "PartDefinition"
            else:
                kind = ""        # parent outside this builder: the importer decides
        self._kinds[ident] = kind or "PartUsage"
        row = {"ID": ident, "Name": name, "Kind": kind, "Parent ID": parent_id or self.root_id,
               "Reference ID": reference_id or "", "Multiplicity": multiplicity or "",
               "Documentation": doc, **extra}
        self.rows["Components"].append(self._stereo_cols(row, stereotypes, values))
        return ident

    def add_port(self, name: str, direction: str, component_id: str, *,
                 interface_id: Optional[str] = None, id: Optional[str] = None,
                 kind: str = "PortUsage", doc: str = "",
                 stereotypes: Optional[Iterable[str]] = None, values: Optional[dict] = None,
                 **extra: Any) -> str:
        ident = self._id(id)
        self._kinds[ident] = kind
        row = {"ID": ident, "Name": name, "Kind": kind, "Component ID": component_id,
               "Direction": direction or "", "Interface ID": interface_id or "",
               "Documentation": doc, **extra}
        self.rows["Ports"].append(self._stereo_cols(row, stereotypes, values))
        return ident

    def add_connection(self, name: str, source_port_id: str, target_port_id: str, *,
                       owner_id: str, source_component_id: Optional[str] = None,
                       target_component_id: Optional[str] = None, id: Optional[str] = None,
                       kind: str = "ConnectionUsage", doc: str = "",
                       stereotypes: Optional[Iterable[str]] = None,
                       values: Optional[dict] = None, **extra: Any) -> str:
        """A connector owned by the composition `owner_id` it wires."""
        ident = self._id(id)
        row = {"ID": ident, "Name": name, "Kind": kind, "Owner ID": owner_id,
               "Source Component ID": source_component_id or "",
               "Source Port ID": source_port_id,
               "Target Component ID": target_component_id or "",
               "Target Port ID": target_port_id, "Documentation": doc, **extra}
        self.rows["Connections"].append(self._stereo_cols(row, stereotypes, values))
        return ident

    def add_interface(self, name: str, *, owner_id: Optional[str] = None,
                      kind: str = "PortDefinition", id: Optional[str] = None, doc: str = "",
                      stereotypes: Optional[Iterable[str]] = None,
                      values: Optional[dict] = None, **extra: Any) -> str:
        ident = self._id(id)
        self._kinds[ident] = kind
        row = {"ID": ident, "Name": name, "Kind": kind, "Owner ID": owner_id or self.root_id,
               "Documentation": doc, **extra}
        self.rows["Interfaces"].append(self._stereo_cols(row, stereotypes, values))
        return ident

    def add_element_in_interface(self, name: str, interface_id: str, *,
                                 type: Optional[str] = None, type_id: Optional[str] = None,
                                 kind: str = "AttributeUsage", direction: str = "",
                                 multiplicity: Optional[str] = None, id: Optional[str] = None,
                                 doc: str = "", **extra: Any) -> str:
        """An interface element; `type` is a qualified name such as ``ScalarValues::Real``."""
        ident = self._id(id)
        row = {"ID": ident, "Name": name, "Kind": kind, "Owner ID": interface_id,
               "Type ID": type_id or "", "Type": type or "", "Direction": direction,
               "Multiplicity": multiplicity or "", "Documentation": doc, **extra}
        self.rows["Interfaces"].append(row)
        return ident

    def add_requirement(self, name: str, *, req_id: str = "", text: str = "",
                        owner_id: Optional[str] = None, kind: str = "RequirementDefinition",
                        id: Optional[str] = None, doc: str = "",
                        stereotypes: Optional[Iterable[str]] = None,
                        values: Optional[dict] = None, **extra: Any) -> str:
        ident = self._id(id)
        row = {"ID": ident, "Req ID": req_id, "Name": name, "Kind": kind,
               "Owner ID": owner_id or self.root_id, "Text": text, "Documentation": doc,
               **extra}
        self.rows["Requirements"].append(self._stereo_cols(row, stereotypes, values))
        return ident

    def add_element(self, name: str, kind: str, *, owner_id: Optional[str] = None,
                    type_id: Optional[str] = None, id: Optional[str] = None, doc: str = "",
                    **extra: Any) -> str:
        """Any other element (Package, AttributeDefinition, ActionDefinition, ...)."""
        ident = self._id(id)
        self._kinds[ident] = kind
        row = {"ID": ident, "Name": name, "Kind": kind, "Owner ID": owner_id or self.root_id,
               "Type ID": type_id or "", "Documentation": doc, **extra}
        self.rows["Elements"].append(row)
        return ident

    def add_link(self, kind: str, source_id: str, target_id: str, *,
                 id: Optional[str] = None) -> str:
        ident = self._id(id)
        self.rows["Links"].append({"ID": ident, "Kind": kind, "Source ID": source_id,
                                   "Target ID": target_id})
        return ident

    def add_stereotype(self, name: str, *, profile: str = "", applies_to: str = "",
                       properties: Optional[Iterable[Any]] = None, base: str = "",
                       id: Optional[str] = None) -> str:
        """A stereotype; `properties` are names or ``(name, default)`` (legacy untyped
        properties) or dict rows with Profiles columns (``{"Property": "mass", "Type":
        "double", "Unit": "kg", "Default": 0, "Min": 0}``). With `profile`, the stereotype
        belongs to that profile (created by engine.profiles when missing). Returns the
        name to use in ``stereotypes=`` / value columns (``Profile.Stereotype``)."""
        ident = self._id(id)
        base_row = {"Profile": profile, "Stereotype ID": ident, "Stereotype": name}
        if base:                # only cells that say something (an existing stereotype keeps
            base_row["Base"] = base          # the definition the builder does not mention)
        if applies_to:
            base_row["Applies To"] = applies_to
        props = list(properties or [])
        if not props:
            self.rows["Profiles"].append(dict(base_row))
        for p in props:
            if isinstance(p, dict):
                self.rows["Profiles"].append({**base_row, **p})
            elif isinstance(p, (tuple, list)):
                self.rows["Profiles"].append({**base_row, "Property": p[0],
                                              "Default": p[1] if len(p) > 1 else ""})
            else:
                self.rows["Profiles"].append({**base_row, "Property": str(p)})
        return f"{profile}.{name}" if profile else name

    def tables(self) -> Sheets:
        sheets: Sheets = {"Model": [["Property", "Value"], ["Format", FORMAT],
                                    ["Name", self.name], ["Root ID", self.root_id]]}
        for t in TABLE_ORDER[1:]:
            rows = self.rows[t]
            if t == TOOL_DATA:
                continue                    # the builder makes no layout
            if t == "Profiles":
                # Only the columns the builder filled: a blank profile / stereotype cell would
                # clear that setting of a profile that already exists in the target project.
                used = {k for r in rows for k in r}
                base = [c for c in PROFILE_COLUMNS if c in used]
            else:
                base = LINK_COLUMNS if t == "Links" else BASE_COLUMNS[t]
            sheets[t] = _sheet(_columns(base, rows), rows)
        return sheets

    def build(self, repo=None):
        """Create the model: a new project (returned) or merged into `repo` (returns the report)."""
        if repo is None:
            built, _report = tables_to_project(self.tables(), self.name)
            return built
        return import_tables(repo, self.tables())
