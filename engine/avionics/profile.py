"""The ``Avionics`` profile: stereotypes for equipment, IMA modules, partitions, software, buses.

The profile is created through :mod:`engine.profiles` (so every check, unit conversion and
undo rule of the Profile Editor applies) and can be extended or edited afterwards in the
Profile Editor like any other profile. :func:`ensure_profile` is idempotent: it creates what
is missing and never changes a stereotype or property that already exists.

Stereotype tree::

    Equipment (abstract)             mass, power, MTBF / FIT, part number, ATA, DAL, TSO, DO-160
    +-- LRU                          a generic line replaceable unit (default port: DataBusPort)
    |   +-- Sensor, Display, Actuator, Computer, Switch, Gateway, PowerSupply
    +-- LRM                          IMA line replaceable module (partitioning mark)
    Partition                        ARINC 653 partition: DAL, time window, period, memory
    SoftwareItem                     CSCI: DAL, language, SLOC
    LogicalItem                      logical (architecture level) item with an assigned DAL
    DataBusPort    (Port)            bus type, label / virtual link / RT address
    BusLink        (Connector)       bus type, bandwidth, latency, length
    AvionicsRequirement (Requirement) level, DAL, derived, safety related, verification method

An element carries at most one *Equipment*-derived stereotype (a second one would repeat
every Equipment property); pick the most specific one (Computer, Sensor, ...).

Reading values: :func:`read` and :func:`effective` go through
``engine.profiles.get_property_value`` only. ``effective`` looks at the element itself and,
for a component usage typed by a definition, at its definition: equipment values live on
the part definitions (reference components), so ``ADC1 : AirDataComputer`` has the DAL of
``AirDataComputer``.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Optional

from kerml.elements import Element
from kerml.stereotypes import Profile, Stereotype, application_of, stereotypes_on

from engine import profiles as P
from engine.structure import definition_of

__all__ = [
    "PROFILE_NAME", "DALS", "DAL_DEFAULT", "BUS_TYPES", "STEREOTYPES", "EQUIPMENT_STEREOTYPES",
    "ensure_profile", "find_profile", "stereotype", "apply", "set_values", "read", "effective",
    "effective_dal", "equipment_summary", "dal_rank", "dal_at_least", "normalize_dal", "is_dal",
]

PROFILE_NAME = "Avionics"
PROFILE_VERSION = "1.0"

DALS = ("A", "B", "C", "D", "E")
DAL_DEFAULT = "E"
BUS_TYPES = ("Unspecified", "ARINC429", "AFDX", "MIL-STD-1553", "Discrete", "Analog",
             "ARINC825", "ARINC653", "Power")
LANGUAGES = ("Ada", "C", "C++", "Assembly", "Model-based", "Other")
REQ_LEVELS = ("System", "Item", "HLR", "LLR")
VERIFICATION_METHODS = ("Test", "Analysis", "Inspection", "Demonstration", "Review", "Similarity")

DAL_TEXT = {
    "A": "Level A: catastrophic failure condition",
    "B": "Level B: hazardous failure condition",
    "C": "Level C: major failure condition",
    "D": "Level D: minor failure condition",
    "E": "Level E: no safety effect",
}


def _p(name: str, kind: str = "double", unit: str = "", *, default: Any = None, minimum: Any = None,
       maximum: Any = None, literals: Optional[Iterable[str]] = None, description: str = "") -> dict:
    return {"name": name, "type": kind, "unit": unit, "default": default, "minimum": minimum,
            "maximum": maximum, "literals": list(literals) if literals else None,
            "description": description}


def _dal(description: str = "Development assurance level (DO-178C / DO-254 / ARP4754A), "
                            "A (most stringent) to E") -> dict:
    return _p("dal", "enumeration", default=DAL_DEFAULT, literals=DALS, description=description)


# Stereotype definitions, in creation order (a base before the stereotypes derived from it, a
# default stereotype before the one naming it).
STEREOTYPES: list[dict] = [
    {"name": "DataBusPort", "applies_to": "Port",
     "description": "A port on a data bus: bus type and the address the bus uses "
                    "(ARINC 429 label, AFDX virtual link, MIL-STD-1553 remote terminal).",
     "style": {"icon": "network"},
     "props": [
         _p("busType", "enumeration", default="Unspecified", literals=BUS_TYPES,
            description="Bus or signal type of the port"),
         _p("label", "string", description="ARINC 429 label (octal) or ARINC 825 CAN identifier"),
         _p("virtualLink", "uint16", description="ARINC 664 part 7 virtual link identifier"),
         _p("rtAddress", "uint8", minimum=0, maximum=31,
            description="MIL-STD-1553B remote terminal address"),
     ]},
    {"name": "BusLink", "applies_to": "Connector",
     "description": "A physical link between two ports: bus type, bandwidth, latency, cable length.",
     "style": {"line": "solid"},
     "props": [
         _p("busType", "enumeration", default="Unspecified", literals=BUS_TYPES,
            description="Bus or signal type of the link"),
         _p("bandwidth", "double", "Mbit/s", minimum=0, description="Link bandwidth"),
         _p("latency", "double", "ms", minimum=0, description="Worst-case transport latency"),
         _p("length", "double", "m", minimum=0, description="Cable length"),
     ]},
    {"name": "Equipment", "applies_to": "Component", "abstract": True,
     "description": "Common attributes of avionics equipment (LRUs and IMA modules). Abstract: "
                    "apply one of the derived stereotypes.",
     "style": {"fill": "#dbeafe", "stroke": "#1d4ed8", "icon": "component"},
     "props": [
         _p("mass", "double", "kg", minimum=0, description="Unit mass"),
         _p("powerNominal", "double", "W", minimum=0, description="Nominal electrical power consumption"),
         _p("powerPeak", "double", "W", minimum=0, description="Peak electrical power consumption"),
         _p("mtbf", "double", "h", minimum=0, description="Mean time between failures"),
         _p("failureRate", "double", "FIT", minimum=0, description="Failure rate (1 FIT = 1e-9 per hour)"),
         _p("partNumber", "string", description="Manufacturer part number"),
         _p("manufacturer", "string", description="Manufacturer"),
         _p("ataChapter", "uint8", minimum=0, maximum=99, description="ATA chapter (system)"),
         _dal("Hardware / item development assurance level (DO-254 / ARP4754A IDAL), A to E"),
         _p("certificationBasis", "string", description="TSO / ETSO and certification basis"),
         _p("do160Categories", "string", description="RTCA DO-160 environmental categories"),
     ]},
    {"name": "LRU", "base": "Equipment", "description": "Line replaceable unit.",
     "defaults": {"port": "DataBusPort"}, "props": []},
    {"name": "Sensor", "base": "LRU", "description": "Sensor or sensor computer.",
     "style": {"fill": "#dcfce7", "icon": "sensor"},
     "props": [_p("measurand", "string", description="What it measures (pressure, attitude, altitude, ...)")]},
    {"name": "Display", "base": "LRU", "description": "Cockpit display unit.",
     "style": {"fill": "#ede9fe", "icon": "display"},
     "props": [_p("diagonal", "double", "in", minimum=0, description="Screen diagonal")]},
    {"name": "Actuator", "base": "LRU", "description": "Actuator with its control electronics.",
     "style": {"fill": "#ffedd5", "icon": "actuator"},
     "props": [_p("stroke", "double", "mm", minimum=0, description="Stroke"),
               _p("maxForce", "double", "N", minimum=0, description="Maximum force")]},
    {"name": "Computer", "base": "LRU", "description": "Computer (flight control, air data, ...).",
     "style": {"fill": "#fef9c3", "icon": "computer"},
     "props": [_p("processor", "string", description="Processor / platform"),
               _p("memory", "double", "kB", minimum=0, description="Memory")]},
    {"name": "Switch", "base": "LRU", "description": "Network switch (ARINC 664 part 7 AFDX).",
     "style": {"fill": "#cffafe", "icon": "network"},
     "props": [_p("portCount", "uint8", description="Number of switch ports"),
               _p("switchingLatency", "double", "us", minimum=0, description="Maximum switching latency")]},
    {"name": "Gateway", "base": "LRU", "description": "Gateway or remote data concentrator between buses.",
     "style": {"fill": "#e0f2fe", "icon": "network"},
     "props": [_p("protocols", "string", description="Protocols it translates between")]},
    {"name": "PowerSupply", "base": "LRU", "description": "Power supply or converter.",
     "style": {"fill": "#fee2e2", "icon": "power"},
     "props": [_p("outputVoltage", "double", "V", minimum=0, description="Output voltage"),
               _p("ratedPower", "double", "W", minimum=0, description="Rated output power")]},
    {"name": "LRM", "base": "Equipment",
     "description": "IMA line replaceable module (core processing or I/O module of an integrated modular "
                    "avionics cabinet).",
     "style": {"fill": "#ecfccb", "icon": "computer"}, "defaults": {"port": "DataBusPort"},
     "props": [
         _p("slot", "string", description="Cabinet slot"),
         _p("cores", "uint8", description="Processor cores"),
         _p("memory", "double", "kB", minimum=0, description="Memory"),
         _p("partitioningMark", "boolean", default=False,
            description="Robust ARINC 653 partitioning is claimed for this module, so partitions of "
                        "different DAL may share it"),
     ]},
    {"name": "Partition", "applies_to": "Component",
     "description": "ARINC 653 partition hosted by an IMA module.",
     "style": {"fill": "#f3e8ff", "stroke": "#7e22ce", "icon": "software"},
     "props": [
         _p("partitionId", "uint8", description="ARINC 653 partition identifier"),
         _dal("Software level of the partition (DO-178C), A to E"),
         _p("timeWindow", "double", "ms", minimum=0, description="Scheduled time window per period"),
         _p("period", "double", "ms", minimum=0, description="Partition period"),
         _p("memory", "double", "kB", minimum=0, description="Memory budget"),
         _p("partitioningMark", "boolean", default=False,
            description="Separation between the software items of this partition is claimed, so items "
                        "of different DAL may share it"),
     ]},
    {"name": "SoftwareItem", "applies_to": "Component",
     "description": "Software configuration item (CSCI).",
     "style": {"fill": "#fae8ff", "stroke": "#a21caf", "icon": "software"},
     "props": [
         _dal("Software level (DO-178C), A to E"),
         _p("language", "enumeration", default="C", literals=LANGUAGES, description="Programming language"),
         _p("sloc", "uint32", description="Source lines of code"),
         _p("version", "string", description="Release or baseline"),
     ]},
    {"name": "LogicalItem", "applies_to": "Component",
     "description": "Item of the logical architecture with its assigned development assurance level.",
     "style": {"fill": "#f1f5f9", "stroke": "#475569", "icon": "controller"},
     "props": [_dal("Function / item development assurance level (ARP4754A FDAL / IDAL), A to E")]},
    {"name": "AvionicsRequirement", "applies_to": "Requirement",
     "description": "ARP4754A / DO-178C attributes of a requirement.",
     "style": {"fill": "#fef3c7", "icon": "component"},
     "props": [
         _p("level", "enumeration", default="System", literals=REQ_LEVELS,
            description="Requirement level: system, item, software high-level (HLR) or low-level (LLR)"),
         _dal("Development assurance level of what implements the requirement (DO-178C software "
              "level), A to E"),
         _p("derived", "boolean", default=False,
            description="Derived requirement: not traceable to a higher-level requirement; needs a "
                        "rationale and feedback to the safety assessment"),
         _p("safetyRelated", "boolean", default=False, description="Safety related requirement"),
         _p("verificationMethod", "enumeration", default="Test", literals=VERIFICATION_METHODS,
            description="Verification method (superset of the generic field: also review and "
                        "similarity)"),
     ]},
]

#: Names of the stereotypes derived from Equipment (a component carries at most one).
EQUIPMENT_STEREOTYPES = tuple(s["name"] for s in STEREOTYPES
                              if s["name"] == "LRU" or s.get("base") in ("Equipment", "LRU"))


# ---------------------------------------------------------------------------
# Creating the profile
# ---------------------------------------------------------------------------

def find_profile(repo) -> Optional[Profile]:
    return next((p for p in P.profiles_of(repo) if p.name == PROFILE_NAME), None)


def _qualified(name: Optional[str]) -> Optional[str]:
    return f"{PROFILE_NAME}.{name}" if name else None


def ensure_profile(repo, *, version: str = PROFILE_VERSION) -> Profile:
    """The ``Avionics`` profile, created (or completed) through :mod:`engine.profiles`.

    Stereotypes and properties that already exist are left exactly as they are, so a profile
    the user edited keeps their changes; missing ones are added.
    """
    prof = find_profile(repo)
    if prof is None:
        prof = P.create_profile(repo, PROFILE_NAME, version=version,
                                description="Avionics equipment, IMA, software and bus attributes "
                                            "(ARP4754A / DO-178C / DO-254 / ARINC).")
    for spec in STEREOTYPES:
        st = prof.stereotype(spec["name"])
        if st is None:
            defaults = {slot: _qualified(ref) for slot, ref in (spec.get("defaults") or {}).items()}
            st = P.add_stereotype(repo, prof, spec["name"], description=spec.get("description", ""),
                                  applies_to=spec.get("applies_to", ""), base=_qualified(spec.get("base")),
                                  abstract=bool(spec.get("abstract")), style=spec.get("style"),
                                  defaults=defaults)
        have = {t.name for t in st.tags}
        for prop in spec["props"]:
            if prop["name"] in have:
                continue
            P.add_property(repo, st, prop["name"], prop["type"], unit=prop["unit"], default=prop["default"],
                           minimum=prop["minimum"], maximum=prop["maximum"], literals=prop["literals"],
                           description=prop["description"])
    return prof


def stereotype(repo, name: str) -> Stereotype:
    """``Avionics.<name>`` (raises ``ProfileError`` when the profile lacks it)."""
    return P.find_stereotype(repo, name if "." in name else f"{PROFILE_NAME}.{name}")


def apply(repo, element: Element, name: str, values: Optional[dict] = None) -> Any:
    """Apply ``Avionics.<name>`` to an element (once) and set ``values`` (plain property names)."""
    st = stereotype(repo, name)
    app = application_of(element, st)
    if app is None:
        return P.apply_stereotype(repo, element, st, values or {})
    if values:
        set_values(repo, element, name, values)
    return app


def set_values(repo, element: Element, name: str, values: dict) -> dict:
    """Set property values of an applied stereotype, checked and converted all or nothing."""
    st = stereotype(repo, name)
    paths = {}
    for prop in values:
        tag = st.find_tag(prop)
        if tag is None:
            raise P.ProfileError(f"«{st.full_name}» has no property {prop!r}")
        paths[prop] = f"{tag.stereotype.full_name}.{prop}"
    return P.set_property_values(repo, element, {paths[k]: v for k, v in values.items()})


# ---------------------------------------------------------------------------
# Reading values
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _declaring(prop: str) -> tuple[str, ...]:
    """Qualified paths ``Avionics.<Stereotype>.<prop>`` for every stereotype declaring ``prop``."""
    return tuple(f"{PROFILE_NAME}.{s['name']}.{prop}" for s in STEREOTYPES
                 if any(p["name"] == prop for p in s["props"]))


def read(element: Optional[Element], prop: str) -> Any:
    """Value of an Avionics property on the element itself (None when it carries none).

    Goes through ``engine.profiles.get_property_value``; a user-defined stereotype with a
    property of the same name (a profile of their own with ``dal``) is read as a fallback.
    """
    if element is None or not stereotypes_on(element):
        return None
    for path in (*_declaring(prop), prop):
        try:
            return P.get_property_value(element, path)
        except ValueError:
            continue
    return None


def effective(element: Optional[Element], prop: str) -> Any:
    """Like :func:`read`; a component usage without its own value takes its definition's."""
    value = read(element, prop)
    if value is None and element is not None:
        d = definition_of(element)
        if d is not None and d is not element:
            value = read(d, prop)
    return value


# ---------------------------------------------------------------------------
# Development assurance levels
# ---------------------------------------------------------------------------

def is_dal(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper() in DALS


def normalize_dal(value: Any) -> Optional[str]:
    """``'b'`` -> ``'B'``; None for anything that is not a level A..E."""
    return value.strip().upper() if is_dal(value) else None


def dal_rank(dal: Any) -> Optional[int]:
    """0 for A (most stringent) ... 4 for E; None for an unknown level."""
    d = normalize_dal(dal)
    return DALS.index(d) if d else None


def dal_at_least(actual: Any, required: Any) -> bool:
    """True when level ``actual`` is as stringent as ``required`` (B >= C; A >= everything)."""
    a, r = dal_rank(actual), dal_rank(required)
    return a is not None and r is not None and a <= r


def effective_dal(element: Optional[Element]) -> Optional[str]:
    return normalize_dal(effective(element, "dal"))


# ---------------------------------------------------------------------------
# Roll-up
# ---------------------------------------------------------------------------

def equipment_summary(repo, architecture: Optional[Element] = None) -> list[dict]:
    """Mass, power and DAL roll-up per architecture.

    Every component (at any depth, reference components through their definition) that has a
    mass or a power value counts once per usage, so two ``FlightControlComputer`` usages weigh
    twice. ``architecture`` limits the roll-up to one architecture; by default every top-level
    architecture that holds such equipment is listed.
    """
    from engine import architecture as A
    from engine.structure import component_tree
    roots = [architecture] if architecture is not None else A.architecture_roots(repo)
    out = []
    for root in roots:
        items, mass, nominal, peak = 0, 0.0, 0.0, 0.0
        by_dal: dict[str, int] = {}
        for comp, depth, _parent in component_tree(root):
            if depth == 0:
                continue
            m, pn, pp = (effective(comp, "mass"), effective(comp, "powerNominal"),
                         effective(comp, "powerPeak"))
            if not any(isinstance(v, (int, float)) for v in (m, pn, pp)):
                continue
            items += 1
            mass += m if isinstance(m, (int, float)) else 0.0
            nominal += pn if isinstance(pn, (int, float)) else 0.0
            peak += pp if isinstance(pp, (int, float)) else 0.0
            dal = effective_dal(comp)
            if dal:
                by_dal[dal] = by_dal.get(dal, 0) + 1
        if items:
            out.append({"id": root.element_id, "name": root.name, "items": items,
                        "mass_kg": round(mass, 3), "power_nominal_w": round(nominal, 1),
                        "power_peak_w": round(peak, 1), "by_dal": dict(sorted(by_dal.items()))})
    return out
