"""Model repository — the in-memory store backing a SysML v2 project.

Plays the role of Cameo's project / containment-tree:
- holds a root Package (the project),
- imports the standard libraries (KerML + SysML v2),
- indexes every Element by UUID and by qualified name,
- exposes traversal, search, and remove operations.
"""
from __future__ import annotations

from typing import Callable, Iterable, Iterator, Optional

from kerml.elements import Element, Relationship
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Namespace, Package
from sysmlv2.library import SYSML_LIBRARY


# Feature modules clean their own references to deleted elements with
# register_removal_hook(fn(repo, removed_ids)); removed_ids holds id() values.
_REMOVAL_HOOKS: list[Callable[["Repository", set[int]], None]] = []


def register_removal_hook(fn: Callable[["Repository", set[int]], None]) -> None:
    _REMOVAL_HOOKS.append(fn)


def _with_dependents(root: Element, element: Element) -> list[Element]:
    """`element` plus connectors/transitions elsewhere that would dangle without it."""
    doomed = [element]
    removed = {id(x) for x in element.walk()}
    changed = True
    while changed:
        changed = False
        for e in root.walk():
            if id(e) in removed:
                continue
            anchors = list(getattr(e, "ends", None) or [])
            anchors += [getattr(e, "transition_source", None), getattr(e, "transition_target", None)]
            if any(a is not None and id(a) in removed for a in anchors):
                doomed.append(e)
                removed |= {id(x) for x in e.walk()}
                changed = True
    return doomed


def _detach_relationship(owner: Element, rel: Relationship) -> None:
    """Remove `rel` from `owner` and from every list on it that tracks relationships."""
    owner.owned_relationships = [r for r in owner.owned_relationships if r is not rel]
    for attr, value in list(vars(owner).items()):
        if isinstance(value, list) and any(v is rel for v in value):
            setattr(owner, attr, [v for v in value if v is not rel])


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
        """Delete `element`, its subtree, and everything that only made sense with it.

        Cascades to connectors attached to a removed feature and transitions to or
        from a removed state; drops relationships (links, typings, specializations,
        memberships) and stereotype applications that point into the removed set;
        and clears every other attribute or list entry referring to it. Feature
        modules clean their own references via ``register_removal_hook``.
        """
        doomed = _with_dependents(self.root_package, element)
        removed = {id(x) for d in doomed for x in d.walk()}
        is_removed = lambda v: isinstance(v, Element) and id(v) in removed  # noqa: E731

        for e in self.root_package.walk():
            if id(e) in removed:
                continue
            for rel in [r for r in e.owned_relationships if is_removed(r.source) or is_removed(r.target)]:
                _detach_relationship(e, rel)
                self.registry.unregister(rel)
            e.annotations = [a for a in e.annotations if not is_removed(getattr(a, "stereotype", None))]
            for attr, value in list(vars(e).items()):
                if attr == "owner":
                    continue
                if isinstance(value, list) and any(is_removed(v) for v in value):
                    setattr(e, attr, [v for v in value if not is_removed(v)])
                elif is_removed(value):
                    setattr(e, attr, None)

        for hook in _REMOVAL_HOOKS:
            hook(self, removed)

        for d in doomed:
            for x in d.walk():
                self.registry.unregister(x)
                for rel in x.owned_relationships:
                    self.registry.unregister(rel)
            d.owner = None

    # --- queries ------------------------------------------------------
    def by_id(self, element_id: str) -> Optional[Element]:
        return self.registry.get(element_id)

    def resolve(self, qualified_name: str) -> Optional[Element]:
        """Find an element by qualified name, in any form ``Element.qualified_name`` gives.

        Accepts a root-relative name (``Avionics::ADIRU``), the full name with the project
        root in front (``Project::Avionics::ADIRU``, as element JSON reports it; the root
        alone names the root package), a library name (``KerML::ScalarValues::Real``) and
        the ``<1a2b3c4d>`` placeholder of an unnamed element (its id prefix). When a name
        reads both ways (a top-level package named like the project), root-relative wins.
        """
        if not isinstance(qualified_name, str):
            return None
        qn = qualified_name.strip()
        if not qn:
            return None
        root = self.root_package
        hit = root.resolve(qn)
        if hit is not None:
            return hit
        head, sep, rest = qn.partition("::")
        if root.name and head == root.name:
            if not sep:
                return root
            hit = root.resolve(rest)
            if hit is not None:
                return hit
        if sep:
            for imp in root.imports:
                lib = imp.target
                if isinstance(lib, Namespace) and lib.name == head:
                    hit = lib.resolve(rest)
                    if hit is not None:
                        return hit
        if len(qn) == 10 and qn[0] == "<" and qn[-1] == ">":
            matches = [e for e in self.registry if e.element_id.startswith(qn[1:-1])]
            if len(matches) == 1 and matches[0].name is None:
                return matches[0]
        return None

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
