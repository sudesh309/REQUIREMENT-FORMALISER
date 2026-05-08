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
    MetadataDefinition, MetadataUsage,
    OccurrenceDefinition, OccurrenceUsage,
)
from .relationships import (
    Satisfy, Verify, Refine, Trace, DeriveRequirement, Copy,
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
    "MetadataDefinition", "MetadataUsage",
    "OccurrenceDefinition", "OccurrenceUsage",
    "Satisfy", "Verify", "Refine", "Trace", "DeriveRequirement", "Copy",
    "SYSML_LIBRARY", "build_sysml_library",
]
