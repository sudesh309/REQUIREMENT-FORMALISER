"""Project templates: "File > New from template" for avionics.

========================  =============================================================================
Template                  Contents
========================  =============================================================================
``blank``                 the ``Avionics`` profile, the full interface library, the four requirement
                          skeleton sets (ARP4754A system and item, DO-178C HLR and LLR), an empty FHA
                          table and an empty ``SystemArchitecture``
``ima_example``           the complete IMA avionics example (see :mod:`engine.avionics.example`)
========================  =============================================================================

``create_project(template, name)`` returns a fresh :class:`~engine.Repository`; the web API
(``POST /api/new/avionics``) and the MCP tool ``sysml_create_avionics_project`` install it as the
current project, which starts a new undo history like *New*.
"""
from __future__ import annotations

from typing import Optional

import engine.requirements as rq
from engine import Repository
from engine import architecture as A

from . import interfaces_lib, requirements_lib
from . import profile as AP
from . import safety as SF

__all__ = ["TEMPLATES", "list_templates", "create_project", "populate_blank", "template_info", "overview"]

TEMPLATES: list[dict] = [
    {"id": "blank", "name": "Blank avionics project", "default_name": "AvionicsProject",
     "description": "Avionics profile, interface library, ARP4754A / DO-178C requirement skeletons, an "
                    "empty FHA table and an empty system architecture: a starting point for your own system.",
     "includes": ["Avionics profile (equipment, IMA, software and bus stereotypes)",
                  "Interface library (ARINC 429 / 664 / 825 / 653, MIL-STD-1553B, discrete, analog, power)",
                  "Requirement skeletons: ARP4754A system and item, DO-178C HLR and LLR",
                  "Empty FHA table", "Empty SystemArchitecture"]},
    {"id": "ima_example", "name": "Complete IMA avionics example", "default_name": "IMA_Avionics",
     "description": "A whole avionics system: air data, inertial, radio altimeter and GNSS, dual flight "
                    "control computers with monitors, PFD / ND / EICAS, an IMA cabinet with partitions and "
                    "software items, a redundant AFDX network with ARINC 429, MIL-STD-1553B, discrete and "
                    "analog legs, requirements, allocation, FHA and a state machine.",
     "includes": ["Functional, logical and physical architectures with interfaces on every port",
                  "Avionics stereotype values (mass, power, MTBF, DAL ...) on all equipment",
                  "ARP4754A / DO-178C requirement sets linked to components and test cases, with open gaps",
                  "Function to logical item to hardware / IMA partition allocation",
                  "FHA table, FCC mode state machine"]},
]

_COUNTS: dict[str, dict] = {}


def template_info(template_id: str) -> dict:
    t = next((t for t in TEMPLATES if t["id"] == template_id), None)
    if t is None:
        raise ValueError(f"Unknown template {template_id!r}; use one of: {', '.join(x['id'] for x in TEMPLATES)}")
    return t


def list_templates(*, counts: bool = False) -> list[dict]:
    """The templates; with ``counts`` each carries what it builds (computed once, ~0.5 s)."""
    out = [dict(t) for t in TEMPLATES]
    if counts:
        for t in out:
            t["counts"] = _counts(t["id"])
    return out


def _counts(template_id: str) -> dict:
    if template_id not in _COUNTS:
        from . import example
        repo = create_project(template_id)
        _COUNTS[template_id] = example.describe_example(repo) if template_id == "ima_example" else {
            "interfaces": len(interfaces_lib.ITEMS), "requirement_sets": [s["name"] for s in requirements_lib.SETS.values()],
            "requirements": sum(requirements_lib._count(s["requirements"]) for s in requirements_lib.SETS.values())}
    return _COUNTS[template_id]


def populate_blank(repo: Repository, architecture: str = "SystemArchitecture") -> dict:
    """Profile, libraries, FHA table and an empty system architecture in ``repo``."""
    A.set_model_type(repo, "system")
    AP.ensure_profile(repo)
    lib = interfaces_lib.import_library(repo)
    sets = requirements_lib.import_requirement_library(repo)
    SF.fha_table(repo, create=True)
    arch = A.create_architecture(repo, architecture)
    return {"architecture": arch, "interfaces": len(lib["created"]),
            "requirement_sets": [r["set"].name for r in sets]}


def create_project(template: str, name: Optional[str] = None) -> Repository:
    """A new project from a template (``blank`` or ``ima_example``)."""
    info = template_info(template)
    pname = (name or "").strip() or info["default_name"]
    if "::" in pname:
        raise ValueError("a project name cannot contain '::'")
    if template == "blank":
        repo = Repository(pname)
        populate_blank(repo)
        return repo
    from . import example
    return example.build_example(pname)


def overview(repo: Repository) -> dict:
    """What the project holds of the avionics pack: profile, libraries, FHA, safety counts, roll-up."""
    prof = AP.find_profile(repo)
    lib = interfaces_lib.library_status(repo)
    check = SF.safety_check(repo)
    table = SF.fha_table(repo)
    roots = [a for a in A.architecture_roots(repo) if A.components_of(a)]
    return {
        "project": repo.name,
        "profile": {"present": prof is not None, "id": prof.element_id if prof else None,
                    "version": prof.version if prof else None,
                    "stereotypes": [s.name for s in prof.stereotypes] if prof else [],
                    "expected": [s["name"] for s in AP.STEREOTYPES]},
        "interfaces": {"present": lib["present"], "total": lib["count"]},
        "requirement_sets": [{"id": s.element_id, "name": s.name, "prefix": s.id_prefix,
                              "requirements": sum(1 for _ in rq.walk_requirements(s))}
                             for s in rq.requirement_sets(repo)],
        "fha": {"rows": len(SF.fha_rows(repo)), "table_id": table.element_id if table else None},
        "safety": {"counts": check["counts"], "total": check["total"]},
        "equipment": AP.equipment_summary(repo),
        "architectures": [{"id": a.element_id, "name": a.name} for a in sorted(roots, key=lambda a: a.name or "")],
        "templates": list_templates(),
    }
