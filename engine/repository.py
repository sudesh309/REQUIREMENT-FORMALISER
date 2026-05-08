"""Model repository — the in-memory store backing a SysML v2 project.

Plays the role of Cameo's project / containment-tree:
- holds a root Package (the project),
- imports the standard libraries (KerML + SysML v2),
- indexes every Element by UUID and by qualified name,
- exposes traversal, search, and remove operations.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional

from kerml.elements import Element
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Namespace, Package
from sysmlv2.library import SYSML_LIBRARY


class ElementRegistry:
    """UUID -> Element index, with qualified-name lookups."""

    def __init__(self):
        self._by_id: dict[str, Element] = {}

    def register(self, element: Element) -> None:
        self._by_id[element.element_id] = element

    def register_tree(self, root: Element) -> None:
        for e in root.walk():
            self.register(e)
            for r in getattr(e, "owned_relationships", []):
                self._by_id[r.element_id] = r

    def unregister(self, element: Element) -> None:
        self._by_id.pop(element.element_id, None)

    def get(self, element_id: str) -> Optional[Element]:
        return self._by_id.get(element_id)

    def __iter__(self) -> Iterator[Element]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


class Repository:
    """A SysML v2 modeling project."""

    def __init__(self, name: str = "Project", *, import_libraries: bool = True):
        self.name = name
        self.root_package: Package = Package(name=name)
        self.registry = ElementRegistry()
        self.registry.register_tree(self.root_package)
        if import_libraries:
            self.root_package.add_import(KERML_LIBRARY, recursive=True)
            self.root_package.add_import(SYSML_LIBRARY, recursive=True)

    # --- mutation -----------------------------------------------------
    def add(self, element: Element, *, parent: Optional[Namespace] = None) -> Element:
        target = parent or self.root_package
        target.own(element)
        self.registry.register_tree(element)
        return element

    def remove(self, element: Element) -> None:
        for e in element.walk():
            self.registry.unregister(e)
        if element.owner is not None:
            element.owner.owned_elements.remove(element)
            if isinstance(element.owner, Namespace):
                element.owner.memberships = [
                    m for m in element.owner.memberships if m.member is not element
                ]
        element.owner = None

    # --- queries ------------------------------------------------------
    def by_id(self, element_id: str) -> Optional[Element]:
        return self.registry.get(element_id)

    def resolve(self, qualified_name: str) -> Optional[Element]:
        return self.root_package.resolve(qualified_name)

    def all_elements(self) -> Iterable[Element]:
        return iter(self.registry)

    def by_kind(self, kind: str) -> list[Element]:
        return [e for e in self.registry if e.kind == kind]

    def find(self, predicate) -> list[Element]:
        return [e for e in self.registry if predicate(e)]

    # --- IO -----------------------------------------------------------
    def save(self, path: str) -> None:
        from .serializer import to_json
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_json(self))

    @classmethod
    def load(cls, path: str) -> "Repository":
        from .serializer import from_json
        with open(path, encoding="utf-8") as f:
            return from_json(f.read())

    # --- validation ---------------------------------------------------
    def validate(self) -> list:
        from .validator import Validator
        return Validator().validate(self)

    def __repr__(self) -> str:
        return f"<Repository {self.name!r}: {len(self.registry)} elements>"
