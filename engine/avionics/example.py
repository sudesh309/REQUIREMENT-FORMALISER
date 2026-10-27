"""The complete IMA avionics example, built through the public engine APIs.

``build_example(name)`` returns a repository holding a whole aircraft avionics system model:

* **Interfaces**: the full interface library (ARINC 429 / 664 / 825 / 653, MIL-STD-1553B, discrete,
  analog, power) with an interface assigned to every port.
* **Profile**: ``Avionics`` with mass / power / MTBF / DAL / part number ... on every equipment
  *definition* (``Equipment`` package), partitions, software items and bus links.
* **Architectures**: ``FunctionalArchitecture`` (13 functions), ``LogicalArchitecture`` (12 items) and
  ``PhysicalArchitecture``: air data computers, inertial reference units, radio altimeters, GNSS,
  sidesticks, remote data concentrators, a dual-network AFDX switch pair, an IMA cabinet (two core
  processing modules hosting four partitions and eight software items), two flight control computers
  (command and monitor lanes, with a mode state machine), three displays (PFD / ND / EICAS), two
  actuators and two power supplies, wired with ARINC 429, AFDX, MIL-STD-1553B, discrete, analog and
  28 VDC links.
* **Requirements**: ARP4754A system and item sets and DO-178C HLR / LLR sets, linked to components
  (implement) and test cases (verify), with deliberate open gaps (:data:`OPEN_GAPS`).
* **Allocation**: functions -> logical items -> hardware / IMA partitions.
* **Safety**: an FHA table whose rows are allocated to functions.

Everything is created through ``engine.architecture``, ``interfaces``, ``profiles``,
``requirements``, ``allocation`` and :mod:`engine.avionics.safety`; nothing is written as raw JSON.
Run ``python -m engine.avionics.example out.json`` to save the example.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

import engine.requirements as rq
from engine import Repository
from engine import allocation as AL
from engine import architecture as A
from engine import interfaces as I
from engine import profiles as P
from engine.hooks import notify_created
from kerml.elements import Documentation, Element
from kerml.namespaces import Package
from sysmlv2.definitions import PartDefinition
from sysmlv2.state_machines import attach_state_machine

from . import interfaces_lib
from . import profile as AP
from . import safety as SF

__all__ = ["build_example", "OPEN_GAPS", "EXAMPLE_NAME", "describe_example"]

EXAMPLE_NAME = "IMA_Avionics"

#: The open gaps left in the example on purpose, for reviews and tests.
OPEN_GAPS = {
    # requirements (by summary) that no design element implements / no test case verifies
    "not_implemented": ["GNSS integrity monitoring"],
    "not_verified": ["Detect erroneous air data", "GNSS integrity monitoring", "Concentrator conversion",
                     "Software memory budget", "Division guard"],
    "failed_tests": ["TC-FccLatency"],
    "unexecuted_tests": ["TC-IruAccuracy", "TC-NetworkRedundancy"],
}


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------

def _doc(e: Element, text: str) -> None:
    if text:
        e.annotations = [a for a in e.annotations if not isinstance(a, Documentation)]
        e.add_annotation(Documentation(body=text))


_BUS_LABEL = {"a429": "ARINC429", "afdx": "AFDX", "1553": "MIL-STD-1553", "disc": "Discrete",
              "analog": "Analog", "a653": "ARINC653", "pwr": "Power"}
_BUS_LINK = {   # busType, bandwidth (Mbit/s), latency (ms)
    "a429": ("ARINC429", 0.1, 1.0), "afdx": ("AFDX", 100.0, 0.5), "1553": ("MIL-STD-1553", 1.0, 2.0),
    "disc": ("Discrete", None, 1.0), "analog": ("Analog", None, 2.0), "pwr": ("Power", None, None)}
_DIR_TEXT = {"in": "Input", "out": "Output", "inout": "Bidirectional"}


class _Builder:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.n_links = 0

    # --- interfaces ---------------------------------------------------------
    def iface(self, name: str) -> Element:
        it = I.find_item(self.repo, name)
        if it is None:
            raise KeyError(f"interface {name} missing")
        return it

    # --- structure ----------------------------------------------------------
    def port(self, owner: Element, name: str, direction: str, iface: str, bus: str, *,
             kind: str = "data", doc: Optional[str] = None, tag: bool = True, **values: Any) -> Element:
        p = A.add_port(self.repo, owner, name, direction, kind, self.iface(iface))
        if tag:                                    # bus type and address (physical architectures)
            label = values.pop("label", None)
            if label is None and iface.startswith("A429"):
                item = interfaces_lib.find_item(iface)
                label = "/".join(el["label"] for el in item.get("elements", ()) if el.get("label")) or None
            data = {"busType": _BUS_LABEL[bus], **values}
            if label:
                data["label"] = label
            AP.apply(self.repo, p, "DataBusPort", data)
        _doc(p, doc or f"{_DIR_TEXT.get(direction, 'Port')} port carrying {iface}.")
        return p

    def comp(self, composition: Element, name: str, definition: Optional[Element] = None,
             doc: str = "") -> Element:
        c = A.add_component(self.repo, composition, name, definition)
        _doc(c, doc)
        return c

    def connect(self, composition: Element, a: tuple, b: tuple, bus: Optional[str] = None, *,
                length: Optional[float] = None, **extra: Any) -> Element:
        """Connect ``(component | None, "port")`` to ``(component | None, "port")``; a bus
        key (``a429`` ...) also applies ``Avionics.BusLink`` with typical values."""
        conn = A.connect(self.repo, composition, {"component": a[0], "port": a[1]},
                         {"component": b[0], "port": b[1]})
        if bus in _BUS_LINK:
            bus_type, bandwidth, latency = _BUS_LINK[bus]
            values: dict[str, Any] = {"busType": bus_type}
            if bandwidth is not None:
                values["bandwidth"] = bandwidth
            if latency is not None:
                values["latency"] = latency
            if length is not None:
                values["length"] = length
            values.update(extra)
            AP.apply(self.repo, conn, "BusLink", values)
            self.n_links += 1
        return conn


# ---------------------------------------------------------------------------------------------
# Equipment definitions
# ---------------------------------------------------------------------------------------------

_ENV = "A1(CA)BAB(SBM)XXXXXXZZAZZZA"

# name, stereotype, values, documentation
EQUIPMENT: list[tuple[str, str, dict, str]] = [
    ("AirDataComputer", "Computer",
     dict(mass=3.6, powerNominal=30, powerPeak=45, mtbf=40000, failureRate=25000, partNumber="ADC-4100-02",
          manufacturer="Meridian Avionics", ataChapter=34, dal="B", certificationBasis="TSO-C106",
          do160Categories=_ENV, processor="PowerPC e500", memory=8192),
     "Air data computer: pressure altitude, airspeeds, Mach, vertical speed and air temperature on ARINC 429."),
    ("InertialReferenceUnit", "Sensor",
     dict(mass=9.8, powerNominal=60, powerPeak=90, mtbf=30000, partNumber="IRU-7100-01",
          manufacturer="Helios Inertial", ataChapter=34, dal="B", certificationBasis="TSO-C201",
          do160Categories=_ENV, measurand="attitude, heading, acceleration and position"),
     "Laser-gyro inertial reference unit."),
    ("RadioAltimeter", "Sensor",
     dict(mass=2.4, powerNominal=25, powerPeak=35, mtbf=25000, partNumber="RA-3500-00",
          manufacturer="Meridian Avionics", ataChapter=34, dal="C", certificationBasis="TSO-C87A",
          do160Categories=_ENV, measurand="height above ground"),
     "Radio altimeter transceiver."),
    ("GnssReceiver", "Sensor",
     dict(mass=1.8, powerNominal=12, powerPeak=15, mtbf=50000, partNumber="GNSS-900-03",
          manufacturer="Orbitek", ataChapter=34, dal="C", certificationBasis="TSO-C145e / TSO-C146e",
          do160Categories=_ENV, measurand="position, velocity and time"),
     "GNSS (GPS / SBAS) receiver."),
    ("Sidestick", "Sensor",
     dict(mass=1.2, powerNominal=6, powerPeak=8, mtbf=100000, partNumber="SSK-210-04",
          manufacturer="Helios Inertial", ataChapter=27, dal="A", do160Categories=_ENV,
          measurand="pilot pitch and roll demand"),
     "Pilot sidestick with position transducers and a takeover pushbutton."),
    ("RemoteDataConcentrator", "Gateway",
     dict(mass=2.1, powerNominal=28, powerPeak=36, mtbf=60000, partNumber="RDC-250-01",
          manufacturer="Orbitek", ataChapter=42, dal="B", do160Categories=_ENV,
          protocols="ARINC 429, discrete to ARINC 664 part 7"),
     "Remote data concentrator: converts ARINC 429 and discrete inputs to AFDX."),
    ("AfdxSwitch", "Switch",
     dict(mass=4.5, powerNominal=55, powerPeak=70, mtbf=80000, partNumber="AFDX-SW8-02",
          manufacturer="Orbitek", ataChapter=42, dal="B", do160Categories=_ENV, portCount=8,
          switchingLatency=150),
     "ARINC 664 part 7 AFDX switch, one per redundant network."),
    ("FlightControlComputer", "Computer",
     dict(mass=6.4, powerNominal=110, powerPeak=150, mtbf=25000, failureRate=40000, partNumber="FCC-1000-05",
          manufacturer="Meridian Avionics", ataChapter=27, dal="A", certificationBasis="CS-25.1309",
          do160Categories=_ENV, processor="Dual lockstep cores", memory=16384),
     "Flight control computer with a command lane and a dissimilar monitor lane."),
    ("DisplayUnit", "Display",
     dict(mass=7.9, powerNominal=95, powerPeak=130, mtbf=20000, partNumber="DU-1500-03",
          manufacturer="Helios Inertial", ataChapter=31, dal="B", certificationBasis="TSO-C113",
          do160Categories=_ENV, diagonal=15.1),
     "15.1 inch cockpit display unit (PFD, ND or EICAS)."),
    ("ElevatorActuator", "Actuator",
     dict(mass=14.5, powerNominal=40, powerPeak=400, mtbf=18000, partNumber="EHA-E-300",
          manufacturer="Aerotek Actuation", ataChapter=27, dal="A", do160Categories=_ENV,
          stroke=120, maxForce=45000),
     "Electro-hydrostatic elevator actuator with control electronics."),
    ("AileronActuator", "Actuator",
     dict(mass=11.2, powerNominal=35, powerPeak=320, mtbf=18000, partNumber="EHA-A-250",
          manufacturer="Aerotek Actuation", ataChapter=27, dal="A", do160Categories=_ENV,
          stroke=90, maxForce=30000),
     "Electro-hydrostatic aileron actuator with control electronics."),
    ("PowerSupplyUnit", "PowerSupply",
     dict(mass=8.8, powerNominal=35, powerPeak=60, mtbf=100000, partNumber="PSU-28-1200",
          manufacturer="Aerotek Actuation", ataChapter=24, dal="B", do160Categories=_ENV,
          outputVoltage=28, ratedPower=1200),
     "28 VDC power supply unit."),
    ("CoreModuleFMS", "LRM",
     dict(mass=2.9, powerNominal=85, powerPeak=120, mtbf=45000, partNumber="CPM-800-FMS",
          manufacturer="Meridian Avionics", ataChapter=42, dal="B", certificationBasis="DO-297",
          do160Categories=_ENV, slot="1", cores=4, memory=262144, partitioningMark=True),
     "Core processing module loaded with the flight management and flight warning partitions."),
    ("CoreModuleDMS", "LRM",
     dict(mass=2.9, powerNominal=85, powerPeak=120, mtbf=45000, partNumber="CPM-800-DMS",
          manufacturer="Meridian Avionics", ataChapter=42, dal="B", certificationBasis="DO-297",
          do160Categories=_ENV, slot="2", cores=4, memory=262144, partitioningMark=True),
     "Core processing module loaded with the display management and maintenance partitions."),
    ("CabinetPowerModule", "LRM",
     dict(mass=3.4, powerNominal=40, powerPeak=70, mtbf=90000, partNumber="PSM-28-500",
          manufacturer="Aerotek Actuation", ataChapter=24, dal="B", do160Categories=_ENV, slot="3"),
     "Cabinet power conversion module feeding the backplane."),
    ("ImaCabinet", "LRU",
     dict(mass=12.0, powerNominal=15, powerPeak=25, mtbf=120000, partNumber="IMA-CAB-03",
          manufacturer="Meridian Avionics", ataChapter=42, dal="B", certificationBasis="DO-297",
          do160Categories=_ENV),
     "Integrated modular avionics cabinet: chassis, backplane and three modules."),
]

# Ports of the definitions: (name, direction, interface, bus, extra values, documentation)
_A, _B = "afdxA", "afdxB"


def _afdx(vl: int) -> list[tuple]:
    return [(_A, "inout", "A664Message", "afdx", {"virtualLink": vl}, "AFDX end system, network A."),
            (_B, "inout", "A664Message", "afdx", {"virtualLink": vl}, "AFDX end system, network B.")]


def _pwr(name: str = "pwr", doc: str = "28 VDC supply input.") -> tuple:
    return (name, "inout", "Power28VDCBus", "pwr", {}, doc)


PORTS: dict[str, list[tuple]] = {
    "AirDataComputer": [("airData", "out", "A429AirData", "a429", {}, "Air data labels at 20 Hz."),
                        _pwr()],
    "InertialReferenceUnit": [("inertial", "out", "A429Inertial", "a429", {}, "Inertial and attitude labels at 50 Hz."),
                              _pwr()],
    "RadioAltimeter": [("radioAlt", "out", "A429RadioAltitude", "a429", {}, "Radio altitude label at 20 Hz."),
                       _pwr()],
    "GnssReceiver": [("gnss", "out", "A429Gnss", "a429", {}, "GNSS position labels at 5 Hz."), _pwr()],
    "Sidestick": [("pitchPos", "out", "SynchroSignal", "analog", {}, "Pitch demand, synchro."),
                  ("takeover", "out", "DiscreteLine", "disc", {}, "Takeover pushbutton, 28 V / open, active low.")],
    "RemoteDataConcentrator": [
        ("a429In1", "in", "A429AirData", "a429", {}, "Air data input."),
        ("a429In2", "in", "A429Inertial", "a429", {}, "Inertial input."),
        ("a429In3", "in", "A429RadioAltitude", "a429", {}, "Radio altitude input."),
        ("a429In4", "in", "A429Gnss", "a429", {}, "GNSS input."),
        ("discreteIn1", "in", "DiscreteLine", "disc", {}, "Sidestick takeover discrete."),
        *_afdx(1001), _pwr()],
    "AfdxSwitch": [(f"p{i}", "inout", "A664Message", "afdx", {}, f"Switch port {i}.") for i in range(1, 9)]
                  + [_pwr()],
    "DisplayUnit": [*_afdx(3001), _pwr()],
    "ElevatorActuator": [
        ("cmdL", "in", "M1553BMessage", "1553", {"rtAddress": 5}, "Surface command, left channel."),
        ("cmdR", "in", "M1553BMessage", "1553", {"rtAddress": 5}, "Surface command, right channel."),
        ("statusL", "out", "M1553BMessage", "1553", {"rtAddress": 5}, "Status, left channel."),
        ("statusR", "out", "M1553BMessage", "1553", {"rtAddress": 5}, "Status, right channel."),
        ("engageL", "in", "DiscreteLine", "disc", {}, "Engage solenoid enable, left."),
        ("engageR", "in", "DiscreteLine", "disc", {}, "Engage solenoid enable, right."),
        ("lvdtL", "out", "AnalogVoltage", "analog", {}, "Surface position LVDT, 0-10 V, left."),
        ("lvdtR", "out", "AnalogVoltage", "analog", {}, "Surface position LVDT, 0-10 V, right."),
        _pwr("pwrL", "28 VDC supply, left."), _pwr("pwrR", "28 VDC supply, right.")],
    "AileronActuator": [
        ("cmdL", "in", "M1553BMessage", "1553", {"rtAddress": 6}, "Surface command, left channel."),
        ("cmdR", "in", "M1553BMessage", "1553", {"rtAddress": 6}, "Surface command, right channel."),
        ("statusL", "out", "M1553BMessage", "1553", {"rtAddress": 6}, "Status, left channel."),
        ("statusR", "out", "M1553BMessage", "1553", {"rtAddress": 6}, "Status, right channel."),
        ("engageL", "in", "DiscreteLine", "disc", {}, "Engage solenoid enable, left."),
        ("engageR", "in", "DiscreteLine", "disc", {}, "Engage solenoid enable, right."),
        ("posL", "out", "AnalogCurrent", "analog", {}, "Surface position transducer, 4-20 mA, left."),
        ("posR", "out", "AnalogCurrent", "analog", {}, "Surface position transducer, 4-20 mA, right."),
        _pwr("pwrL", "28 VDC supply, left."), _pwr("pwrR", "28 VDC supply, right.")],
    "PowerSupplyUnit": [("feed", "inout", "Power28VDCBus", "pwr", {}, "28 VDC output bus.")],
    "CoreModuleFMS": _afdx(4001),
    "CoreModuleDMS": _afdx(4002),
    "CabinetPowerModule": [_pwr("inA", "Supply A input."), _pwr("inB", "Supply B input.")],
    "ImaCabinet": [*_afdx(4000), _pwr("pwrA", "Supply A input."), _pwr("pwrB", "Supply B input.")],
}

FCC_PORTS: list[tuple] = [
    ("airDataIn", "in", "A429AirData", "a429", {}, "Air data from the same-side ADC."),
    ("inertialIn", "in", "A429Inertial", "a429", {}, "Inertial data from the same-side IRU."),
    ("radioAltIn", "in", "A429RadioAltitude", "a429", {}, "Radio altitude from the same-side RA."),
    ("sidestickPitch", "in", "SynchroSignal", "analog", {}, "Pitch demand from the sidestick."),
    ("elevPos", "in", "AnalogVoltage", "analog", {}, "Elevator position feedback, 0-10 V."),
    ("ailPos", "in", "AnalogCurrent", "analog", {}, "Aileron position feedback, 4-20 mA."),
    ("surfaceCmd", "out", "M1553BMessage", "1553", {"rtAddress": 0}, "Surface commands, bus controller."),
    ("elevStatus", "in", "M1553BMessage", "1553", {"rtAddress": 5}, "Elevator actuator status."),
    ("ailStatus", "in", "M1553BMessage", "1553", {"rtAddress": 6}, "Aileron actuator status."),
    ("engageElev", "out", "DiscreteLine", "disc", {}, "Elevator engage enable, 28 V when the monitor agrees."),
    ("engageAil", "out", "DiscreteLine", "disc", {}, "Aileron engage enable, 28 V when the monitor agrees."),
    *_afdx(2001), _pwr(),
]


def _define_equipment(b: _Builder) -> dict[str, PartDefinition]:
    repo = b.repo
    pkg = Package(name="Equipment")
    repo.add(pkg)
    _doc(pkg, "Reference components (part definitions) of the avionics equipment. Their stereotype values "
              "(mass, power, MTBF, DAL ...) are shared by every usage.")
    notify_created(pkg, repo)
    defs: dict[str, PartDefinition] = {}
    for name, stereo, values, doc in EQUIPMENT:
        d = A.create_architecture(repo, name, pkg)
        _doc(d, doc)
        AP.apply(repo, d, stereo, values)       # first: its default port stereotype applies to the ports
        defs[name] = d
        for pname, direction, iface, bus, extra, pdoc in PORTS.get(name, ()):
            kind = "physical" if bus == "pwr" else "data"
            b.port(d, pname, direction, iface, bus, kind=kind, doc=pdoc, **extra)
    return defs


# ---------------------------------------------------------------------------------------------
# Software side: FCC lanes and IMA partitions
# ---------------------------------------------------------------------------------------------

def _build_fcc(b: _Builder, d: PartDefinition) -> None:
    repo = b.repo
    for pname, direction, iface, bus, extra, pdoc in FCC_PORTS:
        b.port(d, pname, direction, iface, bus, kind="physical" if bus == "pwr" else "data", doc=pdoc, **extra)
    cmd = b.comp(d, "CommandLane", doc="Command lane: computes the control laws and the surface commands.")
    mon = b.comp(d, "MonitorLane", doc="Dissimilar monitor lane: checks the command lane and enables the "
                                       "actuator engage discretes.")
    AP.apply(repo, cmd, "SoftwareItem", dict(dal="A", language="Ada", sloc=85000, version="B2.3"))
    AP.apply(repo, mon, "SoftwareItem", dict(dal="A", language="C", sloc=42000, version="B2.3"))
    # Lane ports.
    for lane, names in ((cmd, ("airData", "inertial", "radioAlt")), (mon, ("airData", "inertial", "radioAlt"))):
        for n, iface in zip(names, ("A429AirData", "A429Inertial", "A429RadioAltitude")):
            b.port(lane, n, "in", iface, "a429", doc=f"{iface} copy for this lane.")
    b.port(cmd, "sidestick", "in", "SynchroSignal", "analog", doc="Pitch demand.")
    b.port(mon, "sidestick", "in", "SynchroSignal", "analog", doc="Pitch demand, for the plausibility check.")
    b.port(cmd, "elevPos", "in", "AnalogVoltage", "analog", doc="Elevator position.")
    b.port(cmd, "ailPos", "in", "AnalogCurrent", "analog", doc="Aileron position.")
    b.port(cmd, "surfaceCmd", "out", "M1553BMessage", "1553", doc="Surface commands to the actuators.")
    b.port(cmd, "elevStatus", "in", "M1553BMessage", "1553", doc="Elevator actuator status.")
    b.port(cmd, "ailStatus", "in", "M1553BMessage", "1553", doc="Aileron actuator status.")
    b.port(mon, "engageElev", "out", "DiscreteLine", "disc", doc="Elevator engage enable.")
    b.port(mon, "engageAil", "out", "DiscreteLine", "disc", doc="Aileron engage enable.")
    b.port(cmd, "afdxA", "inout", "A664Message", "afdx", doc="Network A.")
    b.port(cmd, "afdxB", "inout", "A664Message", "afdx", doc="Network B.")
    b.port(cmd, "pwr", "inout", "Power28VDCBus", "pwr", kind="physical", doc="28 VDC supply.")
    b.port(mon, "pwr", "inout", "Power28VDCBus", "pwr", kind="physical", doc="28 VDC supply.")
    c = lambda a, bb, bus=None: b.connect(d, a, bb, bus)                       # noqa: E731
    for n, bp in (("airData", "airDataIn"), ("inertial", "inertialIn"), ("radioAlt", "radioAltIn")):
        c((None, bp), (cmd, n))
        c((None, bp), (mon, n))
    c((None, "sidestickPitch"), (cmd, "sidestick"))
    c((None, "sidestickPitch"), (mon, "sidestick"))
    c((None, "elevPos"), (cmd, "elevPos"))
    c((None, "ailPos"), (cmd, "ailPos"))
    c((cmd, "surfaceCmd"), (None, "surfaceCmd"))
    c((None, "elevStatus"), (cmd, "elevStatus"))
    c((None, "ailStatus"), (cmd, "ailStatus"))
    c((mon, "engageElev"), (None, "engageElev"))
    c((mon, "engageAil"), (None, "engageAil"))
    c((None, "afdxA"), (cmd, "afdxA"))
    c((None, "afdxB"), (cmd, "afdxB"))
    c((None, "pwr"), (cmd, "pwr"))
    c((None, "pwr"), (mon, "pwr"))
    # Mode logic.
    sm = attach_state_machine(d, "FccModes")
    notify_created(sm, repo)
    states = {}
    for name, kw in (("PowerUp", dict(is_initial=True, entry="run power-up built-in test")),
                     ("Standby", dict(entry="outputs passive")),
                     ("Engaged", dict(do="compute control laws")),
                     ("Degraded", dict(entry="revert to direct law")),
                     ("Passive", dict(entry="disengage actuator outputs")),
                     ("Failed", dict(is_final=True, entry="latch fault"))):
        states[name] = sm.add_state(name, **kw)
        notify_created(states[name], repo)
    for src, tgt, trig, guard in (
            ("PowerUp", "Standby", "bitPass", None), ("PowerUp", "Failed", "bitFail", None),
            ("Standby", "Engaged", "engage", "sensorsValid"), ("Engaged", "Degraded", "airDataLost", None),
            ("Degraded", "Engaged", "airDataRestored", None), ("Engaged", "Passive", "monitorMismatch", None),
            ("Degraded", "Passive", "monitorMismatch", None), ("Passive", "Standby", "reset", "onGround"),
            ("Passive", "Failed", "latentFailure", None)):
        t = sm.add_transition(states[src], states[tgt], trigger=trig, guard=guard)
        notify_created(t, repo)
    _doc(sm, "Flight control computer modes: power-up test, standby, engaged, degraded (direct law), "
             "passive after a monitor mismatch, failed.")


# (module definition, partition, DAL, period ms, window ms, memory kB, id, items, nav port)
# item: (name, DAL, language, SLOC, version)
_PARTITIONS = {
    "CoreModuleFMS": [
        ("P_FMS", "C", 25, 8, 49152, 1, [("FMS_Nav", "C", "C++", 180000, "R4.1"),
                                          ("FMS_Perf", "C", "C++", 95000, "R4.1")],
         "Flight management: navigation solution and performance."),
        ("P_FWS", "B", 25, 5, 24576, 2, [("FWS_Logic", "B", "Ada", 60000, "R3.0"),
                                          ("FWS_Alerts", "B", "Ada", 22000, "R3.0")],
         "Flight warning system: alert logic and alert generation."),
    ],
    "CoreModuleDMS": [
        ("P_DMS", "B", 20, 9, 65536, 3, [("DMS_Symbology", "B", "C", 70000, "R5.2"),
                                          ("DMS_Render", "B", "C", 110000, "R5.2")],
         "Display management: symbology and rendering for the displays."),
        ("P_MNT", "D", 100, 12, 32768, 4, [("MNT_Dataload", "D", "C", 30000, "R2.0"),
                                            ("MNT_Logger", "D", "C", 45000, "R2.0")],
         "Maintenance: data loading and fault logging."),
    ],
}


def _build_module(b: _Builder, d: PartDefinition) -> None:
    """Partitions and software items of one core processing module definition."""
    repo = b.repo
    specs = _PARTITIONS[d.name]
    parts = {}
    for pname, dal, period, window, memory, pid, items, doc in specs:
        p = b.comp(d, pname, doc=doc)
        AP.apply(repo, p, "Partition", dict(partitionId=pid, dal=dal, timeWindow=window, period=period,
                                            memory=memory, partitioningMark=False))
        parts[pname] = p
        b.port(p, "afdxA", "inout", "A664Message", "afdx", doc="Network A through the module.")
        b.port(p, "afdxB", "inout", "A664Message", "afdx", doc="Network B through the module.")
        subs = {}
        for iname, idal, lang, sloc, ver in items:
            it = b.comp(p, iname, doc=f"Software configuration item of {pname}.")
            AP.apply(repo, it, "SoftwareItem", dict(dal=idal, language=lang, sloc=sloc, version=ver))
            subs[iname] = it
        first = items[0][0]
        b.port(subs[first], "afdxA", "inout", "A664Message", "afdx", doc="Network A.")
        b.port(subs[first], "afdxB", "inout", "A664Message", "afdx", doc="Network B.")
        b.connect(p, (None, "afdxA"), (subs[first], "afdxA"))
        b.connect(p, (None, "afdxB"), (subs[first], "afdxB"))
    # Inter-partition and intra-partition ARINC 653 ports.
    comps = {c.name: c for p in parts.values() for c in A.components_of(p)}
    if d.name == "CoreModuleFMS":
        b.port(comps["FMS_Nav"], "navSolution", "out", "A653SamplingPort", "a653", doc="Navigation solution.")
        b.port(comps["FMS_Perf"], "navIn", "in", "A653SamplingPort", "a653", doc="Navigation solution.")
        b.connect(parts["P_FMS"], (comps["FMS_Nav"], "navSolution"), (comps["FMS_Perf"], "navIn"))
        b.port(parts["P_FMS"], "navOut", "out", "A653SamplingPort", "a653", doc="Navigation solution for the "
                                                                              "flight warning partition.")
        b.connect(parts["P_FMS"], (comps["FMS_Nav"], "navSolution"), (None, "navOut"))
        b.port(parts["P_FWS"], "navIn", "in", "A653SamplingPort", "a653", doc="Navigation solution.")
        b.port(comps["FWS_Logic"], "navIn", "in", "A653SamplingPort", "a653", doc="Navigation solution.")
        b.connect(parts["P_FWS"], (None, "navIn"), (comps["FWS_Logic"], "navIn"))
        b.port(comps["FWS_Alerts"], "alertsOut", "out", "A653QueuingPort", "a653", doc="Generated alerts.")
        b.port(comps["FWS_Logic"], "alertsIn", "in", "A653QueuingPort", "a653", doc="Alerts to evaluate.")
        b.connect(parts["P_FWS"], (comps["FWS_Alerts"], "alertsOut"), (comps["FWS_Logic"], "alertsIn"))
        b.connect(d, (parts["P_FMS"], "navOut"), (parts["P_FWS"], "navIn"))
    else:
        b.port(comps["DMS_Symbology"], "symbolsOut", "out", "A653SamplingPort", "a653", doc="Symbology.")
        b.port(comps["DMS_Render"], "symbolsIn", "in", "A653SamplingPort", "a653", doc="Symbology.")
        b.connect(parts["P_DMS"], (comps["DMS_Symbology"], "symbolsOut"), (comps["DMS_Render"], "symbolsIn"))
        b.port(comps["DMS_Render"], "healthOut", "out", "A653QueuingPort", "a653", doc="Display health events.")
        b.port(parts["P_DMS"], "healthOut", "out", "A653QueuingPort", "a653", doc="Display health events.")
        b.connect(parts["P_DMS"], (comps["DMS_Render"], "healthOut"), (None, "healthOut"))
        b.port(parts["P_MNT"], "healthIn", "in", "A653QueuingPort", "a653", doc="Health events to log.")
        b.port(comps["MNT_Logger"], "healthIn", "in", "A653QueuingPort", "a653", doc="Health events to log.")
        b.connect(parts["P_MNT"], (None, "healthIn"), (comps["MNT_Logger"], "healthIn"))
        b.port(comps["MNT_Dataload"], "loadOut", "out", "A653QueuingPort", "a653", doc="Loaded data records.")
        b.port(comps["MNT_Logger"], "loadIn", "in", "A653QueuingPort", "a653", doc="Loaded data records.")
        b.connect(parts["P_MNT"], (comps["MNT_Dataload"], "loadOut"), (comps["MNT_Logger"], "loadIn"))
        b.connect(d, (parts["P_DMS"], "healthOut"), (parts["P_MNT"], "healthIn"))
    # Module boundary: networks A / B reach both partitions.
    for net in (_A, _B):
        for pname in parts:
            b.connect(d, (None, net), (parts[pname], net))


def _build_cabinet(b: _Builder, cab: PartDefinition, defs: dict) -> dict:
    cpm1 = b.comp(cab, "CPM1", defs["CoreModuleFMS"], "Core processing module 1.")
    cpm2 = b.comp(cab, "CPM2", defs["CoreModuleDMS"], "Core processing module 2.")
    psm = b.comp(cab, "PSM", defs["CabinetPowerModule"], "Cabinet power module.")
    for net in (_A, _B):
        b.connect(cab, (None, net), (cpm1, net), "afdx", length=0.3)
        b.connect(cab, (None, net), (cpm2, net), "afdx", length=0.3)
    b.connect(cab, (None, "pwrA"), (psm, "inA"), "pwr", length=0.5)
    b.connect(cab, (None, "pwrB"), (psm, "inB"), "pwr", length=0.5)
    return {"CPM1": cpm1, "CPM2": cpm2, "PSM": psm}


# ---------------------------------------------------------------------------------------------
# Physical architecture
# ---------------------------------------------------------------------------------------------

def _build_physical(b: _Builder, defs: dict) -> tuple[PartDefinition, dict]:
    repo = b.repo
    phys = A.create_architecture(repo, "PhysicalArchitecture")
    _doc(phys, "Physical architecture of the avionics suite: LRUs, the IMA cabinet, networks and power.")
    c: dict[str, Element] = {}

    def add(name: str, definition: str, doc: str) -> None:
        c[name] = b.comp(phys, name, defs[definition], doc)
    for n in ("1", "2"):
        add(f"ADC{n}", "AirDataComputer", f"Air data computer {n}.")
    for n in ("1", "2"):
        add(f"IRU{n}", "InertialReferenceUnit", f"Inertial reference unit {n}.")
    for n in ("1", "2"):
        add(f"RA{n}", "RadioAltimeter", f"Radio altimeter {n}.")
    for n in ("1", "2"):
        add(f"GPS{n}", "GnssReceiver", f"GNSS receiver {n}.")
    add("SidestickCapt", "Sidestick", "Captain sidestick.")
    add("SidestickFO", "Sidestick", "First officer sidestick.")
    add("RDC1", "RemoteDataConcentrator", "Remote data concentrator 1 (left side sensors).")
    add("RDC2", "RemoteDataConcentrator", "Remote data concentrator 2 (right side sensors).")
    add("SW_A", "AfdxSwitch", "AFDX switch, network A.")
    add("SW_B", "AfdxSwitch", "AFDX switch, network B.")
    add("IMA_Cabinet", "ImaCabinet", "IMA cabinet hosting the flight management, flight warning, display "
                                     "management and maintenance partitions.")
    add("FCC_L", "FlightControlComputer", "Flight control computer, left channel.")
    add("FCC_R", "FlightControlComputer", "Flight control computer, right channel.")
    add("PFD", "DisplayUnit", "Primary flight display.")
    add("ND", "DisplayUnit", "Navigation display.")
    add("EICAS", "DisplayUnit", "Engine indication and crew alerting display.")
    add("ElevAct", "ElevatorActuator", "Elevator actuator.")
    add("AilAct", "AileronActuator", "Aileron actuator.")
    add("PSU1", "PowerSupplyUnit", "28 VDC power supply 1 (essential bus).")
    add("PSU2", "PowerSupplyUnit", "28 VDC power supply 2 (normal bus).")

    k = [0]

    def ln(base: float = 8.0) -> float:
        k[0] += 1
        return round(base + 2.5 * (k[0] % 7), 1)
    con = lambda a, bb, bus, base=8.0: b.connect(phys, a, bb, bus, length=ln(base))   # noqa: E731
    # ARINC 429: sensors to the concentrators and straight to the flight control computers.
    for s, side in (("1", "L"), ("2", "R")):
        rdc, fcc = c[f"RDC{s}"], c[f"FCC_{side}"]
        con((c[f"ADC{s}"], "airData"), (rdc, "a429In1"), "a429")
        con((c[f"IRU{s}"], "inertial"), (rdc, "a429In2"), "a429")
        con((c[f"RA{s}"], "radioAlt"), (rdc, "a429In3"), "a429")
        con((c[f"GPS{s}"], "gnss"), (rdc, "a429In4"), "a429")
        con((c[f"ADC{s}"], "airData"), (fcc, "airDataIn"), "a429")
        con((c[f"IRU{s}"], "inertial"), (fcc, "inertialIn"), "a429")
        con((c[f"RA{s}"], "radioAlt"), (fcc, "radioAltIn"), "a429")
    # Sidestick: pitch synchro to the same-side FCC, takeover discrete to the concentrator.
    for stick, rdc, fcc in (("SidestickCapt", "RDC1", "FCC_L"), ("SidestickFO", "RDC2", "FCC_R")):
        con((c[stick], "pitchPos"), (c[fcc], "sidestickPitch"), "analog", 4.0)
        con((c[stick], "takeover"), (c[rdc], "discreteIn1"), "disc", 4.0)
    # Actuators: MIL-STD-1553B commands and status, engage discretes, position feedback.
    for fcc, side in (("FCC_L", "L"), ("FCC_R", "R")):
        for act, pos, fb, status in (("ElevAct", "lvdt", "elevPos", "elevStatus"),
                                     ("AilAct", "pos", "ailPos", "ailStatus")):
            con((c[fcc], "surfaceCmd"), (c[act], f"cmd{side}"), "1553", 12.0)
            con((c[act], f"status{side}"), (c[fcc], status), "1553", 12.0)
            con((c[fcc], "engageElev" if act == "ElevAct" else "engageAil"), (c[act], f"engage{side}"), "disc", 12.0)
            con((c[act], f"{pos}{side}"), (c[fcc], fb), "analog", 12.0)
    # AFDX: every end system on both networks.
    for sw, net in (("SW_A", _A), ("SW_B", _B)):
        ends = [("RDC1", net), ("RDC2", net), ("IMA_Cabinet", net), ("FCC_L", net), ("FCC_R", net),
                ("PFD", net), ("ND", net), ("EICAS", net)]
        for i, (name, port) in enumerate(ends, 1):
            con((c[sw], f"p{i}"), (c[name], port), "afdx", 20.0)
    # 28 VDC: PSU1 feeds the left / essential loads, PSU2 the right / normal ones.
    loads1 = [("ADC1", "pwr"), ("IRU1", "pwr"), ("RA1", "pwr"), ("GPS1", "pwr"), ("RDC1", "pwr"), ("SW_A", "pwr"),
              ("FCC_L", "pwr"), ("IMA_Cabinet", "pwrA"), ("PFD", "pwr"), ("EICAS", "pwr"),
              ("ElevAct", "pwrL"), ("AilAct", "pwrL")]
    loads2 = [("ADC2", "pwr"), ("IRU2", "pwr"), ("RA2", "pwr"), ("GPS2", "pwr"), ("RDC2", "pwr"), ("SW_B", "pwr"),
              ("FCC_R", "pwr"), ("IMA_Cabinet", "pwrB"), ("ND", "pwr"), ("ElevAct", "pwrR"), ("AilAct", "pwrR")]
    for psu, loads in (("PSU1", loads1), ("PSU2", loads2)):
        for name, port in loads:
            con((c[psu], "feed"), (c[name], port), "pwr", 6.0)
    return phys, c


# ---------------------------------------------------------------------------------------------
# Functional and logical architectures
# ---------------------------------------------------------------------------------------------

_FUNCTIONS: dict[str, list[tuple]] = {      # function -> ports (name, dir, interface, kind)
    "ProvideAirData": [("airData", "out", "A429AirData")],
    "ProvideAttitude": [("inertial", "out", "A429Inertial")],
    "MeasureRadioAltitude": [("radioAlt", "out", "A429RadioAltitude")],
    "DeterminePosition": [("gnss", "out", "A429Gnss")],
    "ManageFlight": [("airData", "in", "A429AirData"), ("inertial", "in", "A429Inertial"),
                     ("gnss", "in", "A429Gnss"), ("guidance", "out", "A429Navigation")],
    "ComputeFlightControlLaws": [("airData", "in", "A429AirData"), ("inertial", "in", "A429Inertial"),
                                 ("radioAlt", "in", "A429RadioAltitude"), ("guidance", "in", "A429Navigation"),
                                 ("surfaceCmd", "out", "M1553BMessage")],
    "MonitorFlightControl": [("surfaceCmd", "in", "M1553BMessage"), ("engage", "out", "DiscreteLine")],
    "DriveFlightSurfaces": [("surfaceCmd", "in", "M1553BMessage"), ("engage", "in", "DiscreteLine")],
    "DisplayFlightData": [("airData", "in", "A429AirData"), ("inertial", "in", "A429Inertial"),
                          ("guidance", "in", "A429Navigation")],
    "AnnunciateAlerts": [("engage", "in", "DiscreteLine")],
    "DistributePower": [("pwr", "inout", "Power28VDCBus")],
    "ProvideDataNetwork": [("pwr", "inout", "Power28VDCBus"), ("afdx", "inout", "A664Message")],
    "LogMaintenanceData": [("afdx", "inout", "A664Message")],
}
_FLOWS: list[tuple] = [   # (function, port) -> (function, port)
    ("ProvideAirData", "airData", "ManageFlight", "airData"),
    ("ProvideAirData", "airData", "ComputeFlightControlLaws", "airData"),
    ("ProvideAirData", "airData", "DisplayFlightData", "airData"),
    ("ProvideAttitude", "inertial", "ManageFlight", "inertial"),
    ("ProvideAttitude", "inertial", "ComputeFlightControlLaws", "inertial"),
    ("ProvideAttitude", "inertial", "DisplayFlightData", "inertial"),
    ("MeasureRadioAltitude", "radioAlt", "ComputeFlightControlLaws", "radioAlt"),
    ("DeterminePosition", "gnss", "ManageFlight", "gnss"),
    ("ManageFlight", "guidance", "ComputeFlightControlLaws", "guidance"),
    ("ManageFlight", "guidance", "DisplayFlightData", "guidance"),
    ("ComputeFlightControlLaws", "surfaceCmd", "MonitorFlightControl", "surfaceCmd"),
    ("ComputeFlightControlLaws", "surfaceCmd", "DriveFlightSurfaces", "surfaceCmd"),
    ("MonitorFlightControl", "engage", "DriveFlightSurfaces", "engage"),
    ("MonitorFlightControl", "engage", "AnnunciateAlerts", "engage"),
    ("DistributePower", "pwr", "ProvideDataNetwork", "pwr"),
    ("ProvideDataNetwork", "afdx", "LogMaintenanceData", "afdx"),
]
_FUNCTION_DOC = {
    "ProvideAirData": "Measure and provide pressure altitude, airspeeds, Mach, vertical speed and air temperature.",
    "ProvideAttitude": "Provide attitude, heading, accelerations and inertial position.",
    "MeasureRadioAltitude": "Measure the height above ground.",
    "DeterminePosition": "Determine the aircraft position from satellite navigation.",
    "ManageFlight": "Manage the flight plan and compute lateral and vertical guidance.",
    "ComputeFlightControlLaws": "Compute the pitch and roll control laws and the surface commands.",
    "MonitorFlightControl": "Monitor the control law computation and enable the actuators only when it agrees.",
    "DriveFlightSurfaces": "Position the flight control surfaces.",
    "DisplayFlightData": "Display primary flight and navigation data to the crew.",
    "AnnunciateAlerts": "Annunciate flight control and system alerts to the crew.",
    "DistributePower": "Distribute 28 VDC power to the avionics.",
    "ProvideDataNetwork": "Provide redundant data communication between the avionics.",
    "LogMaintenanceData": "Record maintenance events and load data.",
}
#: Logical architecture item of each function (several functions may share an item).
LOGICAL_OF = {
    "ProvideAirData": "AirDataSystem", "ProvideAttitude": "InertialReferenceSystem",
    "MeasureRadioAltitude": "RadioAltimetry", "DeterminePosition": "NavigationSystem",
    "ManageFlight": "FlightManagement", "ComputeFlightControlLaws": "FlightControl",
    "MonitorFlightControl": "FlightControlMonitoring", "DriveFlightSurfaces": "Actuation",
    "DisplayFlightData": "DisplaySystem", "AnnunciateAlerts": "DisplaySystem",
    "DistributePower": "PowerSystem", "ProvideDataNetwork": "DataNetwork",
    "LogMaintenanceData": "MaintenanceSystem",
}
#: Assigned level (FDAL) of each logical item.
LOGICAL_DAL = {
    "AirDataSystem": "A", "InertialReferenceSystem": "B", "RadioAltimetry": "B", "NavigationSystem": "C",
    "FlightManagement": "C", "FlightControl": "A", "FlightControlMonitoring": "A", "Actuation": "A",
    "DisplaySystem": "B", "PowerSystem": "B", "DataNetwork": "B", "MaintenanceSystem": "E",
}


def _build_flow_architecture(b: _Builder, name: str, mapping: Optional[dict], doc: str) -> tuple:
    """A functional (``mapping`` None) or logical architecture; returns (architecture, {name: component})."""
    repo = b.repo
    arch = A.create_architecture(repo, name)
    _doc(arch, doc)
    nodes: dict[str, list[tuple]] = {}
    for fn, ports in _FUNCTIONS.items():
        node = mapping[fn] if mapping else fn
        have = nodes.setdefault(node, [])
        for p in ports:
            if all(p[0] != q[0] for q in have):
                have.append(p)
    comps: dict[str, Element] = {}
    for node, ports in nodes.items():
        if mapping:
            text = " and ".join(_FUNCTION_DOC[f].rstrip(".").lower() for f, n in mapping.items() if n == node)
            text = f"Logical item: {text}."
        else:
            text = _FUNCTION_DOC[node]
        comps[node] = b.comp(arch, node, doc=text)
        for pname, direction, iface in ports:
            kind = "physical" if iface.startswith("Power") else "data"
            bus = "pwr" if kind == "physical" else ("afdx" if iface == "A664Message" else
                  "1553" if iface.startswith("M1553") else "disc" if iface.startswith("Discrete") else "a429")
            b.port(comps[node], pname, direction, iface, bus, kind=kind, tag=False,
                   doc=f"{_DIR_TEXT[direction]} {iface}.")
    seen = set()
    for sf, sp, df, dp in _FLOWS:
        s, d = (mapping[sf], mapping[df]) if mapping else (sf, df)
        if (s, sp, d, dp) in seen or s == d:
            continue
        seen.add((s, sp, d, dp))
        b.connect(arch, (comps[s], sp), (comps[d], dp))
    return arch, comps


# ---------------------------------------------------------------------------------------------
# Requirements, test cases and links
# ---------------------------------------------------------------------------------------------
# requirement: (summary, text, type, method, dal, safety, derived, implemented by [component names], verified by [tests])
# A string entry in `children` introduces a group (summary, text) holding the following requirements.

def Q(summary, text, kind, method, dal, impl=(), tests=(), *, safety=False, derived=False, rationale=""):
    return dict(summary=summary, text=text, kind=kind, method=method, dal=dal, impl=list(impl),
                tests=list(tests), safety=safety, derived=derived, rationale=rationale, children=[])


def G(summary, text, *children):
    return dict(summary=summary, text=text or f"{summary} requirements.", kind="other", method=None, dal="E", impl=[], tests=[],
                safety=False, derived=False, rationale="", children=list(children))


SYS_REQS = [
    G("Air data", "Air data for flight control, flight management and displays.",
      Q("Provide air data", "The air data system shall provide pressure altitude, computed airspeed, Mach number, "
        "vertical speed and total and static air temperature to the flight control, flight management and "
        "display systems at 20 Hz.", "functional", "test", "A", ["AirDataSystem"], ["TC-AirDataOutput"],
        safety=True),
      Q("Air data accuracy", "The air data system shall provide altitude to within 30 ft and airspeed to within "
        "2 kt over the flight envelope.", "performance", "test", "B", ["AirDataSystem"], ["TC-AirDataAccuracy"]),
      Q("Detect erroneous air data", "An erroneous air data output shall be detected by comparison of two "
        "independent channels and annunciated within 1 second.", "safety", "analysis", "A",
        ["AirDataSystem", "FlightControlMonitoring"], [], safety=True)),
    G("Inertial reference", "Attitude, heading and inertial position.",
      Q("Provide attitude and heading", "The inertial reference system shall provide pitch, roll, heading, "
        "accelerations and position at 50 Hz.", "functional", "test", "B", ["InertialReferenceSystem"],
        ["TC-IruOutput"]),
      Q("Attitude accuracy", "Pitch and roll shall be accurate to within 0.2 degrees (1 sigma).", "performance",
        "analysis", "B", ["InertialReferenceSystem"], ["TC-IruAccuracy"])),
    G("Navigation and altitude", "GNSS and radio altitude.",
      Q("Provide GNSS position", "The navigation system shall provide GNSS position and ground speed at 5 Hz.",
        "functional", "test", "C", ["NavigationSystem"], ["TC-GnssOutput"]),
      Q("GNSS integrity monitoring", "The navigation system shall monitor the integrity of the GNSS position and "
        "annunciate loss of integrity within 10 seconds.", "safety", "analysis", "C", [], [], safety=True),
      Q("Provide radio altitude", "The radio altimeter system shall provide radio altitude below 2500 ft at 20 Hz.",
        "functional", "test", "B", ["RadioAltimetry"], ["TC-RadioAltOutput"])),
    G("Flight management and display", "",
      Q("Compute flight plan guidance", "The flight management function shall compute lateral and vertical "
        "guidance from the active flight plan at 5 Hz.", "functional", "test", "C", ["FlightManagement"],
        ["TC-Guidance"]),
      Q("Display primary flight data", "The display system shall present attitude, airspeed, altitude and "
        "heading on the PFD and the navigation data on the ND.", "functional", "test", "B", ["DisplaySystem"],
        ["TC-PfdSymbology"]),
      Q("Annunciate alerts", "The display system shall annunciate flight control and system alerts within "
        "1 second of their detection.", "functional", "test", "C", ["DisplaySystem"], ["TC-AlertTiming"])),
    G("Flight control", "Fly-by-wire control laws and their monitoring.",
      Q("Compute control laws", "The flight control system shall compute the pitch and roll control laws and "
        "command the surface actuators at 40 Hz.", "functional", "test", "A", ["FlightControl"],
        ["TC-FccOutput"], safety=True),
      Q("Monitor the command lane", "Each flight control channel shall be monitored by a dissimilar monitor; "
        "the probability of an undetected erroneous surface command shall be less than 1E-9 per flight hour.",
        "safety", "analysis", "A", ["FlightControlMonitoring"], ["TC-MonitorCoverage"], safety=True),
      Q("Command latency", "The latency from sidestick movement to surface command shall not exceed 40 ms.",
        "performance", "test", "A", ["FlightControl", "Actuation"], ["TC-FccLatency"], safety=True),
      Q("Reversion on air data loss", "On loss of air data the flight control system shall revert to the direct "
        "law and annunciate the reversion.", "functional", "test", "A", ["FlightControl"], ["TC-Reversion"],
        derived=True, safety=True, rationale="Introduced by the flight control design: the control laws "
        "need air data, so a defined reversion is required (fed back to the system safety assessment).")),
    G("Platform", "Network, power and integration.",
      Q("Redundant networks", "Loss of either AFDX network shall not cause the loss of any function.",
        "design-constraint", "analysis", "B", ["DataNetwork"], ["TC-NetworkRedundancy"], safety=True),
      Q("Robust partitioning", "Partitions of different levels hosted in the IMA cabinet shall be robustly "
        "partitioned (ARINC 653).", "design-constraint", "analysis", "B", ["IMA_Cabinet"], ["TC-Partitioning"], safety=True),
      Q("Redundant power", "Loss of one 28 VDC supply shall not cause the loss of any function.",
        "safety", "analysis", "B", ["PowerSystem"], ["TC-PowerLoss"], safety=True),
      Q("Maintenance logging", "The maintenance system shall record detected faults with time and flight phase.",
        "functional", "test", "E", ["MaintenanceSystem"], ["TC-FaultLog"])),
    G("Environment", "",
      Q("Environmental qualification", "The equipment shall be qualified to RTCA DO-160G for the categories of "
        "its equipment specification.", "environmental", "test", "D", [], [])),
]

ITEM_REQS = [
    G("Air data computer", "",
      Q("ADC output rate", "The ADC shall transmit the air data labels at 20 Hz on ARINC 429 high speed.",
        "interface", "test", "B", ["ADC1", "ADC2"], ["TC-AirDataOutput"]),
      Q("ADC reliability", "The ADC shall have an MTBF of at least 40000 hours.", "performance", "analysis", "D",
        ["ADC1", "ADC2"], [])),
    G("Flight control computer", "",
      Q("Fail-passive monitor", "On a mismatch between the command and monitor lanes the FCC shall remove the "
        "actuator engage discretes within 20 ms.", "safety", "test", "A", ["FCC_L", "FCC_R"],
        ["TC-MonitorCoverage"], safety=True),
      Q("Built-in test coverage", "Built-in test shall detect at least 98 percent of the failures that affect "
        "the control law computation.", "performance", "test", "A", ["FCC_L", "FCC_R"], ["TC-FccBit"],
        safety=True),
      Q("FCC execution frame", "The FCC shall complete the control law computation in a 25 ms frame.",
        "performance", "test", "A", ["FCC_L", "FCC_R"], ["TC-FccLatency"])),
    G("Network", "",
      Q("Switch latency", "The AFDX switch shall forward a frame within 150 microseconds.", "performance",
        "test", "B", ["SW_A", "SW_B"], ["TC-NetworkRedundancy"]),
      Q("Concentrator conversion", "The RDC shall convert ARINC 429 labels to AFDX messages within 5 ms.",
        "performance", "test", "B", ["RDC1", "RDC2"], [])),
    G("Display and power", "",
      Q("Display refresh", "The display unit shall refresh the PFD symbology at 30 Hz or better.", "performance",
        "test", "B", ["PFD", "ND"], ["TC-PfdSymbology"]),
      Q("Power hold-up", "The power supply shall hold its output for 50 ms after loss of input power.",
        "performance", "test", "B", ["PSU1", "PSU2"], ["TC-PowerLoss"])),
]

HLR_REQS = [
    G("Flight control software", "",
      Q("Pitch control law", "The command lane shall compute the pitch demand from the sidestick, the air data "
        "and the inertial data every 25 ms.", "functional", "test", "A", ["CommandLane"], ["TC-FccOutput"]),
      Q("Invalid input handling", "The command lane shall treat an input as invalid when its status is not "
        "normal operation or its age exceeds 100 ms.", "functional", "test", "A", ["CommandLane"],
        ["TC-Reversion"], safety=True),
      Q("Monitor comparison", "The monitor lane shall compare the commanded surface positions with its own "
        "computation and clear the engage discretes when they differ by more than the threshold.",
        "safety", "test", "A", ["MonitorLane"], ["TC-MonitorCoverage"], safety=True)),
    G("Flight management software", "",
      Q("Guidance computation", "The navigation software shall compute the cross-track error and the track "
        "angle error every 200 ms.", "functional", "test", "C", ["FMS_Nav"], ["TC-Guidance"]),
      Q("Software memory budget", "The flight management partition shall use no more than 48 MB of memory.",
        "design-constraint", "test", "C", ["FMS_Perf"], [])),
]

LLR_REQS = [
    G("Command lane algorithms", "",
      Q("Pitch law gain schedule", "The function pitch_demand shall interpolate the gain table linearly "
        "against computed airspeed.", "functional", "test", "A", ["CommandLane"], ["TC-FccOutput"]),
      Q("Output saturation", "The function pitch_demand shall saturate its result to the surface limits.",
        "functional", "test", "A", ["CommandLane"], ["TC-FccOutput"], safety=True),
      Q("Input age check", "The function input_valid shall reject an input older than 100 ms.", "functional",
        "test", "A", ["CommandLane"], ["TC-Reversion"]),
      Q("Division guard", "The function gain_schedule shall not divide by a value with magnitude below 1E-6.",
        "functional", "test", "A", ["CommandLane"], [], safety=True),
      Q("Static memory", "The command lane source code shall use static allocation only.", "design-constraint",
        "test", "A", ["CommandLane"], ["TC-FccOutput"])),
]

# test case -> result (passed / failed / unexecuted)
TEST_CASES = {
    "TC-AirDataOutput": "passed", "TC-AirDataAccuracy": "passed", "TC-IruOutput": "passed",
    "TC-IruAccuracy": "unexecuted", "TC-GnssOutput": "passed", "TC-RadioAltOutput": "passed",
    "TC-Guidance": "passed", "TC-PfdSymbology": "passed", "TC-AlertTiming": "passed",
    "TC-FccOutput": "passed", "TC-MonitorCoverage": "passed", "TC-FccLatency": "failed",
    "TC-Reversion": "passed", "TC-FccBit": "passed", "TC-NetworkRedundancy": "unexecuted",
    "TC-Partitioning": "passed", "TC-PowerLoss": "passed", "TC-FaultLog": "passed",
}


def _build_requirements(b: _Builder, targets: dict) -> dict:
    """Create the five sets; ``targets`` maps component names to the elements that implement."""
    repo = b.repo
    out = {}
    tests: dict[str, Element] = {}
    sets = []
    for key, name, prefix, level, desc, reqs in (
            ("sys", "SystemRequirements", "SYS-", "System", "ARP4754A system requirements of the avionics suite.", SYS_REQS),
            ("itm", "ItemRequirements", "ITM-", "Item", "ARP4754A item requirements allocated to the equipment.", ITEM_REQS),
            ("hlr", "SoftwareHighLevelRequirements", "HLR-", "HLR", "DO-178C high-level requirements.", HLR_REQS),
            ("llr", "SoftwareLowLevelRequirements", "LLR-", "LLR", "DO-178C low-level requirements.", LLR_REQS)):
        rset = rq.create_requirement_set(repo, name, prefix=prefix, description=desc)
        sets.append((key, rset, level, reqs))
        out[key] = rset
    created: dict[str, Element] = {}
    pending: list[tuple[str, Element]] = []

    def add(parent: Element, entry: dict, level: str) -> None:
        fields = {"summary": entry["summary"], "description": entry["text"], "type": entry["kind"]}
        if entry["rationale"]:
            fields["rationale"] = entry["rationale"]
        if entry["method"]:
            fields["verification_method"] = entry["method"]
        req = rq.add_requirement(repo, parent, fields)
        AP.apply(repo, req, "AvionicsRequirement", dict(
            level=level, dal=entry["dal"], derived=entry["derived"], safetyRelated=entry["safety"],
            verificationMethod=(entry["method"] or "analysis").capitalize()))
        created[req.req_id] = req
        for comp in entry["impl"]:
            rq.create_trace_link(repo, "implement", targets[comp], req)
        pending.extend((tc, req) for tc in entry["tests"])
        for child in entry["children"]:
            add(req, child, level)
    for _key, rset, level, reqs in sets:
        for entry in reqs:
            add(rset, entry, level)
    # Test cases live in the system set, after its requirements (tables keep that order).
    for tc_name, result in TEST_CASES.items():
        tests[tc_name] = rq.add_test_case(repo, out["sys"], tc_name, result=result,
                                          description=f"Verification case {tc_name[3:]}.")
    for tc_name, req in pending:
        rq.create_trace_link(repo, "verify", tests[tc_name], req)
    return {"sets": out, "tests": tests, "requirements": created}


def _trace_levels(repo, reqs: dict) -> None:
    """Derive / refine links between the levels, by summary."""
    by = {(r.req_id.split("-")[0], r.name): r for r in reqs.values()}
    pairs = [("ITM", "ADC output rate", "SYS", "Provide air data", "derive"),
             ("ITM", "Fail-passive monitor", "SYS", "Monitor the command lane", "derive"),
             ("ITM", "Built-in test coverage", "SYS", "Compute control laws", "derive"),
             ("ITM", "FCC execution frame", "SYS", "Command latency", "derive"),
             ("ITM", "Switch latency", "SYS", "Redundant networks", "derive"),
             ("ITM", "Display refresh", "SYS", "Display primary flight data", "derive"),
             ("ITM", "Power hold-up", "SYS", "Redundant power", "derive"),
             ("HLR", "Pitch control law", "ITM", "FCC execution frame", "derive"),
             ("HLR", "Invalid input handling", "SYS", "Reversion on air data loss", "derive"),
             ("HLR", "Monitor comparison", "ITM", "Fail-passive monitor", "derive"),
             ("HLR", "Guidance computation", "SYS", "Compute flight plan guidance", "derive"),
             ("LLR", "Pitch law gain schedule", "HLR", "Pitch control law", "refine"),
             ("LLR", "Output saturation", "HLR", "Pitch control law", "refine"),
             ("LLR", "Input age check", "HLR", "Invalid input handling", "refine"),
             ("LLR", "Division guard", "HLR", "Pitch control law", "refine"),
             ("LLR", "Static memory", "HLR", "Pitch control law", "refine")]
    for sp, sn, dp, dn, kind in pairs:
        rq.create_trace_link(repo, kind, by[(sp, sn)], by[(dp, dn)])


# ---------------------------------------------------------------------------------------------
# FHA and allocation
# ---------------------------------------------------------------------------------------------

# function, failure condition, phases, effect, classification
FHA_ROWS = [
    ("ProvideAirData", "Total loss of air data", "All",
     "Loss of airspeed and altitude indication; flight control reverts to direct law.", "Hazardous"),
    ("ProvideAirData", "Erroneous air data on all channels, undetected", "All",
     "Misleading airspeed and altitude; possible loss of control.", "Catastrophic"),
    ("ProvideAttitude", "Loss of attitude and heading", "All",
     "Loss of primary attitude reference; large reduction in safety margins.", "Hazardous"),
    ("ProvideAttitude", "Erroneous attitude on one channel, detected", "Cruise",
     "Cross-comparison annunciates the failure; crew selects the other source.", "Minor"),
    ("MeasureRadioAltitude", "Erroneous radio altitude during approach", "Approach,Landing",
     "Misleading height above ground during autoland; high crew workload.", "Hazardous"),
    ("MeasureRadioAltitude", "Loss of radio altitude", "Approach,Landing",
     "Loss of height indication; crew uses barometric altitude.", "Major"),
    ("DeterminePosition", "Loss of GNSS position", "All", "Navigation continues on inertial reference.", "Minor"),
    ("DeterminePosition", "Erroneous GNSS position", "Cruise,Descent,Approach",
     "Position error grows undetected; increased crew workload.", "Major"),
    ("ManageFlight", "Loss of flight management", "All",
     "Crew navigates with the basic modes; significant workload increase.", "Major"),
    ("ComputeFlightControlLaws", "Loss of flight control computation, all channels", "All",
     "Loss of electronic flight control; possible loss of control.", "Catastrophic"),
    ("ComputeFlightControlLaws", "Erroneous flight control command, undetected", "All",
     "Uncommanded surface movement; possible loss of control.", "Catastrophic"),
    ("MonitorFlightControl", "Loss of command lane monitoring", "All",
     "Latent: an erroneous command would no longer be detected.", "Hazardous"),
    ("DriveFlightSurfaces", "Uncommanded surface movement", "All",
     "Loss of control authority; possible loss of control.", "Catastrophic"),
    ("DisplayFlightData", "Loss of all primary displays", "All",
     "Loss of primary flight data; crew uses the standby instruments.", "Hazardous"),
    ("DisplayFlightData", "Misleading primary flight data", "All",
     "Crew acts on wrong data; large reduction in safety margins.", "Hazardous"),
    ("AnnunciateAlerts", "Loss of alert annunciation", "All", "Crew unaware of system failures; workload.", "Major"),
    ("DistributePower", "Loss of both 28 VDC supplies", "All",
     "Loss of all avionics; only standby instruments remain.", "Hazardous"),
    ("DistributePower", "Loss of one 28 VDC supply", "All", "Redundant supply carries the load.", "Minor"),
    ("ProvideDataNetwork", "Loss of both AFDX networks", "All",
     "Loss of communication between the avionics; reversion to direct modes.", "Hazardous"),
    ("ProvideDataNetwork", "Loss of one AFDX network", "All", "The other network carries all traffic.", "Minor"),
    ("LogMaintenanceData", "Loss of maintenance data", "Ground",
     "Fault history lost; troubleshooting takes longer.", "No Safety Effect"),
]


def _build_allocations(b: _Builder, func: dict, logical: dict, phys: dict, hw: dict) -> dict:
    repo = b.repo
    f_arch = next(iter(func.values())).owner
    l_arch = next(iter(logical.values())).owner
    p_arch = next(iter(phys.values())).owner
    f2l = AL.create_allocation_set(repo, "FunctionsToLogical", f_arch, l_arch, scenario_name="Baseline",
                                   description="Functions to the logical items that realise them.",
                                   require_complete_coverage=True)
    l2p = AL.create_allocation_set(repo, "LogicalToPhysical", l_arch, p_arch, scenario_name="Baseline",
                                   description="Logical items to hardware and IMA partitions.",
                                   require_complete_coverage=True)
    n = 0
    for fn, lg in LOGICAL_OF.items():
        AL.allocate(repo, f2l.scenarios[0], func[fn], logical[lg])
        n += 1
    mapping = {
        "AirDataSystem": ["ADC1", "ADC2"], "InertialReferenceSystem": ["IRU1", "IRU2"],
        "RadioAltimetry": ["RA1", "RA2"], "NavigationSystem": ["GPS1", "GPS2"],
        "FlightManagement": ["P_FMS"], "FlightControl": ["FCC_L", "FCC_R"],
        "FlightControlMonitoring": ["MonitorLane"], "Actuation": ["ElevAct", "AilAct"],
        "DisplaySystem": ["PFD", "ND", "EICAS", "P_DMS"], "PowerSystem": ["PSU1", "PSU2"],
        "DataNetwork": ["SW_A", "SW_B", "RDC1", "RDC2"], "MaintenanceSystem": ["P_MNT"],
    }
    for lg, targets in mapping.items():
        for t in targets:
            AL.allocate(repo, l2p.scenarios[0], logical[lg], hw[t])
            n += 1
    return {"f2l": f2l, "l2p": l2p, "allocations": n}


# ---------------------------------------------------------------------------------------------
# The example
# ---------------------------------------------------------------------------------------------

def _all_compositions(repo) -> list[Element]:
    out = []
    for e in repo.root_package.walk():
        if isinstance(e, PartDefinition) or e.kind == "PartUsage":
            if [c for c in A.components_of(e) if c.owner is e]:
                out.append(e)
    return out


def build_example(name: str = EXAMPLE_NAME, *, repo: Optional[Repository] = None) -> Repository:
    """The complete IMA avionics example (see the module documentation)."""
    repo = repo or Repository(name)
    A.set_model_type(repo, "system")
    b = _Builder(repo)
    AP.ensure_profile(repo)
    interfaces_lib.import_library(repo)

    defs = _define_equipment(b)
    # Software side: FCC lanes + modes, IMA partitions.
    _build_fcc(b, defs["FlightControlComputer"])
    for d in ("CoreModuleFMS", "CoreModuleDMS"):
        _build_module(b, defs[d])
    cabinet_parts = _build_cabinet(b, defs["ImaCabinet"], defs)
    phys, pc = _build_physical(b, defs)
    func_arch, func = _build_flow_architecture(
        b, "FunctionalArchitecture", None, "Functions of the avionics suite and the data flowing between them.")
    log_arch, logical = _build_flow_architecture(
        b, "LogicalArchitecture", LOGICAL_OF,
        "Logical items that realise the functions, with their assigned development assurance levels.")
    for item, dal in LOGICAL_DAL.items():
        AP.apply(repo, logical[item], "LogicalItem", dict(dal=dal))

    # Hardware / software targets by name, for links and allocations.
    parts = {c.name: c for d in (defs["CoreModuleFMS"], defs["CoreModuleDMS"]) for c in A.components_of(d)}
    sw = {c.name: c for p in parts.values() for c in A.components_of(p)}
    lanes = {c.name: c for c in A.components_of(defs["FlightControlComputer"])}
    hw = {**pc, **parts, **{"MonitorLane": lanes["MonitorLane"]}}
    targets = {**pc, **logical, **sw, **lanes}

    req = _build_requirements(b, targets)
    _trace_levels(repo, req["requirements"])
    alloc = _build_allocations(b, func, logical, pc, hw)

    rows = []
    for fn, text, phases, effect, cls in FHA_ROWS:
        rows.append(SF.add_fha_row(repo, function=func[fn], failure_condition=text, flight_phase=phases,
                                   effect=effect, classification=cls))

    # Layout: Arrange every composition.
    for comp in _all_compositions(repo):
        A.auto_layout(repo, comp)
    return repo


def describe_example(repo: Repository) -> dict:
    """Counts of what the example holds (used by the template list, the HTTP API and the tests)."""
    from engine.structure import component_tree, connectors_of, ports_of
    arch = next((e for e in repo.root_package.owned_elements
                 if isinstance(e, PartDefinition) and e.name == "PhysicalArchitecture"), None)
    sets = rq.requirement_sets(repo)
    reqs = rq.all_requirements(repo)
    tests = [e for e in repo.root_package.walk() if rq.is_test_case(e)]
    return {
        "architectures": [e.name for e in repo.root_package.owned_elements
                          if isinstance(e, PartDefinition) and e.name.endswith("Architecture")],
        "physical_components": len(list(component_tree(arch))) - 1 if arch else 0,
        "requirement_sets": [s.name for s in sets], "requirements": len(reqs), "test_cases": len(tests),
        "fha_rows": len(SF.fha_rows(repo)),
        "allocation_sets": [s.name for s in AL.allocation_sets(repo)],
        "interfaces": len(I.shared_items(repo)),
    }


if __name__ == "__main__":                                   # pragma: no cover
    out = sys.argv[1] if len(sys.argv) > 1 else "ima_avionics.json"
    build_example().save(out)
    print(f"saved {out}")
