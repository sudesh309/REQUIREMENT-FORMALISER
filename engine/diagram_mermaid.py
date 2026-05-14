"""Generate Mermaid syntax for SysML v2 diagrams.

Same diagram domains as `engine.diagram` (which emits Graphviz DOT) but
producing Mermaid text — ideal for in-browser rendering with mermaid.js,
GitHub / GitLab markdown, and the bundled web frontend.
"""
from __future__ import annotations

from kerml.elements import Element
from kerml.features import Feature
from kerml.namespaces import Namespace
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ConnectionUsage, Definition, PartDefinition, PortUsage,
    RequirementDefinition, StateUsage, TransitionUsage,
)
from sysmlv2.relationships import (
    Satisfy, Verify, Refine, Trace, DeriveRequirement,
)
from sysmlv2.state_machines import StateMachineDefinition


def _nid(e: Element) -> str:
    return "n" + e.element_id.replace("-", "")


def _safe(text: str) -> str:
    return (text or "").replace('"', "'").replace("\n", " ")


def _stereo(e: Element) -> str:
    apps = stereotypes_on(e)
    if not apps:
        return ""
    return "«" + ", ".join(a.stereotype.name for a in apps) + "» "


# --- BDD ----------------------------------------------------------------

def bdd_mermaid(root: Namespace) -> str:
    lines = ["classDiagram"]
    defs = [e for e in root.walk() if isinstance(e, Definition)]
    for d in defs:
        lines.append(f"    class {_nid(d)}[\"{_safe(_stereo(d) + (d.name or '?'))}\"] {{")
        lines.append(f"        <<{d.kind}>>")
        for f in d.owned_features:
            if isinstance(f, ConnectionUsage):
                continue
            t = ", ".join(t.name or "?" for t in f.types) or "?"
            lines.append(f"        +{_safe(f.name or '?')} : {_safe(t)}")
        lines.append("    }")
    for d in defs:
        for s in getattr(d, "specializations", []):
            tgt = s.target
            if isinstance(tgt, Definition):
                lines.append(f"    {_nid(tgt)} <|-- {_nid(d)}")
        if isinstance(d, PartDefinition):
            for u in d.owned_features:
                if isinstance(u, ConnectionUsage):
                    continue
                for t in getattr(u, "types", []):
                    if isinstance(t, Definition) and t is not d:
                        lines.append(
                            f'    {_nid(d)} "1" o-- "1" {_nid(t)} : {_safe(u.name or "")}'
                        )
    return "\n".join(lines)


# --- IBD ----------------------------------------------------------------

def ibd_mermaid(part: PartDefinition) -> str:
    lines = ["flowchart LR"]
    lines.append(f"    subgraph {_nid(part)}[\"{_safe(part.name or '?')}\"]")
    port_ids: list[str] = []
    for u in part.owned_features:
        if isinstance(u, ConnectionUsage):
            continue
        type_name = ", ".join(t.name or "?" for t in u.types) or "?"
        sub = f"sub_{_nid(u)}"
        lines.append(f'        subgraph {sub}["{_safe(u.name or "?")} : {_safe(type_name)}"]')
        for child in u.owned_elements:
            if isinstance(child, PortUsage):
                lines.append(f'            {_nid(child)}(("{_safe(child.name or "?")}"))')
                port_ids.append(_nid(child))
        for t in getattr(u, "types", []):
            if isinstance(t, Definition):
                for sub_p in t.owned_features:
                    if isinstance(sub_p, PortUsage):
                        pid = f"{_nid(u)}_{_nid(sub_p)}"
                        lines.append(f'            {pid}(("{_safe(sub_p.name or "?")}"))')
        lines.append("        end")
    lines.append("    end")
    for c in part.owned_features:
        if not isinstance(c, ConnectionUsage) or len(c.ends) < 2:
            continue
        a, b = c.ends[0], c.ends[1]
        lines.append(f'    {_nid(a)} ---|"{_safe(c.name or "")}"| {_nid(b)}')
    return "\n".join(lines)


# --- Requirements --------------------------------------------------------

def requirements_mermaid(root: Namespace) -> str:
    lines = ["flowchart LR"]
    reqs = [e for e in root.walk() if isinstance(e, RequirementDefinition)]
    for r in reqs:
        req_id = getattr(r, "req_id", None) or "-"
        text = (getattr(r, "text", None) or "")[:40]
        lines.append(
            f'    {_nid(r)}["«requirement»<br/>{_safe(r.name or "?")}<br/>'
            f'id: {_safe(req_id)}<br/>{_safe(text)}"]'
        )
    rel_kinds: list[tuple[type, str]] = [
        (Satisfy, "satisfy"), (Verify, "verify"), (Refine, "refine"),
        (Trace, "trace"), (DeriveRequirement, "derive"),
    ]
    for e in root.walk():
        for rel in getattr(e, "owned_relationships", []):
            for cls, label in rel_kinds:
                if isinstance(rel, cls):
                    src = rel.source; tgt = rel.target
                    if src is None or tgt is None:
                        continue
                    if not isinstance(src, RequirementDefinition):
                        lines.append(f'    {_nid(src)}["{_safe(src.name or src.kind)}"]')
                    lines.append(
                        f'    {_nid(src)} -.->|«{label}»| {_nid(tgt)}'
                    )
                    break
    return "\n".join(lines)


# --- State machine ------------------------------------------------------

def state_machine_mermaid(sm: StateMachineDefinition) -> str:
    lines = ["stateDiagram-v2", "    direction LR"]
    if sm.initial_state is not None:
        lines.append(f"    [*] --> {_safe(sm.initial_state.name or '?')}")
    for t in sm.transitions:
        src = t.transition_source
        tgt = t.transition_target
        if src is None or tgt is None:
            continue
        bits = []
        if t.trigger_event:
            bits.append(t.trigger_event)
        if t.guard is not None:
            bits.append("[" + (t.guard if isinstance(t.guard, str) else "λ") + "]")
        if t.effect is not None:
            bits.append("/ " + (t.effect if isinstance(t.effect, str) else "λ"))
        label = " ".join(bits)
        line = f"    {_safe(src.name or '?')} --> {_safe(tgt.name or '?')}"
        if label:
            line += f" : {_safe(label)}"
        lines.append(line)
    # Final state edges.
    for f in sm.final_states:
        lines.append(f"    {_safe(f.name or '?')} --> [*]")
    # State action descriptions.
    for s in sm.states:
        for kind, attr in (("entry", "entry_action"),
                           ("do",    "do_action"),
                           ("exit",  "exit_action")):
            v = getattr(s, attr, None)
            if v:
                v_str = v if isinstance(v, str) else "λ"
                lines.append(f"    {_safe(s.name or '?')} : {kind} / {_safe(v_str)}")
    return "\n".join(lines)


# --- Dispatch -----------------------------------------------------------

def diagram_mermaid(kind: str, target) -> str:
    if kind == "bdd":
        if not isinstance(target, Namespace):
            raise TypeError("bdd requires a Namespace target")
        return bdd_mermaid(target)
    if kind == "ibd":
        if not isinstance(target, PartDefinition):
            raise TypeError("ibd requires a PartDefinition target")
        return ibd_mermaid(target)
    if kind in ("requirements", "req"):
        if not isinstance(target, Namespace):
            raise TypeError("requirements requires a Namespace target")
        return requirements_mermaid(target)
    if kind in ("statemachine", "state", "sm"):
        if not isinstance(target, StateMachineDefinition):
            raise TypeError("statemachine requires a StateMachineDefinition target")
        return state_machine_mermaid(target)
    raise ValueError(f"Unknown diagram kind {kind!r}")
