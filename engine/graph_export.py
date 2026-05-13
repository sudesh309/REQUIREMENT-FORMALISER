"""Export the SysML v2 model as a knowledge graph.

Four output formats:

- ``"turtle"`` — RDF 1.1 Turtle (mime ``text/turtle``). Ingestible by
  Apache Jena, RDFLib, GraphDB, Stardog, Neo4j n10s, etc.
- ``"json-ld"`` — JSON-LD 1.1 (compact form). Ingestible by RDFLib,
  Neo4j, and any JSON graph tool.
- ``"graphml"`` — GraphML XML (Gephi, yEd, Cytoscape, NetworkX).
- ``"cypher"`` — Neo4j Cypher ``MERGE`` script you can paste into the
  Neo4j browser.

The graph model is uniform across formats:

- Every Element becomes a node with ``id``, ``kind`` (metaclass),
  ``name``, ``qualified_name``, and any kind-specific properties.
- Every ownership becomes a ``:owns`` edge.
- Every typed relationship (Specialization, Subsetting, Redefinition,
  FeatureTyping, Membership, Import, Satisfy, Verify, Refine, Trace,
  Connection ends, Stereotype application) becomes a typed edge.
"""
from __future__ import annotations

import html
import json
import xml.sax.saxutils as sx
from typing import Any, Iterable, Iterator

from kerml.elements import Element, Relationship
from kerml.features import Feature, Redefinition, Subsetting, FeatureTyping
from kerml.namespaces import Namespace, Import, Membership
from kerml.stereotypes import StereotypeApplication, stereotypes_on
from kerml.types import Specialization
from sysmlv2.definitions import ConnectionUsage
from sysmlv2.relationships import Satisfy, Verify, Refine, Trace, DeriveRequirement


NS = "https://example.org/sysmlv2#"


# --- shared edge collector ----------------------------------------------

def _iter_edges(root: Element) -> Iterator[tuple[str, Element, Element, dict]]:
    """Yield ``(predicate, src, tgt, props)`` tuples spanning the project."""
    for e in root.walk():
        # Ownership.
        for c in e.owned_elements:
            yield ("owns", e, c, {})
        # Stereotype applications.
        for app in stereotypes_on(e):
            yield ("stereotype", e, app.stereotype, {"values": json.dumps(app.values, default=str)})
        # Typed relationships owned by this element.
        for r in getattr(e, "owned_relationships", []):
            src, tgt = r.source, r.target
            if src is None or tgt is None:
                continue
            label = _rel_label(r)
            if label is None:
                continue
            yield (label, src, tgt, {})
        # Feature typing / subsetting / redefinition.
        if isinstance(e, Feature):
            for ft in e.feature_typings:
                if ft.target is not None:
                    yield ("typedBy", e, ft.target, {})
            for s in e.subsettings:
                if s.target is not None:
                    pred = "redefines" if isinstance(s, Redefinition) else "subsets"
                    yield (pred, e, s.target, {})
        # Connection ends.
        if isinstance(e, ConnectionUsage):
            for end in e.ends:
                yield ("connects", e, end, {})


def _rel_label(rel: Relationship) -> str | None:
    if isinstance(rel, Specialization):       return "specializes"
    if isinstance(rel, Subsetting):           return "subsets"
    if isinstance(rel, FeatureTyping):        return "typedBy"
    if isinstance(rel, Import):               return "imports"
    if isinstance(rel, Satisfy):              return "satisfies"
    if isinstance(rel, Verify):               return "verifies"
    if isinstance(rel, Refine):               return "refines"
    if isinstance(rel, Trace):                return "traces"
    if isinstance(rel, DeriveRequirement):    return "derivesFrom"
    if isinstance(rel, Membership):           return None  # captured via ownership
    return None


def _props(e: Element) -> dict[str, Any]:
    p: dict[str, Any] = {
        "kind": e.kind,
        "name": e.name,
        "qualified_name": e.qualified_name,
    }
    if getattr(e, "is_abstract", False):
        p["isAbstract"] = True
    if isinstance(e, Feature):
        up = e.multiplicity.upper
        p["multiplicityLower"] = e.multiplicity.lower
        p["multiplicityUpper"] = "*" if up is None else up
        p["direction"] = e.direction.value
    for attr in ("req_id", "text", "short_name"):
        v = getattr(e, attr, None)
        if v is not None:
            p[attr] = v
    return p


# --- Turtle / RDF -------------------------------------------------------

def to_turtle(root: Element) -> str:
    lines: list[str] = [
        f"@prefix sysml: <{NS}> .",
        "@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for e in root.walk():
        iri = f"sysml:{e.element_id}"
        lines.append(f"{iri} a sysml:{e.kind} ;")
        for k, v in _props(e).items():
            if k == "kind":
                continue
            lines.append(f"    sysml:{k} {_ttl(v)} ;")
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    for predicate, src, tgt, props in _iter_edges(root):
        line = f"sysml:{src.element_id} sysml:{predicate} sysml:{tgt.element_id}"
        if props:
            payload = ", ".join(f"{k}={v}" for k, v in props.items())
            line += f" .  # {payload}"
        else:
            line += " ."
        lines.append(line)
    return "\n".join(lines) + "\n"


def _ttl(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f'"{value}"^^xsd:integer'
    if isinstance(value, float):
        return f'"{value}"^^xsd:double'
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


# --- JSON-LD ------------------------------------------------------------

def to_jsonld(root: Element) -> str:
    nodes = []
    for e in root.walk():
        node = {
            "@id":   f"sysml:{e.element_id}",
            "@type": f"sysml:{e.kind}",
            **{f"sysml:{k}": v for k, v in _props(e).items() if k != "kind"},
        }
        nodes.append(node)
    edges = []
    for predicate, src, tgt, props in _iter_edges(root):
        edges.append({
            "@id":   f"sysml:edge_{src.element_id}_{predicate}_{tgt.element_id}",
            "@type": f"sysml:{predicate}",
            "sysml:source": f"sysml:{src.element_id}",
            "sysml:target": f"sysml:{tgt.element_id}",
            **{f"sysml:{k}": v for k, v in props.items()},
        })
    return json.dumps({
        "@context": {"sysml": NS},
        "@graph": nodes + edges,
    }, indent=2, default=str)


# --- GraphML ------------------------------------------------------------

def to_graphml(root: Element) -> str:
    keys = ["kind", "name", "qualified_name", "isAbstract",
            "multiplicityLower", "multiplicityUpper", "direction",
            "req_id", "text", "short_name"]
    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for k in keys:
        out.append(f'  <key id="{k}" for="node" attr.name="{k}" attr.type="string"/>')
    out.append('  <key id="predicate" for="edge" attr.name="predicate" attr.type="string"/>')
    out.append('  <graph edgedefault="directed">')
    for e in root.walk():
        out.append(f'    <node id="{e.element_id}">')
        for k, v in _props(e).items():
            out.append(f'      <data key="{k}">{sx.escape(str(v))}</data>')
        out.append('    </node>')
    eid = 0
    for predicate, src, tgt, _ in _iter_edges(root):
        out.append(f'    <edge id="e{eid}" source="{src.element_id}" target="{tgt.element_id}">')
        out.append(f'      <data key="predicate">{predicate}</data>')
        out.append('    </edge>')
        eid += 1
    out.append('  </graph>')
    out.append('</graphml>')
    return "\n".join(out) + "\n"


# --- Cypher (Neo4j) -----------------------------------------------------

def _cy(v: Any) -> str:
    if isinstance(v, bool):  return "true" if v else "false"
    if isinstance(v, (int, float)): return str(v)
    text = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def to_cypher(root: Element) -> str:
    lines: list[str] = ["// Generated by engine.graph_export.to_cypher"]
    for e in root.walk():
        props = _props(e)
        props["id"] = e.element_id
        body = ", ".join(f"{k}: {_cy(v)}" for k, v in props.items())
        lines.append(f"MERGE (:{e.kind} {{ {body} }});")
    for predicate, src, tgt, edge_props in _iter_edges(root):
        rel_props = (" {" + ", ".join(f"{k}: {_cy(v)}" for k, v in edge_props.items()) + "}") if edge_props else ""
        lines.append(
            f"MATCH (a {{id: {_cy(src.element_id)}}}), (b {{id: {_cy(tgt.element_id)}}}) "
            f"MERGE (a)-[:{predicate.upper()}{rel_props}]->(b);"
        )
    return "\n".join(lines) + "\n"


# --- dispatch -----------------------------------------------------------

EXPORTERS = {
    "turtle":   to_turtle,
    "ttl":      to_turtle,
    "json-ld":  to_jsonld,
    "jsonld":   to_jsonld,
    "graphml":  to_graphml,
    "cypher":   to_cypher,
}


def export_knowledge_graph(root: Element, format: str = "turtle") -> str:
    fn = EXPORTERS.get(format.lower())
    if fn is None:
        raise ValueError(f"Unknown format {format!r}; known: {sorted(EXPORTERS)}")
    return fn(root)
