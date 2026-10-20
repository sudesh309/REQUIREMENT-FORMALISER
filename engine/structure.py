"""Shared reading of architecture structure (System Composer terms on SysML v2).

Every feature (canvas, analysis, views, allocation, tables) walks the
architecture through these helpers so they agree on what a component is.

Conventions
-----------
- An *architecture* is a ``PartDefinition`` (the model's root composition, or
  a reusable component type).
- A *component* is a ``PartUsage`` owned by an architecture or by another
  component.
  - **Reference component**: typed by a ``PartDefinition``; its ports and
    internals come from that definition (shared by every usage).
  - **Inline component**: untyped; owns its own ports and sub-components.
  Its own ``PortUsage`` children are added to the definition's ports, so a
  typed usage may also carry extra ports of its own.
- A *port* is a ``PortUsage`` owned by a component or architecture; its
  direction is ``Feature.direction`` and its interface is its type.
- A *connector* is a ``ConnectionUsage`` owned by the composition whose
  internals it wires; ``ends[0]`` is the source port and ``ends[1]`` the
  destination port. ``end_contexts[i]`` is the sub-component usage through
  which ``ends[i]`` is reached (None for a boundary port of the composition),
  so two usages of one definition port are told apart; read both with
  ``connector_ends``.
- A port's *kind* is ``PortUsage.port_kind``: 'data' (directional),
  'physical' (non-directional), 'client' or 'server' (software services).
"""
from __future__ import annotations

from typing import Iterator, Optional

from kerml.elements import Element
from sysmlv2.definitions import (
    ConnectionUsage, PartDefinition, PartUsage, PortUsage,
)


def definition_of(component: Element) -> Optional[PartDefinition]:
    """The PartDefinition a component usage is typed by (None for inline components)."""
    if isinstance(component, PartUsage):
        return next((t for t in component.types if isinstance(t, PartDefinition)), None)
    return None


def _internal_owners(composition: Element) -> list[Element]:
    """Elements whose owned children make up `composition`'s internals."""
    owners = [composition]
    d = definition_of(composition)
    if d is not None and d is not composition:
        owners.append(d)
    return owners


def components_of(composition: Element) -> list[PartUsage]:
    """Direct sub-components of an architecture or component."""
    out: list[PartUsage] = []
    for owner in _internal_owners(composition):
        out += [c for c in owner.owned_elements if isinstance(c, PartUsage)]
    return out


def ports_of(component: Element) -> list[PortUsage]:
    """Ports of an architecture or component (own ports plus its definition's)."""
    out: list[PortUsage] = []
    for owner in _internal_owners(component):
        out += [p for p in owner.owned_elements if isinstance(p, PortUsage)]
    return out


def connectors_of(composition: Element) -> list[ConnectionUsage]:
    """Connectors wiring the internals of an architecture or component."""
    out: list[ConnectionUsage] = []
    for owner in _internal_owners(composition):
        out += [c for c in owner.owned_elements if isinstance(c, ConnectionUsage)]
    return out


def component_tree(root: Element, *, _depth: int = 0, _parent: Optional[Element] = None,
                   _seen: Optional[set[int]] = None) -> Iterator[tuple[Element, int, Optional[Element]]]:
    """Pre-order walk yielding (component, depth, parent), starting with `root` itself.

    Recursion through a definition that (directly or indirectly) contains a usage
    of itself is cut off, so a malformed model cannot loop forever.
    """
    seen = _seen if _seen is not None else set()
    yield root, _depth, _parent
    d = definition_of(root)
    key = id(d) if d is not None else None
    if key is not None:
        if key in seen:
            return
        seen = seen | {key}
    for child in components_of(root):
        yield from component_tree(child, _depth=_depth + 1, _parent=root, _seen=seen)


def owning_component(port: PortUsage) -> Optional[Element]:
    """The component or architecture that owns a port."""
    return port.owner if isinstance(port.owner, (PartUsage, PartDefinition)) else None


def is_component(e: Element) -> bool:
    """True for a PartUsage that sits inside an architecture or another component."""
    return isinstance(e, PartUsage) and isinstance(e.owner, (PartUsage, PartDefinition))


def internal_owners(composition: Element) -> list[Element]:
    """The composition itself plus, for a reference component, its definition."""
    return _internal_owners(composition)


def context_of(composition: Element, end: Element) -> Optional[Element]:
    """Best guess of the sub-component through which `end` is reached inside `composition`.

    None means `end` belongs to the composition itself (a boundary port) or is
    not reachable from it. Used for connectors saved without ``end_contexts``.
    """
    owners = _internal_owners(composition)
    if any(end.owner is o for o in owners):
        return None
    comps = components_of(composition)
    for c in comps:
        if end.owner is c:
            return c
    for c in comps:
        d = definition_of(c)
        if d is not None and end.owner is d:
            return c
    return None


def connector_ends(conn: ConnectionUsage,
                   composition: Optional[Element] = None) -> list[tuple[Optional[Element], Element]]:
    """``[(context, end), ...]`` for a connector, in ``ends`` order.

    ``context`` is the sub-component usage that owns (or is typed by the owner of)
    the port, or None for a boundary port of the composition. Stored
    ``end_contexts`` win; otherwise contexts are inferred from ownership.
    """
    comp = composition if composition is not None else conn.owner
    ends = [e for e in conn.ends if e is not None]
    stored = tuple(getattr(conn, "end_contexts", ()) or ())
    if len(stored) == len(ends) and ends:
        return list(zip(stored, ends))
    if comp is None:
        return [(None, e) for e in ends]
    return [(context_of(comp, e), e) for e in ends]
