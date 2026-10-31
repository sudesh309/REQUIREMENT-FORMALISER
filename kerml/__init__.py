"""KerML kernel metamodel - foundation for SysML v2.

See :mod:`kerml.elements` for the conventions every module follows
(metaclass names, Python property names, constructors, ownership storage).
"""
from .elements import (
    Element, Relationship, Dependency, Annotation, AnnotatingElement, Comment, Documentation,
    TextualRepresentation, DerivedList, derived_id, escape_name, is_pure_relationship,
)
from .namespaces import (
    Namespace, Package, LibraryPackage, Membership, OwningMembership, Import, NamespaceImport,
    MembershipImport, ElementFilterMembership, VISIBILITIES,
)
from .types import (
    Type, Classifier, DataType, Class, Structure, Behavior, Association,
    Specialization, Subclassification, Conjugation, Disjoining, Unioning, Intersecting,
    Differencing, FeatureMembership,
)
from .features import (
    Feature, FeatureTyping, Subsetting, Redefinition, ReferenceSubsetting, CrossSubsetting,
    FeatureChaining, FeatureInverting, TypeFeaturing, EndFeatureMembership,
    Multiplicity, MultiplicityRange, FeatureDirection,
)
from .behaviors import Step, Function, Predicate, ParameterMembership, ReturnParameterMembership
from .expressions import (
    Expression, BooleanExpression, Invariant, LiteralExpression, LiteralBoolean, LiteralInteger,
    LiteralRational, LiteralString, LiteralInfinity, NullExpression, FeatureReferenceExpression,
    Invocation,
)
from .values import FeatureValue, MultiplicityRangeElement
from .connectors import Connector, BindingConnector, Succession
from .stereotypes import Stereotype, StereotypeTag, StereotypeApplication, stereotypes_on
from .interactions import (
    AssociationStructure, Interaction, Flow, FlowEnd, PayloadFeature, SuccessionFlow,
)
from .metadata import Metaclass, MetadataFeature
from .functions import ResultExpressionMembership
from .operator_expressions import (
    InstantiationExpression, InvocationExpression, ConstructorExpression, OperatorExpression,
    FeatureChainExpression, SelectExpression, CollectExpression, IndexExpression,
    MetadataAccessExpression,
)
from . import derived  # noqa: E402 - installs the generated KerML derived properties (last)

__all__ = [
    "Element", "Relationship", "Dependency", "Annotation", "AnnotatingElement", "Comment",
    "Documentation", "TextualRepresentation", "DerivedList", "derived_id", "escape_name",
    "is_pure_relationship",
    "Namespace", "Package", "LibraryPackage", "Membership", "OwningMembership", "Import",
    "NamespaceImport", "MembershipImport", "ElementFilterMembership", "VISIBILITIES",
    "Type", "Classifier", "DataType", "Class", "Structure", "Behavior", "Association",
    "Specialization", "Subclassification", "Conjugation", "Disjoining", "Unioning",
    "Intersecting", "Differencing", "FeatureMembership",
    "Feature", "FeatureTyping", "Subsetting", "Redefinition", "ReferenceSubsetting",
    "CrossSubsetting", "FeatureChaining", "FeatureInverting", "TypeFeaturing",
    "EndFeatureMembership", "Multiplicity", "MultiplicityRange", "FeatureDirection",
    "Step", "Function", "Predicate", "ParameterMembership", "ReturnParameterMembership",
    "Expression", "BooleanExpression", "Invariant", "LiteralExpression", "LiteralBoolean",
    "LiteralInteger", "LiteralRational", "LiteralString", "LiteralInfinity", "NullExpression",
    "FeatureReferenceExpression", "Invocation",
    "FeatureValue", "MultiplicityRangeElement",
    "Connector", "BindingConnector", "Succession",
    "Stereotype", "StereotypeTag", "StereotypeApplication", "stereotypes_on",
    "AssociationStructure", "Interaction", "Flow", "FlowEnd", "PayloadFeature", "SuccessionFlow",
    "Metaclass", "MetadataFeature", "ResultExpressionMembership",
    "InstantiationExpression", "InvocationExpression", "ConstructorExpression",
    "OperatorExpression", "FeatureChainExpression", "SelectExpression", "CollectExpression",
    "IndexExpression", "MetadataAccessExpression",
]
