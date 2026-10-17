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
  destination port.
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
