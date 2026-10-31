"""Association structures and interactions (KerML 8.3.4.4.3, 8.3.4.9): flows between features.

* :class:`AssociationStructure` is an Association that is also a Structure
  (link objects); :class:`Interaction` an Association that is also a Behavior.
* A :class:`Flow` is a Connector and a Step that transfers values from the
  feature at its source end to the feature at its target end. Its ends are
  :class:`FlowEnd` features; each one references the related feature (as a
  connector end does, see :mod:`kerml.connectors`) and owns one feature that
  redefines the output (source end) or input (target end) feature of the
  related feature. Its optional :class:`PayloadFeature` gives the type of what
  is transferred. :class:`SuccessionFlow` also orders its source before its
  target.

Builders: :meth:`Flow.add_flow_end` and :meth:`Flow.set_payload`; every
derived property is computed from the owned structure.
"""
from __future__ import annotations

from typing import Optional

from .behaviors import Step
from .connectors import Connector, Succession
from .features import Feature
from .types import Association, Behavior, Classifier, Structure, Type


class AssociationStructure(Association, Structure):
    """An Association that is also a Structure: it classifies link objects (KerML 8.3.4.4.3)."""

    kind = "AssociationStructure"


class Interaction(Association, Behavior):
    """A Behavior that is also an Association (KerML 8.3.4.9.4): it types Flows."""

    kind = "Interaction"


class FlowEnd(Feature):
    """A connector end of a Flow (KerML 8.3.4.9.3).

    It is an end feature (``is_end`` defaults to true) and owns exactly one
    feature, which redefines the output or input feature of the related
    feature of its end.
    """

    kind = "FlowEnd"

    def __init__(self, name: Optional[str] = None, **kwargs):
        kwargs.setdefault("is_end", True)
        super().__init__(name=name, **kwargs)


class PayloadFeature(Feature):
    """The owned feature of a Flow that identifies what the flow carries (KerML 8.3.4.9.5)."""

    kind = "PayloadFeature"


class Flow(Connector, Step):
    """A Step that transfers values from one Feature to another (KerML 8.3.4.9.2).

    ``flow_ends`` are the connector ends that are FlowEnds; the first one is the
    source, the second the target. ``source_output_feature`` and
    ``target_input_feature`` are the first owned features of those ends.
    """

    kind = "Flow"

    # --- ends ------------------------------------------------------------------
    def _new_end(self, **kwargs) -> Feature:
        return FlowEnd(**kwargs)

    def add_flow_end(self, feature: Optional[Feature] = None, io_feature: Optional[Feature] = None, *,
                     via: Optional[Feature] = None, name: Optional[str] = None,
                     element_id: Optional[str] = None) -> FlowEnd:
        """Add a FlowEnd related to `feature` (through ``via.feature`` when `via` is given).

        With `io_feature` (the output feature of a source, the input feature of a
        target) the end owns a feature that redefines it, as ``flow a.x to b.y``
        does for ``x`` and ``y``.
        """
        end = self.add_end(feature, via=via, name=name, element_id=element_id)
        if io_feature is not None:
            inner = Feature()
            inner.redefine(io_feature)
            end.own(inner)
        return end  # type: ignore[return-value]

    @property
    def flow_ends(self) -> list[FlowEnd]:
        """The connector ends that are FlowEnds (spec ``flowEnd``)."""
        return [e for e in self.connector_ends if isinstance(e, FlowEnd)]

    @property
    def source_output_feature(self) -> Optional[Feature]:
        """The first owned feature of the first connector end (spec ``sourceOutputFeature``)."""
        return self._end_feature(0)

    @property
    def target_input_feature(self) -> Optional[Feature]:
        """The first owned feature of the second connector end (spec ``targetInputFeature``)."""
        return self._end_feature(1)

    def _end_feature(self, index: int) -> Optional[Feature]:
        ends = self.connector_ends
        if len(ends) <= index:
            return None
        owned = ends[index].owned_features
        return owned[0] if owned else None

    # --- payload ---------------------------------------------------------------
    def set_payload(self, type_: Optional[Type] = None, *, name: Optional[str] = None) -> PayloadFeature:
        """Give the flow a PayloadFeature (typed by `type_`), replacing an existing one."""
        old = self.payload_feature
        if old is not None:
            old.detach()
        payload = PayloadFeature(name, typed_by=type_)
        self.own(payload)
        return payload

    @property
    def payload_feature(self) -> Optional[PayloadFeature]:
        """The owned feature that is a PayloadFeature, if any (spec ``payloadFeature``)."""
        return next((f for f in self.owned_features if isinstance(f, PayloadFeature)), None)

    @property
    def payload_types(self) -> list[Classifier]:
        """The types of the payload feature (spec ``payloadType``)."""
        p = self.payload_feature
        return list(p.types) if p is not None else []

    # --- typing ------------------------------------------------------------------
    @property
    def interactions(self) -> list[Interaction]:
        """The Interactions that type this flow (spec ``interaction``)."""
        return [t for t in self.types if isinstance(t, Interaction)]


class SuccessionFlow(Succession, Flow):
    """A Flow that is also a Succession: the transfer happens after its source and before its
    target (KerML 8.3.4.9.6)."""

    kind = "SuccessionFlow"


__all__ = ["AssociationStructure", "Interaction", "FlowEnd", "PayloadFeature", "Flow",
           "SuccessionFlow"]
