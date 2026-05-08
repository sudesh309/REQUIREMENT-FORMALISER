"""KerML kernel metamodel - foundation for SysML v2."""
from .elements import Element, Relationship, Comment, Documentation, Annotation
from .namespaces import Namespace, Package, Membership, Import, OwningMembership
from .types import (
    Type, Classifier, DataType, Class, Structure, Behavior, Association,
    Specialization, Conjugation,
)
from .features import (
    Feature, FeatureMembership, FeatureTyping, Subsetting, Redefinition,
    Multiplicity, MultiplicityRange, FeatureDirection,
)
from .expressions import Expression, LiteralExpression, FeatureReferenceExpression, Invocation

__all__ = [
    "Element", "Relationship", "Comment", "Documentation", "Annotation",
    "Namespace", "Package", "Membership", "Import", "OwningMembership",
    "Type", "Classifier", "DataType", "Class", "Structure", "Behavior", "Association",
    "Specialization", "Conjugation",
    "Feature", "FeatureMembership", "FeatureTyping", "Subsetting", "Redefinition",
    "Multiplicity", "MultiplicityRange", "FeatureDirection",
    "Expression", "LiteralExpression", "FeatureReferenceExpression", "Invocation",
]
