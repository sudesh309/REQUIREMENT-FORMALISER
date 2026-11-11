"""Generate Mermaid syntax for SysML v2 diagrams.

Same diagram domains as `engine.diagram` (which emits Graphviz DOT) but
producing Mermaid text — ideal for in-browser rendering with mermaid.js,
GitHub / GitLab markdown, and the bundled web frontend.
"""
from __future__ import annotations

from kerml.elements import Element
from kerml.features import Feature
from kerml.namespaces import Namespace
from kerml.stereotypes import effective_applications
from sysmlv2.definitions import (
    ConnectionUsage, Definition, PartDefinition, PortUsage,
    RequirementDefinition, StateUsage, TransitionUsage,
)
from sysmlv2.definitions import is_part_definition
from sysmlv2.relationships import (
    Satisfy, Verify, Refine, Trace, DeriveRequirement,
)
from sysmlv2.state_machines import StateMachineDefinition


def _nid(e: Element) -> str:
    return "n" + e.element_id.replace("-", "")


def _safe(text: str) -> str:
    return (text or "").replace('"', "'").replace("\n", " ")


def _stereo(e: Element) -> str:
    apps = effective_applications(e)      # a reference component shows its definition's too
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
        if is_part_definition(d):
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

def _ibd_node(ctx, end) -> str:
    """Mermaid id of a connector end: a sub-component port is drawn per component usage,
    a boundary port on the frame, and a part-to-part end attaches to the part's box."""
    if ctx is not None:
        return f"{_nid(ctx)}_{_nid(end)}"
    if isinstance(end, PortUsage):
        return _nid(end)
    return f"sub_{_nid(end)}"


def _port_text(p: PortUsage) -> str:
    kind = getattr(p, "port_kind", "data")
    if kind != "data":
        return f"{p.name or '?'} · {kind}"
    return {"in": "▸ ", "inout": "◂▸ "}.get(p.direction.value, "") + (p.name or "?") + (
        " ▸" if p.direction.value == "out" else "")


def ibd_mermaid(part: PartDefinition) -> str:
    """Internal block diagram: boundary ports on the frame, sub-components with their ports,
    connectors between the drawn port nodes (directed for data and client/server)."""
    from .architecture import connector_label
    from .structure import components_of, connector_ends, connectors_of, ports_of
    lines = ["flowchart LR"]
    lines.append(f"    subgraph {_nid(part)}[\"{_safe(part.name or '?')}\"]")
    for p in ports_of(part):
        shape = ('>"{}"]' if p.direction.value == "in" else '(["{}"])').format(_safe(_port_text(p)))
        lines.append(f"        {_nid(p)}{shape}")
    for u in components_of(part):
        type_name = ", ".join(t.name or "?" for t in u.types)
        title = _safe(u.name or "?") + (f" : {_safe(type_name)}" if type_name else "")
        lines.append(f'        subgraph sub_{_nid(u)}["{title}"]')
        ports = ports_of(u)
        for p in ports:
            lines.append(f'            {_nid(u)}_{_nid(p)}(("{_safe(_port_text(p))}"))')
        if not ports:
            lines.append(f'            {_nid(u)}_body[" "]')
            lines.append(f"            style {_nid(u)}_body fill:none,stroke:none")
        lines.append("        end")
    lines.append("    end")
    for c in connectors_of(part):
        ends = connector_ends(c, part)
        if len(ends) < 2:
            continue
        a, b = _ibd_node(*ends[0]), _ibd_node(*ends[1])
        kinds = {getattr(p, "port_kind", "data") for _, p in ends}
        directed = all(isinstance(p, PortUsage) for _, p in ends) and "physical" not in kinds
        link = "-->" if directed else "---"
        text = connector_label(c, part)
        label = f'|"{_safe(text)}"|' if text else ""
        lines.append(f"    {a} {link}{label} {b}")
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
        if not is_part_definition(target):
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
