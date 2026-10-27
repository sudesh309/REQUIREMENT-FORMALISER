"""MCP tools for profiles, stereotypes and typed stereotype properties.

All logic lives in :mod:`engine.profiles`. Stereotypes are addressed by id,
``Profile.Stereotype`` or a unique bare name; property values by
``Profile.Stereotype.property``. Numeric values may carry a compatible unit
(``"2.5 lb"`` for a kg property) or be an arithmetic expression (``"2*0.75"``).

``sysml_apply_stereotype`` here replaces the core tool of the same name (same
arguments and result keys): it also accepts ``Profile.Stereotype`` and unique
bare names, dotted value keys, and refuses duplicates with a clear message.

Reference components (a ``PartUsage`` typed by a ``PartDefinition``) inherit the stereotypes
and values of their definition: the read tools list them with ``inherited`` / ``origin``,
``sysml_set_stereotype_property`` (or applying the stereotype with values) overrides a value
on the component, ``sysml_reset_stereotype_property`` inherits the definition's again.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from engine import profiles as P
from engine import units
from kerml.stereotypes import (
    CATEGORIES, Profile, StereotypeError, effective_applications, stereotypes_on,
)
from mcp_server.core import SESSION, _err, _ok, register_kind, register_summary_hook


def _repo():
    return SESSION.repo


def _call(fn: Callable[[], Any]) -> dict:
    try:
        return _ok(fn())
    except (P.ProfileError, StereotypeError, units.UnitError) as ex:
        return _err(str(ex))


def _given(**kw: Any) -> dict:
    """Keyword arguments the caller actually passed (None means 'not given')."""
    return {k: v for k, v in kw.items() if v is not None}


# --- profiles -----------------------------------------------------------------

def tool_profile_vocabulary() -> dict:
    """The values a profile definition may use: property types, applies-to categories, icons ..."""
    meta = P.meta()
    return _ok({k: v for k, v in meta.items() if k != "units"})


def tool_list_profiles() -> dict:
    def run():
        repo = _repo()
        return {"profiles": [P.describe_profile(repo, p) for p in P.profiles_of(repo)],
                "ungrouped": [P.describe_stereotype(repo, s) for s in P.stereotypes_of(repo)
                              if s.profile is None],
                "imports": P.import_log(repo)}
    return _call(run)


def tool_create_profile(name: str, description: str = "", version: str = "1.0") -> dict:
    return _call(lambda: P.describe_profile(
        _repo(), P.create_profile(_repo(), name, description=description, version=version)))


def tool_update_profile(profile: str, name: Optional[str] = None, description: Optional[str] = None,
                        version: Optional[str] = None, root_stereotype: Optional[str] = None) -> dict:
    def run():
        repo = _repo()
        kw = _given(name=name, description=description, version=version)
        if root_stereotype is not None:
            kw["root_stereotype"] = root_stereotype or None
        out = P.update_profile(repo, P.find_profile(repo, profile), **kw)
        return {**P.describe_profile(repo, out["profile"]), "root_applied": out["root_applied"]}
    return _call(run)


def tool_delete_profile(profile: str) -> dict:
    return _call(lambda: P.delete_profile(_repo(), P.find_profile(_repo(), profile)))


def tool_export_profile(profile: str, path: Optional[str] = None) -> dict:
    def run():
        p = P.find_profile(_repo(), profile)
        text = P.export_profile_json(p)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return {"saved": path, "file_name": P.profile_file_name(p)}
        return {"file_name": P.profile_file_name(p), "text": text}
    return _call(run)


def tool_import_profile(text: Optional[str] = None, path: Optional[str] = None,
                        replace: bool = False) -> dict:
    def run():
        content, name = text, ""
        if path:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if not content:
            raise P.ProfileError("give the profile file as 'text' or 'path'")
        out = P.import_profile(_repo(), content, replace=replace, file_name=name)
        return {"profile": P.describe_profile(_repo(), out["profile"]),
                "created": out["created"], "report": out["report"]}
    return _call(run)


# --- stereotypes --------------------------------------------------------------

def tool_add_stereotype(profile: str, name: str, description: str = "", applies_to: str = "",
                        base: Optional[str] = None, abstract: bool = False,
                        style: Optional[dict] = None, defaults: Optional[dict] = None) -> dict:
    def run():
        repo = _repo()
        st = P.add_stereotype(repo, P.find_profile(repo, profile), name, description=description,
                              applies_to=applies_to, base=base, abstract=abstract,
                              style=style, defaults=defaults)
        return P.describe_stereotype(repo, st)
    return _call(run)


def tool_update_stereotype(stereotype: str, name: Optional[str] = None,
                           description: Optional[str] = None, applies_to: Optional[str] = None,
                           base: Optional[str] = None, abstract: Optional[bool] = None,
                           style: Optional[dict] = None, defaults: Optional[dict] = None,
                           force: bool = False) -> dict:
    def run():
        repo = _repo()
        kw = _given(name=name, description=description, applies_to=applies_to,
                    abstract=abstract, style=style, defaults=defaults)
        if base is not None:
            kw["base"] = base or None
        out = P.update_stereotype(repo, P.find_stereotype(repo, stereotype), force=force, **kw)
        return {**P.describe_stereotype(repo, out["stereotype"]), "stripped": out["stripped"]}
    return _call(run)


def tool_delete_stereotype(stereotype: str) -> dict:
    return _call(lambda: P.delete_stereotype(_repo(), P.find_stereotype(_repo(), stereotype)))


def tool_add_stereotype_property(stereotype: str, name: str, type: str = "double", unit: str = "",
                                 default: Any = None, min: Any = None, max: Any = None,
                                 literals: Optional[list] = None, description: str = "",
                                 index: Optional[int] = None) -> dict:
    def run():
        repo = _repo()
        tag = P.add_property(repo, P.find_stereotype(repo, stereotype), name, type, unit=unit,
                             default=default, minimum=min, maximum=max, literals=literals,
                             description=description, index=index)
        return tag.describe()
    return _call(run)


def tool_update_stereotype_property(stereotype: str, property: str, name: Optional[str] = None,
                                    type: Optional[str] = None, unit: Optional[str] = None,
                                    default: Any = None, min: Any = None, max: Any = None,
                                    literals: Optional[list] = None,
                                    description: Optional[str] = None,
                                    index: Optional[int] = None, clear: Optional[list] = None) -> dict:
    def run():
        repo = _repo()
        st = P.find_stereotype(repo, stereotype)
        tag = P.find_property(repo, property, st)
        kw = _given(name=name, prop_type=type, unit=unit, default=default, minimum=min,
                    maximum=max, literals=literals, description=description, index=index)
        rename = {"type": "prop_type", "min": "minimum", "max": "maximum"}
        for key in clear or []:              # explicitly clear default / min / max / unit
            kw[rename.get(key, key)] = "" if key == "unit" else None
        out = P.update_property(repo, tag, **kw)
        return {**tag.describe(), "converted": out["converted"], "reset": out["reset"]}
    return _call(run)


def tool_delete_stereotype_property(stereotype: str, property: str) -> dict:
    def run():
        repo = _repo()
        return P.delete_property(repo, P.find_property(repo, property, P.find_stereotype(repo, stereotype)))
    return _call(run)


# --- applications -------------------------------------------------------------

def tool_apply_stereotype(stereotype: str, target: str, values: Optional[dict] = None) -> dict:
    """Extends the core ``sysml_apply_stereotype`` (same name and result keys)."""
    def run():
        repo = _repo()
        e = P.find_element(repo, target)
        st = P.find_stereotype(repo, stereotype)
        app = P.apply_stereotype(repo, e, st, values or {})
        return {"applied": st.name, "stereotype": st.full_name, "to": e.qualified_name,
                "values": app.values, "stereotypes": P.element_stereotypes(e)}
    return _call(run)


def tool_remove_stereotype(target: str, stereotype: Optional[str] = None) -> dict:
    def run():
        repo = _repo()
        e = P.find_element(repo, target)
        if stereotype:
            P.remove_stereotype(repo, e, P.find_stereotype(repo, stereotype))
            removed = 1
        else:
            removed = P.remove_all_stereotypes(repo, e)
        # What the element still carries: stereotypes inherited from its definition stay.
        return {"removed": removed, "applied": [a.stereotype.full_name for a in stereotypes_on(e)],
                "inherited": [a.stereotype.full_name for a in effective_applications(e) if a.inherited]}
    return _call(run)


def tool_set_stereotype_property(target: str, property: Optional[str] = None, value: Any = None,
                                 values: Optional[dict] = None) -> dict:
    def run():
        repo = _repo()
        e = P.find_element(repo, target)
        todo = dict(values or {})
        if property:
            todo[property] = value
        if not todo:
            raise P.ProfileError("give 'property' and 'value', or 'values'")
        return {"stored": P.set_property_values(repo, e, todo),
                "stereotypes": P.element_stereotypes(e)}
    return _call(run)


def tool_reset_stereotype_property(target: str, property: Optional[str] = None,
                                   properties: Optional[list] = None) -> dict:
    def run():
        repo = _repo()
        e = P.find_element(repo, target)
        paths = list(properties or [])
        if property:
            paths.append(property)
        out = P.reset_property_values(repo, e, paths)
        return {**out, "stereotypes": P.element_stereotypes(e)}
    return _call(run)


def tool_get_stereotype_properties(target: str, property: Optional[str] = None) -> dict:
    def run():
        repo = _repo()
        e = P.find_element(repo, target)
        if property:
            a, tag = P.resolve_value_path(e, property)
            v = a.get(tag.name)
            parent = a.parent()
            out = {"property": f"{a.stereotype.full_name}.{tag.name}", "value": v,
                   "unit": tag.unit, "type": tag.type_label(),
                   "display": P.format_value(v, tag.unit),
                   # own / inherited (from the definition a reference component is typed by) / default
                   "origin": a.origin(tag.name), "inherited": a.origin(tag.name) == "inherited"}
            if parent is not None:
                out.update(overridden=a.origin(tag.name) == "own", inherited_value=parent.get(tag.name),
                           inherited_from=parent.annotated_element.qualified_name)
            return out
        return {"element": e.qualified_name, "stereotypes": P.element_stereotypes(e),
                "applicable": [s.full_name for s in P.applicable_stereotypes(repo, e)]}
    return _call(run)


def tool_batch_apply_stereotype(stereotype: str, scope: str = "model", ids: Optional[list] = None,
                                root: Optional[str] = None, category: Optional[str] = None,
                                values: Optional[dict] = None, dry_run: bool = False) -> dict:
    def run():
        repo = _repo()
        return P.batch_apply(repo, P.find_stereotype(repo, stereotype), scope=scope, root=root,
                             elements=ids, category=category, values=values, dry_run=dry_run)
    return _call(run)


def tool_list_units(quantity: Optional[str] = None) -> dict:
    rows = units.list_units()
    if quantity:
        rows = [u for u in rows if u["quantity"] == quantity]
    return _ok(rows)


def tool_convert_units(value: Any, to: str, unit: Optional[str] = None) -> dict:
    def run():
        num, parsed = units.parse_quantity(str(value))
        src = unit or parsed
        if not src:
            raise units.UnitError("give the unit inside 'value' (e.g. '3 lb') or as 'unit'")
        return {"value": units.convert(num, src, to), "unit": units.normalize_unit(to)}
    return _call(run)


# --- element summaries ----------------------------------------------------------

def _summary(e, out: dict) -> None:
    apps = effective_applications(e)
    if not apps:
        return
    badges, style = P.display_fields(e)
    out.setdefault("badges", []).extend(badges)
    out.setdefault("style", {}).update(style)
    out["stereotypes"] = [{"stereotype": a.stereotype.full_name, "values": a.values,
                           "inherited": bool(a.inherited)} for a in apps]


register_summary_hook(_summary)
register_kind("Profile", Profile)

# The applies-to categories, from the metamodel so the text cannot go stale.
_CATEGORY_TEXT = ", ".join(c for c in CATEGORIES if c)
_STYLE_SCHEMA = {"type": "object", "description": "Display style: fill / stroke / text (hex colours), "
                 "icon (one of the fixed icons), line (solid|dashed|dotted|dashdot, connectors)"}
_DEFAULTS_SCHEMA = {"type": "object", "description": "Default stereotypes applied to new elements "
                    "created inside an element carrying this stereotype: {component, port, connector}"}
_ANY = {"description": "number, text (may carry a unit: '2.5 lb', or be an expression: '2*0.75'), "
        "boolean or enumeration literal"}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS: list[dict] = [
    {"name": "sysml_profile_vocabulary",
     "description": "The vocabulary of profile definitions: property types, applies-to categories "
                    "(including Allocation and AllocationSet), icons, line styles, default slots. "
                    "Units are listed by sysml_list_units.",
     "inputSchema": _schema({}, []), "handler": tool_profile_vocabulary},
    {"name": "sysml_list_profiles",
     "description": "List profiles with their stereotypes and typed properties, stereotypes outside "
                    "profiles, and the profile import log.",
     "inputSchema": _schema({}, []), "handler": tool_list_profiles},
    {"name": "sysml_create_profile",
     "description": "Create a profile (a package of stereotypes) in the project.",
     "inputSchema": _schema({"name": {"type": "string"}, "description": {"type": "string"},
                             "version": {"type": "string"}}, ["name"]),
     "handler": tool_create_profile},
    {"name": "sysml_update_profile",
     "description": "Rename a profile or change its description, version or model-root stereotype "
                    "(applied to root architectures; '' clears it).",
     "inputSchema": _schema({"profile": {"type": "string"}, "name": {"type": "string"},
                             "description": {"type": "string"}, "version": {"type": "string"},
                             "root_stereotype": {"type": "string"}}, ["profile"]),
     "handler": tool_update_profile},
    {"name": "sysml_delete_profile",
     "description": "Delete a profile; every application and value of its stereotypes is removed.",
     "inputSchema": _schema({"profile": {"type": "string"}}, ["profile"]),
     "handler": tool_delete_profile},
    {"name": "sysml_add_stereotype",
     "description": "Add a stereotype to a profile. applies_to: '' (all elements) or one category: "
                    + _CATEGORY_TEXT + ".",
     "inputSchema": _schema({"profile": {"type": "string"}, "name": {"type": "string"},
                             "description": {"type": "string"}, "applies_to": {"type": "string"},
                             "base": {"type": "string", "description": "base stereotype (Profile.Stereotype)"},
                             "abstract": {"type": "boolean"}, "style": _STYLE_SCHEMA,
                             "defaults": _DEFAULTS_SCHEMA}, ["profile", "name"]),
     "handler": tool_add_stereotype},
    {"name": "sysml_update_stereotype",
     "description": "Edit a stereotype (name, description, applies_to (" + _CATEGORY_TEXT + "), "
                    "base ('' clears), abstract, style, defaults). force=true strips applications "
                    "the change would invalidate.",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "name": {"type": "string"},
                             "description": {"type": "string"}, "applies_to": {"type": "string"},
                             "base": {"type": "string"}, "abstract": {"type": "boolean"},
                             "style": _STYLE_SCHEMA, "defaults": _DEFAULTS_SCHEMA,
                             "force": {"type": "boolean"}}, ["stereotype"]),
     "handler": tool_update_stereotype},
    {"name": "sysml_delete_stereotype",
     "description": "Delete a stereotype definition; its applications are removed from all elements.",
     "inputSchema": _schema({"stereotype": {"type": "string"}}, ["stereotype"]),
     "handler": tool_delete_stereotype},
    {"name": "sysml_add_stereotype_property",
     "description": "Add a typed property to a stereotype. type: double, single, int8..int64, "
                    "uint8..uint64, boolean, string or enumeration (with literals). Numeric "
                    "properties may have a unit (kg, W, ms, kbit/s, ft, kt, FIT, ...) and min/max.",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "name": {"type": "string"},
                             "type": {"type": "string"}, "unit": {"type": "string"},
                             "default": _ANY, "min": _ANY, "max": _ANY,
                             "literals": {"type": "array", "items": {"type": "string"}},
                             "description": {"type": "string"}, "index": {"type": "integer"}},
                            ["stereotype", "name"]),
     "handler": tool_add_stereotype_property},
    {"name": "sysml_update_stereotype_property",
     "description": "Edit a stereotype property definition; renames keep stored values, unit "
                    "changes convert them, values that no longer fit are reset (reported). "
                    "clear: list of 'default'|'min'|'max'|'unit' to clear.",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "property": {"type": "string"},
                             "name": {"type": "string"}, "type": {"type": "string"},
                             "unit": {"type": "string"}, "default": _ANY, "min": _ANY, "max": _ANY,
                             "literals": {"type": "array", "items": {"type": "string"}},
                             "description": {"type": "string"}, "index": {"type": "integer"},
                             "clear": {"type": "array", "items": {"type": "string"}}},
                            ["stereotype", "property"]),
     "handler": tool_update_stereotype_property},
    {"name": "sysml_delete_stereotype_property",
     "description": "Delete a stereotype property; its values are removed from all elements.",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "property": {"type": "string"}},
                            ["stereotype", "property"]),
     "handler": tool_delete_stereotype_property},
    {"name": "sysml_apply_stereotype",
     "description": "Apply a stereotype to an element (on a reference component whose definition "
                    "already carries it, an override of the given values). stereotype: id, 'Profile.Stereotype', "
                    "'Pkg::Stereotype' or a unique name. Optional initial values keyed by "
                    "property name or 'Profile.Stereotype.prop' are checked (type, range, "
                    "literals) and converted from compatible units ('3 lb' into kg). Abstract, "
                    "non-applicable (applies-to) and duplicate applications are refused.",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "target": {"type": "string"},
                             "values": {"type": "object"}}, ["stereotype", "target"]),
     "handler": tool_apply_stereotype},
    {"name": "sysml_remove_stereotype",
     "description": "Remove an applied stereotype from an element (all of them if 'stereotype' is "
                    "omitted). Stereotypes inherited from a definition cannot be removed here: remove "
                    "them from the definition.",
     "inputSchema": _schema({"target": {"type": "string"}, "stereotype": {"type": "string"}}, ["target"]),
     "handler": tool_remove_stereotype},
    {"name": "sysml_set_stereotype_property",
     "description": "Set stereotype property values on an element: property='Profile.Stereotype.prop' "
                    "with value, or values={path: value}. Values are checked (type, range, literals) "
                    "and converted from compatible units; all-or-nothing. On a reference component "
                    "(typed by a definition that carries the stereotype) this overrides the "
                    "definition's value for that component only.",
     "inputSchema": _schema({"target": {"type": "string"}, "property": {"type": "string"},
                             "value": _ANY, "values": {"type": "object"}}, ["target"]),
     "handler": tool_set_stereotype_property},
    {"name": "sysml_reset_stereotype_property",
     "description": "Take back values set on a reference component so it inherits its definition's "
                    "again (property, or properties=[...]); an override that no longer sets anything "
                    "is dropped. Without a definition value the property default applies.",
     "inputSchema": _schema({"target": {"type": "string"}, "property": {"type": "string"},
                             "properties": {"type": "array", "items": {"type": "string"}}}, ["target"]),
     "handler": tool_reset_stereotype_property},
    {"name": "sysml_get_stereotype_properties",
     "description": "Stereotypes applied to an element with their property values (grouped by "
                    "owning stereotype) and the stereotypes that could still be applied; or one "
                    "value when 'property' is given. A reference component also lists the "
                    "stereotypes and values it inherits from its definition (inherited / origin / "
                    "overridden mark them).",
     "inputSchema": _schema({"target": {"type": "string"}, "property": {"type": "string"}}, ["target"]),
     "handler": tool_get_stereotype_properties},
    {"name": "sysml_batch_apply_stereotype",
     "description": "Apply a stereotype to every matching element of a scope: 'selection' (ids), "
                    "'composition' (everything the root owns: its components, ports and connectors; "
                    "not the root itself and not the internals of referenced definitions: select those "
                    "explicitly) or 'model'; category narrows the candidates; optional initial values. "
                    "Elements that already carry the stereotype, or inherit it from their definition, "
                    "are skipped. dry_run=true changes nothing and reports how many elements would "
                    "get it (count, preview, skipped_by_reason).",
     "inputSchema": _schema({"stereotype": {"type": "string"}, "scope": {"type": "string"},
                             "ids": {"type": "array", "items": {"type": "string"}},
                             "root": {"type": "string"}, "category": {"type": "string"},
                             "values": {"type": "object"}, "dry_run": {"type": "boolean"}},
                            ["stereotype"]),
     "handler": tool_batch_apply_stereotype},
    {"name": "sysml_export_profile",
     "description": "Export a profile as a standalone JSON profile file (returned as text, or "
                    "written to 'path').",
     "inputSchema": _schema({"profile": {"type": "string"}, "path": {"type": "string"}}, ["profile"]),
     "handler": tool_export_profile},
    {"name": "sysml_import_profile",
     "description": "Import a profile file (JSON text or a path). An existing profile with the same "
                    "name is only updated when replace=true.",
     "inputSchema": _schema({"text": {"type": "string"}, "path": {"type": "string"},
                             "replace": {"type": "boolean"}}, []),
     "handler": tool_import_profile},
    {"name": "sysml_list_units",
     "description": "Units understood by stereotype properties (optionally for one quantity, e.g. 'mass').",
     "inputSchema": _schema({"quantity": {"type": "string"}}, []),
     "handler": tool_list_units},
    {"name": "sysml_convert_units",
     "description": "Convert a quantity, e.g. value='3 lb', to='kg'.",
     "inputSchema": _schema({"value": _ANY, "to": {"type": "string"}, "unit": {"type": "string"}},
                            ["value", "to"]),
     "handler": tool_convert_units},
]
