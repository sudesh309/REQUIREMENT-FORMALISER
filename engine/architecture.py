"""System Composer-style architecture modeling on top of SysML v2.

This module is the single engine-level implementation of architecture editing
used by the web API (``webapp/routes/architecture.py``), the MCP tools
(``mcp_server/tools/architecture.py``) and the textual parser. It follows the
cross-feature contract of ``engine/structure.py``:

- an *architecture* is a ``PartDefinition``; a *component* is a ``PartUsage``
  inside an architecture or another component (inline when untyped, a
  *reference component* when typed by a ``PartDefinition`` whose internals are
  shared by every usage);
- a *port* is a ``PortUsage`` with ``direction`` (in / out / inout) and
  ``port_kind`` (data / physical / client / server);
- a *connector* is a ``ConnectionUsage`` owned by the composition it wires,
  ``ends[0]`` = source port, ``ends[1]`` = target port and ``end_contexts[i]``
  the sub-component the port is reached through (None for a boundary port of
  the composition).

Every editing function validates its input and raises ``ArchitectureError``
(``.status`` is the HTTP status the web API answers with: 400 invalid, 404 not
found, 409 conflict) *before* changing the model, calls
``engine.notify_created`` for each element it creates and deletes only through
``Repository.remove``.

Project-level *model type* ('system' or 'software') decides which port kinds
are allowed; it is persisted by a repository codec. Layout (component boxes,
port sides, connector points) lives in ``tool_data`` and is persisted with the
element.
"""
from __future__ import annotations

import copy
import json
import math
import re
import uuid
from typing import Any, Callable, Iterable, NamedTuple, Optional

from kerml.elements import Documentation, Element
from kerml.features import Feature, FeatureDirection, MultiplicityRange, Redefinition
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import stereotypes_on
from kerml.types import Type
from sysmlv2.definitions import (
    PORT_KINDS, ConnectionUsage, PartDefinition, PartUsage, PortUsage,
)
from sysmlv2.state_machines import StateMachineDefinition

from engine.graph_export import register_edge_source
from engine.hooks import notify_created
from engine.repository import register_removal_hook
from engine.serializer import register_codec, register_repo_codec
from engine.structure import (
    component_tree, components_of, connector_ends, connectors_of, definition_of,
    internal_owners, is_component, ports_of,
)
from engine.validator import Severity, ValidationIssue, register_repo_rule


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ArchitectureError(ValueError):
    """Invalid architecture edit. ``status`` is the matching HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _not_found(what: str) -> ArchitectureError:
    return ArchitectureError(f"{what} not found", 404)


def _conflict(message: str) -> ArchitectureError:
    return ArchitectureError(message, 409)


# ---------------------------------------------------------------------------
# Model type
# ---------------------------------------------------------------------------

MODEL_TYPES: tuple[str, ...] = ("system", "software")
ALLOWED_PORT_KINDS: dict[str, tuple[str, ...]] = {
    "system": ("data", "physical"),
    "software": ("data", "client", "server"),
}
DIRECTIONS: tuple[str, ...] = ("in", "out", "inout")


def model_type(repo) -> str:
    t = getattr(repo, "model_type", "system")
    return t if t in MODEL_TYPES else "system"


def allowed_port_kinds(repo_or_type) -> tuple[str, ...]:
    t = repo_or_type if isinstance(repo_or_type, str) else model_type(repo_or_type)
    return ALLOWED_PORT_KINDS.get(t, ALLOWED_PORT_KINDS["system"])


def _all_ports(repo) -> list[PortUsage]:
    return [e for e in repo.root_package.walk() if isinstance(e, PortUsage)]


def set_model_type(repo, new_type: str, *, force: bool = False) -> str:
    """Switch the project between a 'system' and a 'software' architecture model.

    Refuses (409) when ports use kinds the new type does not allow, unless
    ``force`` is set (the validator then reports them).
    """
    if new_type not in MODEL_TYPES:
        raise ArchitectureError(f"model type must be one of {list(MODEL_TYPES)}, not {new_type!r}")
    allowed = allowed_port_kinds(new_type)
    bad = [p for p in _all_ports(repo) if p.port_kind not in allowed]
    if bad and not force:
        names = ", ".join(f"{p.qualified_name} ({p.port_kind})" for p in bad[:5])
        raise _conflict(f"{len(bad)} port(s) use kinds a {new_type} architecture does not allow: "
                        f"{names}; change them first or pass force")
    repo.model_type = new_type
    return new_type


def check_port_kind(repo, kind: str) -> None:
    if kind not in PORT_KINDS:
        raise ArchitectureError(f"port kind must be one of {list(PORT_KINDS)}, not {kind!r}")
    if kind not in allowed_port_kinds(repo):
        t = model_type(repo)
        need = "software" if kind in ("client", "server") else "system"
        raise ArchitectureError(f"{kind} ports are not allowed in a {t} architecture "
                                f"(use a {need} model); allowed: {list(allowed_port_kinds(repo))}")


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

_TRAILING_DIGITS = re.compile(r"\d+$")
_BAD_NAME = re.compile(r"::|[.\n\r\t]")


def unique_name(base: str, taken: Iterable[str]) -> str:
    """``base`` if free, else ``<stem>1``, ``<stem>2``... (System Composer numbering)."""
    taken = set(taken)
    base = (base or "Component").strip() or "Component"
    if base not in taken:
        return base
    stem = _TRAILING_DIGITS.sub("", base) or base
    i = 1
    while f"{stem}{i}" in taken:
        i += 1
    return f"{stem}{i}"


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ArchitectureError("name must be a non-empty string")
    name = name.strip()
    if _BAD_NAME.search(name):
        raise ArchitectureError(f"name {name!r} may not contain '::', '.', tabs or line breaks")
    return name


def _names_in(owners: Iterable[Element], exclude: Optional[Element] = None) -> set[str]:
    out: set[str] = set()
    for o in owners:
        for x in o.owned_elements:
            if x is not exclude and x.name:
                out.add(x.name)
    return out


def member_names(composition: Element, exclude: Optional[Element] = None) -> set[str]:
    """Names already used inside a composition (its own and, for a reference, its definition's)."""
    return _names_in(internal_owners(composition), exclude)


def sibling_names(e: Element) -> set[str]:
    owner = e.owner
    if owner is None:
        return set()
    owners = [owner]
    # A usage's own extras share the namespace view with its definition's members.
    if isinstance(owner, PartUsage):
        owners = internal_owners(owner)
    return _names_in(owners, exclude=e)


def _usages_of(repo, definition: Element) -> list[PartUsage]:
    return [u for u in repo.root_package.walk()
            if isinstance(u, PartUsage) and definition_of(u) is definition]


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

def require_composition(e: Optional[Element], what: str = "composition") -> Element:
    if e is None:
        raise _not_found(what)
    if not isinstance(e, (PartDefinition, PartUsage)):
        raise ArchitectureError(f"{e.qualified_name} ({e.kind}) is not an architecture or component")
    return e


def require_component(e: Optional[Element], what: str = "component") -> PartUsage:
    if e is None:
        raise _not_found(what)
    if not is_component(e):
        raise ArchitectureError(f"{e.qualified_name} ({e.kind}) is not a component "
                                "(a part usage inside an architecture or component)")
    return e  # type: ignore[return-value]


def edit_owner(composition: Element) -> Element:
    """Where new internals of `composition` go: its definition for a reference component."""
    return definition_of(composition) or composition


def _detach(e: Element, repo=None) -> None:
    """Remove `e` from its owner (owned_elements, memberships) without deleting it."""
    old = e.owner
    if old is None:
        return
    old.owned_elements = [x for x in old.owned_elements if x is not e]
    if isinstance(old, Namespace):
        dead = [m for m in old.memberships if m.member is e]
        if dead:
            old.memberships = [m for m in old.memberships if m.member is not e]
            old.owned_relationships = [r for r in old.owned_relationships
                                       if not any(r is m for m in dead)]
            if repo is not None:
                for m in dead:
                    repo.registry.unregister(m)
    e.owner = None


def reparent(e: Element, new_owner: Element, repo=None) -> Element:
    """Move `e` under `new_owner`, keeping its id, contents and references."""
    if e.owner is new_owner:
        return e
    _detach(e, repo)
    new_owner.own(e)
    if hasattr(e, "featuring_type") and isinstance(new_owner, Type):
        e.featuring_type = new_owner
    if repo is not None:
        repo.registry.register_tree(new_owner)
    return e


def _enclosing_definitions(e: Element) -> set[int]:
    out: set[int] = set()
    node: Optional[Element] = e
    while node is not None:
        if isinstance(node, PartDefinition):
            out.add(id(node))
        d = definition_of(node)
        if d is not None:
            out.add(id(d))
        node = node.owner
    return out


def _definitions_reachable(e: Element) -> set[int]:
    out: set[int] = set()
    if isinstance(e, PartDefinition):
        out.add(id(e))
    for c, _depth, _parent in component_tree(e):
        d = definition_of(c)
        if d is not None:
            out.add(id(d))
    return out


def _check_no_cycle(container: Element, candidate: Element) -> None:
    """Refuse to place `candidate` (a definition or a component) inside `container` if it recurses."""
    if _definitions_reachable(candidate) & _enclosing_definitions(container):
        raise ArchitectureError(f"placing {candidate.name!r} inside {container.name!r} would make "
                                "the architecture contain itself")


def model_package(e: Element) -> Element:
    node: Optional[Element] = e.owner
    while node is not None and not isinstance(node, Package):
        node = node.owner
    return node or e.root()


# ---------------------------------------------------------------------------
# Badges (summary contract)
# ---------------------------------------------------------------------------

def owns_state_machine(e: Element) -> bool:
    return any(isinstance(x, StateMachineDefinition)
               for o in internal_owners(e) for x in o.owned_elements)


def component_badges(e: Element) -> list[str]:
    """Classification badges for a component: ref|inline, leaf|composite, SM."""
    if not is_component(e):
        return []
    out = ["ref" if definition_of(e) is not None else "inline"]
    out.append("composite" if components_of(e) else "leaf")
    if owns_state_machine(e):
        out.append("SM")
    return out


def port_badges(p: Element) -> list[str]:
    if not isinstance(p, PortUsage):
        return []
    out = []
    if p.direction is not FeatureDirection.NONE and p.port_kind == "data":
        out.append(p.direction.value)
    if p.port_kind != "data":
        out.append(p.port_kind)
    return out


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def create_architecture(repo, name: Optional[str] = None, package: Optional[Element] = None
                        ) -> PartDefinition:
    """A new root architecture (PartDefinition) in `package` (default: project root)."""
    pkg = package or repo.root_package
    if not isinstance(pkg, Package):
        raise ArchitectureError(f"{pkg.qualified_name} is not a package")
    taken = _names_in([pkg])
    if name:
        name = check_name(name)
        if name in taken:
            raise _conflict(f"{pkg.name} already contains an element named {name!r}")
    else:
        name = unique_name("Architecture", taken)
    arch = PartDefinition(name=name)
    pkg.own(arch)
    notify_created(arch, repo)
    return arch


def add_component(repo, composition: Element, name: Optional[str] = None,
                  definition: Optional[Element] = None,
                  layout: Optional[dict] = None) -> PartUsage:
    """Add a component (inline, or a reference when `definition` is given)."""
    comp = require_composition(composition)
    taken = member_names(comp)
    if name:
        name = check_name(name)
        if name in taken:
            raise _conflict(f"{comp.name} already has a member named {name!r}")
    else:
        name = unique_name(definition.name if isinstance(definition, PartDefinition) and definition.name
                           else "Component", taken)
    if definition is not None:
        if not isinstance(definition, PartDefinition):
            raise ArchitectureError(f"{definition.qualified_name} is not a PartDefinition")
        _check_no_cycle(comp, definition)
    lay = clean_box(layout) if layout else None
    u = PartUsage(name=name, multiplicity=MultiplicityRange(1, 1))
    if definition is not None:
        u.add_type(definition)
    edit_owner(comp).own(u)
    if lay:
        u.tool_data["layout"] = lay
    notify_created(u, repo)
    return u


def rename(repo, element: Element, name: str) -> Element:
    """Rename a component, port, connector or architecture; names stay unique among siblings."""
    if element is None:
        raise _not_found("element")
    name = check_name(name)
    if name == element.name:
        return element
    if name in sibling_names(element):
        owner = element.owner.name if element.owner else "the model"
        raise _conflict(f"{owner} already has a member named {name!r}")
    if isinstance(element, PortUsage) and isinstance(element.owner, PartDefinition):
        for u in _usages_of(repo, element.owner):
            if name in _names_in([u]):
                raise _conflict(f"component {u.qualified_name} already has a member named {name!r}")
    element.name = name
    return element


def set_definition(repo, component: Element, definition: Optional[Element]) -> PartUsage:
    """Retype a component: make it a reference to `definition`, or clear the typing (None).

    Connectors that reached the old definition's ports through this component are
    re-attached to the new definition's ports of the same name; the others stay
    and show up as broken (validator / view ``issues``), as in System Composer.
    """
    c = require_component(component)
    old = definition_of(c)
    if definition is not None:
        if not isinstance(definition, PartDefinition):
            raise ArchitectureError(f"{definition.qualified_name} is not a PartDefinition")
        _check_no_cycle(c.owner, definition)
    affected = []
    if old is not None and old is not definition:
        for conn in [x for x in repo.root_package.walk() if isinstance(x, ConnectionUsage)]:
            ends = connector_ends(conn)
            if any(ctx is c and p.owner is old for ctx, p in ends):
                affected.append((conn, ends))
    c.feature_typings = []
    c.owned_relationships = [r for r in c.owned_relationships if r.kind != "FeatureTyping"]
    if definition is not None:
        c.add_type(definition)
    for conn, ends in affected:
        new_ends = []
        for ctx, p in ends:
            if ctx is c and p.owner is old and definition is not None:
                p = next((q for q in ports_of(definition) if q.name == p.name), p)
            new_ends.append((ctx, p))
        conn.ends = [p for _, p in new_ends]
        conn.end_contexts = tuple(ctx for ctx, _ in new_ends)
    return c


def delete_elements(repo, elements: Iterable[Element]) -> list[str]:
    """Delete components, ports and connectors (and whatever depends on them)."""
    elements = list(elements)
    for e in elements:
        if e is None:
            raise _not_found("element")
        if e is repo.root_package:
            raise ArchitectureError("cannot delete the project root")
    deleted = []
    for e in elements:
        if e.owner is None or repo.by_id(e.element_id) is None:
            continue   # already removed with an earlier one
        deleted.append(e.element_id)
        repo.remove(e)
    return deleted


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

_DEFAULT_PORT_NAMES = {"in": "In", "out": "Out", "inout": "InOut",
                       "physical": "Conn", "client": "Client", "server": "Server"}


def _check_interface(interface: Optional[Element]) -> Optional[Type]:
    if interface is None:
        return None
    if not isinstance(interface, Type) or isinstance(interface, Feature):
        raise ArchitectureError(f"{interface.qualified_name} ({interface.kind}) cannot type a port; "
                                "use a port, interface, item or attribute definition")
    return interface


def normalize_direction(direction: Optional[str], kind: str) -> FeatureDirection:
    if kind != "data":
        return FeatureDirection.INOUT      # physical and client/server ports are non-directional
    d = direction or "in"
    if d not in DIRECTIONS:
        raise ArchitectureError(f"direction must be one of {list(DIRECTIONS)}, not {d!r}")
    return FeatureDirection(d)


def add_port(repo, owner: Element, name: Optional[str] = None, direction: Optional[str] = "in",
             kind: str = "data", interface: Optional[Element] = None, *,
             usage_only: bool = False, layout: Optional[dict] = None) -> PortUsage:
    """Add a port to a component or architecture.

    Viewing a composition's internals, its own ports are the boundary ports. On a
    reference component the port goes to the definition (so every usage shows it)
    unless ``usage_only`` is set.
    """
    comp = require_composition(owner, "port owner")
    kind = kind or "data"
    check_port_kind(repo, kind)
    fdir = normalize_direction(direction, kind)
    iface = _check_interface(interface)
    target = comp if usage_only else edit_owner(comp)
    taken = member_names(comp)
    if isinstance(target, PartDefinition):
        for u in _usages_of(repo, target):
            taken |= _names_in([u])
    if name:
        name = check_name(name)
        if name in taken:
            raise _conflict(f"{comp.name} already has a port or member named {name!r}")
    else:
        base = _DEFAULT_PORT_NAMES[kind if kind != "data" else fdir.value]
        name = unique_name(base, taken)
    lay = clean_port_layout(layout) if layout else None
    p = PortUsage(name=name, port_kind=kind, direction=fdir, multiplicity=MultiplicityRange(1, 1))
    if iface is not None:
        p.add_type(iface)
    target.own(p)
    if lay:
        p.tool_data["port_layout"] = lay
    notify_created(p, repo)
    return p


_UNSET: Any = object()


def connectors_touching(repo, port: Element) -> list[ConnectionUsage]:
    return [c for c in repo.root_package.walk()
            if isinstance(c, ConnectionUsage) and any(x is port for x in c.ends)]


def update_port(repo, port: Element, *, name: Optional[str] = None, direction: Optional[str] = None,
                kind: Optional[str] = None, interface: Any = _UNSET, force: bool = False) -> PortUsage:
    """Change a port; refuses (409) when that would break existing connectors unless ``force``."""
    if not isinstance(port, PortUsage):
        raise ArchitectureError("not a port" if port is not None else "port not found",
                                400 if port is not None else 404)
    new_name = port.name
    if name is not None and name != port.name:
        new_name = check_name(name)
        if new_name in sibling_names(port):
            raise _conflict(f"{port.owner.name} already has a member named {new_name!r}")
    new_kind = kind or port.port_kind
    if kind is not None:
        check_port_kind(repo, kind)
    if direction is not None or kind is not None:
        current = port.direction.value if port.direction is not FeatureDirection.NONE else "in"
        new_dir = normalize_direction(direction or current, new_kind)
    else:
        new_dir = port.direction
    new_types = list(port.types)
    if interface is not _UNSET:
        iface = _check_interface(interface)
        new_types = [iface] if iface is not None else []
    old = (port.port_kind, port.direction, list(port.types))
    port.port_kind, port.direction = new_kind, new_dir
    _set_types(port, new_types)
    if not force:
        broken = []
        for c in connectors_touching(repo, port):
            problems = connector_problems(c)
            if problems:
                broken.append(f"{c.name or c.element_id}: {problems[0][1]}")
        if broken:
            port.port_kind, port.direction = old[0], old[1]
            _set_types(port, old[2])
            raise _conflict("change would break connector(s): " + "; ".join(broken[:5]))
    if new_name != port.name:
        rename(repo, port, new_name)
    return port


def _set_types(f: Feature, types: list[Type]) -> None:
    if [t for t in f.types] == types:
        return
    f.feature_typings = []
    f.owned_relationships = [r for r in f.owned_relationships if r.kind != "FeatureTyping"]
    for t in types:
        f.add_type(t)


# ---------------------------------------------------------------------------
# Connection rules
# ---------------------------------------------------------------------------

Endpoint = tuple[Optional[Element], Element]   # (context component or None, port)


def _flip(role: str) -> str:
    return {"in": "out", "out": "in", "client": "server", "server": "client"}.get(role, role)


def data_role(port: PortUsage, boundary: bool) -> str:
    """'out' (source), 'in' (sink) or 'inout' as seen from inside the composition."""
    d = port.direction
    if d is FeatureDirection.IN or d is FeatureDirection.OUT:
        return _flip(d.value) if boundary else d.value
    return "inout"


def service_role(port: PortUsage, boundary: bool) -> str:
    return _flip(port.port_kind) if boundary else port.port_kind


def _label(ep: Endpoint) -> str:
    ctx, port = ep
    if ctx is None:
        return f"{port.name} (boundary)"
    return f"{ctx.name}.{port.name}"


def _same(a: Endpoint, b: Endpoint) -> bool:
    return a[0] is b[0] and a[1] is b[1]


def _scope_problem(composition: Element, ep: Endpoint) -> Optional[str]:
    ctx, port = ep
    if ctx is None:
        if not any(port is p for p in ports_of(composition)):
            return (f"{port.name} is not a port of {composition.name}; ports must belong to the "
                    "composition or its direct sub-components")
        return None
    if not any(ctx is c for c in components_of(composition)):
        return f"{ctx.name} is not a direct sub-component of {composition.name}"
    if not any(port is p for p in ports_of(ctx)):
        return f"{port.name} is not a port of {ctx.name}"
    return None


class Check(NamedTuple):
    """Result of :func:`classify`."""
    problem: Optional[str]
    rule: Optional[str]
    kind: str
    source: Endpoint
    target: Endpoint


def classify(composition: Element, src: Endpoint, dst: Endpoint) -> Check:
    """Check one connection in isolation.

    ``problem`` is None when the connection is valid (else a message, with
    ``rule`` the validator rule id); ``kind`` is 'data' | 'physical' |
    'client-server'; (source, target) is the connection oriented from output to
    input (data) or client to server.
    """
    for ep in (src, dst):
        if not isinstance(ep[1], PortUsage):
            return Check("connector ends must be ports", "arch.connector.scope", "unknown", src, dst)
    if _same(src, dst):
        return Check("cannot connect a port to itself", "arch.connector.self", "unknown", src, dst)
    for ep in (src, dst):
        problem = _scope_problem(composition, ep)
        if problem:
            return Check(problem, "arch.connector.scope", "unknown", src, dst)
    sp, dp = src[1], dst[1]
    ks, kd = sp.port_kind, dp.port_kind
    if "physical" in (ks, kd):
        if ks != kd:
            return Check(f"physical port {_label(src if ks == 'physical' else dst)} can only connect "
                         f"to another physical port, not a {kd if ks == 'physical' else ks} port",
                         "arch.connector.kind", "physical", src, dst)
        return Check(None, None, "physical", src, dst)
    if ks in ("client", "server") or kd in ("client", "server"):
        if ks == "data" or kd == "data":
            return Check("data ports cannot connect to client/server ports",
                         "arch.connector.kind", "client-server", src, dst)
        rs, rd = service_role(sp, src[0] is None), service_role(dp, dst[0] is None)
        if {rs, rd} != {"client", "server"}:
            return Check(f"a client port must connect to a server port ({_label(src)} acts as {rs}, "
                         f"{_label(dst)} acts as {rd} here)", "arch.connector.kind", "client-server",
                         src, dst)
        return Check(None, None, "client-server", *((src, dst) if rs == "client" else (dst, src)))
    rs, rd = data_role(sp, src[0] is None), data_role(dp, dst[0] is None)

    def ok(a: str, b: str) -> bool:
        return a in ("out", "inout") and b in ("in", "inout")
    if ok(rs, rd):
        return Check(None, None, "data", src, dst)
    if ok(rd, rs):
        return Check(None, None, "data", dst, src)
    return Check(f"cannot connect {_label(src)} ({rs}) to {_label(dst)} ({rd}): data connectors go "
                 "from an output (or a boundary input) to an input (or a boundary output)",
                 "arch.connector.direction", "data", src, dst)


def connector_kind(composition: Element, conn: ConnectionUsage) -> str:
    ends = connector_ends(conn, composition)
    if len(ends) != 2 or not all(isinstance(p, PortUsage) for _, p in ends):
        return "unknown"
    kinds = {p.port_kind for _, p in ends}
    if "physical" in kinds:
        return "physical"
    if kinds & {"client", "server"}:
        return "client-server"
    return "data"


def _existing_conflict(composition: Element, kind: str, src: Endpoint, dst: Endpoint,
                       exclude: Optional[ConnectionUsage] = None) -> Optional[str]:
    for c in connectors_of(composition):
        if c is exclude:
            continue
        ends = connector_ends(c, composition)
        if len(ends) != 2:
            continue
        a, b = ends[0], ends[1]
        if (_same(a, src) and _same(b, dst)) or (_same(a, dst) and _same(b, src)):
            return f"{_label(src)} and {_label(dst)} are already connected ({c.name})"
        if (kind == "data" and _same(b, dst) and isinstance(dst[1], PortUsage)
                and data_role(dst[1], dst[0] is None) == "in"
                and connector_kind(composition, c) == "data"):
            return (f"input {_label(dst)} already has an incoming connection from {_label(a)}; "
                    "an input can only be driven by one source (branch from the output instead)")
    return None


def connector_problems(conn: ConnectionUsage) -> list[tuple[str, str]]:
    """``[(rule, message), ...]`` for a stored connector (empty when valid)."""
    comp = conn.owner
    if not isinstance(comp, (PartDefinition, PartUsage)):
        return []
    ends = connector_ends(conn, comp)
    if len(ends) != 2:
        return []
    if not all(isinstance(p, PortUsage) for _, p in ends):
        return []            # part-to-part (legacy) connectors are not checked here
    out: list[tuple[str, str]] = []
    stored = tuple(getattr(conn, "end_contexts", ()) or ())
    if stored and len(stored) != len(conn.ends):
        out.append(("arch.connector.context", "end contexts do not match the connector ends"))
    chk = classify(comp, ends[0], ends[1])
    if chk.problem:
        out.append((chk.rule, chk.problem))
        return out
    if chk.kind == "data" and not (_same(chk.source, ends[0]) and _same(chk.target, ends[1])):
        out.append(("arch.connector.direction",
                    f"connector runs from input {_label(ends[0])} to output {_label(ends[1])}; "
                    "ends[0] must be the source"))
    return out


def can_connect(composition: Element, src: Endpoint, dst: Endpoint) -> dict:
    """Non-mutating check for canvas drag feedback."""
    chk = classify(composition, src, dst)
    problem = chk.problem
    if problem is None:
        problem = _existing_conflict(composition, chk.kind, chk.source, chk.target)
    return {"ok": problem is None, "reason": problem, "kind": chk.kind,
            "swapped": problem is None and not (_same(chk.source, src) and _same(chk.target, dst))}


# ---------------------------------------------------------------------------
# Connecting (including cross-hierarchy punch-through)
# ---------------------------------------------------------------------------

def resolve_port(owner: Element, port: Any) -> PortUsage:
    if isinstance(port, PortUsage):
        return port
    if isinstance(port, str) and port:
        hit = next((p for p in ports_of(owner) if p.name == port or p.element_id == port), None)
        if hit is not None:
            return hit
        raise _not_found(f"port {port!r} on {owner.name}")
    if port is None:
        raise ArchitectureError(f"a port on {owner.name} is required")
    raise ArchitectureError(f"{getattr(port, 'qualified_name', port)} is not a port")


def _chain(composition: Element, component: Element) -> list[Element]:
    """[c1, ..., ck]: c1 a direct sub-component of `composition`, ck = `component`."""
    direct = components_of(composition)
    chain = [component]
    node = component
    while not any(node is c for c in direct):
        parent = node.owner
        if not isinstance(parent, PartUsage):
            if isinstance(parent, PartDefinition) and parent is not edit_owner(composition):
                raise ArchitectureError(
                    f"{component.name} is inside the referenced definition {parent.name}; connect to a "
                    "port of the reference component instead (or inline it first)")
            raise ArchitectureError(f"{component.name} is not inside {composition.name}")
        chain.insert(0, parent)
        node = parent
        if len(chain) > 64:
            raise ArchitectureError("component hierarchy too deep")
    return chain


def _punch_through(repo, chain: list[Element], port: PortUsage, created: list[Element]) -> Endpoint:
    """Expose `port` of chain[-1] on chain[0] by adding boundary ports level by level."""
    ctx, p = chain[-1], port
    for parent in reversed(chain[:-1]):
        reuse = None
        for c in connectors_of(parent):
            ends = connector_ends(c, parent)
            if len(ends) != 2:
                continue
            for i in (0, 1):
                if _same(ends[i], (ctx, p)) and ends[1 - i][0] is None:
                    reuse = ends[1 - i][1]
        if reuse is None:
            direction = p.direction.value if p.direction is not FeatureDirection.NONE else "inout"
            bp = add_port(repo, parent, name=None if not p.name else
                          unique_name(p.name, member_names(parent)),
                          direction=direction, kind=p.port_kind,
                          interface=p.types[0] if p.types else None, usage_only=True)
            created.append(bp)
            created.append(connect(repo, parent, (ctx, p), (None, bp)))
            reuse = bp
        ctx, p = parent, reuse
    return (ctx, p)


def _endpoint(repo, composition: Element, spec: Any, created: list[Element]) -> Endpoint:
    """Normalize an endpoint given as (component|None, port) or {component?, port}."""
    if isinstance(spec, dict):
        component, port = spec.get("component"), spec.get("port")
    else:
        component, port = spec
    if component is None:
        return (None, resolve_port(composition, port))
    if not isinstance(component, PartUsage):
        raise ArchitectureError(f"{getattr(component, 'qualified_name', component)} is not a component")
    p = resolve_port(component, port)
    if any(component is c for c in components_of(composition)):
        return (component, p)
    chain = _chain(composition, component)
    return _punch_through(repo, chain, p, created)


def connect(repo, composition: Element, source: Any, target: Any, name: Optional[str] = None
            ) -> ConnectionUsage:
    """Connect two ports inside `composition` (System Composer rules).

    Endpoints are ``(component_or_None, port)`` tuples or ``{"component", "port"}``
    dicts; ``port`` may be a PortUsage or a port name. A component deeper in the
    hierarchy is reached by adding boundary ports on the components in between
    (cross-hierarchy connection). Data connectors are oriented output -> input
    and client -> server automatically.
    """
    comp = require_composition(composition)
    if name is not None:
        name = check_name(name)
        if name in member_names(comp):
            raise _conflict(f"{comp.name} already has a member named {name!r}")
    created: list[Element] = []
    try:
        src = _endpoint(repo, comp, source, created)
        dst = _endpoint(repo, comp, target, created)
        chk = classify(comp, src, dst)
        if chk.problem:
            raise ArchitectureError(chk.problem)
        s, d = chk.source, chk.target
        problem = _existing_conflict(comp, chk.kind, s, d)
        if problem:
            raise _conflict(problem)
    except ArchitectureError:
        for e in reversed(created):
            if e.owner is not None:
                repo.remove(e)
        raise
    owner = edit_owner(comp)
    if comp is not owner and any(x is not None and x.owner is comp for x in (s[0], s[1], d[0], d[1])):
        owner = comp
    conn = ConnectionUsage(name=name or unique_name("Connector", member_names(comp)),
                           ends=[s[1], d[1]], end_contexts=(s[0], d[0]))
    owner.own(conn)
    notify_created(conn, repo)
    return conn


def set_connector_points(conn: ConnectionUsage, points: Optional[list]) -> None:
    if points is None:
        conn.tool_data.pop("points", None)
        return
    conn.tool_data["points"] = clean_points(points)


# ---------------------------------------------------------------------------
# Deep copy
# ---------------------------------------------------------------------------

_REL_LISTS = ("owned_relationships", "memberships", "imports", "specializations",
              "conjugations", "feature_typings", "subsettings", "redefinitions")
_SKIP_ATTRS = {"owner", "owned_elements", "annotations", "tool_data", "element_id",
               "multiplicity", *_REL_LISTS}


def _json_copy(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        try:
            out[k] = json.loads(json.dumps(v))
        except (TypeError, ValueError):
            pass
    return out


def clone_forest(roots: list[Element], mapping: Optional[dict] = None
                 ) -> tuple[list[Element], dict, list]:
    """Deep-copy element subtrees.

    Returns ``(copies, mapping, stereotype_apps)``: ``mapping`` maps ``id(original)``
    to its copy; references inside the copied set are remapped, references
    outside stay shared. Typings, specializations, subsettings and docs are
    rebuilt; stereotype applications are returned as ``(copy, stereotype, values)``
    for the caller to apply after ``notify_created``. Traceability links are not copied.
    """
    mapping = {} if mapping is None else mapping
    originals: list[Element] = []
    for r in roots:
        originals.extend(r.walk())
    for o in originals:
        c = copy.copy(o)
        c.element_id = str(uuid.uuid4())
        mapping[id(o)] = c

    def remap(v):
        return mapping.get(id(v), v) if isinstance(v, Element) else v

    apps = []
    for o in originals:
        c = mapping[id(o)]
        c.owner = None
        c.owned_elements = []
        for attr in _REL_LISTS:
            if attr in vars(c):
                setattr(c, attr, [])
        c.annotations = []
        c.tool_data = _json_copy(o.tool_data)
        if isinstance(o, Feature):
            c.multiplicity = MultiplicityRange(o.multiplicity.lower, o.multiplicity.upper)
        for attr, value in list(vars(c).items()):
            if attr in _SKIP_ATTRS:
                continue
            if isinstance(value, Element):
                setattr(c, attr, remap(value))
            elif isinstance(value, list):
                setattr(c, attr, [remap(v) for v in value])
            elif isinstance(value, tuple):
                setattr(c, attr, tuple(remap(v) for v in value))
            elif isinstance(value, (dict, set)):
                setattr(c, attr, copy.copy(value))
    for o in originals:
        c = mapping[id(o)]
        for child in o.owned_elements:
            c.own(mapping[id(child)])
        if isinstance(o, Feature):
            for t in o.types:
                c.add_type(remap(t))
            for s in o.subsettings:
                if s.target is None:
                    continue
                if isinstance(s, Redefinition):
                    c.redefine(remap(s.target))
                else:
                    c.subset(remap(s.target))
        if isinstance(o, Type):
            for s in o.specializations:
                if s.target is not None:
                    c.specialize(remap(s.target))
            for cj in getattr(o, "conjugations", []):
                if cj.target is not None:
                    c.conjugate(remap(cj.target))
        if isinstance(o, Namespace):
            for imp in o.imports:
                if imp.target is not None:
                    c.add_import(remap(imp.target), recursive=imp.recursive)
        for a in o.annotations:
            if isinstance(a, Documentation):
                c.add_annotation(Documentation(body=a.body))
        for app in stereotypes_on(o):
            apps.append((c, app.stereotype, dict(app.values)))
    return [mapping[id(r)] for r in roots], mapping, apps


def _finish_copies(repo, copies: list[Element], apps: list) -> None:
    for c in copies:
        for x in list(c.walk()):
            notify_created(x, repo)
    for target, st, values in apps:
        if any(a.stereotype is st for a in stereotypes_on(target)):
            continue
        try:
            st.apply(target, values)
        except (TypeError, KeyError):
            pass
    for c in copies:
        repo.registry.register_tree(c)


def duplicate(repo, components: list[Element], target: Optional[Element] = None,
              offset: tuple[float, float] = (30, 30)) -> list[PartUsage]:
    """Deep-copy components (ports, sub-components, internal connectors, stereotypes,
    tool_data) into `target` (default: their own composition) with fresh names.
    Connectors between the copied components are copied too (copy-paste)."""
    comps = [require_component(c) for c in components]
    if not comps:
        raise ArchitectureError("select at least one component to duplicate")
    src_owner = comps[0].owner
    if any(c.owner is not src_owner for c in comps):
        raise ArchitectureError("components to duplicate must share one parent")
    dest = require_composition(target) if target is not None else src_owner
    for c in comps:
        _check_no_cycle(dest, c)      # a copy may not contain (a reference to) its new container
    copies, mapping, apps = clone_forest(comps)
    owner = edit_owner(dest)
    taken = member_names(dest)
    dx, dy = (offset or (30, 30))
    for orig, cp in zip(comps, copies):
        cp.name = unique_name(orig.name or "Component", taken)
        taken.add(cp.name)
        lay = cp.tool_data.get("layout")
        if isinstance(lay, dict) and "x" in lay and "y" in lay:
            cp.tool_data["layout"] = {**lay, "x": lay["x"] + dx, "y": lay["y"] + dy}
        owner.own(cp)
    # Connectors between selected components, copied into the destination.
    selected = {id(c) for c in comps}
    conn_copies = []
    for conn in connectors_of(src_owner):
        ends = connector_ends(conn, src_owner)
        if len(ends) == 2 and all(ctx is not None and id(ctx) in selected for ctx, _ in ends):
            cc = ConnectionUsage(name=unique_name(conn.name or "Connector", taken),
                                 ends=[mapping.get(id(p), p) for _, p in ends],
                                 end_contexts=tuple(mapping[id(ctx)] for ctx, _ in ends))
            cc.tool_data = _json_copy(conn.tool_data)
            cc.tool_data.pop("points", None)
            taken.add(cc.name)
            owner.own(cc)
            conn_copies.append(cc)
    _finish_copies(repo, copies + conn_copies, apps)
    return copies


# ---------------------------------------------------------------------------
# Create component from selection / expand
# ---------------------------------------------------------------------------

def group(repo, composition: Element, components: list[Element], name: Optional[str] = None
          ) -> PartUsage:
    """System Composer 'Create Component from Selection'.

    Moves the selected direct sub-components into a new inline component and
    re-routes every connector that crossed the selection boundary through new
    boundary ports of that component.
    """
    comp = require_composition(composition)
    comps = [require_component(c) for c in components]
    if not comps:
        raise ArchitectureError("select at least one component")
    direct = components_of(comp)
    for c in comps:
        if not any(c is x for x in direct):
            raise ArchitectureError(f"{c.name} is not a direct component of {comp.name}")
    src_owner = comps[0].owner
    if any(c.owner is not src_owner for c in comps):
        raise ArchitectureError("selected components must share one owner")
    taken = member_names(comp)
    if name:
        name = check_name(name)
        if name in taken:
            raise _conflict(f"{comp.name} already has a member named {name!r}")
    else:
        name = unique_name("Component", taken)

    defaults = _default_boxes(comp)
    boxes = {id(c): effective_box(c, comp, defaults) for c in comps}
    minx = min(b["x"] for b in boxes.values())
    miny = min(b["y"] for b in boxes.values())
    maxx = max(b["x"] + b["w"] for b in boxes.values())
    maxy = max(b["y"] + b["h"] for b in boxes.values())

    g = PartUsage(name=name, multiplicity=MultiplicityRange(1, 1))
    src_owner.own(g)
    g.tool_data["layout"] = {"x": minx, "y": miny,
                             "w": max(DEFAULT_W, min(maxx - minx, 260)),
                             "h": max(DEFAULT_H, min(maxy - miny, 200))}
    selected = {id(c) for c in comps}
    crossing = []
    for conn in list(connectors_of(comp)):
        ends = connector_ends(conn, comp)
        inside = [ctx is not None and id(ctx) in selected for ctx, _ in ends]
        if len(ends) == 2 and all(inside):
            conn.end_contexts = tuple(ctx for ctx, _ in ends)
            reparent(conn, g, repo)
        elif len(ends) == 2 and any(inside):
            crossing.append((conn, ends, inside.index(True)))
    for c in comps:
        reparent(c, g, repo)
        b = boxes[id(c)]
        c.tool_data["layout"] = {**b, "x": b["x"] - minx + 120, "y": b["y"] - miny + 60}

    created: list[Element] = [g]
    boundary: dict[tuple, PortUsage] = {}
    inner_done: set[tuple] = set()
    seen_outer: set[tuple] = set()
    g_taken = member_names(g)
    for conn, ends, i in crossing:
        in_ep, out_ep = ends[i], ends[1 - i]
        key = (("src", id(in_ep[0]), id(in_ep[1])) if i == 0
               else ("dst", id(out_ep[0]), id(out_ep[1])))
        bp = boundary.get(key)
        p = in_ep[1]
        if bp is None:
            kind = p.port_kind if isinstance(p, PortUsage) else "data"
            if kind == "data":
                fdir = FeatureDirection.OUT if i == 0 else FeatureDirection.IN
            else:
                fdir = FeatureDirection.INOUT
            bp = PortUsage(name=unique_name(p.name or "Port", g_taken), port_kind=kind,
                           direction=fdir, multiplicity=MultiplicityRange(1, 1))
            g_taken.add(bp.name)
            for t in p.types:
                bp.add_type(t)
            bp.tool_data["port_layout"] = {"side": "right" if i == 0 else "left", "offset": 0.5}
            g.own(bp)
            boundary[key] = bp
            created.append(bp)
        inner_key = (id(bp), id(in_ep[0]), id(in_ep[1]))
        if inner_key not in inner_done:
            inner_done.add(inner_key)
            inner_ends = [in_ep, (None, bp)] if i == 0 else [(None, bp), in_ep]
            ic = ConnectionUsage(name=unique_name(conn.name or "Connector", g_taken),
                                 ends=[e[1] for e in inner_ends],
                                 end_contexts=tuple(e[0] for e in inner_ends))
            g_taken.add(ic.name)
            g.own(ic)
            created.append(ic)
        new_ends = list(ends)
        new_ends[i] = (g, bp)
        outer_key = (id(new_ends[0][0]), id(new_ends[0][1]), id(new_ends[1][0]), id(new_ends[1][1]))
        if outer_key in seen_outer:
            repo.remove(conn)          # same outer source now feeds the group once
            continue
        seen_outer.add(outer_key)
        conn.ends = [e[1] for e in new_ends]
        conn.end_contexts = tuple(e[0] for e in new_ends)
        conn.tool_data.pop("points", None)
    _spread_ports(g)
    for e in created:
        notify_created(e, repo)
    repo.registry.register_tree(g)
    return g


def expand(repo, component: Element) -> list[PartUsage]:
    """Inverse of :func:`group`: move an inline component's sub-components up one level,
    merge connectors through its boundary ports and delete the now-empty component."""
    g = require_component(component)
    if definition_of(g) is not None:
        raise ArchitectureError(f"{g.name} is a reference to {definition_of(g).name}; inline it first")
    parent = g.owner
    inner = [c for c in g.owned_elements if isinstance(c, PartUsage)]
    taken = member_names(parent, exclude=g)
    gbox = effective_box(g, parent)
    ports = [p for p in g.owned_elements if isinstance(p, PortUsage)]
    port_ids = {id(p) for p in ports}

    outer: dict[int, list] = {}
    for c in connectors_of(parent):
        ends = connector_ends(c, parent)
        for i, (ctx, p) in enumerate(ends):
            if ctx is g and id(p) in port_ids and len(ends) == 2:
                outer.setdefault(id(p), []).append((c, ends[1 - i], i))
    inner_by_port: dict[int, list] = {}
    inner_plain: list[ConnectionUsage] = []
    for c in [x for x in g.owned_elements if isinstance(x, ConnectionUsage)]:
        ends = connector_ends(c, g)
        hit = False
        for i, (ctx, p) in enumerate(ends):
            if ctx is None and id(p) in port_ids and len(ends) == 2:
                inner_by_port.setdefault(id(p), []).append((c, ends[1 - i], i))
                hit = True
        if not hit:
            c.end_contexts = tuple(ctx for ctx, _ in ends)
            inner_plain.append(c)

    for c in inner:
        if c.name in taken:
            c.name = unique_name(c.name, taken)
        taken.add(c.name)
        lay = effective_box(c, g)
        c.tool_data["layout"] = {**lay, "x": gbox["x"] + lay["x"] - 120, "y": gbox["y"] + lay["y"] - 60}
        reparent(c, parent, repo)
    for c in inner_plain:
        if c.name in taken:
            c.name = unique_name(c.name, taken)
        taken.add(c.name)
        reparent(c, parent, repo)

    merged = []
    for pid, outs in outer.items():
        for oc, other_out, out_i in outs:
            for ic, other_in, _in_i in inner_by_port.get(pid, []):
                if other_in[0] is None:
                    continue       # boundary-to-boundary pass-through inside the group: dropped
                # out_i == 1: the outer connector ends at the group port, so the outside is the source.
                ends = [other_out, other_in] if out_i == 1 else [other_in, other_out]
                nc = ConnectionUsage(name=unique_name(oc.name or "Connector", taken),
                                     ends=[e[1] for e in ends], end_contexts=tuple(e[0] for e in ends))
                taken.add(nc.name)
                parent.own(nc)
                merged.append(nc)
    repo.remove(g)
    for nc in merged:
        notify_created(nc, repo)
    repo.registry.register_tree(parent)
    return inner


# ---------------------------------------------------------------------------
# Reference components
# ---------------------------------------------------------------------------

def _capitalized(name: str) -> str:
    return name[:1].upper() + name[1:] if name else "Component"


def save_as_reference(repo, component: Element, name: Optional[str] = None,
                      package: Optional[Element] = None) -> PartDefinition:
    """Turn an inline component into a reusable PartDefinition and type the component by it."""
    c = require_component(component)
    if definition_of(c) is not None:
        raise ArchitectureError(f"{c.name} already references {definition_of(c).name}")
    pkg = package if package is not None else model_package(c)
    if not isinstance(pkg, Package):
        raise ArchitectureError(f"{pkg.qualified_name} is not a package")
    taken = _names_in([pkg])
    if name:
        name = check_name(name)
        if name in taken:
            raise _conflict(f"{pkg.name} already contains an element named {name!r}")
    else:
        name = unique_name(_capitalized(c.name or "Component"), taken)
    d = PartDefinition(name=name)
    pkg.own(d)
    for x in list(c.owned_elements):
        if isinstance(x, ConnectionUsage):
            x.end_contexts = tuple(ctx for ctx, _ in connector_ends(x, c))
        reparent(x, d, repo)
    c.add_type(d)
    notify_created(d, repo)
    return d


def inline_component(repo, component: Element) -> PartUsage:
    """Copy a reference component's definition internals into this usage only and drop the typing."""
    c = require_component(component)
    d = definition_of(c)
    if d is None:
        raise ArchitectureError(f"{c.name} is already an inline component")
    items = [x for x in d.owned_elements]
    for x in items:
        if isinstance(x, ConnectionUsage):
            x.end_contexts = tuple(ctx for ctx, _ in connector_ends(x, d))
    # Resolve every connector that reaches d's ports through this usage (outside), or that
    # this usage owns itself (its extras), while the typing still explains the contexts.
    affected = []
    for conn in [x for x in repo.root_package.walk() if isinstance(x, ConnectionUsage)]:
        ends = connector_ends(conn)
        if conn.owner is c or any(ctx is c for ctx, _ in ends):
            affected.append((conn, ends))
    copies, mapping, apps = clone_forest(items)
    taken = _names_in([c])
    for cp in copies:
        if cp.name and cp.name in taken:
            cp.name = unique_name(cp.name, taken)
        if cp.name:
            taken.add(cp.name)
        c.own(cp)
    set_definition(repo, c, None)

    def remap(v):
        return mapping.get(id(v), v) if v is not None else None
    for conn, ends in affected:
        if conn.owner is c:        # inside this usage: d's ports/components became its own copies
            new = [(remap(ctx), remap(p)) for ctx, p in ends]
        else:                      # outside: only ends reached through this usage change
            new = [(ctx, remap(p)) if ctx is c else (ctx, p) for ctx, p in ends]
        conn.ends = [p for _, p in new]
        conn.end_contexts = tuple(ctx for ctx, _ in new)
    _finish_copies(repo, copies, apps)
    return c


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

DEFAULT_W, DEFAULT_H = 160, 90
PORT_PITCH = 22
SIDES = ("left", "right", "top", "bottom")
_GRID_X0, _GRID_Y0, _GAP_X, _GAP_Y = 160, 60, 110, 70


def number(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ArchitectureError(f"{what} must be a finite number")
    return float(v) if isinstance(v, float) and not v.is_integer() else int(v)


def clean_box(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ArchitectureError("layout must be an object")
    out = {"x": number(item.get("x"), "x"), "y": number(item.get("y"), "y")}
    for k in ("w", "h"):
        if item.get(k) is not None:
            v = number(item[k], k)
            if v <= 0:
                raise ArchitectureError(f"{k} must be positive")
            out[k] = v
    return out


def clean_port_layout(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ArchitectureError("port layout must be an object")
    side = item.get("side")
    if side not in SIDES:
        raise ArchitectureError(f"side must be one of {list(SIDES)}")
    off = number(item.get("offset", 0.5), "offset")
    if not 0 <= off <= 1:
        raise ArchitectureError("offset must be between 0 and 1")
    return {"side": side, "offset": off}


def clean_points(points: Any) -> list:
    if not isinstance(points, list):
        raise ArchitectureError("points must be a list of [x, y] pairs")
    out = []
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise ArchitectureError("points must be a list of [x, y] pairs")
        out.append([number(pt[0], "point x"), number(pt[1], "point y")])
    return out


def default_side(port: PortUsage) -> str:
    k = port.port_kind
    if k == "client":
        return "right"
    if k == "server":
        return "left"
    if k == "data" and port.direction is FeatureDirection.OUT:
        return "right"
    return "left"


def port_layouts(owner: Element) -> dict[int, dict]:
    """``id(port) -> {side, offset}`` for every port of `owner` (stored or default)."""
    ports = ports_of(owner)
    sides: dict[int, str] = {}
    stored: dict[int, dict] = {}
    for p in ports:
        lay = p.tool_data.get("port_layout")
        if isinstance(lay, dict) and lay.get("side") in SIDES:
            stored[id(p)] = lay
            sides[id(p)] = lay["side"]
        else:
            sides[id(p)] = default_side(p)
    out: dict[int, dict] = {}
    for side in SIDES:
        on_side = [p for p in ports if sides[id(p)] == side]
        for i, p in enumerate(on_side):
            if id(p) in stored:
                off = stored[id(p)].get("offset", 0.5)
                out[id(p)] = {"side": side, "offset": off if isinstance(off, (int, float)) else 0.5}
            else:
                out[id(p)] = {"side": side, "offset": round((i + 1) / (len(on_side) + 1), 4)}
    return out


def default_size(c: Element) -> tuple[int, int]:
    counts = {s: 0 for s in SIDES}
    for lay in port_layouts(c).values():
        counts[lay["side"]] += 1
    h = max(DEFAULT_H, 30 + PORT_PITCH * max(counts["left"], counts["right"]))
    w = max(DEFAULT_W, 40 + PORT_PITCH * max(counts["top"], counts["bottom"]))
    return w, h


def _default_boxes(composition: Element) -> dict[int, dict]:
    comps = components_of(composition)
    n = len(comps)
    if not n:
        return {}
    cols = max(1, math.ceil(math.sqrt(n)))
    sizes = [default_size(c) for c in comps]
    col_w = max(w for w, _ in sizes)
    out: dict[int, dict] = {}
    y = _GRID_Y0
    for row_start in range(0, n, cols):
        row = list(range(row_start, min(n, row_start + cols)))
        row_h = max(sizes[i][1] for i in row)
        for col, i in enumerate(row):
            w, h = sizes[i]
            out[id(comps[i])] = {"x": _GRID_X0 + col * (col_w + _GAP_X), "y": y, "w": w, "h": h}
        y += row_h + _GAP_Y
    return out


def effective_box(c: Element, composition: Optional[Element] = None,
                  _defaults: Optional[dict] = None) -> dict:
    lay = c.tool_data.get("layout")
    w, h = default_size(c)
    if isinstance(lay, dict) and isinstance(lay.get("x"), (int, float)) and isinstance(lay.get("y"), (int, float)):
        return {"x": lay["x"], "y": lay["y"], "w": lay.get("w") or w, "h": lay.get("h") or h}
    defaults = _defaults if _defaults is not None else (
        _default_boxes(composition) if composition is not None else {})
    return dict(defaults.get(id(c)) or {"x": _GRID_X0, "y": _GRID_Y0, "w": w, "h": h})


def apply_layout(repo, items: list) -> int:
    """Batch-save layout: ``{id, x, y, w?, h?}`` for components, ``{id, side, offset}`` for
    ports, ``{id, points}`` for connectors. Validates everything before writing anything."""
    if not isinstance(items, list):
        raise ArchitectureError("items must be a list")
    planned = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            raise ArchitectureError("every layout item needs an id")
        e = repo.by_id(item["id"])
        if e is None:
            raise _not_found(f"element {item['id']!r}")
        if isinstance(e, PortUsage):
            planned.append((e, "port_layout", clean_port_layout(item)))
        elif isinstance(e, ConnectionUsage):
            pts = item.get("points")
            planned.append((e, "points", None if pts is None else clean_points(pts)))
        elif isinstance(e, (PartUsage, PartDefinition)):
            planned.append((e, "layout", clean_box(item)))
        else:
            raise ArchitectureError(f"{e.qualified_name} ({e.kind}) has no canvas layout")
    for e, key, value in planned:
        if value is None:
            e.tool_data.pop(key, None)
        else:
            e.tool_data[key] = value
    return len(planned)


def _spread_ports(owner: Element) -> None:
    """Inputs on the left, outputs on the right, evenly spaced."""
    ports = ports_of(owner)
    by_side: dict[str, list] = {s: [] for s in SIDES}
    for p in ports:
        by_side[default_side(p)].append(p)
    for side, ps in by_side.items():
        for i, p in enumerate(ps):
            p.tool_data["port_layout"] = {"side": side, "offset": round((i + 1) / (len(ps) + 1), 4)}


def auto_layout(repo, composition: Element) -> dict:
    """Left-to-right layered layout ordered by connector direction (System Composer 'Arrange')."""
    comp = require_composition(composition)
    comps = components_of(comp)
    idx = {id(c): i for i, c in enumerate(comps)}
    succ: dict[int, list[int]] = {i: [] for i in range(len(comps))}
    pred: dict[int, list[int]] = {i: [] for i in range(len(comps))}
    for conn in connectors_of(comp):
        ends = connector_ends(conn, comp)
        if len(ends) != 2:
            continue
        a, b = ends[0][0], ends[1][0]
        if a is None or b is None or id(a) not in idx or id(b) not in idx or a is b:
            continue
        ia, ib = idx[id(a)], idx[id(b)]
        if ib not in succ[ia]:
            succ[ia].append(ib)
            pred[ib].append(ia)
    # Depth-first topological order; back edges (cycles) are ignored.
    state = [0] * len(comps)
    order: list[int] = []
    back: set[tuple[int, int]] = set()

    def visit(i: int) -> None:
        stack = [(i, iter(succ[i]))]
        state[i] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                order.append(node)
                stack.pop()
            elif state[nxt] == 1:
                back.add((node, nxt))
            elif state[nxt] == 0:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))
    roots = [i for i in range(len(comps)) if not pred[i]] + list(range(len(comps)))
    for i in roots:
        if state[i] == 0:
            visit(i)
    order.reverse()
    layer = [0] * len(comps)
    for i in order:
        for j in succ[i]:
            if (i, j) not in back:
                layer[j] = max(layer[j], layer[i] + 1)
    layers: dict[int, list[int]] = {}
    for i in range(len(comps)):
        layers.setdefault(layer[i], []).append(i)
    for c in comps:
        _spread_ports(c)
    _spread_ports(comp)
    sizes = [default_size(c) for c in comps]
    col_w = max([w for w, _ in sizes] or [DEFAULT_W])
    pos_rank: dict[int, float] = {}
    positions: dict[str, dict] = {}
    heights = {k: sum(sizes[i][1] for i in v) + _GAP_Y * (len(v) - 1) for k, v in layers.items()}
    tallest = max(heights.values() or [0])
    for k in sorted(layers):
        members = layers[k]
        members.sort(key=lambda i: (sum(pos_rank.get(p, 0) for p in pred[i]) / len(pred[i])
                                    if pred[i] else pos_rank.get(i, i), i))
        y = _GRID_Y0 + (tallest - heights[k]) / 2
        for rank, i in enumerate(members):
            w, h = sizes[i]
            box = {"x": _GRID_X0 + k * (col_w + _GAP_X), "y": round(y), "w": w, "h": h}
            comps[i].tool_data["layout"] = box
            positions[comps[i].element_id] = box
            pos_rank[i] = rank
            y += h + _GAP_Y
    for conn in connectors_of(comp):
        conn.tool_data.pop("points", None)
    return positions


# ---------------------------------------------------------------------------
# View model (for the canvas)
# ---------------------------------------------------------------------------

_DEFAULT_CONNECTOR_NAME = re.compile(r"^(Connector\d*|connect_.*)$")


def _ref(e: Optional[Element]) -> Optional[dict]:
    return None if e is None else {"id": e.element_id, "name": e.name,
                                   "qualified_name": e.qualified_name, "kind": e.kind}


def _basic_decor(e: Element) -> dict:
    return {"badges": component_badges(e) + port_badges(e), "style": {},
            "stereotypes": [{"name": a.stereotype.name, "values": a.values} for a in stereotypes_on(e)]}


def _decor(decorate: Optional[Callable[[Element], dict]], e: Element) -> dict:
    d = decorate(e) if decorate else _basic_decor(e)
    return {"badges": list(d.get("badges") or []), "style": dict(d.get("style") or {}),
            "stereotypes": list(d.get("stereotypes") or [])}


def port_view(p: PortUsage, owner: Element, layout: dict,
              decorate: Optional[Callable] = None) -> dict:
    iface = p.types[0] if p.types else None
    return {
        "id": p.element_id, "name": p.name, "kind": p.port_kind,
        "direction": p.direction.value,
        "interface": _ref(iface),
        "side": layout["side"], "offset": layout["offset"],
        "owner_id": p.owner.element_id if p.owner else None,
        "on_definition": p.owner is not owner,
        **_decor(decorate, p),
    }


def component_view(c: PartUsage, composition: Element, decorate: Optional[Callable] = None,
                   _defaults: Optional[dict] = None) -> dict:
    d = definition_of(c)
    pl = port_layouts(c)
    return {
        "id": c.element_id, "name": c.name, "kind": c.kind,
        "qualified_name": c.qualified_name,
        "definition": _ref(d), "is_reference": d is not None,
        "owner_id": c.owner.element_id if c.owner else None,
        # Viewing a reference component: this sub-component belongs to the shared definition.
        "from_definition": c.owner is not composition,
        "layout": effective_box(c, composition, _defaults),
        "has_children": bool(components_of(c)),
        "has_state_machine": owns_state_machine(c),
        "ports": [port_view(p, c, pl[id(p)], decorate) for p in ports_of(c)],
        **_decor(decorate, c),
    }


def connector_interfaces(conn: ConnectionUsage, composition: Optional[Element] = None) -> list[str]:
    """Interface names on a connector: its own type, then its end ports' types."""
    ends = connector_ends(conn, composition)
    out: list[str] = []
    for t in list(conn.types) + [t for _, p in ends if isinstance(p, Feature) for t in p.types]:
        if t.name and t.name not in out:
            out.append(t.name)
    return out


def connector_label(conn: ConnectionUsage, composition: Optional[Element] = None) -> str:
    """Text drawn on a connector line: the interface name(s), as System Composer does,
    prefixed SysML-style by a name the user gave it (``drive : Mech``); auto-generated
    names (Connector, Connector1, connect_a_b) are not drawn."""
    ifaces = ", ".join(connector_interfaces(conn, composition))
    named = bool(conn.name) and not _DEFAULT_CONNECTOR_NAME.match(conn.name)
    if named and ifaces:
        return f"{conn.name} : {ifaces}"
    return conn.name if named else ifaces


def connector_view(conn: ConnectionUsage, composition: Element,
                   decorate: Optional[Callable] = None) -> dict:
    ends = connector_ends(conn, composition)

    def ep(i: int) -> Optional[dict]:
        if i >= len(ends):
            return None
        ctx, p = ends[i]
        if isinstance(p, PartUsage) and not isinstance(p, PortUsage):
            return {"component_id": p.element_id, "port_id": None}
        return {"component_id": ctx.element_id if ctx is not None else None, "port_id": p.element_id}

    ifaces = connector_interfaces(conn, composition)
    pts = conn.tool_data.get("points")
    label = connector_label(conn, composition)
    return {
        "id": conn.element_id, "name": conn.name, "label": label,
        "kind": connector_kind(composition, conn),
        "source": ep(0), "target": ep(1),
        "interfaces": ifaces,
        "points": pts if isinstance(pts, list) else None,
        "owner_id": conn.owner.element_id if conn.owner else None,
        "issues": [msg for _rule, msg in connector_problems(conn)],
        **_decor(decorate, conn),
    }


def breadcrumbs(composition: Element, path: Optional[list[Element]] = None) -> list[dict]:
    """Path from the model root to `composition`. A drill-down `path` (list of elements from
    the root) is honoured when every step is a sub-component of the previous one."""
    if path:
        ok = path[-1] is composition and all(
            any(b is c for c in components_of(a)) for a, b in zip(path, path[1:]))
        if ok:
            return [{"id": e.element_id, "name": e.name, "kind": e.kind} for e in path]
    chain = [composition]
    node = composition
    while isinstance(node.owner, (PartUsage, PartDefinition)):
        node = node.owner
        chain.insert(0, node)
    return [{"id": e.element_id, "name": e.name, "kind": e.kind} for e in chain]


def view(repo, composition: Element, *, path: Optional[list[Element]] = None,
         decorate: Optional[Callable[[Element], dict]] = None) -> dict:
    """Complete canvas view model for one composition (architecture or component)."""
    comp = require_composition(composition)
    d = definition_of(comp)
    comps = components_of(comp)
    defaults = _default_boxes(comp)
    pl = port_layouts(comp)
    return {
        "model_type": model_type(repo),
        "allowed_port_kinds": list(allowed_port_kinds(repo)),
        "composition": {
            "id": comp.element_id, "name": comp.name, "kind": comp.kind,
            "qualified_name": comp.qualified_name,
            "definition": _ref(d), "is_reference": d is not None,
            "edit_owner_id": edit_owner(comp).element_id,
            "shared_by": len(_usages_of(repo, d)) if d is not None else 0,
            "breadcrumbs": breadcrumbs(comp, path),
            "has_state_machine": owns_state_machine(comp),
            **_decor(decorate, comp),
        },
        "boundary_ports": [port_view(p, comp, pl[id(p)], decorate) for p in ports_of(comp)],
        "components": [component_view(c, comp, decorate, defaults) for c in comps],
        "connectors": [connector_view(c, comp, decorate) for c in connectors_of(comp)],
    }


def model_tree(root: Element, *, decorate: Optional[Callable] = None) -> dict:
    """Model browser: nested components (through reference definitions) with their ports."""
    def node(e: Element, path: list[str], seen: frozenset) -> dict:
        d = definition_of(e)
        here = [*path, e.element_id]
        out = {
            "id": e.element_id, "name": e.name, "kind": e.kind,
            "definition": _ref(d), "path": here,
            "ports": [{"id": p.element_id, "name": p.name, "direction": p.direction.value,
                       "kind": p.port_kind} for p in ports_of(e)],
            "children": [],
            **_decor(decorate, e),
        }
        key = id(d) if d is not None else (id(e) if isinstance(e, PartDefinition) else None)
        if key is not None and key in seen:
            out["recursive"] = True
            return out
        nseen = seen | {key} if key is not None else seen
        out["children"] = [node(c, here, nseen) for c in components_of(e)]
        return out
    return node(require_composition(root), [], frozenset())


def architecture_roots(repo) -> list[PartDefinition]:
    """Part definitions not used as the type of any component (top-level architectures)."""
    defs = [e for e in repo.root_package.walk() if isinstance(e, PartDefinition)
            and not isinstance(e, StateMachineDefinition)]
    used = {id(definition_of(u)) for u in repo.root_package.walk()
            if isinstance(u, PartUsage) and definition_of(u) is not None}
    return [d for d in defs if id(d) not in used]


def part_definitions(repo) -> list[PartDefinition]:
    return [e for e in repo.root_package.walk() if isinstance(e, PartDefinition)]


# ---------------------------------------------------------------------------
# Persistence, validation, cleanup and graph registrations
# ---------------------------------------------------------------------------

def _encode_port(e: Element):
    if isinstance(e, PortUsage) and e.port_kind != "data":
        return {"kind": e.port_kind}
    return None


def _decode_port(e: Element, data, by_id) -> None:
    if isinstance(e, PortUsage) and isinstance(data, dict):
        try:
            e.port_kind = data.get("kind", "data")
        except ValueError:
            e.port_kind = "data"


def _encode_connector(e: Element):
    if not isinstance(e, ConnectionUsage):
        return None
    ctxs = tuple(getattr(e, "end_contexts", ()) or ())
    if not ctxs or len(ctxs) != len(e.ends):
        return None
    return {"contexts": [c.element_id if c is not None else None for c in ctxs]}


def _decode_connector(e: Element, data, by_id) -> None:
    if not isinstance(e, ConnectionUsage) or not isinstance(data, dict):
        return
    ids = data.get("contexts") or []
    ctxs = []
    for i in ids:
        if i is None:
            ctxs.append(None)
        elif i in by_id:
            ctxs.append(by_id[i])
        else:
            e.end_contexts = ()      # a context is gone: fall back to inference
            return
    e.end_contexts = tuple(ctxs)


def _encode_repo(repo):
    t = model_type(repo)
    return {"model_type": t} if t != "system" else None


def _decode_repo(repo, data, by_id) -> None:
    if isinstance(data, dict) and data.get("model_type") in MODEL_TYPES:
        repo.model_type = data["model_type"]


def check_repo(repo) -> Iterable[ValidationIssue]:
    """Validator rules for architectures (registered as a repository rule)."""
    allowed = allowed_port_kinds(repo)
    t = model_type(repo)
    drivers: dict[tuple, list] = {}
    for e in repo.root_package.walk():
        if isinstance(e, PortUsage) and e.port_kind not in allowed:
            yield ValidationIssue(Severity.ERROR, "arch.port.kind",
                                  f"{e.port_kind} ports are not allowed in a {t} architecture", e)
        if isinstance(e, PortUsage) and isinstance(e.owner, PartUsage):
            d = definition_of(e.owner)
            if d is not None and any(p.name == e.name for p in ports_of(d) if p is not e):
                yield ValidationIssue(Severity.ERROR, "arch.port.unique",
                                      f"port name {e.name!r} is also used by {d.name}", e)
        if not isinstance(e, ConnectionUsage) or not isinstance(e.owner, (PartDefinition, PartUsage)):
            continue
        for rule, msg in connector_problems(e):
            yield ValidationIssue(Severity.ERROR, rule, msg, e)
        ends = connector_ends(e)
        if len(ends) == 2 and all(isinstance(p, PortUsage) for _, p in ends):
            (sc, sp), (dc, dp) = ends
            st, dt = sp.types, dp.types
            if st and dt and not any(a.conforms_to(b) or b.conforms_to(a) for a in st for b in dt):
                yield ValidationIssue(Severity.WARNING, "arch.connector.interface",
                                      f"interface mismatch: {sp.name} is {st[0].name}, "
                                      f"{dp.name} is {dt[0].name}", e)
            if (connector_kind(e.owner, e) == "data" and data_role(dp, dc is None) == "in"):
                drivers.setdefault((id(e.owner), id(dc), id(dp)), []).append(e)
    for conns in drivers.values():
        for extra in conns[1:]:
            yield ValidationIssue(Severity.ERROR, "arch.port.multiple-drivers",
                                  f"input {extra.ends[1].name} is driven by {len(conns)} connectors "
                                  "(an input accepts one source)", extra)


def _on_removed(repo, removed_ids: set[int]) -> None:
    """Delete connectors that reached a deleted component through `end_contexts`."""
    doomed = [c for c in repo.root_package.walk()
              if isinstance(c, ConnectionUsage) and id(c) not in removed_ids
              and any(x is not None and id(x) in removed_ids
                      for x in (getattr(c, "end_contexts", ()) or ()))]
    for c in doomed:
        if c.owner is not None and repo.by_id(c.element_id) is not None:
            repo.remove(c)


def _on_created(e: Element, repo) -> None:
    """Generic creation paths (POST /api/element, MCP create, parser) keep component and
    port names unique among their siblings, as System Composer does."""
    if not e.name:
        return
    if not (is_component(e) or (isinstance(e, PortUsage)
                                and isinstance(e.owner, (PartDefinition, PartUsage)))):
        return
    taken = sibling_names(e)
    if e.name in taken:
        e.name = unique_name(e.name, taken)


def _edges(e: Element):
    if isinstance(e, ConnectionUsage):
        for i, ctx in enumerate(getattr(e, "end_contexts", ()) or ()):
            if ctx is not None:
                yield ("connectsVia", e, ctx, {"end": i})


_INSTALLED = False


def install() -> None:
    """Register codecs, rules and hooks (idempotent; runs on import)."""
    global _INSTALLED
    from engine import graph_export as _g, hooks as _h, repository as _r, validator as _v
    register_codec("arch.port", _encode_port, _decode_port)
    register_codec("arch.connector", _encode_connector, _decode_connector)
    register_repo_codec("architecture", _encode_repo, _decode_repo)
    if check_repo not in _v._REPO_RULES:
        register_repo_rule(check_repo)
    if _on_removed not in _r._REMOVAL_HOOKS:
        register_removal_hook(_on_removed)
    if _on_created not in _h._CREATED_HOOKS:
        _h.register_created_hook(_on_created)
    if _edges not in _g._EDGE_SOURCES:
        register_edge_source(_edges)
    _INSTALLED = True


install()
