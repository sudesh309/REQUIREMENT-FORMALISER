"""Model comparison and three-way merge of projects (System Composer *Compare* / merge).

Both work on the serialized project (``engine.to_dict``), so a project can be
compared or merged with a JSON file without loading it, and every feature that
persists through codecs (``ext``) takes part automatically.

``compare(old, new)`` lists elements that were added, removed or modified, with
property-level differences (name, kind, owner / moved, type, direction,
multiplicity, documentation, requirement id / text, connection ends,
specializations, stereotype values, links, feature data in ``ext``) and a
containment tree for display.

``three_way_merge(base, theirs, mine)`` merges the changes both sides made since
``base``: changes made on one side only are taken automatically, changes made
differently on both sides become conflicts that are resolved per conflict with
``"mine"`` or ``"theirs"`` (``MergeResult.resolve``).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .common import InteropError, library_by_id

ROOT = "<root>"
# Keys that never take part in comparison (UI layout lives in tool_data).
IGNORED_KEYS = {"id", "tool_data"}
_LABELS = {
    "name": "name", "kind": "kind", "class": "metaclass", "owner": "owner",
    "short_name": "short name", "is_abstract": "abstract", "multiplicity": "multiplicity",
    "direction": "direction", "typed_by": "type", "subsets": "subsets",
    "redefines": "redefines", "specializes": "specializes", "req_id": "req id",
    "text": "text", "ends": "connection ends", "doc": "documentation",
    "default_value": "default value", "parameter_kind": "parameter kind",
}


# --- loading ---------------------------------------------------------------------

def project_data(source: Any) -> dict:
    """A serialized project from a Repository, a dict or JSON text (validated)."""
    from engine.repository import Repository
    from engine.serializer import to_dict
    if isinstance(source, Repository):
        return to_dict(source)
    if isinstance(source, (bytes, bytearray)):
        source = source.decode("utf-8-sig")
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except ValueError as ex:
            raise InteropError(f"not a project JSON file: {ex}") from None
    if not isinstance(source, dict) or not isinstance(source.get("elements"), list) \
            or "root" not in source:
        raise InteropError("not a project JSON file (expected 'root' and 'elements')")
    for e in source["elements"]:
        if not isinstance(e, dict) or "id" not in e or "class" not in e:
            raise InteropError("project JSON has an element without 'id' / 'class'")
    return source


def _elements(data: dict) -> dict[str, dict]:
    root = data.get("root")
    return {e["id"]: e for e in data["elements"] if e["id"] != root}


def _norm_ref(data: dict, ref: Optional[str]) -> Optional[str]:
    return ROOT if ref is not None and ref == data.get("root") else ref


# --- naming ------------------------------------------------------------------------

class _Names:
    """Qualified names of ids across the projects being compared (and the libraries)."""

    def __init__(self, *datas: dict):
        self.by_id: dict[str, dict] = {}
        self.roots = {d.get("root") for d in datas}
        for d in reversed(datas):
            for e in d["elements"]:
                self.by_id[e["id"]] = e
        self.lib = {k: v.qualified_name for k, v in library_by_id().items()}

    def qname(self, ident: Optional[str]) -> str:
        if ident is None:
            return ""
        if ident == ROOT or ident in self.roots:
            return "(project)"
        if ident.startswith("lib:"):
            return ident[4:]
        if ident in self.lib:
            return self.lib[ident]
        parts: list[str] = []
        seen: set[str] = set()
        node = self.by_id.get(ident)
        while node is not None and node["id"] not in self.roots and node["id"] not in seen:
            seen.add(node["id"])
            parts.append(node.get("name") or f"<{node.get('kind', '?')}>")
            node = self.by_id.get(node.get("owner") or "")
        return "::".join(reversed(parts)) or f"<{ident[:8]}>"

    def stereotype(self, ident: str) -> str:
        """A stereotype's name as ``Stereotype.full_name`` gives it on a loaded project:
        ``Profile.Stereotype`` inside a profile, the bare name elsewhere (plain package)."""
        e = self.by_id.get(ident)
        if e is None:
            return self.qname(ident).rsplit("::", 1)[-1]
        owner = self.by_id.get(e.get("owner") or "") or {}
        name = e.get("name") or f"<{ident[:8]}>"
        return f"{owner.get('name')}.{name}" if owner.get("kind") == "Profile" else name

    def path(self, ident: str) -> list[str]:
        """Ancestor ids (outermost first) of an element, excluding the root."""
        out: list[str] = []
        node = self.by_id.get(self.by_id.get(ident, {}).get("owner") or "")
        seen: set[str] = set()
        while node is not None and node["id"] not in self.roots and node["id"] not in seen:
            seen.add(node["id"])
            out.append(node["id"])
            node = self.by_id.get(node.get("owner") or "")
        return list(reversed(out))


# --- normalized element view ----------------------------------------------------------

def _stereo_map(e: dict) -> dict[str, dict]:
    return {s["stereotype"]: dict(s.get("values") or {}) for s in e.get("stereotypes") or []}


def _links_by_source(data: dict) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for link in data.get("links") or []:
        out.setdefault(link["source"], {})[link["id"]] = link
    return out


def _link_label(names: _Names, link: dict) -> str:
    cls = link.get("class", "").rsplit(".", 1)[-1]
    return f"{cls.lower()} -> {names.qname(link.get('target'))}"


def _fmt(names: _Names, key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in ("owner",):
        return names.qname(value)
    if key in ("typed_by", "subsets", "redefines", "specializes", "ends"):
        return [names.qname(v) for v in value]
    if key == "multiplicity" and isinstance(value, list) and len(value) == 2:
        lo, hi = value
        return f"{lo}..{'*' if hi is None else hi}"
    return value


def _element_diffs(names: _Names, old_data: dict, new_data: dict, a: dict, b: dict,
                   links_a: dict, links_b: dict, include_layout: bool) -> list[dict]:
    props: list[dict] = []
    keys = sorted(set(a) | set(b))
    for k in keys:
        if k in IGNORED_KEYS and not (include_layout and k == "tool_data"):
            continue
        if k in ("stereotypes", "ext", "owner"):
            continue
        va, vb = a.get(k), b.get(k)
        if va == vb or (va in (None, [], {}, "") and vb in (None, [], {}, "")):
            continue
        props.append({"property": _LABELS.get(k, k), "key": k,
                      "old": _fmt(names, k, va), "new": _fmt(names, k, vb)})
    oa, ob = _norm_ref(old_data, a.get("owner")), _norm_ref(new_data, b.get("owner"))
    if oa != ob:
        props.append({"property": "owner (moved)", "key": "owner",
                      "old": names.qname(oa), "new": names.qname(ob)})
    sa, sb = _stereo_map(a), _stereo_map(b)
    for sid in sorted(set(sa) | set(sb), key=names.qname):
        sname = names.stereotype(sid)
        if sid not in sa:
            props.append({"property": f"«{sname}»", "key": f"stereotype:{sid}",
                          "old": None, "new": "applied"})
        elif sid not in sb:
            props.append({"property": f"«{sname}»", "key": f"stereotype:{sid}",
                          "old": "applied", "new": None})
        for prop in sorted(set(sa.get(sid, {})) | set(sb.get(sid, {}))):
            if sid in sa and sid in sb and sa[sid].get(prop) != sb[sid].get(prop):
                props.append({"property": f"{sname}.{prop}", "key": f"value:{sid}:{prop}",
                              "old": sa[sid].get(prop), "new": sb[sid].get(prop)})
    ea, eb = a.get("ext") or {}, b.get("ext") or {}
    for name in sorted(set(ea) | set(eb)):
        da = (ea.get(name) or {}).get("data")
        db = (eb.get(name) or {}).get("data")
        if da != db:
            props.append({"property": f"{name} data", "key": f"ext:{name}",
                          "old": da, "new": db})
    la = {l["id"]: _link_label(names, l) for l in links_a.values()}
    lb = {l["id"]: _link_label(names, l) for l in links_b.values()}
    ka, kb = set(la.values()), set(lb.values())
    for label in sorted(kb - ka):
        props.append({"property": "link", "key": "link", "old": None, "new": label})
    for label in sorted(ka - kb):
        props.append({"property": "link", "key": "link", "old": label, "new": None})
    return props


def compare(old: Any, new: Any, *, include_layout: bool = False,
            old_label: str = "other", new_label: str = "current") -> dict:
    """Differences from `old` to `new` (Repository, dict or JSON text)."""
    od, nd = project_data(old), project_data(new)
    names = _Names(nd, od)
    ea, eb = _elements(od), _elements(nd)
    la, lb = _links_by_source(od), _links_by_source(nd)
    changes: list[dict] = []

    def entry(ident: str, change: str, e: dict, props: list[dict]) -> dict:
        return {"id": ident, "change": change, "kind": e.get("kind", ""),
                "name": e.get("name"), "qualified_name": names.qname(ident),
                "path": names.path(ident), "properties": props}

    order = [i for i in eb] + [i for i in ea if i not in eb]
    for ident in order:
        a, b = ea.get(ident), eb.get(ident)
        if a is None:
            changes.append(entry(ident, "added", b, []))
        elif b is None:
            changes.append(entry(ident, "removed", a, []))
        else:
            props = _element_diffs(names, od, nd, a, b, la.get(ident, {}), lb.get(ident, {}),
                                   include_layout)
            if props:
                changes.append(entry(ident, "modified", b, props))
    project_props = []
    if od.get("name") != nd.get("name"):
        project_props.append({"property": "project name", "key": "name",
                              "old": od.get("name"), "new": nd.get("name")})
    for name in sorted(set(od.get("ext") or {}) | set(nd.get("ext") or {})):
        da = ((od.get("ext") or {}).get(name) or {}).get("data")
        db = ((nd.get("ext") or {}).get(name) or {}).get("data")
        if da != db:
            project_props.append({"property": f"{name} data", "key": f"ext:{name}",
                                  "old": da, "new": db})
    summary = {k: sum(1 for c in changes if c["change"] == k)
               for k in ("added", "removed", "modified")}
    return {
        "old": {"name": od.get("name"), "label": old_label, "elements": len(ea)},
        "new": {"name": nd.get("name"), "label": new_label, "elements": len(eb)},
        "identical": not changes and not project_props,
        "summary": summary,
        "project": project_props,
        "changes": changes,
        "tree": _tree(changes, names),
    }


def _tree(changes: list[dict], names: _Names) -> list[dict]:
    """Changed elements nested under their (possibly unchanged) ancestors."""
    nodes: dict[str, dict] = {}
    roots: list[dict] = []

    def node(ident: str) -> dict:
        if ident not in nodes:
            e = names.by_id.get(ident, {})
            nodes[ident] = {"id": ident, "name": e.get("name"), "kind": e.get("kind", ""),
                            "change": None, "properties": [], "children": []}
        return nodes[ident]

    for c in changes:
        n = node(c["id"])
        n["change"], n["properties"] = c["change"], c["properties"]
        chain = c["path"] + [c["id"]]
        for parent_id, child_id in zip(chain, chain[1:]):
            p, ch = node(parent_id), node(child_id)
            if not any(x is ch for x in p["children"]):
                p["children"].append(ch)
        top = node(chain[0])
        if not any(x is top for x in roots):
            roots.append(top)
    return roots


# =============================================================================
# Three-way merge
# =============================================================================

_MISSING = object()


@dataclass
class Conflict:
    id: str
    element_id: str
    element: str          # qualified name for display
    property: str         # property label ("name", "type", "«LRU».mass", "element")
    kind: str             # "modify" | "delete-modify" | "add-add"
    base: Any = None
    mine: Any = None
    theirs: Any = None

    def to_dict(self) -> dict:
        return {"id": self.id, "element_id": self.element_id, "element": self.element,
                "property": self.property, "kind": self.kind, "base": _show(self.base),
                "mine": _show(self.mine), "theirs": _show(self.theirs)}


def _show(v: Any) -> Any:
    if v is _MISSING:
        return "(absent)"
    if isinstance(v, dict) and set(v) >= {"id", "class"}:
        return f"{v.get('kind', 'element')} {v.get('name') or ''}".strip()
    return v


def _flatten(e: dict) -> dict[tuple, Any]:
    """Element payload -> {path tuple: leaf value}; dicts recurse, lists are atomic."""
    out: dict[tuple, Any] = {}
    payload = dict(e)
    stereos = payload.pop("stereotypes", None)
    for k, v in payload.items():
        if k == "id":
            continue
        if isinstance(v, dict):
            for sub, sv in _flatten_dict(v).items():
                out[(k,) + sub] = sv
        else:
            out[(k,)] = v
    for s in stereos or []:
        out[("stereotypes", s["stereotype"], "@applied")] = True
        for pk, pv in (s.get("values") or {}).items():
            out[("stereotypes", s["stereotype"], pk)] = pv
    return out


def _flatten_dict(d: dict, prefix: tuple = ()) -> dict[tuple, Any]:
    out: dict[tuple, Any] = {}
    if not d:
        out[prefix + ("@empty",)] = True
    for k, v in d.items():
        if isinstance(v, dict) and v:
            out.update(_flatten_dict(v, prefix + (k,)))
        else:
            out[prefix + (k,)] = v
    return out


def _unflatten(flat: dict[tuple, Any], ident: str) -> dict:
    e: dict[str, Any] = {"id": ident}
    stereos: dict[str, dict] = {}
    for path, v in flat.items():
        if path[0] == "stereotypes":
            sid, prop = path[1], path[2]
            entry = stereos.setdefault(sid, {})
            if prop != "@applied":
                entry[prop] = v
            continue
        node = e
        for p in path[:-1]:
            node = node.setdefault(p, {})
        if path[-1] != "@empty":
            node[path[-1]] = v
    if stereos:
        e["stereotypes"] = [{"stereotype": sid, "values": vals} for sid, vals in stereos.items()]
    return e


def _label(path: tuple, names: _Names) -> str:
    if path[0] == "stereotypes":
        sname = names.stereotype(path[1])
        return f"«{sname}»" if path[2] == "@applied" else f"«{sname}».{path[2]}"
    if path[0] == "ext":
        return "/".join(str(p) for p in path if p not in ("data", "module", "@empty"))
    return _LABELS.get(path[0], path[0]) + ("/" + "/".join(map(str, path[1:]))
                                            if len(path) > 1 else "")


@dataclass
class MergeResult:
    """Outcome of ``three_way_merge``; ``resolve`` turns it into project data."""
    base: dict
    theirs: dict
    mine: dict
    conflicts: list[Conflict] = field(default_factory=list)
    auto: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    merged: dict[str, Optional[dict]] = field(default_factory=dict, repr=False)  # id -> flat
    order: list[str] = field(default_factory=list, repr=False)
    links: dict[str, Optional[dict]] = field(default_factory=dict, repr=False)
    name: Any = None
    ext: dict = field(default_factory=dict, repr=False)
    appliers: dict[str, Any] = field(default_factory=dict, repr=False)

    def summary(self) -> dict:
        return {"conflicts": len(self.conflicts), "auto_merged": len(self.auto),
                "notes": list(self.notes)}

    def to_dict(self) -> dict:
        return {"conflicts": [c.to_dict() for c in self.conflicts], "auto": list(self.auto),
                "notes": list(self.notes), "summary": self.summary()}

    def resolve(self, choices: Optional[dict[str, str]] = None, default: str = "mine") -> dict:
        """The merged project data; each conflict takes ``choices[id]`` (``mine``/``theirs``)."""
        choices = dict(choices or {})
        if default not in ("mine", "theirs"):
            raise InteropError("default must be 'mine' or 'theirs'")
        known = {c.id for c in self.conflicts}
        for cid, side in choices.items():
            if cid not in known:
                raise InteropError(f"unknown conflict {cid!r}")
            if side not in ("mine", "theirs"):
                raise InteropError(f"conflict {cid}: choose 'mine' or 'theirs', not {side!r}")
        state = {
            "elements": {i: (copy.deepcopy(f) if f is not None else None)
                         for i, f in self.merged.items()},
            "name": self.name,
            "ext": copy.deepcopy(self.ext),
        }
        for c in self.conflicts:
            self.appliers[c.id](state, choices.get(c.id, default))
        elements: dict[str, Optional[dict]] = state["elements"]
        all_ids = self._all_ids()
        kept = {i for i, f in elements.items() if f is not None}
        # Drop elements whose owner no longer exists (cascade).
        changed = True
        while changed:
            changed = False
            for ident in list(kept):
                owner = elements[ident].get(("owner",))
                if owner not in (None, ROOT) and owner not in kept and owner in all_ids:
                    kept.discard(ident)
                    changed = True
        notes = list(self.notes)
        root = self.mine.get("root")
        out_elements: list[dict] = []
        root_payload = next((copy.deepcopy(e) for e in self.mine["elements"] if e["id"] == root),
                            None)
        if root_payload is not None:
            root_payload["name"] = state["name"]
            out_elements.append(root_payload)
        dropped_connectors: list[str] = []
        for ident in self.order:
            if ident not in kept:
                continue
            flat = elements[ident]
            if flat.get(("owner",)) == ROOT:
                flat[("owner",)] = root
            ends = flat.get(("ends",))
            if isinstance(ends, list) and any(r in all_ids and r not in kept for r in ends):
                dropped_connectors.append(str(flat.get(("name",)) or ident))
                continue
            for key in (("typed_by",), ("subsets",), ("redefines",), ("specializes",)):
                refs = flat.get(key)
                if isinstance(refs, list):
                    alive = [r for r in refs if r in kept or r not in all_ids]
                    if len(alive) != len(refs):
                        notes.append(f"{flat.get(('name',)) or ident}: dropped "
                                     f"{_LABELS.get(key[0], key[0])} reference(s) to deleted "
                                     "elements")
                        flat[key] = alive
            for path in [p for p in flat if p[0] == "stereotypes"]:
                if path[1] in all_ids and path[1] not in kept:
                    del flat[path]
            out_elements.append(_unflatten(flat, ident))
        if dropped_connectors:
            notes.append("removed connector(s) whose ends were deleted: "
                         + ", ".join(sorted(dropped_connectors)))
        kept_out = {e["id"] for e in out_elements}
        links = [l for l in self.links.values() if l is not None and l["source"] in kept_out
                 and (l["target"] in kept_out or l["target"] not in all_ids)]
        self.resolved_notes = notes
        return {"format": self.mine.get("format", "sysmlv2-core/1"), "name": state["name"],
                "root": root, "elements": out_elements, "links": links, "ext": state["ext"]}

    def _all_ids(self) -> set[str]:
        ids: set[str] = set()
        for d in (self.base, self.theirs, self.mine):
            ids |= {e["id"] for e in d["elements"]}
        return ids


def _owner_map(elements: dict[str, dict]) -> dict[str, Optional[str]]:
    return {i: e.get("owner") for i, e in elements.items()}


def _inside(ident: str, ancestor: str, owners: dict[str, Optional[str]]) -> bool:
    seen: set[str] = set()
    node = owners.get(ident)
    while node is not None and node not in seen:
        if node == ancestor:
            return True
        seen.add(node)
        node = owners.get(node)
    return False


def three_way_merge(base: Any, theirs: Any, mine: Any) -> MergeResult:
    """Merge `theirs` and `mine`, both derived from `base` (Repository, dict or JSON text)."""
    bd, td, md = project_data(base), project_data(theirs), project_data(mine)
    res = MergeResult(bd, td, md)
    names = _Names(md, td, bd)
    eb, et, em = _elements(bd), _elements(td), _elements(md)
    roots = {bd.get("root"), td.get("root"), md.get("root")}
    owners_t, owners_m = _owner_map(et), _owner_map(em)

    def norm(e: Optional[dict]) -> Optional[dict]:
        if e is None:
            return None
        flat = _flatten(e)
        if flat.get(("owner",)) in roots:
            flat[("owner",)] = ROOT
        return flat

    def conflict(ident: str, prop: str, kind: str, b: Any, m: Any, t: Any, applier) -> None:
        cid = f"c{len(res.conflicts) + 1}"
        res.conflicts.append(Conflict(cid, ident, names.qname(ident), prop, kind, b, m, t))
        res.appliers[cid] = applier

    def note(ident: str, prop: str, side: str) -> None:
        res.auto.append({"element_id": ident, "element": names.qname(ident),
                         "property": prop, "from": side})

    def changed_inside(ident: str, side: dict, owners: dict) -> bool:
        return any(_inside(x, ident, owners) and (x not in eb or norm(eb[x]) != norm(e))
                   for x, e in side.items())

    res.order = list(dict.fromkeys(list(em) + list(et) + list(eb)))
    for ident in res.order:
        fb, ft, fm = norm(eb.get(ident)), norm(et.get(ident)), norm(em.get(ident))
        if fm is not None and ft is not None:
            if fm == ft:
                res.merged[ident] = fm
                continue
            base_flat = fb or {}
            merged: dict[tuple, Any] = {}
            for path in dict.fromkeys(list(fm) + list(ft) + list(base_flat)):
                vb = base_flat.get(path, _MISSING)
                vm, vt = fm.get(path, _MISSING), ft.get(path, _MISSING)
                if vm == vt:
                    val = vm
                elif vm == vb:
                    val = vt
                    note(ident, _label(path, names), "theirs")
                elif vt == vb:
                    val = vm
                    note(ident, _label(path, names), "mine")
                else:
                    val = vm

                    def apply(state, side, ident=ident, path=path, vm=vm, vt=vt):
                        flat = state["elements"].get(ident)
                        if flat is None:
                            return
                        v = vm if side == "mine" else vt
                        if v is _MISSING:
                            flat.pop(path, None)
                        else:
                            flat[path] = v
                    conflict(ident, _label(path, names), "modify" if fb else "add-add",
                             vb, vm, vt, apply)
                if val is not _MISSING:
                    merged[path] = val
            res.merged[ident] = merged
        elif fm is None and ft is None:
            res.merged[ident] = None                       # deleted on both sides
        elif fb is None:
            res.merged[ident] = fm if fm is not None else ft
            note(ident, "element added", "mine" if fm is not None else "theirs")
        else:
            deleted_in = "mine" if fm is None else "theirs"
            other = ft if fm is None else fm
            other_side, other_owners = (et, owners_t) if fm is None else (em, owners_m)
            if other == fb and not changed_inside(ident, other_side, other_owners):
                res.merged[ident] = None
                note(ident, "element deleted", deleted_in)
                continue
            res.merged[ident] = None if deleted_in == "mine" else fm

            def apply(state, side, ident=ident, deleted_in=deleted_in, other=other):
                state["elements"][ident] = None if side == deleted_in else copy.deepcopy(other)
            conflict(ident, "element", "delete-modify", "(exists)",
                     "(deleted)" if deleted_in == "mine" else "(modified)",
                     "(deleted)" if deleted_in == "theirs" else "(modified)", apply)
    # Links are identified by id and never edited: merge additions and deletions.
    lb = {l["id"]: l for l in bd.get("links") or []}
    lt = {l["id"]: l for l in td.get("links") or []}
    lm = {l["id"]: l for l in md.get("links") or []}
    for lid in dict.fromkeys(list(lm) + list(lt) + list(lb)):
        if lid in lm and (lid in lt or lid not in lb):
            res.links[lid] = lm[lid]
        elif lid in lt and lid not in lb:
            res.links[lid] = lt[lid]
            note(lt[lid]["source"], "link added", "theirs")
        else:
            res.links[lid] = None
            if lid in lb:
                note(lb[lid]["source"], "link deleted", "theirs" if lid in lm else "mine")
    # Project name and project-level feature data (``ext``).
    nb, nt, nm = bd.get("name"), td.get("name"), md.get("name")
    res.name = nm if (nm == nt or nt == nb) else nt if nm == nb else nm
    if nm != nt and nm != nb and nt != nb:
        def apply_name(state, side, nm=nm, nt=nt):
            state["name"] = nm if side == "mine" else nt
        conflict(md.get("root"), "project name", "modify", nb, nm, nt, apply_name)
    xb, xt, xm = bd.get("ext") or {}, td.get("ext") or {}, md.get("ext") or {}
    for key in dict.fromkeys(list(xm) + list(xt) + list(xb)):
        vb, vt, vm = xb.get(key, _MISSING), xt.get(key, _MISSING), xm.get(key, _MISSING)
        if vm == vt or vt == vb:
            val = vm
        elif vm == vb:
            val = vt
        else:
            val = vm

            def apply_ext(state, side, key=key, vm=vm, vt=vt):
                v = vm if side == "mine" else vt
                if v is _MISSING:
                    state["ext"].pop(key, None)
                else:
                    state["ext"][key] = v
            conflict(md.get("root"), f"{key} (project data)", "modify", vb, vm, vt, apply_ext)
        if val is not _MISSING:
            res.ext[key] = val
    return res


def merge_to_repo(result: MergeResult, choices: Optional[dict[str, str]] = None,
                  default: str = "mine"):
    """Resolve the merge and load it as a Repository."""
    from engine.serializer import from_dict
    data = result.resolve(choices, default)
    try:
        return from_dict(data)
    except Exception as ex:  # noqa: BLE001 - report as an interop problem
        raise InteropError(f"the merged project could not be loaded: {ex}") from None
