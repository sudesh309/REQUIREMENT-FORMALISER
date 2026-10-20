"""Shared avionics test model for the interop tests (no tests in this module)."""
from __future__ import annotations

from pathlib import Path

from engine import Repository, create_link
from kerml.elements import Documentation
from kerml.features import FeatureDirection, MultiplicityRange
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Package
from kerml.stereotypes import Stereotype
from sysmlv2 import (
    AttributeUsage, ConnectionUsage, PartDefinition, PartUsage, PortDefinition, PortUsage,
    RequirementDefinition,
)
from sysmlv2.state_machines import attach_state_machine

DATA = Path(__file__).resolve().parent / "data"
XMI_FIXTURE = DATA / "interop_avionics_cameo.xmi"


def doc(e, text):
    e.add_annotation(Documentation(body=text))
    return e


def avionics_repo(name: str = "FlightDeck") -> Repository:
    """A small but complete avionics architecture.

    Interfaces::A429Word (label, data), Components::{GPSReceiver, FlightManagementComputer,
    PrimaryFlightDisplay}, architecture FlightDeck {gps, fmc, pfd[2], ims {partition1}},
    connectors navBus / displayBus, requirements SRS-001 / SRS-002 / HLR-010 with satisfy,
    derive and verify links, stereotype LRU (mass, dal) and a state machine on the FMC.
    """
    repo = Repository(name)
    real = KERML_LIBRARY.resolve("ScalarValues::Real")
    integer = KERML_LIBRARY.resolve("ScalarValues::Integer")
    doc(repo.root_package, "Flight deck avionics architecture (test model).")

    ifaces = repo.add(Package(name="Interfaces"))
    a429 = doc(PortDefinition(name="A429Word"), "ARINC 429 32-bit word")
    ifaces.own(a429)
    a429.own(AttributeUsage(name="label", typed_by=integer, multiplicity=MultiplicityRange(1, 1)))
    a429.own(AttributeUsage(name="data", typed_by=real, multiplicity=MultiplicityRange(1, 1)))

    comps = repo.add(Package(name="Components"))
    gps_def = doc(PartDefinition(name="GPSReceiver"), "Multi-constellation GNSS receiver")
    comps.own(gps_def)
    gps_out = PortUsage(name="navOut", typed_by=a429, direction=FeatureDirection.OUT)
    gps_def.own(gps_out)
    fmc_def = doc(PartDefinition(name="FlightManagementComputer"), "Computes the flight plan")
    comps.own(fmc_def)
    fmc_in = PortUsage(name="navIn", typed_by=a429, direction=FeatureDirection.IN)
    fmc_out = PortUsage(name="displayOut", typed_by=a429, direction=FeatureDirection.OUT)
    fmc_def.own(fmc_in)
    fmc_def.own(fmc_out)
    fmc_def.own(AttributeUsage(name="cruiseAltitude", typed_by=real,
                               multiplicity=MultiplicityRange(1, 1)))
    pfd_def = PartDefinition(name="PrimaryFlightDisplay")
    comps.own(pfd_def)
    pfd_in = PortUsage(name="displayIn", typed_by=a429, direction=FeatureDirection.IN)
    pfd_def.own(pfd_in)

    arch = doc(PartDefinition(name="FlightDeck"), "Top-level flight deck architecture")
    repo.add(arch)
    gps = PartUsage(name="gps", typed_by=gps_def, multiplicity=MultiplicityRange(1, 1))
    fmc = PartUsage(name="fmc", typed_by=fmc_def, multiplicity=MultiplicityRange(1, 1))
    pfd = PartUsage(name="pfd", typed_by=pfd_def, multiplicity=MultiplicityRange(2, 2))
    ims = PartUsage(name="ims", multiplicity=MultiplicityRange(1, 1))     # inline component
    for p in (gps, fmc, pfd, ims):
        arch.own(p)
    health = PortUsage(name="health", typed_by=a429, direction=FeatureDirection.OUT)
    ims.own(health)
    ims.own(PartUsage(name="partition1", multiplicity=MultiplicityRange(1, 1)))
    arch.own(ConnectionUsage(name="navBus", ends=[gps_out, fmc_in]))
    arch.own(ConnectionUsage(name="displayBus", ends=[fmc_out, pfd_in]))

    reqs = repo.add(Package(name="Requirements"))
    r1 = RequirementDefinition(name="NavAccuracy", req_id="SRS-001",
                               text="The system shall determine position within RNP 0.3.")
    r2 = RequirementDefinition(name="AttitudeDisplay", req_id="SRS-002",
                               text="The system shall display attitude.")
    r3 = RequirementDefinition(name="LateralGuidance", req_id="HLR-010",
                               text="The FMC shall compute lateral guidance.")
    for r in (r1, r2, r3):
        reqs.own(r)
    create_link("satisfy", fmc_def, r1)
    create_link("satisfy", pfd_def, r2)
    create_link("derive", r3, r1)

    profile = repo.add(Package(name="AvionicsProfile"))
    lru = Stereotype("LRU", applies_to=[PartDefinition, PartUsage])
    profile.own(lru)
    lru.define_tag("mass", default=0.0)
    lru.define_tag("dal", default="E")
    lru.apply(fmc_def, {"mass": 4.2, "dal": "A"})
    lru.apply(gps_def, {"mass": 1.1, "dal": "B"})

    sm = attach_state_machine(fmc_def, "Modes")
    off = sm.add_state("Off", is_initial=True)
    on = sm.add_state("On", entry="selfTest()")
    sm.add_transition(off, on, trigger="powerOn")
    repo.registry.register_tree(repo.root_package)
    return repo


def add_avionics_profile(repo: Repository):
    """Add a real profile (engine.profiles) next to the legacy «LRU» of avionics_repo().

    Profile Avionics 2.1: abstract Equipment (Component; mass double kg >= 0, default 1.5;
    style fill + icon), LRU (base Equipment; dal A..E default C, ata uint8, spare boolean,
    pn string; default port stereotype A429Port; dashed stroke), A429Port (Port; rate
    kbit/s); an empty profile Spare 0.1. «Avionics.LRU» is applied to FlightDeck::fmc with
    mass '3 lb' (stored as 1.36077711 kg), dal B, ata 34, «Avionics.A429Port» to
    Components::FlightManagementComputer::navIn (rate 12.5). Returns the profile.
    """
    from engine import profiles as P
    prof = P.create_profile(repo, "Avionics", description="Avionics equipment", version="2.1")
    eq = P.add_stereotype(repo, prof, "Equipment", applies_to="Component", abstract=True,
                          style={"fill": "#dbeafe", "icon": "computer"})
    P.add_property(repo, eq, "mass", "double", unit="kg", default="1.5", minimum=0)
    port = P.add_stereotype(repo, prof, "A429Port", applies_to="Port")
    P.add_property(repo, port, "rate", "double", unit="kbit/s", default=100)
    lru = P.add_stereotype(repo, prof, "LRU", base=eq, style={"stroke": "#1d4ed8", "line": "dashed"},
                           defaults={"port": port})
    P.add_property(repo, lru, "dal", "enumeration", literals="A,B,C,D,E", default="C")
    P.add_property(repo, lru, "ata", "uint8", default=34)
    P.add_property(repo, lru, "spare", "boolean")
    P.add_property(repo, lru, "pn", "string", description="part number")
    P.create_profile(repo, "Spare", version="0.1")
    P.apply_stereotype(repo, repo.resolve("FlightDeck::fmc"), lru, {"mass": "3 lb", "dal": "b"})
    P.apply_stereotype(repo, repo.resolve("Components::FlightManagementComputer::navIn"), port,
                       {"rate": 12.5})
    repo.registry.register_tree(repo.root_package)
    return prof
