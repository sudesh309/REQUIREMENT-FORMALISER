"""Metadata (KerML 8.3.4.12): Metaclass and MetadataFeature.

A :class:`MetadataFeature` is an AnnotatingElement and a Feature typed by a
:class:`Metaclass`; it annotates the elements it is ``about`` (or, without
annotations, its owner) with structured metadata. Its owned features redefine
features of its metaclass and bind them to model-level evaluable values.

A metadata feature in the body of a namespace (``@M;``) is owned through an
``OwningMembership``, as other annotating elements are: pass
``membership=OwningMembership`` to ``own`` (``Type.own`` would otherwise pick
a ``FeatureMembership`` because it is a feature), or use :func:`annotate`. It
is hidden from the application tree like comments are.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .elements import AnnotatingElement, Element
from .features import Feature
from .types import Structure


class Metaclass(Structure):
    """A Structure used to type MetadataFeatures (KerML 8.3.4.12.2)."""

    kind = "Metaclass"


class MetadataFeature(AnnotatingElement, Feature):
    """A Feature that annotates elements with metadata (KerML 8.3.4.12.3).

    ``MetadataFeature("m", typed_by=SecurityLevel, about=[part])``.
    """

    kind = "MetadataFeature"

    def __init__(self, name: Optional[str] = None, *, about: Optional[Iterable[Element]] = None,
                 **kwargs):
        super().__init__(name=name, about=about, **kwargs)

    @property
    def metaclass(self) -> Optional[Metaclass]:
        """The first type that is a Metaclass (spec ``metaclass``)."""
        return next((t for t in self.types if isinstance(t, Metaclass)), None)


def annotate(element: Element, metadata: MetadataFeature) -> MetadataFeature:
    """Annotate `element` with `metadata`, owned by `element`.

    A namespace owns it through an ``OwningMembership``; any other element
    through an owned ``Annotation`` (as :meth:`Element.add_annotation` does).
    """
    from .namespaces import Namespace, OwningMembership
    if isinstance(element, Namespace):
        element.own(metadata, membership=OwningMembership)
        return metadata
    element.add_annotation(metadata)
    return metadata


__all__ = ["Metaclass", "MetadataFeature", "annotate"]
