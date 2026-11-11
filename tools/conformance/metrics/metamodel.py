"""How much of the KerML / SysML abstract syntax the Python element classes implement.

Measured against the metamodel registry (``kerml.metamodel``, generated from
the reflective models). The Python class of a spec metaclass is the element
class whose ``kind`` is the metaclass name (``kerml.metamodel.python_classes()``;
when several share a ``kind``, the one that declares it, in ``kerml``/``sysmlv2``
first).

- ``metamodel.<lang>.metaclasses_present``: spec metaclasses that have a Python class.
- ``metamodel.supertypes_consistent``: present metaclasses (both languages)
  each of whose spec supertypes is the ``kind`` declared by a Python ancestor.
- ``metamodel.<lang>.attributes_present`` / ``derived_present``: owned
  non-derived / derived properties found under their Python name (ADR 0002
  decision 2) on the metaclass's Python class. The denominator is every such
  property of *every* metaclass of the language, so a missing class counts all
  its properties as missing and the number cannot look good by omission.
  An instance is built with no arguments; failing that with ``None`` for each
  required parameter; failing that the class alone is inspected (attributes set
  in ``__init__`` are then missed). Attributes, Python properties and class
  attributes count; methods do not (a spec property is not called).
- ``metamodel.nonstandard_kinds``: element classes whose ``kind`` is not a
  spec metaclass and that declare no ``spec_metaclass`` (lower is better).

Each ``detail`` lists what is missing, so the report is a to-do list.
"""
from __future__ import annotations

import inspect

_MISSING = object()
_CORE_PACKAGES = ("kerml", "sysmlv2")


def _build(cls: type):
    """(instance or None, how): "no-args", "placeholders" or "failed"."""
    try:
        return cls(), "no-args"
    except Exception:  # noqa: BLE001 - any failure falls back
        pass
    try:
        params = inspect.signature(cls).parameters.values()
        args = [None for p in params if p.default is p.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        kwargs = {p.name: None for p in params if p.default is p.empty and p.kind == p.KEYWORD_ONLY}
        return cls(*args, **kwargs), "placeholders"
    except Exception:  # noqa: BLE001
        return None, "failed"


def _presence(cls: type, instance, name: str) -> str:
    """"yes", "method" or "no"."""
    for c in cls.__mro__:
        if name in vars(c):
            attr = vars(c)[name]
            if inspect.isfunction(attr) or isinstance(attr, (staticmethod, classmethod)):
                return "method"
            return "yes"            # property, descriptor or class attribute
    if instance is not None and name in getattr(instance, "__dict__", {}):
        return "yes"
    return "no"


def _class_map(mm, classes: list[type]) -> tuple[dict[str, type], list[str]]:
    """Metaclass name -> Python class, and notes on shared kinds."""
    by_kind: dict[str, list[type]] = {}
    for cls in classes:
        kind = getattr(cls, "kind", None)
        if mm.is_metaclass(kind):
            by_kind.setdefault(kind, []).append(cls)
    chosen, notes = {}, []
    for kind, found in by_kind.items():
        found.sort(key=lambda c: ("kind" not in vars(c),
                                  c.__module__.split(".")[0] not in _CORE_PACKAGES))
        chosen[kind] = found[0]
        if len(found) > 1:
            notes.append(f"kind {kind!r} is shared by {', '.join(_qual(c) for c in found)}; "
                         f"measured {_qual(found[0])}")
    return chosen, notes


def _qual(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _ratio(ok: int, total: int) -> float:
    return round(ok / total, 4) if total else 0.0


def collect() -> list[dict]:
    from kerml import metamodel as mm
    import sysmlv2.metamodel  # noqa: F401 - registers the SysML metaclasses

    classes = mm.python_classes()
    import_notes = [f"import failed: {mod}: {err}" for mod, err in mm.discovery_errors().items()]
    py_for, shared_notes = _class_map(mm, classes)

    built: dict[type, tuple[object, str]] = {cls: _build(cls) for cls in set(py_for.values())}
    out: list[dict] = []
    present_all: list = []

    for lang in mm.languages():
        key = lang.lower()
        metas = mm.all_metaclasses(lang)
        present = [m for m in metas if m.name in py_for]
        present_all += present
        missing_by_pkg: dict[str, list[str]] = {}
        for m in metas:
            if m.name not in py_for:
                missing_by_pkg.setdefault(m.package, []).append(m.name)
        out.append({
            "name": f"metamodel.{key}.metaclasses_present", "better": "higher",
            "value": _ratio(len(present), len(metas)),
            "detail": import_notes + shared_notes
            + [f"{pkg}: no class for {', '.join(names)}" for pkg, names in missing_by_pkg.items()],
        })

        lang_classes = [py_for[m.name] for m in present]
        needs_args = sorted(c.__name__ for c in lang_classes if built[c][1] == "placeholders")
        failed = sorted(c.__name__ for c in lang_classes if built[c][1] == "failed")
        construction = [f"construction: {len(needs_args) + len(failed)} of {len(lang_classes)} "
                        f"classes cannot be built without arguments"
                        + (f"; built with None placeholders: {', '.join(needs_args)}"
                           if needs_args else "")
                        + (f"; could not be built, class inspected: {', '.join(failed)}"
                           if failed else "")]
        for derived, metric in ((False, "attributes_present"), (True, "derived_present")):
            total = ok = 0
            detail: list[str] = []
            for m in metas:
                props = mm.properties(m.name, inherited=False, derived=derived)
                if not props:
                    continue
                total += len(props)
                cls = py_for.get(m.name)
                if cls is None:
                    detail.append(f"{m.name} [no class]: "
                                  + ", ".join(mm.python_name(p) for p in props))
                    continue
                instance = built[cls][0]
                gaps = []
                for p in props:
                    name = mm.python_name(p)
                    state = _presence(cls, instance, name)
                    if state == "yes":
                        ok += 1
                    else:
                        gaps.append(name if state == "no" else f"{name} (method)")
                if gaps:
                    detail.append(f"{m.name}: {', '.join(gaps)}")
            out.append({"name": f"metamodel.{key}.{metric}", "better": "higher",
                        "value": _ratio(ok, total), "detail": construction + detail})

    consistent, inconsistent = 0, []
    for m in present_all:
        cls = py_for[m.name]
        kinds = {vars(a).get("kind") for a in cls.__mro__[1:]}
        missing = [s for s in m.supertypes if s not in kinds]
        if missing:
            inconsistent.append(f"{m.name} ({_qual(cls)}): no Python ancestor for "
                                f"{', '.join(missing)}")
        else:
            consistent += 1
    out.append({"name": "metamodel.supertypes_consistent", "better": "higher",
                "value": _ratio(consistent, len(present_all)), "detail": inconsistent})

    nonstandard = []
    for cls in classes:
        if mm.spec_metaclass_of(cls) is None:
            declared = vars(cls).get("spec_metaclass")
            note = f"; declares unknown spec_metaclass {declared!r}" if declared else ""
            nonstandard.append(f"{_qual(cls)} (kind {getattr(cls, 'kind', None)!r}{note})")
    out.append({"name": "metamodel.nonstandard_kinds", "better": "lower",
                "value": len(nonstandard), "detail": nonstandard})
    return out
