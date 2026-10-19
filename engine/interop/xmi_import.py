"""Import a SysML 1.x model from XMI 2.5.1 (the subset Cameo / MagicDraw export).

Mapping
-------
==============================================  ========================================
XMI (UML + SysML 1.x stereotypes)               SysML v2 element
==============================================  ========================================
``uml:Model`` / ``uml:Package``                 ``Package``
``uml:Class`` «Block»                           ``PartDefinition``
``uml:Class`` «InterfaceBlock»                  ``PortDefinition`` (flow properties become
                                                directed ``AttributeUsage`` elements)
``uml:Class`` «Requirement» (Id, Text)          ``RequirementDefinition`` (req_id, text)
``uml:Class`` «ConstraintBlock»                 ``ConstraintDefinition``
``uml:DataType`` / «ValueType» / PrimitiveType  ``AttributeDefinition``
``uml:Enumeration`` + literals                  ``EnumerationDefinition`` + literals
``uml:Signal``                                  ``ItemDefinition``
``uml:Activity`` / «TestCase»                   ``ActionDefinition`` / ``VerificationCaseDefinition``
``uml:StateMachine``                            ``StateDefinition`` (name only)
part property (typed by a block)                ``PartUsage`` (multiplicity kept)
value property (typed by a value type)          ``AttributeUsage``
``uml:Port`` «FlowPort» / «ProxyPort» / «FullPort»  ``PortUsage`` (direction from the flow port,
                                                or from the interface block's flow properties;
                                                conjugated ports are flipped)
``uml:Connector`` with ``partWithPort`` ends    ``ConnectionUsage`` (ends + end contexts)
``uml:Generalization``                          specialization
``ownedComment``                                documentation
«Satisfy» / «Verify» / «DeriveReqt» / «Refine»  satisfy / verify / derive / refine /
/ «Trace» / «Copy» / «Allocate» abstractions    trace / copy / allocate links
other profile stereotypes (``Avionics:LRU``)    stereotypes (created if missing) with values
==============================================  ========================================

XMI ids become element ids, so importing the same file again updates the
elements instead of duplicating them. Documents with a DTD or entity
declarations are rejected (see ``xlsx.safe_xml``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import xml.etree.ElementTree as ET

from kerml.elements import Element, Relationship
from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2.definitions import (
    ActionDefinition, AttributeDefinition, AttributeUsage, ConnectionUsage,
    ConstraintDefinition, EnumerationDefinition, EnumerationUsage, ItemDefinition,
    PartDefinition, PartUsage, PortDefinition, PortUsage, RequirementDefinition,
    StateDefinition, VerificationCaseDefinition,
)

from .common import (
    InteropError, infer_scalar, move_element, set_documentation, set_feature_types,
    set_specializations,
)
from .xlsx import local, safe_xml

MAX_XMI_BYTES = 32 * 1024 * 1024

_SYSML_STEREOTYPES = {
    "Block", "InterfaceBlock", "Requirement", "ConstraintBlock", "ValueType", "FlowPort",
    "ProxyPort", "FullPort", "FlowProperty", "Satisfy", "Verify", "DeriveReqt", "Refine",
    "Trace", "Copy", "Allocate", "TestCase", "FlowSpecification", "BindingConnector",
    "ItemFlow", "ConstraintProperty", "ParticipantProperty", "ValueProperty",
    "functionalRequirement", "performanceRequirement", "interfaceRequirement",
    "physicalRequirement", "designConstraint", "extendedRequirement", "AllocateActivityPartition",
    "Rationale", "Problem", "View", "Viewpoint", "Conform", "Expose", "Stakeholder",
}
_LINK_STEREOTYPES = {"Satisfy": "satisfy", "Verify": "verify", "DeriveReqt": "derive",
                     "Refine": "refine", "Trace": "trace", "Copy": "copy",
                     "Allocate": "allocate"}
_PRIMITIVES = {"Real": "Real", "Integer": "Integer", "String": "String", "Boolean": "Boolean",
               "UnlimitedNatural": "Natural", "Number": "Real", "Complex": "Real",
               "double": "Real", "float": "Real", "int": "Integer", "boolean": "Boolean",
               "string": "String"}
_INTERNAL_NS = ("nomagic", "magicdraw", "omg.org/spec/uml", "omg.org/spec/xmi",
                "schema.omg.org", "omg.org/spec/mof")


@dataclass
class XmiReport:
    model_name: str = ""
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    links_created: int = 0
    stereotypes_applied: int = 0
    warnings: list[str] = field(default_factory=list)
    root_id: str = ""

    def to_dict(self) -> dict:
        return {"model_name": self.model_name, "created": len(self.created),
                "updated": len(self.updated), "links_created": self.links_created,
                "stereotypes_applied": self.stereotypes_applied,
                "created_ids": list(self.created), "warnings": list(self.warnings),
                "root_id": self.root_id}


# --- XML helpers ---------------------------------------------------------------

def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def _xattr(node: ET.Element, name: str) -> Optional[str]:
    """An ``xmi:`` attribute (id, type, idref) whatever the XMI namespace version."""
    for k, v in node.attrib.items():
        if k.startswith("{") and local(k) == name and "xmi" in _ns(k).lower():
            return v
    return node.attrib.get(f"xmi:{name}")


def _xtype(node: ET.Element) -> str:
    t = _xattr(node, "type") or ""
    return t.split(":", 1)[1] if ":" in t else t


def _refs(node: ET.Element, name: str) -> list[str]:
    """Id references held in attribute `name` (space separated) or in <name xmi:idref=.../> children."""
    out = (node.get(name) or "").split()
    for child in node:
        if local(child.tag) == name:
            ref = _xattr(child, "idref") or child.get("href", "").rsplit("#", 1)[-1]
            if ref:
                out.append(ref)
    return out


def _name(node: ET.Element) -> Optional[str]:
    if node.get("name") is not None:
        return node.get("name")
    child = next((c for c in node if local(c.tag) == "name"), None)
    return child.text if child is not None else None


def _body(node: ET.Element) -> str:
    if node.get("body") is not None:
        return node.get("body") or ""
    child = next((c for c in node if local(c.tag) == "body"), None)
    return (child.text or "") if child is not None else ""


class _XmiImporter:
    def __init__(self, repo, data: bytes | str, *, wrap: bool):
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if len(raw) > MAX_XMI_BYTES:
            raise InteropError("XMI file is too large")
        self.doc = safe_xml(raw)
        self.repo = repo
        self.wrap = wrap
        self.report = XmiReport()
        self.nodes: dict[str, ET.Element] = {}
        self.elements: dict[str, Element] = {}
        self.stereo: dict[str, list[tuple[str, str, ET.Element]]] = {}
        self.properties: list[tuple[ET.Element, Element]] = []   # (ownedAttribute, owner)
        self.connectors: list[tuple[ET.Element, Element]] = []
        self.generalizations: list[tuple[ET.Element, Element]] = []
        self.links: list[tuple[str, ET.Element]] = []
        self.ports: list[tuple[ET.Element, PortUsage]] = []
        self.pending_stereotypes: list[tuple[str, Element]] = []
        self.created_ids: set[str] = set()

    # --- indexing -------------------------------------------------------------
    def index(self) -> ET.Element:
        for node in self.doc.iter():
            ident = _xattr(node, "id")
            if ident:
                self.nodes[ident] = node
        root_children = list(self.doc) if local(self.doc.tag) == "XMI" else []
        for node in root_children:
            ns = _ns(node.tag)
            tag = local(node.tag)
            if "xmi" in ns.lower() and tag in ("Documentation", "Extension"):
                continue
            if "omg.org/spec/uml" in ns.lower() or ns == "":
                continue
            for k, v in node.attrib.items():
                if local(k).startswith("base_") and v:
                    self.stereo.setdefault(v, []).append((tag, ns, node))
        model = None
        candidates = [self.doc] + root_children
        for node in candidates:
            if local(node.tag) == "Model" or _xtype(node) == "Model":
                model = node
                break
        if model is None:
            model = next((n for n in candidates if local(n.tag) == "Package"
                          or _xtype(n) == "Package"), None)
        if model is None:
            raise InteropError("no uml:Model or uml:Package found in the XMI document")
        return model

    def stereotypes_of(self, ident: str) -> set[str]:
        return {tag for tag, _ns_, _n in self.stereo.get(ident, [])}

    def sysml_attr(self, ident: str, stereo: str, attr: str) -> Optional[str]:
        for tag, _ns_, node in self.stereo.get(ident, []):
            if tag == stereo:
                for k, v in node.attrib.items():
                    if "xmi" in _ns(k).lower() or k.startswith("xmi:"):
                        continue        # xmi:id is not the requirement's Id
                    if local(k).lower() == attr.lower():
                        return v
                child = next((c for c in node if local(c.tag).lower() == attr.lower()), None)
                if child is not None:
                    return child.text or ""
        return None

    # --- element creation -----------------------------------------------------
    def make(self, cls: type, node: ET.Element, owner: Element) -> Element:
        ident = _xattr(node, "id") or ""
        name = _name(node)
        existing = self.repo.by_id(ident) if ident else None
        if existing is not None and type(existing) is cls:
            if existing.owner is not owner:
                move_element(existing, owner)
            existing.name = name
            e = existing
            self.report.updated.append(ident)
        else:
            if existing is not None:
                raise InteropError(f"XMI id {ident!r} is already used by a {existing.kind} "
                                   f"({existing.qualified_name})")
            try:
                e = cls(name=name)
            except TypeError:
                e = cls()
                e.name = name
            if ident:
                e.element_id = ident
            owner.own(e)
            self.created_ids.add(e.element_id)
            self.report.created.append(e.element_id)
        if ident:
            self.elements[ident] = e
        if node.get("isAbstract") in ("true", "false") and not isinstance(e, Package):
            e.is_abstract = node.get("isAbstract") == "true"
        self.repo.registry.register_tree(e)
        self.comments(node, e)
        return e

    def comments(self, node: ET.Element, e: Element) -> None:
        texts = []
        ident = _xattr(node, "id")
        for c in node:
            if local(c.tag) == "ownedComment":
                annotated = _refs(c, "annotatedElement")
                if not annotated or ident in annotated:
                    body = _body(c).strip()
                    if body:
                        texts.append(body)
        if texts:
            set_documentation(e, "\n\n".join(texts))

    def classifier_class(self, node: ET.Element) -> Optional[type]:
        xt = _xtype(node)
        st = self.stereotypes_of(_xattr(node, "id") or "")
        if xt == "Class":
            if any("Requirement" in s or s == "designConstraint" for s in st):
                return RequirementDefinition
            if "InterfaceBlock" in st or "FlowSpecification" in st:
                return PortDefinition
            if "ConstraintBlock" in st:
                return ConstraintDefinition
            return PartDefinition
        if xt in ("DataType", "PrimitiveType") or "ValueType" in st:
            return AttributeDefinition
        if xt == "Enumeration":
            return EnumerationDefinition
        if xt == "Signal":
            return ItemDefinition
        if xt in ("Activity", "OpaqueBehavior", "Interaction"):
            return VerificationCaseDefinition if "TestCase" in st else ActionDefinition
        if xt == "StateMachine":
            return StateDefinition
        if xt == "Interface":
            return PortDefinition
        return None

    def package_content(self, node: ET.Element, owner: Element) -> None:
        for child in node:
            tag = local(child.tag)
            if tag not in ("packagedElement", "nestedClassifier", "ownedBehavior",
                           "ownedMember"):
                continue
            xt = _xtype(child)
            if xt in ("Package", "Model"):
                pkg = self.make(Package, child, owner)
                self.package_content(child, pkg)
            elif xt in ("Abstraction", "Dependency", "Realization", "Usage"):
                self.links.append((xt, child))
            elif xt in ("Association", "InstanceSpecification", "Comment", "Diagram",
                        "Profile", "ProfileApplication"):
                continue
            else:
                cls = self.classifier_class(child)
                if cls is None:
                    self.report.warnings.append(
                        f"skipped unsupported {xt or tag} {(_name(child) or '')!r}")
                    continue
                e = self.make(cls, child, owner)
                self.classifier_content(child, e)

    def classifier_content(self, node: ET.Element, e: Element) -> None:
        ident = _xattr(node, "id") or ""
        if isinstance(e, RequirementDefinition):
            stereo = next((s for s in self.stereotypes_of(ident) if "Requirement" in s
                           or s == "designConstraint"), "Requirement")
            rid = self.sysml_attr(ident, stereo, "Id")
            text = self.sysml_attr(ident, stereo, "Text")
            e.req_id = rid or None
            e.text = text or None
        for child in node:
            tag = local(child.tag)
            if tag == "ownedAttribute":
                self.properties.append((child, e))
            elif tag == "ownedConnector":
                self.connectors.append((child, e))
            elif tag == "generalization":
                self.generalizations.append((child, e))
            elif tag == "ownedLiteral" and isinstance(e, EnumerationDefinition):
                lit = self.make(EnumerationUsage, child, e)
                set_feature_types(lit, [e])  # type: ignore[arg-type]
                if lit not in e.literals:
                    e.literals.append(lit)
            elif tag in ("nestedClassifier", "ownedBehavior"):
                cls = self.classifier_class(child)
                if cls is not None:
                    sub = self.make(cls, child, e)
                    self.classifier_content(child, sub)
        self.pending_stereotypes.append((ident, e))

    # --- features -----------------------------------------------------------------
    def type_of(self, node: ET.Element) -> Optional[Element]:
        ref = node.get("type")
        href = None
        if not ref:
            child = next((c for c in node if local(c.tag) == "type"), None)
            if child is not None:
                ref = _xattr(child, "idref")
                href = child.get("href")
        if ref and ref in self.elements:
            return self.elements[ref]
        if ref and self.repo.by_id(ref) is not None:
            return self.repo.by_id(ref)
        key = (href or ref or "").rsplit("#", 1)[-1].rsplit(".", 1)[-1].rsplit("::", 1)[-1]
        if key in _PRIMITIVES:
            return KERML_LIBRARY.resolve(f"ScalarValues::{_PRIMITIVES[key]}")
        if ref or href:
            self.report.warnings.append(f"type {(href or ref)!r} of {_name(node)!r} not found")
        return None

    @staticmethod
    def multiplicity(node: ET.Element) -> MultiplicityRange:
        lo, hi = 1, 1
        for child in node:
            tag = local(child.tag)
            if tag not in ("lowerValue", "upperValue"):
                continue
            v = child.get("value")
            if tag == "lowerValue":
                lo = int(v) if v and v.lstrip("-").isdigit() else 0
            else:
                hi = None if v in ("*", "-1") else (int(v) if v and v.isdigit() else 0)
        try:
            return MultiplicityRange(max(lo, 0), hi if hi is None or hi >= max(lo, 0) else None)
        except ValueError:
            return MultiplicityRange(0, None)

    def create_features(self) -> None:
        for node, owner in self.properties:
            ident = _xattr(node, "id") or ""
            xt = _xtype(node)
            st = self.stereotypes_of(ident)
            t = self.type_of(node)
            if xt == "Port":
                cls: type = PortUsage
            elif isinstance(t, (PartDefinition,)) and not isinstance(owner, PortDefinition):
                cls = PartUsage
            else:
                cls = AttributeUsage
            f = self.make(cls, node, owner)
            assert isinstance(f, Feature)
            f.multiplicity = self.multiplicity(node)
            set_feature_types(f, [t] if t is not None else [])
            if cls is PartUsage and (node.get("aggregation") or "none") != "composite" \
                    and hasattr(f, "is_reference"):
                f.is_reference = True
            if "FlowProperty" in st:
                f.direction = self.flow_direction(ident, "FlowProperty")
            if cls is PortUsage:
                self.ports.append((node, f))  # type: ignore[arg-type]
            if node.get("isReadOnly") == "true":
                f.is_readonly = True
            if node.get("isDerived") == "true":
                f.is_derived = True
            if node.get("default") or next((c for c in node if local(c.tag) == "defaultValue"),
                                           None) is not None:
                dv = node.get("default")
                if dv is None:
                    dnode = next(c for c in node if local(c.tag) == "defaultValue")
                    dv = dnode.get("value")
                if dv is not None:
                    f.default_value = infer_scalar(dv)
            self.pending_stereotypes.append((ident, f))

    def flow_direction(self, ident: str, stereo: str) -> FeatureDirection:
        d = (self.sysml_attr(ident, stereo, "direction") or "inout").lower()
        return {"in": FeatureDirection.IN, "out": FeatureDirection.OUT}.get(d, FeatureDirection.INOUT)

    def port_directions(self) -> None:
        for node, port in self.ports:
            ident = _xattr(node, "id") or ""
            st = self.stereotypes_of(ident)
            if "FlowPort" in st:
                direction = self.flow_direction(ident, "FlowPort")
            else:
                iface = next(iter(port.types), None)
                dirs = {f.direction for f in getattr(iface, "owned_elements", [])
                        if isinstance(f, Feature) and f.direction is not FeatureDirection.NONE}
                if not dirs:
                    direction = FeatureDirection.NONE
                elif len(dirs) == 1:
                    direction = next(iter(dirs))
                else:
                    direction = FeatureDirection.INOUT
            if node.get("isConjugated") == "true":
                direction = {FeatureDirection.IN: FeatureDirection.OUT,
                             FeatureDirection.OUT: FeatureDirection.IN}.get(direction, direction)
            port.direction = direction

    def create_connectors(self) -> None:
        for node, owner in self.connectors:
            ends, contexts = [], []
            for end in [c for c in node if local(c.tag) == "end"]:
                role = (_refs(end, "role") or [None])[0]
                pwp = (_refs(end, "partWithPort") or [None])[0]
                target = self.elements.get(role or "") or (self.repo.by_id(role) if role else None)
                if target is None:
                    self.report.warnings.append(
                        f"connector {(_name(node) or _xattr(node, 'id'))!r}: end {role!r} not found")
                    continue
                ends.append(target)
                contexts.append(self.elements.get(pwp or ""))
            conn = self.make(ConnectionUsage, node, owner)
            conn.ends = ends  # type: ignore[attr-defined]
            if hasattr(conn, "end_contexts"):
                conn.end_contexts = tuple(contexts) if any(contexts) and len(contexts) == len(ends) \
                    else ()  # type: ignore[attr-defined]
            if not conn.name:
                names = [x.name or "?" for x in ends]
                conn.name = f"connect_{'_'.join(names)}" if names else None
            self.pending_stereotypes.append((_xattr(node, "id") or "", conn))

    def create_generalizations(self) -> None:
        for node, e in self.generalizations:
            general = (_refs(node, "general") or [None])[0]
            target = self.elements.get(general or "")
            if target is None:
                self.report.warnings.append(f"generalization of {e.name!r}: {general!r} not found")
                continue
            current = [s.target for s in getattr(e, "specializations", [])]
            if target not in current:
                set_specializations(e, current + [target])

    def create_links(self) -> None:
        from engine.links import create_link
        for xt, node in self.links:
            ident = _xattr(node, "id") or ""
            st = self.stereotypes_of(ident)
            kind = next((_LINK_STEREOTYPES[s] for s in st if s in _LINK_STEREOTYPES), None)
            if kind is None:
                if xt == "Abstraction":
                    kind = "trace"
                elif xt == "Realization":
                    kind = "refine"
                else:
                    continue
            clients = [self.elements.get(c) or self.repo.by_id(c) for c in _refs(node, "client")]
            suppliers = [self.elements.get(s) or self.repo.by_id(s) for s in _refs(node, "supplier")]
            if not clients or not suppliers or None in clients or None in suppliers:
                self.report.warnings.append(f"{kind} link {ident!r}: client/supplier not found")
                continue
            for i, (src, tgt) in enumerate((c, s) for c in clients for s in suppliers):
                rid = ident if i == 0 else f"{ident}_{i}"
                existing = self.repo.by_id(rid) if rid else None
                if isinstance(existing, Relationship):
                    continue
                rel = create_link(kind, src, tgt)
                if rid:
                    rel.element_id = rid
                self.repo.registry.register(rel)
                self.report.links_created += 1

    # --- user profiles ------------------------------------------------------------
    def custom_stereotypes(self, ident: str, e: Element) -> None:
        for tag, ns, node in self.stereo.get(ident, []):
            if tag in _SYSML_STEREOTYPES or "sysml" in ns.lower() or \
                    any(x in ns.lower() for x in _INTERNAL_NS):
                continue
            values = {local(k): infer_scalar(v) for k, v in node.attrib.items()
                      if not local(k).startswith("base_") and "xmi" not in _ns(k).lower()
                      and not k.startswith("xmi:")}
            st = self.user_stereotype(tag, ns, values)
            app = next((a for a in stereotypes_on(e) if a.stereotype is st), None)
            try:
                if app is None:
                    app = st.apply(e, {})
                    self.report.stereotypes_applied += 1
                for k, v in values.items():
                    setter = getattr(app, "set", None)
                    if callable(setter):
                        setter(k, v)
                    else:
                        app.values[k] = v
            except Exception as ex:  # noqa: BLE001 - report and continue
                self.report.warnings.append(f"stereotype «{tag}» on {e.name!r}: {ex}")

    def user_stereotype(self, tag: str, ns: str, values: dict) -> Stereotype:
        st = next((s for s in self.repo.root_package.walk()
                   if isinstance(s, Stereotype) and s.name == tag), None)
        if st is None:
            holder = next((p for p in self.repo.root_package.owned_elements
                           if isinstance(p, Package) and p.name == "XMI_Profiles"), None)
            if holder is None:
                holder = Package(name="XMI_Profiles")
                self.repo.root_package.own(holder)
                self.repo.registry.register_tree(holder)
                self.created_ids.add(holder.element_id)
                self.report.created.append(holder.element_id)
            st = Stereotype(tag)
            holder.own(st)
            self.created_ids.add(st.element_id)
            self.report.created.append(st.element_id)
        known = {t.name for t in st.all_tags()}
        for k, v in values.items():
            if k not in known:
                st.define_tag(k, default=None)
        self.repo.registry.register_tree(st)
        return st

    # --- driver ---------------------------------------------------------------------
    def run(self) -> XmiReport:
        from engine.hooks import notify_created
        model = self.index()
        self.report.model_name = _name(model) or "Model"
        if self.wrap:
            target = self.make(Package, model, self.repo.root_package)
        else:
            target = self.repo.root_package
            self.comments(model, target)
        self.report.root_id = target.element_id
        self.package_content(model, target)
        self.create_features()
        self.create_generalizations()
        self.port_directions()
        self.create_connectors()
        for ident, e in self.pending_stereotypes:
            self.custom_stereotypes(ident, e)
        self.repo.registry.register_tree(self.repo.root_package)
        for e in list(self.repo.root_package.walk()):
            if e.element_id in self.created_ids and not isinstance(e, Stereotype):
                notify_created(e, self.repo)
        self.create_links()
        self.repo.registry.register_tree(self.repo.root_package)
        return self.report


def import_xmi(repo, data: bytes | str, *, wrap: bool = True, atomic: bool = True) -> XmiReport:
    """Import XMI into `repo` (under a package named after the model when `wrap`)."""
    if atomic:
        from engine.serializer import from_dict, to_dict
        _XmiImporter(from_dict(to_dict(repo)), data, wrap=wrap).run()
    return _XmiImporter(repo, data, wrap=wrap).run()


def xmi_to_project(data: bytes | str, name: Optional[str] = None):
    """A new project from an XMI file (model contents at the root). Returns (repo, report)."""
    from engine.repository import Repository
    probe = _XmiImporter(Repository("probe"), data, wrap=False)
    model = probe.index()
    repo = Repository(name=name or _name(model) or "ImportedModel")
    report = _XmiImporter(repo, data, wrap=False).run()
    return repo, report
