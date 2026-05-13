"""Generate Graphviz DOT for SysML v2 diagrams.

Three diagram domains are supported:

- ``"bdd"`` — Block (Part / Item / Attribute / Port Definition) diagram
  with specialization edges and feature compartments.
- ``"ibd"`` — Internal Block Diagram of a single PartDefinition: nested
  PartUsages with ports, joined by ConnectionUsage edges.
- ``"requirements"`` — Requirements with Satisfy / Verify / Derive edges.

The output is always Graphviz DOT text — no `graphviz` package is
required. The caller can render to SVG/PNG with ``dot -Tsvg`` if they
have Graphviz installed, embed the DOT in Mermaid via ``%%{init...}``,
or hand it to any DOT-aware renderer (D3, viz.js, etc.).
"""
from __future__ import annotations

from typing import Iterable, Optional

from kerml.elements import Element
from kerml.features import Feature
from kerml.namespaces import Namespace
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ConnectionUsage,
    Definition,
    PartDefinition,
    PortUsage,
    RequirementDefinition,
    Usage,
)
from sysmlv2.relationships import Satisfy, Verify, Refine, DeriveRequirement, Trace


# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _stereo_label(e: Element) -> str:
    apps = stereotypes_on(e)
    if not apps:
        return ""
    return "<<" + ", ".join(a.stereotype.name for a in apps) + ">>\\n"


def _node_id(e: Element) -> str:
    return "n" + e.element_id.replace("-", "")


# ---------------------------------------------------------------------------

def bdd(root: Namespace) -> str:
    """Block Definition Diagram for a package / project."""
    lines = ["digraph BDD {",
             '  rankdir=BT;',
             '  node [shape=record, fontname="Helvetica"];',
             '  edge [arrowhead=empty, fontname="Helvetica"];']
    defs: list[Definition] = [e for e in root.walk() if isinstance(e, Definition)]
    for d in defs:
        compartments = [_stereo_label(d) + f"{d.kind}\\n{d.name or ''}"]
        feats = [f for f in d.owned_features if isinstance(f, Feature) and not isinstance(f, ConnectionUsage)]
        if feats:
            compartments.append("\\l".join(
                f"+ {f.name or '?'} : {', '.join(t.name or '?' for t in f.types) or '?'}"
                for f in feats
            ) + "\\l")
        label = "|".join("{" + c + "}" for c in compartments)
        lines.append(f'  {_node_id(d)} [label="{{{label}}}"];')
    # Specialization edges
    for d in defs:
        for s in getattr(d, "specializations", []):
            tgt = s.target
            if isinstance(tgt, Definition):
                lines.append(f"  {_node_id(d)} -> {_node_id(tgt)};")
    # Composition (PartUsage typed by another Definition)
    for d in defs:
        if not isinstance(d, PartDefinition):
            continue
        for u in d.owned_features:
            for t in getattr(u, "types", []):
                if isinstance(t, Definition) and t is not d:
                    lines.append(
                        f'  {_node_id(d)} -> {_node_id(t)} '
                        f'[arrowhead=diamond, arrowtail=none, dir=both, '
                        f'label="{_escape(u.name or "")}"];'
                    )
    lines.append("}")
    return "\n".join(lines)


def ibd(part: PartDefinition) -> str:
    """Internal Block Diagram for one PartDefinition."""
    lines = [f"digraph IBD_{_node_id(part)} {{",
             f'  label="IBD: {_escape(part.name or "")}"; labelloc=t;',
             '  node [shape=box, style=rounded, fontname="Helvetica"];',
             '  rankdir=LR;']
    # Inner part usages as subgraphs/clusters; ports as nodes on the cluster.
    for u in part.owned_features:
        if isinstance(u, ConnectionUsage):
            continue
        cluster_id = f"cluster_{_node_id(u)}"
        lines.append(f"  subgraph {cluster_id} {{")
        type_name = ", ".join(t.name or "?" for t in u.types) or "?"
        lines.append(f'    label="{_escape(u.name or "?")} : {_escape(type_name)}";')
        lines.append('    style="rounded,filled"; fillcolor="#f4f4f4";')
        for sub in u.owned_elements:
            if isinstance(sub, PortUsage):
                lines.append(
                    f'    {_node_id(sub)} [label="{_escape(sub.name or "?")}", '
                    f'shape=square, width=0.3, height=0.3];'
                )
        # If the usage's type is a Definition, surface its ports too.
        for t in getattr(u, "types", []):
            if isinstance(t, Definition):
                for sub in t.owned_features:
                    if isinstance(sub, PortUsage):
                        nid = f"{_node_id(u)}_{_node_id(sub)}"
                        lines.append(
                            f'    {nid} [label="{_escape(sub.name or "?")}", '
                            f'shape=square, width=0.3, height=0.3];'
                        )
        lines.append("  }")
    # ConnectionUsage edges
    for c in part.owned_features:
        if not isinstance(c, ConnectionUsage) or len(c.ends) < 2:
            continue
        a, b = c.ends[0], c.ends[1]
        lines.append(
            f'  {_node_id(a)} -> {_node_id(b)} '
            f'[dir=none, label="{_escape(c.name or "")}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def requirements(root: Namespace) -> str:
    """Requirements diagram with Satisfy / Verify / Derive / Refine / Trace edges."""
    lines = ["digraph Requirements {",
             '  rankdir=LR;',
             '  node [fontname="Helvetica"];']
    reqs = [e for e in root.walk() if isinstance(e, RequirementDefinition)]
    for r in reqs:
        text = (getattr(r, "text", None) or "")[:80].replace('"', "'")
        label = (
            f"{_stereo_label(r)}<<requirement>>\\n"
            f"{r.name or '?'}\\n"
            f"id: {getattr(r, 'req_id', None) or '-'}\\n"
            f"\\n{_escape(text)}"
        )
        lines.append(
            f'  {_node_id(r)} '
            f'[shape=note, style=filled, fillcolor="#fffbe6", label="{label}"];'
        )
    # Traceability edges
    rel_kinds: list[tuple[type, str, str]] = [
        (Satisfy,           "satisfy",  "dashed"),
        (Verify,            "verify",   "dashed"),
        (Refine,            "refine",   "dotted"),
        (DeriveRequirement, "derive",   "dashed"),
        (Trace,             "trace",    "dotted"),
    ]
    for e in root.walk():
        for rel in getattr(e, "owned_relationships", []):
            for cls, label, style in rel_kinds:
                if isinstance(rel, cls):
                    src = rel.source; tgt = rel.target
                    if src is None or tgt is None:
                        continue
                    # Make sure source has a node — add a stub if not a requirement.
                    if not isinstance(src, RequirementDefinition):
                        lines.append(
                            f'  {_node_id(src)} [label="{_escape(src.name or src.kind)}"];'
                        )
                    lines.append(
                        f'  {_node_id(src)} -> {_node_id(tgt)} '
                        f'[style={style}, label="<<{label}>>"];'
                    )
                    break
    lines.append("}")
    return "\n".join(lines)


def state_machine(sm) -> str:
    """State machine diagram (states + transitions + entry/do/exit hooks)."""
    from sysmlv2.state_machines import StateMachineDefinition
    if not isinstance(sm, StateMachineDefinition):
        raise TypeError("state_machine requires a StateMachineDefinition target")
    lines = [f"digraph SM_{_node_id(sm)} {{",
             f'  label="StateMachine: {_escape(sm.name or "")}"; labelloc=t;',
             '  rankdir=LR;',
             '  node [shape=box, style="rounded,filled", fillcolor="#fef9e7",'
             ' fontname="Helvetica"];',
             '  start [shape=circle, label="", style=filled, fillcolor=black, width=0.2];']
    if sm.initial_state is not None:
        lines.append(f'  start -> {_node_id(sm.initial_state)};')
    for s in sm.states:
        rows = [f"<<state>>\\n{s.name or '?'}"]
        for kind, attr in (("entry", "entry_action"),
                           ("do",    "do_action"),
                           ("exit",  "exit_action")):
            val = getattr(s, attr, None)
            if val:
                rows.append(f"{kind}/ {val}")
        label = "\\n".join(_escape(r) for r in rows)
        shape = "doublecircle" if getattr(s, "is_final", False) else "box"
        if getattr(s, "is_final", False):
            lines.append(f'  {_node_id(s)} [shape={shape}, label="", fillcolor=black, width=0.25];')
            lines.append(f'  {_node_id(s)}_lbl [shape=plain, label="{label}"];')
        else:
            lines.append(f'  {_node_id(s)} [label="{label}"];')
    for t in sm.transitions:
        src, tgt = t.transition_source, t.transition_target
        if src is None or tgt is None:
            continue
        bits = []
        if t.trigger_event: bits.append(t.trigger_event)
        if t.guard is not None:
            bits.append("[" + (t.guard if isinstance(t.guard, str) else "λ") + "]")
        if t.effect is not None:
            bits.append("/ " + (t.effect if isinstance(t.effect, str) else "λ"))
        lbl = " ".join(bits)
        lines.append(
            f'  {_node_id(src)} -> {_node_id(tgt)} [label="{_escape(lbl)}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def diagram(kind: str, target: Element) -> str:
    """Dispatch entry point."""
    if kind == "bdd":
        if not isinstance(target, Namespace):
            raise TypeError("bdd requires a Namespace target")
        return bdd(target)
    if kind == "ibd":
        if not isinstance(target, PartDefinition):
            raise TypeError("ibd requires a PartDefinition target")
        return ibd(target)
    if kind in ("requirements", "req"):
        if not isinstance(target, Namespace):
            raise TypeError("requirements requires a Namespace target")
        return requirements(target)
    if kind in ("statemachine", "state", "sm"):
        return state_machine(target)
    raise ValueError(f"Unknown diagram kind {kind!r}")
