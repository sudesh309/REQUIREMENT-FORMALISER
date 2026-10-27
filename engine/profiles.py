"""Profiles, stereotypes and typed stereotype properties (System Composer Profile Editor).

The metamodel (:class:`Profile`, :class:`Stereotype`, :class:`StereotypeTag`,
:class:`StereotypeApplication`) lives in :mod:`kerml.stereotypes`; this module
holds every repository-level operation shared by the web API
(``webapp/routes/profiles.py``), the MCP tools (``mcp_server/tools/profiles.py``)
and Python users:

- profile / stereotype / property CRUD with change propagation (renames keep
  values, deleting a property drops its values, deleting a stereotype or a
  profile strips its applications, type and unit changes convert stored values);
- applying stereotypes (single, batch over a scope) and setting values by the
  ``Profile.Stereotype.property`` address, with unit conversion and checks;
- default stereotypes for ports / connectors / sub-components created inside
  a stereotyped component and a profile's model-root stereotype (applied by an
  ``engine.register_created_hook`` hook);
- standalone profile files (JSON) for export / import, with an import log;
- persistence of the extra attributes (serializer codecs), validator rules and
  the element display fields (badges, style).

Every editing function checks its input and raises :class:`ProfileError`
(``.status`` is the HTTP status: 400 invalid, 404 not found, 409 conflict)
before changing the model; created elements go through
``engine.notify_created`` and deletions through ``Repository.remove``.
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Iterable, Iterator, Optional

from kerml.elements import Element, Relationship
from kerml.namespaces import Package
from kerml.stereotypes import (
    CATEGORIES, DASH_PATTERNS, DEFAULT_SLOTS, ICONS, INT_RANGES, LINE_STYLES,
    NUMERIC_TYPES, PROPERTY_TYPES, InheritedApplication, Profile, Stereotype,
    StereotypeApplication, StereotypeError, StereotypeTag, UnknownPropertyError,
    application_of, build_property, categories_of, check_name, effective_application_of,
    effective_applications, format_short, format_value, inheritance_source, kind_names,
    matches_category, normalize_literals, normalize_style, stereotypes_on,
)

from . import units
from .hooks import notify_created, register_created_hook
from .repository import register_removal_hook
from .serializer import register_codec, register_repo_codec
from .validator import Severity, ValidationIssue, register_repo_rule

__all__ = [
    "ProfileError", "Profile", "Stereotype", "StereotypeTag", "StereotypeApplication",
    "PROPERTY_TYPES", "CATEGORIES", "ICONS", "LINE_STYLES", "PROFILE_FORMAT",
    "profiles_of", "stereotypes_of", "find_profile", "find_stereotype", "find_property",
    "create_profile", "update_profile", "delete_profile",
    "add_stereotype", "update_stereotype", "delete_stereotype",
    "add_property", "update_property", "delete_property", "move_property",
    "apply_stereotype", "remove_stereotype", "remove_all_stereotypes",
    "own_application", "set_property_value", "set_property_values", "reset_property_value", "reset_property_values",
    "get_property_value", "resolve_value_path", "effective_applications", "inheritance_source",
    "element_stereotypes", "applicable_stereotypes", "batch_apply",
    "export_profile", "export_profile_json", "import_profile",
    "display_fields", "validate_profiles", "describe_profile", "meta",
]

PROFILE_FORMAT = "sysmlv2-profile/1"


class ProfileError(StereotypeError):
    """Invalid profile edit; ``status`` is the matching HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _not_found(what: str) -> ProfileError:
    return ProfileError(f"{what} not found", 404)


def _conflict(message: str) -> ProfileError:
    return ProfileError(message, 409)


def _wrap(fn, *args, **kwargs):
    """Re-raise StereotypeError from the metamodel as a ProfileError (keeps .status)."""
    try:
        return fn(*args, **kwargs)
    except ProfileError:
        raise
    except StereotypeError as ex:
        raise ProfileError(str(ex), getattr(ex, "status", 400)) from None


_UNSET: Any = object()


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _in_profile_space(e: Element) -> bool:
    node: Optional[Element] = e
    while node is not None:
        if isinstance(node, (Profile, Stereotype)):
            return True
        node = node.owner
    return False


def model_elements(repo) -> Iterator[Element]:
    """Elements of the project that stereotypes can be applied to."""
    for e in repo.root_package.walk():
        if e is repo.root_package or isinstance(e, Relationship) or _in_profile_space(e):
            continue
        yield e


def profiles_of(repo) -> list[Profile]:
    return [e for e in repo.root_package.walk() if isinstance(e, Profile)]


def stereotypes_of(repo) -> list[Stereotype]:
    return [e for e in repo.root_package.walk() if isinstance(e, Stereotype)]


def _lookup(repo, ref: Any) -> Optional[Element]:
    if isinstance(ref, Element):
        return ref
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip()
    return repo.by_id(ref) or repo.resolve(ref)


def find_element(repo, ref: Any) -> Element:
    e = _lookup(repo, ref)
    if e is None:
        raise _not_found(f"element {ref!r}")
    return e


def find_profile(repo, ref: Any) -> Profile:
    e = _lookup(repo, ref)
    if isinstance(e, Profile):
        return e
    hit = [p for p in profiles_of(repo) if p.name == ref]
    if len(hit) == 1:
        return hit[0]
    raise _not_found(f"profile {ref!r}")


def find_stereotype(repo, ref: Any) -> Stereotype:
    """By id, ``Pkg::Name`` qualified name, ``Profile.Stereotype`` or a unique bare name."""
    e = _lookup(repo, ref)
    if isinstance(e, Stereotype):
        return e
    if isinstance(ref, str):
        ref = ref.strip()
        all_st = stereotypes_of(repo)
        hit = [s for s in all_st if s.full_name == ref]
        if not hit:
            hit = [s for s in all_st if s.name == ref]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:
            raise ProfileError(f"stereotype name {ref!r} is ambiguous; use one of "
                               f"{sorted(s.full_name for s in hit)}")
    raise _not_found(f"stereotype {ref!r}")


def find_property(repo, ref: Any, stereotype: Optional[Stereotype] = None) -> StereotypeTag:
    """By id, by name within ``stereotype``, or by ``Profile.Stereotype.property``."""
    e = _lookup(repo, ref)
    if isinstance(e, StereotypeTag):
        return e
    if isinstance(ref, str):
        if stereotype is not None and "." not in ref:
            tag = stereotype.find_tag(ref)
            if tag is not None:
                return tag
        elif "." in ref:
            st_ref, _, name = ref.rpartition(".")
            tag = find_stereotype(repo, st_ref).find_tag(name)
            if tag is not None:
                return tag
    raise _not_found(f"property {ref!r}")


def descendants_of(repo, st: Stereotype) -> list[Stereotype]:
    """Stereotypes that inherit (directly or indirectly) from ``st`` (excluding it)."""
    return [s for s in stereotypes_of(repo) if s is not st and s.is_kind_of(st)]


def applications_of(repo, st: Stereotype, *, include_derived: bool = False
                    ) -> list[tuple[Element, StereotypeApplication]]:
    out = []
    for e in model_elements(repo):
        for a in stereotypes_on(e):
            if a.stereotype is st or (include_derived and a.stereotype.is_kind_of(st)):
                out.append((e, a))
    return out


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def _require_package(repo, parent: Any) -> Package:
    pkg = find_element(repo, parent) if parent not in (None, "") else repo.root_package
    if not isinstance(pkg, Package) or isinstance(pkg, Profile):
        raise ProfileError(f"{pkg.qualified_name} is not a package that can hold profiles")
    return pkg


def _check_profile_name(repo, name: Any, owner: Package, exclude: Optional[Element] = None) -> str:
    name = _wrap(check_name, name, "profile name")
    for p in profiles_of(repo):
        if p is not exclude and p.name == name:
            raise _conflict(f"a profile named {name!r} already exists")
    for m in owner.owned_elements:
        if m is not exclude and m.name == name:
            raise _conflict(f"{owner.qualified_name} already contains an element named {name!r}")
    return name


def create_profile(repo, name: str, *, description: str = "", version: str = "1.0",
                   parent: Any = None) -> Profile:
    pkg = _require_package(repo, parent)
    name = _check_profile_name(repo, name, pkg)
    p = Profile(name=name, description=str(description or ""), version=str(version or ""))
    pkg.own(p)
    notify_created(p, repo)
    return p


def _check_root_stereotype(st: Optional[Stereotype]) -> Optional[Stereotype]:
    if st is None:
        return None
    if st.is_abstract:
        raise ProfileError(f"«{st.full_name}» is abstract and cannot be the model root stereotype")
    if st.effective_category() not in ("", "Component", "Architecture"):
        raise ProfileError(f"«{st.full_name}» applies to {st.effective_category()} elements, "
                           f"not to the root architecture")
    return st


def root_architectures(repo) -> list[Element]:
    return [e for e in model_elements(repo) if matches_category(e, "Architecture")]


def apply_root_stereotype(repo, profile: Profile) -> list[Element]:
    """Apply the profile's model-root stereotype to root architectures that lack it."""
    st = profile.root_stereotype
    done: list[Element] = []
    if st is None or st.is_abstract:
        return done
    for arch in root_architectures(repo):
        if st.can_apply_to(arch) and application_of(arch, st) is None:
            st.apply(arch)
            done.append(arch)
    return done


def update_profile(repo, profile: Profile, *, name: Any = _UNSET, description: Any = _UNSET,
                   version: Any = _UNSET, root_stereotype: Any = _UNSET) -> dict:
    """Edit profile metadata; returns ``{"profile", "root_applied": [qualified names]}``."""
    owner = profile.owner if isinstance(profile.owner, Package) else repo.root_package
    new_name = profile.name if name is _UNSET else _check_profile_name(repo, name, owner, exclude=profile)
    new_root = profile.root_stereotype
    if root_stereotype is not _UNSET:
        new_root = None if root_stereotype in (None, "") else find_stereotype(repo, root_stereotype)
        if new_root is not None and new_root.profile is not profile:
            raise ProfileError(f"the model root stereotype must belong to profile {profile.name!r}")
        _check_root_stereotype(new_root)
    profile.name = new_name
    if description is not _UNSET:
        profile.description = str(description or "")
    if version is not _UNSET:
        profile.version = str(version or "")
    applied: list[Element] = []
    if root_stereotype is not _UNSET and new_root is not profile.root_stereotype:
        profile.root_stereotype = new_root
        applied = apply_root_stereotype(repo, profile)
    return {"profile": profile, "root_applied": [e.qualified_name for e in applied]}


def delete_profile(repo, profile: Profile) -> dict:
    """Remove a profile; every application (and value) of its stereotypes is stripped."""
    sts = profile.stereotypes
    removed = sum(len(applications_of(repo, s)) for s in sts)
    orphaned = sorted({d.full_name for s in sts for d in descendants_of(repo, s)
                       if d.profile is not profile and d.base is not None and d.base.profile is profile})
    repo.remove(profile)
    return {"deleted": profile.name, "applications_removed": removed, "rebased": orphaned}


# ---------------------------------------------------------------------------
# Stereotypes
# ---------------------------------------------------------------------------

def _check_stereotype_name(profile: Element, name: Any, exclude: Optional[Element] = None) -> str:
    name = _wrap(check_name, name, "stereotype name")
    for m in profile.owned_elements:
        if m is not exclude and m.name == name:
            raise _conflict(f"profile {profile.name!r} already has a stereotype named {name!r}")
    return name


def _check_category(category: Any) -> str:
    category = category or ""
    if category not in CATEGORIES:
        raise ProfileError(f"applies-to {category!r} is not one of {[c for c in CATEGORIES if c]} (or '' for all)")
    return category


def _resolve_optional_stereotype(repo, ref: Any) -> Optional[Stereotype]:
    if ref in (None, ""):
        return None
    return find_stereotype(repo, ref)


_SLOT_CATEGORY = {"component": "Component", "port": "Port", "connector": "Connector"}


def _check_defaults(st_category: str, defaults: dict, repo) -> dict:
    out: dict[str, Optional[Stereotype]] = {}
    for slot, ref in (defaults or {}).items():
        if slot not in DEFAULT_SLOTS:
            raise ProfileError(f"unknown default slot {slot!r}; use {list(DEFAULT_SLOTS)}")
        d = _resolve_optional_stereotype(repo, ref)
        if d is not None:
            if st_category not in ("", "Component", "Architecture"):
                raise ProfileError("only component stereotypes can name default stereotypes "
                                   f"(this one applies to {st_category} elements)")
            if d.is_abstract:
                raise ProfileError(f"default {slot} stereotype «{d.full_name}» is abstract")
            cat = d.effective_category()
            if cat not in ("", _SLOT_CATEGORY[slot]):
                raise ProfileError(f"default {slot} stereotype «{d.full_name}» applies to "
                                   f"{cat} elements, not {_SLOT_CATEGORY[slot]}s")
        out[slot] = d
    return out


def _check_base(repo, st: Optional[Stereotype], base: Optional[Stereotype], own_category: str,
                own_names: Iterable[str]) -> None:
    if base is None:
        return
    if st is not None and base.is_kind_of(st):
        raise ProfileError(f"«{base.full_name}» cannot be the base of «{st.full_name}»: "
                           f"that would create an inheritance cycle")
    base_cat = base.effective_category()
    if own_category and base_cat and own_category != base_cat:
        raise ProfileError(f"base «{base.full_name}» applies to {base_cat} elements, "
                           f"so a stereotype derived from it cannot apply to {own_category}")
    inherited = {t.name for t in base.all_tags()}
    clash = sorted(set(own_names) & inherited)
    if clash:
        raise _conflict(f"properties {clash} are already defined by base «{base.full_name}»")


def add_stereotype(repo, profile: Profile, name: str, *, description: str = "",
                   applies_to: str = "", base: Any = None, abstract: bool = False,
                   style: Optional[dict] = None, defaults: Optional[dict] = None) -> Stereotype:
    if not isinstance(profile, Profile):
        raise ProfileError("stereotypes are added to a profile")
    name = _check_stereotype_name(profile, name)
    category = _check_category(applies_to)
    base_st = _resolve_optional_stereotype(repo, base)
    _check_base(repo, None, base_st, category, [])
    style_n = _wrap(normalize_style, style)
    eff_cat = category or (base_st.effective_category() if base_st else "")
    dflt = _check_defaults(eff_cat, defaults or {}, repo)
    st = Stereotype(name=name, category=category, description=str(description or ""), style=style_n)
    st.base = base_st
    st.is_abstract = bool(abstract)
    for slot, d in dflt.items():
        setattr(st, f"default_{slot}_stereotype", d)
    profile.own(st)
    notify_created(st, repo)
    return st


def _apps_breaking_category(repo, st: Stereotype, new_effective: dict) -> list[tuple[Element, StereotypeApplication]]:
    """Applications (of ``st`` or its descendants) that a category change would invalidate."""
    bad = []
    for e in model_elements(repo):
        for a in stereotypes_on(e):
            cat = new_effective.get(id(a.stereotype))
            if cat is not None and not matches_category(e, cat):
                bad.append((e, a))
    return bad


def _strip(e: Element, a: StereotypeApplication) -> None:
    e.annotations = [x for x in e.annotations if x is not a]


def update_stereotype(repo, st: Stereotype, *, name: Any = _UNSET, description: Any = _UNSET,
                      applies_to: Any = _UNSET, base: Any = _UNSET, abstract: Any = _UNSET,
                      style: Any = _UNSET, defaults: Any = _UNSET, force: bool = False) -> dict:
    """Edit a stereotype. Returns ``{"stereotype", "stripped": [...]}``.

    Changes that would invalidate existing applications (an applies-to change
    that excludes stereotyped elements, making an applied stereotype abstract)
    are refused with 409, unless ``force`` strips those applications.
    """
    owner = st.owner if st.owner is not None else repo.root_package
    new_name = st.name if name is _UNSET else _check_stereotype_name(owner, name, exclude=st)
    category = st.category if applies_to is _UNSET else _check_category(applies_to)
    new_base = st.base if base is _UNSET else _resolve_optional_stereotype(repo, base)
    desc = descendants_of(repo, st)
    if base is not _UNSET and new_base is not st.base:
        own_names = {t.name for t in st.tags} | {t.name for d in desc for t in d.tags}
        _check_base(repo, st, new_base, category, own_names)
    elif applies_to is not _UNSET and new_base is not None:
        _check_base(repo, st, new_base, category, [])
    # Effective categories after the change, for st and its descendants.
    def eff_after(x: Optional[Stereotype]) -> str:
        seen: set[int] = set()
        while x is not None and id(x) not in seen:
            seen.add(id(x))
            cat = category if x is st else x.category
            if cat:
                return cat
            x = new_base if x is st else x.base
        return ""

    eff_self = eff_after(st)
    for d in desc:
        parent = eff_after(d.base)
        if d.category and parent and d.category != parent:
            raise ProfileError(f"derived stereotype «{d.full_name}» applies to {d.category} "
                               f"elements; it cannot inherit from a {parent} stereotype")
    new_effective = {id(x): eff_after(x) for x in [st, *desc]}
    stripped: list[str] = []
    breaking = _apps_breaking_category(repo, st, new_effective)
    if breaking and not force:
        names = ", ".join(e.qualified_name for e, _ in breaking[:3])
        raise _conflict(f"«{st.full_name}» is applied to {len(breaking)} element(s) that are not "
                        f"{eff_self or 'allowed'} elements ({names}); remove those applications first")
    want_abstract = st.is_abstract if abstract is _UNSET else bool(abstract)
    live = st.live_applications() if want_abstract and not st.is_abstract else []
    if live and not force:
        names = ", ".join(a.annotated_element.qualified_name for a in live[:3])
        raise _conflict(f"«{st.full_name}» is applied to {len(live)} element(s) ({names}); "
                        f"remove those applications before making it abstract")
    style_n = st.style if style is _UNSET else _wrap(normalize_style, style)
    dflt: dict = {}
    if defaults is not _UNSET:
        dflt = _check_defaults(eff_self, defaults or {}, repo)
    elif eff_self not in ("", "Component", "Architecture"):
        dflt = {slot: None for slot in DEFAULT_SLOTS}   # defaults only make sense on components
    # --- apply ---------------------------------------------------------------
    for e, a in breaking:
        _strip(e, a)
        stripped.append(f"{e.qualified_name} «{a.stereotype.full_name}»")
    for a in live:
        _strip(a.annotated_element, a)
        stripped.append(f"{a.annotated_element.qualified_name} «{st.full_name}»")
    st.name = new_name
    if description is not _UNSET:
        st.description = str(description or "")
    st.category = category
    st.base = new_base
    st.is_abstract = want_abstract
    st.style = style_n
    for slot, d in dflt.items():
        setattr(st, f"default_{slot}_stereotype", d)
    return {"stereotype": st, "stripped": stripped}


def delete_stereotype(repo, st: Stereotype) -> dict:
    removed = len(applications_of(repo, st))
    rebased = sorted(d.full_name for d in descendants_of(repo, st) if d.base is st)
    repo.remove(st)
    return {"deleted": st.full_name, "applications_removed": removed, "rebased": rebased}


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def _check_property_name_free(repo, st: Stereotype, name: str, exclude: Optional[StereotypeTag] = None) -> None:
    for t in st.all_tags():
        if t is not exclude and t.name == name:
            where = "" if t.stereotype is st else f" (inherited from «{t.stereotype.full_name}»)"
            raise _conflict(f"«{st.full_name}» already has a property named {name!r}{where}")
    for d in descendants_of(repo, st):
        for t in d.tags:
            if t is not exclude and t.name == name:
                raise _conflict(f"derived stereotype «{d.full_name}» already has a property named {name!r}")


def unique_property_name(st: Stereotype, base: str = "Property") -> str:
    taken = {t.name for t in st.all_tags()}
    if base not in taken:
        return base
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"


def add_property(repo, st: Stereotype, name: Optional[str] = None, prop_type: str = "double", *,
                 unit: str = "", default: Any = None, minimum: Any = None, maximum: Any = None,
                 literals: Any = None, description: str = "", index: Optional[int] = None,
                 _check_names: bool = True) -> StereotypeTag:
    name = name or unique_property_name(st)
    name = _wrap(check_name, name, "property name")
    if _check_names:
        _check_property_name_free(repo, st, name)
    tag = _wrap(build_property, name, prop_type or "double", unit=unit or "", default=default,
                minimum=minimum, maximum=maximum, literals=literals,
                description=description or "", label=f"{st.full_name}.{name}")
    st.own(tag)
    if index is None or not 0 <= int(index) <= len(st.tags):
        st.tags.append(tag)
    else:
        st.tags.insert(int(index), tag)
        move_property(repo, tag, int(index))
    notify_created(tag, repo)
    return tag


def _convert_value(v: Any, old: StereotypeTag, new: StereotypeTag, old_lits: list[str]) -> Any:
    """Carry a stored value over a definition change; raises StereotypeError if impossible."""
    if v is None:
        return new.coerce(None)
    if new.prop_type in NUMERIC_TYPES and isinstance(v, (int, float)) and not isinstance(v, bool):
        if old.unit and new.unit and old.unit != new.unit and units.compatible(old.unit, new.unit):
            v = units.convert(v, old.unit, new.unit)
        return new.coerce(v)
    if new.prop_type == "enumeration" and isinstance(v, str) and v not in new.literals \
            and v in old_lits and len(old_lits) == len(new.literals):
        v = new.literals[old_lits.index(v)]       # literal renamed in place
    return new.coerce(v)


def update_property(repo, tag: StereotypeTag, *, name: Any = _UNSET, prop_type: Any = _UNSET,
                    unit: Any = _UNSET, default: Any = _UNSET, minimum: Any = _UNSET,
                    maximum: Any = _UNSET, literals: Any = _UNSET, description: Any = _UNSET,
                    index: Any = _UNSET, _check_names: bool = True) -> dict:
    """Edit a property definition and propagate to stored values.

    Renames keep values; a unit change converts values (and the default, min
    and max) when the units are compatible; a type change coerces values.
    Values that no longer fit are reset to the new default and listed in the
    returned ``{"property", "converted", "reset": [...]}``.
    """
    st = tag.stereotype
    if st is None:
        raise ProfileError(f"{tag.qualified_name} is not owned by a stereotype")
    new_name = tag.name
    if name is not _UNSET:
        new_name = _wrap(check_name, name, "property name")
        if new_name != tag.name and _check_names:
            _check_property_name_free(repo, st, new_name, exclude=tag)
    # A legacy untyped property (type '') stays untyped until a type is chosen.
    new_type = tag.prop_type if prop_type is _UNSET else prop_type
    if prop_type is not _UNSET and not prop_type:
        raise ProfileError(f"{tag.path}: a property type is required")
    if new_type and new_type not in PROPERTY_TYPES:
        raise ProfileError(f"type {new_type!r} is not one of {list(PROPERTY_TYPES)}")
    numeric = new_type in NUMERIC_TYPES
    new_unit = tag.unit if unit is _UNSET else (unit or "")
    if not numeric:
        if unit is not _UNSET and new_unit:
            raise ProfileError(f"{tag.path}: only numeric properties have units")
        new_unit = ""
    unit_converts = bool(numeric and tag.unit and new_unit and tag.unit != new_unit
                         and units.compatible(tag.unit, new_unit))
    old_lits = list(tag.literals)
    new_lits = old_lits if literals is _UNSET else _wrap(normalize_literals, literals)

    def carried(v: Any) -> Any:
        if v is None or not numeric or not isinstance(v, (int, float)) or isinstance(v, bool):
            return v if numeric else None
        return units.convert(v, tag.unit, new_unit) if unit_converts else v

    new_min = carried(tag.minimum) if minimum is _UNSET else minimum
    new_max = carried(tag.maximum) if maximum is _UNSET else maximum
    label = f"{st.full_name}.{new_name}"
    if not new_type:
        cand = StereotypeTag(name=new_name, description=tag.description)
        cand.default_value = tag.default_value if default is _UNSET else default
    else:
        if default is _UNSET:
            try:
                probe = _wrap(build_property, new_name, new_type, unit=new_unit, minimum=new_min,
                              maximum=new_max, literals=new_lits, label=label)
                dflt = _convert_value(tag.default_value, tag, probe, old_lits)
            except (StereotypeError, units.UnitError):
                dflt = None
        else:
            dflt = default
        cand = _wrap(build_property, new_name, new_type, unit=new_unit, default=dflt,
                     minimum=new_min, maximum=new_max, literals=new_lits,
                     description=tag.description, label=label)
    if description is not _UNSET:
        cand.description = str(description or "")
    if index is not _UNSET and index is not None:
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise ProfileError(f"index must be a whole number, not {index!r}") from None
    # Carry stored values of every application that includes this property.
    plan: list[tuple[StereotypeApplication, Any]] = []
    reset: list[str] = []
    converted = 0
    for e in model_elements(repo):
        for a in stereotypes_on(e):
            if not a.stereotype.is_kind_of(st):
                continue
            slots = a.raw_slots()
            if tag not in slots:
                continue
            old_v = slots[tag]
            try:
                new_v = _convert_value(old_v, tag, cand, old_lits) if cand.prop_type else old_v
            except (StereotypeError, units.UnitError):
                new_v = cand.default_value
                reset.append(f"{e.qualified_name}: {format_value(old_v, tag.unit)!r} -> "
                             f"{format_value(new_v, cand.unit)!r}")
            if new_v != old_v:
                converted += 1
            plan.append((a, new_v))
    # --- apply ---------------------------------------------------------------
    tag.name = cand.name
    tag.prop_type = cand.prop_type
    tag.unit = cand.unit
    tag.minimum, tag.maximum = cand.minimum, cand.maximum
    tag.literals = list(cand.literals)
    tag.description = cand.description
    tag.default_value = cand.default_value
    for a, v in plan:
        a.raw_slots()[tag] = v
    if index is not _UNSET and index is not None:
        move_property(repo, tag, index)
    return {"property": tag, "converted": converted, "reset": reset}


def delete_property(repo, tag: StereotypeTag) -> dict:
    st = tag.stereotype
    affected = 0
    if st is not None:
        for _e, a in applications_of(repo, st, include_derived=True):
            if tag in a.raw_slots():
                affected += 1
            a.forget(tag)
    path = tag.path
    repo.remove(tag)
    return {"deleted": path, "values_removed": affected}


def move_property(repo, tag: StereotypeTag, index: int) -> StereotypeTag:
    st = tag.stereotype
    if st is None:
        raise ProfileError(f"{tag.qualified_name} is not owned by a stereotype")
    index = max(0, min(int(index), len(st.tags) - 1))
    st.tags.remove(tag)
    st.tags.insert(index, tag)
    # Keep the containment order in step so the tree and saved files agree.
    in_tags = {id(t) for t in st.tags}
    others = [c for c in st.owned_elements if id(c) not in in_tags]
    st.owned_elements = others + [t for t in st.tags if t.owner is st]
    return tag


# ---------------------------------------------------------------------------
# Applications and values
# ---------------------------------------------------------------------------

def _check_target(e: Element) -> None:
    if _in_profile_space(e) or isinstance(e, Relationship):
        raise ProfileError(f"stereotypes cannot be applied to profile definitions ({e.qualified_name})")


def apply_stereotype(repo, element: Element, stereotype: Stereotype,
                     values: Optional[dict] = None) -> StereotypeApplication:
    """Apply ``stereotype`` to ``element`` (409 when it already carries its own application).

    On a reference component whose definition already carries the stereotype this is an
    *override*, not a duplicate: the new application inherits every value the definition
    has and overrides only the ``values`` given.
    """
    _check_target(element)
    if application_of(element, stereotype) is not None:
        raise _conflict(f"«{stereotype.full_name}» is already applied to {element.qualified_name!r}")
    return _wrap(stereotype.apply, element, _local_values(stereotype, values or {}))


def _local_values(st: Stereotype, values: dict) -> dict:
    """Accept ``{'mass': v}`` or ``{'Profile.Stereotype.mass': v}`` keys."""
    out = {}
    for k, v in values.items():
        key = str(k)
        if "." in key:
            prefix, _, prop = key.rpartition(".")
            if not any(prefix in (s.full_name, s.name) for s in st.ancestors()):
                raise ProfileError(f"{key!r} does not address «{st.full_name}»")
            key = prop
        out[key] = v
    return out


def remove_stereotype(repo, element: Element, stereotype: Stereotype) -> bool:
    """Remove the element's own application (an override, on a reference component)."""
    a = application_of(element, stereotype)
    if a is None:
        inherited = effective_application_of(element, stereotype)
        if inherited is not None:
            raise _conflict(f"«{stereotype.full_name}» is inherited from "
                            f"{inherited.definition.qualified_name!r}: remove it there")
        raise _not_found(f"«{stereotype.full_name}» on {element.qualified_name!r}")
    _strip(element, a)
    return True


def remove_all_stereotypes(repo, element: Element) -> int:
    """Remove the element's own applications; inherited ones stay with the definition."""
    apps = stereotypes_on(element)
    element.annotations = [x for x in element.annotations if not isinstance(x, StereotypeApplication)]
    return len(apps)


def resolve_value_path(element: Element, path: str) -> tuple[StereotypeApplication, StereotypeTag]:
    """``Profile.Stereotype.property`` (or ``Stereotype.property`` / ``property``) on an element.

    The stereotype part may also name a base of an applied stereotype. The application is the
    element's own or, for a stereotype a reference component inherits from its definition,
    an inherited one (``.inherited``; reading it works, ``set_property_value`` overrides it).
    """
    if not isinstance(path, str) or not path.strip():
        raise ProfileError("property path must be 'Profile.Stereotype.property'")
    path = path.strip()
    prefix, _, prop = path.rpartition(".")
    apps = effective_applications(element)
    if not apps:
        raise _not_found(f"stereotype property {path!r}: {element.qualified_name!r} has no stereotypes")
    if prefix:
        cands = [a for a in apps if any(prefix in (s.full_name, s.name) for s in a.stereotype.ancestors())]
        if not cands:
            raise _not_found(f"stereotype {prefix!r} on {element.qualified_name!r} "
                             f"(applied: {[a.stereotype.full_name for a in apps]})")
        cands = [a for a in cands
                 if any(prefix in (s.full_name, s.name) and s.find_tag(prop) is not None
                        for s in a.stereotype.ancestors())]
    else:
        cands = [a for a in apps if a.stereotype.find_tag(prop) is not None]
    if not cands:
        raise _not_found(f"stereotype property {path!r} on {element.qualified_name!r}")
    if len(cands) > 1:
        raise ProfileError(f"{path!r} is ambiguous on {element.qualified_name!r}; use one of "
                           f"{[a.stereotype.full_name + '.' + prop for a in cands]}")
    a = cands[0]
    return a, a.stereotype.find_tag(prop)  # type: ignore[return-value]


def own_application(repo, element: Element, a) -> StereotypeApplication:
    """The element's own application behind ``a``. A stereotype the element only inherits gets
    an application of its own (no values set: everything is still inherited) to hold overrides."""
    if not a.inherited:
        return a
    own = application_of(element, a.stereotype)
    return own if own is not None else _wrap(a.stereotype.apply, element, {})


def set_property_value(repo, element: Element, path: str, value: Any) -> Any:
    """Check, convert and store one value; returns the stored form.

    On a reference component this overrides the definition's value; ``reset_property_value``
    inherits it again.
    """
    a, tag = resolve_value_path(element, path)
    stored = _wrap(tag.coerce, value, f"{a.stereotype.full_name}.{tag.name}")
    own_application(repo, element, a).assign(tag, stored)
    return stored


def set_property_values(repo, element: Element, values: dict) -> dict:
    """All-or-nothing: every value is checked before any is stored."""
    plan = []
    for path, value in (values or {}).items():
        a, tag = resolve_value_path(element, path)
        plan.append((a, tag, path, _wrap(tag.coerce, value, f"{a.stereotype.full_name}.{tag.name}")))
    out = {}
    for a, tag, path, stored in plan:
        own_application(repo, element, a).assign(tag, stored)
        out[path] = stored
    return out


def reset_property_values(repo, element: Element, paths: Iterable[str]) -> dict:
    """Take back the values set on the element: they are inherited from the definition again
    (the property default when there is none). All or nothing.

    An override application that no longer sets anything is dropped. Returns
    ``{"reset": [paths that had a value set], "unchanged": [paths already inherited],
    "removed": [stereotypes whose empty override was dropped]}``.
    """
    plan = [(path, *resolve_value_path(element, path)) for path in paths or []]
    if not plan:
        raise ProfileError("name the properties to reset")
    out: dict = {"reset": [], "unchanged": [], "removed": []}
    touched: dict[int, StereotypeApplication] = {}
    for path, a, tag in plan:
        if not a.inherited and a.reset(tag.name):
            out["reset"].append(path)
            touched[id(a)] = a
        else:
            out["unchanged"].append(path)
    for a in touched.values():
        if a.parent() is not None and not a.explicit_tags():
            _strip(element, a)
            out["removed"].append(a.stereotype.full_name)
    return out


def reset_property_value(repo, element: Element, path: str) -> dict:
    return reset_property_values(repo, element, [path])


def get_property_value(element: Element, path: str) -> Any:
    """The value a property reads on ``element``: its own, else the definition's (reference
    component), else the property default."""
    a, tag = resolve_value_path(element, path)
    return a.get(tag.name)


def _value_entry(a, tag: StereotypeTag) -> dict:
    v = a.get(tag.name)
    d = tag.describe()
    origin = a.origin(tag.name)
    d.update({"path": f"{a.stereotype.full_name}.{tag.name}", "value": v,
              "display": format_value(v, tag.unit),
              # Rounded for compact displays (4.5359237 kg -> '4.54 kg'); `value` and
              # `display` keep the full precision.
              "short": format_short(v), "display_short": format_short(v, tag.unit),
              # 'own' (set here), 'inherited' (the definition's) or 'default'.
              "origin": origin, "inherited": origin == "inherited"})
    parent = a.parent()
    if parent is not None:
        inherited = parent.get(tag.name)
        d.update({"overridden": origin == "own", "inherited_value": inherited,
                  "inherited_display": format_value(inherited, tag.unit),
                  "inherited_short": format_short(inherited)})
    try:
        ok = tag.coerce(v) == v
    except StereotypeError as ex:
        ok, d["problem"] = False, str(ex)
    d["valid"] = ok
    return d


def _definition_ref(a) -> Optional[dict]:
    d = a.parent().annotated_element if a.parent() is not None else None
    return None if d is None else {"id": d.element_id, "name": d.name, "qualified_name": d.qualified_name}


def element_stereotypes(element: Element) -> list[dict]:
    """Applied stereotypes with their values grouped by declaring stereotype (base first).

    Includes the stereotypes a reference component inherits from its definition. Per
    stereotype: ``inherited`` (only through the definition), ``overridden`` (applied here
    and on the definition), ``inherited_from`` (the definition) and, per property value,
    ``origin`` / ``inherited`` / ``overridden`` / ``inherited_value`` (see ``_value_entry``).
    """
    out = []
    for a in effective_applications(element):
        st = a.stereotype
        from_def = _definition_ref(a)
        out.append({
            "id": st.element_id, "name": st.name, "qualified_name": st.full_name,
            "profile": st.profile.name if st.profile else None,
            "description": st.description, "abstract": st.is_abstract,
            "style": st.effective_style(),
            "inherited": bool(a.inherited), "overridden": bool(from_def and not a.inherited),
            "inherited_from": from_def,
            "groups": [{"stereotype": s.full_name, "id": s.element_id, "name": s.name,
                        "properties": [_value_entry(a, t) for t in props]}
                       for s, props in st.property_groups()],
            "values": a.values,
        })
    return out


def applicable_stereotypes(repo, element: Element) -> list[Stereotype]:
    """Stereotypes that can still be applied (not abstract, not already carried or inherited)."""
    if _in_profile_space(element) or isinstance(element, Relationship) or element is repo.root_package:
        return []
    have = {id(a.stereotype) for a in effective_applications(element)}
    return [s for s in stereotypes_of(repo)
            if not s.is_abstract and s.can_apply_to(element) and id(s) not in have]


def _composition_elements(root: Element) -> list[Element]:
    """``root`` and everything inside it, including reference components' definitions."""
    out: list[Element] = []
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        for e in node.walk():
            if id(e) in seen:
                continue
            seen.add(id(e))
            out.append(e)
            if "PartUsage" in kind_names(e):
                for t in getattr(e, "types", []) or []:
                    if "PartDefinition" in kind_names(t) and id(t) not in seen:
                        stack.append(t)
    return out


SCOPES = ("selection", "composition", "model")


def batch_apply(repo, stereotype: Stereotype, *, scope: str = "model", root: Any = None,
                elements: Optional[Iterable[Any]] = None, category: Optional[str] = None,
                values: Optional[dict] = None) -> dict:
    """Apply a stereotype to every matching element of a scope.

    ``scope``: 'selection' (``elements``), 'composition' (``root`` and everything
    inside it) or 'model'. ``category`` narrows the candidates (defaults to the
    stereotype's applies-to). Returns ``{"applied": [ids], "skipped": [...]}``.
    """
    st = stereotype
    if scope not in SCOPES:
        raise ProfileError(f"scope must be one of {list(SCOPES)}, not {scope!r}")
    if st.is_abstract:
        raise ProfileError(f"«{st.full_name}» is abstract and cannot be applied")
    category = _check_category(category) or st.effective_category()
    local = _local_values(st, values or {})
    for k, v in local.items():                       # check values before applying anything
        tag = st.find_tag(k)
        if tag is None:
            raise ProfileError(f"«{st.full_name}» has no property {k!r}")
        _wrap(tag.coerce, v, f"{st.full_name}.{k}")
    if scope == "selection":
        refs = list(elements or [])
        if not refs:
            raise ProfileError("nothing is selected")
        cands = [find_element(repo, r) for r in refs]
        report_mismatch = True
    else:
        if not category and not st.applies_to:
            raise ProfileError(f"«{st.full_name}» applies to all elements; choose an element "
                               f"category for a {scope} batch")
        if scope == "composition":
            base = find_element(repo, root) if root not in (None, "") else None
            if base is None:
                raise ProfileError("choose the composition (package or component) to apply to")
            cands = _composition_elements(base)
        else:
            cands = list(repo.root_package.walk())
        report_mismatch = False
    applied: list[str] = []
    skipped: list[dict] = []
    for e in cands:
        if e is repo.root_package and scope != "selection":
            continue
        if _in_profile_space(e) or isinstance(e, Relationship):
            if report_mismatch:
                skipped.append({"id": e.element_id, "name": e.qualified_name, "reason": "profile definition"})
            continue
        if category and not matches_category(e, category):
            if report_mismatch:
                skipped.append({"id": e.element_id, "name": e.qualified_name,
                                "reason": f"not a {category}"})
            continue
        if application_of(e, st) is not None:
            skipped.append({"id": e.element_id, "name": e.qualified_name, "reason": "already applied"})
            continue
        if not st.can_apply_to(e):
            skipped.append({"id": e.element_id, "name": e.qualified_name,
                            "reason": f"«{st.full_name}» does not apply to {e.kind}"})
            continue
        st.apply(e, local)
        applied.append(e.element_id)
    return {"stereotype": st.full_name, "scope": scope, "category": category,
            "applied": applied, "skipped": skipped, "count": len(applied)}


# ---------------------------------------------------------------------------
# Profile files (standalone JSON)
# ---------------------------------------------------------------------------

def _ref_name(st: Optional[Stereotype], profile: Profile) -> Optional[str]:
    if st is None:
        return None
    return st.name if st.profile is profile else st.full_name


def export_profile(profile: Profile) -> dict:
    return {
        "format": PROFILE_FORMAT,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "profile": {
            "id": profile.element_id, "name": profile.name,
            "description": profile.description, "version": profile.version,
            "root_stereotype": _ref_name(profile.root_stereotype, profile),
            "stereotypes": [{
                "id": s.element_id, "name": s.name, "description": s.description,
                "applies_to": s.category, "base": _ref_name(s.base, profile),
                "abstract": s.is_abstract, "style": dict(s.style),
                "defaults": {slot: _ref_name(getattr(s, f"default_{slot}_stereotype"), profile)
                             for slot in DEFAULT_SLOTS
                             if getattr(s, f"default_{slot}_stereotype") is not None},
                "properties": [{
                    "id": t.element_id, "name": t.name, "type": t.prop_type or "string",
                    "unit": t.unit, "default": t.default_value, "min": t.minimum,
                    "max": t.maximum, "literals": list(t.literals), "description": t.description,
                } for t in s.tags],
            } for s in profile.stereotypes],
        },
    }


def export_profile_json(profile: Profile) -> str:
    return json.dumps(export_profile(profile), indent=2, default=str)


def profile_file_name(profile: Profile) -> str:
    return f"{profile.name}.profile.json"


def _parse_document(data: Any) -> dict:
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as ex:
            raise ProfileError(f"profile file is not valid JSON: {ex}") from None
    if not isinstance(data, dict):
        raise ProfileError("profile file must be a JSON object")
    fmt = data.get("format")
    if fmt not in (PROFILE_FORMAT, None):
        raise ProfileError(f"unsupported profile format {fmt!r} (expected {PROFILE_FORMAT!r})")
    doc = data.get("profile", data if "stereotypes" in data else None)
    if not isinstance(doc, dict):
        raise ProfileError("profile file has no 'profile' object")
    if not isinstance(doc.get("stereotypes", []), list):
        raise ProfileError("'stereotypes' must be a list")
    return doc


def _validate_document(repo, doc: dict) -> dict:
    """Check a whole profile document before anything changes; returns a normalized form.

    Covers names, types, units, defaults and ranges of every property,
    applies-to values, styles, base references (local or existing in the
    project), inheritance cycles, property names hidden by a base, applies-to
    conflicts with a base, default stereotypes and the model root stereotype.
    """
    name = _wrap(check_name, doc.get("name"), "profile name")
    sts = []
    names: set[str] = set()
    for raw in doc.get("stereotypes", []):
        if not isinstance(raw, dict):
            raise ProfileError("each stereotype must be an object")
        sname = _wrap(check_name, raw.get("name"), "stereotype name")
        if sname in names:
            raise ProfileError(f"duplicate stereotype {sname!r} in profile {name!r}")
        names.add(sname)
        category = _check_category(raw.get("applies_to", ""))
        style = _wrap(normalize_style, raw.get("style") or {})
        props = []
        pnames: set[str] = set()
        for p in raw.get("properties", []) or []:
            if not isinstance(p, dict):
                raise ProfileError(f"properties of {sname!r} must be objects")
            ptype = p.get("type") or "string"
            label = f"{name}.{sname}.{p.get('name')}"
            tag = _wrap(build_property, p.get("name"), ptype, unit=p.get("unit") or "",
                        default=p.get("default"), minimum=p.get("min"), maximum=p.get("max"),
                        literals=p.get("literals"), description=p.get("description") or "",
                        label=label)
            if tag.name in pnames:
                raise ProfileError(f"duplicate property {tag.name!r} in {name}.{sname}")
            pnames.add(tag.name)
            props.append({"id": p.get("id"), "tag": tag})
        defaults = raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ProfileError(f"defaults of {name}.{sname} must be an object")
        sts.append({"id": raw.get("id"), "name": sname, "description": str(raw.get("description") or ""),
                    "applies_to": category, "base": raw.get("base"), "abstract": bool(raw.get("abstract")),
                    "style": style, "defaults": dict(defaults), "properties": props})

    def resolve(ref: Any) -> tuple[Optional[str], Optional[Stereotype]]:
        """(local name, None) for a stereotype of this document, (None, st) for an existing one."""
        if ref in (None, ""):
            return None, None
        ref = str(ref)
        local = ref.split(".", 1)[1] if ref.startswith(name + ".") else ref
        if local in names:
            return local, None
        try:
            ext = find_stereotype(repo, ref)
        except ProfileError:
            raise ProfileError(f"stereotype {ref!r} referenced by profile {name!r} is not defined "
                               f"in it or in the project") from None
        if any(a.profile is not None and a.profile.name == name for a in ext.ancestors()):
            raise ProfileError(f"stereotype {ref!r} belongs to (or inherits from) profile {name!r}; "
                               f"reference stereotypes of the imported file by their local name")
        return None, ext

    by_name = {s["name"]: s for s in sts}
    for s in sts:
        s["base_ref"] = resolve(s["base"])
        for slot in list(s["defaults"]):
            if slot not in DEFAULT_SLOTS:
                raise ProfileError(f"unknown default slot {slot!r} in {name}.{s['name']}")
            s["defaults"][slot] = resolve(s["defaults"][slot])
    for s in sts:                                    # inheritance cycles among local stereotypes
        seen, node = {s["name"]}, s
        while node["base_ref"][0] is not None:
            nxt = node["base_ref"][0]
            if nxt in seen:
                raise ProfileError(f"inheritance cycle through {name}.{nxt}")
            seen.add(nxt)
            node = by_name[nxt]

    def chain(s: dict) -> tuple[list[dict], Optional[Stereotype]]:
        local_chain, node = [s], s
        while node["base_ref"][0] is not None:
            node = by_name[node["base_ref"][0]]
            local_chain.append(node)
        return local_chain, node["base_ref"][1]

    def effective(s: dict) -> str:
        local_chain, ext = chain(s)
        for x in local_chain:
            if x["applies_to"]:
                return x["applies_to"]
        return ext.effective_category() if ext is not None else ""

    def chain_names(s: dict) -> set[str]:
        local_chain, ext = chain(s)
        out = {p["tag"].name for x in local_chain for p in x["properties"]}
        return out | ({t.name for t in ext.all_tags()} if ext is not None else set())

    def ref_category(ref: tuple) -> tuple[str, bool]:
        local, ext = ref
        return (effective(by_name[local]), by_name[local]["abstract"]) if local \
            else (ext.effective_category(), ext.is_abstract)

    for s in sts:
        local_chain, ext = chain(s)
        label = f"{name}.{s['name']}"
        if s["base_ref"] != (None, None):
            parent = effective(by_name[s["base_ref"][0]]) if s["base_ref"][0] \
                else s["base_ref"][1].effective_category()
            if s["applies_to"] and parent and parent != s["applies_to"]:
                raise ProfileError(f"{label} applies to {s['applies_to']} but its base applies to {parent}")
        inherited = {p["tag"].name for x in local_chain[1:] for p in x["properties"]}
        if ext is not None:
            inherited |= {t.name for t in ext.all_tags()}
        clash = sorted({p["tag"].name for p in s["properties"]} & inherited)
        if clash:
            raise ProfileError(f"{label}: properties {clash} are already defined by a base stereotype")
        own_cat = effective(s)
        for slot, ref in s["defaults"].items():
            if ref == (None, None):
                continue
            if own_cat not in ("", "Component", "Architecture"):
                raise ProfileError(f"{label}: only component stereotypes can name default stereotypes")
            cat, abstract = ref_category(ref)
            if abstract:
                raise ProfileError(f"{label}: the default {slot} stereotype is abstract")
            if cat not in ("", _SLOT_CATEGORY[slot]):
                raise ProfileError(f"{label}: the default {slot} stereotype applies to {cat} elements")
    root = doc.get("root_stereotype")
    if root not in (None, ""):
        local, _ext = resolve(root)
        if local is None:
            raise ProfileError(f"the model root stereotype {root!r} must belong to profile {name!r}")
        cat, abstract = ref_category((local, None))
        if abstract or cat not in ("", "Component", "Architecture"):
            raise ProfileError(f"{name}.{local} cannot be the model root stereotype "
                               f"(it is abstract or does not apply to architectures)")
        root = local
    version = doc.get("version")
    return {"name": name, "description": str(doc.get("description") or ""),
            "version": "" if version is None else str(version), "id": doc.get("id"),
            "root": root or None, "stereotypes": sts,
            "effective": {s["name"]: effective(s) for s in sts},
            "chain_names": {s["name"]: chain_names(s) for s in sts}}


def _fresh_id(repo, wanted: Any) -> Optional[str]:
    return wanted if isinstance(wanted, str) and wanted and repo.by_id(wanted) is None else None


def _check_external_descendants(repo, profile: Profile, doc: dict) -> None:
    """Before replacing ``profile``: stereotypes of other profiles derived from it must still fit."""
    for st in profile.stereotypes:
        new_name = next((s["name"] for s in doc["stereotypes"] if s["id"] == st.element_id), None) \
            or (st.name if st.name in doc["effective"] else None)
        if new_name is None:
            continue              # base deleted: derived stereotypes just lose it
        for d in descendants_of(repo, st):
            if d.base is not st or d.profile is profile:
                continue
            parent = doc["effective"][new_name]
            if d.category and parent and d.category != parent:
                raise _conflict(f"«{d.full_name}» applies to {d.category} and derives from "
                                f"«{profile.name}.{new_name}», which the file makes a {parent} stereotype")
            own = {t.name for x in [d, *descendants_of(repo, d)] for t in x.tags}
            clash = sorted(own & doc["chain_names"][new_name])
            if clash:
                raise _conflict(f"«{d.full_name}» already defines {clash}, which the file adds to its base")


def import_profile(repo, data: Any, *, replace: bool = False, file_name: Optional[str] = None,
                   parent: Any = None) -> dict:
    """Import a profile file into the project.

    The whole file is checked before the model changes. A profile with the
    same name is refused with 409 unless ``replace`` is set, in which case it
    is updated in place: stereotypes and properties are matched by id, then by
    name; values follow renames, unit and type changes; stereotypes or
    properties missing from the file are deleted (their applications / values
    stripped) and the changes are listed in the returned report.
    Returns ``{"profile", "created", "report"}``.
    """
    doc = _validate_document(repo, _parse_document(data))
    existing = next((p for p in profiles_of(repo) if p.name == doc["name"]), None)
    if existing is not None and not replace:
        raise _conflict(f"profile {doc['name']!r} (version {existing.version or '?'}) already exists; "
                        f"import with replace to update it")
    report: list[str] = []
    if existing is None:
        pkg = _require_package(repo, parent)
        _check_profile_name(repo, doc["name"], pkg)
        profile = Profile(name=doc["name"], description=doc["description"], version=doc["version"],
                          element_id=_fresh_id(repo, doc["id"]))
        pkg.own(profile)
        notify_created(profile, repo)
        created = True
    else:
        _check_external_descendants(repo, existing, doc)
        profile = existing
        created = False
    by_name = _merge_document(repo, profile, doc, report)
    profile.description, profile.version = doc["description"], doc["version"]
    new_root = by_name[doc["root"]] if doc["root"] else None
    profile.root_stereotype = _check_root_stereotype(new_root)
    applied = apply_root_stereotype(repo, profile)
    if new_root is not None:
        report += [f"applied «{new_root.full_name}» to {e.qualified_name}" for e in applied]
    profile.source = {"file": file_name or "", "format": PROFILE_FORMAT,
                      "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    log = _import_log(repo)
    log[:] = [x for x in log if x.get("profile") != profile.element_id]
    log.append({"profile": profile.element_id, "name": profile.name, "version": profile.version,
                "file": file_name or "", "imported_at": profile.source["imported_at"],
                "mode": "created" if created else "replaced"})
    return {"profile": profile, "created": created, "report": report}


def _merge_document(repo, profile: Profile, doc: dict, report: list[str]) -> dict[str, Stereotype]:
    """Make ``profile`` match a validated document (new or existing profile)."""
    existing = profile.stereotypes
    matched: dict[str, Stereotype] = {}
    used: set[int] = set()
    for s in doc["stereotypes"]:
        hit = next((x for x in existing if x.element_id == s["id"] and id(x) not in used), None) \
            or next((x for x in existing if x.name == s["name"] and id(x) not in used), None)
        if hit is not None:
            matched[s["name"]] = hit
            used.add(id(hit))
    for x in existing:
        if id(x) not in used:
            out = delete_stereotype(repo, x)
            report.append(f"deleted stereotype «{out['deleted']}» "
                          f"({out['applications_removed']} application(s) removed)")
    for i, (nm, st) in enumerate(matched.items()):   # two-step rename: swapped names never collide
        if st.name != nm:
            st.name = f"__import_tmp_{i}"
    by_name: dict[str, Stereotype] = {}
    for s in doc["stereotypes"]:
        st = matched.get(s["name"])
        if st is None:
            st = Stereotype(name=s["name"], category=s["applies_to"], description=s["description"],
                            style=s["style"], element_id=_fresh_id(repo, s["id"]))
            profile.own(st)
            notify_created(st, repo)
            if existing:
                report.append(f"added stereotype «{st.full_name}»")
        elif st.name != s["name"]:
            report.append(f"renamed stereotype to «{profile.name}.{s['name']}»")
            st.name = s["name"]
        by_name[s["name"]] = st
    # Properties first, while the old inheritance still links derived applications.
    for s in doc["stereotypes"]:
        _merge_properties(repo, by_name[s["name"]], s["properties"], report, announce=bool(existing))
    # Then the stereotype settings, with inheritance rebuilt from scratch.
    for st in by_name.values():
        st.base = None
        for slot in DEFAULT_SLOTS:
            setattr(st, f"default_{slot}_stereotype", None)
    for s in doc["stereotypes"]:
        out = update_stereotype(repo, by_name[s["name"]], description=s["description"],
                                applies_to=s["applies_to"], style=s["style"], force=True)
        report += [f"stripped {x}" for x in out["stripped"]]
    order: list[dict] = []
    for s in doc["stereotypes"]:                     # bases before the stereotypes deriving from them
        stack, node = [], s
        while node is not None and not any(node is x for x in order) and not any(node is x for x in stack):
            stack.append(node)
            node = next((x for x in doc["stereotypes"] if x["name"] == node["base_ref"][0]), None)
        order += list(reversed(stack))
    for s in order:
        local, ext = s["base_ref"]
        base = by_name[local] if local else ext
        if base is not None:
            out = update_stereotype(repo, by_name[s["name"]], base=base, force=True)
            report += [f"stripped {x}" for x in out["stripped"]]
    for s in doc["stereotypes"]:
        dflt = {slot: (by_name[ref[0]] if ref[0] else ref[1]) for slot, ref in s["defaults"].items()}
        out = update_stereotype(repo, by_name[s["name"]], abstract=s["abstract"],
                                defaults={slot: dflt.get(slot) for slot in DEFAULT_SLOTS}, force=True)
        report += [f"stripped {x}" for x in out["stripped"]]
    return by_name


def _merge_properties(repo, st: Stereotype, props: list[dict], report: list[str], *,
                      announce: bool = True) -> None:
    existing = list(st.tags)
    matched: dict[str, StereotypeTag] = {}
    used: set[int] = set()
    for p in props:
        tag = p["tag"]
        hit = next((x for x in existing if x.element_id == p["id"] and id(x) not in used), None) \
            or next((x for x in existing if x.name == tag.name and id(x) not in used), None)
        if hit is not None:
            matched[tag.name] = hit
            used.add(id(hit))
    for x in existing:
        if id(x) not in used:
            out = delete_property(repo, x)
            report.append(f"deleted property {out['deleted']} ({out['values_removed']} value(s) removed)")
    for i, (nm, t) in enumerate(matched.items()):
        if t.name != nm:
            t.name = f"__import_tmp_{i}"
    for i, p in enumerate(props):
        new = p["tag"]
        cur = matched.get(new.name)
        if cur is None:
            wanted = _fresh_id(repo, p["id"])
            if wanted:
                new.element_id = wanted
            st.own(new)
            st.tags.append(new)
            notify_created(new, repo)
            cur = new
            if announce:
                report.append(f"added property {cur.path}")
        else:
            cur.name = new.name
            out = update_property(repo, cur, prop_type=new.prop_type, unit=new.unit,
                                  default=new.default_value, minimum=new.minimum, maximum=new.maximum,
                                  literals=new.literals, description=new.description, _check_names=False)
            report += [f"reset {cur.path} on {r}" for r in out["reset"]]
        move_property(repo, cur, i)


def _import_log(repo) -> list[dict]:
    log = getattr(repo, "profile_imports", None)
    if log is None:
        log = []
        repo.profile_imports = log
    return log


def import_log(repo) -> list[dict]:
    return list(_import_log(repo))


# ---------------------------------------------------------------------------
# Description helpers (shared by the web API and the MCP tools)
# ---------------------------------------------------------------------------

def describe_profile(repo, profile: Profile, *, with_stereotypes: bool = True) -> dict:
    d = {
        "id": profile.element_id, "name": profile.name, "qualified_name": profile.qualified_name,
        "description": profile.description, "version": profile.version,
        "root_stereotype": profile.root_stereotype.full_name if profile.root_stereotype else None,
        "root_stereotype_id": profile.root_stereotype.element_id if profile.root_stereotype else None,
        "source": dict(profile.source),
        "stereotype_count": len(profile.stereotypes),
    }
    if with_stereotypes:
        d["stereotypes"] = [describe_stereotype(repo, s) for s in profile.stereotypes]
    return d


def describe_stereotype(repo, st: Stereotype) -> dict:
    d = st.describe()
    d["application_count"] = len(applications_of(repo, st))
    d["derived"] = [x.full_name for x in descendants_of(repo, st) if x.base is st]
    return d


def meta() -> dict:
    """Vocabularies for editors: types, categories, icons, line styles, units."""
    return {
        "types": list(PROPERTY_TYPES), "numeric_types": sorted(NUMERIC_TYPES),
        "int_ranges": {k: list(v) for k, v in INT_RANGES.items()},
        "categories": [c for c in CATEGORIES if c], "icons": [i for i in ICONS if i],
        "line_styles": [s for s in LINE_STYLES if s], "default_slots": list(DEFAULT_SLOTS),
        "units": units.list_units(), "format": PROFILE_FORMAT,
    }


def display_fields(e: Element) -> tuple[list[str], dict]:
    """``(badges, style)`` for the element JSON display contract."""
    apps = effective_applications(e)
    badges = [f"«{a.stereotype.name}»" for a in apps]
    style: dict = {}
    for a in apps:
        for key, value in a.stereotype.effective_style().items():
            if key == "line":
                if value in DASH_PATTERNS:
                    style.setdefault("dash", DASH_PATTERNS[value])
            else:
                style.setdefault(key, value)
    return badges, style


# ---------------------------------------------------------------------------
# Validation (repository rule: element rules can be cleared by other tests)
# ---------------------------------------------------------------------------

def _bad_name(e: Element) -> bool:
    try:
        check_name(e.name)
        return False
    except StereotypeError:
        return True


def validate_profiles(repo) -> Iterator[ValidationIssue]:
    E, W = Severity.ERROR, Severity.WARNING
    # Names created through generic element routes bypass the editor's checks.
    for e in [*profiles_of(repo), *stereotypes_of(repo),
              *(t for s in stereotypes_of(repo) for t in s.tags)]:
        if _bad_name(e):
            yield ValidationIssue(W, "profile.name", f"{e.kind} name {e.name!r} is not an identifier "
                                  f"(letters, digits, '_'), so 'Profile.Stereotype.property' "
                                  f"addresses cannot reach it", e)
    for st in stereotypes_of(repo):
        if st.has_base_cycle():
            yield ValidationIssue(E, "profile.stereotype.cycle",
                                  f"«{st.full_name}» inherits from itself", st)
            continue
        if st.base is not None and st.category:
            base_cat = st.base.effective_category()
            if base_cat and base_cat != st.category:
                yield ValidationIssue(E, "profile.stereotype.applies_to",
                                      f"«{st.full_name}» applies to {st.category} but its base "
                                      f"«{st.base.full_name}» applies to {base_cat}", st)
        inherited = {t.name: t for s in st.ancestors()[1:] for t in s.tags}
        for t in st.tags:
            if t.name in inherited:
                yield ValidationIssue(E, "profile.property.duplicate",
                                      f"{t.path} hides the inherited property of "
                                      f"«{inherited[t.name].stereotype.full_name}»", t)
            for problem in t.problems():
                yield ValidationIssue(E, "profile.property.definition", f"{t.path}: {problem}", t)
        for slot in DEFAULT_SLOTS:
            d = getattr(st, f"default_{slot}_stereotype", None)
            if d is None:
                continue
            cat = d.effective_category()
            if d.is_abstract or cat not in ("", _SLOT_CATEGORY[slot]):
                yield ValidationIssue(W, "profile.default_stereotype",
                                      f"default {slot} stereotype «{d.full_name}» of «{st.full_name}» "
                                      f"cannot be applied to {slot}s", st)
    for p in profiles_of(repo):
        r = p.root_stereotype
        if r is not None and (r.is_abstract or r.effective_category() not in ("", "Component", "Architecture")):
            yield ValidationIssue(W, "profile.root_stereotype",
                                  f"model root stereotype «{r.full_name}» cannot be applied to an architecture", p)
    for e in model_elements(repo):
        apps = stereotypes_on(e)
        seen: set[int] = set()
        for a in apps:
            st = a.stereotype
            if id(st) in seen:
                yield ValidationIssue(E, "profile.application.duplicate",
                                      f"«{st.full_name}» is applied more than once", e)
            seen.add(id(st))
            if st.is_abstract:
                yield ValidationIssue(E, "profile.application.abstract",
                                      f"abstract stereotype «{st.full_name}» is applied", e)
            if not st.can_apply_to(e):
                yield ValidationIssue(E, "profile.application.applies_to",
                                      f"«{st.full_name}» applies to {st.effective_category() or 'other'} "
                                      f"elements, not to this {e.kind}", e)
            parent = a.parent()
            for tag in st.all_tags():
                if parent is not None and not a.is_explicit(tag):
                    continue                  # inherited: checked once, on the definition
                v = a.get(tag.name)
                try:
                    ok = tag.coerce(v) == v
                    problem = "" if ok else f"{v!r} is not a valid {tag.type_label()}"
                except StereotypeError as ex:
                    ok, problem = False, str(ex)
                if not ok:
                    yield ValidationIssue(E, "profile.value.invalid",
                                          f"{st.full_name}.{tag.name}: {problem}", e)


# ---------------------------------------------------------------------------
# Hooks: default stereotypes, cleanup on removal
# ---------------------------------------------------------------------------

def _default_hosts(repo, host: Element) -> list[Element]:
    """Elements whose stereotypes give defaults to elements created in ``host``.

    A reference component keeps its ports, parts and connectors on its
    definition (engine/structure.py), so a definition also takes the defaults
    of the stereotypes applied to the component usages typed by it.
    """
    hosts = [host]
    if "PartDefinition" in kind_names(host):
        hosts += [u for u in model_elements(repo) if "PartUsage" in kind_names(u)
                  and any(t is host for t in getattr(u, "types", None) or [])]
    return hosts


def _on_created(e: Element, repo) -> None:
    """Default stereotypes for new ports / connectors / components and new root architectures."""
    try:
        if _in_profile_space(e) or isinstance(e, Relationship):
            return
        k = kind_names(e)
        slot = ("port" if "PortUsage" in k else "connector" if "ConnectionUsage" in k
                else "component" if "PartUsage" in k else None)
        host = e.owner
        if slot and host is not None:
            for h in _default_hosts(repo, host):
                for a in stereotypes_on(h):
                    d = a.stereotype.effective_default(slot)
                    if d is not None and not d.is_abstract and d.can_apply_to(e) \
                            and application_of(e, d) is None:
                        d.apply(e)
        if matches_category(e, "Architecture") and isinstance(e.owner, Package):
            for p in profiles_of(repo):
                r = p.root_stereotype
                if r is not None and not r.is_abstract and r.can_apply_to(e) \
                        and application_of(e, r) is None:
                    r.apply(e)
    except Exception:  # noqa: BLE001 - a default must never break element creation
        pass


def _on_removed(repo, removed: set[int]) -> None:
    for st in stereotypes_of(repo):
        apps = st.__dict__.get("_applications", [])
        st.__dict__["_applications"] = [a for a in apps if id(a.annotated_element) not in removed]
    log = getattr(repo, "profile_imports", None)
    if log:
        keep = []
        for entry in log:
            p = repo.by_id(entry.get("profile") or "")
            if p is not None and id(p) not in removed:
                keep.append(entry)
        log[:] = keep


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def inheritance_capable(e: Element) -> bool:
    """Can ``e`` inherit stereotype values (so the properties set on it are worth recording)?"""
    return "PartUsage" in kind_names(e)


def _encode(e: Element) -> Any:
    if isinstance(e, Profile):
        return {"description": e.description, "version": e.version,
                "root": e.root_stereotype.element_id if e.root_stereotype else None,
                "source": dict(e.source)}
    if isinstance(e, Stereotype):
        return {"category": e.category, "description": e.description, "style": dict(e.style),
                "defaults": {slot: getattr(e, f"default_{slot}_stereotype").element_id
                             for slot in DEFAULT_SLOTS
                             if getattr(e, f"default_{slot}_stereotype") is not None},
                "order": [t.element_id for t in e.tags]}
    if isinstance(e, StereotypeTag):
        if not e.prop_type and not e.description:
            return None
        return {"type": e.prop_type, "unit": e.unit, "min": e.minimum, "max": e.maximum,
                "literals": list(e.literals), "description": e.description}
    apps = stereotypes_on(e)
    if apps and inheritance_capable(e):
        # Which values were set on the element itself (the others are inherited from the
        # definition it is typed by). `values` in the application records what is read.
        return {"overrides": [{"stereotype": a.stereotype.element_id,
                               "properties": [t.element_id for t in a.explicit_tags()]}
                              for a in apps]}
    return None


def _decode(e: Element, data: Any, by_id: dict) -> None:
    if not isinstance(data, dict):
        return
    if isinstance(e, Profile):
        e.description = data.get("description") or ""
        e.version = data.get("version") or ""
        root = by_id.get(data.get("root") or "")
        e.root_stereotype = root if isinstance(root, Stereotype) else None
        e.source = dict(data.get("source") or {})
    elif isinstance(e, Stereotype):
        e.category = data.get("category") if data.get("category") in CATEGORIES else ""
        e.description = data.get("description") or ""
        try:
            e.style = normalize_style(data.get("style"))
        except StereotypeError:
            e.style = {}
        for slot in DEFAULT_SLOTS:
            d = by_id.get((data.get("defaults") or {}).get(slot) or "")
            setattr(e, f"default_{slot}_stereotype", d if isinstance(d, Stereotype) else None)
        order = {tid: i for i, tid in enumerate(data.get("order") or [])}
        e.tags.sort(key=lambda t: order.get(t.element_id, len(order)))
    elif isinstance(e, StereotypeTag):
        e.prop_type = data.get("type") or ""
        e.unit = data.get("unit") or ""
        e.minimum, e.maximum = data.get("min"), data.get("max")
        e.literals = list(data.get("literals") or [])
        e.description = data.get("description") or ""
    elif isinstance(data.get("overrides"), list):
        for entry in data["overrides"]:
            st = by_id.get((entry or {}).get("stereotype") or "")
            app = application_of(e, st) if isinstance(st, Stereotype) else None
            if app is not None:
                app.restore_explicit(by_id[i] for i in entry.get("properties") or []
                                     if isinstance(by_id.get(i), StereotypeTag))


def _encode_repo(repo) -> Any:
    log = getattr(repo, "profile_imports", None)
    return list(log) if log else None


def _decode_repo(repo, data: Any, by_id: dict) -> None:
    repo.profile_imports = [x for x in (data or []) if isinstance(x, dict) and x.get("profile") in by_id]


register_codec("profiles", _encode, _decode)
register_repo_codec("profiles", _encode_repo, _decode_repo)
register_repo_rule(validate_profiles)
register_created_hook(_on_created)
register_removal_hook(_on_removed)
