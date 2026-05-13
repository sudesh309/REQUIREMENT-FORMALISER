"""SysML v2 Definition / Usage classes.

The SysML v2 metamodel layers on KerML by introducing, for each domain,
a *Definition* (a KerML Classifier) and a *Usage* (a KerML Feature
typed by the Definition). This mirrors the Cameo SysML v1.6 distinction
between e.g. a Block and a Part Property, but with consistent semantics.
"""
from __future__ import annotations

from typing import Optional

from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.types import Behavior, Class, Classifier, DataType, Structure, Type


# -- Roots ----------------------------------------------------------------

class Definition(Classifier):
    """Root of all SysML v2 definitions."""

    kind = "Definition"

    def __init__(self, name: Optional[str] = None, *, is_variation: bool = False,
                 is_individual: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_variation = is_variation
        self.is_individual = is_individual

    # Convenience: add an owned Usage that becomes a feature of this Definition.
    def own_usage(self, usage: "Usage") -> "Usage":
        self.own(usage)
        usage.featuring_type = self
        return usage


class Usage(Feature):
    """Root of all SysML v2 usages."""

    kind = "Usage"

    def __init__(self, name: Optional[str] = None, *,
                 is_variant: bool = False, is_reference: bool = False,
                 portion_kind: str = "none", **kwargs):
        super().__init__(name=name, **kwargs)
        self.is_variant = is_variant
        self.is_reference = is_reference
        self.portion_kind = portion_kind  # "timeslice" | "snapshot" | "none"
        self.featuring_type: Optional[Type] = None


# -- Structure (BDD / IBD) ------------------------------------------------

class OccurrenceDefinition(Definition): kind = "OccurrenceDefinition"
class OccurrenceUsage(Usage):           kind = "OccurrenceUsage"

class ItemDefinition(OccurrenceDefinition): kind = "ItemDefinition"
class ItemUsage(OccurrenceUsage):           kind = "ItemUsage"

class PartDefinition(ItemDefinition): kind = "PartDefinition"
class PartUsage(ItemUsage):           kind = "PartUsage"

class AttributeDefinition(Definition): kind = "AttributeDefinition"
class AttributeUsage(Usage):           kind = "AttributeUsage"

class PortDefinition(OccurrenceDefinition):
    kind = "PortDefinition"
    def __init__(self, *args, is_conjugated: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_conjugated = is_conjugated

class PortUsage(OccurrenceUsage): kind = "PortUsage"

class InterfaceDefinition(Definition): kind = "InterfaceDefinition"
class InterfaceUsage(Usage):           kind = "InterfaceUsage"

class ConnectionDefinition(Definition): kind = "ConnectionDefinition"

class ConnectionUsage(Usage):
    kind = "ConnectionUsage"
    def __init__(self, *args, ends: Optional[list[Feature]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ends: list[Feature] = ends or []

class FlowConnectionDefinition(ConnectionDefinition):
    kind = "FlowConnectionDefinition"
    def __init__(self, *args, payload_type: Optional[Type] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload_type = payload_type

class FlowConnectionUsage(ConnectionUsage):
    kind = "FlowConnectionUsage"
    def __init__(self, *args, payload_type: Optional[Type] = None,
                 source: Optional[Feature] = None, target: Optional[Feature] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.payload_type = payload_type
        self.flow_source = source
        self.flow_target = target


# -- Behavior (Action / State) -------------------------------------------

class ActionDefinition(OccurrenceDefinition): kind = "ActionDefinition"
class ActionUsage(OccurrenceUsage):           kind = "ActionUsage"

class StateDefinition(ActionDefinition):
    kind = "StateDefinition"
    def __init__(self, *args, is_parallel: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_parallel = is_parallel

class StateUsage(ActionUsage): kind = "StateUsage"

class TransitionUsage(ActionUsage):
    kind = "TransitionUsage"
    def __init__(self, name: Optional[str] = None, *,
                 source: Optional[Feature] = None, target: Optional[Feature] = None,
                 trigger: Optional[Feature] = None, guard=None, effect: Optional[Feature] = None,
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.transition_source = source
        self.transition_target = target
        self.trigger = trigger
        self.guard = guard
        self.effect = effect


class CalculationDefinition(ActionDefinition): kind = "CalculationDefinition"
class CalculationUsage(ActionUsage):           kind = "CalculationUsage"

class ConstraintDefinition(CalculationDefinition): kind = "ConstraintDefinition"

class ConstraintUsage(CalculationUsage):
    kind = "ConstraintUsage"
    def __init__(self, *args, expression=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expression = expression


# -- Requirements / Cases / Analysis -------------------------------------

class RequirementDefinition(ConstraintDefinition):
    kind = "RequirementDefinition"

    def __init__(self, name: Optional[str] = None, *, req_id: Optional[str] = None,
                 text: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.req_id = req_id
        self.text = text
        self.subject: Optional[Feature] = None
        self.stakeholders: list[Feature] = []
        self.actors: list[Feature] = []
        self.assumed_constraints: list[ConstraintUsage] = []
        self.required_constraints: list[ConstraintUsage] = []
        self.satisfied_by: list[Feature] = []
        self.verified_by: list[Feature] = []


class RequirementUsage(ConstraintUsage):
    kind = "RequirementUsage"

    def __init__(self, *args, req_id: Optional[str] = None, text: Optional[str] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.req_id = req_id
        self.text = text
        self.satisfied_by: list[Feature] = []
        self.verified_by: list[Feature] = []


class CaseDefinition(CalculationDefinition):
    kind = "CaseDefinition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subject: Optional[Feature] = None
        self.objective: Optional[Feature] = None


class CaseUsage(CalculationUsage): kind = "CaseUsage"

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

class AllocationDefinition(Definition): kind = "AllocationDefinition"

class AllocationUsage(Usage):
    kind = "AllocationUsage"
    def __init__(self, *args, allocate_from: Optional[Feature] = None,
                 allocate_to: Optional[Feature] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allocate_from = allocate_from
        self.allocate_to = allocate_to


class ViewDefinition(Definition): kind = "ViewDefinition"

class ViewUsage(Usage):
    kind = "ViewUsage"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exposed: list[Feature] = []


class ViewpointDefinition(RequirementDefinition):
    kind = "ViewpointDefinition"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.concerns: list[str] = []

class ViewpointUsage(RequirementUsage): kind = "ViewpointUsage"

class ConcernDefinition(RequirementDefinition): kind = "ConcernDefinition"
class ConcernUsage(RequirementUsage):           kind = "ConcernUsage"

class MetadataDefinition(Definition): kind = "MetadataDefinition"
class MetadataUsage(Usage):           kind = "MetadataUsage"

class ParameterDefinition(AttributeDefinition):
    """SysML v2 parameter definition — typed input/output slot of a behavior."""
    kind = "ParameterDefinition"


class ParameterUsage(AttributeUsage):
    """SysML v2 parameter usage — a directional, typed feature on Action /
    Calculation / Constraint / Requirement definitions and usages.

    `parameter_kind` is one of: 'in', 'out', 'inout', 'return'.
    """
    kind = "ParameterUsage"

    def __init__(self, name: Optional[str] = None, *,
                 parameter_kind: str = "in",
                 typed_by: Optional[Type] = None,
                 default_expression=None,
                 **kwargs):
        from kerml.features import FeatureDirection
        dir_map = {"in":     FeatureDirection.IN,
                   "out":    FeatureDirection.OUT,
                   "inout":  FeatureDirection.INOUT,
                   "return": FeatureDirection.OUT}
        super().__init__(name=name,
                         direction=dir_map.get(parameter_kind, FeatureDirection.IN),
                         typed_by=typed_by, **kwargs)
        self.parameter_kind = parameter_kind  # 'in' | 'out' | 'inout' | 'return'
        self.default_expression = default_expression


class EnumerationDefinition(AttributeDefinition):
    kind = "EnumerationDefinition"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.literals: list["EnumerationUsage"] = []

class EnumerationUsage(AttributeUsage): kind = "EnumerationUsage"
