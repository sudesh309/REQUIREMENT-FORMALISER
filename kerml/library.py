"""KerML standard library — minimal subset of the OMG-published library.

Provides primitive scalar types and root classifiers (Anything, Occurrence,
Object, Performance) that user definitions implicitly specialize.
"""
from __future__ import annotations

from .namespaces import Package
from .types import Behavior, Class, Classifier, DataType, Structure


def build_kerml_library() -> Package:
    root = Package(name="KerML")

    base = Package(name="Base"); root.own(base)
    scalars = Package(name="ScalarValues"); root.own(scalars)
    occurrences = Package(name="Occurrences"); root.own(occurrences)
    objects = Package(name="Objects"); root.own(objects)
    performances = Package(name="Performances"); root.own(performances)

    Anything = Classifier(name="Anything", is_abstract=True); base.own(Anything)

    Boolean = DataType(name="Boolean"); scalars.own(Boolean)
    String  = DataType(name="String");  scalars.own(String)
    Integer = DataType(name="Integer"); scalars.own(Integer)
    Real    = DataType(name="Real");    scalars.own(Real)
    Natural = DataType(name="Natural"); scalars.own(Natural)
    for s in (Boolean, String, Integer, Real, Natural):
        s.specialize(Anything)
    Natural.specialize(Integer)
    Integer.specialize(Real)

    Occurrence = Class(name="Occurrence", is_abstract=True); occurrences.own(Occurrence)
    Occurrence.specialize(Anything)

    Object = Structure(name="Object", is_abstract=True); objects.own(Object)
    Object.specialize(Occurrence)

    Performance = Behavior(name="Performance", is_abstract=True); performances.own(Performance)
    Performance.specialize(Occurrence)

    return root


KERML_LIBRARY: Package = build_kerml_library()
