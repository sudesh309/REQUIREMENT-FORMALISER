"""Model Advisor style checks and the Model Check runner.

The extra checks are ordinary validator rules (``engine.register_rule`` /
``register_repo_rule``), so they also appear in Validate (F5), the HTTP
``/api/validate`` endpoint and the MCP ``sysml_validate`` tool:

=================================  ========  ===================================================
Rule                               Severity  Reports
=================================  ========  ===================================================
``advisor.empty-composition``      info      an architecture / component with no components,
                                             ports or connectors (and no reference definition)
``advisor.unconnected-port``       warning   a component port not wired in the composition
                                             holding the component (per usage of a reference
                                             component), or a port of a composition with
                                             sub-components that none of them is wired to
``advisor.duplicate-name``         warning   sibling components / ports whose names differ only
                                             by case, or a usage port that repeats a port of
                                             its definition
``advisor.component-without-ports`` info     a component with sub-components or a reference
                                             definition but no ports
``advisor.missing-documentation``  info      architectures, components, ports and interfaces
                                             without documentation
=================================  ========  ===================================================

``run_model_check(repo)`` runs the whole validator and returns issues with
counts per severity and rule plus a catalogue of known rules.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional

from engine.structure import components_of, connectors_of, definition_of, ports_of
from engine.validator import (
    Severity, ValidationIssue, Validator, _ELEMENT_RULES, _REPO_RULES, register_repo_rule,
    register_rule,
)
from kerml.elements import Element
from sysmlv2.definitions import (
    ConnectionUsage, InterfaceDefinition, PartDefinition, PartUsage, PortDefinition, PortUsage,
)
from sysmlv2.definitions import is_part_usage, is_part_definition

from .common import documentation, in_library, is_profile_content

RULES: dict[str, dict] = {
    "advisor.empty-composition": {
        "title": "Empty composition", "severity": "info",
        "description": "Architecture or component with no components, ports or connectors."},
    "advisor.unconnected-port": {
        "title": "Unconnected port", "severity": "warning",
        "description": "A component port not wired in the composition that holds the "
                       "component (checked per usage of a reference component), or a port of "
                       "a composition that none of its components is wired to."},
    "advisor.duplicate-name": {
        "title": "Duplicate sibling name", "severity": "warning",
        "description": "Sibling components or ports whose names collide (ignoring case), "
                       "or a usage port repeating a port of its definition."},
    "advisor.component-without-ports": {
        "title": "Component without ports", "severity": "info",
        "description": "A component that cannot be connected because it has no ports."},
    "advisor.missing-documentation": {
        "title": "Missing documentation", "severity": "info",
        "description": "Architectures, components, ports and interfaces should be documented."},
}

# Descriptions of the core validator rules (features add their own rule ids).
CORE_RULES: dict[str, dict] = {
    "name.unique": {"title": "Unique member names", "severity": "error",
                    "description": "Members of a namespace must have distinct names."},
    "feature.typed": {"title": "Typed feature", "severity": "warning",
                      "description": "A plain KerML feature should be typed (it defaults to "
                                     "Anything); SysML usages such as components, ports and "
                                     "connectors default to their library definition."},
    "multiplicity.lower": {"title": "Multiplicity lower bound", "severity": "error",
                           "description": "Lower bound must be >= 0."},
    "multiplicity.upper": {"title": "Multiplicity upper bound", "severity": "error",
                           "description": "Upper bound must be >= the lower bound."},
    "redefinition.conformance": {"title": "Redefinition conformance", "severity": "error",
                                 "description": "A redefining feature must conform to the "
                                                "redefined feature's type."},
    "usage.typing": {"title": "Usage typed by a definition", "severity": "warning",
                     "description": "A usage is typically typed by a SysML definition."},
    "connection.ends": {"title": "Connector ends", "severity": "error",
                        "description": "A connector needs two ends."},
    "port.typed": {"title": "Port interface", "severity": "warning",
                   "description": "A port should be typed by an interface (port definition)."},
    "requirement.empty": {"title": "Requirement content", "severity": "info",
                          "description": "A requirement should have text or constraints."},
}


def _issue(sev: Severity, rule: str, msg: str, e: Element) -> ValidationIssue:
    return ValidationIssue(sev, rule, msg, e)


def _relevant(e: Element) -> bool:
    return e.owner is not None and not in_library(e) and not is_profile_content(e)


def _structure(e: Element) -> list[Element]:
    return [c for c in e.children
            if (isinstance(c, (PortUsage, ConnectionUsage,)) or is_part_usage(c)) or
            getattr(c, "kind", "").endswith("Usage")]


def _is_component(e: Element) -> bool:
    return is_part_usage(e) and (is_part_definition(e.owner) or is_part_usage(e.owner))


def check_element(e: Element) -> Iterator[ValidationIssue]:
    """Per-element advisor checks (registered with ``register_rule``)."""
    if not _relevant(e):
        return
    label = e.name or f"<{e.kind}>"
    if is_part_definition(e) or (is_part_usage(e) and definition_of(e) is None):
        if not _structure(e) and not (is_part_usage(e) and e.types):
            what = "Component" if is_part_usage(e) else "Architecture"
            yield _issue(Severity.INFO, "advisor.empty-composition",
                         f"{what} {label!r} is empty: add components or ports"
                         + ("" if is_part_definition(e) else
                            ", or reference a definition"), e)
    if _is_component(e) and not ports_of(e) and (components_of(e) or e.types):
        yield _issue(Severity.INFO, "advisor.component-without-ports",
                     f"Component {label!r} has no ports, so it cannot be connected", e)
    if (is_part_definition(e) or is_part_usage(e)):
        yield from _duplicates(e)
    documented = (PartDefinition, PortUsage, PortDefinition, InterfaceDefinition)
    if (isinstance(e, documented) or _is_component(e)) and e.name and not documentation(e):
        what = ("Port" if isinstance(e, PortUsage) else
                "Interface" if isinstance(e, (PortDefinition, InterfaceDefinition)) else
                "Component" if is_part_usage(e) else "Architecture")
        yield _issue(Severity.INFO, "advisor.missing-documentation",
                     f"{what} {label!r} has no documentation", e)


def _duplicates(comp: Element) -> Iterator[ValidationIssue]:
    members = components_of(comp) + ports_of(comp)
    typed_usage = is_part_usage(comp) and definition_of(comp) is not None
    groups: dict[str, list[Element]] = {}
    for m in members:
        if m.name:
            groups.setdefault(m.name.casefold(), []).append(m)
    for group in groups.values():
        if len(group) < 2:
            continue
        owners = {id(m.owner) for m in group}
        names = {m.name for m in group}
        if len(owners) == 1 and len(names) == 1:
            continue                     # exact duplicates: reported by name.unique
        first = group[0]
        for dup in group[1:]:
            if typed_usage and dup.owner is not comp and first.owner is not comp:
                continue                 # reported once, on the definition
            yield _issue(Severity.WARNING, "advisor.duplicate-name",
                         f"{dup.kind.replace('Usage', '').lower()} name {dup.name!r} collides "
                         f"with {first.name!r} in {comp.name or comp.kind!r}", dup)


def _compositions(repo) -> Iterable[Element]:
    for e in repo.root_package.walk():
        if not _relevant(e):
            continue
        if is_part_definition(e) or (is_part_usage(e) and definition_of(e) is None):
            yield e


def _ends(conns: list[ConnectionUsage]) -> list[tuple[Optional[Element], Element]]:
    out = []
    for c in conns:
        ends = [x for x in c.ends if x is not None]
        ctx = tuple(getattr(c, "end_contexts", ()) or ())
        for i, end in enumerate(ends):
            out.append((ctx[i] if len(ctx) == len(ends) else None, end))
    return out


def check_unconnected_ports(repo) -> Iterator[ValidationIssue]:
    """Repo-level advisor check: ports nothing is connected to, judged level by level.

    A component's port must be wired in the composition that holds the component; a
    connection inside the component (delegation to its parts) does not wire it to its
    neighbours. Reference components are judged per usage: FCC-L and FCC-R of one
    definition are reported separately, on the usage (the port itself belongs to the
    shared definition). A composition with sub-components (architecture, definition or
    inline component) must also wire each of its own ports to one of them.
    """
    for comp in _compositions(repo):
        subs = components_of(comp)
        if not subs:
            continue
        ends = _ends(connectors_of(comp))
        for c in subs:
            for p in ports_of(c):
                if not any(end is p and (ctx is None or ctx is c) for ctx, end in ends):
                    yield _issue(Severity.WARNING, "advisor.unconnected-port",
                                 f"Port {c.name}.{p.name} is not connected in "
                                 f"{comp.name or comp.kind}", p if p.owner is c else c)
        for p in ports_of(comp):
            if p.owner is comp and not any(end is p for _ctx, end in ends):
                yield _issue(Severity.WARNING, "advisor.unconnected-port",
                             f"Boundary port {comp.name}.{p.name} is not connected to any "
                             "component", p)


def install() -> None:
    """Register the advisor rules (idempotent)."""
    if check_element not in _ELEMENT_RULES:
        register_rule(check_element)
    if check_unconnected_ports not in _REPO_RULES:
        register_repo_rule(check_unconnected_ports)


install()


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def rule_catalog(found: Iterable[str] = ()) -> list[dict]:
    out = []
    for rid, meta in {**CORE_RULES, **RULES}.items():
        out.append({"id": rid, **meta, "source": "advisor" if rid in RULES else "core"})
    known = {r["id"] for r in out}
    for rid in sorted(set(found) - known):
        out.append({"id": rid, "title": rid, "severity": "", "description": "",
                    "source": "feature"})
    return out


def run_model_check(repo, *, severities: Optional[Iterable[str]] = None,
                    rules: Optional[Iterable[str]] = None) -> dict:
    """Validate `repo` and return issues (optionally filtered) with counts and the rule catalogue."""
    install()
    issues = Validator().validate(repo)
    rows = []
    for i in issues:
        e = i.element
        rows.append({"severity": i.severity.value, "rule": i.rule, "message": i.message,
                     "element_id": e.element_id, "qualified_name": e.qualified_name,
                     "name": e.name, "kind": e.kind,
                     "owner_id": e.owner.element_id if e.owner is not None else None})
    rows.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), r["rule"],
                             r["qualified_name"], r["message"]))
    sev = set(severities) if severities else None
    rset = set(rules) if rules else None
    shown = [r for r in rows if (sev is None or r["severity"] in sev)
             and (rset is None or r["rule"] in rset)]
    counts = {s: sum(1 for r in rows if r["severity"] == s) for s in ("error", "warning", "info")}
    by_rule: dict[str, int] = {}
    for r in rows:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
    return {"issues": shown, "total": len(rows), "counts": counts, "by_rule": by_rule,
            "rules": rule_catalog(by_rule)}
