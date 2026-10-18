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
``Profile.Stereotype.property`` columns. Further columns are discovered from the
elements themselves (any JSON-able attribute whose value differs from the
default, e.g. ``port_kind`` or ``rationale``), so attributes added by other
features round-trip without changes here.

``import_tables(repo, sheets)`` creates or updates elements matched by ``ID``
(falling back to owner + name), so export -> import preserves ids; it is atomic
(a dry run on a copy of the project must succeed first). ``ModelBuilder`` builds
the same tables incrementally from Python and then the model.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from kerml.elements import Element, Relationship
from kerml.features import Feature, FeatureDirection
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, StereotypeTag, stereotypes_on
from sysmlv2.definitions import (
    ConnectionUsage, Definition, InterfaceDefinition, PartDefinition, PartUsage,
    PortDefinition, PortUsage, RequirementDefinition, RequirementUsage,
)

from .common import (
    InteropError, cell_text, class_default, class_for_kind, coerce_like, documentation,
    extra_attributes, format_multiplicity, in_library, infer_scalar, is_profile_content,
    link_kind_name, model_links, move_element, new_element, parse_direction,
    parse_multiplicity, project_elements, relative_qname, resolve_qname, set_documentation,
    set_feature_types, set_specializations, stereotype_full_name, stereotype_tags,
)

FORMAT = "sysml-studio-tables/1"
TABLE_ORDER = ["Model", "Profiles", "Components", "Ports", "Interfaces", "Connections",
               "Requirements", "Elements", "Links"]
ELEMENT_TABLES = ["Components", "Ports", "Interfaces", "Connections", "Requirements", "Elements"]

# Element-valued attributes exported as "<attr> ID" columns (features may add theirs).
REFERENCE_ATTRIBUTES: list[str] = [
    "transition_source", "transition_target", "initial_state", "final_states",
    "allocate_from", "allocate_to", "payload_type", "flow_source", "flow_target",
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
PROFILE_COLUMNS = ["Profile ID", "Profile", "Stereotype ID", "Stereotype", "Base", "Applies To",
                   "Abstract", "Property ID", "Property", "Type", "Unit", "Default", "Description"]
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
    apps = stereotypes_on(e)
    row["Stereotypes"] = ";".join(stereotype_full_name(a.stereotype) for a in apps)
    for a in apps:
        full = stereotype_full_name(a.stereotype)
        for tag in stereotype_tags(a.stereotype):
            v = (getattr(a, "values", {}) or {}).get(tag.name)
            row[f"{full}.{tag.name}"] = v
    for attr in REFERENCE_ATTRIBUTES:
        if not hasattr(e, attr):
            continue
        v = getattr(e, attr)
        if isinstance(v, Element):
            row[f"{attr} ID"] = v.element_id
        elif isinstance(v, list) and v and all(isinstance(x, Element) for x in v):
            row[f"{attr} ID"] = ";".join(x.element_id for x in v)
    allowed = set(BASE_COLUMNS[table]) | ({"Other End IDs"} if table == "Connections" else set())
    row = {k: v for k, v in row.items() if k in allowed or k not in _ALL_BASE}
    for k, v in extra_attributes(e).items():
        row.setdefault(k, v)
    return row


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


def _profile_rows(repo) -> list[dict]:
    rows: list[dict] = []
    for st in [e for e in repo.root_package.walk() if isinstance(e, Stereotype)]:
        owner = st.owner
        profile_id = owner.element_id if owner is not None and owner is not repo.root_package else ""
        profile = owner.name if profile_id else ""
        applies = getattr(st, "category", "") or ";".join(
            getattr(c, "kind", c.__name__) for c in getattr(st, "applies_to", []) or [])
        base_row = {"Profile ID": profile_id, "Profile": profile or "",
                    "Stereotype ID": st.element_id, "Stereotype": st.name or "",
                    "Base": stereotype_full_name(st.base) if getattr(st, "base", None) else "",
                    "Applies To": applies,
                    "Abstract": True if getattr(st, "is_abstract", False) else ""}
        own_tags = [t for t in getattr(st, "tags", []) if isinstance(t, StereotypeTag)]
        if not own_tags:
            rows.append({**base_row, "Property ID": "", "Property": ""})
        for t in own_tags:
            rows.append({**base_row, "Property ID": t.element_id, "Property": t.name or "",
                         "Type": getattr(t, "prop_type", "") or "",
                         "Unit": getattr(t, "unit", "") or "",
                         "Default": t.default_value,
                         "Description": getattr(t, "description", "") or ""})
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
                  ["Root ID", repo.root_package.element_id]],
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
    return sheets


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

    def to_dict(self) -> dict:
        return {"created": len(self.created), "updated": len(self.updated),
                "unchanged": len(self.unchanged), "links_created": self.links_created,
                "links_unchanged": self.links_unchanged,
                "stereotypes_created": self.stereotypes_created,
                "stereotypes_applied": self.stereotypes_applied,
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
    key = name.lower().replace(" ", "")
    for t in TABLE_ORDER:
        if t.lower() == key or t.lower() == key.rstrip("s") + "s":
            return t
    aliases = {"component": "Components", "port": "Ports", "connection": "Connections",
               "connectors": "Connections", "interface": "Interfaces",
               "portinterfaces": "Interfaces", "requirement": "Requirements",
               "element": "Elements", "link": "Links", "requirementlinks": "Links",
               "stereotypes": "Profiles", "profile": "Profiles"}
    return aliases.get(key)


def _canonical_columns(table: str, row: dict) -> dict:
    known = BASE_COLUMNS.get(table, []) + LINK_COLUMNS + PROFILE_COLUMNS + ["Property", "Value"]
    by_low = {c.lower(): c for c in known}
    return {by_low.get(k.lower(), k): v for k, v in row.items()}


class _Importer:
    def __init__(self, repo, sheets: Any):
        self.repo = repo
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
        self.stereo_by_ref: dict[str, Stereotype] = {}
        self.report = ImportReport(warnings=self.warnings)
        self._warned: set[str] = set()

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
    def import_profiles(self) -> None:
        from kerml.stereotypes import Stereotype as BaseStereotype
        rows = self.tables.get("Profiles", [])
        pending_bases: list[tuple[Stereotype, str, str]] = []
        for rownum, row in rows:
            where = f"Profiles row {rownum}"
            sname = _text(row.get("Stereotype"))
            sid = _text(row.get("Stereotype ID"))
            if not sname and not sid:
                continue
            st = self.stereo_by_ref.get(sid) if sid else None
            if st is None and sid:
                hit = self.repo.by_id(sid)
                st = hit if isinstance(hit, Stereotype) else None
            profile = self._profile(row, where)
            if st is None:
                full = f"{profile.name}.{sname}" if profile is not self.repo.root_package else sname
                st = next((s for s in self.repo.root_package.walk() if isinstance(s, Stereotype)
                           and (stereotype_full_name(s) == full or
                                (s.owner is profile and s.name == sname))), None)
            if st is None:
                if not sname:
                    raise InteropError(f"{where}: Stereotype name is required")
                cls = class_for_kind("Stereotype") or BaseStereotype
                st = cls(name=sname)
                if sid:
                    st.element_id = sid
                profile.own(st)
                self._apply_applies_to(st, _text(row.get("Applies To")), where)
                if _text(row.get("Abstract")).lower() in ("true", "1", "yes"):
                    try:
                        st.is_abstract = True
                    except Exception as ex:  # noqa: BLE001
                        raise InteropError(f"{where}: {ex}") from None
                self.repo.registry.register_tree(st)
                self.report.stereotypes_created += 1
                if _text(row.get("Base")):
                    pending_bases.append((st, _text(row.get("Base")), where))
            if sid:
                self.stereo_by_ref[sid] = st
            self.stereo_by_ref[stereotype_full_name(st)] = st
            pname = _text(row.get("Property"))
            if pname and not any(t.name == pname for t in stereotype_tags(st)):
                self._define_property(st, row, pname, where)
        for st, base_ref, where in pending_bases:
            base = self.stereotype(base_ref)
            if base is None:
                raise InteropError(f"{where}: base stereotype {base_ref!r} not found")
            st.base = base

    def _profile(self, row: dict, where: str) -> Namespace:
        pid, pname = _text(row.get("Profile ID")), _text(row.get("Profile"))
        if not pid and not pname:
            return self.repo.root_package
        hit = self.repo.by_id(pid) if pid else None
        if isinstance(hit, Namespace):
            return hit
        if pname:
            hit = next((e for e in self.repo.root_package.owned_elements
                        if isinstance(e, Package) and e.name == pname), None)
            if hit is not None:
                return hit
        cls = class_for_kind("Profile") or Package
        prof = new_element(cls, pname or "Profile", pid or None)
        self.repo.root_package.own(prof)
        self.repo.registry.register_tree(prof)
        return prof

    def _apply_applies_to(self, st: Stereotype, value: str, where: str) -> None:
        if not value:
            return
        kinds = [k.strip() for k in value.split(";") if k.strip()]
        classes = [class_for_kind(k) for k in kinds]
        if all(c is not None for c in classes):
            st.applies_to = classes  # type: ignore[assignment]
        elif hasattr(st, "category"):
            try:
                st.category = value
            except Exception as ex:  # noqa: BLE001
                raise InteropError(f"{where}: {ex}") from None
        else:
            raise InteropError(f"{where}: unknown Applies To {value!r}")

    def _define_property(self, st: Stereotype, row: dict, pname: str, where: str) -> None:
        default = row.get("Default")
        default = None if default in ("", None) else default
        ptype, unit = _text(row.get("Type")), _text(row.get("Unit"))
        try:
            if hasattr(st, "define_property") and ptype:
                kwargs: dict[str, Any] = {"unit": unit, "default": default}
                if _text(row.get("Description")):
                    kwargs["description"] = _text(row.get("Description"))
                tag = st.define_property(pname, ptype, **kwargs)
            else:
                tag = st.define_tag(pname, default=infer_scalar(default)
                                    if isinstance(default, str) else default)
        except Exception as ex:  # noqa: BLE001 - profile errors carry the reason
            raise InteropError(f"{where}: {ex}") from None
        if _text(row.get("Property ID")):
            self.repo.registry.unregister(tag)
            tag.element_id = _text(row.get("Property ID"))
        self.repo.registry.register_tree(tag)

    def stereotype(self, ref: str) -> Optional[Stereotype]:
        from .common import find_stereotype
        return self.stereo_by_ref.get(ref) or find_stereotype(self.repo, ref)

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
        if value in (None, ""):
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
            ids = _split(spec.row[col])
            targets = []
            for ident in ids:
                hit = self.lookup(ident, allow_root=False)
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
        e, row = spec.element, spec.row
        assert e is not None
        if "Stereotypes" in row:
            wanted: list[Stereotype] = []
            for ref in _split(row["Stereotypes"]):
                st = self.stereotype(ref)
                if st is None:
                    raise InteropError(f"{spec.where}: stereotype {ref!r} not found")
                wanted.append(st)
            current = stereotypes_on(e)
            for app in current:
                if not any(app.stereotype is st for st in wanted):
                    e.annotations = [a for a in e.annotations if a is not app]
            for st in wanted:
                if not any(a.stereotype is st for a in stereotypes_on(e)):
                    try:
                        st.apply(e, {})
                    except Exception as ex:  # noqa: BLE001 - TypeError / StereotypeError
                        raise InteropError(f"{spec.where}: {ex}") from None
                    self.report.stereotypes_applied += 1
        for col, value in row.items():
            if "." not in col or value in (None, ""):
                continue
            st_ref, prop = col.rsplit(".", 1)
            app = next((a for a in stereotypes_on(e)
                        if stereotype_full_name(a.stereotype) == st_ref
                        or a.stereotype.name == st_ref), None)
            if app is None:
                st = self.stereotype(st_ref)
                if st is None:
                    self.warn_once(f"col:{col}", f"column {col!r}: stereotype {st_ref!r} "
                                   "not found; values ignored")
                else:
                    self.warn_once(f"{spec.where}:{col}",
                                   f"{spec.where}: value for {col} ignored because "
                                   f"«{st_ref}» is not applied")
                continue
            self._set_value(spec, app, prop, value)

    def _set_value(self, spec: _Spec, app, prop: str, value: Any) -> None:
        tags = {t.name: t for t in stereotype_tags(app.stereotype)}
        if prop not in tags:
            raise InteropError(f"{spec.where}: «{stereotype_full_name(app.stereotype)}» "
                               f"has no property {prop!r}")
        setter = getattr(app, "set", None)
        try:
            if callable(setter):
                if getattr(app, "values", {}).get(prop) == value:
                    return
                setter(prop, value)
            else:
                default = tags[prop].default_value
                if default is not None and not isinstance(default, (list, dict)):
                    new = coerce_like(default, value, prop)
                else:
                    new = infer_scalar(value) if isinstance(value, str) else value
                app.values[prop] = new
        except InteropError:
            raise
        except Exception as ex:  # noqa: BLE001 - coercion errors name the property
            raise InteropError(f"{spec.where}: {stereotype_full_name(app.stereotype)}.{prop}: "
                               f"{ex}") from None

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

    # --- driver -----------------------------------------------------------------
    def run(self) -> ImportReport:
        from engine.hooks import notify_created
        self.parse_rows()
        self.create_all()
        self.import_profiles()          # after elements: a profile may be a package row
        for spec in self.specs:
            self.set_fields(spec)
        for spec in self.specs:
            self.set_references(spec)
        for spec in self.specs:
            if spec.created:
                notify_created(spec.element, self.repo)  # type: ignore[arg-type]
        for spec in self.specs:
            self.apply_stereotypes(spec)
        self.import_links()
        self.repo.registry.register_tree(self.repo.root_package)
        for spec in self.specs:
            eid = spec.element.element_id  # type: ignore[union-attr]
            if spec.created:
                self.report.created.append(eid)
            elif spec.before != _snapshot(spec.element):  # type: ignore[arg-type]
                self.report.updated.append(eid)
            else:
                self.report.unchanged.append(eid)
        return self.report


def _snapshot(e: Element) -> str:
    """Serialized form of one element (a detached copy, to detect updates)."""
    import json
    from engine.serializer import _encode_element
    return json.dumps(_encode_element(e), sort_keys=True, default=str)


def _join_errors(errors: list[str], limit: int = 25) -> str:
    more = f"\n... and {len(errors) - limit} more" if len(errors) > limit else ""
    return "\n".join(errors[:limit]) + more


def _clone(repo):
    from engine.serializer import from_dict, to_dict
    return from_dict(to_dict(repo))


def import_tables(repo, sheets: Any, *, atomic: bool = True) -> ImportReport:
    """Create or update elements of `repo` from tables; raises InteropError on bad input.

    With ``atomic`` (default) the import is first rehearsed on a copy of the
    project, so a failing import leaves `repo` untouched.
    """
    if atomic:
        _Importer(_clone(repo), sheets).run()
    return _Importer(repo, sheets).run()


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
    report = _Importer(repo, sheets).run()
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
        """A stereotype; `properties` are names or ``(name, default)`` / dict rows
        (``{"Property": "mass", "Type": "double", "Unit": "kg", "Default": 0}``).
        Returns the full name to use in ``stereotypes=`` / value columns."""
        ident = self._id(id)
        base_row = {"Profile": profile, "Stereotype ID": ident, "Stereotype": name,
                    "Base": base, "Applies To": applies_to}
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
            base = (PROFILE_COLUMNS if t == "Profiles" else LINK_COLUMNS if t == "Links"
                    else BASE_COLUMNS[t])
            sheets[t] = _sheet(_columns(base, rows), rows)
        return sheets

    def build(self, repo=None):
        """Create the model: a new project (returned) or merged into `repo` (returns the report)."""
        if repo is None:
            built, _report = tables_to_project(self.tables(), self.name)
            return built
        return import_tables(repo, self.tables())
