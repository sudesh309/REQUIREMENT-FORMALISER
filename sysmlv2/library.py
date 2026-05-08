"""SysML v2 standard library — abstract roots that user definitions specialize.

Mirrors the layout of the OMG SysML v2 standard library while staying
intentionally minimal: each Definition is the abstract root of its kind,
and is itself rooted in the corresponding KerML library type.
"""
from __future__ import annotations

from kerml.library import KERML_LIBRARY
from kerml.namespaces import Package

from .definitions import (
    AllocationDefinition,
    ActionDefinition,
    AttributeDefinition,
    CalculationDefinition,
    CaseDefinition,
    ConcernDefinition,
    ConnectionDefinition,
    ConstraintDefinition,
    EnumerationDefinition,
    FlowConnectionDefinition,
    InterfaceDefinition,
    ItemDefinition,
    MetadataDefinition,
    OccurrenceDefinition,
    PartDefinition,
    PortDefinition,
    RequirementDefinition,
    StateDefinition,
    UseCaseDefinition,
    AnalysisCaseDefinition,
    VerificationCaseDefinition,
    ViewDefinition,
    ViewpointDefinition,
)


def _kerml(qn: str):
    return KERML_LIBRARY.resolve(qn)


def build_sysml_library() -> Package:
    root = Package(name="SysML")

    # Sub-packages mirroring SysML v2 standard library layout.
    sub = {n: Package(name=n) for n in [
        "Occurrences", "Items", "Parts", "Attributes", "Ports", "Interfaces",
        "Connections", "Flows", "Actions", "States", "Calculations",
        "Constraints", "Requirements", "Concerns", "Cases", "UseCases",
        "AnalysisCases", "VerificationCases", "Allocations", "Views",
        "Viewpoints", "Metadata", "Enumerations",
    ]}
    for p in sub.values():
        root.own(p)

    Occurrence = OccurrenceDefinition(name="Occurrence", is_abstract=True)
    sub["Occurrences"].own(Occurrence)
    if (k := _kerml("Occurrences::Occurrence")):
        Occurrence.specialize(k)

    Item = ItemDefinition(name="Item", is_abstract=True); sub["Items"].own(Item)
    Item.specialize(Occurrence)

    Part = PartDefinition(name="Part", is_abstract=True); sub["Parts"].own(Part)
    Part.specialize(Item)

    Attribute = AttributeDefinition(name="Attribute", is_abstract=True)
    sub["Attributes"].own(Attribute)

    Port = PortDefinition(name="Port", is_abstract=True); sub["Ports"].own(Port)
    Port.specialize(Occurrence)

    Connection = ConnectionDefinition(name="Connection", is_abstract=True)
    sub["Connections"].own(Connection); Connection.specialize(Part)

    Interface = InterfaceDefinition(name="Interface", is_abstract=True)
    sub["Interfaces"].own(Interface); Interface.specialize(Connection)

    FlowConnection = FlowConnectionDefinition(name="FlowConnection", is_abstract=True)
    sub["Flows"].own(FlowConnection); FlowConnection.specialize(Connection)

    Action = ActionDefinition(name="Action", is_abstract=True)
    sub["Actions"].own(Action); Action.specialize(Occurrence)

    State = StateDefinition(name="State", is_abstract=True)
    sub["States"].own(State); State.specialize(Action)

    Calculation = CalculationDefinition(name="Calculation", is_abstract=True)
    sub["Calculations"].own(Calculation); Calculation.specialize(Action)

    Constraint = ConstraintDefinition(name="Constraint", is_abstract=True)
    sub["Constraints"].own(Constraint); Constraint.specialize(Calculation)

    Requirement = RequirementDefinition(name="Requirement", is_abstract=True)
    sub["Requirements"].own(Requirement); Requirement.specialize(Constraint)

    Concern = ConcernDefinition(name="Concern", is_abstract=True)
    sub["Concerns"].own(Concern); Concern.specialize(Requirement)

    Case = CaseDefinition(name="Case", is_abstract=True)
    sub["Cases"].own(Case); Case.specialize(Calculation)

    UseCase = UseCaseDefinition(name="UseCase", is_abstract=True)
    sub["UseCases"].own(UseCase); UseCase.specialize(Case)

    AnalysisCase = AnalysisCaseDefinition(name="AnalysisCase", is_abstract=True)
    sub["AnalysisCases"].own(AnalysisCase); AnalysisCase.specialize(Case)

    VerificationCase = VerificationCaseDefinition(name="VerificationCase", is_abstract=True)
    sub["VerificationCases"].own(VerificationCase); VerificationCase.specialize(Case)

    Allocation = AllocationDefinition(name="Allocation", is_abstract=True)
    sub["Allocations"].own(Allocation)

    View = ViewDefinition(name="View", is_abstract=True); sub["Views"].own(View)
    Viewpoint = ViewpointDefinition(name="Viewpoint", is_abstract=True)
    sub["Viewpoints"].own(Viewpoint); Viewpoint.specialize(Requirement)

    Metaobject = MetadataDefinition(name="Metaobject", is_abstract=True)
    sub["Metadata"].own(Metaobject)

    Enumeration = EnumerationDefinition(name="Enumeration", is_abstract=True)
    sub["Enumerations"].own(Enumeration); Enumeration.specialize(Attribute)

    return root


SYSML_LIBRARY: Package = build_sysml_library()
