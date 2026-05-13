"""Engine layer: repository, parser, validator, serializer."""
from .repository import Repository, ElementRegistry
from .validator import Validator, ValidationIssue, Severity
from .serializer import to_dict, to_json, from_dict, from_json
from .parser import parse, ParseError
from .diagram import bdd, ibd, requirements, diagram
from .graph_export import export_knowledge_graph, EXPORTERS
from .links import (
    LINK_KINDS, LinkKind, create_link, link_kind, links_of, describe_link,
    list_link_kinds,
)

__all__ = [
    "Repository", "ElementRegistry",
    "Validator", "ValidationIssue", "Severity",
    "to_dict", "to_json", "from_dict", "from_json",
    "parse", "ParseError",
    "bdd", "ibd", "requirements", "diagram",
    "export_knowledge_graph", "EXPORTERS",
    "LINK_KINDS", "LinkKind", "create_link", "link_kind",
    "links_of", "describe_link", "list_link_kinds",
]
