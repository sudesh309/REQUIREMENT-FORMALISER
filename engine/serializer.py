"""JSON (de)serialization of repositories and metamodel elements.

Serialization is structural: every Element is captured by `kind`, id,
name, owner-id, and a kind-specific payload. References to other
elements are stored by id and re-bound on load.
"""
from __future__ import annotations

import importlib
import json
from typing import Any, TYPE_CHECKING

from kerml.elements import Element
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package

if TYPE_CHECKING:
    from .repository import Repository


def _fqcn(obj: object) -> str:
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


def _resolve_class(fqcn: str) -> type:
    mod, _, name = fqcn.rpartition(".")
    return getattr(importlib.import_module(mod), name)


# -- encode ---------------------------------------------------------------

def _encode_element(e: Element) -> dict:
    payload: dict[str, Any] = {
        "id": e.element_id,
        "class": _fqcn(e),
        "kind": getattr(e, "kind", "Element"),
        "name": e.name,
        "short_name": e.short_name,
        "is_abstract": e.is_abstract,
        "owner": e.owner.element_id if e.owner else None,
    }
    if isinstance(e, Feature):
        payload["multiplicity"] = [e.multiplicity.lower, e.multiplicity.upper]
        payload["direction"] = e.direction.value
        payload["is_composite"] = e.is_composite
        payload["is_readonly"] = e.is_readonly
        payload["is_derived"] = e.is_derived
        payload["is_end"] = e.is_end
        payload["default_value"] = e.default_value
        payload["typed_by"] = [t.element_id for t in e.types]
        payload["subsets"] = [s.target.element_id for s in e.subsettings if s.target]
        payload["redefines"] = [r.target.element_id for r in e.redefinitions if r.target]
    if hasattr(e, "specializations"):
        payload["specializes"] = [
            s.target.element_id for s in e.specializations if s.target
        ]
    # SysML-specific extras ------------------------------------------------
    for attr in ("req_id", "text", "is_conjugated", "portion_kind", "is_variant",
                 "is_reference", "is_individual", "is_variation", "is_parallel"):
        if hasattr(e, attr):
            payload[attr] = getattr(e, attr)
    if hasattr(e, "ends"):
        payload["ends"] = [f.element_id for f in getattr(e, "ends", []) if f]
    return payload


def to_dict(repo: "Repository") -> dict:
    elements: list[dict] = []
    for e in repo.all_elements():
        # Skip the standard libraries — they are reconstructed on load.
        root = e
        while root.owner is not None:
            root = root.owner
        if root.name in {"KerML", "SysML"}:
            continue
        elements.append(_encode_element(e))
    return {
        "format": "sysmlv2-core/1",
        "name": repo.name,
        "root": repo.root_package.element_id,
        "elements": elements,
    }


def to_json(repo: "Repository", *, indent: int = 2) -> str:
    return json.dumps(to_dict(repo), indent=indent)


# -- decode ---------------------------------------------------------------

def from_dict(data: dict) -> "Repository":
    from .repository import Repository
    repo = Repository(name=data.get("name", "Project"))
    by_id: dict[str, Element] = {repo.root_package.element_id: repo.root_package}

    raw = data["elements"]
    raw_by_id = {r["id"]: r for r in raw}

    # Pass 1: instantiate every element bare.
    for r in raw:
        if r["id"] == data["root"]:
            inst = repo.root_package
            inst.name = r.get("name") or inst.name
        else:
            cls = _resolve_class(r["class"])
            inst = cls.__new__(cls)
            Element.__init__(inst, name=r.get("name"), short_name=r.get("short_name"),
                             element_id=r["id"])
            # Re-init kind-specific defaults via class' __init__ where possible
            try:
                cls.__init__(inst, name=r.get("name"))
            except TypeError:
                pass
            inst.element_id = r["id"]
            inst.is_abstract = r.get("is_abstract", False)
        by_id[r["id"]] = inst

    # Pass 2: rebuild ownership and references.
    for r in raw:
        if r["id"] == data["root"]:
            continue
        inst = by_id[r["id"]]
        owner_id = r.get("owner")
        owner = by_id.get(owner_id) if owner_id else repo.root_package
        if isinstance(owner, Namespace):
            owner.own(inst)
        if isinstance(inst, Feature):
            lo, hi = r.get("multiplicity", [0, None])
            inst.multiplicity = MultiplicityRange(lo, hi)
            from kerml.features import FeatureDirection
            inst.direction = FeatureDirection(r.get("direction", "none"))
            inst.is_composite = r.get("is_composite", False)
            inst.is_readonly = r.get("is_readonly", False)
            inst.is_derived = r.get("is_derived", False)
            inst.is_end = r.get("is_end", False)
            inst.default_value = r.get("default_value")
            inst.feature_typings = []
            for tid in r.get("typed_by", []):
                tgt = by_id.get(tid)
                if tgt is not None:
                    inst.add_type(tgt)
            inst.subsettings = []
            for sid in r.get("subsets", []):
                tgt = by_id.get(sid)
                if isinstance(tgt, Feature):
                    inst.subset(tgt)
            for rid in r.get("redefines", []):
                tgt = by_id.get(rid)
                if isinstance(tgt, Feature):
                    inst.redefine(tgt)
        if hasattr(inst, "specializations"):
            inst.specializations = []
            for sid in r.get("specializes", []):
                tgt = by_id.get(sid)
                if tgt is not None:
                    inst.specialize(tgt)
        for attr in ("req_id", "text", "is_conjugated", "portion_kind", "is_variant",
                     "is_reference", "is_individual", "is_variation", "is_parallel"):
            if attr in r and hasattr(inst, attr):
                setattr(inst, attr, r[attr])
        if "ends" in r and hasattr(inst, "ends"):
            inst.ends = [by_id[i] for i in r["ends"] if i in by_id]
        repo.registry.register(inst)

    return repo


def from_json(text: str) -> "Repository":
    return from_dict(json.loads(text))
