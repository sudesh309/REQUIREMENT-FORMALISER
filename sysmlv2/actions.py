"""Action usages, control nodes and performed occurrences (SysML 8.3.9, 8.3.17, 8.3.18).

* :class:`EventOccurrenceUsage` references an occurrence (``event e;``) and
  :class:`PerformActionUsage` (``perform a;``) and :class:`ExhibitStateUsage`
  (``exhibit s;``) specialize it: the performed or exhibited usage is the
  feature target of the usage's owned ReferenceSubsetting, or the usage itself
  when it has none.
* :class:`SendActionUsage`, :class:`AssignmentActionUsage`,
  :class:`TerminateActionUsage` and :class:`ForLoopActionUsage` take their
  arguments from the FeatureValues of their owned input parameters
  (:func:`argument`); :class:`IfActionUsage` and the loops take their condition
  and body as the owned input parameters themselves (:func:`input_parameter`).
* :class:`ControlNode` and its decision, fork, join and merge nodes.

The helpers :func:`input_parameters`, :func:`input_parameter` and
:func:`argument` are the spec operations of ``ActionUsage``
(``inputParameters()``, ``inputParameter(i)``, ``argument(i)``; ``i`` counts
from 1). Constructor keywords build the owned structure for small models;
execution is Phase 3.
"""
from __future__ import annotations

from typing import Any, Optional

from kerml.derived import class_for
from kerml.expressions import Expression
from kerml.features import Feature, FeatureDirection
from kerml.metadata import MetadataFeature
from kerml.operator_expressions import set_value_expression, value_expression
from kerml.types import FeatureMembership

from .definitions import ActionUsage, OccurrenceUsage, StateUsage, Usage


# ---------------------------------------------------------------------------
# ActionUsage operations (spec 8.3.17.4) and Usage::referencedFeatureTarget()
# ---------------------------------------------------------------------------

def input_parameters(action: ActionUsage) -> list[Feature]:
    """The owned input parameters of `action` (spec ``inputParameters()``: inputs it owns)."""
    return [f for f in action.inputs if f.owner is action]


def input_parameter(action: ActionUsage, i: int) -> Optional[Feature]:
    """The `i`-th (from 1) owned input parameter, or None (spec ``inputParameter(i)``)."""
    params = input_parameters(action)
    return params[i - 1] if 1 <= i <= len(params) else None


def argument(action: ActionUsage, i: int) -> Optional[Expression]:
    """The value Expression of the `i`-th owned input parameter, or None (spec ``argument(i)``)."""
    p = input_parameter(action, i)
    return value_expression(p) if p is not None else None


def referenced_feature_target(usage: Feature) -> Optional[Feature]:
    """The feature target of the feature referenced by the owned ReferenceSubsetting, or None
    (spec ``Usage::referencedFeatureTarget()``)."""
    rs = usage.owned_reference_subsetting
    f = rs.referenced_feature if rs is not None else None
    return f.feature_target if isinstance(f, Feature) else None


def _new_parameter(name: Optional[str] = None) -> Feature:
    # Action parameters are ReferenceUsages in the spec.
    # TODO(A3 merge): ReferenceUsage always exists then; drop the Usage fallback.
    cls = class_for("ReferenceUsage")
    if cls is not None:
        return cls(name)
    return Usage(name, is_reference=True)


def add_parameter(action: ActionUsage, parameter: Optional[Feature] = None, *,
                  value: Any = None, name: Optional[str] = None) -> Feature:
    """Own an input parameter of `action` (a new reference usage when `parameter` is None).

    With `value` (an Expression or a Python literal) the parameter is bound to it
    through a FeatureValue, which makes it an argument of the action.
    """
    p = parameter if parameter is not None else _new_parameter(name)
    p.direction = FeatureDirection.IN
    action.own(p)
    if value is not None:
        set_value_expression(p, value)
    return p


def _of(value: Any, cls: type) -> Any:
    return value if isinstance(value, cls) else None


# ---------------------------------------------------------------------------
# Event occurrences and performed actions
# ---------------------------------------------------------------------------

class EventOccurrenceUsage(OccurrenceUsage):
    """A reference to an occurrence that is an event of its owner (SysML 8.3.9.2).

    ``event_occurrence=`` references the occurrence (an owned ReferenceSubsetting).
    """

    kind = "EventOccurrenceUsage"

    def __init__(self, name: Optional[str] = None, *, event_occurrence: Optional[Feature] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        if event_occurrence is not None:
            self.reference_subset(event_occurrence)

    @property
    def is_reference(self) -> bool:
        """Always true: an EventOccurrenceUsage is referential (spec ``isReference``).

        Assignments are ignored (``Usage.__init__`` assigns it).
        """
        return True

    @is_reference.setter
    def is_reference(self, value: bool) -> None:
        pass

    @property
    def event_occurrence(self) -> Optional[OccurrenceUsage]:
        """The referenced occurrence: the feature target of the owned ReferenceSubsetting if it is an
        OccurrenceUsage (None if it is not), else this usage itself (spec ``eventOccurrence``)."""
        target = referenced_feature_target(self)
        if target is None:
            return self
        return _of(target, OccurrenceUsage)


class PerformActionUsage(ActionUsage, EventOccurrenceUsage):
    """``perform a;``: performs an action usage (SysML 8.3.17.14)."""

    kind = "PerformActionUsage"

    def __init__(self, name: Optional[str] = None, *, performed_action: Optional[Feature] = None,
                 **kwargs):
        super().__init__(name=name, event_occurrence=performed_action, **kwargs)

    @property
    def performed_action(self) -> Optional[ActionUsage]:
        """The event occurrence, if it is an ActionUsage (spec ``performedAction``)."""
        return _of(self.event_occurrence, ActionUsage)


class ExhibitStateUsage(StateUsage, PerformActionUsage):
    """``exhibit s;``: exhibits a state usage (SysML 8.3.18.2)."""

    kind = "ExhibitStateUsage"

    def __init__(self, name: Optional[str] = None, *, exhibited_state: Optional[Feature] = None,
                 **kwargs):
        super().__init__(name=name, performed_action=exhibited_state, **kwargs)

    @property
    def exhibited_state(self) -> Optional[StateUsage]:
        """The performed action, if it is a StateUsage (spec ``exhibitedState``)."""
        return _of(self.performed_action, StateUsage)


# ---------------------------------------------------------------------------
# Actions with arguments
# ---------------------------------------------------------------------------

class SendActionUsage(ActionUsage):
    """``send payload via sender to receiver`` (SysML 8.3.17.15).

    Arguments 1, 2 and 3 are the payload, sender and receiver. Giving any of
    the keywords creates the three parameters, bound to the values given.
    """

    kind = "SendActionUsage"

    def __init__(self, name: Optional[str] = None, *, payload: Any = None, sender: Any = None,
                 receiver: Any = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if payload is not None or sender is not None or receiver is not None:
            for role, value in (("payload", payload), ("sender", sender), ("receiver", receiver)):
                add_parameter(self, name=role, value=value)

    @property
    def payload_argument(self) -> Optional[Expression]:
        """Spec ``payloadArgument``: ``argument(1)``."""
        return argument(self, 1)

    @property
    def sender_argument(self) -> Optional[Expression]:
        """Spec ``senderArgument``: ``argument(2)``."""
        return argument(self, 2)

    @property
    def receiver_argument(self) -> Optional[Expression]:
        """Spec ``receiverArgument``: ``argument(3)``."""
        return argument(self, 3)


class AssignmentActionUsage(ActionUsage):
    """``assign target.referent := value`` (SysML 8.3.17.5).

    ``referent=`` makes the assigned feature a member (a non-owning Membership);
    ``target=`` and ``value=`` create the two parameters.
    """

    kind = "AssignmentActionUsage"

    def __init__(self, name: Optional[str] = None, *, referent: Optional[Feature] = None,
                 target: Any = None, value: Any = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if referent is not None:
            self.add_member(referent, owned=False)
        if target is not None or value is not None:
            add_parameter(self, name="target", value=target)
            add_parameter(self, name="replacementValues", value=value)

    @property
    def target_argument(self) -> Optional[Expression]:
        """Spec ``targetArgument``: ``argument(1)``."""
        return argument(self, 1)

    @property
    def value_expression(self) -> Optional[Expression]:
        """Spec ``valueExpression``: ``argument(2)``."""
        return argument(self, 2)

    @property
    def referent(self) -> Optional[Feature]:
        """The first member of an owned membership that is not a FeatureMembership and that is a
        Feature but not a MetadataFeature (spec ``referent``)."""
        for m in self.owned_memberships:
            if isinstance(m, FeatureMembership):
                continue
            el = m.member_element
            if isinstance(el, Feature) and not isinstance(el, MetadataFeature):
                return el
        return None


class TerminateActionUsage(ActionUsage):
    """``terminate occurrence`` (SysML 8.3.17.16)."""

    kind = "TerminateActionUsage"

    def __init__(self, name: Optional[str] = None, *, terminated_occurrence: Any = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if terminated_occurrence is not None:
            add_parameter(self, name="terminatedOccurrence", value=terminated_occurrence)

    @property
    def terminated_occurrence_argument(self) -> Optional[Expression]:
        """Spec ``terminatedOccurrenceArgument``: ``argument(1)``."""
        return argument(self, 1)


# ---------------------------------------------------------------------------
# Conditionals and loops
# ---------------------------------------------------------------------------

class IfActionUsage(ActionUsage):
    """``if cond then a else b`` (SysML 8.3.17.10).

    Input parameters 1, 2 and 3 are the condition Expression and the then and
    else ActionUsages; the keywords own them in that order.
    """

    kind = "IfActionUsage"

    def __init__(self, name: Optional[str] = None, *, if_argument: Optional[Expression] = None,
                 then_action: Optional[ActionUsage] = None,
                 else_action: Optional[ActionUsage] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        for p in (if_argument, then_action, else_action):
            if p is not None:
                add_parameter(self, p)

    @property
    def if_argument(self) -> Optional[Expression]:
        """Input parameter 1, if an Expression (spec ``ifArgument``)."""
        return _of(input_parameter(self, 1), Expression)

    @property
    def then_action(self) -> Optional[ActionUsage]:
        """Input parameter 2, if an ActionUsage (spec ``thenAction``)."""
        return _of(input_parameter(self, 2), ActionUsage)

    @property
    def else_action(self) -> Optional[ActionUsage]:
        """Input parameter 3, if an ActionUsage (spec ``elseAction``)."""
        return _of(input_parameter(self, 3), ActionUsage)


class LoopActionUsage(ActionUsage):
    """An action that repeats its ``body_action`` (SysML 8.3.17.12; abstract)."""

    kind = "LoopActionUsage"

    @property
    def body_action(self) -> Optional[ActionUsage]:
        """Input parameter 2, if an ActionUsage (spec ``bodyAction``)."""
        return _of(input_parameter(self, 2), ActionUsage)


class WhileLoopActionUsage(LoopActionUsage):
    """``while cond { body } until cond`` (SysML 8.3.17.19).

    Input parameters 1, 2 and 3 are the while Expression, the body and the
    until Expression; the keywords own them in that order.
    """

    kind = "WhileLoopActionUsage"

    def __init__(self, name: Optional[str] = None, *, while_argument: Optional[Expression] = None,
                 body_action: Optional[ActionUsage] = None,
                 until_argument: Optional[Expression] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        for p in (while_argument, body_action, until_argument):
            if p is not None:
                add_parameter(self, p)

    @property
    def while_argument(self) -> Optional[Expression]:
        """Input parameter 1, if an Expression (spec ``whileArgument``)."""
        return _of(input_parameter(self, 1), Expression)

    @property
    def until_argument(self) -> Optional[Expression]:
        """Input parameter 3, if an Expression (spec ``untilArgument``)."""
        return _of(input_parameter(self, 3), Expression)


class ForLoopActionUsage(LoopActionUsage):
    """``for v in seq { body }`` (SysML 8.3.17.9).

    The ``loop_variable`` is the first owned feature (not a parameter);
    argument 1 is the sequence and input parameter 2 the body.
    """

    kind = "ForLoopActionUsage"

    def __init__(self, name: Optional[str] = None, *, loop_variable: Optional[Feature] = None,
                 seq: Any = None, body_action: Optional[ActionUsage] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        if loop_variable is not None:
            self.own(loop_variable)
        if seq is not None or body_action is not None:
            add_parameter(self, name="seq", value=seq)
            if body_action is not None:
                add_parameter(self, body_action)

    @property
    def seq_argument(self) -> Optional[Expression]:
        """Spec ``seqArgument``: ``argument(1)``."""
        return argument(self, 1)

    @property
    def loop_variable(self) -> Optional[Feature]:
        """The first owned feature, if it is a ReferenceUsage (spec ``loopVariable``)."""
        owned = self.owned_features
        if not owned:
            return None
        # TODO(A3 merge): ReferenceUsage always exists then; drop the Usage fallback.
        cls = class_for("ReferenceUsage") or Usage
        return _of(owned[0], cls)


# ---------------------------------------------------------------------------
# Control nodes
# ---------------------------------------------------------------------------

class ControlNode(ActionUsage):
    """An action that controls the flow between other actions (SysML 8.3.17.6; abstract)."""

    kind = "ControlNode"


class DecisionNode(ControlNode):
    """Chooses one outgoing succession (SysML 8.3.17.7)."""

    kind = "DecisionNode"


class ForkNode(ControlNode):
    """Starts all its outgoing successions (SysML 8.3.17.8)."""

    kind = "ForkNode"


class JoinNode(ControlNode):
    """Waits for all its incoming successions (SysML 8.3.17.11)."""

    kind = "JoinNode"


class MergeNode(ControlNode):
    """Continues after any incoming succession (SysML 8.3.17.13)."""

    kind = "MergeNode"


__all__ = [
    "EventOccurrenceUsage", "PerformActionUsage", "ExhibitStateUsage", "SendActionUsage",
    "AssignmentActionUsage", "TerminateActionUsage", "IfActionUsage", "LoopActionUsage",
    "WhileLoopActionUsage", "ForLoopActionUsage", "ControlNode", "DecisionNode", "ForkNode",
    "JoinNode", "MergeNode",
    "input_parameters", "input_parameter", "argument", "referenced_feature_target",
    "add_parameter",
]
