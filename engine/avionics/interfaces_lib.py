"""Avionics interface library: shared interfaces importable into the interface dictionary.

The library holds typical avionics buses and signals as ordinary dictionary items (value types,
enumerations, data / physical interfaces) created through :mod:`engine.interfaces`, so they are
edited, assigned to ports and checked for compatibility like any other interface.

.. warning::

   Label numbers, word layouts and numeric ranges are *typical* values taken from common
   ARINC 429 / 664 / 825 / 653 and MIL-STD-1553B practice. They are a starting point: verify
   every one against your programme's interface control document (ICD) before relying on it.

Groups
------
``types``     value types (altitude, airspeed, angle, ...) and enumerations (SSM, discrete level, ...)
``a429``      ARINC 429 word and the label sets for air data, inertial / attitude, navigation,
              radio altitude and GNSS
``a664``      ARINC 664 part 7 (AFDX) virtual link message
``m1553``     MIL-STD-1553B message
``discrete``  28 V / ground / open discrete, active low
``analog``    0-10 V, 4-20 mA, synchro
``a825``      ARINC 825 CAN frame
``a653``      ARINC 653 sampling and queuing port
``power``     28 VDC and 115 VAC 400 Hz power, hydraulic supply (physical interfaces)

``import_library(repo, names=None, groups=None, on_conflict="skip")`` imports the items you ask
for (everything by default) together with the value types and enumerations they need. Items
that already exist are skipped (``on_conflict="skip"``) or imported under a new name
(``"rename"``), so importing twice never duplicates anything.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from engine import interfaces as I

__all__ = ["GROUPS", "ITEMS", "ICD_WARNING", "catalog", "library_status", "import_library",
           "find_item"]

ICD_WARNING = ("Label numbers, word layouts and ranges are typical values: verify every one "
               "against your programme's ICD.")

GROUPS: list[tuple[str, str]] = [
    ("types", "Value types and enumerations"),
    ("a429", "ARINC 429"),
    ("a664", "ARINC 664 part 7 (AFDX)"),
    ("m1553", "MIL-STD-1553B"),
    ("discrete", "Discrete signals"),
    ("analog", "Analog signals"),
    ("a825", "ARINC 825 (CAN)"),
    ("a653", "ARINC 653 ports"),
    ("power", "Power and physical supplies"),
]

_COLORS = {"types": "#64748b", "a429": "#1f77b4", "a664": "#ff7f0e", "m1553": "#9467bd",
           "discrete": "#d62728", "analog": "#2ca02c", "a825": "#17becf", "a653": "#8c564b",
           "power": "#111827"}


def _vt(name: str, units: str, lo: Any, hi: Any, description: str, base: str = "double") -> dict:
    return {"name": name, "kind": "ValueType", "group": "types", "description": description,
            "fields": {"base_type": base, "units": units, "minimum": lo, "maximum": hi}}


def _enum(name: str, literals: list[tuple[str, int]], description: str, default: Optional[str] = None) -> dict:
    fields = {"default": default} if default else {}
    return {"name": name, "kind": "Enumeration", "group": "types", "description": description,
            "literals": [{"name": n, "value": v} for n, v in literals], "fields": fields}


def _el(name: str, type_: str = "double", description: str = "", label: Optional[str] = None, **fields) -> dict:
    out = {"name": name, "type": type_, **fields}
    desc = description
    if label:
        desc = f"Label {label} (octal): {description}" if description else f"Label {label} (octal)"
        out["label"] = label
    if desc:
        out["description"] = desc
    return out


def _bus(name: str, group: str, description: str, elements: list[dict], kind: str = "DataInterface") -> dict:
    return {"name": name, "kind": kind, "group": group, "description": description, "elements": elements}


ITEMS: list[dict] = [
    # ---- value types ------------------------------------------------------------------------
    _vt("AltitudeFt", "ft", -1500, 60000, "Altitude"),
    _vt("RadioAltitudeFt", "ft", -20, 2500, "Radio altitude above ground"),
    _vt("AirspeedKt", "kt", 0, 700, "Airspeed"),
    _vt("MachNumber", "", 0, 2, "Mach number"),
    _vt("TemperatureDegC", "degC", -100, 150, "Air temperature"),
    _vt("VerticalSpeedFpm", "ft/min", -20000, 20000, "Vertical speed"),
    _vt("AngleDeg", "deg", -180, 360, "Attitude or heading angle"),
    _vt("CourseDeg", "deg", 0, 360, "Course or track"),
    _vt("LatitudeDeg", "deg", -90, 90, "Latitude"),
    _vt("LongitudeDeg", "deg", -180, 180, "Longitude"),
    _vt("GroundSpeedKt", "kt", 0, 1000, "Ground speed"),
    _vt("AccelerationG", "gn", -8, 8, "Acceleration in g"),
    _vt("DistanceNmi", "nmi", 0, 9999, "Distance"),
    _enum("Ssm429", [("FAILURE_WARNING", 0), ("NO_COMPUTED_DATA", 1), ("FUNCTIONAL_TEST", 2),
                     ("NORMAL_OPERATION", 3)],
          "ARINC 429 sign / status matrix (BNR coding): failure warning, no computed data, "
          "functional test, normal operation", default="NORMAL_OPERATION"),
    _enum("DiscreteLevel", [("OPEN", 0), ("GROUND", 1), ("V28", 2)],
          "Electrical level of a discrete line", default="OPEN"),
    _enum("NetworkId", [("NET_A", 0), ("NET_B", 1), ("NET_A_AND_B", 2)],
          "ARINC 664 network: A, B or both (redundant transmission)", default="NET_A_AND_B"),
    _enum("BusSelect", [("BUS_A", 0), ("BUS_B", 1)], "MIL-STD-1553B bus A or B", default="BUS_A"),
    _enum("QueuingDiscipline", [("FIFO", 0), ("PRIORITY", 1)], "ARINC 653 queuing discipline",
          default="FIFO"),
    _enum("PortValidity", [("INVALID", 0), ("VALID", 1)], "ARINC 653 sampling message validity",
          default="VALID"),

    # ---- ARINC 429 ---------------------------------------------------------------------------
    _bus("A429Word", "a429", "32-bit ARINC 429 word: label (octal), source/destination identifier, "
         "data field, sign/status matrix and odd parity.",
         [_el("label", "uint8", "Label, bits 1-8 (written in octal, e.g. 0o203)", minimum=0, maximum=255),
          _el("sdi", "uint8", "Source / destination identifier, bits 9-10", minimum=0, maximum=3),
          _el("data", "uint32", "Data field, bits 11-29 (BNR, BCD or discrete)", minimum=0, maximum=524287),
          _el("ssm", "Enum: Ssm429", "Sign / status matrix, bits 30-31"),
          _el("parity", "boolean", "Odd parity, bit 32")]),
    _bus("A429AirData", "a429", "Air data label set (typical labels, verify against the ICD).",
         [_el("pressureAltitude", "ValueType: AltitudeFt", "pressure altitude (1013.25 hPa)", label="203"),
          _el("baroCorrectedAltitude", "ValueType: AltitudeFt", "baro-corrected altitude", label="204"),
          _el("mach", "ValueType: MachNumber", "Mach number", label="205"),
          _el("computedAirspeed", "ValueType: AirspeedKt", "computed airspeed (CAS)", label="206"),
          _el("trueAirspeed", "ValueType: AirspeedKt", "true airspeed (TAS)", label="210"),
          _el("totalAirTemperature", "ValueType: TemperatureDegC", "total air temperature (TAT)", label="211"),
          _el("verticalSpeed", "ValueType: VerticalSpeedFpm", "altitude rate", label="212"),
          _el("staticAirTemperature", "ValueType: TemperatureDegC", "static air temperature (SAT)", label="213"),
          _el("valid", "boolean", "all labels carry normal-operation SSM")]),
    _bus("A429Inertial", "a429", "Inertial / attitude label set (typical labels, verify against the ICD).",
         [_el("latitude", "ValueType: LatitudeDeg", "present position latitude", label="310"),
          _el("longitude", "ValueType: LongitudeDeg", "present position longitude", label="311"),
          _el("groundSpeed", "ValueType: GroundSpeedKt", "ground speed", label="312"),
          _el("magneticHeading", "ValueType: AngleDeg", "magnetic heading", label="320"),
          _el("trackAngle", "ValueType: CourseDeg", "magnetic track angle", label="322"),
          _el("pitch", "ValueType: AngleDeg", "pitch angle", label="324"),
          _el("roll", "ValueType: AngleDeg", "roll angle", label="325"),
          _el("longitudinalAcceleration", "ValueType: AccelerationG", "body longitudinal acceleration",
              label="331"),
          _el("lateralAcceleration", "ValueType: AccelerationG", "body lateral acceleration", label="332"),
          _el("normalAcceleration", "ValueType: AccelerationG", "body normal acceleration", label="333"),
          _el("valid", "boolean", "all labels carry normal-operation SSM")]),
    _bus("A429Navigation", "a429", "Navigation label set (typical labels, verify against the ICD).",
         [_el("distanceToGo", "ValueType: DistanceNmi", "distance to go", label="001"),
          _el("selectedCourse", "ValueType: CourseDeg", "selected course #1", label="100"),
          _el("desiredTrack", "ValueType: CourseDeg", "desired track", label="114"),
          _el("valid", "boolean", "all labels carry normal-operation SSM")]),
    _bus("A429RadioAltitude", "a429", "Radio altimeter label set (typical label, verify against the ICD).",
         [_el("radioAltitude", "ValueType: RadioAltitudeFt", "radio altitude", label="164"),
          _el("valid", "boolean", "label carries normal-operation SSM")]),
    _bus("A429Gnss", "a429", "GNSS receiver label set (typical labels, verify against the ICD).",
         [_el("gnssAltitude", "ValueType: AltitudeFt", "GNSS altitude (MSL)", label="076"),
          _el("gnssTrackAngle", "ValueType: CourseDeg", "GNSS track angle", label="103"),
          _el("gnssLatitude", "ValueType: LatitudeDeg", "GNSS latitude", label="110"),
          _el("gnssLongitude", "ValueType: LongitudeDeg", "GNSS longitude", label="111"),
          _el("gnssGroundSpeed", "ValueType: GroundSpeedKt", "GNSS ground speed", label="112"),
          _el("valid", "boolean", "all labels carry normal-operation SSM")]),

    # ---- ARINC 664 part 7 ---------------------------------------------------------------------
    _bus("A664Message", "a664", "ARINC 664 part 7 (AFDX) virtual link message: bandwidth allocation gap, "
         "maximum frame size, jitter, sub-virtual link and network A / B redundancy.",
         [_el("vlId", "uint16", "Virtual link identifier", minimum=1, maximum=65535),
          _el("bag", "double", "Bandwidth allocation gap (1, 2, 4 ... 128 ms)", units="ms",
              minimum=1, maximum=128),
          _el("lmax", "uint16", "Largest Ethernet frame on the virtual link (Lmax)", units="byte",
              minimum=64, maximum=1518),
          _el("jitterMax", "double", "Maximum emission jitter", units="us", minimum=0, maximum=500),
          _el("subVl", "uint8", "Sub-virtual link (0..3)", minimum=0, maximum=3),
          _el("network", "Enum: NetworkId", "Network A, B or both (redundancy)"),
          _el("sequenceNumber", "uint8", "Redundancy management sequence number"),
          _el("payload", "uint8", "UDP payload", dimensions="1471", units="byte")]),

    # ---- MIL-STD-1553B ------------------------------------------------------------------------
    _bus("M1553BMessage", "m1553", "MIL-STD-1553B command / data / status message.",
         [_el("rtAddress", "uint8", "Remote terminal address (31 = broadcast)", minimum=0, maximum=31),
          _el("transmit", "boolean", "T/R bit: remote terminal transmits"),
          _el("subaddress", "uint8", "Subaddress / mode code", minimum=0, maximum=31),
          _el("wordCount", "uint8", "Data word count (32 words coded as 0)", minimum=1, maximum=32),
          _el("rate", "double", "Message rate", units="Hz", minimum=0, maximum=1000),
          _el("bus", "Enum: BusSelect", "Bus A or B"),
          _el("dataWords", "uint16", "Data words", dimensions="32"),
          _el("statusWord", "uint16", "Remote terminal status word")]),

    # ---- discrete ------------------------------------------------------------------------------
    _bus("DiscreteLine", "discrete", "Discrete signal: 28 V / ground / open, optionally active low.",
         [_el("level", "Enum: DiscreteLevel", "Electrical level on the line (28 V, ground or open)"),
          _el("activeLow", "boolean", "Asserted when the line is at ground / open (active low)"),
          _el("asserted", "boolean", "Logical state after applying the polarity"),
          _el("valid", "boolean", "Signal validity")]),

    # ---- analog --------------------------------------------------------------------------------
    _bus("AnalogVoltage", "analog", "0-10 V analog signal.",
         [_el("value", "double", "Measured voltage", units="V", minimum=0, maximum=10),
          _el("valid", "boolean", "Signal validity")]),
    _bus("AnalogCurrent", "analog", "4-20 mA current loop (below 4 mA means open loop / failure).",
         [_el("current", "double", "Loop current", units="mA", minimum=4, maximum=20),
          _el("valid", "boolean", "Signal validity")]),
    _bus("SynchroSignal", "analog", "Synchro / resolver angle signal (3-wire stator, excited by a reference).",
         [_el("angle", "double", "Shaft angle", units="deg", minimum=0, maximum=360),
          _el("excitationVoltage", "double", "Reference excitation (typically 26 V or 115 V)", units="V",
              minimum=0, maximum=130),
          _el("excitationFrequency", "double", "Reference frequency (typically 400 Hz)", units="Hz",
              minimum=0, maximum=10000),
          _el("valid", "boolean", "Signal validity")]),

    # ---- ARINC 825 -----------------------------------------------------------------------------
    _bus("A825Frame", "a825", "ARINC 825 (CAN) frame: 29-bit identifier, priority and up to 8 data bytes.",
         [_el("canId", "uint32", "29-bit extended identifier", minimum=0, maximum=536870911),
          _el("priority", "uint8", "Message priority (0 highest)", minimum=0, maximum=7),
          _el("dlc", "uint8", "Data length code", minimum=0, maximum=8),
          _el("data", "uint8", "Data bytes", dimensions="8", units="byte")]),

    # ---- ARINC 653 -----------------------------------------------------------------------------
    _bus("A653SamplingPort", "a653", "ARINC 653 sampling port: the last message is kept and refreshed.",
         [_el("maxMessageSize", "uint32", "Largest message", units="byte"),
          _el("refreshPeriod", "double", "Refresh period", units="ms", minimum=0),
          _el("validity", "Enum: PortValidity", "Age of the message against the refresh period"),
          _el("message", "uint8", "Message", dimensions="64", units="byte")]),
    _bus("A653QueuingPort", "a653", "ARINC 653 queuing port: messages are queued and none is lost.",
         [_el("maxMessageSize", "uint32", "Largest message", units="byte"),
          _el("maxNbMessage", "uint16", "Queue depth", minimum=1),
          _el("discipline", "Enum: QueuingDiscipline", "Queuing discipline"),
          _el("nbMessage", "uint16", "Messages currently queued", minimum=0),
          _el("message", "uint8", "Message", dimensions="64", units="byte")]),

    # ---- power ---------------------------------------------------------------------------------
    _bus("Power28VDCBus", "power", "28 VDC aircraft power feed (MIL-STD-704 / DO-160 section 16).",
         [{"name": "positive", "domain": "electrical", "description": "+28 VDC"},
          {"name": "ret", "domain": "electrical", "description": "Power return"}], kind="PhysicalInterface"),
    _bus("Power115VAC400Hz", "power", "115 VAC 400 Hz single-phase power feed.",
         [{"name": "line", "domain": "electrical", "description": "115 VAC 400 Hz"},
          {"name": "neutral", "domain": "electrical", "description": "Neutral"}], kind="PhysicalInterface"),
    _bus("HydraulicSupply", "power", "Hydraulic supply (pressure and return lines).",
         [{"name": "pressure", "domain": "hydraulic", "description": "System pressure line"},
          {"name": "returnLine", "domain": "hydraulic", "description": "Return line"}],
         kind="PhysicalInterface"),
]

_BY_NAME = {it["name"]: it for it in ITEMS}


def find_item(name: str) -> Optional[dict]:
    return _BY_NAME.get(name)


def _requires(item: dict) -> list[str]:
    """Names of the library items an item's element types refer to (``ValueType: X`` / ``Enum: X``)."""
    out: list[str] = []
    for el in item.get("elements", ()):
        t = el.get("type", "")
        if ":" in t:
            out.append(t.split(":", 1)[1].strip())
    return list(dict.fromkeys(out))


def _labels(item: dict) -> list[dict]:
    return [{"element": el["name"], "label": el["label"], "description": el.get("description", "")}
            for el in item.get("elements", ()) if el.get("label")]


def _brief(item: dict) -> dict:
    elements = item.get("elements") or item.get("literals") or []
    return {"name": item["name"], "kind": item["kind"], "group": item["group"],
            "description": item["description"], "requires": _requires(item),
            "elements": len(elements), "labels": _labels(item),
            "units": (item.get("fields") or {}).get("units", "")}


def catalog() -> dict:
    """The library as JSON: groups with their items (no project needed)."""
    return {"warning": ICD_WARNING,
            "groups": [{"id": gid, "title": title,
                        "items": [_brief(i) for i in ITEMS if i["group"] == gid]}
                       for gid, title in GROUPS],
            "count": len(ITEMS)}


def library_status(repo) -> dict:
    """The catalog with a ``present`` flag per item: is a dictionary item of that name already there?"""
    have = {e.name for e in I.shared_items(repo)}
    cat = catalog()
    for g in cat["groups"]:
        for it in g["items"]:
            it["present"] = it["name"] in have
    cat["present"] = sum(1 for g in cat["groups"] for it in g["items"] if it["present"])
    return cat


def _closure(wanted: Iterable[str]) -> list[str]:
    """``wanted`` plus everything they need, in library order (types before their users)."""
    need: set[str] = set()

    def add(name: str) -> None:
        if name in need:
            return
        need.add(name)
        for dep in _requires(_BY_NAME[name]):
            if dep in _BY_NAME:
                add(dep)
    for n in wanted:
        add(n)
    return [it["name"] for it in ITEMS if it["name"] in need]


def import_library(repo, names: Optional[Iterable[str]] = None, groups: Optional[Iterable[str]] = None,
                   on_conflict: str = "skip") -> dict:
    """Import library items into the project's interface dictionary.

    ``names`` / ``groups`` select what to import (all when both are empty); the value types and
    enumerations the selection needs come with it. ``on_conflict``: ``"skip"`` keeps an existing
    item of the same name, ``"rename"`` creates the library item as ``Name_1``.
    Returns ``{"created": [...], "skipped": [...], "renamed": {name: new name},
    "dependencies": [...], "warning": ICD_WARNING}``; raises ``InterfaceError`` for unknown names.
    """
    if on_conflict not in ("skip", "rename"):
        raise I.InterfaceError(f"on_conflict must be 'skip' or 'rename', not {on_conflict!r}")
    names = [n for n in (names or []) if n]
    unknown = [n for n in names if n not in _BY_NAME]
    if unknown:
        raise I.InterfaceError(f"Unknown library item(s): {', '.join(unknown)}", 404)
    group_ids = [g for g in (groups or []) if g]
    bad = [g for g in group_ids if g not in dict(GROUPS)]
    if bad:
        raise I.InterfaceError(f"Unknown library group(s): {', '.join(bad)}; use {', '.join(dict(GROUPS))}", 404)
    wanted = list(names) + [it["name"] for it in ITEMS if it["group"] in group_ids]
    if not wanted:
        wanted = [it["name"] for it in ITEMS]
    order = _closure(wanted)
    deps = [n for n in order if n not in wanted]
    result: dict[str, Any] = {"created": [], "skipped": [], "renamed": {}, "dependencies": deps,
                              "warning": ICD_WARNING}
    dic = I.get_dictionary(repo)
    name_map: dict[str, Any] = {}
    for name in order:
        item = _BY_NAME[name]
        existing = I._sibling(dic, name)
        if existing is not None and on_conflict == "skip":
            result["skipped"].append(name)
            name_map[name] = existing
            continue
        target = name
        if existing is not None:
            target = I._unique_rename(dic, name)
            result["renamed"][name] = target
        created = _create(repo, item, target, name_map)
        name_map[name] = created
        result["created"].append(target)
    return result


def _create(repo, item: dict, name: str, name_map: dict) -> Any:
    kind = item["kind"]
    fields = dict(item.get("fields") or {})
    fields["description"] = item["description"]
    if kind in ("ValueType", "DataInterface", "PhysicalInterface"):
        fields["color"] = _COLORS.get(item["group"])
    elements = []
    for el in item.get("elements", ()):
        spec = {k: v for k, v in el.items() if k != "label"}
        t = spec.get("type", "")
        if ":" in t:
            prefix, ref = (p.strip() for p in t.split(":", 1))
            if ref in name_map:                      # renamed or already present: type by the object
                spec["type"] = name_map[ref]
        elements.append(spec)
    literals = [dict(lit) for lit in item.get("literals", ())]
    return I.create_item(repo, kind, name, elements=elements, literals=literals, **fields)
