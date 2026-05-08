"""Namespace, Package, Membership, Import.

A `Namespace` aggregates members through `Membership` relationships.
`Package` is the user-visible container (analogous to a UML package or
to Cameo's containment-tree node). Imports bring foreign members into
the local visibility scope.
"""
from __future__ import annotations

from typing import Optional

from .elements import Element, Relationship


class Membership(Relationship):
    """Membership of an element in a namespace (visibility, alias)."""

    kind = "Membership"

    def __init__(self, namespace: "Namespace", member: Element,
                 *, visibility: str = "public", alias: Optional[str] = None, **kwargs):
        super().__init__(source=namespace, target=member, **kwargs)
        self.visibility = visibility
        self.alias = alias

    @property
    def member(self) -> Element:
        return self.target  # type: ignore[return-value]

    @property
    def member_name(self) -> Optional[str]:
        return self.alias or self.member.name


class OwningMembership(Membership):
    """Membership that also makes the namespace own the member."""

    kind = "OwningMembership"


class Import(Relationship):
    """Import another namespace's members into this one."""

    kind = "Import"

    def __init__(self, importing: "Namespace", imported: "Namespace",
                 *, recursive: bool = False, visibility: str = "public", **kwargs):
        super().__init__(source=importing, target=imported, **kwargs)
        self.recursive = recursive
        self.visibility = visibility


class Namespace(Element):
    """A container of named members reachable by qualified name."""

    kind = "Namespace"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.memberships: list[Membership] = []
        self.imports: list[Import] = []

    # --- membership management ----------------------------------------
    def add_member(self, member: Element, *, owned: bool = True,
                   visibility: str = "public", alias: Optional[str] = None) -> Membership:
        cls = OwningMembership if owned else Membership
        m = cls(self, member, visibility=visibility, alias=alias)
        self.memberships.append(m)
        self.add_relationship(m)
        if owned:
            self.own(member)
        return m

    def own(self, child: Element) -> Element:  # type: ignore[override]
        super().own(child)
        if not any(m.member is child for m in self.memberships):
            m = OwningMembership(self, child)
            self.memberships.append(m)
            self.add_relationship(m)
        return child

    def add_import(self, imported: "Namespace", *, recursive: bool = False) -> Import:
        i = Import(self, imported, recursive=recursive)
        self.imports.append(i)
        self.add_relationship(i)
        return i

    # --- lookup --------------------------------------------------------
    def members(self, *, include_imports: bool = True) -> list[Element]:
        out = [m.member for m in self.memberships]
        if include_imports:
            seen = {id(e) for e in out}
            for imp in self.imports:
                target = imp.target
                if isinstance(target, Namespace):
                    for member in target.members(include_imports=imp.recursive):
                        if id(member) not in seen:
                            out.append(member)
                            seen.add(id(member))
        return out

    def resolve(self, qualified_name: str) -> Optional[Element]:
        """Resolve `A::B::C` against this namespace."""
        parts = qualified_name.split("::")
        current: Element = self
        for part in parts:
            if not isinstance(current, Namespace):
                return None
            match = next((m.member for m in current.memberships
                          if (m.alias or m.member.name) == part), None)
            if match is None:
                # Try imports.
                match = next((e for e in current.members(include_imports=True)
                              if e.name == part), None)
            if match is None:
                return None
            current = match
        return current


class Package(Namespace):
    """User-facing container in the SysML v2 containment tree."""

    kind = "Package"
