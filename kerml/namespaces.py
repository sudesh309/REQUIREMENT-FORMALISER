"""Namespaces, memberships and imports (KerML 8.3.2.4), packages (8.3.4.13).

A :class:`Namespace` has members through :class:`Membership` relationships:
an :class:`OwningMembership` owns its member, a plain Membership gives an
element owned elsewhere an alias. Imports (:class:`NamespaceImport`,
:class:`MembershipImport`) add the visible memberships of other namespaces.
Name resolution follows KerML 8.2.3.5 (see :meth:`Namespace.resolve_membership`);
:meth:`Namespace.resolve` keeps the application's lookup, which returns the
element rather than the membership.

``Namespace.own(child)`` picks the membership kind: a Type picks
``FeatureMembership`` and its specializations for features (see
``Type._membership_class_for``), everything else ``OwningMembership``; a
``membership=`` argument overrides the choice.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Union

from .elements import (
    DerivedList, Element, Relationship, escape_name, split_qualified_name, touch,
)

PUBLIC, PROTECTED, PRIVATE = "public", "protected", "private"
VISIBILITIES = (PUBLIC, PROTECTED, PRIVATE)


def _check_visibility(value: Any) -> str:
    v = getattr(value, "value", value)
    if v not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {list(VISIBILITIES)}, not {value!r}")
    return v


def _unique(memberships: Iterable["Membership"]) -> list["Membership"]:
    seen: set[int] = set()
    out = []
    for m in memberships:
        if id(m) not in seen:
            seen.add(id(m))
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Memberships
# ---------------------------------------------------------------------------

class Membership(Relationship):
    """Membership of ``member_element`` in its ``membership_owning_namespace``.

    A plain Membership names an element owned elsewhere (``member_name`` and
    ``member_short_name`` are aliases); :class:`OwningMembership` owns it.
    """

    kind = "Membership"
    _dies_with_owned = True
    _visibility = PUBLIC
    _member_name: Optional[str] = None
    _member_short_name: Optional[str] = None

    def __init__(self, namespace: Optional["Namespace"] = None, member: Optional[Element] = None, *,
                 visibility: str = PUBLIC, alias: Optional[str] = None,
                 member_name: Optional[str] = None, member_short_name: Optional[str] = None,
                 **kwargs):
        super().__init__(source=namespace, target=member, **kwargs)
        if visibility != PUBLIC:
            self._visibility = _check_visibility(visibility)
        if member_name is not None or alias is not None:
            self._member_name = member_name if member_name is not None else alias
        if member_short_name is not None:
            self._member_short_name = member_short_name

    @property
    def visibility(self) -> str:
        return self._visibility

    @visibility.setter
    def visibility(self, value: str) -> None:
        self._visibility = _check_visibility(value)
        touch()

    @property
    def member_element(self) -> Optional[Element]:
        return self.target

    @member_element.setter
    def member_element(self, value: Optional[Element]) -> None:
        self.target = value

    @property
    def member_element_id(self) -> Optional[str]:
        m = self.member_element
        return m.element_id if m is not None else None

    @property
    def membership_owning_namespace(self) -> Optional["Namespace"]:
        o = self._owning_related_element
        return o if o is not None else self.source  # type: ignore[return-value]

    @property
    def member_name(self) -> Optional[str]:
        """The name of the member in the namespace (an alias for a plain Membership)."""
        if self._member_name is not None:
            return self._member_name
        m = self.member_element
        return m.name if m is not None else None

    @member_name.setter
    def member_name(self, value: Optional[str]) -> None:
        self._member_name = value

    @property
    def member_short_name(self) -> Optional[str]:
        if self._member_short_name is not None or self._member_name is not None:
            return self._member_short_name
        m = self.member_element
        return m.short_name if m is not None else None

    @member_short_name.setter
    def member_short_name(self, value: Optional[str]) -> None:
        self._member_short_name = value

    # --- compatibility ---------------------------------------------------------
    @property
    def member(self) -> Optional[Element]:
        """Compatibility: ``member_element``."""
        return self.target

    @property
    def alias(self) -> Optional[str]:
        """Compatibility: the alias name of a plain Membership (None for an owning one)."""
        return self._member_name

    @alias.setter
    def alias(self, value: Optional[str]) -> None:
        self._member_name = value

    def is_distinguishable_from(self, other: "Membership") -> bool:
        a, b = self.member_element, other.member_element
        if a is None or b is None:
            return True
        if not (isinstance(a, type(b)) or isinstance(b, type(a))):
            return True
        names = {n for n in (other.member_short_name, other.member_name) if n is not None}
        return all(n is None or n not in names for n in (self.member_short_name, self.member_name))

    def path(self) -> str:
        m = self.member_element
        if isinstance(self, OwningMembership) and m is not None:
            qn = m._spec_qualified_name()
            if qn is not None:
                return qn + "/owningMembership"
        return super().path()


class OwningMembership(Membership):
    """A membership that owns its member (``owned_member_element``)."""

    kind = "OwningMembership"
    _tree_owns = True
    _carries_annotation = True

    def __init__(self, namespace: Optional["Namespace"] = None, member: Optional[Element] = None,
                 **kwargs):
        super().__init__(namespace, member, **kwargs)
        if member is not None:
            self.add_owned_related_element(member)

    @property
    def owned_member_element(self) -> Optional[Element]:
        owned = self._owned_related_elements
        return owned[0] if owned else None

    @property
    def member_element(self) -> Optional[Element]:
        owned = self._owned_related_elements
        return owned[0] if owned else self.target

    @member_element.setter
    def member_element(self, value: Optional[Element]) -> None:
        self.target = value

    @property
    def member(self) -> Optional[Element]:
        return self.member_element

    @property
    def target(self) -> Optional[Element]:
        owned = self._owned_related_elements
        if owned:
            return owned[0]
        t = self._targets
        return t[0] if t else None

    @target.setter
    def target(self, value: Optional[Element]) -> None:
        Relationship.target.fset(self, value)

    @property
    def targets(self) -> list[Element]:
        t = self.target
        return [t] if t is not None else []

    @targets.setter
    def targets(self, value: Iterable[Element]) -> None:
        Relationship.targets.fset(self, value)

    def add_owned_related_element(self, element: Element) -> Element:
        super().add_owned_related_element(element)
        if not self._targets:
            self._targets = [element]
        elif self._targets[0] is not element:
            self._targets[0] = element
        return element

    @property
    def owned_member_element_id(self) -> Optional[str]:
        m = self.owned_member_element
        return m.element_id if m is not None else None

    @property
    def owned_member_name(self) -> Optional[str]:
        m = self.owned_member_element
        return m.name if m is not None else None

    @property
    def owned_member_short_name(self) -> Optional[str]:
        m = self.owned_member_element
        return m.short_name if m is not None else None

    @property
    def member_name(self) -> Optional[str]:
        m = self.member_element
        return m.name if m is not None else None

    @member_name.setter
    def member_name(self, value: Optional[str]) -> None:
        raise AttributeError("the member name of an owning membership is its member's name")

    @property
    def member_short_name(self) -> Optional[str]:
        m = self.member_element
        return m.short_name if m is not None else None

    @member_short_name.setter
    def member_short_name(self, value: Optional[str]) -> None:
        raise AttributeError("the member short name of an owning membership is its member's short name")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

class Import(Relationship):
    """Imports memberships into its ``import_owning_namespace`` (abstract in the spec).

    ``visibility`` defaults to private as in the spec; ``Namespace.add_import``
    keeps the application's public default.
    """

    kind = "Import"
    _dies_with_owned = False

    def __init__(self, importing: Optional["Namespace"] = None, imported: Optional[Element] = None, *,
                 recursive: bool = False, is_recursive: Optional[bool] = None,
                 visibility: str = PRIVATE, is_import_all: bool = False, **kwargs):
        super().__init__(source=importing, target=imported, **kwargs)
        self.is_recursive: bool = bool(recursive if is_recursive is None else is_recursive)
        self.is_import_all: bool = bool(is_import_all)
        self._visibility = _check_visibility(visibility)

    @property
    def visibility(self) -> str:
        return self._visibility

    @visibility.setter
    def visibility(self, value: str) -> None:
        self._visibility = _check_visibility(value)
        touch()

    @property
    def recursive(self) -> bool:
        """Compatibility: ``is_recursive``."""
        return self.is_recursive

    @recursive.setter
    def recursive(self, value: bool) -> None:
        self.is_recursive = bool(value)

    @property
    def import_owning_namespace(self) -> Optional["Namespace"]:
        o = self._owning_related_element
        return o if o is not None else self.source  # type: ignore[return-value]

    @property
    def imported_element(self) -> Optional[Element]:
        return self.target

    def imported_memberships(self, excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        return []


class NamespaceImport(Import):
    """Imports the visible memberships of ``imported_namespace`` (``import X::*``, ``X::**``)."""

    kind = "NamespaceImport"

    @property
    def imported_namespace(self) -> Optional["Namespace"]:
        return self.target  # type: ignore[return-value]

    @imported_namespace.setter
    def imported_namespace(self, value: Optional["Namespace"]) -> None:
        self.target = value

    @property
    def target(self) -> Optional[Element]:
        t = self._targets
        if t:
            return t[0]
        owned = self._owned_related_elements      # a filter package owned by the import
        return owned[0] if owned else None

    @target.setter
    def target(self, value: Optional[Element]) -> None:
        Relationship.target.fset(self, value)

    def imported_memberships(self, excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        ns = self.imported_namespace
        excl = list(excluded)
        if not isinstance(ns, Namespace) or any(ns is x for x in excl):
            return []
        return ns.visible_memberships(excl, self.is_recursive, self.is_import_all)


class MembershipImport(Import):
    """Imports one ``imported_membership`` (``import X::a``, recursively ``X::a::**``)."""

    kind = "MembershipImport"

    @property
    def imported_membership(self) -> Optional[Membership]:
        return self.target  # type: ignore[return-value]

    @imported_membership.setter
    def imported_membership(self, value: Optional[Membership]) -> None:
        self.target = value

    @property
    def imported_element(self) -> Optional[Element]:
        m = self.imported_membership
        return m.member_element if isinstance(m, Membership) else None

    def imported_memberships(self, excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        m = self.imported_membership
        if not isinstance(m, Membership):
            return []
        el = m.member_element
        excl = list(excluded)
        if not self.is_recursive or not isinstance(el, Namespace) or any(el is x for x in excl):
            return [m]
        return _unique([m] + el.visible_memberships(excl, True, self.is_import_all))


# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

class Namespace(Element):
    """An element that contains members through memberships (KerML 8.3.2.4.5)."""

    kind = "Namespace"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)

    # --- derived properties ----------------------------------------------------
    @property
    def owned_memberships(self) -> list[Membership]:
        return [r for r in self._owned_relationships if isinstance(r, Membership)]

    @property
    def owned_imports(self) -> list[Import]:
        return [r for r in self._owned_relationships if isinstance(r, Import)]

    @property
    def imports(self) -> list[Import]:
        """Compatibility: ``owned_imports``."""
        return self.owned_imports

    @property
    def owned_members(self) -> list[Element]:
        return [x for r in self._owned_relationships if isinstance(r, OwningMembership)
                for x in r._owned_related_elements]

    def _imported_memberships(self, excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        excl = list(excluded) + [self]
        out: list[Membership] = []
        for imp in self.owned_imports:
            out += imp.imported_memberships(excl)
        own = self.owned_memberships
        own_ids = {id(m) for m in own}
        result = []
        for m in _unique(out):
            if id(m) in own_ids:
                continue
            result.append(m)
        return result

    @property
    def imported_memberships(self) -> DerivedList:
        """Memberships brought in by the owned imports (callable with ``excluded``)."""
        return DerivedList(self._imported_memberships(), self._imported_memberships)

    def _all_memberships(self) -> list[Membership]:
        return _unique(self.owned_memberships + self._imported_memberships())

    @property
    def memberships(self) -> list[Membership]:
        """All memberships: owned, imported and (for a Type) inherited (spec ``membership``)."""
        return self._all_memberships()

    def _members(self, *, include_imports: bool = True) -> list[Element]:
        ms = self._all_memberships() if include_imports else self.owned_memberships
        out, seen = [], set()
        for m in ms:
            e = m.member_element
            if e is not None and id(e) not in seen:
                seen.add(id(e))
                out.append(e)
        return out

    @property
    def members(self) -> DerivedList:
        """Member elements (spec ``member``).

        Compatibility: ``members(include_imports=False)`` lists the owned and
        aliased members only.
        """
        return DerivedList(self._members(), self._members)

    # --- visibility ------------------------------------------------------------
    def memberships_of_visibility(self, visibility: Optional[str],
                                  excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        excl = list(excluded) + [self]
        out = [m for m in self.owned_memberships if visibility is None or m.visibility == visibility]
        for imp in self.owned_imports:
            if visibility is None or imp.visibility == visibility:
                out += imp.imported_memberships(excl)
        return _unique(out)

    def visible_memberships(self, excluded: Iterable["Namespace"] = (), is_recursive: bool = False,
                            include_all: bool = False) -> list[Membership]:
        excl = list(excluded)
        out = self.memberships_of_visibility(None if include_all else PUBLIC, excl)
        if is_recursive:
            excl2 = excl + [self]
            for m in self.owned_memberships:
                if not isinstance(m, OwningMembership):
                    continue
                ns = m.member_element
                if isinstance(ns, Namespace) and (include_all or m.visibility == PUBLIC) \
                        and not any(ns is x for x in excl2):
                    out += ns.visible_memberships(excl2, True, include_all)
        return _unique(out)

    def visibility_of(self, membership: Membership) -> str:
        if any(m is membership for m in self.owned_memberships):
            return membership.visibility
        for imp in self.owned_imports:
            if any(m is membership for m in imp.imported_memberships(())):
                return imp.visibility
        if any(m is membership for m in self.memberships):
            return membership.visibility
        return PRIVATE

    def names_of(self, element: Element) -> list[str]:
        out: list[str] = []
        for m in self.memberships:
            if m.member_element is element:
                for n in (m.member_short_name, m.member_name):
                    if n is not None and n not in out:
                        out.append(n)
        return out

    # --- name resolution (KerML 8.2.3.5) ----------------------------------------
    @staticmethod
    def qualification_of(qualified_name: str) -> Optional[str]:
        segs = split_qualified_name(qualified_name)
        if len(segs) < 2:
            return None
        return "::".join(s if s == "$" else escape_name(s) for s in segs[:-1])

    @staticmethod
    def unqualified_name_of(qualified_name: str) -> str:
        return split_qualified_name(qualified_name)[-1]

    def _local_membership(self, name: str) -> Optional[Membership]:
        """The local resolution of a simple name: any membership naming it."""
        hit = None
        for m in self.memberships:
            if m.member_short_name == name or m.member_name == name:
                return m
        return hit

    def resolve_visible(self, name: str) -> Optional[Membership]:
        for m in self.visible_memberships((), False, False):
            if m.member_short_name == name or m.member_name == name:
                return m
        return None

    def resolve_local(self, name: str) -> Optional[Membership]:
        """Resolve a simple name here, then in the containing namespaces, then globally.

        A named root package (the project) is searched before the global scope,
        as a top-level package of an implied root namespace would be.
        """
        ns: Optional[Element] = self
        while ns is not None:
            if isinstance(ns, Namespace):
                m = ns._local_membership(name)
                if m is not None:
                    return m
            ns = ns.owner
        return self.resolve_global(name)

    def resolve_global(self, qualified_name: str) -> Optional[Membership]:
        """Resolve in the global namespace: the visible members of every root namespace."""
        segs = split_qualified_name(qualified_name)
        if segs and segs[0] == "$":
            segs = segs[1:]
        if not segs:
            return None
        for root in _global_roots(self):
            hit = None
            if len(segs) == 1:
                if isinstance(root, Namespace):
                    hit = root.resolve_visible(segs[0])
                if hit is None and root.name == segs[0]:
                    hit = _RootMembership(root)
            else:
                if root.name == segs[0] and isinstance(root, Namespace):
                    hit = root._resolve_segments(segs[1:], visible_first=True)
                elif isinstance(root, Namespace):
                    first = root.resolve_visible(segs[0])
                    if first is not None and isinstance(first.member_element, Namespace):
                        hit = first.member_element._resolve_segments(segs[1:], visible_first=True)
            if hit is not None:
                return hit
        return None

    def _resolve_segments(self, segs: list[str], *, visible_first: bool) -> Optional[Membership]:
        ns: Namespace = self
        hit: Optional[Membership] = None
        for i, seg in enumerate(segs):
            if i > 0:
                el = hit.member_element if hit is not None else None
                if not isinstance(el, Namespace):
                    return None
                ns = el
            hit = ns.resolve_visible(seg) if (visible_first or i > 0) else ns._local_membership(seg)
            if hit is None:
                return None
        return hit

    def resolve_membership(self, qualified_name: str) -> Optional[Membership]:
        """The spec's ``resolve``: the Membership a qualified name identifies from this scope."""
        segs = split_qualified_name(qualified_name)
        if not segs or not segs[-1]:
            return None
        if segs[0] == "$":
            return self.resolve_global("::".join(escape_name(s) for s in segs[1:]))
        first = self.resolve_local(segs[0])
        if len(segs) == 1 or first is None:
            return first
        el = first.member_element
        if not isinstance(el, Namespace):
            return None
        return el._resolve_segments(segs[1:], visible_first=True)

    def resolve(self, qualified_name: str) -> Optional[Element]:
        """Compatibility lookup of ``A::B::C`` relative to this namespace; returns the element.

        The first segment is looked up among this namespace's memberships
        (owned, aliased, imported and, for a type, inherited); later segments
        among the visible members of the previous one. Quoted segments
        (``'my part'``) and short names are accepted. Unlike
        :meth:`resolve_membership`, containing namespaces and the global
        scope are not searched.
        """
        if not isinstance(qualified_name, str):
            return None
        segs = split_qualified_name(qualified_name)
        if not segs or any(s == "" for s in segs):
            return None
        current: Element = self
        for i, seg in enumerate(segs):
            if not isinstance(current, Namespace):
                return None
            m = current._lookup_compat(seg, first=(i == 0))
            if m is None:
                return None
            current = m
        return current

    def _lookup_compat(self, seg: str, *, first: bool) -> Optional[Element]:
        for m in self.owned_memberships:
            if m.member_name == seg or m.member_short_name == seg:
                return m.member_element
        for m in (self.memberships if first else self.visible_memberships()):
            if m.member_name == seg or m.member_short_name == seg:
                return m.member_element
        return None

    # --- mutation ---------------------------------------------------------------
    def _membership_class_for(self, child: Element) -> type:
        return OwningMembership

    def own(self, child: Element, *, membership: Union[type, Membership, None] = None,
            visibility: str = PUBLIC) -> Element:
        """Own `child` through a new owning membership (idempotent).

        The membership kind is chosen by :meth:`_membership_class_for` unless
        `membership` gives a class (or a ready-made, unowned membership).
        """
        r = child._owning_relationship
        if r is not None and r._owning_related_element is self:
            if membership is None or (isinstance(membership, type) and type(r) is membership):
                return child
        if isinstance(membership, Membership):
            m = membership
            m.sources = [self]
            m.add_owned_related_element(child)
            self.add_relationship(m)
            return child
        cls = membership or self._membership_class_for(child)
        child.detach()
        m = cls(self, child, visibility=visibility)
        self.add_relationship(m)
        return child

    def add_member(self, member: Element, *, owned: bool = True, visibility: str = PUBLIC,
                   alias: Optional[str] = None) -> Membership:
        """Add `member`: owned (an owning membership) or aliased (a plain membership).

        Compatibility: ``owned=True`` with an ``alias`` owns the member and adds an
        alias membership for it; the alias membership is returned.
        """
        if owned:
            self.own(member, visibility=visibility)
            m = member._owning_relationship
            if alias is None:
                return m  # type: ignore[return-value]
        m = Membership(self, member, visibility=visibility, alias=alias)
        self.add_relationship(m)
        return m

    def add_import(self, imported: Union["Namespace", Membership], *, recursive: bool = False,
                   visibility: str = PUBLIC, import_all: bool = False,
                   filter_conditions: Optional[Iterable[Element]] = None) -> Import:
        """Import a namespace's visible members (or one membership).

        Compatibility default: ``visibility='public'``. With `filter_conditions`
        (expressions) the import is filtered (``import X::*[cond]``): the
        imported namespace becomes an owned filter package that imports `imported`
        and holds the conditions as ``ElementFilterMembership``s.
        """
        if filter_conditions:
            fp = Package()
            fp.add_import(imported, recursive=recursive, visibility=PUBLIC, import_all=import_all)
            for cond in filter_conditions:
                fp.add_relationship(ElementFilterMembership(fp, cond))
            imp = NamespaceImport(self, None, visibility=visibility, is_import_all=import_all)
            imp.add_owned_related_element(fp)
            self.add_relationship(imp)
            return imp
        if isinstance(imported, Membership):
            imp: Import = MembershipImport(self, imported, recursive=recursive, visibility=visibility,
                                           is_import_all=import_all)
        else:
            imp = NamespaceImport(self, imported, recursive=recursive, visibility=visibility,
                                  is_import_all=import_all)
        self.add_relationship(imp)
        return imp


class _RootMembership(Membership):
    """A transient membership naming a root namespace in the global scope."""

    kind = "Membership"

    def __init__(self, root: Element):
        super().__init__(None, root)


# Root namespaces available in the global scope (KerML 8.2.3.5.2): the model
# libraries plus whatever a repository registers.
_GLOBAL_ROOTS: list[Element] = []


def register_global_root(root: Element) -> None:
    if not any(r is root for r in _GLOBAL_ROOTS):
        _GLOBAL_ROOTS.append(root)


def _global_roots(start: Element) -> list[Element]:
    own_root = start.root()
    roots = [own_root] + [r for r in _GLOBAL_ROOTS if r is not own_root]
    return roots


# ---------------------------------------------------------------------------
# Packages (KerML 8.3.4.13)
# ---------------------------------------------------------------------------

class Package(Namespace):
    """User-facing container in the containment tree.

    ``filter_conditions`` are the expressions of its ``ElementFilterMembership``s;
    imported memberships whose member does not pass them are excluded (an
    expression is evaluated only when it has a Python ``evaluate`` that
    accepts the element; otherwise it is kept and evaluated from Phase 3).
    """

    kind = "Package"

    @property
    def filter_conditions(self) -> list[Element]:
        return [r.condition for r in self._owned_relationships
                if isinstance(r, ElementFilterMembership) and r.condition is not None]

    def include_as_member(self, element: Element) -> bool:
        for cond in self.filter_conditions:
            fn = getattr(cond, "evaluate_on", None)
            if callable(fn):
                try:
                    if not fn(element):
                        return False
                except Exception:  # noqa: BLE001 - an unevaluable condition does not filter
                    continue
        return True

    def _imported_memberships(self, excluded: Iterable["Namespace"] = ()) -> list[Membership]:
        out = super()._imported_memberships(excluded)
        if not self.filter_conditions:
            return out
        return [m for m in out if m.member_element is None or self.include_as_member(m.member_element)]


class LibraryPackage(Package):
    """A package of a model library; ``is_standard`` for the OMG standard libraries."""

    kind = "LibraryPackage"

    def __init__(self, name: Optional[str] = None, *, is_standard: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_standard: bool = bool(is_standard)

    def library_namespace(self) -> Optional[Element]:
        return self


class ElementFilterMembership(OwningMembership):
    """Owns a filter ``condition`` (a boolean expression) of a package."""

    kind = "ElementFilterMembership"
    _tree_owns = False

    @property
    def condition(self) -> Optional[Element]:
        return self.owned_member_element
