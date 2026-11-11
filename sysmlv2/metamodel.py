"""SysML metaclasses in the metamodel registry.

Importing this module registers the SysML part of the registry (generated in
``sysmlv2/_metamodel_sysml.py`` by ``python -m tools.metagen``) with
``kerml.metamodel``, which holds the KerML part. The registry API is re-exported
here for convenience.
"""
from __future__ import annotations

from kerml import metamodel as _registry
from kerml.metamodel import (  # noqa: F401 - re-exported
    EnumSpec, MetaclassSpec, PropertySpec, all_enums, all_metaclasses, enum, is_metaclass,
    metaclass, properties, python_classes, python_name, spec_metaclass_of, supertypes_closure,
)

from . import _metamodel_sysml

_registry.register(_metamodel_sysml)

__all__ = [
    "EnumSpec", "MetaclassSpec", "PropertySpec", "all_enums", "all_metaclasses", "enum",
    "is_metaclass", "metaclass", "properties", "python_classes", "python_name",
    "spec_metaclass_of", "supertypes_closure",
]
