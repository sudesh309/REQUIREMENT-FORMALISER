"""Printer from the spec-shaped tree to canonical KerML / SysML text (Phase 2b).

    >>> from sysml_text import parse
    >>> from sysml_text.printer import print_tree
    >>> print(print_tree(parse("part def A:>B{attribute x:Real=1.5[kg];}").root), end="")
    part def A :> B {
        attribute x : Real = 1.5 [kg];
    }

The printer is the inverse of the parser: for every file of the corpus,
``parse(print_tree(parse(text).root))`` gives the same tree (``ast.diff``).

Formatting
----------
Four-space indentation, one member per line, ``{`` at the end of the
declaration line and ``}`` on its own line, ``;`` for an empty body. The
symbolic forms are used (``:``, ``:>``, ``:>>``, ``::>``, ``=>``, ``~``); names
are written plain when they are basic names and not reserved words of the
language, quoted (with escapes) otherwise; cross references are written as the
view gives them. Expressions get the fewest parentheses the precedence of KerML
Table 6 allows, units are written ``5 [kg]``, multiplicities ``x : T[0..*]``.
``doc``/``comment``/``rep`` bodies are written so that their processed text
(KerML 8.2.3.3.2) is unchanged: on one line when they are one line, otherwise
as a ``/*`` block with `` * `` line prefixes. Leading members that are plain
metadata usages are written as ``#X`` prefixes; implied elements of the
grammar (empty result members, empty parameters, a port definition's
conjugate, ...) are not written.

The view interface
------------------
The printer reads a tree only through a *view* with three methods:

``view.type(node) -> str``
    the metaclass name of an element or relationship (``"PartUsage"``,
    ``"FeatureTyping"``, ``"OperatorExpression"``, ...);
``view.get(node, name, default=None)``
    the value of the spec property ``name``: a ``str``, ``bool``, ``int`` or
    ``float``, an element, a reference, or a list of those. Children are
    reached by property: ``ownedRelationship`` (an element's relationships, in
    order) and ``ownedRelatedElement`` (a relationship's owned elements);
``view.ref(value, owner) -> str``
    the text of the cross reference ``value`` held by the relationship or
    element ``owner`` (a qualified name, quoted as needed).

An element-valued property of a relationship that is also one of its
``ownedRelatedElement`` (an owned feature chain) is printed as that chain; any
other element-valued end is a reference and printed through ``view.ref``.

:class:`AstView` implements the view for :class:`~sysml_text.ast.Node` and
:class:`~sysml_text.ast.Ref`. A model adapter implements the same three methods
over model elements, which use the same metaclass and property names
(ADR 0002, decision 7). Such an adapter should return ``None`` for properties
at their default value (``False`` flags, ``isUnique`` true, the default
visibility of memberships), leave out relationships with ``isImplied`` true,
give an import's visibility always (the notation requires it), and make
``ref`` return a name that resolves from the owner's namespace.
"""
from __future__ import annotations

import re

from .expressions import INFIX
from .lexer import KERML_KEYWORDS, SYSML_KEYWORDS

__all__ = ["AstView", "Printer", "PrintError", "print_tree"]

INDENT = "    "
_BASIC_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_ESCAPE = {"\\": "\\\\", "\b": "\\b", "\f": "\\f", "\t": "\\t", "\n": "\\n", "\r": "\\r", "\v": "\\v"}

PRIMARY = 100
UNARY = 14
BP = {op: bp for op, (bp, _) in INFIX.items()}
RIGHT_ASSOCIATIVE = frozenset(("^", "**"))
LAZY = frozenset(("??", "implies", "or", "and"))
CLASSIFICATION = frozenset(("istype", "hastype", "@", "as"))

IMPORTS = frozenset(("MembershipImport", "NamespaceImport", "MembershipExpose", "NamespaceExpose"))
ACTION_CONTEXTS = frozenset(("action", "calc", "case"))

# FeatureSpecialization and the other relationships of a declaration: type -> (symbol, end property)
SPECIALIZATIONS = {
    "FeatureTyping": (":", "type"), "ConjugatedPortTyping": (":", "originalPortDefinition"),
    "Subsetting": (":>", "subsettedFeature"), "Redefinition": (":>>", "redefinedFeature"),
    "ReferenceSubsetting": ("::>", "referencedFeature"), "CrossSubsetting": ("=>", "crossedFeature"),
    "Specialization": (":>", "general"), "Subclassification": (":>", "superclassifier"),
    "Conjugation": ("~", "originalType"), "Disjoining": ("disjoint from", "disjoiningType"),
    "Unioning": ("unions", "unioningType"), "Intersecting": ("intersects", "intersectingType"),
    "Differencing": ("differences", "differencingType"), "TypeFeaturing": ("featured by", "featuringType"),
    "FeatureInverting": ("inverse of", "invertingFeature"),
}
SINGLE = frozenset(("::>", "=>", "~", "inverse of"))  # not comma lists

# SysML definitions and usages: metaclass -> (keyword, body context)
DEFINITIONS = {
    "AttributeDefinition": ("attribute def", "definition"), "EnumerationDefinition": ("enum def", "enum"),
    "OccurrenceDefinition": ("occurrence def", "definition"), "ItemDefinition": ("item def", "definition"),
    "PartDefinition": ("part def", "definition"), "ConnectionDefinition": ("connection def", "definition"),
    "FlowDefinition": ("flow def", "definition"), "InterfaceDefinition": ("interface def", "interface"),
    "AllocationDefinition": ("allocation def", "definition"), "PortDefinition": ("port def", "definition"),
    "ActionDefinition": ("action def", "action"), "CalculationDefinition": ("calc def", "calc"),
    "StateDefinition": ("state def", "state"), "ConstraintDefinition": ("constraint def", "calc"),
    "RequirementDefinition": ("requirement def", "requirement"),
    "ConcernDefinition": ("concern def", "requirement"), "CaseDefinition": ("case def", "case"),
    "AnalysisCaseDefinition": ("analysis def", "case"),
    "VerificationCaseDefinition": ("verification def", "case"), "UseCaseDefinition": ("use case def", "case"),
    "ViewDefinition": ("view def", "viewdef"), "ViewpointDefinition": ("viewpoint def", "requirement"),
    "RenderingDefinition": ("rendering def", "definition"), "MetadataDefinition": ("metadata def", "definition"),
    "Definition": ("def", "definition"),
}
USAGES = {
    "AttributeUsage": ("attribute", "definition"), "EnumerationUsage": ("enum", "definition"),
    "OccurrenceUsage": ("occurrence", "definition"), "ItemUsage": ("item", "definition"),
    "PartUsage": ("part", "definition"), "PortUsage": ("port", "definition"),
    "RenderingUsage": ("rendering", "definition"), "ActionUsage": ("action", "action"),
    "CalculationUsage": ("calc", "calc"), "StateUsage": ("state", "state"),
    "ConstraintUsage": ("constraint", "calc"), "RequirementUsage": ("requirement", "requirement"),
    "ConcernUsage": ("concern", "requirement"), "ViewpointUsage": ("viewpoint", "requirement"),
    "CaseUsage": ("case", "case"), "AnalysisCaseUsage": ("analysis", "case"),
    "VerificationCaseUsage": ("verification", "case"), "UseCaseUsage": ("use case", "case"),
    "ViewUsage": ("view", "view"), "ReferenceUsage": ("ref", "definition"), "Usage": ("", "definition"),
}
CONTROL_NODES = {"MergeNode": "merge", "DecisionNode": "decide", "JoinNode": "join", "ForkNode": "fork"}
KERML_TYPES = {"Type": "type", "Classifier": "classifier", "DataType": "datatype", "Class": "class",
               "Structure": "struct", "Association": "assoc", "AssociationStructure": "assoc struct",
               "Behavior": "behavior", "Function": "function", "Predicate": "predicate",
               "Interaction": "interaction", "Metaclass": "metaclass"}
KERML_FEATURES = {"Feature": "feature", "Step": "step", "Expression": "expr", "BooleanExpression": "bool",
                  "Invariant": "inv", "Connector": "connector", "BindingConnector": "binding",
                  "Succession": "succession", "Flow": "flow", "SuccessionFlow": "succession flow"}
KERML_RELATIONSHIPS = {  # metaclass -> (keyword with identification, keyword, specific end, symbol, general end)
    "Specialization": ("specialization", "subtype", "specific", ":>", "general"),
    "Subclassification": ("specialization", "subclassifier", "subclassifier", ":>", "superclassifier"),
    "FeatureTyping": ("specialization", "typing", "typedFeature", ":", "type"),
    "Subsetting": ("specialization", "subset", "subsettingFeature", ":>", "subsettedFeature"),
    "Redefinition": ("specialization", "redefinition", "redefiningFeature", ":>>", "redefinedFeature"),
    "Conjugation": ("conjugation", "conjugate", "conjugatedType", "~", "originalType"),
    "Disjoining": ("disjoining", "disjoint", "typeDisjoined", "from", "disjoiningType"),
    "FeatureInverting": ("inverting", "inverse", "featureInverted", "of", "invertingFeature"),
}


class PrintError(Exception):
    """The tree has a node the printer cannot write (not one the parser builds)."""


class AstView:
    """The view of :mod:`sysml_text.ast` trees: nodes, their ``props`` and ``Ref`` texts."""

    def type(self, node) -> str:
        return node.type

    def get(self, node, name: str, default=None):
        return node.props.get(name, default)

    def ref(self, value, owner) -> str:
        return value.text


class _Cursor:
    """The relationships of an element, consumed in order by the productions."""

    __slots__ = ("items", "i")

    def __init__(self, items):
        self.items = list(items)
        self.i = 0

    def peek(self, n: int = 0):
        j = self.i + n
        return self.items[j] if j < len(self.items) else None

    def next(self):
        item = self.items[self.i]
        self.i += 1
        return item

    def rest(self) -> list:
        out = self.items[self.i:]
        self.i = len(self.items)
        return out


def print_tree(root, language: str = "sysml", view=None) -> str:
    """Canonical text of a tree (the root ``Namespace`` or any element)."""
    return Printer(language, view).print(root)


class Printer:
    """Writes KerML (``language="kerml"``) or SysML text from a tree read through a view."""

    def __init__(self, language: str = "sysml", view=None):
        if language not in ("sysml", "kerml"):
            raise ValueError(f"unknown language {language!r}")
        self.kerml = language == "kerml"
        self.view = view or AstView()
        self.keywords = KERML_KEYWORDS if self.kerml else SYSML_KEYWORDS

    # ------------------------------------------------------------- view

    def t(self, node) -> str:
        return self.view.type(node)

    def g(self, node, name: str, default=None):
        return self.view.get(node, name, default)

    def rels(self, node) -> list:
        return list(self.g(node, "ownedRelationship") or ())

    def owned(self, node) -> list:
        return list(self.g(node, "ownedRelatedElement") or ())

    def el(self, rel):
        owned = self.owned(rel)
        if not owned:
            raise PrintError(f"{self.t(rel)} owns no element")
        return owned[0]

    def target(self, rel, prop: str) -> str:
        """A relationship end: an owned feature chain, or a reference."""
        value = self.g(rel, prop)
        owned = self.owned(rel)
        if value is None:
            if owned:  # Unioning / Intersecting / Differencing with a chain
                return self.chain(owned[0])
            raise PrintError(f"{self.t(rel)} has no {prop}")
        for o in owned:
            if o is value:
                return self.chain(value)
        return self.view.ref(value, rel)

    def chain(self, feature) -> str:
        """OwnedFeatureChain: the chaining features joined with '.'."""
        return ".".join(self.target(c, "chainingFeature") for c in self.rels(feature))

    # ------------------------------------------------------------ lexical

    def name(self, text: str) -> str:
        if _BASIC_NAME.match(text) and text not in self.keywords:
            return text
        return "'" + "".join(_ESCAPE.get(c, "\\'" if c == "'" else c) for c in text) + "'"

    @staticmethod
    def string(text: str) -> str:
        return '"' + "".join(_ESCAPE.get(c, '\\"' if c == '"' else c) for c in text) + '"'

    @staticmethod
    def comment_text(body: str) -> str:
        """A REGULAR_COMMENT whose processed body is ``body``."""
        if "\n" not in body and "\r" not in body and body == body.lstrip(" \t\f") and "*/" not in body:
            return f"/* {body} */" if body else "/* */"
        lines = body.split("\n")
        out = ["/*"]
        for line in lines[:-1]:
            out.append(" * " + line if line.strip("\r") else " *" + line)
        last = lines[-1]
        if last:
            out.append(" * " + last + " */")
        else:
            out.append(" */")
        return "\n".join(out)

    def identification(self, node) -> str:
        """Identification : Element = ( '<' declaredShortName = NAME '>' )? ( declaredName = NAME )?"""
        parts = []
        short = self.g(node, "declaredShortName")
        name = self.g(node, "declaredName")
        if short is not None:
            parts.append(f"<{self.name(short)}>")
        if name is not None:
            parts.append(self.name(name))
        return " ".join(parts)

    # ------------------------------------------------------------- bodies

    def print(self, root) -> str:
        if self.t(root) == "Namespace" and self.g(root, "declaredName") is None:
            lines = self.body(self.rels(root), "namespace" if self.kerml else "package")
        else:
            lines = self.element(root, "namespace" if self.kerml else "package")
        return "\n".join(lines) + "\n" if lines else ""

    @staticmethod
    def indent(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            for sub in line.split("\n"):
                out.append(INDENT + sub if sub else "")
        return out

    def block(self, head: str, members: list, ctx: str, braces: bool = False) -> list[str]:
        """head ';' | head '{' members '}'"""
        if not members and not braces:
            return [head + ";"]
        lines = self.body(members, ctx)
        if not lines:
            return [head + " { }" if head else "{ }"]
        return [(head + " {") if head else "{", *self.indent(lines), "}"]

    def body(self, rels: list, ctx: str) -> list[str]:
        """The members of a body, in order, one per line; a member with a body of its own is set
        off by blank lines. A SourceSuccessionMember ('then') is written on the line of the member
        it precedes."""
        out: list[str] = []
        after_entry = False
        previous_block = False
        i = 0
        while i < len(rels):
            m = rels[i]
            if self.is_source_succession(m) and i + 1 < len(rels):
                lines = self.member(rels[i + 1], ctx)
                end = self.el(self.rels(self.el(m))[0])
                mult = [self.multiplicity(r) for r in self.rels(end)]
                lines[0] = "then " + "".join(x + " " for x in mult) + lines[0]
                after_entry = False
                i += 2
            else:
                lines = self.member(m, ctx, after_entry)
                after_entry = ctx == "state" and self.is_entry_like(m)
                i += 1
            block = len(lines) > 1 and lines[-1].startswith("}")
            if out and (block or previous_block):
                out.append("")
            out.extend(lines)
            previous_block = block
        return out

    def is_source_succession(self, m) -> bool:
        """SourceSuccessionMember: a SuccessionAsUsage with only its (empty) source end."""
        if self.t(m) != "FeatureMembership":
            return False
        el = self.el(m)
        if self.t(el) != "SuccessionAsUsage" or self.g(el, "declaredName") is not None:
            return False
        rels = self.rels(el)
        return len(rels) == 1 and self.t(rels[0]) == "EndFeatureMembership"

    def is_target_succession(self, el) -> bool:
        """TargetSuccession: a SuccessionAsUsage whose source end references nothing."""
        rels = self.rels(el)
        if self.t(el) != "SuccessionAsUsage" or len(rels) < 2 or self.t(rels[0]) != "EndFeatureMembership":
            return False
        source = self.el(rels[0])
        return all(self.t(r) != "ReferenceSubsetting" for r in self.rels(source))

    def is_entry_like(self, m) -> bool:
        if self.t(m) == "StateSubactionMembership":
            return self.g(m, "kind") == "entry"
        if self.t(m) != "FeatureMembership":
            return False
        el = self.el(m)
        if self.is_target_succession(el):
            return True
        rels = self.rels(el)
        return self.t(el) == "TransitionUsage" and bool(rels) and self.t(rels[0]) == "TransitionFeatureMembership"

    # ------------------------------------------------------------ members

    def member(self, m, ctx: str, after_entry: bool = False) -> list[str]:
        t = self.t(m)
        vis = self.g(m, "visibility")
        pre = vis + " " if vis else ""
        if t in IMPORTS:
            return self.import_(m)
        if t == "Membership":
            if ctx in ACTION_CONTEXTS and self.g(m, "memberName") is None and self.g(m, "memberShortName") is None:
                # InitialNodeMember (GRAMMAR_NOTES D9)
                return self.relationship_body(f"{pre}first {self.target(m, 'memberElement')}", m)
            return self.alias(m, pre)
        if t == "ElementFilterMembership":
            return [f"{pre}filter {self.expr(self.el(m))};"]
        if t == "ResultExpressionMembership":
            return [pre + self.expr(self.el(m))]
        el = self.el(m)
        et = self.t(el)
        if t == "ReturnParameterMembership":
            lines = self.element(el, ctx, member="return")
            lines[0] = "return " + lines[0]
        elif t == "VariantMembership":
            lines = self.enumerated_value(el) if ctx == "enum" else self.variant(el, ctx)
        elif t in ("SubjectMembership", "ActorMembership", "StakeholderMembership"):
            keyword = {"SubjectMembership": "subject", "ActorMembership": "actor",
                       "StakeholderMembership": "stakeholder"}[t]
            lines = self.keyword_usage(keyword, el, "definition")
        elif t == "ObjectiveMembership":
            lines = self.keyword_usage("objective", el, "requirement", declaration="constraint")
        elif t in ("RequirementConstraintMembership", "FramedConcernMembership", "RequirementVerificationMembership"):
            lines = self.constraint_member(m, el)
        elif t == "ViewRenderingMembership":
            lines = self.rendering_member(el)
        elif t == "StateSubactionMembership":
            lines = self.state_action(el)
            lines[0] = f"{self.g(m, 'kind')}{' ' if lines[0] != ';' else ''}{lines[0]}"
        elif t == "FeatureMembership" and ctx == "metadata":
            lines = self.metadata_body_feature(el)
        elif t == "FeatureMembership" and et == "SuccessionAsUsage" and self.is_target_succession(el):
            lines = self.target_succession(el, ctx)
        elif t == "FeatureMembership" and et == "TransitionUsage":
            lines = self.transition(el, ctx, after_entry)
        elif t == "OwningMembership" and self.kerml and ctx in ("type", "function") and et in KERML_FEATURES:
            lines = self.element(el, ctx)
            lines[0] = "member " + lines[0]  # TypeFeatureMember
        elif t in ("OwningMembership", "FeatureMembership"):
            lines = self.element(el, ctx)
        else:
            raise PrintError(f"cannot print a {t} member")
        lines[0] = pre + lines[0]
        return lines

    def alias(self, m, pre: str) -> list[str]:
        """AliasMember : Membership = MemberPrefix 'alias' ( '<' memberShortName = NAME '>' )?
        ( memberName = NAME )? 'for' memberElement = [QualifiedName] RelationshipBody"""
        words = [pre + "alias"]
        if self.g(m, "memberShortName") is not None:
            words.append(f"<{self.name(self.g(m, 'memberShortName'))}>")
        if self.g(m, "memberName") is not None:
            words.append(self.name(self.g(m, "memberName")))
        words += ["for", self.target(m, "memberElement")]
        return self.relationship_body(" ".join(words), m)

    def relationship_body(self, head: str, rel, exclude=(), annotations=None) -> list[str]:
        """RelationshipBody : Relationship = ';' | '{' ( ownedRelationship += OwnedAnnotation )* '}'
        (KerML: also ownedRelatedElement += OwnedRelatedElement)"""
        lines: list[str] = []
        for a in self.rels(rel) if annotations is None else annotations:
            lines += self.element(self.el(a), "namespace")
        skip = {id(x) for x in exclude}
        for prop in ("specific", "general", "subclassifier", "superclassifier", "typedFeature", "type",
                     "subsettingFeature", "subsettedFeature", "redefiningFeature", "redefinedFeature",
                     "conjugatedType", "originalType", "typeDisjoined", "disjoiningType", "featureInverted",
                     "invertingFeature", "importedNamespace"):
            v = self.g(rel, prop)
            if v is not None:
                skip.add(id(v))
        for o in self.owned(rel):
            if id(o) not in skip:
                lines += self.element(o, "namespace")
        if not lines:
            return [head + ";"]
        return [head + " {", *self.indent(lines), "}"]

    def import_(self, m) -> list[str]:
        """Import = visibility = VisibilityIndicator 'import' ( isImportAll ?= 'all' )? ImportDeclaration
        RelationshipBody;  Expose = 'expose' ( MembershipExpose | NamespaceExpose ) RelationshipBody"""
        t = self.t(m)
        words = []
        if self.g(m, "visibility"):
            words.append(self.g(m, "visibility"))
        words.append("expose" if t.endswith("Expose") else "import")
        if self.g(m, "isImportAll"):
            words.append("all")
        ns = self.g(m, "importedNamespace")
        exclude = []
        if t in ("NamespaceImport", "NamespaceExpose") and any(o is ns for o in self.owned(m)):
            # NamespaceImport = importedNamespace = FilterPackage { ownedRelatedElement += importedNamespace }
            decl, *filters = self.rels(ns)
            text = self.import_declaration(decl) + "".join(f"[{self.expr(self.el(f))}]" for f in filters)
            exclude = [ns]
        else:
            text = self.import_declaration(m)
        words.append(text)
        return self.relationship_body(" ".join(words), m, exclude)

    def import_declaration(self, imp) -> str:
        """MembershipImport = importedMembership = [QualifiedName] ( '::' isRecursive ?= '**' )?
        NamespaceImport = importedNamespace = [QualifiedName] '::' '*' ( '::' isRecursive ?= '**' )?"""
        recursive = "::**" if self.g(imp, "isRecursive") else ""
        if self.t(imp).startswith("Membership"):
            return self.target(imp, "importedMembership") + recursive
        return self.target(imp, "importedNamespace") + "::*" + recursive

    # ------------------------------------------------------------ elements

    def element(self, el, ctx: str, member: str = "", prefix: bool = True) -> list[str]:
        """Any element as a member of a body of context ``ctx``."""
        t = self.t(el)
        if t == "Comment":
            return [self.comment(el)]
        if t == "Documentation":
            return [self.documentation(el)]
        if t == "TextualRepresentation":
            return [self.representation(el)]
        if t in ("Package", "LibraryPackage", "Namespace"):
            return self.package(el)
        if t == "Dependency":
            return self.dependency(el)
        if t in ("MetadataFeature", "MetadataUsage"):
            return self.metadata_usage(el, prefix)
        if self.kerml:
            if t in KERML_TYPES:
                return self.kerml_type(el)
            if t in KERML_FEATURES:
                return self.kerml_feature(el, member)
            if t in ("Multiplicity", "MultiplicityRange"):
                return self.multiplicity_element(el)
            if t in KERML_RELATIONSHIPS or t == "TypeFeaturing":
                return self.kerml_relationship(el)
            raise PrintError(f"cannot print a {t} in KerML")
        if t in DEFINITIONS:
            return self.definition(el)
        return self.usage(el, ctx, prefix)

    def prefix_metadata(self, cur: _Cursor, annotation: bool = False) -> list[str]:
        """( ownedRelationship += PrefixMetadataMember )*: leading members that own a plain metadata usage."""
        out = []
        want = "Annotation" if annotation else "OwningMembership"
        while True:
            m = cur.peek()
            if m is None or self.t(m) != want:
                return out
            md = self.owned(m)
            if len(md) != 1 or self.t(md[0]) not in ("MetadataUsage", "MetadataFeature"):
                return out
            rels = self.rels(md[0])
            if len(rels) != 1 or self.t(rels[0]) != "FeatureTyping" or self.g(md[0], "declaredName") is not None \
                    or self.g(md[0], "declaredShortName") is not None:
                return out
            out.append("#" + self.target(rels[0], "type"))
            cur.next()

    def is_multiplicity_member(self, m) -> bool:
        if m is None or self.t(m) != "OwningMembership":
            return False
        owned = self.owned(m)
        return len(owned) == 1 and self.t(owned[0]) == "MultiplicityRange" \
            and self.g(owned[0], "declaredName") is None and self.g(owned[0], "declaredShortName") is None

    def multiplicity(self, m) -> str:
        """OwnedMultiplicity: '[' ( lower '..' )? upper ']'"""
        bounds = [self.expr(self.el(b)) for b in self.rels(self.el(m))]
        return "[" + "..".join(bounds) + "]"

    def specialization_part(self, el, cur: _Cursor) -> str:
        """FeatureSpecializationPart (and Type/Classifier specialization, conjugation, disjoining,
        unioning, intersecting, differencing, chaining, inverting and featuring parts), in the order
        of the relationships, with the MultiplicityPart where its relationship is."""
        parts: list[str] = []
        last_symbol = None
        mult_done = False
        while True:
            m = cur.peek()
            if m is None:
                break
            t = self.t(m)
            if t in SPECIALIZATIONS:
                symbol, prop = SPECIALIZATIONS[t]
                text = self.target(m, prop)
                if t == "ConjugatedPortTyping":
                    text = "~" + text
                if symbol == last_symbol and symbol not in SINGLE:
                    parts[-1] += ", " + text
                else:
                    parts.append(f"{symbol} {text}")
                last_symbol = symbol
                cur.next()
            elif t == "FeatureChaining":
                links = []
                while cur.peek() is not None and self.t(cur.peek()) == "FeatureChaining":
                    links.append(self.target(cur.next(), "chainingFeature"))
                parts.append("chains " + ".".join(links))
                last_symbol = None
            elif self.is_multiplicity_member(m) and not mult_done:
                text = self.multiplicity(cur.next())
                if parts and not parts[-1].endswith("]"):
                    parts[-1] += text
                else:
                    parts.append(text)
                parts += self.order_flags(el)
                mult_done = True
                last_symbol = None
            else:
                break
        if not mult_done:
            parts += self.order_flags(el)
        return " ".join(parts)

    def order_flags(self, el) -> list[str]:
        flags = []
        if self.g(el, "isOrdered"):
            flags.append("ordered")
        if self.g(el, "isUnique") is False:
            flags.append("nonunique")
        return flags

    def value_part(self, cur: _Cursor) -> str:
        """ValuePart : Feature = ownedRelationship += FeatureValue
        FeatureValue = ( '=' | isInitial ?= ':=' | isDefault ?= 'default' ( '=' | isInitial ?= ':=' )? )
        ownedRelatedElement += OwnedExpression"""
        m = cur.peek()
        if m is None or self.t(m) != "FeatureValue":
            return ""
        cur.next()
        if self.g(m, "isDefault"):
            op = "default := " if self.g(m, "isInitial") else "default = "
        else:
            op = ":= " if self.g(m, "isInitial") else "= "
        return op + self.expr(self.el(m))

    @staticmethod
    def join(*parts: str) -> str:
        return " ".join(p for p in parts if p)

    @staticmethod
    def name_and_spec(ident: str, spec: str) -> str:
        """Identification and specialization part; a leading multiplicity is attached: ``x[1]``"""
        if ident and spec.startswith("["):
            return ident + spec
        return " ".join(p for p in (ident, spec) if p)

    def declaration(self, el, cur: _Cursor, value: bool = False) -> str:
        """UsageDeclaration : Usage = Identification FeatureSpecializationPart? (ValuePart? with ``value``)"""
        text = self.name_and_spec(self.identification(el), self.specialization_part(el, cur))
        if value:
            text = self.join(text, self.value_part(cur))
        return text

    # ------------------------------------------------------- annotations

    def comment(self, c) -> str:
        """Comment = ( 'comment' Identification ( 'about' Annotation ( ',' Annotation )* )? )?
        ( 'locale' locale = STRING_VALUE )? body = REGULAR_COMMENT"""
        words = []
        ident = self.identification(c)
        abouts = [self.target(a, "annotatedElement") for a in self.rels(c) if self.t(a) == "Annotation"]
        if ident or abouts:
            words.append(self.join("comment", ident))
            if abouts:
                words.append("about " + ", ".join(abouts))
        return self._annotation_tail(words, c)

    def _annotation_tail(self, words: list[str], c) -> str:
        if self.g(c, "locale") is not None:
            words.append("locale " + self.string(self.g(c, "locale")))
        body = self.comment_text(self.g(c, "body", ""))
        if words and "\n" in body:
            return " ".join(words) + "\n" + body
        return " ".join(words + [body])

    def documentation(self, d) -> str:
        """Documentation = 'doc' Identification ( 'locale' locale = STRING_VALUE )? body = REGULAR_COMMENT"""
        return self._annotation_tail([self.join("doc", self.identification(d))], d)

    def representation(self, r) -> str:
        """TextualRepresentation = ( 'rep' Identification )? 'language' language = STRING_VALUE
        body = REGULAR_COMMENT"""
        words = []
        ident = self.identification(r)
        if ident:
            words.append("rep " + ident)
        words.append("language " + self.string(self.g(r, "language", "")))
        body = self.comment_text(self.g(r, "body", ""))
        return " ".join(words) + ("\n" if "\n" in body else " ") + body

    def metadata_usage(self, el, prefix: bool = True) -> list[str]:
        """MetadataUsage = UsageExtensionKeyword* ( '@' | 'metadata' ) MetadataUsageDeclaration
        ( 'about' Annotation ( ',' Annotation )* )? MetadataBody   (KerML MetadataFeature alike)"""
        cur = _Cursor(self.rels(el))
        words = self.prefix_metadata(cur) if prefix else []
        typing = cur.next()
        type_text = self.target(typing, "type")
        ident = self.identification(el)
        words.append(f"metadata {ident} : {type_text}" if ident else "@" + type_text)
        abouts = []
        while cur.peek() is not None and self.t(cur.peek()) == "Annotation" and not self.owned(cur.peek()):
            abouts.append(self.target(cur.next(), "annotatedElement"))
        if abouts:
            words.append("about " + ", ".join(abouts))
        return self.block(" ".join(words), cur.rest(), "metadata")

    def metadata_body_feature(self, el) -> list[str]:
        """MetadataBodyUsage : ReferenceUsage = 'ref'? ( ':>>' | 'redefines' )? ownedRelationship += OwnedRedefinition
        FeatureSpecializationPart? ValuePart? MetadataBody   (KerML MetadataBodyFeature alike)"""
        cur = _Cursor(self.rels(el))
        redefinition = cur.next()
        name = self.target(redefinition, "redefinedFeature")
        head = (":>> " if name.startswith("$") else "") + name
        head = self.join(head, self.specialization_part(el, cur), self.value_part(cur))
        return self.block(head, cur.rest(), "metadata")

    # ------------------------------------------------------------ packages

    def package(self, el) -> list[str]:
        """Package = PrefixMetadataMember* PackageDeclaration PackageBody;
        LibraryPackage = ( isStandard ?= 'standard' )? 'library' PrefixMetadataMember* PackageDeclaration PackageBody;
        Namespace = PrefixMetadataMember* NamespaceDeclaration NamespaceBody (KerML)"""
        t = self.t(el)
        cur = _Cursor(self.rels(el))
        words = []
        if t == "LibraryPackage":
            if self.g(el, "isStandard"):
                words.append("standard")
            words.append("library")
        words += self.prefix_metadata(cur)
        words.append("namespace" if t == "Namespace" else "package")
        words.append(self.identification(el))
        ctx = "namespace" if t == "Namespace" else "package"
        return self.block(self.join(*words), cur.rest(), ctx)

    def dependency(self, el) -> list[str]:
        """Dependency = ( ownedRelationship += PrefixMetadataAnnotation )* 'dependency'
        ( Identification? 'from' )? client += [QualifiedName] ( ',' ... )* 'to' supplier += [QualifiedName] ..."""
        cur = _Cursor(self.rels(el))
        words = self.prefix_metadata(cur, annotation=True)
        words.append("dependency")
        ident = self.identification(el)
        if ident:
            words += [ident, "from"]
        words.append(", ".join(self.view.ref(c, el) for c in self.g(el, "client", ())))
        words.append("to")
        words.append(", ".join(self.view.ref(s, el) for s in self.g(el, "supplier", ())))
        return self.relationship_body(" ".join(words), el, annotations=cur.rest())

    # --------------------------------------------------------------- KerML

    def kerml_type(self, el) -> list[str]:
        """Type = TypePrefix 'type' TypeDeclaration TypeBody, and Classifier, DataType, Class, Structure,
        Association, AssociationStructure, Behavior, Function, Predicate, Interaction, Metaclass
        = TypePrefix <keyword> ClassifierDeclaration TypeBody (FunctionBody)"""
        t = self.t(el)
        cur = _Cursor(self.rels(el))
        words = ["abstract"] if self.g(el, "isAbstract") else []
        words += self.prefix_metadata(cur)
        words.append(KERML_TYPES[t])
        if self.g(el, "isSufficient"):
            words.append("all")
        words.append(self.name_and_spec(self.identification(el), self.specialization_part(el, cur)))
        ctx = "function" if t in ("Function", "Predicate") else "type"
        return self.block(self.join(*words), cur.rest(), ctx)

    def feature_prefix(self, el) -> list[str]:
        """BasicFeaturePrefix / EndFeaturePrefix flags"""
        words = []
        if self.g(el, "isEnd"):
            if self.g(el, "isConstant"):
                words.append("const")
            words.append("end")
            return words
        if self.g(el, "direction"):
            words.append(self.g(el, "direction"))
        if self.g(el, "isDerived"):
            words.append("derived")
        if self.g(el, "isAbstract"):
            words.append("abstract")
        if self.g(el, "isComposite"):
            words.append("composite")
        elif self.g(el, "isPortion"):
            words.append("portion")
        if self.g(el, "isConstant"):
            words.append("const")
        elif self.g(el, "isVariable"):
            words.append("var")
        return words

    def kerml_feature_declaration(self, el, cur: _Cursor) -> str:
        """FeatureDeclaration : Feature = ( isSufficient ?= 'all' )? ( FeatureIdentification
        ( FeatureSpecializationPart | ConjugationPart )? | ... ) FeatureRelationshipPart*"""
        return self.join("all" if self.g(el, "isSufficient") else "",
                         self.name_and_spec(self.identification(el), self.specialization_part(el, cur)))

    def cross_feature(self, cur: _Cursor) -> str:
        """OwnedCrossFeatureMember: the first member of an end feature that owns a feature."""
        m = cur.peek()
        if m is None or self.t(m) != "OwningMembership":
            return ""
        owned = self.owned(m)
        if len(owned) != 1 or self.t(owned[0]) not in ("Feature", "ReferenceUsage"):
            return ""
        cur.next()
        cross = owned[0]
        prefix = self.feature_prefix(cross) if self.kerml else self.ref_prefix(cross, reference=True)
        c = _Cursor(self.rels(cross))
        if self.kerml:
            return self.join(*prefix, self.kerml_feature_declaration(cross, c))
        return self.join(*prefix, self.declaration(cross, c))

    def kerml_feature(self, el, member: str = "") -> list[str]:
        """Feature, Step, Expression, BooleanExpression, Invariant, Connector, BindingConnector, Succession,
        Flow, SuccessionFlow = FeaturePrefix <keyword> <declaration> ... (KerML 8.2.4.3, 8.2.5)"""
        t = self.t(el)
        cur = _Cursor(self.rels(el))
        words = self.feature_prefix(el)
        cross = self.cross_feature(cur) if self.g(el, "isEnd") else ""
        if cross:
            words.append(cross)
        words += self.prefix_metadata(cur)
        keyword = KERML_FEATURES[t]
        if t == "Feature":
            decl = self.join(self.kerml_feature_declaration(el, cur), self.value_part(cur))
            bare = decl and not cross and (member == "return" or self.g(el, "direction")
                                          or (self.g(el, "isEnd") and words[-1] == "end"))
            if not bare:
                words.append(keyword)
            words.append(decl)
            return self.block(self.join(*words), cur.rest(), "type")
        words.append(keyword)
        if t == "Invariant" and self.g(el, "isNegated"):
            words.append("false")
        if t in ("Step", "Expression", "BooleanExpression", "Invariant"):
            words += [self.kerml_feature_declaration(el, cur), self.value_part(cur)]
            ctx = "type" if t == "Step" else "function"
            return self.block(self.join(*words), cur.rest(), ctx)
        decl = self.kerml_feature_declaration(el, cur) if not self.g(el, "isSufficient") or self.identification(el) \
            else self.name_and_spec(self.identification(el), self.specialization_part(el, cur))
        if t in ("Flow", "SuccessionFlow"):
            words.append(self.flow_declaration(el, cur, decl))
        else:
            words.append(self.connector_declaration(el, cur, decl, t))
        return self.block(self.join(*words), cur.rest(), "type")

    def connector_ends(self, cur: _Cursor) -> list[str]:
        ends = []
        while cur.peek() is not None and self.t(cur.peek()) == "EndFeatureMembership":
            ends.append(self.connector_end(self.el(cur.next())))
        return ends

    def connector_end(self, end) -> str:
        """ConnectorEnd = ( ownedRelationship += OwnedCrossMultiplicityMember )? ( declaredName = NAME REFERENCES )?
        ownedRelationship += OwnedReferenceSubsetting"""
        words = []
        for r in self.rels(end):
            if self.t(r) == "OwningMembership":
                cross = self.el(r)
                words.append(self.multiplicity(self.rels(cross)[0]))
            elif self.t(r) == "ReferenceSubsetting":
                if self.g(end, "declaredName") is not None:
                    words += [self.name(self.g(end, "declaredName")), "::>"]
                words.append(self.target(r, "referencedFeature"))
        return " ".join(words)

    def connector_declaration(self, el, cur: _Cursor, decl: str, t: str) -> str:
        """Connector, BindingConnector and Succession declarations with their ends."""
        value = self.value_part(cur)
        ends = self.connector_ends(cur)
        suff = "all" if self.g(el, "isSufficient") and not self.identification(el) else ""
        if t == "Connector":
            if len(ends) > 2:
                return self.join(suff, decl, "(" + ", ".join(ends) + ")")
            if ends:
                return self.join(suff, decl, "from" if decl else "", f"{ends[0]} to {ends[1]}")
            return self.join(suff, decl, value)
        kw, sep = ("of", "=") if t == "BindingConnector" else ("first", "then")
        if ends:
            return self.join(suff, decl, kw if decl or t == "Succession" else "", f"{ends[0]} {sep} {ends[1]}")
        return self.join(suff, decl)

    def flow_declaration(self, el, cur: _Cursor, decl: str) -> str:
        """FlowDeclaration (KerML and SysML): declaration ValuePart? ( 'of' payload )? ( 'from' end 'to' end )?
        | end 'to' end"""
        value = self.value_part(cur)
        payload = ""
        m = cur.peek()
        if m is not None and self.t(m) == "FeatureMembership" and self.t(self.el(m)) == "PayloadFeature":
            payload = "of " + self.payload(self.el(cur.next()))
        ends = []
        while cur.peek() is not None and self.t(cur.peek()) in ("EndFeatureMembership", "ParameterMembership"):
            end = self.el(cur.next())
            ends.append(self.flow_end(end) if self.t(end) == "FlowEnd" else self.target(self.rels(end)[0],
                                                                                          "referencedFeature"))
        suff = "all" if self.g(el, "isSufficient") else ""
        head = self.join(decl, value, payload)
        if ends:
            pair = f"{ends[0]} to {ends[1]}"
            return self.join(suff, head, "from " + pair if head else pair)
        return self.join(suff, head)

    def flow_end(self, end) -> str:
        """FlowEnd = ( ownedRelationship += FlowEndSubsetting )? ownedRelationship += FlowFeatureMember"""
        parts = []
        for r in self.rels(end):
            if self.t(r) == "ReferenceSubsetting":
                parts.append(self.target(r, "referencedFeature"))
            else:
                feature = self.el(r)
                parts.append(self.target(self.rels(feature)[0], "redefinedFeature"))
        return ".".join(parts)

    def payload(self, p) -> str:
        """PayloadFeature = Identification? PayloadFeatureSpecializationPart ValuePart?
        | OwnedFeatureTyping OwnedMultiplicity? | OwnedMultiplicity OwnedFeatureTyping"""
        rels = self.rels(p)
        types = [self.t(r) for r in rels]
        plain = self.identification(p) == "" and not self.order_flags(p)
        if plain and types == ["FeatureTyping"]:
            return self.target(rels[0], "type")
        if plain and len(rels) == 2 and types[0] == "FeatureTyping" and self.is_multiplicity_member(rels[1]):
            return self.target(rels[0], "type") + self.multiplicity(rels[1])
        if plain and len(rels) == 2 and types[1] == "FeatureTyping" and self.is_multiplicity_member(rels[0]):
            return self.multiplicity(rels[0]) + " " + self.target(rels[1], "type")
        cur = _Cursor(rels)
        return self.join(self.identification(p), self.specialization_part(p, cur), self.value_part(cur))

    def multiplicity_element(self, el) -> list[str]:
        """MultiplicitySubset : Multiplicity = 'multiplicity' Identification Subsets TypeBody
        MultiplicityRange = 'multiplicity' Identification MultiplicityBounds TypeBody"""
        cur = _Cursor(self.rels(el))
        head = self.join("multiplicity", self.identification(el))
        if self.t(el) == "MultiplicityRange":
            bounds = []
            while cur.peek() is not None and self.t(cur.peek()) == "OwningMembership" and \
                    self.t(self.el(cur.peek())) != "MultiplicityRange" and len(bounds) < 2:
                bounds.append(self.expr(self.el(cur.next())))
            head += " [" + "..".join(bounds) + "]"
        else:
            head += " :> " + self.target(cur.next(), "subsettedFeature")
        return self.block(head, cur.rest(), "type")

    def kerml_relationship(self, el) -> list[str]:
        """Specialization, Subclassification, FeatureTyping, Subsetting, Redefinition, Conjugation,
        Disjoining, FeatureInverting and TypeFeaturing written as members."""
        t = self.t(el)
        ident = self.identification(el)
        if t == "TypeFeaturing":
            words = ["featuring"]
            if ident:
                words += [ident, "of"]
            words += [self.target(el, "featureOfType"), "by", self.target(el, "featuringType")]
            return self.relationship_body(" ".join(words), el)
        intro, keyword, specific, symbol, general = KERML_RELATIONSHIPS[t]
        words = [intro, ident] if ident else []
        words += [keyword, self.target(el, specific), symbol, self.target(el, general)]
        return self.relationship_body(" ".join(words), el)

    # ------------------------------------------------------- SysML: definitions

    def definition(self, el) -> list[str]:
        """<Kind>Definition = DefinitionPrefix <keyword> 'def' DefinitionDeclaration <Kind>Body"""
        t = self.t(el)
        keyword, ctx = DEFINITIONS[t]
        rels = self.rels(el)
        words = []
        if self.g(el, "isAbstract"):
            words.append("abstract")
        elif self.g(el, "isVariation"):
            words.append("variation")
        if self.g(el, "isIndividual"):
            words.append("individual")
            if rels and self.is_empty_multiplicity(rels[0]):
                rels = rels[1:]  # OccurrenceDefinitionPrefix
            elif t == "OccurrenceDefinition" and rels and self.is_empty_multiplicity(rels[-1]):
                rels = rels[:-1]  # IndividualDefinition = ... 'individual' ... 'def' Definition ...
                keyword = "def"
        if t == "PortDefinition" and rels and self.t(rels[-1]) == "OwningMembership" \
                and self.t(self.owned(rels[-1])[0]) == "ConjugatedPortDefinition":
            rels = rels[:-1]  # ConjugatedPortDefinitionMember (implied)
        cur = _Cursor(rels)
        words += self.prefix_metadata(cur)
        words += [keyword, self.identification(el), self.specialization_part(el, cur)]
        return self.typed_body(el, self.join(*words), cur.rest(), ctx)

    def is_empty_multiplicity(self, m) -> bool:
        owned = self.owned(m) if self.t(m) == "OwningMembership" else []
        return len(owned) == 1 and self.t(owned[0]) == "Multiplicity" and not self.rels(owned[0])

    def typed_body(self, el, head: str, members: list, ctx: str) -> list[str]:
        if ctx == "state" and self.g(el, "isParallel"):
            return self.block(head + " parallel", members, ctx, braces=True)
        return self.block(head, members, ctx)

    # ------------------------------------------------------------ SysML: usages

    def ref_prefix(self, el, reference: bool = False) -> list[str]:
        """RefPrefix : Usage = ( direction )? ( isDerived ?= 'derived' )? ( isAbstract | isVariation )?
        ( isConstant ?= 'constant' )?   (and BasicUsagePrefix's 'ref' with ``reference``)"""
        words = []
        if self.g(el, "direction"):
            words.append(self.g(el, "direction"))
        if self.g(el, "isDerived"):
            words.append("derived")
        if self.g(el, "isAbstract"):
            words.append("abstract")
        elif self.g(el, "isVariation"):
            words.append("variation")
        if self.g(el, "isConstant"):
            words.append("constant")
        if reference and self.g(el, "isReference"):
            words.append("ref")
        return words

    def usage_prefix(self, el, cur: _Cursor, prefix: bool, abstract: bool = True) -> list[str]:
        """UsagePrefix / OccurrenceUsagePrefix: ( EndUsagePrefix | RefPrefix 'ref'? ) 'individual'? PortionKind?
        UsageExtensionKeyword*"""
        t = self.t(el)
        if self.g(el, "isEnd"):
            words = ["end"]
            cross = self.cross_feature(cur)
            if cross:
                words.append(cross)
            if self.g(el, "isReference") and t != "ReferenceUsage":
                words.append("ref")
        else:
            words = self.ref_prefix(el, reference=t != "ReferenceUsage")
            if not abstract and "abstract" in words:
                words.remove("abstract")
        if self.g(el, "isIndividual"):
            words.append("individual")
        if self.g(el, "portionKind"):
            words.append(self.g(el, "portionKind"))
        if prefix:
            words += self.prefix_metadata(cur)
        return words

    def usage(self, el, ctx: str, prefix: bool = True) -> list[str]:
        """The usage elements (StructureUsageElement, BehaviorUsageElement, NonOccurrenceUsageElement)."""
        t = self.t(el)
        cur = _Cursor(self.rels(el))
        if t == "FlowUsage" and self.is_message(el):
            words = self.usage_prefix(el, cur, prefix, abstract=False)
            words += ["message", self.flow_declaration(el, cur, self.declaration(el, cur))]
            return self.block(self.join(*words), cur.rest(), "definition")
        words = self.usage_prefix(el, cur, prefix)
        if t in USAGES:
            keyword, body = USAGES[t]
            if t == "ReferenceUsage":
                keyword = "ref" if self.g(el, "isReference") else ""
            elif t == "OccurrenceUsage" and (self.g(el, "isIndividual") or self.g(el, "portionKind")):
                keyword = ""  # IndividualUsage / PortionUsage
            head = self.join(*words, keyword, self.declaration(el, cur, value=True))
            return self.typed_body(el, head, cur.rest(), body)
        if t in CONTROL_NODES:
            head = self.join(*words, CONTROL_NODES[t], self.declaration(el, cur))
            return self.block(head, cur.rest(), "action")
        method = getattr(self, "usage_" + t, None)
        if method is None:
            raise PrintError(f"cannot print a {t}")
        return method(el, cur, words, ctx)

    def is_message(self, el) -> bool:
        if not self.g(el, "isAbstract"):
            return False
        return not any(self.t(r) == "EndFeatureMembership" for r in self.rels(el))

    def ors_form(self, el, cur: _Cursor) -> bool:
        """( ownedRelationship += OwnedReferenceSubsetting FeatureSpecializationPart? | <keyword> declaration )"""
        m = cur.peek()
        return m is not None and self.t(m) == "ReferenceSubsetting" and self.identification(el) == ""

    def ors_or_declaration(self, el, cur: _Cursor, keyword: str, value: bool = True) -> str:
        if self.ors_form(el, cur):
            text = self.join(self.target(cur.next(), "referencedFeature"), self.specialization_part(el, cur))
        else:
            text = self.join(keyword, self.declaration(el, cur))
        return self.join(text, self.value_part(cur)) if value else text

    def usage_EventOccurrenceUsage(self, el, cur, words, ctx):
        """EventOccurrenceUsage = OccurrenceUsagePrefix 'event' ( OwnedReferenceSubsetting
        FeatureSpecializationPart? | 'occurrence' UsageDeclaration? ) UsageCompletion"""
        head = self.join(*words, "event", self.ors_or_declaration(el, cur, "occurrence"))
        return self.block(head, cur.rest(), "definition")

    def usage_PerformActionUsage(self, el, cur, words, ctx):
        head = self.join(*words, "perform", self.ors_or_declaration(el, cur, "action"))
        return self.block(head, cur.rest(), "action")

    def usage_ExhibitStateUsage(self, el, cur, words, ctx):
        head = self.join(*words, "exhibit", self.ors_or_declaration(el, cur, "state"))
        return self.typed_body(el, head, cur.rest(), "state")

    def usage_IncludeUseCaseUsage(self, el, cur, words, ctx):
        head = self.join(*words, "include", self.ors_or_declaration(el, cur, "use case"))
        return self.block(head, cur.rest(), "case")

    def usage_AssertConstraintUsage(self, el, cur, words, ctx):
        words = words + ["assert"] + (["not"] if self.g(el, "isNegated") else [])
        head = self.join(*words, self.ors_or_declaration(el, cur, "constraint"))
        return self.block(head, cur.rest(), "calc")

    def usage_SatisfyRequirementUsage(self, el, cur, words, ctx):
        words = words + (["assert", "not"] if self.g(el, "isNegated") else []) + ["satisfy"]
        head = self.join(*words, self.ors_or_declaration(el, cur, "requirement"))
        m = cur.peek()
        if m is not None and self.t(m) == "SubjectMembership":
            # 'by' SatisfactionSubjectMember: the FeatureChainMember of its reference expression
            cur.next()
            expr = self.el(self.rels(self.el(m))[0])
            head += " by " + self.feature_chain_member(self.rels(expr)[0])
        return self.block(head, cur.rest(), "requirement")

    def usage_ConnectionUsage(self, el, cur, words, ctx):
        """ConnectionUsage = OccurrenceUsagePrefix ( 'connection' UsageDeclaration ValuePart?
        ( 'connect' ConnectorPart )? | 'connect' ConnectorPart ) UsageBody"""
        return self._connector_usage(el, cur, words, "connection", "connect", "definition")

    def usage_InterfaceUsage(self, el, cur, words, ctx):
        return self._connector_usage(el, cur, words, "interface", "connect", "interface", direct=True)

    def usage_AllocationUsage(self, el, cur, words, ctx):
        return self._connector_usage(el, cur, words, "allocation", "allocate", "definition")

    def _connector_usage(self, el, cur, words, keyword, connect, body, direct=False):
        decl = self.declaration(el, cur, value=keyword != "allocation")
        ends = self.connector_ends(cur)
        part = (f"{ends[0]} to {ends[1]}" if len(ends) == 2 else "(" + ", ".join(ends) + ")") if ends else ""
        if not ends:
            head = self.join(*words, keyword, decl)
        elif decl:
            head = self.join(*words, keyword, decl, connect, part)
        elif direct:
            head = self.join(*words, keyword, part)
        else:
            head = self.join(*words, connect, part)
        return self.block(head, cur.rest(), body)

    def usage_FlowUsage(self, el, cur, words, ctx):
        head = self.join(*words, "flow", self.flow_declaration(el, cur, self.declaration(el, cur)))
        return self.block(head, cur.rest(), "definition")

    def usage_SuccessionFlowUsage(self, el, cur, words, ctx):
        head = self.join(*words, "succession flow", self.flow_declaration(el, cur, self.declaration(el, cur)))
        return self.block(head, cur.rest(), "definition")

    def usage_BindingConnectorAsUsage(self, el, cur, words, ctx):
        """BindingConnectorAsUsage = UsagePrefix ( 'binding' UsageDeclaration )? 'bind' end '=' end UsageBody"""
        decl = self.declaration(el, cur)
        ends = self.connector_ends(cur)
        head = self.join(*words, "binding " + decl if decl else "", f"bind {ends[0]} = {ends[1]}")
        return self.block(head, cur.rest(), "definition")

    def usage_SuccessionAsUsage(self, el, cur, words, ctx):
        """SuccessionAsUsage = UsagePrefix ( 'succession' UsageDeclaration )? 'first' end 'then' end UsageBody"""
        decl = self.declaration(el, cur)
        ends = self.connector_ends(cur)
        head = self.join(*words, "succession " + decl if decl else "", f"first {ends[0]} then {ends[1]}")
        return self.block(head, cur.rest(), "definition")

    def usage_TransitionUsage(self, el, cur, words, ctx):
        return self.transition(el, ctx, False, words)

    def usage_MetadataUsage(self, el, cur, words, ctx):  # pragma: no cover - handled by element()
        return self.metadata_usage(el)

    # ------------------------------------------------------------ action nodes

    def node_declaration(self, el, cur: _Cursor) -> str:
        """ActionNodeUsageDeclaration : ActionUsage = 'action' UsageDeclaration?"""
        decl = self.declaration(el, cur)
        return "action " + decl if decl else ""

    def usage_AcceptActionUsage(self, el, cur, words, ctx):
        head = self.join(*words, self.node_declaration(el, cur), self.accept_part(cur))
        return self.block(head, cur.rest(), "action")

    def accept_part(self, cur: _Cursor) -> str:
        """'accept' AcceptParameterPart: PayloadParameterMember ( 'via' NodeParameterMember )?"""
        param = self.el(cur.next())
        text = "accept " + self.payload_parameter(param)
        m = cur.peek()
        if m is not None and self.t(m) == "ParameterMembership":
            text += " via " + self.node_parameter(cur.next())
        return text

    def payload_parameter(self, p) -> str:
        """PayloadParameter : ReferenceUsage = PayloadFeature | Identification PayloadFeatureSpecializationPart?
        TriggerValuePart"""
        rels = self.rels(p)
        if rels and self.t(rels[-1]) == "FeatureValue" and self.t(self.el(rels[-1])) == "TriggerInvocationExpression":
            cur = _Cursor(rels[:-1])
            decl = self.join(self.identification(p), self.specialization_part(p, cur))
            trigger = self.el(rels[-1])
            kind = self.g(trigger, "kind")
            arg = self.rels(trigger)[0]
            value = self.lazy_arg(arg) if kind == "when" else self.arg(arg)
            return self.join(decl, kind, value)
        return self.payload(p)

    def node_parameter(self, m) -> str:
        """NodeParameterMember: the expression of its FeatureBinding"""
        param = self.el(m)
        return self.expr(self.el(self.rels(param)[0]))

    def is_empty_parameter(self, m) -> bool:
        if m is None or self.t(m) != "ParameterMembership":
            return False
        owned = self.owned(m)
        return len(owned) == 1 and self.t(owned[0]) == "ReferenceUsage" and not self.rels(owned[0]) \
            and self.identification(owned[0]) == ""

    def usage_SendActionUsage(self, el, cur, words, ctx):
        head = self.join(*words, self.node_declaration(el, cur), self.send_part(cur))
        return self.block(head, cur.rest(), "action")

    def send_part(self, cur: _Cursor) -> str:
        """'send' ( NodeParameterMember SenderReceiverPart? | EmptyParameterMember SenderReceiverPart )?"""
        words = ["send"]
        params = []
        while cur.peek() is not None and self.t(cur.peek()) == "ParameterMembership":
            params.append(cur.next())
        if params and not self.is_empty_parameter(params[0]):
            words.append(self.node_parameter(params[0]))
        if len(params) > 1:
            if self.is_empty_parameter(params[1]):
                words += ["to", self.node_parameter(params[2])]
            else:
                words += ["via", self.node_parameter(params[1])]
                if len(params) > 2:
                    words += ["to", self.node_parameter(params[2])]
        return " ".join(words)

    def usage_AssignmentActionUsage(self, el, cur, words, ctx):
        head = self.join(*words, self.node_declaration(el, cur), self.assign_part(cur))
        return self.block(head, cur.rest(), "action")

    def assign_part(self, cur: _Cursor) -> str:
        """'assign' AssignmentTargetMember FeatureChainMember ':=' NodeParameterMember"""
        target = self.el(cur.next())
        binding = self.rels(target)
        prefix = ""
        if binding:
            text, bp = self.xp(self.el(binding[0]))
            if bp < PRIMARY or self.t(self.el(binding[0])) == "FeatureChainExpression":
                text = f"({text})"
            prefix = text + "."
        member = self.feature_chain_member(cur.next())
        return f"assign {prefix}{member} := {self.node_parameter(cur.next())}"

    def usage_TerminateActionUsage(self, el, cur, words, ctx):
        m = cur.peek()
        param = ""
        if m is not None and self.t(m) == "ParameterMembership":
            param = self.node_parameter(cur.next())
        head = self.join(*words, self.node_declaration(el, cur), "terminate", param)
        return self.block(head, cur.rest(), "action")

    def usage_IfActionUsage(self, el, cur, words, ctx):
        """IfNode : IfActionUsage = ActionNodePrefix 'if' ExpressionParameterMember ActionBodyParameterMember
        ( 'else' ( ActionBodyParameterMember | IfNodeParameterMember ) )?"""
        head = self.join(*words, self.node_declaration(el, cur))
        return self._if(head, cur)

    def _if(self, head: str, cur: _Cursor) -> list[str]:
        cond = self.expr(self.el(cur.next()))
        lines = self.action_body_parameter(self.join(head, "if", cond), self.el(cur.next()))
        m = cur.peek()
        if m is not None and self.t(m) == "ParameterMembership":
            other = self.el(cur.next())
            if self.t(other) == "IfActionUsage":
                inner = _Cursor(self.rels(other))
                rest = self._if("", inner)
                lines[-1] += " else " + rest[0]
                lines += rest[1:]
            else:
                rest = self.action_body_parameter("", other)
                lines[-1] += " else " + rest[0]
                lines += rest[1:]
        return lines

    def action_body_parameter(self, head: str, action) -> list[str]:
        """ActionBodyParameter : ActionUsage = ( 'action' UsageDeclaration? )? '{' ActionBodyItem* '}'"""
        cur = _Cursor(self.rels(action))
        decl = self.declaration(action, cur)
        head = self.join(head, "action " + decl if decl or self.g(action, "declaredName") is not None else "")
        return self.block(head, cur.rest(), "action", braces=True)

    def usage_WhileLoopActionUsage(self, el, cur, words, ctx):
        """WhileLoopNode = ActionNodePrefix ( 'while' ExpressionParameterMember | 'loop' EmptyParameterMember )
        ActionBodyParameterMember ( 'until' ExpressionParameterMember ';' )?"""
        head = self.join(*words, self.node_declaration(el, cur))
        first = cur.next()
        if self.is_empty_parameter(first):
            head = self.join(head, "loop")
        else:
            head = self.join(head, "while", self.expr(self.el(first)))
        lines = self.action_body_parameter(head, self.el(cur.next()))
        m = cur.peek()
        if m is not None and self.t(m) == "ParameterMembership":
            lines[-1] += f" until {self.expr(self.el(cur.next()))};"
        return lines

    def usage_ForLoopActionUsage(self, el, cur, words, ctx):
        """ForLoopNode = ActionNodePrefix 'for' ForVariableDeclarationMember 'in' NodeParameterMember
        ActionBodyParameterMember"""
        head = self.join(*words, self.node_declaration(el, cur))
        var = self.el(cur.next())
        vcur = _Cursor(self.rels(var))
        head = self.join(head, "for", self.declaration(var, vcur), "in", self.node_parameter(cur.next()))
        return self.action_body_parameter(head, self.el(cur.next()))

    # --------------------------------------------------- successions, transitions

    def feature_chain_member(self, m) -> str:
        """FeatureChainMember : Membership = memberElement = [QualifiedName] | OwnedFeatureChainMember"""
        if self.t(m) == "Membership":
            return self.target(m, "memberElement")
        return self.chain(self.el(m))

    def transition_target(self, m) -> str:
        """TransitionSuccessionMember: the connector end of its succession's second end"""
        succession = self.el(m)
        return self.connector_end(self.el(self.rels(succession)[1]))

    def target_succession(self, el, ctx: str) -> list[str]:
        """TargetSuccession : SuccessionAsUsage = SourceEndMember 'then' ConnectorEndMember
        (ActionTargetSuccessionMember with UsageBody; EntryTransitionMember with ';')"""
        rels = self.rels(el)
        head = "then " + self.connector_end(self.el(rels[1]))
        if ctx == "state":
            return [head + ";"]
        return self.block(head, rels[2:], "definition")

    def transition(self, el, ctx: str, after_entry: bool, words=None) -> list[str]:
        """TransitionUsage, TargetTransitionUsage, GuardedTargetSuccession, DefaultTargetSuccession and
        GuardedSuccession, told apart by their first relationships."""
        words = list(words or [])
        cur = _Cursor(self.rels(el))
        first = cur.peek()
        ft = self.t(first)
        if ft == "TransitionFeatureMembership":
            # GuardedTargetSuccession (action bodies, entry transitions): guard 'then' target
            guard = self.expr(self.el(cur.next()))
            head = f"if {guard} then {self.transition_target(cur.next())}"
            if ctx == "state":
                return [head + ";"]
            return self.block(head, cur.rest(), "definition")
        if ft == "OwningMembership" and self.t(self.el(first)) == "Succession":
            # DefaultTargetSuccession = 'else' TransitionSuccessionMember
            head = "else " + self.transition_target(cur.next())
            return self.block(head, cur.rest(), "definition")
        if ft == "ParameterMembership":
            # TargetTransitionUsage
            cur.next()
            tail, needs_keyword = self.transition_tail(cur)
            if needs_keyword or after_entry:
                tail = "transition " + tail
            return self.block(self.join(*words, tail), cur.rest(), "action")
        decl = self.declaration(el, cur)
        source = self.feature_chain_member(cur.next())
        if self.is_empty_parameter(cur.peek()):
            # TransitionUsage = 'transition' ( UsageDeclaration 'first' )? FeatureChainMember ...
            cur.next()
            tail, _ = self.transition_tail(cur)
            head = self.join(*words, "transition", decl + " first" if decl else "first", source, tail)
            return self.block(head, cur.rest(), "action")
        # GuardedSuccession = ( 'succession' UsageDeclaration )? 'first' FeatureChainMember guard 'then' target
        guard = self.expr(self.el(cur.next()))
        target = self.transition_target(cur.next())
        head = self.join(*words, "succession " + decl if decl else "", f"first {source} if {guard} then {target}")
        return self.block(head, cur.rest(), "definition")

    def transition_tail(self, cur: _Cursor) -> tuple[str, bool]:
        """( EmptyParameterMember TriggerActionMember )? GuardExpressionMember? EffectBehaviorMember?
        'then' TransitionSuccessionMember; and whether the 'transition' keyword is required"""
        words = []
        trigger = guard = effect = False
        if self.is_empty_parameter(cur.peek()):
            cur.next()
            accept = self.el(cur.next())
            words.append(self.accept_part(_Cursor(self.rels(accept))))
            trigger = True
        m = cur.peek()
        if m is not None and self.t(m) == "TransitionFeatureMembership" and self.g(m, "kind") == "guard":
            words.append("if " + self.expr(self.el(cur.next())))
            guard = True
        m = cur.peek()
        if m is not None and self.t(m) == "TransitionFeatureMembership" and self.g(m, "kind") == "effect":
            words.append("do " + self.effect(self.el(cur.next())))
            effect = True
        words.append("then " + self.transition_target(cur.next()))
        return " ".join(w for w in words if w), effect and not trigger and not guard

    def effect(self, action) -> str:
        """EffectBehaviorUsage : ActionUsage = EmptyActionUsage | TransitionPerformActionUsage
        | TransitionAcceptActionUsage | TransitionSendActionUsage | TransitionAssignmentActionUsage
        (each with an optional '{' ActionBodyItem* '}')"""
        head, members = self.subaction(action)
        if not members:
            return head
        lines = self.block(head, members, "action", braces=True)
        return "\n".join(lines)

    def subaction(self, action) -> tuple[str, list]:
        """The perform / accept / send / assign action of a transition effect or state subaction."""
        t = self.t(action)
        cur = _Cursor(self.rels(action))
        if t == "ActionUsage":
            return "", cur.rest()
        if t == "PerformActionUsage":
            head = self.ors_or_declaration(action, cur, "action")
        elif t == "AcceptActionUsage":
            head = self.join(self.node_declaration(action, cur), self.accept_part(cur))
        elif t == "SendActionUsage":
            head = self.join(self.node_declaration(action, cur), self.send_part(cur))
        elif t == "AssignmentActionUsage":
            head = self.join(self.node_declaration(action, cur), self.assign_part(cur))
        else:
            raise PrintError(f"cannot print a {t} as a subaction")
        return head, cur.rest()

    def state_action(self, action) -> list[str]:
        """StateActionUsage : ActionUsage = EmptyActionUsage ';' | StatePerformActionUsage
        | StateAcceptActionUsage | StateSendActionUsage | StateAssignmentActionUsage (with ActionBody)"""
        head, members = self.subaction(action)
        if not head and not members:
            return [";"]
        return self.block(head, members, "action")

    # ------------------------------------------------- requirement members

    def keyword_usage(self, keyword: str, el, body: str, declaration: str = "usage") -> list[str]:
        """SubjectUsage, ActorUsage, StakeholderUsage = <keyword> UsageExtensionKeyword* Usage;
        ObjectiveMember's ObjectiveRequirementUsage = UsageExtensionKeyword* ConstraintUsageDeclaration
        RequirementBody"""
        cur = _Cursor(self.rels(el))
        words = [keyword] + self.prefix_metadata(cur)
        head = self.join(*words, self.declaration(el, cur, value=True))
        return self.block(head, cur.rest(), body)

    def constraint_member(self, m, el) -> list[str]:
        """RequirementConstraintMember ('assume' / 'require'), FramedConcernMember ('frame') and
        RequirementVerificationMember ('verify') with their constraint, concern and requirement usages."""
        t = self.t(m)
        if t == "RequirementConstraintMembership":
            intro = "assume" if self.g(m, "kind") == "assumption" else "require"
            keyword, body = "constraint", "calc"
        elif t == "FramedConcernMembership":
            intro, keyword, body = "frame", "concern", "requirement"
        else:
            intro, keyword, body = "verify", "requirement", "requirement"
        cur = _Cursor(self.rels(el))
        meta = self.prefix_metadata(cur)
        rest = cur.items[cur.i:]
        uses_result = any(self.t(r) == "ResultExpressionMembership" for r in rest)
        if not meta and self.ors_form(el, cur) and not uses_result:
            head = self.join(intro, self.target(cur.next(), "referencedFeature"), self.specialization_part(el, cur))
            return self.block(head, cur.rest(), "requirement")
        head = self.join(intro, *meta, keyword, self.declaration(el, cur, value=True))
        return self.block(head, cur.rest(), body)

    def rendering_member(self, el) -> list[str]:
        """ViewRenderingUsage : RenderingUsage = OwnedReferenceSubsetting FeatureSpecializationPart? UsageBody
        | ( UsageExtensionKeyword* 'rendering' | UsageExtensionKeyword+ ) Usage"""
        cur = _Cursor(self.rels(el))
        meta = self.prefix_metadata(cur)
        if not meta and self.ors_form(el, cur):
            head = self.join("render", self.target(cur.next(), "referencedFeature"), self.specialization_part(el, cur))
        else:
            head = self.join("render", *meta, "rendering", self.declaration(el, cur, value=True))
        return self.block(head, cur.rest(), "definition")

    def variant(self, el, ctx: str) -> list[str]:
        """VariantUsageMember = MemberPrefix 'variant' VariantUsageElement;
        VariantReference : ReferenceUsage = OwnedReferenceSubsetting FeatureSpecialization* UsageBody"""
        cur = _Cursor(self.rels(el))
        if self.t(el) == "ReferenceUsage" and not self.g(el, "isReference") and self.ors_form(el, cur):
            head = self.join("variant", self.target(cur.next(), "referencedFeature"),
                             self.specialization_part(el, cur))
            return self.block(head, cur.rest(), "definition")
        lines = self.element(el, ctx)
        lines[0] = "variant " + lines[0]
        return lines

    def enumerated_value(self, el) -> list[str]:
        """EnumeratedValue : EnumerationUsage = UsageExtensionKeyword* 'enum'? Usage"""
        cur = _Cursor(self.rels(el))
        words = self.prefix_metadata(cur) + ["enum", self.declaration(el, cur, value=True)]
        return self.block(self.join(*words), cur.rest(), "definition")

    # --------------------------------------------------------- expressions

    def expr(self, e) -> str:
        return self.xp(e)[0]

    def arg(self, m) -> str:
        """The operand of an argument member: member -> Feature -> FeatureValue -> expression."""
        return self.expr(self.arg_expr(m))

    def arg_expr(self, m):
        feature = self.el(m)
        rels = self.rels(feature)
        if rels and self.t(rels[0]) == "FeatureValue":
            return self.el(rels[0])
        raise PrintError(f"{self.t(m)} is not an argument member")

    def lazy_expr(self, m):
        """ArgumentExpressionMember: the expression inside its expression reference"""
        ref = self.arg_expr(m)
        return self.el(self.rels(ref)[0])

    def lazy_arg(self, m) -> str:
        return self.expr(self.lazy_expr(m))

    def operands(self, e) -> list:
        """The relationships of an operator or invocation expression without its EmptyResultMember."""
        return [m for m in self.rels(e) if not self.is_empty_result(m)]

    def is_empty_result(self, m) -> bool:
        if self.t(m) != "ReturnParameterMembership":
            return False
        owned = self.owned(m)
        return len(owned) == 1 and self.t(owned[0]) == "Feature" and not self.rels(owned[0]) \
            and self.g(owned[0], "declaredName") is None

    def paren(self, e, need: int) -> str:
        text, bp = self.xp(e)
        return f"({text})" if bp < need else text

    def xp(self, e) -> tuple[str, int]:
        """An expression and its binding power (PRIMARY for primary expressions)."""
        t = self.t(e)
        if t == "OperatorExpression":
            return self.operator(e)
        if t == "FeatureReferenceExpression":
            m = self.rels(e)[0]
            if self.t(m) == "Membership":
                return self.target(m, "memberElement"), PRIMARY
            return self.body_expression(self.el(m)), PRIMARY
        if t == "LiteralInteger":
            return str(self.g(e, "value")), PRIMARY
        if t == "LiteralRational":
            return repr(float(self.g(e, "value"))), PRIMARY
        if t == "LiteralString":
            return self.string(self.g(e, "value")), PRIMARY
        if t == "LiteralBoolean":
            return ("true" if self.g(e, "value") else "false"), PRIMARY
        if t == "LiteralInfinity":
            return "*", PRIMARY
        if t == "NullExpression":
            return "null", PRIMARY
        if t == "FeatureChainExpression":
            left, member = self.operands(e)
            base = self.arg_expr(left)
            text, bp = self.xp(base)
            if bp < PRIMARY or self.t(base) == "FeatureChainExpression":
                text = f"({text})"
            return f"{text}.{self.feature_chain_member(member)}", PRIMARY
        if t == "InvocationExpression":
            return self.invocation(e), PRIMARY
        if t == "ConstructorExpression":
            rels = self.rels(e)
            args = self.argument_list(self.rels(self.el(rels[1])))
            return f"new {self.feature_chain_member(rels[0])}({args})", PRIMARY
        if t in ("IndexExpression", "SelectExpression", "CollectExpression"):
            left, second = self.operands(e)
            base = self.paren(self.arg_expr(left), PRIMARY)
            if t == "IndexExpression":
                return f"{base}#({self.sequence(self.el(second))})", PRIMARY
            body = self.expr(self.arg_expr(second))
            return f"{base}{'.?' if t == 'SelectExpression' else '.'}{body}", PRIMARY
        if t == "MetadataAccessExpression":
            return self.target(self.rels(e)[0], "memberElement") + ".metadata", PRIMARY
        raise PrintError(f"cannot print a {t} as an expression")

    def sequence(self, e) -> str:
        """SequenceExpressionList: the elements of a ',' operator expression, without parentheses."""
        if self.t(e) == "OperatorExpression" and self.g(e, "operator") == ",":
            first, rest = self.rels(e)
            return f"{self.expr(self.el(first))}, {self.sequence(self.el(rest))}"
        return self.expr(e)

    def operator(self, e) -> tuple[str, int]:
        op = self.g(e, "operator")
        args = self.operands(e)
        if op == "if":
            cond, then, other = args
            return (f"if {self.paren(self.arg_expr(cond), 2)} ? {self.lazy_arg(then)} "
                    f"else {self.lazy_arg(other)}"), 1
        if op == ",":
            return f"({self.sequence(e)})", PRIMARY
        if op == "[":
            left, units = args
            return f"{self.paren(self.arg_expr(left), PRIMARY)} [{self.sequence(self.el(units))}]", PRIMARY
        if op == "all":
            return "all " + self.type_reference(args[0]), UNARY
        if op in CLASSIFICATION and len(args) == 1:
            sep = "" if op == "@" else " "
            return f"{op}{sep}{self.type_reference(args[0])}", UNARY
        if len(args) == 1:
            operand = self.paren(self.arg_expr(args[0]), UNARY)
            sep = " " if op == "not" or operand[0] in "+-~" else ""
            return f"{op}{sep}{operand}", UNARY
        bp = BP[op]
        if op in CLASSIFICATION:
            return f"{self.paren(self.arg_expr(args[0]), bp)} {op} {self.type_reference(args[1])}", bp
        if op in ("@@", "meta"):
            meta = self.arg_expr(args[0])
            return f"{self.target(self.rels(meta)[0], 'memberElement')} {op} {self.type_reference(args[1])}", bp
        left, right = args
        if op in RIGHT_ASSOCIATIVE:
            ltext = self.paren(self.arg_expr(left), bp + 1)
            rtext = self.paren(self.arg_expr(right), bp)
        else:
            ltext = self.paren(self.arg_expr(left), bp)
            rexpr = self.lazy_expr(right) if op in LAZY else self.arg_expr(right)
            rtext = self.paren(rexpr, bp + 1)
        if op == "..":
            return f"{ltext}..{rtext}", bp
        return f"{ltext} {op} {rtext}", bp

    def type_reference(self, m) -> str:
        """TypeReferenceMember / TypeResultMember: the type of its TypeReference"""
        feature = self.el(m)
        return self.target(self.rels(feature)[0], "type")

    def invocation(self, e) -> str:
        """InvocationExpression = InstantiatedTypeMember ArgumentList; FunctionOperationExpression =
        PrimaryArgumentMember '->' InstantiatedTypeMember ( BodyArgumentMember
        | FunctionReferenceArgumentMember | ArgumentList )"""
        rels = self.operands(e)
        if self.t(rels[0]) == "ParameterMembership":
            base = self.paren(self.arg_expr(rels[0]), PRIMARY)
            name = self.feature_chain_member(rels[1])
            args = rels[2:]
            if len(args) == 1 and self.t(args[0]) == "ParameterMembership":
                value = self.arg_expr(args[0])
                special = self.special_argument(value)
                if special is not None:
                    return f"{base}->{name} {special}"
            return f"{base}->{name}({self.argument_list(args)})"
        return f"{self.feature_chain_member(rels[0])}({self.argument_list(rels[1:])})"

    def special_argument(self, value) -> str | None:
        """A BodyExpression or FunctionReferenceExpression argument written without parentheses."""
        if self.t(value) != "FeatureReferenceExpression":
            return None
        m = self.rels(value)[0]
        if self.t(m) != "FeatureMembership":
            return None
        inner = self.el(m)
        rels = self.rels(inner)
        if self.t(inner) == "Expression" and len(rels) == 1 and self.t(rels[0]) == "FeatureTyping":
            return self.target(rels[0], "type")  # FunctionReference
        if self.t(inner) == "Expression":
            return self.body_expression(inner)
        return None

    def argument_list(self, args: list) -> str:
        """PositionalArgumentList | NamedArgumentList"""
        out = []
        for m in args:
            if self.t(m) == "FeatureMembership":
                arg = self.el(m)
                redef, value = self.rels(arg)
                out.append(f"{self.target(redef, 'redefinedFeature')} = {self.expr(self.el(value))}")
            else:
                out.append(self.arg(m))
        return ", ".join(out)

    def body_expression(self, body) -> str:
        """ExpressionBody : Expression = '{' FunctionBodyPart '}'"""
        lines = self.body(self.rels(body), "function" if self.kerml else "calc")
        if not lines:
            return "{ }"
        if all("\n" not in line for line in lines) and sum(len(x) for x in lines) < 100:
            return "{ " + " ".join(lines) + " }"
        return "{\n" + "\n".join(self.indent(lines)) + "\n}"
