"""SysML v2 definitions and usages (SysML 8.3) on the KerML core.

Each domain concept follows the Definition / Usage pattern: a Definition is
a KerML Classifier and a Usage a KerML Feature typed by definitions. The
supertypes follow the reflective model (``SysML.sysml``): for example an
``ActionDefinition`` is a ``Behavior``, an ``ActionUsage`` a ``Step``, a
``ConnectionUsage`` a ``ConnectorAsUsage`` (so a KerML ``Connector``) and a
``ConstraintDefinition`` a ``Predicate``.

Relationship-valued attributes of the earlier engine are compatibility
properties over the spec structure (ADR 0002 decision 6); each lists its
spec counterpart in its docstring:

=================================================  =============================================
compatibility property                             spec structure
=================================================  =============================================
``ConnectionUsage.ends`` / ``end_contexts``        end features (``EndFeatureMembership``) with a
                                                   ``ReferenceSubsetting`` to the port, through a
                                                   feature chain ``part.port`` for a context
``AllocationUsage.allocate_from`` / ``_to``        the ends of the allocation (a connection)
``TransitionUsage.transition_source`` / ``_target``  the first owned membership / the succession
``trigger_event``, ``trigger``, ``guard``,         ``TransitionFeatureMembership`` of kind trigger
``effect``                                         (``AcceptActionUsage``), guard (``Expression``)
                                                   and effect (``ActionUsage``)
``entry_action``, ``do_action``, ``exit_action``   ``StateSubactionMembership`` owning an action
``subject``, ``actors``, ``stakeholders``          ``SubjectMembership``, ``ActorMembership``,
                                                   ``StakeholderMembership``
``assumed_constraints`` / ``required_constraints``  ``RequirementConstraintMembership``
``req_id`` / ``text``                              ``declared_short_name`` / the ``Documentation``
``ViewUsage.exposed``                              ``MembershipExpose`` / ``NamespaceExpose``
``Usage.featuring_type``                           the owning type, or a ``TypeFeaturing``
=================================================  =============================================

Guard, effect and state action texts are kept as the source text of the
expression or action (a ``TextualRepresentation`` in language ``sysml``)
until Phase 3 evaluates them; Python callables given for them are runtime
only (they are not part of the model and are not saved).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from kerml.behaviors import ParameterMembership, Predicate, Function, Step
from kerml.connectors import Connector, Succession, end_context, end_feature, referenced_feature
from kerml.elements import _EPOCH, Documentation, Element, TextualRepresentation, derived_id
from kerml.expressions import BooleanExpression, Expression
from kerml.features import (
    EndFeatureMembership, Feature, FeatureChaining, FeatureDirection, MultiplicityRange,
    ReferenceSubsetting, TypeFeaturing,
)
from kerml.namespaces import Membership, Namespace, OwningMembership
from kerml.types import Behavior, Class, Classifier, DataType, Structure, Type

from .memberships import (
    ActorMembership, MembershipExpose, NamespaceExpose, RequirementConstraintMembership,
    StakeholderMembership, StateSubactionMembership, SubjectMembership,
    TransitionFeatureMembership, owned_membership,
)

SOURCE_LANGUAGE = "sysml"


def _text_of(e: Optional[Element]) -> Optional[str]:
    """The source text kept on an expression or action (its textual representation)."""
    if e is None:
        return None
    rep = next((r for r in e.textual_representations), None)
    return rep.body if rep is not None else None


def _set_text(e: Element, text: str) -> None:
    rep = next((r for r in e.textual_representations), None)
    if rep is None:
        rep = TextualRepresentation(text, language=SOURCE_LANGUAGE,
                                    element_id=derived_id(e.element_id, "text"))
        e.add_annotation(rep)
    else:
        rep.body = text


# -- Roots ----------------------------------------------------------------

class Definition(Classifier):
    """Root of all SysML v2 definitions."""

    kind = "Definition"

    def __init__(self, name: Optional[str] = None, *, is_variation: bool = False,
                 is_individual: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_variation: bool = is_variation
        # Compatibility: every definition has ``is_individual`` (the spec has it on
        # OccurrenceDefinition).
        self.is_individual: bool = is_individual

    # Convenience: add an owned Usage that becomes a feature of this Definition.
    def own_usage(self, usage: "Usage") -> "Usage":
        self.own(usage)
        return usage


class Usage(Feature):
    """Root of all SysML v2 usages."""

    kind = "Usage"

    def __init__(self, name: Optional[str] = None, *, is_variation: Optional[bool] = None,
                 is_variant: bool = False, is_reference: bool = False, **kwargs):
        portion_kind = kwargs.pop("portion_kind", None)
        is_individual = kwargs.pop("is_individual", None)
        super().__init__(name=name, **kwargs)
        self.is_variation: bool = bool(is_variant if is_variation is None else is_variation)
        # Compatibility: stored (the spec derives isReference from isComposite).
        self.is_reference: bool = is_reference
        if isinstance(self, OccurrenceUsage):
            if portion_kind is not None:
                self.portion_kind = portion_kind
            if is_individual is not None:
                self.is_individual = bool(is_individual)

    @property
    def is_variant(self) -> bool:
        """Compatibility alias of ``is_variation``."""
        return self.is_variation

    @is_variant.setter
    def is_variant(self, value: bool) -> None:
        self.is_variation = bool(value)

    @property
    def definitions(self) -> list[Type]:
        """Spec ``definition``: the types of the usage."""
        return self.types

    @property
    def owning_definition(self) -> Optional["Definition"]:
        t = self.owning_type
        return t if isinstance(t, Definition) else None

    @property
    def owning_usage(self) -> Optional["Usage"]:
        t = self.owning_type
        return t if isinstance(t, Usage) else None

    @property
    def featuring_type(self) -> Optional[Type]:
        """Compatibility: the owning type, else the type of the first owned TypeFeaturing.

        Assigning the owning type (or None) removes the owned type featurings;
        another type becomes the featuring type of a single owned TypeFeaturing.
        """
        ot = self.owning_type
        if ot is not None:
            return ot
        tf = next(iter(self.owned_type_featurings), None)
        return tf.featuring_type if tf is not None else None

    @featuring_type.setter
    def featuring_type(self, value: Optional[Type]) -> None:
        for r in self.owned_type_featurings:
            self.remove_relationship(r)
        if value is not None and value is not self.owning_type:
            self.add_relationship(TypeFeaturing(self, value))


class ReferenceUsage(Usage):
    """A usage that references things rather than composing them (``ref``)."""

    kind = "ReferenceUsage"


# -- Occurrences, items, parts, attributes, ports --------------------------

PORTION_KINDS = ("timeslice", "snapshot")


class OccurrenceDefinition(Definition, Class):
    kind = "OccurrenceDefinition"


class OccurrenceUsage(Usage):
    kind = "OccurrenceUsage"

    def __init__(self, name: Optional[str] = None, **kwargs):
        self._portion_kind: Optional[str] = None
        self.is_individual: bool = False
        super().__init__(name=name, **kwargs)

    @property
    def portion_kind(self) -> Optional[str]:
        """``'timeslice'``, ``'snapshot'`` or None (the earlier ``'none'`` reads as None)."""
        return self._portion_kind

    @portion_kind.setter
    def portion_kind(self, value: Optional[str]) -> None:
        if value in (None, "", "none"):
            self._portion_kind = None
        elif value in PORTION_KINDS:
            self._portion_kind = value
        else:
            raise ValueError(f"portion kind must be one of {list(PORTION_KINDS)} or None, not {value!r}")


class ItemDefinition(OccurrenceDefinition, Structure): kind = "ItemDefinition"
class ItemUsage(OccurrenceUsage):                      kind = "ItemUsage"

class PartDefinition(ItemDefinition): kind = "PartDefinition"
class PartUsage(ItemUsage):           kind = "PartUsage"

class AttributeDefinition(Definition, DataType): kind = "AttributeDefinition"
class AttributeUsage(Usage):                     kind = "AttributeUsage"


class PortDefinition(OccurrenceDefinition, Structure):
    kind = "PortDefinition"
    compat_attributes = ("is_conjugated",)

    def __init__(self, *args, is_conjugated: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._conjugated_flag = bool(is_conjugated)

    @property
    def is_conjugated(self) -> bool:
        """Spec ``isConjugated`` (has an owned conjugator); compatibility: also True when the
        application flagged the port definition as conjugated (assignable)."""
        return self._conjugated_flag or self.owned_conjugator is not None

    @is_conjugated.setter
    def is_conjugated(self, value: bool) -> None:
        self._conjugated_flag = bool(value)


# Port kinds (System Composer): 'data' (directional signals/messages),
# 'physical' (non-directional physical/conserving connections such as power or
# wiring), 'client' / 'server' (software service ports). Which kinds a model
# may use depends on its architecture type (see engine.architecture).
PORT_KINDS: tuple[str, ...] = ("data", "physical", "client", "server")


class PortUsage(OccurrenceUsage):
    kind = "PortUsage"

    def __init__(self, *args, port_kind: str = "data", **kwargs):
        super().__init__(*args, **kwargs)
        self.port_kind = port_kind

    @property
    def port_kind(self) -> str:
        return getattr(self, "_port_kind", "data")

    @port_kind.setter
    def port_kind(self, value: str) -> None:
        if value not in PORT_KINDS:
            raise ValueError(f"port kind must be one of {list(PORT_KINDS)}, not {value!r}")
        self._port_kind = value


# -- Connections (KerML connectors) ----------------------------------------

class ConnectionDefinition(PartDefinition):
    """``connection def`` (the spec also makes it an AssociationStructure)."""

    kind = "ConnectionDefinition"


class InterfaceDefinition(ConnectionDefinition): kind = "InterfaceDefinition"
class AllocationDefinition(ConnectionDefinition): kind = "AllocationDefinition"


class FlowConnectionDefinition(ConnectionDefinition):
    """Application class for flow connection definitions (interchanged as FlowDefinition)."""

    kind = "FlowConnectionDefinition"
    spec_metaclass = "FlowDefinition"

    def __init__(self, *args, payload_type: Optional[Type] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload_type = payload_type


class ConnectorAsUsage(Usage, Connector):
    """A usage that is also a KerML Connector (abstract)."""

    kind = "ConnectorAsUsage"


class ConnectionUsage(ConnectorAsUsage, PartUsage):
    """A connector between features (ports).

    Compatibility: ``ends[i]`` is the connected feature of end ``i`` and
    ``end_contexts[i]`` the sub-component usage through which it is reached
    (None for a boundary port of the composition). In the model each end is
    a ``ReferenceUsage`` owned through an ``EndFeatureMembership``, whose
    ``ReferenceSubsetting`` references the port, or a feature chain
    ``context.port`` when a context is given. ``end_contexts`` reads ``()``
    when no end goes through a context (the application then infers
    contexts from ownership).
    """

    kind = "ConnectionUsage"
    compat_attributes = ("ends", "end_contexts")

    def __init__(self, *args, ends: Optional[list[Feature]] = None,
                 end_contexts: Optional[tuple] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._contexts_hint: tuple = ()
        if ends:
            self._set_ends(list(ends), tuple(end_contexts or ()))
        elif end_contexts:
            self._contexts_hint = tuple(end_contexts)

    def _new_end(self, **kwargs) -> Feature:
        return ReferenceUsage(**kwargs)

    def _end_id(self, i: int) -> str:
        return derived_id(self.element_id, f"end/{i}")

    def _set_ends(self, features: list, contexts: tuple) -> None:
        self.remove_ends()
        use_ctx = len(contexts) == len(features)
        for i, f in enumerate(features):
            via = contexts[i] if use_ctx else None
            self.add_end(f, via=via, element_id=self._end_id(i))
        self._contexts_hint = ()

    def _ends_view(self) -> tuple:
        """``(ends, contexts)`` read from the end features, cached until the model changes."""
        cache = self.__dict__.get("_ends_cache")
        epoch = _EPOCH[0]
        if cache is not None and cache[0] == epoch:
            return cache[1], cache[2]
        features: list = []
        ctxs: list = []
        for r in self._owned_relationships:
            if not isinstance(r, EndFeatureMembership):
                continue
            for end in r._owned_related_elements:
                if not getattr(end, "is_end", False):
                    continue
                ref = next((x._targets[0] for x in end._owned_relationships
                            if isinstance(x, ReferenceSubsetting) and x._sources and x._sources[0] is end
                            and x._targets), None)
                if ref is None:
                    ctxs.append(None)
                    continue
                chain = [x._targets[0] for x in ref._owned_relationships
                         if isinstance(x, FeatureChaining) and x._targets]
                features.append(chain[-1] if chain else ref)
                ctxs.append(chain[-2] if len(chain) >= 2 else None)
        ctxs_t = tuple(ctxs)
        self.__dict__["_ends_cache"] = (epoch, features, ctxs_t)
        return features, ctxs_t

    @property
    def ends(self) -> list:
        return list(self._ends_view()[0])

    @ends.setter
    def ends(self, value: Iterable) -> None:
        features = [f for f in (value or []) if f is not None]
        contexts = self._contexts_hint if len(self._contexts_hint) == len(features) else ()
        if not contexts:
            current = self.end_contexts
            contexts = current if len(current) == len(features) else ()
        self._set_ends(features, contexts)

    @property
    def end_contexts(self) -> tuple:
        features, ctxs = self._ends_view()
        if any(c is not None for c in ctxs):
            return ctxs
        return self._contexts_hint if not ctxs else ()

    @end_contexts.setter
    def end_contexts(self, value: Optional[Iterable]) -> None:
        ctxs = tuple(value or ())
        ends = self.connector_ends
        if ctxs and len(ctxs) != len(ends):
            self._contexts_hint = ctxs
            return
        self._contexts_hint = ()
        for i, end in enumerate(ends):
            feature = end_feature(end)
            ctx = ctxs[i] if ctxs else None
            if feature is not None and end_context(end) is not ctx:
                self.set_end_reference(end, feature, ctx)


class InterfaceUsage(ConnectionUsage): kind = "InterfaceUsage"


class FlowConnectionUsage(ConnectionUsage):
    """Application class for flow connections (interchanged as FlowUsage)."""

    kind = "FlowConnectionUsage"
    spec_metaclass = "FlowUsage"

    def __init__(self, *args, payload_type: Optional[Type] = None,
                 source: Optional[Feature] = None, target: Optional[Feature] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.payload_type = payload_type
        self.flow_source = source
        self.flow_target = target


class AllocationUsage(ConnectionUsage):
    """An allocation; compatibility ``allocate_from`` / ``allocate_to`` are its two ends."""

    kind = "AllocationUsage"
    compat_attributes = ("allocate_from", "allocate_to")

    def __init__(self, *args, allocate_from: Optional[Feature] = None,
                 allocate_to: Optional[Feature] = None, **kwargs):
        super().__init__(*args, **kwargs)
        if allocate_from is not None or allocate_to is not None:
            self._set_pair(allocate_from, allocate_to)

    def _set_pair(self, a, b) -> None:
        self.remove_ends()
        self.add_end(a, element_id=self._end_id(0))
        self.add_end(b, element_id=self._end_id(1))

    def _end(self, i: int):
        ends = self.connector_ends
        return end_feature(ends[i]) if len(ends) > i else None

    @property
    def allocate_from(self) -> Optional[Feature]:
        return self._end(0)

    @allocate_from.setter
    def allocate_from(self, value: Optional[Feature]) -> None:
        self._set_pair(value, self._end(1))

    @property
    def allocate_to(self) -> Optional[Feature]:
        return self._end(1)

    @allocate_to.setter
    def allocate_to(self, value: Optional[Feature]) -> None:
        self._set_pair(self._end(0), value)


# -- Behavior (Action / State) -------------------------------------------

class ActionDefinition(OccurrenceDefinition, Behavior): kind = "ActionDefinition"
class ActionUsage(OccurrenceUsage, Step):               kind = "ActionUsage"


class AcceptActionUsage(ActionUsage):
    """``accept`` action (as far as transition triggers need it): its payload parameter."""

    kind = "AcceptActionUsage"

    @property
    def payload_parameter(self) -> Optional[Feature]:
        return next((m.owned_member_element for m in self.owned_feature_memberships
                     if isinstance(m, ParameterMembership)), None)

    def set_payload(self, name: Optional[str], referenced: Optional[Feature] = None) -> Feature:
        p = self.payload_parameter
        if p is None:
            p = ReferenceUsage(name, direction=FeatureDirection.IN,
                               element_id=derived_id(self.element_id, "payload"))
            self.own(p, membership=ParameterMembership)
        else:
            p.name = name
        if referenced is not None:
            p.reference_subset(referenced, element_id=derived_id(p.element_id, "reference"))
        else:
            p.remove_subsettings()
        return p

    @property
    def receiver_argument(self):
        return None             # `via` receivers come with Phase 4b

    @property
    def payload_argument(self):
        return None


class _RuntimeValues:
    """Mixin keeping Python callables given for actions and guards (runtime only)."""

    def _runtime(self) -> dict:
        d = self.__dict__.get("_runtime_values")
        if d is None:
            d = self.__dict__["_runtime_values"] = {}
        return d

    def _after_clone(self) -> None:
        super()._after_clone()
        if "_runtime_values" in self.__dict__:
            self.__dict__["_runtime_values"] = dict(self.__dict__["_runtime_values"])


class _StateSubactions(_RuntimeValues):
    """``entry_action`` / ``do_action`` / ``exit_action`` over StateSubactionMemberships.

    Compatibility: these read the action's source text (or a Python callable
    given at run time), as the state machine runner and the editors expect;
    :meth:`subaction` returns the spec ``ActionUsage``.
    """

    compat_attributes = ("entry_action", "do_action", "exit_action")

    def subaction(self, kind: str) -> Optional["ActionUsage"]:
        m = owned_membership(self, StateSubactionMembership, state_subaction_kind=kind)
        return m.action if m is not None else None

    def _get_subaction(self, kind: str) -> Any:
        rt = self._runtime()
        if kind in rt:
            return rt[kind]
        return _text_of(self.subaction(kind))

    def _set_subaction(self, kind: str, value: Any) -> None:
        rt = self._runtime()
        rt.pop(kind, None)
        m = owned_membership(self, StateSubactionMembership, state_subaction_kind=kind)
        if value is None or not isinstance(value, str):
            if m is not None:
                self.remove_relationship(m)
            if value is not None:
                rt[kind] = value
            return
        if m is None:
            action = ActionUsage(element_id=derived_id(self.element_id, kind))
            self.own(action, membership=StateSubactionMembership)
            action.owning_relationship.state_subaction_kind = kind
        else:
            action = m.action
        _set_text(action, value)

    @property
    def entry_action(self) -> Any:
        return self._get_subaction("entry")

    @entry_action.setter
    def entry_action(self, value: Any) -> None:
        self._set_subaction("entry", value)

    @property
    def do_action(self) -> Any:
        return self._get_subaction("do")

    @do_action.setter
    def do_action(self, value: Any) -> None:
        self._set_subaction("do", value)

    @property
    def exit_action(self) -> Any:
        return self._get_subaction("exit")

    @exit_action.setter
    def exit_action(self, value: Any) -> None:
        self._set_subaction("exit", value)


class StateDefinition(_StateSubactions, ActionDefinition):
    kind = "StateDefinition"

    def __init__(self, *args, is_parallel: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_parallel = is_parallel


class StateUsage(_StateSubactions, ActionUsage):
    kind = "StateUsage"
    # Application flag (the spec marks final states by a succession to ``done``).
    is_final = False

    def __init__(self, *args, is_parallel: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_parallel = is_parallel


class TransitionUsage(_RuntimeValues, ActionUsage):
    """A transition between states (SysML 8.3.17.9).

    Spec structure: the first owned membership names the ``source`` state, an
    owned ``Succession`` reaches the ``target`` state, and
    ``TransitionFeatureMembership``s own the trigger (``AcceptActionUsage``),
    guard (``Expression``) and effect (``ActionUsage``). The compatibility
    properties ``transition_source``, ``transition_target``, ``trigger_event``
    (the accepted event name), ``trigger``, ``guard`` and ``effect`` read and
    write that structure.
    """

    kind = "TransitionUsage"
    compat_attributes = ("transition_source", "transition_target", "trigger_event", "guard",
                         "effect")

    def __init__(self, name: Optional[str] = None, *,
                 source: Optional[Feature] = None, target: Optional[Feature] = None,
                 trigger: Optional[Feature] = None, guard=None, effect: Any = None,
                 trigger_event: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if source is not None:
            self.transition_source = source
        if target is not None:
            self.transition_target = target
        if trigger_event is not None:
            self.trigger_event = trigger_event
        if trigger is not None:
            self.trigger = trigger
        if guard is not None:
            self.guard = guard
        if effect is not None:
            self.effect = effect

    def _hides_child(self, rel, child) -> bool:
        return isinstance(child, Succession)

    # --- source and target ------------------------------------------------
    def _source_membership(self) -> Optional[Membership]:
        return next((r for r in self._owned_relationships if type(r) is Membership), None)

    @property
    def source(self) -> Optional[Element]:
        """The source state: the member of the first owned membership (spec ``source``)."""
        m = self._source_membership()
        return m.member_element if m is not None else None

    @property
    def transition_source(self) -> Optional[Element]:
        """Compatibility: ``source`` (assignable)."""
        return self.source

    @transition_source.setter
    def transition_source(self, value: Optional[Element]) -> None:
        m = self._source_membership()
        if value is None:
            if m is not None:
                self.remove_relationship(m)
        elif m is not None:
            m.member_element = value
        else:
            self.add_relationship(Membership(self, value, element_id=derived_id(self.element_id, "source")),
                                  index=0)

    @property
    def succession(self) -> Optional[Succession]:
        return next((x for r in self._owned_relationships if isinstance(r, OwningMembership)
                     for x in r._owned_related_elements if isinstance(x, Succession)), None)

    @property
    def target(self) -> Optional[Element]:
        """The target state, reached by the succession's second end (spec ``target``)."""
        s = self.succession
        if s is None:
            return None
        ends = s.connector_ends
        return end_feature(ends[1]) if len(ends) > 1 else None

    @property
    def transition_target(self) -> Optional[Element]:
        """Compatibility: ``target`` (assignable)."""
        return self.target

    @transition_target.setter
    def transition_target(self, value: Optional[Element]) -> None:
        s = self.succession
        if value is None:
            if s is not None:
                s.detach()
            return
        if s is None:
            sid = derived_id(self.element_id, "succession")
            s = Succession(element_id=sid)
            s.add_end(None, element_id=derived_id(sid, "end/0"))
            s.add_end(value, element_id=derived_id(sid, "end/1"))
            self.own(s, membership=OwningMembership)
        else:
            ends = s.connector_ends
            s.set_end_reference(ends[1], value)

    # --- trigger, guard, effect ------------------------------------------------
    def _feature(self, kind: str) -> Optional[Feature]:
        m = owned_membership(self, TransitionFeatureMembership, transition_feature_kind=kind)
        return m.transition_feature if m is not None else None

    def _ensure_feature(self, kind: str, cls: type) -> Feature:
        f = self._feature(kind)
        if f is None:
            f = cls(element_id=derived_id(self.element_id, kind))
            self.own(f, membership=TransitionFeatureMembership)
            f.owning_relationship.transition_feature_kind = kind
        return f

    def _drop_feature(self, kind: str) -> None:
        m = owned_membership(self, TransitionFeatureMembership, transition_feature_kind=kind)
        if m is not None:
            self.remove_relationship(m)

    def _features(self, kind: str) -> list:
        return [r.transition_feature for r in self._owned_relationships
                if isinstance(r, TransitionFeatureMembership) and r.transition_feature_kind == kind]

    @property
    def trigger_actions(self) -> list:
        return self._features("trigger")

    @property
    def guard_expressions(self) -> list:
        return self._features("guard")

    @property
    def effect_actions(self) -> list:
        return self._features("effect")

    @property
    def trigger_event(self) -> Optional[str]:
        """Compatibility: the name of the event the trigger accepts (its payload parameter)."""
        a = self._feature("trigger")
        p = a.payload_parameter if isinstance(a, AcceptActionUsage) else None
        return p.name if p is not None else None

    @trigger_event.setter
    def trigger_event(self, value: Optional[str]) -> None:
        if value is None and self.trigger is None:
            self._drop_feature("trigger")
            return
        a = self._ensure_feature("trigger", AcceptActionUsage)
        p = a.payload_parameter
        a.set_payload(value, referenced=referenced_feature(p) if p is not None else None)

    @property
    def trigger(self) -> Optional[Feature]:
        """Compatibility: the feature the trigger's payload references (if any)."""
        a = self._feature("trigger")
        p = a.payload_parameter if isinstance(a, AcceptActionUsage) else None
        return referenced_feature(p) if p is not None else None

    @trigger.setter
    def trigger(self, value: Optional[Feature]) -> None:
        name = self.trigger_event
        if value is None and name is None:
            self._drop_feature("trigger")
            return
        a = self._ensure_feature("trigger", AcceptActionUsage)
        a.set_payload(name, referenced=value)

    def _get_text_feature(self, kind: str) -> Any:
        rt = self._runtime()
        if kind in rt:
            return rt[kind]
        return _text_of(self._feature(kind))

    def _set_text_feature(self, kind: str, cls: type, value: Any) -> None:
        rt = self._runtime()
        rt.pop(kind, None)
        if value is None or not isinstance(value, str):
            self._drop_feature(kind)
            if value is not None:
                rt[kind] = value
            return
        _set_text(self._ensure_feature(kind, cls), value)

    @property
    def guard(self) -> Any:
        """Compatibility: the guard's source text (or a callable given at run time)."""
        return self._get_text_feature("guard")

    @guard.setter
    def guard(self, value: Any) -> None:
        self._set_text_feature("guard", Expression, value)

    @property
    def effect(self) -> Any:
        """Compatibility: the effect's source text (or a callable given at run time)."""
        return self._get_text_feature("effect")

    @effect.setter
    def effect(self, value: Any) -> None:
        self._set_text_feature("effect", ActionUsage, value)


class CalculationDefinition(ActionDefinition, Function): kind = "CalculationDefinition"
class CalculationUsage(ActionUsage, Expression):         kind = "CalculationUsage"

class ConstraintDefinition(OccurrenceDefinition, Predicate): kind = "ConstraintDefinition"


class ConstraintUsage(OccurrenceUsage, BooleanExpression):
    kind = "ConstraintUsage"

    def __init__(self, *args, expression=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expression = expression


# -- Requirements / Cases / Analysis -------------------------------------

def _referencing(cls: type, target: Element, owner: Element, role: str) -> Feature:
    """A new parameter usage that references `target` (a feature) or is typed by it (a type)."""
    eid = derived_id(owner.element_id, role)
    p = cls(element_id=eid)
    if isinstance(target, Feature):
        p.reference_subset(target, element_id=derived_id(eid, "reference"))
    elif isinstance(target, Type):
        p.add_type(target, element_id=derived_id(eid, "typing"))
    else:
        p._referent = target            # neither a feature nor a type: kept at run time only
    return p


def _referent(p: Optional[Element]) -> Optional[Element]:
    """What a subject / actor / stakeholder parameter stands for (see :func:`_referencing`)."""
    if p is None:
        return None
    other = p.__dict__.get("_referent")
    if other is not None:
        return other
    ref = referenced_feature(p) if isinstance(p, Feature) else None
    if ref is not None:
        return ref
    typings = p.owned_typings if isinstance(p, Feature) else []
    return typings[0].type if typings else p


class _SubjectParameter:
    """Mixin: the subject parameter of a requirement or case (``SubjectMembership``)."""

    @property
    def subject_parameter(self) -> Optional[Feature]:
        m = owned_membership(self, SubjectMembership)
        return m.owned_subject_parameter if m is not None else None

    @property
    def subject(self) -> Optional[Element]:
        """Compatibility: the element the subject parameter references (or is typed by)."""
        return _referent(self.subject_parameter)

    @subject.setter
    def subject(self, value: Optional[Element]) -> None:
        m = owned_membership(self, SubjectMembership)
        if m is not None:
            self.remove_relationship(m)
        if value is not None:
            self.own(_referencing(ReferenceUsage, value, self, "subject"), membership=SubjectMembership)

    def _parameters(self, cls: type) -> list:
        return [r.owned_member_element for r in self._owned_relationships if isinstance(r, cls)]

    @property
    def actor_parameters(self) -> list:
        return self._parameters(ActorMembership)

    @property
    def actors(self) -> list:
        """Compatibility: what the actor parameters reference (assign a list to replace them)."""
        return [_referent(p) for p in self.actor_parameters]

    @actors.setter
    def actors(self, value: Iterable[Element]) -> None:
        self._set_parameters(ActorMembership, "actor", value)

    def add_actor(self, element: Element) -> Feature:
        return self._add_parameter(ActorMembership, "actor", element)

    def _set_parameters(self, cls: type, role: str, value: Iterable[Element]) -> None:
        for r in [r for r in self._owned_relationships if isinstance(r, cls)]:
            self.remove_relationship(r)
        for e in value or ():
            self._add_parameter(cls, role, e)

    def _add_parameter(self, cls: type, role: str, element: Element) -> Feature:
        n = sum(1 for r in self._owned_relationships if isinstance(r, cls))
        p = _referencing(PartUsage, element, self, f"{role}/{n}")
        self.own(p, membership=cls)
        return p


class _RequirementParts(_SubjectParameter):
    """Mixin: requirement structure (SysML 8.3.20) with its compatibility properties."""

    compat_attributes = ("req_id", "text")

    # --- id and text ------------------------------------------------------
    @property
    def req_id(self) -> Optional[str]:
        """Spec ``reqId``, which is the ``declared_short_name``."""
        return self._declared_short_name

    @req_id.setter
    def req_id(self, value: Optional[str]) -> None:
        self._declared_short_name = value

    def _text_doc(self) -> Optional[Documentation]:
        d = self.__dict__.get("_text_documentation")
        return d if d is not None and d.owner is self else None

    @property
    def texts(self) -> list[str]:
        """Spec ``text``: the bodies of the requirement's documentation."""
        return [d.body for d in self.documentation]

    @property
    def text(self) -> Optional[str]:
        """Compatibility: the requirement text, the body of its text Documentation."""
        d = self._text_doc()
        return d.body if d is not None else None

    @text.setter
    def text(self, value: Optional[str]) -> None:
        d = self._text_doc()
        if value is None:
            if d is not None:
                d.detach()
            self.__dict__["_text_documentation"] = None
            return
        if d is None:
            d = Documentation(str(value), element_id=derived_id(self.element_id, "text"))
            self.add_relationship(OwningMembership(self, d), index=0)
            self.__dict__["_text_documentation"] = d
        else:
            d.body = str(value)

    def adopt_text_documentation(self, doc: Documentation) -> None:
        """Make an owned Documentation the one that holds the requirement text (loaders)."""
        if doc.owner is self:
            self.__dict__["_text_documentation"] = doc

    @property
    def annotations(self) -> list:
        """Compatibility: as for any element, but without the Documentation holding ``text``."""
        d = self._text_doc()
        return [a for a in Element.annotations.fget(self) if a is not d]

    @annotations.setter
    def annotations(self, value: Iterable[Element]) -> None:
        d = self._text_doc()
        wanted = list(value)
        if d is not None and not any(a is d for a in wanted):
            wanted.insert(0, d)
        Element.annotations.fset(self, wanted)

    # --- stakeholders and constraints ---------------------------------------
    @property
    def stakeholder_parameters(self) -> list:
        return self._parameters(StakeholderMembership)

    @property
    def stakeholders(self) -> list:
        """Compatibility: what the stakeholder parameters reference (assign a list to replace)."""
        return [_referent(p) for p in self.stakeholder_parameters]

    @stakeholders.setter
    def stakeholders(self, value: Iterable[Element]) -> None:
        self._set_parameters(StakeholderMembership, "stakeholder", value)

    def add_stakeholder(self, element: Element) -> Feature:
        return self._add_parameter(StakeholderMembership, "stakeholder", element)

    def _constraints(self, kind: str) -> list:
        return [r.owned_constraint for r in self._owned_relationships
                if isinstance(r, RequirementConstraintMembership)
                and r.requirement_constraint_kind == kind]

    def _set_constraints(self, kind: str, value: Iterable[Element]) -> None:
        for r in [r for r in self._owned_relationships if isinstance(r, RequirementConstraintMembership)
                  and r.requirement_constraint_kind == kind]:
            self.remove_relationship(r)
        for c in value or ():
            self.add_constraint(c, kind)

    def add_constraint(self, constraint: "ConstraintUsage", kind: str = "requirement") -> "ConstraintUsage":
        """``assume`` (kind 'assumption') or ``require`` a constraint: an unowned one becomes the
        owned constraint, one owned elsewhere is referenced by a new constraint usage."""
        if constraint.owner is None and constraint.owning_relationship is None:
            owned = constraint
        else:
            n = len(self._constraints(kind))
            owned = ConstraintUsage(element_id=derived_id(self.element_id, f"{kind}/{n}"))
            owned.reference_subset(constraint)
        self.own(owned, membership=RequirementConstraintMembership)
        owned.owning_relationship.requirement_constraint_kind = kind
        return owned

    @property
    def assumed_constraints(self) -> list:
        """Spec ``assumedConstraint`` (assignable: see :meth:`add_constraint`)."""
        return self._constraints("assumption")

    @assumed_constraints.setter
    def assumed_constraints(self, value: Iterable[Element]) -> None:
        self._set_constraints("assumption", value)

    @property
    def required_constraints(self) -> list:
        """Spec ``requiredConstraint`` (assignable: see :meth:`add_constraint`)."""
        return self._constraints("requirement")

    @required_constraints.setter
    def required_constraints(self, value: Iterable[Element]) -> None:
        self._set_constraints("requirement", value)


class RequirementDefinition(_RequirementParts, ConstraintDefinition):
    kind = "RequirementDefinition"

    def __init__(self, name: Optional[str] = None, *, req_id: Optional[str] = None,
                 text: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if req_id is not None:
            self.req_id = req_id
        if text is not None:
            self.text = text
        self.satisfied_by: list[Feature] = []
        self.verified_by: list[Feature] = []


class RequirementUsage(_RequirementParts, ConstraintUsage):
    kind = "RequirementUsage"

    def __init__(self, *args, req_id: Optional[str] = None, text: Optional[str] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        if req_id is not None:
            self.req_id = req_id
        if text is not None:
            self.text = text
        self.satisfied_by: list[Feature] = []
        self.verified_by: list[Feature] = []


class CaseDefinition(_SubjectParameter, CalculationDefinition):
    kind = "CaseDefinition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Application attribute (ObjectiveMembership comes with Phase 4c).
        self.objective: Optional[Feature] = None


class CaseUsage(_SubjectParameter, CalculationUsage): kind = "CaseUsage"

class UseCaseDefinition(CaseDefinition):  kind = "UseCaseDefinition"
class UseCaseUsage(CaseUsage):            kind = "UseCaseUsage"

class AnalysisCaseDefinition(CaseDefinition): kind = "AnalysisCaseDefinition"
class AnalysisCaseUsage(CaseUsage):           kind = "AnalysisCaseUsage"


class VerificationCaseDefinition(CaseDefinition):
    kind = "VerificationCaseDefinition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.verifies: list[RequirementUsage] = []


class VerificationCaseUsage(CaseUsage): kind = "VerificationCaseUsage"


# -- Allocation / Views / Metadata / Concern -----------------------------

class ViewDefinition(PartDefinition): kind = "ViewDefinition"


class ViewUsage(PartUsage):
    """A view; compatibility ``exposed`` lists what its Expose relationships expose."""

    kind = "ViewUsage"
    compat_attributes = ("exposed",)

    @property
    def owned_exposes(self) -> list:
        from .memberships import Expose
        return [r for r in self._owned_relationships if isinstance(r, Expose)]

    @property
    def exposed_elements(self) -> list[Element]:
        out: list[Element] = []
        for x in self.owned_exposes:
            for m in x.imported_memberships(()):
                e = m.member_element
                if e is not None and not any(e is y for y in out):
                    out.append(e)
        return out

    def expose(self, element: Element, *, recursive: bool = False):
        """Expose `element`: its membership (MembershipExpose), or a namespace's members
        (NamespaceExpose) when it has no owning membership."""
        m = element.owning_relationship
        if isinstance(m, Membership):
            x = MembershipExpose(self, m, recursive=recursive)
        else:
            x = NamespaceExpose(self, element, recursive=recursive)
        self.add_relationship(x)
        return x

    @property
    def exposed(self) -> list[Element]:
        """Compatibility: the elements exposed one by one (assign a list to replace them)."""
        out = []
        for x in self.owned_exposes:
            t = x.imported_element
            if t is not None:
                out.append(t)
        return out

    @exposed.setter
    def exposed(self, value: Iterable[Element]) -> None:
        for x in self.owned_exposes:
            self.remove_relationship(x)
        for e in value or ():
            self.expose(e)


class ViewpointDefinition(RequirementDefinition):
    kind = "ViewpointDefinition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.concerns: list[str] = []


class ViewpointUsage(RequirementUsage): kind = "ViewpointUsage"

class ConcernDefinition(RequirementDefinition): kind = "ConcernDefinition"
class ConcernUsage(RequirementUsage):           kind = "ConcernUsage"

class MetadataDefinition(ItemDefinition): kind = "MetadataDefinition"
class MetadataUsage(ItemUsage):           kind = "MetadataUsage"


class ParameterDefinition(AttributeDefinition):
    """Application class: a typed input/output slot of a behavior (an attribute definition)."""
    kind = "ParameterDefinition"
    spec_metaclass = "AttributeDefinition"


class ParameterUsage(AttributeUsage):
    """Application class: a directional, typed attribute usage on Action / Calculation /
    Constraint / Requirement definitions and usages (interchanged as an AttributeUsage owned
    through a ParameterMembership).

    `parameter_kind` is one of: 'in', 'out', 'inout', 'return'.
    """
    kind = "ParameterUsage"
    spec_metaclass = "AttributeUsage"

    def __init__(self, name: Optional[str] = None, *,
                 parameter_kind: str = "in",
                 typed_by: Optional[Type] = None,
                 default_expression=None,
                 **kwargs):
        dir_map = {"in":     FeatureDirection.IN,
                   "out":    FeatureDirection.OUT,
                   "inout":  FeatureDirection.INOUT,
                   "return": FeatureDirection.OUT}
        kwargs.setdefault("direction", dir_map.get(parameter_kind, FeatureDirection.IN))
        super().__init__(name=name, typed_by=typed_by, **kwargs)
        self.parameter_kind = parameter_kind  # 'in' | 'out' | 'inout' | 'return'
        self.default_expression = default_expression


class EnumerationDefinition(AttributeDefinition):
    kind = "EnumerationDefinition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.literals: list["EnumerationUsage"] = []


class EnumerationUsage(AttributeUsage): kind = "EnumerationUsage"


# -- Application predicates ----------------------------------------------
#
# In the spec a ConnectionUsage (and so every connector, interface and allocation usage)
# and a ViewUsage are PartUsages, and connection and view definitions are PartDefinitions.
# The application's "component" and "architecture" are the other part usages and
# definitions; these predicates say so, and the application tests with them instead of
# ``isinstance(e, PartUsage)`` / ``isinstance(e, PartDefinition)``.

_NOT_COMPONENT_USAGES: tuple = (ConnectorAsUsage, ViewUsage)
_NOT_COMPONENT_DEFINITIONS: tuple = (ConnectionDefinition, ViewDefinition)


for _cls in (PartUsage, PartDefinition):
    _cls._app_part = True
for _cls in _NOT_COMPONENT_USAGES + _NOT_COMPONENT_DEFINITIONS:
    _cls._app_part = False


def is_part_usage(e: Any) -> bool:
    """A PartUsage that is not a connection or view usage (the application's component)."""
    return getattr(e, "_app_part", False) and isinstance(e, PartUsage)


def is_part_definition(e: Any) -> bool:
    """A PartDefinition that is not a connection or view definition (architecture, block)."""
    return getattr(e, "_app_part", False) and isinstance(e, PartDefinition)
