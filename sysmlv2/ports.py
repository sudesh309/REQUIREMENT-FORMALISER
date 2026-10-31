"""Port conjugation (SysML 8.3.12): ConjugatedPortDefinition, PortConjugation, ConjugatedPortTyping.

Every PortDefinition (other than a conjugated one) has one
:class:`ConjugatedPortDefinition`, an owned member named ``~`` + its name,
whose ``owned_port_conjugator`` is a :class:`PortConjugation` to the original
port definition: it has the original's features with ``in`` and ``out``
swapped. A port typed by it (``port p : ~P``) is typed through a
:class:`ConjugatedPortTyping`.

:func:`conjugated_port_definition` returns (creating on demand) the conjugate
of a port definition; :func:`type_by_conjugate` types a port usage by it.
The derived ``PortDefinition.conjugated_port_definition`` is installed by
:mod:`sysmlv2.derived`.
"""
from __future__ import annotations

from typing import Optional

from kerml.features import Feature, FeatureTyping
from kerml.types import Conjugation

from .definitions import PortDefinition


class ConjugatedPortDefinition(PortDefinition):
    """The conjugate of its owning PortDefinition (SysML 8.3.12.2).

    Its effective name is ``~`` followed by the original's name (unless it
    declares one).
    """

    kind = "ConjugatedPortDefinition"

    @property
    def original_port_definition(self) -> Optional[PortDefinition]:
        """The owning namespace, a PortDefinition (spec ``originalPortDefinition``)."""
        ns = self.owning_namespace
        return ns if isinstance(ns, PortDefinition) else None

    @property
    def owned_port_conjugator(self) -> Optional["PortConjugation"]:
        """The owned conjugator, a PortConjugation (spec ``ownedPortConjugator``)."""
        c = self.owned_conjugator
        return c if isinstance(c, PortConjugation) else None

    def effective_name(self) -> Optional[str]:
        if self._declared_name is not None:
            return self._declared_name
        original = self.original_port_definition
        name = original.name if original is not None else None
        return None if name is None else "~" + name

    @property
    def name(self) -> Optional[str]:
        """The declared name, else ``~`` + the original's name (spec ``effectiveName()``)."""
        return self.effective_name()

    @name.setter
    def name(self, value: Optional[str]) -> None:
        self._declared_name = value


class PortConjugation(Conjugation):
    """Conjugates a ConjugatedPortDefinition to its original PortDefinition (SysML 8.3.12.4)."""

    kind = "PortConjugation"

    @property
    def original_port_definition(self) -> Optional[PortDefinition]:
        """The PortDefinition being conjugated (spec ``originalPortDefinition``, redefines
        ``originalType``; assignable)."""
        t = self.original_type
        return t if isinstance(t, PortDefinition) else None

    @original_port_definition.setter
    def original_port_definition(self, value: Optional[PortDefinition]) -> None:
        self.target = value

    @property
    def conjugated_port_definition(self) -> Optional[ConjugatedPortDefinition]:
        """The owning type, a ConjugatedPortDefinition (spec ``conjugatedPortDefinition``)."""
        o = self.owning_type
        return o if isinstance(o, ConjugatedPortDefinition) else None


class ConjugatedPortTyping(FeatureTyping):
    """Types a feature by a ConjugatedPortDefinition (``: ~P``, SysML 8.3.12.3)."""

    kind = "ConjugatedPortTyping"

    @property
    def conjugated_port_definition(self) -> Optional[ConjugatedPortDefinition]:
        """The type, a ConjugatedPortDefinition (spec ``conjugatedPortDefinition``, redefines
        ``type``; assignable)."""
        t = self.type
        return t if isinstance(t, ConjugatedPortDefinition) else None

    @conjugated_port_definition.setter
    def conjugated_port_definition(self, value: Optional[ConjugatedPortDefinition]) -> None:
        self.target = value

    @property
    def port_definition(self) -> Optional[PortDefinition]:
        """The original port definition of the conjugated one (spec ``portDefinition``)."""
        c = self.conjugated_port_definition
        return c.original_port_definition if c is not None else None


def conjugated_port_definition(port: PortDefinition, *, create: bool = True
                               ) -> Optional[ConjugatedPortDefinition]:
    """The ConjugatedPortDefinition owned by `port`, created with its PortConjugation if missing."""
    if isinstance(port, ConjugatedPortDefinition):
        raise ValueError("a ConjugatedPortDefinition has no conjugated port definition")
    found = next((m for m in port.owned_members if isinstance(m, ConjugatedPortDefinition)), None)
    if found is not None or not create:
        return found
    cpd = ConjugatedPortDefinition()
    port.own(cpd)
    cpd.add_relationship(PortConjugation(cpd, port))
    return cpd


def type_by_conjugate(feature: Feature, port: PortDefinition) -> ConjugatedPortTyping:
    """Type `feature` by the conjugate of `port` (``port p : ~P``)."""
    typing = ConjugatedPortTyping(feature, conjugated_port_definition(port))
    feature.add_relationship(typing)
    return typing


__all__ = ["ConjugatedPortDefinition", "PortConjugation", "ConjugatedPortTyping",
           "conjugated_port_definition", "type_by_conjugate"]
