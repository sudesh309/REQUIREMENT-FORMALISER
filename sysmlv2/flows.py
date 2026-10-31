"""Flows and connectors as usages (SysML 8.3.13, 8.3.16).

* :class:`FlowDefinition` is an ActionDefinition that is also a KerML
  Interaction; :class:`FlowUsage` a usage that is also a KerML Flow (so it has
  flow ends, a payload and source output / target input features, see
  :mod:`kerml.interactions`); :class:`SuccessionFlowUsage` is also a
  succession.
* :class:`BindingConnectorAsUsage` (``bind a = b``) and
  :class:`SuccessionAsUsage` (``first a then b``) are KerML binding connectors
  and successions used as SysML usages.

The application's ``FlowConnectionDefinition`` / ``FlowConnectionUsage``
(:mod:`sysmlv2.definitions`) predate these classes and keep their own kinds.
"""
from __future__ import annotations

from kerml.connectors import BindingConnector, Succession
from kerml.interactions import Flow, Interaction, SuccessionFlow

from .definitions import ActionDefinition, ActionUsage, Usage


class FlowDefinition(Interaction, ActionDefinition):
    """Defines flows between the usages that are its ends (SysML 8.3.16.2)."""

    kind = "FlowDefinition"


# TODO(A3 merge): add the ConnectorAsUsage base (spec supertypes: ConnectorAsUsage, Flow,
# ActionUsage).
class FlowUsage(Flow, ActionUsage):
    """A usage of a FlowDefinition: a Flow and an ActionUsage (SysML 8.3.16.3)."""

    kind = "FlowUsage"


class SuccessionFlowUsage(SuccessionFlow, FlowUsage):
    """A FlowUsage that is also a SuccessionFlow (``succession flow``, SysML 8.3.16.4)."""

    kind = "SuccessionFlowUsage"


# TODO(A3 merge): replace the Usage base by ConnectorAsUsage (spec supertypes: BindingConnector,
# ConnectorAsUsage).
class BindingConnectorAsUsage(BindingConnector, Usage):
    """A BindingConnector used as a Usage (``bind a = b``, SysML 8.3.13.2)."""

    kind = "BindingConnectorAsUsage"


# TODO(A3 merge): replace the Usage base by ConnectorAsUsage (spec supertypes: ConnectorAsUsage,
# Succession).
class SuccessionAsUsage(Usage, Succession):
    """A Succession used as a Usage (``first a then b``, SysML 8.3.13.6)."""

    kind = "SuccessionAsUsage"


__all__ = ["FlowDefinition", "FlowUsage", "SuccessionFlowUsage", "BindingConnectorAsUsage",
           "SuccessionAsUsage"]
