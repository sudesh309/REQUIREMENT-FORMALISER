"""Requirement libraries: ARP4754A (system, item) and DO-178C (HLR, LLR) skeleton sets.

A skeleton is a hierarchical requirement set whose statements carry ``<placeholders>`` to be
filled in, with the attributes the Requirements feature knows (type, verification method) and
the avionics attributes of the ``Avionics.AvionicsRequirement`` stereotype (level, DAL, derived,
safety related, verification method). The DAL of each entry is a *typical* value to be replaced
by what your functional hazard assessment demands.

``import_requirement_set(repo, key)`` creates the set through :mod:`engine.requirements` and
applies the stereotype; ``import_requirement_library`` imports several.

The module also holds the **verification guidance per DAL** (:data:`VERIFICATION_GUIDANCE`) and
the validator checks built on it (``avionics.req.*`` rules, see :data:`RULES`): they are
guidance for reviewers, not the text of the standards.
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional

from engine import profiles as P
import engine.requirements as rq
from kerml.elements import Element
from kerml.stereotypes import stereotypes_on

from . import profile as AP

__all__ = ["SETS", "VERIFICATION_GUIDANCE", "RULES", "catalog", "import_requirement_set",
           "import_requirement_library", "effective_method", "check_requirements"]


def R(summary: str, text: str = "", kind: str = "functional", method: Optional[str] = "test",
      dal: str = "C", *, derived: bool = False, safety: bool = False, rationale: str = "",
      children: Iterable[dict] = ()) -> dict:
    return {"summary": summary, "text": text, "type": kind, "method": method, "dal": dal,
            "derived": derived, "safety": safety, "rationale": rationale, "children": list(children)}


def group(summary: str, text: str, children: Iterable[dict]) -> dict:
    return R(summary, text or f"{summary}.", "other", None, "E", children=children)


# ---------------------------------------------------------------------------------------------
# Skeleton sets
# ---------------------------------------------------------------------------------------------

_SYSTEM = [
    group("Functional requirements", "What the system does (ARP4754A 5.3, requirements capture).", [
        R("Provide function", "The <system> shall provide <function> to the flight crew in <flight phases>.",
          "functional", "test", "C"),
        R("Operating modes", "The <system> shall provide <normal, degraded and failed> modes and shall "
          "annunciate every mode change to the crew.", "functional", "test", "C"),
        R("Failure annunciation", "The <system> shall annunciate the loss of <function> within <t> seconds.",
          "functional", "test", "C", safety=True),
        R("Initialisation", "The <system> shall be operational within <t> seconds of power application.",
          "performance", "test", "D"),
    ]),
    group("Performance requirements", "How well the system does it.", [
        R("Accuracy", "The <parameter> shall be accurate to within <value> (<confidence>) over <envelope>.",
          "performance", "test", "C"),
        R("End-to-end latency", "The latency from <input> to <output> shall not exceed <ms> ms.",
          "performance", "test", "C"),
        R("Availability", "The availability of <function> shall be at least <value> per flight hour.",
          "performance", "analysis", "D"),
    ]),
    group("Safety requirements", "Derived from the functional hazard assessment and the system safety "
          "assessment (ARP4761, CS/FAR 25.1309).", [
        R("Catastrophic failure conditions", "The probability of <catastrophic failure condition> shall be "
          "less than 1E-9 per flight hour and no single failure shall cause it.", "safety", "analysis", "A",
          safety=True),
        R("Hazardous failure conditions", "The probability of <hazardous failure condition> shall be less "
          "than 1E-7 per flight hour.", "safety", "analysis", "B", safety=True),
        R("Major failure conditions", "The probability of <major failure condition> shall be less than "
          "1E-5 per flight hour.", "safety", "analysis", "C", safety=True),
        R("Independence", "<Channel 1> and <channel 2> shall be independent: no common-cause failure shall "
          "defeat both (common cause analysis).", "design-constraint", "analysis", "A", safety=True),
        R("Latent failures", "Latent failures of <item> shall be detected by built-in test at intervals "
          "not exceeding <t> flight hours.", "safety", "test", "B", safety=True),
        R("Erroneous output", "An erroneous <output> shall be detected and annunciated or passivated "
          "within <t> ms.", "safety", "test", "A", safety=True),
    ]),
    group("Interface requirements", "Interfaces to other systems (see the ICD).", [
        R("Data interface", "The <system> shall exchange <data> with <system> as defined in <ICD> over <bus>.",
          "interface", "test", "C"),
        R("Network bandwidth", "The <system> virtual links shall respect the network configuration "
          "(bandwidth allocation gap, maximum frame size, jitter).", "interface", "analysis", "C"),
        R("Electrical power", "The <system> shall operate from 28 VDC power as defined in DO-160 section 16, "
          "category <category>.", "interface", "test", "D"),
    ]),
    group("Environmental requirements", "", [
        R("Environmental qualification", "The equipment shall be qualified to RTCA DO-160 categories <list>.",
          "environmental", "test", "D"),
        R("Lightning and HIRF", "The <system> shall withstand lightning and high intensity radiated fields "
          "without loss of function at the levels of <level>.", "environmental", "test", "B", safety=True),
    ]),
    group("Design constraints", "", [
        R("DAL assignment", "Every function shall be developed to the development assurance level assigned "
          "by the functional hazard assessment.", "design-constraint", "inspection", "C"),
        R("Robust partitioning", "Software of different levels hosted on one platform shall be robustly "
          "partitioned (ARINC 653 / DO-297).", "design-constraint", "analysis", "B", safety=True),
        R("Mass and power budget", "The <system> shall not exceed <kg> kg and <W> W.", "design-constraint",
          "inspection", "E"),
    ]),
    group("Derived requirements", "Requirements introduced by the design that do not trace to a higher "
          "level. Each needs a rationale and feedback to the safety assessment (ARP4754A 5.3.3).", [
        R("Derived requirement", "<Statement introduced by the design.>", "design-constraint", "analysis",
          "C", derived=True, rationale="<Why the design needs it and its effect on safety.>"),
    ]),
]

_ITEM = [
    group("Item functional requirements", "What the item does (allocated from the system requirements).", [
        R("Item function", "The <item> shall <perform function> when <condition>.", "functional", "test", "C"),
        R("Item modes", "The <item> shall enter <mode> within <t> ms after <event>.", "functional", "test", "C"),
    ]),
    group("Item interface requirements", "", [
        R("ARINC 429 output", "The <item> shall transmit label <octal> at <rate> Hz on ARINC 429 "
          "high speed (100 kbit/s) with SDI <sdi> and valid SSM coding.", "interface", "test", "C"),
        R("ARINC 664 end system", "The <item> shall emit virtual link <id> with BAG <ms> ms and Lmax "
          "<bytes> bytes on networks A and B.", "interface", "test", "C"),
        R("MIL-STD-1553B remote terminal", "The <item> shall respond as remote terminal <address> to "
          "subaddress <n> within the 12 microsecond response time.", "interface", "test", "C"),
        R("Discrete interface", "The <item> shall assert <discrete> (active low, ground / open) when "
          "<condition>.", "interface", "test", "C"),
    ]),
    group("Item reliability and built-in test", "", [
        R("MTBF", "The <item> shall have an MTBF of at least <h> hours.", "performance", "analysis", "D"),
        R("Built-in test coverage", "Built-in test shall detect at least <percent> % of the failures that "
          "affect <function>.", "performance", "test", "C", safety=True),
        R("Fail-safe behaviour", "On detection of a failure the <item> shall <passivate / revert> within "
          "<t> ms.", "safety", "test", "A", safety=True),
    ]),
    group("Item safety and assurance", "", [
        R("Development assurance level", "The <item> shall be developed to DAL <level> in accordance with "
          "DO-178C (software) or DO-254 (hardware).", "design-constraint", "inspection", "C"),
        R("Planning data", "The plan for software aspects of certification (PSAC) or plan for hardware "
          "aspects of certification (PHAC) shall be approved before development starts.",
          "design-constraint", "inspection", "C"),
    ]),
    group("Item physical requirements", "", [
        R("Mass", "The <item> shall not exceed <kg> kg.", "design-constraint", "inspection", "E"),
        R("Power consumption", "The <item> shall not consume more than <W> W nominal and <W> W peak.",
          "design-constraint", "test", "E"),
        R("Environmental qualification", "The <item> shall be qualified to RTCA DO-160 categories <list>.",
          "environmental", "test", "D"),
    ]),
]

_HLR = [
    group("Functional behaviour", "DO-178C 5.1: high-level requirements developed from the system "
          "requirements allocated to software.", [
        R("Compute output", "The <CSCI> shall compute <output> from <inputs> every <period> ms.",
          "functional", "test", "C"),
        R("Mode logic", "The <CSCI> shall change from <mode> to <mode> when <condition>.", "functional",
          "test", "C"),
        R("Input validity", "The <CSCI> shall treat <input> as invalid when its status is not normal "
          "operation or its age exceeds <ms> ms.", "functional", "test", "C", safety=True),
    ]),
    group("Timing and resources", "", [
        R("Worst-case execution time", "The worst-case execution time of <function> shall not exceed "
          "<ms> ms.", "performance", "analysis", "C"),
        R("Memory budget", "The <CSCI> shall use no more than <kB> kB of memory in its partition.",
          "design-constraint", "analysis", "C"),
        R("No dynamic allocation", "The <CSCI> shall not allocate memory dynamically after initialisation.",
          "design-constraint", "inspection", "C"),
    ]),
    group("Robustness", "", [
        R("Out-of-range inputs", "The <CSCI> shall limit every input to its valid range and flag values "
          "outside it.", "functional", "test", "C", safety=True),
        R("Failure handling", "The <CSCI> shall <passivate / hold last value> within <ms> ms of a "
          "detected failure of <input>.", "safety", "test", "B", safety=True),
    ]),
    group("Data and interfaces", "", [
        R("Port usage", "The <CSCI> shall read <port> as an ARINC 653 sampling port and write <port> as "
          "a queuing port.", "interface", "test", "C"),
    ]),
    group("Initialisation", "", [
        R("Start-up", "The <CSCI> shall initialise all data to a known state before its first frame.",
          "functional", "test", "C"),
    ]),
    group("Derived high-level requirements", "Introduced by the software design; fed back to the system "
          "safety assessment (DO-178C 5.1.1).", [
        R("Derived high-level requirement", "<Statement introduced by the software design.>",
          "design-constraint", "analysis", "C", derived=True, rationale="<Why it is needed.>"),
    ]),
]

_LLR = [
    group("Algorithms", "DO-178C 5.2: low-level requirements from which source code is written directly.", [
        R("Function behaviour", "The function <name> shall compute <expression> using <algorithm>.",
          "functional", "test", "C"),
        R("Numerical limits", "The function <name> shall saturate its result to [<min>, <max>].",
          "functional", "test", "C", safety=True),
        R("Division safety", "The function <name> shall not divide by a value with magnitude below "
          "<epsilon>.", "functional", "test", "C", safety=True),
    ]),
    group("Data", "", [
        R("Data types", "The variable <name> shall be <type> with resolution <value> and range "
          "[<min>, <max>].", "design-constraint", "inspection", "C"),
        R("Initial values", "The variable <name> shall be initialised to <value> at start-up.",
          "functional", "test", "C"),
    ]),
    group("Tasks and interrupts", "", [
        R("Task period", "The task <name> shall run every <ms> ms with priority <n>.", "performance",
          "test", "C"),
        R("Interrupt handling", "The interrupt handler <name> shall only set <flag> and return.",
          "design-constraint", "inspection", "C"),
    ]),
    group("Coding constraints", "", [
        R("Coding standard", "The source code shall comply with <coding standard>.", "design-constraint",
          "inspection", "C"),
        R("Static memory", "The source code shall use static allocation only.", "design-constraint",
          "inspection", "C"),
    ]),
    group("Derived low-level requirements", "", [
        R("Derived low-level requirement", "<Statement introduced by the code design.>", "design-constraint",
          "analysis", "C", derived=True, rationale="<Why it is needed.>"),
    ]),
]

SETS: dict[str, dict] = {
    "arp4754a-system": {"name": "SystemRequirements", "prefix": "SYS-", "level": "System",
                        "title": "ARP4754A system requirements",
                        "description": "Skeleton of ARP4754A system level requirements: functional, "
                                       "performance, safety, interface, environmental, design constraints, "
                                       "derived.", "requirements": _SYSTEM},
    "arp4754a-item": {"name": "ItemRequirements", "prefix": "ITM-", "level": "Item",
                      "title": "ARP4754A item requirements",
                      "description": "Skeleton of ARP4754A item (hardware / software) requirements allocated "
                                     "from the system requirements.", "requirements": _ITEM},
    "do178c-hlr": {"name": "SoftwareHighLevelRequirements", "prefix": "HLR-", "level": "HLR",
                   "title": "DO-178C high-level requirements",
                   "description": "Skeleton of DO-178C software high-level requirements.",
                   "requirements": _HLR},
    "do178c-llr": {"name": "SoftwareLowLevelRequirements", "prefix": "LLR-", "level": "LLR",
                   "title": "DO-178C low-level requirements",
                   "description": "Skeleton of DO-178C software low-level requirements.",
                   "requirements": _LLR},
}

#: Verification guidance per development assurance level (project guidance, not standard text).
VERIFICATION_GUIDANCE: dict[str, dict] = {
    "A": {"failure": "Catastrophic", "objectives": 71, "independent": 30, "coverage": "MC/DC",
          "system_methods": ["Test", "Analysis", "Demonstration"], "test_required": True,
          "text": "Requirements-based tests with modified condition / decision coverage; analysis or test "
                  "at system level; many objectives verified independently."},
    "B": {"failure": "Hazardous", "objectives": 69, "independent": 18, "coverage": "Decision",
          "system_methods": ["Test", "Analysis", "Demonstration"], "test_required": True,
          "text": "Requirements-based tests with decision coverage; analysis or test at system level."},
    "C": {"failure": "Major", "objectives": 62, "independent": 5, "coverage": "Statement",
          "system_methods": ["Test", "Analysis", "Demonstration", "Inspection", "Review", "Similarity"],
          "test_required": True,
          "text": "Requirements-based tests with statement coverage; reviews and inspections accepted at "
                  "system level."},
    "D": {"failure": "Minor", "objectives": 26, "independent": 2, "coverage": "None",
          "system_methods": ["Test", "Analysis", "Demonstration", "Inspection", "Review", "Similarity"],
          "test_required": True,
          "text": "Requirements-based tests of high-level requirements; no structural coverage."},
    "E": {"failure": "No safety effect", "objectives": 0, "independent": 0, "coverage": "None",
          "system_methods": ["Test", "Analysis", "Demonstration", "Inspection", "Review", "Similarity"],
          "test_required": False, "text": "No DO-178C objectives; verify as the programme requires."},
}

RULES: dict[str, dict] = {
    "avionics.req.verification": {
        "title": "Verification method for the DAL", "severity": "warning",
        "description": "A DAL A-D software requirement (HLR / LLR) is verified by test; DAL A / B system and "
                       "item requirements by test, analysis or demonstration, not by inspection alone."},
    "avionics.req.unverified": {
        "title": "Requirement without verification", "severity": "warning",
        "description": "A DAL A-C requirement that no test case verifies (directly or through a parent)."},
    "avionics.req.unimplemented": {
        "title": "Requirement not implemented", "severity": "warning",
        "description": "A DAL A-C requirement that no design element implements (directly or through a "
                       "parent)."},
    "avionics.req.derived": {
        "title": "Derived requirement without rationale", "severity": "info",
        "description": "A derived requirement needs a rationale and feedback to the safety assessment."},
    "avionics.req.safety-dal": {
        "title": "Safety related requirement at DAL E", "severity": "warning",
        "description": "A safety related requirement is assigned level E (no safety effect)."},
}


# ---------------------------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------------------------

def _count(reqs: list[dict]) -> int:
    return sum(1 + _count(r["children"]) for r in reqs)


def catalog() -> dict:
    """The skeleton sets for front ends (no project needed)."""
    return {"sets": [{"key": k, "name": s["name"], "prefix": s["prefix"], "title": s["title"],
                      "level": s["level"], "description": s["description"],
                      "requirements": _count(s["requirements"])} for k, s in SETS.items()],
            "guidance": VERIFICATION_GUIDANCE, "rules": RULES}


def _unique_set_name(repo, base: str) -> str:
    taken = {c.name for c in repo.root_package.owned_elements}
    name, i = base, 1
    while name in taken:
        i += 1
        name = f"{base}{i}"
    return name


def import_requirement_set(repo, key: str, *, name: Optional[str] = None, prefix: Optional[str] = None,
                           dal: Optional[str] = None) -> dict:
    """Create the skeleton set ``key`` (see :data:`SETS`) with its requirements.

    ``dal`` replaces the typical level of every requirement (``None`` keeps the library's).
    Applies ``Avionics.AvionicsRequirement`` (the profile is created when missing). Returns
    ``{"set": RequirementSet, "requirements": n, "key": key}``.
    """
    spec = SETS.get(key)
    if spec is None:
        raise rq.RequirementsError(f"Unknown requirement library {key!r}; use one of: {', '.join(SETS)}")
    if dal is not None and not AP.is_dal(dal):
        raise rq.RequirementsError(f"DAL must be one of {', '.join(AP.DALS)}, not {dal!r}")
    AP.ensure_profile(repo)
    set_name = name or _unique_set_name(repo, spec["name"])
    rset = rq.create_requirement_set(repo, set_name, prefix=prefix if prefix is not None else spec["prefix"],
                                     description=spec["description"])
    count = 0

    def add(parent: Element, entry: dict) -> None:
        nonlocal count
        fields = {"summary": entry["summary"], "description": entry["text"], "type": entry["type"],
                  "rationale": entry["rationale"] or None}
        if entry["method"]:
            fields["verification_method"] = entry["method"]
        req = rq.add_requirement(repo, parent, fields)
        values = {"level": spec["level"], "dal": (dal or entry["dal"]).upper(), "derived": entry["derived"],
                  "safetyRelated": entry["safety"]}
        if entry["method"]:
            values["verificationMethod"] = entry["method"].capitalize()
        AP.apply(repo, req, "AvionicsRequirement", values)
        count += 1
        for child in entry["children"]:
            add(req, child)

    for entry in spec["requirements"]:
        add(rset, entry)
    return {"set": rset, "requirements": count, "key": key}


def import_requirement_library(repo, keys: Optional[Iterable[str]] = None, *, dal: Optional[str] = None) -> list[dict]:
    """Import several skeleton sets (all by default); returns one result per set."""
    keys = list(keys or SETS)
    unknown = [k for k in keys if k not in SETS]
    if unknown:
        raise rq.RequirementsError(f"Unknown requirement library {', '.join(unknown)}; use one of: "
                                   f"{', '.join(SETS)}")
    return [import_requirement_set(repo, k, dal=dal) for k in keys]


# ---------------------------------------------------------------------------------------------
# Checks (registered with the other avionics rules by engine.avionics.safety)
# ---------------------------------------------------------------------------------------------

def _is_avionics_req(req: Element) -> bool:
    return any(a.stereotype.name == "AvionicsRequirement" for a in stereotypes_on(req))


def effective_method(req: Element) -> Optional[str]:
    """The verification method of a requirement: the generic field if set, else the stereotype's."""
    native = getattr(req, "verification_method", None)
    if native:
        return str(native).capitalize()
    value = AP.read(req, "verificationMethod")
    return str(value) if value else None


def _label(req: Element) -> str:
    return f"{req.req_id or ''} {req.name or ''}".strip() or "requirement"


def _ancestors(req: Element) -> Iterator[Element]:
    node = req.owner
    while node is not None and rq.is_requirement(node):
        yield node
        node = node.owner


def check_requirements(repo) -> Iterator[tuple]:
    """Yield ``(severity, rule, message, element, related)`` for the requirement rules."""
    index = rq.LinkIndex(repo)
    for req in rq.all_requirements(repo):
        if not _is_avionics_req(req):
            continue
        dal = AP.normalize_dal(AP.read(req, "dal"))
        level = AP.read(req, "level")
        method = effective_method(req)
        leaf = not rq.child_requirements(req)
        safety = bool(AP.read(req, "safetyRelated"))
        tag = f"{_label(req)} (DAL {dal})" if dal else _label(req)
        rank = AP.dal_rank(dal)
        if safety and dal == "E":
            yield ("warning", "avionics.req.safety-dal",
                   f"{_label(req)} is safety related but assigned DAL E (no safety effect)", req, ())
        if AP.read(req, "derived") and not (getattr(req, "rationale", None) or "").strip():
            yield ("info", "avionics.req.derived",
                   f"{_label(req)} is a derived requirement without a rationale: explain why the design "
                   "needs it and feed it back to the safety assessment", req, ())
        if not leaf or rank is None:
            continue
        software = level in ("HLR", "LLR")
        if method:
            if software and rank <= 3 and method != "Test":
                yield ("warning", "avionics.req.verification",
                       f"{tag} is a software {level} verified by {method.lower()} only: DO-178C requires "
                       f"requirements-based tests for levels A to D", req, ())
            elif not software and rank <= 1 and method not in VERIFICATION_GUIDANCE[dal]["system_methods"]:
                yield ("warning", "avionics.req.verification",
                       f"{tag} is verified by {method.lower()} only: levels A and B need test, analysis or "
                       f"demonstration", req, ())
        if rank > 2:                      # unverified / unimplemented are reported for levels A to C
            continue
        tests = _verifying_tests(index, req)
        if not tests:
            yield ("warning", "avionics.req.unverified",
                   f"{tag} has no test case that verifies it, directly or through a parent requirement",
                   req, ())
        if not _implemented(index, req):
            yield ("warning", "avionics.req.unimplemented",
                   f"{tag} is not implemented by any design element, directly or through a parent "
                   f"requirement", req, ())


def _verifying_tests(index: "rq.LinkIndex", req: Element) -> list[Element]:
    for node in (req, *_ancestors(req)):
        tests = [r.source for r in index.incoming_of_type(node, "verify") if rq.is_test_case(r.source)]
        if tests:
            return tests
    return []


def _implemented(index: "rq.LinkIndex", req: Element) -> bool:
    return any(index.incoming_of_type(node, "implement") for node in (req, *_ancestors(req)))
