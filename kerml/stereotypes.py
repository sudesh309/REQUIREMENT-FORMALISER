"""User-defined Stereotypes — the SysML v2 successor of UML/SysML 1.x profiles.

In SysML v2 customization is done through KerML *MetadataDefinitions*; we
expose a friendlier "Stereotype" abstraction that:

- defines named tag-features (typed by KerML primitives) on a stereotype,
- can be *applied* to any Element to attach a typed tag-value bag,
- is itself a first-class Element so it round-trips through the
  serializer and shows up in the GUI and knowledge graph.
"""
from __future__ import annotations

from typing import Any, Optional

from .elements import Annotation, Element
from .features import Feature, MultiplicityRange
from .namespaces import Namespace
from .types import Type


class StereotypeTag(Feature):
    """A tag-property declared by a Stereotype."""

    kind = "StereotypeTag"

    def __init__(self, name: str, tag_type: Optional[Type] = None,
                 default: Any = None, **kwargs):
        super().__init__(name=name, typed_by=tag_type,
                         multiplicity=MultiplicityRange(0, 1), **kwargs)
        self.default_value = default


class Stereotype(Namespace):
    """A user-defined stereotype that can be applied to elements.

    Stereotypes are KerML metaobjects: each declaration adds a typed tag
    namespace; each *application* records (stereotype, {tag_name: value})
    on an annotated element via a `StereotypeApplication`.
    """

    kind = "Stereotype"

    def __init__(self, name: str, *,
                 applies_to: Optional[list[type]] = None,
                 base: Optional["Stereotype"] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        # Which Element subclasses this stereotype may decorate; empty = any.
        self.applies_to: list[type] = list(applies_to or [])
        self.base: Optional[Stereotype] = base
        self.tags: list[StereotypeTag] = []

    # --- definition ----------------------------------------------------
    def define_tag(self, name: str, tag_type: Optional[Type] = None,
                   default: Any = None) -> StereotypeTag:
        tag = StereotypeTag(name=name, tag_type=tag_type, default=default)
        self.own(tag)
        self.tags.append(tag)
        return tag

    def all_tags(self) -> list[StereotypeTag]:
        out: list[StereotypeTag] = []
        seen: set[str] = set()
        node: Optional[Stereotype] = self
        while node is not None:
            for t in node.tags:
                if t.name and t.name not in seen:
                    out.append(t); seen.add(t.name)
            node = node.base
        return out

    def can_apply_to(self, e: Element) -> bool:
        if not self.applies_to:
            return True
        return any(isinstance(e, t) for t in self.applies_to)

    # --- application ---------------------------------------------------
    def apply(self, target: Element, values: Optional[dict[str, Any]] = None
              ) -> "StereotypeApplication":
        if not self.can_apply_to(target):
            raise TypeError(
                f"Stereotype {self.name!r} cannot be applied to {target.kind} "
                f"{target.qualified_name!r}"
            )
        app = StereotypeApplication(self, values or {})
        target.add_annotation(app)
        return app


class StereotypeApplication(Annotation):
    """One application of a Stereotype to an Element."""

    kind = "StereotypeApplication"

    def __init__(self, stereotype: Stereotype, values: dict[str, Any], **kwargs):
        super().__init__(body=f"<<{stereotype.name}>>", **kwargs)
        self.stereotype = stereotype
        # Validate / coerce values against declared tags.
        self.values: dict[str, Any] = {}
        declared = {t.name: t for t in stereotype.all_tags()}
        for k, v in values.items():
            if k not in declared:
                raise KeyError(
                    f"Stereotype {stereotype.name!r} has no tag {k!r}; "
                    f"known: {sorted(declared)}"
                )
            self.values[k] = v
        # Fill in declared defaults so consumers don't have to.
        for k, t in declared.items():
            self.values.setdefault(k, t.default_value)

    def __repr__(self) -> str:
        return f"<<{self.stereotype.name} {self.values}>>"


def stereotypes_on(e: Element) -> list[StereotypeApplication]:
    return [a for a in e.annotations if isinstance(a, StereotypeApplication)]
