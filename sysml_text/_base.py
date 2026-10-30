"""Parser infrastructure and the productions KerML and SysML share.

Recursive descent over the token arrays of :class:`~sysml_text.lexer.Tokens`.
Methods are named after the grammar productions and quote their rule;
a method either builds and returns a new node (a production whose result is a
new element, used on the right of an assignment) or fills the node it is given
(a production whose result type is the caller's, used without assignment).

Errors raise :class:`ParseError`; body loops catch it, record a
:class:`~sysml_text.ast.Diagnostic` and resynchronize at the next ``;`` or
``}`` (ADR 0003, decision 5). While speculating (bounded backtracking through
:meth:`BaseParser.attempt`) errors propagate to the attempt instead.
"""
from __future__ import annotations

from .ast import ERROR, Diagnostic, Node, ParseResult, Ref, Source, Span
from .lexer import Tokens, comment_body

VISIBILITY = frozenset(("public", "private", "protected"))
DIRECTIONS = frozenset(("in", "out", "inout"))

# Tokens that start a FeatureSpecialization (KerML 8.2.4.3.1, SysML 8.2.2.6.5).
SPECIALIZATION_TOKENS = frozenset((":", ":>", ":>>", "::>", "=>", "subsets", "redefines",
                                   "references", "crosses", "typed", "defined"))
MULTIPLICITY_TOKENS = frozenset(("[", "ordered", "nonunique"))


class ParseError(Exception):
    """A syntax error at token ``pos``; caught by the enclosing body loop."""

    def __init__(self, pos: int, message: str, expected: tuple[str, ...] = ()):
        super().__init__(message)
        self.pos = pos
        self.message = message
        self.expected = expected


class BaseParser:
    """Token cursor, diagnostics, recovery and the shared Root/Core productions."""

    LANGUAGE = "sysml"
    #: second word of the TYPED_BY / DEFINED_BY terminal after its first ('typed' / 'defined')
    TYPED_BY = "typed"

    def __init__(self, text: str, path: str | None = None):
        self.src = Source(text, path)
        toks = Tokens(self.src, self.LANGUAGE)
        self.k = toks.kinds
        self.v = toks.values
        self.s = toks.starts
        self.e = toks.ends
        self.p = 0
        self.spec = 0
        self.eof_reported = False
        self.diagnostics: list[Diagnostic] = [
            Diagnostic(ERROR, msg, Span(s, e, self.src)) for s, e, msg in toks.errors]

    def parse(self) -> ParseResult:
        root = self.RootNamespace()
        return ParseResult(root, self.diagnostics, self.src, self.LANGUAGE)

    # ------------------------------------------------------------------ cursor

    def at(self, kind: str) -> bool:
        return self.k[self.p] == kind

    def accept(self, kind: str) -> bool:
        if self.k[self.p] == kind:
            self.p += 1
            return True
        return False

    def expect(self, kind: str) -> int:
        """Consume a token of ``kind`` and return its index, or fail."""
        p = self.p
        if self.k[p] == kind:
            self.p = p + 1
            return p
        raise self.error(f"expected {self._show(kind)}", (kind,))

    def expect_word(self, word: str) -> None:
        """A contextual word (``typed``, ``defined``) that is not reserved: a NAME token."""
        if self.k[self.p] == "NAME" and self.v[self.p] == word:
            self.p += 1
            return
        raise self.error(f"expected '{word}'", (word,))

    def error(self, message: str, expected: tuple[str, ...] = ()) -> ParseError:
        """A ParseError at the current token, with what was found appended."""
        return ParseError(self.p, f"{message}, found {self.describe(self.p)}", expected)

    @staticmethod
    def _show(kind: str) -> str:
        return {"NAME": "a name", "STRING": "a string", "INT": "a number", "REAL": "a number",
                "COMMENT": "a comment /* ... */", "EOF": "end of text"}.get(kind, f"'{kind}'")

    def describe(self, i: int) -> str:
        k = self.k[i]
        if k == "EOF":
            return "end of text"
        text = self.src.text[self.s[i]:self.e[i]]
        if k == "NAME":
            return f"name {text}"
        if k in ("INT", "REAL"):
            return f"number {text}"
        if k == "STRING":
            return f"string {text[:30]}"
        if k == "COMMENT":
            return "comment /* ... */"
        if k == "ERROR":
            return f"invalid text {text[:10]!r}"
        if k[0].isalpha():
            return f"keyword '{k}'"
        return f"'{k}'"

    def span(self, i: int) -> Span:
        """From the start of token ``i`` to the end of the last consumed token."""
        j = self.p - 1
        if j < i:
            return Span(self.s[self.p], self.s[self.p], self.src)
        return Span(self.s[i], self.e[j], self.src)

    def fin(self, node: Node, i: int) -> Node:
        node.span = self.span(i)
        return node

    def new(self, type: str, i: int, props: dict | None = None) -> Node:
        """A node whose span runs from token ``i`` to the last consumed token."""
        return Node(type, {} if props is None else props, self.span(i))

    def empty(self, type: str) -> Node:
        """A node built from no text (``{ }`` productions such as EmptyFeature)."""
        s = self.s[self.p]
        return Node(type, {}, Span(s, s, self.src))

    # ------------------------------------------------------- errors, recovery

    def report(self, err: ParseError) -> None:
        pos = min(err.pos, len(self.k) - 1)
        if self.k[pos] == "EOF":
            if self.eof_reported:
                return
            self.eof_reported = True
        self.diagnostics.append(Diagnostic(ERROR, err.message, Span(self.s[pos], self.e[pos], self.src),
                                           err.expected))

    def sync(self, pos: int, start: int) -> None:
        """Skip to just after the next ``;`` or block, or to a ``}`` that closes the body."""
        k = self.k
        p = pos
        depth = 0
        while True:
            t = k[p]
            if t == "EOF":
                break
            if t == "{":
                depth += 1
            elif t == "}":
                if depth == 0:
                    break
                depth -= 1
                if depth == 0:
                    p += 1
                    break
            elif t == ";" and depth == 0:
                p += 1
                break
            p += 1
        if p <= start and k[p] not in ("}", "EOF"):
            p = start + 1
        self.p = p

    def attempt(self, fn, *args):
        """Run ``fn`` speculatively: its result, or ``None`` with the cursor restored."""
        save = self.p
        self.spec += 1
        try:
            return fn(*args)
        except ParseError:
            self.p = save
            return None
        finally:
            self.spec -= 1

    def items(self, node: Node, item, close: str = "}") -> None:
        """``item* close``: parse items into ``node`` until ``close``, recovering from errors."""
        k = self.k
        while True:
            t = k[self.p]
            if t == close:
                self.p += 1
                return
            if t == "EOF":
                err = self.error(f"expected {self._show(close)}", (close,))
                if self.spec:
                    raise err
                self.report(err)
                return
            start = self.p
            try:
                item(node)
            except ParseError as err:
                if self.spec:
                    raise
                self.report(err)
                self.sync(err.pos if err.pos >= start else self.p, start)

    def RootNamespace(self) -> Node:
        """RootNamespace : Namespace = NamespaceBodyElement*   (SysML: PackageBodyElement*)"""
        root = Node("Namespace", {}, None)
        k = self.k
        while k[self.p] != "EOF":
            start = self.p
            try:
                if k[start] == "}":
                    raise self.error("unexpected '}'")
                self.root_item(root)
            except ParseError as err:
                if self.spec:
                    raise
                self.report(err)
                self.sync(err.pos if err.pos >= start else self.p, start)
                if self.p == start:
                    self.p += 1
        root.span = Span(0, len(self.src.text), self.src)
        return root

    def root_item(self, node: Node) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------ names

    def NAME(self) -> str:
        p = self.p
        if self.k[p] != "NAME":
            raise self.error("expected a name", ("NAME",))
        self.p = p + 1
        return self.v[p]

    def QualifiedName(self) -> Ref:
        """QualifiedName = ( '$' '::' )? ( NAME '::' )* NAME"""
        k = self.k
        p = i = self.p
        glob = False
        if k[p] == "$":
            if k[p + 1] != "::":
                self.p = p + 1
                raise self.error("expected '::' after '$'", ("::",))
            glob = True
            p += 2
        if k[p] != "NAME":
            self.p = p
            raise self.error("expected a name", ("NAME",))
        v, s, e, text = self.v, self.s, self.e, self.src.text
        names = [v[p]]
        p += 1
        while k[p] == "::" and k[p + 1] == "NAME":
            names.append(v[p + 1])
            p += 2
        self.p = p
        if p == i + 1:
            return Ref(text[s[i]:e[i]], Span(s[i], e[i], self.src), (names[0],))
        parts = ["$"] if glob else []
        j = i + 2 if glob else i
        while j < p:
            parts.append(text[s[j]:e[j]])
            j += 2
        return Ref("::".join(parts), Span(s[i], e[p - 1], self.src), tuple(names))

    def scan_qn(self, p: int) -> int:
        """Index after a QualifiedName starting at token ``p``, or -1."""
        k = self.k
        if k[p] == "$":
            if k[p + 1] != "::":
                return -1
            p += 2
        if k[p] != "NAME":
            return -1
        p += 1
        while k[p] == "::" and k[p + 1] == "NAME":
            p += 2
        return p

    def scan_chain(self, p: int) -> tuple[int, int]:
        """(index after, segment count) of QualifiedName ( '.' QualifiedName )* at ``p``."""
        q = self.scan_qn(p)
        if q < 0:
            return -1, 0
        n = 1
        while self.k[q] == ".":
            r = self.scan_qn(q + 1)
            if r < 0:
                break
            q = r
            n += 1
        return q, n

    def Identification(self, node: Node) -> None:
        """Identification : Element = ( '<' declaredShortName = NAME '>' )? ( declaredName = NAME )?"""
        k = self.k
        if k[self.p] == "<":
            self.p += 1
            node.props["declaredShortName"] = self.NAME()
            self.expect(">")
        if k[self.p] == "NAME":
            node.props["declaredName"] = self.v[self.p]
            self.p += 1

    def VisibilityIndicator(self) -> str | None:
        """VisibilityIndicator : VisibilityKind = 'public' | 'private' | 'protected'"""
        t = self.k[self.p]
        if t in VISIBILITY:
            self.p += 1
            return t
        return None

    def MemberPrefix(self, node: Node) -> None:
        """MemberPrefix : Membership = ( visibility = VisibilityIndicator )?"""
        vis = self.VisibilityIndicator()
        if vis:
            node.props["visibility"] = vis

    # ------------------------------------------------------------ annotations

    def RelationshipBody(self, node: Node) -> None:
        """RelationshipBody : Relationship = ';' | '{' ( ownedRelationship += OwnedAnnotation )* '}'"""
        if self.accept(";"):
            return
        self.expect("{")
        self.items(node, self.RelationshipOwnedElement)

    def RelationshipOwnedElement(self, node: Node) -> None:
        """(SysML) ownedRelationship += OwnedAnnotation"""
        node.add("ownedRelationship", self.OwnedAnnotation())

    def Annotation(self) -> Node:
        """Annotation = annotatedElement = [QualifiedName]"""
        i = self.p
        ref = self.QualifiedName()
        return self.new("Annotation", i, {"annotatedElement": ref})

    def OwnedAnnotation(self) -> Node:
        """OwnedAnnotation : Annotation = ownedRelatedElement += AnnotatingElement"""
        i = self.p
        el = self.AnnotatingElement()
        return self.new("Annotation", i, {"ownedRelatedElement": [el]})

    def AnnotatingElement(self) -> Node:
        """AnnotatingElement = Comment | Documentation | TextualRepresentation | MetadataFeature"""
        t = self.k[self.p]
        if t in ("comment", "COMMENT", "locale"):
            return self.Comment()
        if t == "doc":
            return self.Documentation()
        if t in ("rep", "language"):
            return self.TextualRepresentation()
        if t in ("@", "metadata", "#"):
            return self.MetadataFeature()
        raise self.error("expected an annotating element (comment, doc, rep or metadata)")

    def _comment_tail(self, node: Node) -> None:
        if self.accept("locale"):
            node.props["locale"] = self._string()
        if self.k[self.p] != "COMMENT":
            raise self.error("expected a comment /* ... */", ("COMMENT",))
        node.props["body"] = comment_body(self.v[self.p])
        self.p += 1

    def _string(self) -> str:
        p = self.expect("STRING")
        return self.v[p]

    def Comment(self) -> Node:
        """Comment = ( 'comment' Identification ( 'about' ownedRelationship += Annotation
        ( ',' ownedRelationship += Annotation )* )? )? ( 'locale' locale = STRING_VALUE )?
        body = REGULAR_COMMENT"""
        i = self.p
        node = Node("Comment")
        if self.accept("comment"):
            self.Identification(node)
            if self.accept("about"):
                node.add("ownedRelationship", self.Annotation())
                while self.accept(","):
                    node.add("ownedRelationship", self.Annotation())
        self._comment_tail(node)
        return self.fin(node, i)

    def Documentation(self) -> Node:
        """Documentation = 'doc' Identification ( 'locale' locale = STRING_VALUE )? body = REGULAR_COMMENT"""
        i = self.expect("doc")
        node = Node("Documentation")
        self.Identification(node)
        self._comment_tail(node)
        return self.fin(node, i)

    def TextualRepresentation(self) -> Node:
        """TextualRepresentation = ( 'rep' Identification )? 'language' language = STRING_VALUE
        body = REGULAR_COMMENT"""
        i = self.p
        node = Node("TextualRepresentation")
        if self.accept("rep"):
            self.Identification(node)
        self.expect("language")
        node.props["language"] = self._string()
        if self.k[self.p] != "COMMENT":
            raise self.error("expected a comment /* ... */", ("COMMENT",))
        node.props["body"] = comment_body(self.v[self.p])
        self.p += 1
        return self.fin(node, i)

    def MetadataFeature(self) -> Node:
        raise NotImplementedError

    # -------------------------------------------------------------- namespaces

    def PrefixMetadataMember(self) -> Node:
        """PrefixMetadataMember : OwningMembership = '#' ownedRelatedElement += PrefixMetadataFeature"""
        i = self.expect("#")
        md = self.PrefixMetadataFeature()
        return self.new("OwningMembership", i, {"ownedRelatedElement": [md]})

    def PrefixMetadataAnnotation(self) -> Node:
        """PrefixMetadataAnnotation : Annotation = '#' ownedRelatedElement += PrefixMetadataFeature"""
        i = self.expect("#")
        md = self.PrefixMetadataFeature()
        return self.new("Annotation", i, {"ownedRelatedElement": [md]})

    METADATA_FEATURE = "MetadataFeature"

    def PrefixMetadataFeature(self) -> Node:
        """PrefixMetadataFeature : MetadataFeature = ownedRelationship += OwnedFeatureTyping
        (SysML: PrefixMetadataUsage : MetadataUsage)"""
        i = self.p
        typing = self.OwnedFeatureTyping()
        return self.new(self.METADATA_FEATURE, i, {"ownedRelationship": [typing]})

    def prefix_metadata(self) -> list[Node]:
        """( ownedRelationship += PrefixMetadataMember )*"""
        out = []
        while self.k[self.p] == "#":
            out.append(self.PrefixMetadataMember())
        return out

    def AliasMember(self, node: Node) -> None:
        """AliasMember : Membership = MemberPrefix 'alias' ( '<' memberShortName = NAME '>' )?
        ( memberName = NAME )? 'for' memberElement = [QualifiedName] RelationshipBody"""
        self.expect("alias")
        if self.accept("<"):
            node.props["memberShortName"] = self.NAME()
            self.expect(">")
        if self.k[self.p] == "NAME":
            node.props["memberName"] = self.NAME()
        self.expect("for")
        node.props["memberElement"] = self.QualifiedName()
        self.RelationshipBody(node)

    def Import(self, i: int, visibility: str | None, expose: bool = False) -> Node:
        """Import = visibility = VisibilityIndicator 'import' ( isImportAll ?= 'all' )?
        ImportDeclaration RelationshipBody

        Called after MemberPrefix (visibility is optional: GRAMMAR_NOTES.md). With
        ``expose``, SysML's Expose = 'expose' ( MembershipExpose | NamespaceExpose ) RelationshipBody."""
        self.p += 1  # 'import' / 'expose'
        all_ = not expose and self.accept("all")
        node = self.ImportDeclaration(expose)
        if self.k[self.p] == "[":
            # NamespaceImport = importedNamespace = FilterPackage { ownedRelatedElement += importedNamespace }
            # FilterPackageImport : Import = ImportDeclaration { visibility = 'public' }
            node.type = node.type.replace("Expose", "Import")
            node.props["visibility"] = "public"
            pkg = self.FilterPackage(node)
            node = Node("NamespaceExpose" if expose else "NamespaceImport",
                        {"importedNamespace": pkg, "ownedRelatedElement": [pkg]})
        if visibility:
            node.props["visibility"] = visibility
        if all_:
            node.props["isImportAll"] = True
        self.RelationshipBody(node)
        return self.fin(node, i)

    def ImportDeclaration(self, expose: bool = False) -> Node:
        """ImportDeclaration : Import = MembershipImport | NamespaceImport

        MembershipImport = importedMembership = [QualifiedName] ( '::' isRecursive ?= '**' )?
        NamespaceImport = importedNamespace = [QualifiedName] '::' '*' ( '::' isRecursive ?= '**' )?"""
        i = self.p
        ref = self.QualifiedName()
        k = self.k
        if k[self.p] == "::" and k[self.p + 1] == "*":
            self.p += 2
            node = Node("NamespaceExpose" if expose else "NamespaceImport", {"importedNamespace": ref})
        else:
            node = Node("MembershipExpose" if expose else "MembershipImport", {"importedMembership": ref})
        if k[self.p] == "::" and k[self.p + 1] == "**":
            self.p += 2
            node.props["isRecursive"] = True
        return self.fin(node, i)

    def FilterPackage(self, decl: Node) -> Node:
        """FilterPackage : Package = ownedRelationship += ImportDeclaration
        ( ownedRelationship += FilterPackageMember )+"""
        pkg = Node("Package", {"ownedRelationship": [decl]})
        while self.k[self.p] == "[":
            pkg.add("ownedRelationship", self.FilterPackageMember())
        pkg.span = Span(decl.span.start, self.e[self.p - 1], self.src)
        return pkg

    def FilterPackageMember(self) -> Node:
        """FilterPackageMember : ElementFilterMembership = '[' ownedRelatedElement += OwnedExpression ']'"""
        i = self.expect("[")
        expr = self.OwnedExpression()
        self.expect("]")
        return self.new("ElementFilterMembership", i, {"ownedRelatedElement": [expr]})

    def ElementFilterMember(self, node: Node) -> None:
        """ElementFilterMember : ElementFilterMembership = MemberPrefix 'filter'
        condition = OwnedExpression ';'"""
        self.expect("filter")
        node.add("ownedRelatedElement", self.OwnedExpression())
        self.expect(";")

    def Dependency(self, i: int, annotations: list[Node]) -> Node:
        """Dependency = ( ownedRelationship += PrefixMetadataAnnotation )* 'dependency'
        ( Identification? 'from' )? client += [QualifiedName] ( ',' client += [QualifiedName] )*
        'to' supplier += [QualifiedName] ( ',' supplier += [QualifiedName] )* RelationshipBody"""
        node = Node("Dependency", {"ownedRelationship": annotations} if annotations else {})
        self.expect("dependency")
        k = self.k
        t = k[self.p]
        if t == "from" or t == "<" or (t == "NAME" and k[self.p + 1] == "from"):
            self.Identification(node)
            self.expect("from")
        node.add("client", self.QualifiedName())
        while self.accept(","):
            node.add("client", self.QualifiedName())
        self.expect("to")
        node.add("supplier", self.QualifiedName())
        while self.accept(","):
            node.add("supplier", self.QualifiedName())
        self.RelationshipBody(node)
        return self.fin(node, i)

    # ------------------------------------------------------- specializations

    def owned_chain(self, i: int) -> Node:
        """OwnedFeatureChain : Feature = ownedRelationship += OwnedFeatureChaining
        ( '.' ownedRelationship += OwnedFeatureChaining )+   (the first QualifiedName is parsed)"""
        return self.FeatureChain(i)

    def FeatureChain(self, i: int) -> Node:
        """FeatureChain : Feature = ownedRelationship += OwnedFeatureChaining
        ( '.' ownedRelationship += OwnedFeatureChaining )+"""
        p = self.p
        self.p = i
        first = self.OwnedFeatureChaining()
        rels = [first]
        while self.k[self.p] == "." and self.scan_qn(self.p + 1) > 0:
            self.p += 1
            rels.append(self.OwnedFeatureChaining())
        if len(rels) < 2:
            self.p = p
            raise self.error("expected a feature chain")
        return self.new("Feature", i, {"ownedRelationship": rels})

    def OwnedFeatureChaining(self) -> Node:
        """OwnedFeatureChaining : FeatureChaining = chainingFeature = [QualifiedName]"""
        i = self.p
        ref = self.QualifiedName()
        return Node("FeatureChaining", {"chainingFeature": ref}, ref.span)

    def general(self, type: str, prop: str) -> Node:
        """GeneralType : Specialization = general = [QualifiedName]
        | general += OwnedFeatureChain { ownedRelatedElement += general }

        Shared by OwnedFeatureTyping, OwnedSubsetting, OwnedReferenceSubsetting,
        OwnedCrossSubsetting, OwnedRedefinition and OwnedSubclassification, with
        ``prop`` the property the metaclass redefines ``general`` with (as the
        SysML grammar writes it: GRAMMAR_NOTES.md)."""
        i = self.p
        ref = self.QualifiedName()
        if self.k[self.p] == "." and self.scan_qn(self.p + 1) > 0:
            chain = self.FeatureChain(i)
            return self.new(type, i, {prop: chain, "ownedRelatedElement": [chain]})
        return Node(type, {prop: ref}, ref.span)

    def OwnedFeatureTyping(self) -> Node:
        """OwnedFeatureTyping : FeatureTyping = type = [QualifiedName]
        | type = OwnedFeatureChain { ownedRelatedElement += type }"""
        return self.general("FeatureTyping", "type")

    def OwnedSubsetting(self) -> Node:
        """OwnedSubsetting : Subsetting = subsettedFeature = [QualifiedName]
        | subsettedFeature = OwnedFeatureChain { ownedRelatedElement += subsettedFeature }"""
        return self.general("Subsetting", "subsettedFeature")

    def OwnedReferenceSubsetting(self) -> Node:
        """OwnedReferenceSubsetting : ReferenceSubsetting = referencedFeature = [QualifiedName]
        | referencedFeature = OwnedFeatureChain { ownedRelatedElement += referencedFeature }"""
        return self.general("ReferenceSubsetting", "referencedFeature")

    def OwnedCrossSubsetting(self) -> Node:
        """OwnedCrossSubsetting : CrossSubsetting = crossedFeature = [QualifiedName]
        | crossedFeature = OwnedFeatureChain { ownedRelatedElement += crossedFeature }"""
        return self.general("CrossSubsetting", "crossedFeature")

    def OwnedRedefinition(self) -> Node:
        """OwnedRedefinition : Redefinition = redefinedFeature = [QualifiedName]
        | redefinedFeature = OwnedFeatureChain { ownedRelatedElement += redefinedFeature }"""
        return self.general("Redefinition", "redefinedFeature")

    def OwnedSubclassification(self) -> Node:
        """OwnedSubclassification : Subclassification = superclassifier = [QualifiedName]"""
        i = self.p
        ref = self.QualifiedName()
        return Node("Subclassification", {"superclassifier": ref}, ref.span)

    def SubclassificationPart(self, node: Node) -> None:
        """SuperclassingPart : Classifier = SPECIALIZES ownedRelationship += OwnedSubclassification
        ( ',' ownedRelationship += OwnedSubclassification )*"""
        self.p += 1  # ':>' or 'specializes'
        node.add("ownedRelationship", self.OwnedSubclassification())
        while self.accept(","):
            node.add("ownedRelationship", self.OwnedSubclassification())

    def typed_by(self) -> bool:
        """TYPED_BY = ':' | 'typed' 'by'   (SysML DEFINED_BY = ':' | 'defined' 'by')"""
        k = self.k
        if k[self.p] == ":":
            self.p += 1
            return True
        if (k[self.p] == self.TYPED_BY or (k[self.p] == "NAME" and self.v[self.p] == self.TYPED_BY)) \
                and k[self.p + 1] == "by":
            self.p += 2
            return True
        return False

    def FeatureTyping(self) -> Node:
        """(SysML) FeatureTyping = OwnedFeatureTyping | ConjugatedPortTyping"""
        return self.OwnedFeatureTyping()

    def FeatureSpecialization(self, node: Node) -> bool:
        """FeatureSpecialization : Feature = Typings | Subsettings | References | Crosses | Redefinitions

        Typings : Feature = TypedBy ( ',' ownedRelationship += FeatureTyping )*
        Subsettings : Feature = Subsets ( ',' ownedRelationship += OwnedSubsetting )*
        References : Feature = REFERENCES ownedRelationship += OwnedReferenceSubsetting
        Crosses : Feature = CROSSES ownedRelationship += OwnedCrossSubsetting
        Redefinitions : Feature = Redefines ( ',' ownedRelationship += OwnedRedefinition )*

        Returns False (consuming nothing) when no FeatureSpecialization starts here."""
        t = self.k[self.p]
        add = node.add
        if t == ":>" or t == "subsets":
            self.p += 1
            add("ownedRelationship", self.OwnedSubsetting())
            while self.accept(","):
                add("ownedRelationship", self.OwnedSubsetting())
        elif t == ":>>" or t == "redefines":
            self.p += 1
            add("ownedRelationship", self.OwnedRedefinition())
            while self.accept(","):
                add("ownedRelationship", self.OwnedRedefinition())
        elif t == "::>" or t == "references":
            self.p += 1
            add("ownedRelationship", self.OwnedReferenceSubsetting())
        elif t == "=>" or t == "crosses":
            self.p += 1
            add("ownedRelationship", self.OwnedCrossSubsetting())
        elif self.typed_by():
            add("ownedRelationship", self.FeatureTyping())
            while self.accept(","):
                add("ownedRelationship", self.FeatureTyping())
        else:
            return False
        return True

    def FeatureSpecializationPart(self, node: Node) -> bool:
        """FeatureSpecializationPart : Feature = FeatureSpecialization+ MultiplicityPart?
        FeatureSpecialization* | MultiplicityPart FeatureSpecialization*

        Returns whether anything was parsed."""
        k = self.k
        any_ = False
        mult = False
        while True:
            t = k[self.p]
            if t in SPECIALIZATION_TOKENS and self.FeatureSpecialization(node):
                any_ = True
            elif t in MULTIPLICITY_TOKENS and not mult:
                self.MultiplicityPart(node)
                mult = any_ = True
            else:
                return any_

    def MultiplicityPart(self, node: Node) -> None:
        """MultiplicityPart : Feature = ownedRelationship += OwnedMultiplicity
        | ( ownedRelationship += OwnedMultiplicity )?
          ( isOrdered ?= 'ordered' ( {isUnique = false} 'nonunique' )?
          | {isUnique = false} 'nonunique' ( isOrdered ?= 'ordered' )? )"""
        if self.k[self.p] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
        if self.accept("ordered"):
            node.props["isOrdered"] = True
            if self.accept("nonunique"):
                node.props["isUnique"] = False
        elif self.accept("nonunique"):
            node.props["isUnique"] = False
            if self.accept("ordered"):
                node.props["isOrdered"] = True

    def OwnedMultiplicity(self) -> Node:
        """OwnedMultiplicity : OwningMembership = ownedRelatedElement += OwnedMultiplicityRange"""
        i = self.p
        rng = self.MultiplicityBounds(Node("MultiplicityRange"))
        return Node("OwningMembership", {"ownedRelatedElement": [rng]}, rng.span)

    def MultiplicityBounds(self, node: Node) -> Node:
        """MultiplicityBounds : MultiplicityRange = '[' ( ownedRelationship += MultiplicityExpressionMember
        '..' )? ownedRelationship += MultiplicityExpressionMember ']'"""
        i = self.expect("[")
        node.add("ownedRelationship", self.MultiplicityExpressionMember())
        if self.accept(".."):
            node.add("ownedRelationship", self.MultiplicityExpressionMember())
        self.expect("]")
        return self.fin(node, i)

    def MultiplicityExpressionMember(self) -> Node:
        """MultiplicityExpressionMember : OwningMembership =
        ownedRelatedElement += ( LiteralExpression | FeatureReferenceExpression )"""
        t = self.k[self.p]
        if t == "NAME" or t == "$":
            expr = self.FeatureReferenceExpression()
        else:
            expr = self.LiteralExpression()
        return Node("OwningMembership", {"ownedRelatedElement": [expr]}, expr.span)

    def ValuePart(self, node: Node) -> bool:
        """ValuePart : Feature = ownedRelationship += FeatureValue   (returns whether present)"""
        t = self.k[self.p]
        if t == "=" or t == ":=" or t == "default":
            node.add("ownedRelationship", self.FeatureValue())
            return True
        return False

    def FeatureValue(self) -> Node:
        """FeatureValue = ( '=' | isInitial ?= ':=' | isDefault ?= 'default' ( '=' | isInitial ?= ':=' )? )
        ownedRelatedElement += OwnedExpression"""
        i = self.p
        node = Node("FeatureValue")
        t = self.k[i]
        self.p += 1
        if t == ":=":
            node.props["isInitial"] = True
        elif t == "default":
            node.props["isDefault"] = True
            if self.accept(":="):
                node.props["isInitial"] = True
            else:
                self.accept("=")
        elif t != "=":
            self.p = i
            raise self.error("expected '=', ':=' or 'default'")
        node.props["ownedRelatedElement"] = [self.OwnedExpression()]
        return self.fin(node, i)

    # Provided by ExpressionParser.
    def OwnedExpression(self) -> Node:  # pragma: no cover - overridden
        raise NotImplementedError

    def FeatureReferenceExpression(self) -> Node:  # pragma: no cover - overridden
        raise NotImplementedError

    def LiteralExpression(self) -> Node:  # pragma: no cover - overridden
        raise NotImplementedError
