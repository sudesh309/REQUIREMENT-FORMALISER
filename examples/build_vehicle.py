"""Build the same vehicle model programmatically via the metamodel API.

Demonstrates the engine's "Cameo-like" containment-tree workflow without
parsing — the same calls a UI would make.
"""
from engine import Repository
from kerml.namespaces import Package
from sysmlv2 import (
    AttributeDefinition, AttributeUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    ConnectionUsage,
    RequirementDefinition,
)
from sysmlv2.relationships import Satisfy


def build() -> Repository:
    repo = Repository(name="VehicleProject")
    pkg = Package(name="Vehicles")
    repo.add(pkg)

    Mass  = AttributeDefinition(name="Mass");   pkg.own(Mass)
    Power = AttributeDefinition(name="Power");  pkg.own(Power)

    Mech = PortDefinition(name="MechanicalPort"); pkg.own(Mech)
    Elec = PortDefinition(name="ElectricalPort"); pkg.own(Elec)

    Engine = PartDefinition(name="Engine"); pkg.own(Engine)
    Engine.own(AttributeUsage(name="power", typed_by=Power))
    engine_shaft = PortUsage(name="shaft", typed_by=Mech); Engine.own(engine_shaft)

    Trans = PartDefinition(name="Transmission"); pkg.own(Trans)
    trans_in  = PortUsage(name="input",  typed_by=Mech); Trans.own(trans_in)
    trans_out = PortUsage(name="output", typed_by=Mech); Trans.own(trans_out)

    Vehicle = PartDefinition(name="Vehicle"); pkg.own(Vehicle)
    Vehicle.own(AttributeUsage(name="mass", typed_by=Mass))
    e_part = PartUsage(name="engine",       typed_by=Engine); Vehicle.own(e_part)
    t_part = PartUsage(name="transmission", typed_by=Trans);  Vehicle.own(t_part)

    drivetrain = ConnectionUsage(name="drivetrain", ends=[engine_shaft, trans_in])
    Vehicle.own(drivetrain)

    # Requirement + Satisfy relationship.
    range_req = RequirementDefinition(
        name="RangeRequirement", req_id="REQ-001",
        text="Vehicle shall have a range of at least 400 km.",
    )
    pkg.own(range_req)
    Vehicle.add_relationship(Satisfy(Vehicle, range_req))

    repo.registry.register_tree(pkg)
    return repo


if __name__ == "__main__":
    repo = build()
    print(repo)
    for issue in repo.validate():
        print(issue)
