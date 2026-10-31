"""JSON (de)serialization of repositories and metamodel elements.

Serialization is structural: every Element is captured by `kind`, id,
name, owner-id, and a kind-specific payload. References to other
elements are stored by id and re-bound on load.
"""
from __future__ import annotations

import importlib
import json
from typing import Any, Callable, TYPE_CHECKING

from kerml.elements import Documentation, Element, Relationship, is_pure_relationship
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package
from kerml.types import Type
from kerml.stereotypes import Stereotype, StereotypeTag, stereotypes_on
from sysmlv2.definitions import StateUsage, TransitionUsage
from sysmlv2.state_machines import StateMachineDefinition

if TYPE_CHECKING:
    from .repository import Repository


def is_pure_relationship_class(cls: type) -> bool:
    from kerml.types import Type
    return issubclass(cls, Relationship) and not issubclass(cls, Type)


_STORED: dict = {}


def _stored_attr(e: object, attr: str) -> bool:
    """Is `attr` a stored (assignable) attribute of `e`, not a derived property?"""
    cls = type(e)
    kind = _STORED.get((cls, attr))
    if kind is None:
        prop = getattr(cls, attr, None)
        if isinstance(prop, property):
            kind = 1 if prop.fset is not None else 0
        else:
            kind = 2 if prop is None else 1
        _STORED[(cls, attr)] = kind
    if kind == 2:
        return attr in getattr(e, "__dict__", {})
    return kind == 1


def _fqcn(obj: object) -> str:
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


def _resolve_class(fqcn: str) -> type:
    mod, _, name = fqcn.rpartition(".")
    return getattr(importlib.import_module(mod), name)


# -- extension codecs ----------------------------------------------------
#
# Feature modules persist extra state without editing this file:
#
#   register_codec("variants", encode, decode)
#       encode(element) -> JSON-able data, or None when the element has nothing to save
#       decode(element, data, by_id) runs after every element, link and stereotype
#       application is restored; by_id maps saved ids to restored elements.
#
#   register_repo_codec("allocations", encode, decode)
#       project-level state: encode(repo) -> data|None, decode(repo, data, by_id).
#
# The registering module's name is saved next to the data and imported on load,
# so a project loads correctly even if that module was not imported yet.

_CODECS: dict[str, tuple[str, Callable, Callable]] = {}
_REPO_CODECS: dict[str, tuple[str, Callable, Callable]] = {}


def register_codec(name: str, encode: Callable[[Element], Any],
                   decode: Callable[[Element, Any, dict], None]) -> None:
    _CODECS[name] = (encode.__module__, encode, decode)


def register_repo_codec(name: str, encode: Callable[["Repository"], Any],
                        decode: Callable[["Repository", Any, dict], None]) -> None:
    _REPO_CODECS[name] = (encode.__module__, encode, decode)


def _encode_ext(codecs: dict, target: Any) -> dict:
    out = {}
    for name, (module, encode, _decode) in codecs.items():
        data = encode(target)
        if data is not None:
            out[name] = {"module": module, "data": data}
    return out


def _decode_ext(codecs: dict, ext: dict, target: Any, by_id: dict) -> None:
    for name, entry in ext.items():
        if name not in codecs:
            importlib.import_module(entry["module"])
        codecs[name][2](target, entry["data"], by_id)


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


# Library elements get fresh UUIDs in every process, so references to them are
# saved by qualified name ("lib:KerML::ScalarValues::Real"): files stay stable
# across sessions and such typings survive a load.
_LIB_PREFIX = "lib:"


_LIBS: tuple = ()


def _libraries() -> tuple:
    global _LIBS
    if not _LIBS:
        from kerml.library import KERML_LIBRARY
        from sysmlv2.library import SYSML_LIBRARY
        _LIBS = (KERML_LIBRARY, SYSML_LIBRARY)
    return _LIBS


def _ref(e: Element) -> str:
    root = e.root()
    if any(root is lib for lib in _libraries()):
        return _LIB_PREFIX + e.qualified_name
    return e.element_id


def _library_index() -> dict[str, Element]:
    index: dict[str, Element] = {}
    for lib in _libraries():
        for x in lib.walk():
            index[x.element_id] = x
            index[_LIB_PREFIX + x.qualified_name] = x
    return index


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
        payload["typed_by"] = [_ref(t) for t in e.types]
        payload["subsets"] = [_ref(s.target) for s in e.subsettings
                              if s.target and type(s).__name__ == "Subsetting"]
        payload["redefines"] = [_ref(r.target) for r in e.redefinitions if r.target]
    if isinstance(e, Type):
        payload["specializes"] = [
            _ref(s.target) for s in e.specializations if s.target
        ]
    # SysML-specific extras ------------------------------------------------
    for attr in ("req_id", "text", "is_conjugated", "portion_kind", "is_variant",
                 "is_reference", "is_individual", "is_variation", "is_parallel"):
        if _stored_attr(e, attr):
            payload[attr] = getattr(e, attr)
    if hasattr(e, "ends"):
        payload["ends"] = [_ref(f) for f in getattr(e, "ends", []) if f]
    doc = next((a.body for a in e.annotations if isinstance(a, Documentation)), None)
    if doc:
        payload["doc"] = doc
    if hasattr(e, "parameter_kind"):
        payload["parameter_kind"] = e.parameter_kind
    apps = stereotypes_on(e)
    if apps:
        payload["stereotypes"] = [
            {"stereotype": a.stereotype.element_id, "values": a.values} for a in apps
        ]
    if isinstance(e, Stereotype):
        payload["applies_to"] = [f"{c.__module__}.{c.__qualname__}" for c in e.applies_to]
        payload["base"] = e.base.element_id if e.base else None
    # State machines: only string actions/guards persist; callables are runtime-only.
    if isinstance(e, TransitionUsage):
        payload["transition"] = {
            "source": e.transition_source.element_id if e.transition_source else None,
            "target": e.transition_target.element_id if e.transition_target else None,
            "trigger": e.trigger_event,
            "guard": _str_or_none(e.guard),
            "effect": _str_or_none(e.effect),
        }
    elif isinstance(e, StateUsage):
        payload["state"] = {
            "entry": _str_or_none(getattr(e, "entry_action", None)),
            "do": _str_or_none(getattr(e, "do_action", None)),
            "exit": _str_or_none(getattr(e, "exit_action", None)),
            "is_final": bool(getattr(e, "is_final", False)),
        }
    if isinstance(e, StateMachineDefinition):
        payload["state_machine"] = {
            "initial": e.initial_state.element_id if e.initial_state else None,
            "finals": [s.element_id for s in e.final_states],
        }
    # UI state such as canvas layout; only JSON-able entries are kept.
    tool_data = {k: v for k, v in e.tool_data.items() if _json_safe(v)}
    if tool_data:
        payload["tool_data"] = tool_data
    ext = _encode_ext(_CODECS, e)
    if ext:
        payload["ext"] = ext
    return payload


def _str_or_none(v: Any) -> Any:
    return v if isinstance(v, str) else None


def _in_library(e: Element) -> bool:
    root = e
    while root.owner is not None:
        root = root.owner
    return root.name in {"KerML", "SysML"}


def to_dict(repo: "Repository") -> dict:
    from .links import LINK_KINDS
    link_classes = tuple(lk.cls for lk in LINK_KINDS)
    elements: list[dict] = []
    links: list[dict] = []
    # Containment order (not registry order), so the same model always saves the same way.
    ordered = list(repo.root_package.walk())
    seen = {id(e) for e in ordered}
    ordered += [e for e in repo.all_elements() if id(e) not in seen]
    for e in ordered:
        # Relationships are captured by element payloads (structural) or the
        # `links` list (typed links); they are not model elements in their own right.
        if is_pure_relationship(e) or _in_library(e):
            continue
        elements.append(_encode_element(e))
        for rel in e._owned_relationships:
            if isinstance(rel, link_classes) and rel.source and rel.target:
                links.append({
                    "id": rel.element_id,
                    "class": _fqcn(rel),
                    "source": rel.source.element_id,
                    "target": rel.target.element_id,
                })
    return {
        "format": "sysmlv2-core/1",
        "name": repo.name,
        "root": repo.root_package.element_id,
        "elements": elements,
        "links": links,
        "ext": _encode_ext(_REPO_CODECS, repo),
    }


def to_json(repo: "Repository", *, indent: int = 2) -> str:
    """Deterministic JSON (sorted keys, newline at EOF) so saved projects diff cleanly."""
    return json.dumps(to_dict(repo), indent=indent, sort_keys=True) + "\n"


# -- decode ---------------------------------------------------------------

def from_dict(data: dict) -> "Repository":
    from .repository import Repository
    repo = Repository(name=data.get("name", "Project"))
    by_id: dict[str, Element] = _library_index()
    by_id[repo.root_package.element_id] = repo.root_package

    # Files written before links were split out stored Relationship objects as
    # elements; those are rebuilt from payloads/links instead, so drop them.
    raw = [r for r in data["elements"]
           if not is_pure_relationship_class(_resolve_class(r["class"]))]

    # Pass 1: instantiate every element bare.
    for r in raw:
        if r["id"] == data["root"]:
            inst = repo.root_package
            inst.name = r.get("name") or inst.name
            # Keep the saved id so references to the root stay valid across saves.
            repo.registry.unregister(inst)
            inst.element_id = r["id"]
            if r.get("doc"):
                inst.add_annotation(Documentation(body=r["doc"]))
            if r.get("tool_data"):
                inst.tool_data = dict(r["tool_data"])
        else:
            cls = _resolve_class(r["class"])
            inst = cls.__new__(cls)
            Element.__init__(inst, name=r.get("name"), short_name=r.get("short_name"),
                             element_id=r["id"])
            # Re-init kind-specific defaults via class' __init__ where possible
            try:
                cls.__init__(inst, name=r.get("name"), element_id=r["id"])
            except TypeError:
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
            if inst._owned_relationships:
                inst.remove_types()
            for tid in r.get("typed_by", []):
                tgt = by_id.get(tid)
                if tgt is not None:
                    inst.add_type(tgt)
            if inst._owned_relationships:
                inst.remove_subsettings()
            redefined = set(r.get("redefines", []))
            for sid in r.get("subsets", []):
                tgt = by_id.get(sid)
                # Files written before Phase 1 also listed redefined features as subsetted.
                if isinstance(tgt, Feature) and sid not in redefined:
                    inst.subset(tgt)
            for rid in r.get("redefines", []):
                tgt = by_id.get(rid)
                if isinstance(tgt, Feature):
                    inst.redefine(tgt)
        if isinstance(inst, Type):
            if inst._owned_relationships:
                inst.remove_specializations()
            for sid in r.get("specializes", []):
                tgt = by_id.get(sid)
                if tgt is not None:
                    inst.specialize(tgt)
        for attr in ("req_id", "text", "is_conjugated", "portion_kind", "is_variant",
                     "is_reference", "is_individual", "is_variation", "is_parallel"):
            if attr in r and _stored_attr(inst, attr):
                setattr(inst, attr, r[attr])
        if "ends" in r and hasattr(inst, "ends"):
            inst.ends = [by_id[i] for i in r["ends"] if i in by_id]
        if r.get("doc"):
            inst.add_annotation(Documentation(body=r["doc"]))
        if "parameter_kind" in r and hasattr(inst, "parameter_kind"):
            inst.parameter_kind = r["parameter_kind"]
        if "state" in r:
            s = r["state"]
            inst.entry_action, inst.do_action, inst.exit_action = s["entry"], s["do"], s["exit"]
            inst.is_final = s["is_final"]
        if "transition" in r:
            t = r["transition"]
            inst.transition_source = by_id.get(t["source"])
            inst.transition_target = by_id.get(t["target"])
            inst.trigger_event, inst.guard, inst.effect = t["trigger"], t["guard"], t["effect"]
        if r.get("tool_data"):
            inst.tool_data = dict(r["tool_data"])
        if isinstance(inst, Stereotype):
            inst.applies_to = [_resolve_class(c) for c in r.get("applies_to", [])]
            inst.base = by_id.get(r.get("base"))

    # Pass 3: cross-references that need every element to exist and be owned first.
    for st in by_id.values():
        if isinstance(st, Stereotype):
            st.tags = [c for c in st.owned_elements if isinstance(c, StereotypeTag)]
    for r in raw:
        inst = by_id[r["id"]]
        if "state_machine" in r:
            sm = r["state_machine"]
            inst.initial_state = by_id.get(sm["initial"])
            inst.final_states = [by_id[i] for i in sm["finals"] if i in by_id]
        for app in r.get("stereotypes", []):
            st = by_id.get(app["stereotype"])
            if isinstance(st, Stereotype):
                st.apply(inst, app["values"])
    for link in data.get("links", []):
        src, tgt = by_id.get(link["source"]), by_id.get(link["target"])
        if src is None or tgt is None:
            continue
        rel = _resolve_class(link["class"])(src, tgt, element_id=link["id"])
        src.add_relationship(rel)
        _replay_link_side_effects(rel, src, tgt)

    # Pass 4: extension codecs, once the core model is complete.
    repo.registry.register_tree(repo.root_package)
    for r in raw:
        if r.get("ext"):
            _decode_ext(_CODECS, r["ext"], by_id[r["id"]], by_id)
    _decode_ext(_REPO_CODECS, data.get("ext") or {}, repo, by_id)

    repo.registry.register_tree(repo.root_package)
    return repo


def _replay_link_side_effects(rel: Relationship, src: Element, tgt: Element) -> None:
    """Re-populate convenience lists (e.g. Requirement.satisfied_by) that create_link fills."""
    from .links import LINK_KINDS
    for lk in LINK_KINDS:
        if type(rel) is lk.cls:
            if lk.source_list and hasattr(src, lk.source_list):
                getattr(src, lk.source_list).append(tgt)
            if lk.target_list and hasattr(tgt, lk.target_list):
                getattr(tgt, lk.target_list).append(src)
            return


def from_json(text: str) -> "Repository":
    return from_dict(json.loads(text))
