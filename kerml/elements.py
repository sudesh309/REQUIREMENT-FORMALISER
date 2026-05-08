"""Root abstractions of the KerML metamodel.

Every modeling construct in KerML (and therefore SysML v2) is ultimately
an Element. Element provides identity, naming, ownership, and the
ability to host annotations (comments, documentation, metadata).
"""
from __future__ import annotations

import uuid
from typing import Iterable, Iterator, Optional


class Element:
    """Root of the KerML metamodel.

    Identity is a UUID; humans address elements through `name` and the
    qualified name computed from owning namespaces.
    """

    # Subclasses override to be picked up by the (de)serializer.
    kind: str = "Element"

    def __init__(self, name: Optional[str] = None, *, short_name: Optional[str] = None,
                 element_id: Optional[str] = None):
        self.element_id: str = element_id or str(uuid.uuid4())
        self.name: Optional[str] = name
        self.short_name: Optional[str] = short_name
        self.owner: Optional["Element"] = None
        self.owned_relationships: list["Relationship"] = []
        self.owned_elements: list["Element"] = []
        self.annotations: list["Annotation"] = []
        self.is_abstract: bool = False
        # Free-form metadata used by tooling (line/col, source file, ...).
        self.tool_data: dict = {}

    # --- ownership -----------------------------------------------------
    def own(self, child: "Element") -> "Element":
        """Take ownership of `child` (idempotent)."""
        if child.owner is self:
            return child
        if child.owner is not None:
            child.owner.owned_elements.remove(child)
        child.owner = self
        self.owned_elements.append(child)
        return child

    def add_relationship(self, rel: "Relationship") -> "Relationship":
        rel.owner = self
        self.owned_relationships.append(rel)
        return rel

    def add_annotation(self, annotation: "Annotation") -> "Annotation":
        annotation.annotated_element = self
        self.annotations.append(annotation)
        return annotation

    # --- naming --------------------------------------------------------
    @property
    def qualified_name(self) -> str:
        parts: list[str] = []
        node: Optional[Element] = self
        while node is not None and node.name is not None:
            parts.append(node.name)
            node = node.owner
        return "::".join(reversed(parts)) if parts else f"<{self.element_id[:8]}>"

    def root(self) -> "Element":
        node: Element = self
        while node.owner is not None:
            node = node.owner
        return node

    # --- traversal -----------------------------------------------------
    def walk(self) -> Iterator["Element"]:
        """Depth-first traversal of self and all owned elements."""
        yield self
        for child in self.owned_elements:
            yield from child.walk()

    def find(self, predicate) -> Iterator["Element"]:
        return (e for e in self.walk() if predicate(e))

    # --- pretty printing ----------------------------------------------
    def __repr__(self) -> str:
        return f"<{self.kind} {self.qualified_name!r}>"


class Relationship(Element):
    """A relationship connects a `source` to a `target`.

    KerML treats relationships as Elements so they can themselves be
    annotated, owned, and named.
    """

    kind = "Relationship"

    def __init__(self, source: Optional[Element] = None, target: Optional[Element] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.source: Optional[Element] = source
        self.target: Optional[Element] = target

    @property
    def related(self) -> tuple[Optional[Element], Optional[Element]]:
        return (self.source, self.target)


class Annotation(Element):
    """Base class for things that decorate an element (Comment, Documentation, MetadataUsage)."""

    kind = "Annotation"

    def __init__(self, body: str = "", **kwargs):
        super().__init__(**kwargs)
        self.body: str = body
        self.annotated_element: Optional[Element] = None


class Comment(Annotation):
    kind = "Comment"


class Documentation(Annotation):
    kind = "Documentation"


def iter_owned(elements: Iterable[Element]) -> Iterator[Element]:
    for e in elements:
        yield from e.walk()
