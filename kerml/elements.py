"""Root layer of the KerML abstract syntax: Element, Relationship, annotations, Dependency.

Every modeling construct in KerML (and therefore SysML v2) is an Element.
Ownership is carried by relationships (ADR 0002, decision 3).

Conventions for this package (also followed by modules that add metaclasses)
---------------------------------------------------------------------------

* **Metaclass.** A class names the spec metaclass it implements in ``kind``.
  An application class that is not a spec metaclass keeps its own ``kind`` and
  sets ``spec_metaclass`` to the metaclass it is interchanged as.
* **Python names.** A spec property becomes ``snake_case(name)``, pluralized
  when its upper multiplicity is greater than 1 (``ownedRelationship`` ->
  ``owned_relationships``). Derived properties are read-only Python
  properties; non-derived ones are plain attributes or properties with a
  setter. A spec operation becomes a method with the same snake_case name.
  When a derived property and an operation (or an older method) share a name,
  the property returns a :class:`DerivedList`, a list that can also be called
  with the operation's arguments.
* **Constructors** take the element's name as the only positional argument
  (relationships take their source and target) and everything else as
  keywords, so subclasses can pass ``**kwargs`` through ``super().__init__``
  in any multiple-inheritance order.
* **Storage.** Ownership lives in four private fields:
  ``Element._owned_relationships`` (ordered) and ``Element._owning_relationship``;
  ``Relationship._owned_related_elements`` (ordered) and
  ``Relationship._owning_related_element``. ``Relationship._sources`` and
  ``_targets`` hold the ordered related elements. Only the mutation API
  (:meth:`Element.add_relationship`, :meth:`Element.remove_relationship`,
  :meth:`Relationship.add_owned_related_element`, :meth:`Element.detach`,
  ``Namespace.own``) changes them; the derived ``owner`` and
  ``owned_elements`` are cached and the caches are cleared by that API.
* **Application view.** :meth:`Element.walk` and :attr:`Element.children`
  follow the owned members the application shows in its containment tree:
  annotating elements (reached through ``annotations`` / ``documentation``)
  and the structural sub-elements that realize relationship-valued
  compatibility attributes (connector ends, transition triggers, requirement
  subjects, feature chains, ...) are left out. ``owned_elements`` is the
  spec's ``ownedElement`` and includes them; ``walk(structure=True)`` follows
  every owned element.
* **Compatibility properties** keep the meaning they had before the core
  became relationship based; each one says so in its docstring.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Iterable, Iterator, Optional

# Namespace for deterministic ids of elements materialized from values (ADR 0002 decision 5).
ID_NAMESPACE = uuid.UUID("6f1b6c2e-8a51-5c55-9a3f-7d3c1f0e2b41")


def derived_id(owner_id: str, role: str) -> str:
    """Deterministic UUID v5 for a sub-element of `owner_id` playing `role`."""
    return str(uuid.uuid5(ID_NAMESPACE, f"{owner_id}/{role}"))


# A global modification counter: every structural mutation increments it, so
# derived values that depend on the whole model (imported and inherited
# memberships) can be cached and dropped when anything changes.
_EPOCH = [0]


def model_epoch() -> int:
    return _EPOCH[0]


def touch() -> None:
    """Record a structural change (clears every epoch-keyed cache)."""
    _EPOCH[0] += 1


class DerivedList(list):
    """A derived list that can also be called (see the module docstring).

    ``ns.members`` is the spec's derived ``member``; ``ns.members(...)`` calls
    the operation (or older method) of the same name with arguments.
    """

    __slots__ = ("_call",)

    def __init__(self, items: Iterable = (), call: Optional[Callable] = None):
        super().__init__(items)
        self._call = call

    def __call__(self, *args, **kwargs):
        if self._call is None:
            return list(self)
        return self._call(*args, **kwargs)


# ---------------------------------------------------------------------------
# Names (KerML 8.2.2.3 lexical structure)
# ---------------------------------------------------------------------------

_BASIC_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ESCAPES = {"\\": "\\\\", "'": "\\'", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f",
            "\r": "\\r"}
_UNESCAPES = {"\\": "\\", "'": "'", '"': '"', "b": "\b", "t": "\t", "n": "\n", "f": "\f",
              "r": "\r"}


_ESCAPED: dict[str, str] = {}


def is_basic_name(name: str) -> bool:
    return bool(_BASIC_NAME.match(name))


def escape_name(name: Optional[str]) -> Optional[str]:
    """`name` as is when it is a basic name, otherwise as a quoted unrestricted name."""
    if name is None:
        return None
    if _BASIC_NAME.match(name):
        return name
    return "'" + "".join(_ESCAPES.get(c, c) for c in name) + "'"


def unescape_name(segment: str) -> str:
    """The name a (possibly quoted) name segment stands for."""
    s = segment.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        out, i, body = [], 0, s[1:-1]
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                out.append(_UNESCAPES.get(body[i + 1], body[i + 1]))
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    return s


def split_qualified_name(qualified_name: str) -> list[str]:
    """Segments of a qualified name, unescaped (``A::'b c'::D`` -> ``['A', 'b c', 'D']``).

    A leading global scope qualifier is kept as the segment ``'$'``. Unquoted
    segments are taken as written (so ``A::my part`` still splits as two
    segments), which keeps names typed by users resolvable.
    """
    segments: list[str] = []
    buf: list[str] = []
    i, n, quoted = 0, len(qualified_name), False
    while i < n:
        c = qualified_name[i]
        if quoted:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(qualified_name[i + 1])
                i += 2
                continue
            if c == "'":
                quoted = False
        elif c == "'":
            quoted = True
            buf.append(c)
        elif c == ":" and i + 1 < n and qualified_name[i + 1] == ":":
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        else:
            buf.append(c)
        i += 1
    segments.append("".join(buf))
    return [unescape_name(s) for s in segments]


# ---------------------------------------------------------------------------
# Element
# ---------------------------------------------------------------------------

class Element:
    """Root of the KerML metamodel (KerML 8.3.2.1.2).

    Identity is ``element_id`` (a UUID). Names are declared
    (``declared_name``, ``declared_short_name``) and effective (``name``,
    ``short_name``, derived by :meth:`effective_name`). Ownership is derived
    from relationships: ``owner`` is the owning related element of the
    ``owning_relationship`` and ``owned_elements`` the owned related elements
    of the ``owned_relationships``.
    """

    kind: str = "Element"
    # Application classes that are not spec metaclasses name the metaclass they
    # are interchanged as.
    spec_metaclass: Optional[str] = None
    # Class flags read by the traversal (see the module docstring).
    _annotating = False      # AnnotatingElement
    _extension = False       # kept outside the relationship structure (stereotype applications)

    def __init__(self, name: Optional[str] = None, *, short_name: Optional[str] = None,
                 element_id: Optional[str] = None, declared_name: Optional[str] = None,
                 declared_short_name: Optional[str] = None,
                 alias_ids: Optional[Iterable[str]] = None,
                 is_implied_included: bool = False):
        self.element_id: str = element_id or str(uuid.uuid4())
        self._declared_name: Optional[str] = declared_name if declared_name is not None else name
        self._declared_short_name: Optional[str] = (declared_short_name if declared_short_name is not None
                                                    else short_name)
        self.alias_ids: list[str] = list(alias_ids or ())
        self.is_implied_included: bool = bool(is_implied_included)
        self._owned_relationships: list[Relationship] = []
        self._owning_relationship: Optional[Relationship] = None
        # Spec ``owner`` (the owning related element of the owning relationship), cached
        # as a plain attribute and kept in step by the mutation API; never assign it.
        self.owner: Optional[Element] = None
        self._oe: Optional[list] = None      # cache of owned_elements
        self._tc: Optional[list] = None      # cache of the application tree children
        self._ext_annotations: list = []     # extension annotations (stereotype applications)
        # Compatibility: every element has ``is_abstract`` (the spec has it on Type).
        self.is_abstract = False
        # Free-form metadata used by tooling (canvas layout, source position, ...).
        self.tool_data: dict = {}

    # --- metaclass ---------------------------------------------------------
    @classmethod
    def metaclass_name(cls) -> str:
        """The spec metaclass this class is interchanged as."""
        return cls.spec_metaclass or cls.kind

    # --- names -------------------------------------------------------------
    @property
    def declared_name(self) -> Optional[str]:
        return self._declared_name

    @declared_name.setter
    def declared_name(self, value: Optional[str]) -> None:
        self._declared_name = value

    @property
    def declared_short_name(self) -> Optional[str]:
        return self._declared_short_name

    @declared_short_name.setter
    def declared_short_name(self, value: Optional[str]) -> None:
        self._declared_short_name = value

    @property
    def name(self) -> Optional[str]:
        """The effective name (spec ``name``); assigning sets ``declared_name``."""
        return self._declared_name

    @name.setter
    def name(self, value: Optional[str]) -> None:
        self._declared_name = value

    @property
    def short_name(self) -> Optional[str]:
        """The effective short name (spec ``shortName``); assigning sets ``declared_short_name``."""
        return self._declared_short_name

    @short_name.setter
    def short_name(self, value: Optional[str]) -> None:
        self._declared_short_name = value

    def effective_name(self) -> Optional[str]:
        return self._declared_name

    def effective_short_name(self) -> Optional[str]:
        return self._declared_short_name

    def escaped_name(self) -> Optional[str]:
        """``name`` (else ``short_name``) as it is written in a qualified name."""
        n = self.name
        if n is None:
            n = self.short_name
        return escape_name(n)

    @property
    def qualified_name(self) -> str:
        """``Root::Pkg::'my part'`` (spec ``qualifiedName``, with two compatibility rules).

        Segments are escaped names, so unrestricted names are quoted. Unlike the
        spec, a named root package is part of the name (the project root is a
        top-level package of an implied root namespace), the name of an
        element whose ancestors are not all named starts at the first unnamed
        ancestor, and an element without a name reads ``<1a2b3c4d>`` (its id
        prefix) instead of null: the application addresses elements by these.
        """
        parts: list[str] = []
        node: Optional[Element] = self
        cache = _ESCAPED
        while node is not None:
            n = node.name
            if n is None:
                n = node.short_name
                if n is None:
                    break
            en = cache.get(n)
            if en is None:
                en = escape_name(n)
                if len(cache) < 100_000:
                    cache[n] = en
            parts.append(en)
            node = node.owner
        return "::".join(reversed(parts)) if parts else f"<{self.element_id[:8]}>"

    # --- ownership (derived) -------------------------------------------------
    @property
    def owning_relationship(self) -> Optional["Relationship"]:
        return self._owning_relationship

    @property
    def owned_relationships(self) -> list["Relationship"]:
        """The relationships this element owns, in order (spec ``ownedRelationship``).

        Compatibility: assigning a list removes the owned relationships it leaves
        out (with the elements they own) and puts the rest in the given order.
        """
        return list(self._owned_relationships)

    @owned_relationships.setter
    def owned_relationships(self, value: Iterable["Relationship"]) -> None:
        wanted = list(value)
        keep = {id(r) for r in wanted}
        for r in list(self._owned_relationships):
            if id(r) not in keep:
                self.remove_relationship(r)
        current = {id(r) for r in self._owned_relationships}
        for r in wanted:
            if id(r) not in current:
                self.add_relationship(r)
        order = {id(r): i for i, r in enumerate(wanted)}
        self._owned_relationships.sort(key=lambda r: order.get(id(r), len(order)))
        self._invalidate()

    @property
    def owned_elements(self) -> list["Element"]:
        """The owned related elements of the owned relationships (spec ``ownedElement``).

        This includes annotating elements and structural sub-elements; use
        :attr:`children` for the elements the application shows in its tree.

        Compatibility: assigning a list re-orders the tree children to the given
        order and detaches the tree children it leaves out. Annotating elements
        and structural sub-elements are kept.
        """
        oe = self._oe
        if oe is None:
            oe = self._oe = [x for r in self._owned_relationships for x in r._owned_related_elements]
        return list(oe)

    @owned_elements.setter
    def owned_elements(self, value: Iterable["Element"]) -> None:
        wanted = list(value)
        keep = {id(x) for x in wanted}
        for c in list(self._tree_children()):
            if id(c) not in keep:
                c.detach()
        for x in wanted:
            if x.owner is not self:
                self.own(x)
        rank = {id(x): i for i, x in enumerate(wanted)}
        n = len(rank)

        def key(r: "Relationship") -> int:
            owned = r._owned_related_elements
            return rank.get(id(owned[0]), n) if owned else n

        # Stable sort of the owning relationships of the listed elements into the
        # positions they already occupy; other relationships do not move.
        slots = [i for i, r in enumerate(self._owned_relationships)
                 if r._owned_related_elements and id(r._owned_related_elements[0]) in rank]
        ordered = sorted((self._owned_relationships[i] for i in slots), key=key)
        for i, r in zip(slots, ordered):
            self._owned_relationships[i] = r
        self._invalidate()

    @property
    def owning_membership(self) -> Optional["Element"]:
        from .namespaces import OwningMembership
        r = self._owning_relationship
        return r if isinstance(r, OwningMembership) else None

    @property
    def owning_namespace(self) -> Optional["Element"]:
        m = self.owning_membership
        return m.membership_owning_namespace if m is not None else None

    @property
    def documentation(self) -> list["Documentation"]:
        """The Documentation this element owns (spec ``documentation``)."""
        return [x for x in self._owned_elements_cached() if isinstance(x, Documentation)]

    @property
    def textual_representations(self) -> list["TextualRepresentation"]:
        return [x for x in self._owned_elements_cached() if isinstance(x, TextualRepresentation)]

    @property
    def owned_annotations(self) -> list["Annotation"]:
        """Owned Annotation relationships whose annotated element is this element."""
        return [r for r in self._owned_relationships
                if isinstance(r, Annotation) and r.annotated_element is self]

    @property
    def is_library_element(self) -> bool:
        return self.library_namespace() is not None

    def library_namespace(self) -> Optional["Element"]:
        r = self._owning_relationship
        return r.library_namespace() if r is not None else None

    def path(self) -> str:
        """A unique description of where this element sits (spec ``path()``)."""
        qn = self._spec_qualified_name()
        if qn is not None:
            return qn
        r = self._owning_relationship
        if r is not None:
            idx = next(i for i, x in enumerate(r._owned_related_elements) if x is self)
            return f"{r.path()}/{idx + 1}"
        return ""

    def _spec_qualified_name(self) -> Optional[str]:
        ns = self.owning_namespace
        if ns is None:
            return None
        en = self.escaped_name()
        if en is None:
            return None
        if ns.owner is None:
            return en
        q = ns._spec_qualified_name()
        return None if q is None else f"{q}::{en}"

    def root(self) -> "Element":
        node: Element = self
        while True:
            o = node.owner
            if o is None:
                return node
            node = o

    # --- caches --------------------------------------------------------------
    def _invalidate(self) -> None:
        self._oe = None
        self._tc = None
        _EPOCH[0] += 1

    def _owned_elements_cached(self) -> list["Element"]:
        oe = self._oe
        if oe is None:
            oe = self._oe = [x for r in self._owned_relationships for x in r._owned_related_elements]
        return oe

    def _tree_children(self) -> list["Element"]:
        tc = self._tc
        if tc is None:
            tc = []
            for r in self._owned_relationships:
                if r._tree_owns:
                    for x in r._owned_related_elements:
                        if not x._annotating:
                            tc.append(x)
            self._tc = tc
        return tc

    @property
    def children(self) -> list["Element"]:
        """The owned elements the application shows in its containment tree (see module doc)."""
        return list(self._tree_children())

    # --- mutation API ----------------------------------------------------------
    def add_relationship(self, rel: "Relationship", index: Optional[int] = None) -> "Relationship":
        """Make this element the owning related element of `rel`."""
        cur = rel._owning_related_element
        if cur is self:
            return rel
        if cur is not None:
            cur.remove_relationship(rel)
        if rel._owning_relationship is not None:
            rel.detach()
        if index is None:
            self._owned_relationships.append(rel)
        else:
            self._owned_relationships.insert(index, rel)
        rel._owning_related_element = self
        rel.owner = self
        for x in rel._owned_related_elements:
            x.owner = self
        self._invalidate()
        return rel

    def remove_relationship(self, rel: "Relationship") -> None:
        """Stop owning `rel` (the elements `rel` owns stay owned by it)."""
        lst = self._owned_relationships
        for i, r in enumerate(lst):
            if r is rel:
                del lst[i]
                rel._owning_related_element = None
                if rel._owning_relationship is None:
                    rel.owner = None
                for x in rel._owned_related_elements:
                    x.owner = None
                self._invalidate()
                return

    def detach(self) -> None:
        """Remove this element from its owner.

        A membership or annotation that only owned this element is removed
        from its owner too; other owning relationships just release it.
        """
        r = self._owning_relationship
        if r is None:
            return
        r._release(self)
        if r._dies_with_owned and not r._owned_related_elements:
            o = r._owning_related_element
            if o is not None:
                o.remove_relationship(r)

    def clone_bare(self, element_id: Optional[str] = None) -> "Element":
        """A shallow copy with a new id and no relationships, owner or annotations.

        Plain attributes (names, flags, values, application attributes) are
        shared with this element as ``copy.copy`` would; deep-copy helpers
        rebuild relationships and ownership on top.
        """
        import copy as _copy
        c = _copy.copy(self)
        c.element_id = element_id or str(uuid.uuid4())
        c._owned_relationships = []
        c._owning_relationship = None
        c.owner = None
        c._oe = c._tc = None
        c._ext_annotations = []
        c.alias_ids = list(self.alias_ids)
        c.__dict__.pop("_inh_cache", None)
        if isinstance(self, Relationship):
            c._sources = list(self._sources)
            c._targets = list(self._targets)
            c._owned_related_elements = []
            c._owning_related_element = None
        if isinstance(self, AnnotatingElement):
            c._annotated_compat = None
        return c

    def own(self, child: "Element") -> "Element":
        """Take ownership of `child`. Only a Namespace can own members."""
        raise TypeError(f"{self.kind} {self.qualified_name!r} is not a Namespace and cannot own "
                        f"{child.kind} {child.qualified_name!r}")

    # --- annotations ---------------------------------------------------------
    def add_annotation(self, annotation: "Element") -> "Element":
        """Annotate this element with an annotating element it owns.

        A Namespace owns it through an OwningMembership (as ``doc`` in a body
        does); other elements through an owned Annotation relationship.
        Extension annotations (stereotype applications) are kept on the
        element in Phase 1 (ADR 0002 decision 6).
        """
        if annotation._extension or not annotation._annotating:
            annotation.annotated_element = self
            self._ext_annotations.append(annotation)
            return annotation
        from .namespaces import Namespace
        if isinstance(self, Namespace):
            self.own(annotation)
        else:
            annotation.detach()
            rel = Annotation(annotated=self)
            rel.add_owned_related_element(annotation)
            self.add_relationship(rel)
        return annotation

    def remove_annotation(self, annotation: "Element") -> None:
        if annotation._extension or not annotation._annotating:
            self._ext_annotations = [a for a in self._ext_annotations if a is not annotation]
            return
        if annotation.owner is self:
            annotation.detach()

    @property
    def annotations(self) -> list["Element"]:
        """Compatibility: the annotating elements attached to this element.

        That is the comments, documentation and textual representations it owns
        and that annotate it, followed by its extension annotations (stereotype
        applications). Assigning a list detaches the ones it leaves out and
        attaches new ones.
        """
        out: list[Element] = []
        for r in self._owned_relationships:
            if r._carries_annotation:
                for x in r._owned_related_elements:
                    if x._annotating and (not x._owned_relationships
                                          or any(a is self for a in x.annotated_elements)):
                        out.append(x)
        out.extend(self._ext_annotations)
        return out

    @annotations.setter
    def annotations(self, value: Iterable["Element"]) -> None:
        wanted = list(value)
        keep = {id(a) for a in wanted}
        for a in self.annotations:
            if id(a) not in keep:
                self.remove_annotation(a)
        have = {id(a) for a in self.annotations}
        self._ext_annotations = [a for a in wanted if a._extension or not a._annotating]
        for a in wanted:
            if id(a) not in have and not (a._extension or not a._annotating):
                self.add_annotation(a)

    # --- traversal -----------------------------------------------------------
    def walk(self, *, structure: bool = False) -> Iterator["Element"]:
        """Depth-first pre-order traversal of this element and its tree children.

        With ``structure=True`` every owned element is followed (annotating
        elements and structural sub-elements included).
        """
        stack = [self]
        pop, extend = stack.pop, stack.extend
        if structure:
            while stack:
                e = pop()
                yield e
                kids = e._owned_elements_cached()
                if kids:
                    extend(reversed(kids))
        else:
            while stack:
                e = pop()
                yield e
                kids = e._tc if e._tc is not None else e._tree_children()
                if kids:
                    extend(reversed(kids))

    def find(self, predicate) -> Iterator["Element"]:
        return (e for e in self.walk() if predicate(e))

    # --- pretty printing ----------------------------------------------------
    def __repr__(self) -> str:
        return f"<{self.kind} {self.qualified_name!r}>"


def is_pure_relationship(e: Any) -> bool:
    """True for a relationship that is not also a type (connectors and associations are both).

    The application lists types (including ``ConnectionUsage``, a Connector)
    as model elements and keeps pure relationships (memberships, links,
    specializations) out of element lists.
    """
    if not isinstance(e, Relationship):
        return False
    from .types import Type
    return not isinstance(e, Type)


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------

class Relationship(Element):
    """An Element that relates other Elements (KerML 8.3.2.1.3).

    ``sources`` and ``targets`` are ordered; ``source`` and ``target`` are
    singular conveniences (the first of each). A relationship can own some of
    its related elements (``owned_related_elements``) and is itself owned by
    its ``owning_related_element``.

    ``owner`` (compatibility): for a relationship owned through an owning
    relationship it is the spec ``owner``; for one in the
    ``owned_relationships`` of an element it is that
    ``owning_related_element`` (the spec leaves ``owner`` null there), which
    is how the application finds the container of a link.
    """

    kind = "Relationship"
    # Traversal flags: does the application tree descend into the owned
    # related elements; does an annotating element owned by it annotate the
    # owner; is the relationship removed when its last owned element leaves.
    _tree_owns = False
    _carries_annotation = False
    _dies_with_owned = False

    def __init__(self, source: Optional[Element] = None, target: Optional[Element] = None, *,
                 sources: Optional[Iterable[Element]] = None,
                 targets: Optional[Iterable[Element]] = None,
                 is_implied: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._init_relationship(source, target, sources, targets, is_implied)

    def _init_relationship(self, source=None, target=None, sources=None, targets=None,
                           is_implied: bool = False) -> None:
        self._sources: list[Element] = list(sources) if sources is not None else (
            [source] if source is not None else [])
        self._targets: list[Element] = list(targets) if targets is not None else (
            [target] if target is not None else [])
        self._owned_related_elements: list[Element] = []
        self._owning_related_element: Optional[Element] = None
        self.is_implied: bool = bool(is_implied)

    # --- related elements ----------------------------------------------------
    @property
    def sources(self) -> list[Element]:
        return list(self._sources)

    @sources.setter
    def sources(self, value: Iterable[Element]) -> None:
        self._sources = [v for v in value if v is not None]
        _EPOCH[0] += 1

    @property
    def targets(self) -> list[Element]:
        return list(self._targets)

    @targets.setter
    def targets(self, value: Iterable[Element]) -> None:
        self._targets = [v for v in value if v is not None]
        _EPOCH[0] += 1

    @property
    def source(self) -> Optional[Element]:
        """Compatibility: the first source (assigning replaces it; None removes it)."""
        s = self._sources
        return s[0] if s else None

    @source.setter
    def source(self, value: Optional[Element]) -> None:
        if value is None:
            self._sources = self._sources[1:]
        elif self._sources:
            self._sources[0] = value
        else:
            self._sources = [value]
        _EPOCH[0] += 1

    @property
    def target(self) -> Optional[Element]:
        """Compatibility: the first target (assigning replaces it; None removes it)."""
        t = self._targets
        return t[0] if t else None

    @target.setter
    def target(self, value: Optional[Element]) -> None:
        if value is None:
            self._targets = self._targets[1:]
        elif self._targets:
            self._targets[0] = value
        else:
            self._targets = [value]
        _EPOCH[0] += 1

    @property
    def related_elements(self) -> list[Element]:
        return self.sources + self.targets

    @property
    def related(self) -> tuple[Optional[Element], Optional[Element]]:
        """Compatibility: ``(source, target)``."""
        return (self.source, self.target)

    @property
    def owned_related_elements(self) -> list[Element]:
        return list(self._owned_related_elements)

    @property
    def owning_related_element(self) -> Optional[Element]:
        return self._owning_related_element

    def detach(self) -> None:
        if self._owning_relationship is not None:
            super().detach()
        elif self._owning_related_element is not None:
            self._owning_related_element.remove_relationship(self)

    def library_namespace(self) -> Optional[Element]:
        o = self._owning_related_element
        if o is not None:
            return o.library_namespace()
        r = self._owning_relationship
        return r.library_namespace() if r is not None else None

    def path(self) -> str:
        o = self._owning_related_element
        if self._owning_relationship is None and o is not None:
            idx = next(i for i, r in enumerate(o._owned_relationships) if r is self)
            return f"{o.path()}/{idx + 1}"
        return super().path()

    # --- owned related elements ----------------------------------------------
    def add_owned_related_element(self, element: Element) -> Element:
        """Own `element` (it leaves its previous owner)."""
        if element._owning_relationship is self:
            return element
        element.detach()
        self._owned_related_elements.append(element)
        element._owning_relationship = self
        element.owner = self._owning_related_element
        o = self._owning_related_element
        if o is not None:
            o._invalidate()
        else:
            _EPOCH[0] += 1
        return element

    def _release(self, element: Element) -> None:
        lst = self._owned_related_elements
        for i, x in enumerate(lst):
            if x is element:
                del lst[i]
                break
        element._owning_relationship = None
        element.owner = None
        o = self._owning_related_element
        if o is not None:
            o._invalidate()
        else:
            _EPOCH[0] += 1

    def remove_owned_related_element(self, element: Element) -> None:
        if element._owning_relationship is self:
            self._release(element)


# ---------------------------------------------------------------------------
# Dependencies (KerML 8.3.2.2)
# ---------------------------------------------------------------------------

class Dependency(Relationship):
    """``client`` elements depend on ``supplier`` elements (both ordered, n-ary)."""

    kind = "Dependency"

    def __init__(self, client: Any = None, supplier: Any = None, *,
                 clients: Optional[Iterable[Element]] = None,
                 suppliers: Optional[Iterable[Element]] = None, **kwargs):
        if clients is None:
            clients = list(client) if isinstance(client, (list, tuple)) else (
                [client] if client is not None else [])
        if suppliers is None:
            suppliers = list(supplier) if isinstance(supplier, (list, tuple)) else (
                [supplier] if supplier is not None else [])
        super().__init__(sources=clients, targets=suppliers, **kwargs)

    @property
    def clients(self) -> list[Element]:
        return self.sources

    @clients.setter
    def clients(self, value: Iterable[Element]) -> None:
        self.sources = value

    @property
    def suppliers(self) -> list[Element]:
        return self.targets

    @suppliers.setter
    def suppliers(self, value: Iterable[Element]) -> None:
        self.targets = value


# ---------------------------------------------------------------------------
# Annotations (KerML 8.3.2.3)
# ---------------------------------------------------------------------------

class Annotation(Relationship):
    """Relationship between an AnnotatingElement and the Element it annotates.

    ``annotating_element`` is the source, ``annotated_element`` the target.
    The relationship owns its annotating element when it is owned by the
    annotated element (an *owned annotation*); otherwise it is owned by the
    annotating element (a comment ``about`` other elements).
    """

    kind = "Annotation"
    _tree_owns = False
    _carries_annotation = True
    _dies_with_owned = True

    def __init__(self, annotating: Optional[Element] = None, annotated: Optional[Element] = None,
                 **kwargs):
        super().__init__(source=annotating, target=annotated, **kwargs)

    @property
    def annotated_element(self) -> Optional[Element]:
        return self.target

    @annotated_element.setter
    def annotated_element(self, value: Optional[Element]) -> None:
        self.target = value

    @property
    def owned_annotating_element(self) -> Optional["AnnotatingElement"]:
        return next((x for x in self._owned_related_elements if isinstance(x, AnnotatingElement)), None)

    @property
    def owning_annotating_element(self) -> Optional["AnnotatingElement"]:
        o = self._owning_related_element
        return o if isinstance(o, AnnotatingElement) else None

    @property
    def owning_annotated_element(self) -> Optional[Element]:
        o = self._owning_related_element
        return o if o is not None and o is self.annotated_element else None

    @property
    def annotating_element(self) -> Optional["AnnotatingElement"]:
        return self.owned_annotating_element or self.owning_annotating_element or (
            self.source if isinstance(self.source, AnnotatingElement) else None)

    @property
    def source(self) -> Optional[Element]:
        s = self._sources
        if s:
            return s[0]
        return self.owned_annotating_element or self.owning_annotating_element

    @source.setter
    def source(self, value: Optional[Element]) -> None:
        Relationship.source.fset(self, value)

    @property
    def sources(self) -> list[Element]:
        a = self.source
        return [a] if a is not None else []

    @sources.setter
    def sources(self, value: Iterable[Element]) -> None:
        Relationship.sources.fset(self, value)


class AnnotatingElement(Element):
    """An element that annotates other elements (KerML 8.3.2.3.2).

    Its ``annotated_elements`` are the targets of its ``annotations``; without
    annotations it annotates its owning namespace (or the element owning its
    owned annotation).
    """

    kind = "AnnotatingElement"
    _annotating = True

    def __init__(self, name: Optional[str] = None, *, about: Optional[Iterable[Element]] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self._annotated_compat: Optional[Element] = None
        for e in about or ():
            self.add_about(e)

    @property
    def owning_annotating_relationship(self) -> Optional[Annotation]:
        r = self._owning_relationship
        return r if isinstance(r, Annotation) else None

    @property
    def owned_annotating_relationships(self) -> list[Annotation]:
        return [r for r in self._owned_relationships
                if isinstance(r, Annotation) and r.annotated_element is not self]

    @property
    def annotations(self) -> list[Annotation]:  # type: ignore[override]
        """The Annotations relating this element to what it annotates (spec ``annotation``)."""
        r = self.owning_annotating_relationship
        own = self.owned_annotating_relationships
        return ([r] + own) if r is not None else own

    @annotations.setter
    def annotations(self, value) -> None:
        raise AttributeError("annotations of an annotating element are derived; use add_about()")

    @property
    def annotated_elements(self) -> list[Element]:
        anns = self.annotations
        if anns:
            return [a.annotated_element for a in anns if a.annotated_element is not None]
        if self._annotated_compat is not None:
            return [self._annotated_compat]
        o = self.owner
        return [o] if o is not None else []

    @property
    def annotated_element(self) -> Optional[Element]:
        """Compatibility: the first annotated element."""
        ae = self.annotated_elements
        return ae[0] if ae else None

    @annotated_element.setter
    def annotated_element(self, value: Optional[Element]) -> None:
        self._annotated_compat = value

    def add_about(self, element: Element) -> Annotation:
        """Annotate `element` too (``comment about a, b``): an owned annotating relationship."""
        rel = Annotation(self, element)
        self.add_relationship(rel)
        return rel


class Comment(AnnotatingElement):
    """A comment whose ``body`` describes its annotated elements; ``locale`` is optional."""

    kind = "Comment"

    def __init__(self, body: str = "", *, locale: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.body: str = body
        self.locale: Optional[str] = locale


class Documentation(Comment):
    """A comment that documents its owner (``doc``)."""

    kind = "Documentation"

    @property
    def documented_element(self) -> Optional[Element]:
        return self.owner


class TextualRepresentation(AnnotatingElement):
    """The ``body`` of its owner in a named ``language`` (``rep``)."""

    kind = "TextualRepresentation"

    def __init__(self, body: str = "", *, language: str = "", **kwargs):
        super().__init__(**kwargs)
        self.body: str = body
        self.language: str = language

    @property
    def represented_element(self) -> Optional[Element]:
        return self.owner


def iter_owned(elements: Iterable[Element]) -> Iterator[Element]:
    for e in elements:
        yield from e.walk()
