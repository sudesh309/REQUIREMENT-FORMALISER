"""SysML v2 metamodel built on KerML.

Each domain concept follows the SysML v2 Definition/Usage pattern:
- a Definition is a KerML Classifier
- a Usage is a KerML Feature typed by a Definition
"""
from .definitions import (
    Definition, Usage,
    PartDefinition, PartUsage,
    ItemDefinition, ItemUsage,
    AttributeDefinition, AttributeUsage,
    PortDefinition, PortUsage,
    InterfaceDefinition, InterfaceUsage,
    ConnectionDefinition, ConnectionUsage,
    FlowConnectionDefinition, FlowConnectionUsage,
    ActionDefinition, ActionUsage,
    StateDefinition, StateUsage, TransitionUsage,
    CalculationDefinition, CalculationUsage,
    ConstraintDefinition, ConstraintUsage,
    RequirementDefinition, RequirementUsage,
    UseCaseDefinition, UseCaseUsage,
    AnalysisCaseDefinition, AnalysisCaseUsage,
    VerificationCaseDefinition, VerificationCaseUsage,
    AllocationDefinition, AllocationUsage,
    ViewDefinition, ViewUsage,
    ViewpointDefinition, ViewpointUsage,
    ConcernDefinition, ConcernUsage,
    EnumerationDefinition, EnumerationUsage,
    ParameterDefinition, ParameterUsage,
    MetadataDefinition, MetadataUsage,
    OccurrenceDefinition, OccurrenceUsage,
)
from .relationships import (
    Satisfy, Verify, Refine, Trace, DeriveRequirement, Copy,
    Allocation, SubjectOf, StakeholderOf, ActorOf, FramedConcern,
    ParameterBinding, AssumeConstraint, RequireConstraint, Exposes,
)
from .state_machines import (
    StateMachineDefinition, EventDefinition, EventUsage,
    StateMachineRunner, attach_state_machine, state_machines_of,
)
from .library import SYSML_LIBRARY, build_sysml_library

__all__ = [
    "Definition", "Usage",
    "PartDefinition", "PartUsage",
    "ItemDefinition", "ItemUsage",
    "AttributeDefinition", "AttributeUsage",
    "PortDefinition", "PortUsage",
    "InterfaceDefinition", "InterfaceUsage",
    "ConnectionDefinition", "ConnectionUsage",
    "FlowConnectionDefinition", "FlowConnectionUsage",
    "ActionDefinition", "ActionUsage",
    "StateDefinition", "StateUsage", "TransitionUsage",
    "CalculationDefinition", "CalculationUsage",
    "ConstraintDefinition", "ConstraintUsage",
    "RequirementDefinition", "RequirementUsage",
    "UseCaseDefinition", "UseCaseUsage",
    "AnalysisCaseDefinition", "AnalysisCaseUsage",
    "VerificationCaseDefinition", "VerificationCaseUsage",
    "AllocationDefinition", "AllocationUsage",
    "ViewDefinition", "ViewUsage",
    "ViewpointDefinition", "ViewpointUsage",
    "ConcernDefinition", "ConcernUsage",
    "EnumerationDefinition", "EnumerationUsage",
    "ParameterDefinition", "ParameterUsage",
    "MetadataDefinition", "MetadataUsage",
    "OccurrenceDefinition", "OccurrenceUsage",
    "Satisfy", "Verify", "Refine", "Trace", "DeriveRequirement", "Copy",
    "Allocation", "SubjectOf", "StakeholderOf", "ActorOf", "FramedConcern",
    "ParameterBinding", "AssumeConstraint", "RequireConstraint", "Exposes",
    "StateMachineDefinition", "EventDefinition", "EventUsage",
    "StateMachineRunner", "attach_state_machine", "state_machines_of",
    "SYSML_LIBRARY", "build_sysml_library",
]
