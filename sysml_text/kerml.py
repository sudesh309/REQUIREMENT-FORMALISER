"""KerML textual notation (KerML 1.0, 8.2.3 to 8.2.5): ``KerML-textual-bnf.kebnf``."""
from __future__ import annotations

from ._base import DIRECTIONS, SPECIALIZATION_TOKENS, ParseError
from .ast import Node
from .expressions import ExpressionParser

TYPE_KEYWORDS = {"type": "Type", "classifier": "Classifier", "datatype": "DataType", "class": "Class",
                 "struct": "Structure", "assoc": "Association", "behavior": "Behavior",
                 "function": "Function", "predicate": "Predicate", "interaction": "Interaction",
                 "metaclass": "Metaclass"}
FEATURE_KEYWORDS = frozenset(("feature", "step", "expr", "bool", "inv", "connector", "binding",
                              "succession", "flow"))
RELATIONSHIP_KEYWORDS = frozenset(("specialization", "subtype", "subclassifier", "typing", "subset",
                                   "redefinition", "conjugation", "conjugate", "disjoining", "disjoint",
                                   "inverting", "inverse", "featuring"))
#: tokens that can start a FeatureDeclaration
DECLARATION_START = SPECIALIZATION_TOKENS | {"NAME", "<", "[", "ordered", "nonunique", "all", "~",
                                             "conjugates", "specializes"}


class KerMLParser(ExpressionParser):
    """Parser for ``.kerml`` text."""

    LANGUAGE = "kerml"
    TYPED_BY = "typed"
    ARGUMENT_EXPRESSION_MEMBERSHIP = "FeatureMembership"
    METADATA_FEATURE = "MetadataFeature"

    def root_item(self, node: Node) -> None:
        self.NamespaceBodyElement(node)

    # ------------------------------------------------------------ members

    def NamespaceBodyElement(self, node: Node) -> None:
        """NamespaceBodyElement : Namespace = ownedRelationship += NamespaceMember
        | ownedRelationship += AliasMember | ownedRelationship += Import"""
        self.member(node, "namespace")

    def PackageBodyElement(self, node: Node) -> None:
        """PackageBody : Package = ';' | '{' ( NamespaceBodyElement | ownedRelationship += ElementFilterMember )* '}'"""
        self.member(node, "package")

    def TypeBodyElement(self, node: Node) -> None:
        """TypeBodyElement : Type = ownedRelationship += NonFeatureMember | ownedRelationship += FeatureMember
        | ownedRelationship += AliasMember | ownedRelationship += Import"""
        self.member(node, "type")

    def member(self, node: Node, ctx: str) -> None:
        """One member of a namespace (``ctx`` "namespace" or "package") or type ("type", "function")

        NamespaceMember : OwningMembership = NonFeatureMember | NamespaceFeatureMember
        FeatureMember : OwningMembership = TypeFeatureMember | OwnedFeatureMember
        TypeFeatureMember : OwningMembership = MemberPrefix 'member' ownedRelatedElement += FeatureElement
        OwnedFeatureMember : FeatureMembership = MemberPrefix ownedRelatedElement += FeatureElement
        ReturnFeatureMember : ReturnParameterMembership = MemberPrefix 'return' ownedRelatedElement += FeatureElement"""
        k = self.k
        i = self.p
        vis = self.VisibilityIndicator()
        t = k[self.p]
        if t == "import":
            node.add("ownedRelationship", self.Import(i, vis))
            return
        if t == "alias":
            m = Node("Membership", {"visibility": vis} if vis else {})
            self.AliasMember(m)
            node.add("ownedRelationship", self.fin(m, i))
            return
        if t == "filter" and ctx == "package":
            m = Node("ElementFilterMembership", {"visibility": vis} if vis else {})
            self.ElementFilterMember(m)
            node.add("ownedRelationship", self.fin(m, i))
            return
        mtype = None
        if t == "member" and ctx in ("type", "function"):
            self.p += 1
            mtype = "OwningMembership"
        elif t == "return" and ctx == "function":
            self.p += 1
            mtype = "ReturnParameterMembership"
        el, is_feature = self.element()
        if mtype is None:
            mtype = "FeatureMembership" if is_feature and ctx in ("type", "function") else "OwningMembership"
        elif not is_feature:
            raise ParseError(i, f"expected a feature after '{t}'")
        m = self.new(mtype, i, {"ownedRelatedElement": [el]})
        if vis:
            m.props["visibility"] = vis
        node.add("ownedRelationship", m)

    # ----------------------------------------------------------- elements

    def element(self) -> tuple[Node, bool]:
        """MemberElement : Element = AnnotatingElement | NonFeatureElement, or a FeatureElement.

        Returns the element and whether it is a FeatureElement."""
        k = self.k
        i = self.p
        t = k[i]
        if t in ("comment", "COMMENT", "locale"):
            return self.Comment(), False
        if t == "doc":
            return self.Documentation(), False
        if t in ("rep", "language"):
            return self.TextualRepresentation(), False
        if t in ("standard", "library"):
            return self.LibraryPackage(), False
        if t == "multiplicity":
            return self.Multiplicity(), False
        if t in RELATIONSHIP_KEYWORDS:
            return self.relationship_element(), False

        # FeaturePrefix / TypePrefix
        props: dict = {}
        is_end = False
        rels: list[Node] = []
        if t == "const" and k[i + 1] == "end":
            # EndFeaturePrefix : Feature = ( isConstant ?= 'const' { isVariable = true } )? isEnd ?= 'end'
            props.update(isConstant=True, isVariable=True, isEnd=True)
            self.p += 2
            is_end = True
        elif t == "end":
            props["isEnd"] = True
            self.p += 1
            is_end = True
        else:
            self.BasicFeaturePrefix(props)
        if is_end and k[self.p] not in FEATURE_KEYWORDS and k[self.p] != "#" \
                and (k[self.p] in DECLARATION_START or k[self.p] in DIRECTIONS):
            # ( EndFeaturePrefix ( ownedRelationship += OwnedCrossFeatureMember )? ...
            j = self.p
            decl = Node("Feature")
            self.BasicFeaturePrefix(decl.props)
            self.FeatureDeclaration(decl, required=True)
            if k[self.p] in FEATURE_KEYWORDS or k[self.p] == "#":
                self.fin(decl, j)
                rels.append(self.new("OwningMembership", j, {"ownedRelatedElement": [decl]}))
            else:
                # ... | EndFeaturePrefix FeatureDeclaration ) ValuePart? TypeBody
                node = Node("Feature", props)
                node.props.update(decl.props)
                self.ValuePart(node)
                self.TypeBody(node)
                return self.fin(node, i), True
        meta = self.prefix_metadata()
        t = k[self.p]
        if t in TYPE_KEYWORDS:
            extra = set(props) - {"isAbstract"}
            if extra or rels:
                raise ParseError(i, f"a {t} cannot have the feature prefix {self.describe(i)}")
            return self.type_element(i, props, meta), False
        if t in FEATURE_KEYWORDS:
            return self.feature_element(i, props, rels + meta), True
        if t in ("package", "namespace", "dependency", "@", "metadata"):
            if props or rels:
                raise ParseError(i, f"unexpected {self.describe(i)} before '{t}'")
            if t == "package":
                return self.Package(i, meta), False
            if t == "namespace":
                return self.Namespace(i, meta), False
            if t == "dependency":
                for m in meta:
                    m.type = "Annotation"
                return self.Dependency(i, meta), False
            return self.MetadataFeature(i, meta), False
        # Feature = ( FeaturePrefix ownedRelationship += PrefixMetadataMember FeatureDeclaration?
        #           | ( EndFeaturePrefix | BasicFeaturePrefix ) FeatureDeclaration ) ValuePart? TypeBody
        node = Node("Feature", props)
        rels += meta
        if rels:
            node.props["ownedRelationship"] = rels
        if not self.FeatureDeclaration(node, required=not meta) and not (props or meta):
            raise self.error("expected a member")
        self.ValuePart(node)
        self.TypeBody(node)
        return self.fin(node, i), True

    def BasicFeaturePrefix(self, props: dict) -> None:
        """BasicFeaturePrefix : Feature = ( direction = FeatureDirection )? ( isDerived ?= 'derived' )?
        ( isAbstract ?= 'abstract' )? ( isComposite ?= 'composite' | isPortion ?= 'portion' )?
        ( isVariable ?= 'var' | isConstant ?= 'const' { isVariable = true } )?"""
        k = self.k
        t = k[self.p]
        if t in DIRECTIONS:
            props["direction"] = t
            self.p += 1
            t = k[self.p]
        if t == "derived":
            props["isDerived"] = True
            self.p += 1
            t = k[self.p]
        if t == "abstract":
            props["isAbstract"] = True
            self.p += 1
            t = k[self.p]
        if t == "composite":
            props["isComposite"] = True
            self.p += 1
            t = k[self.p]
        elif t == "portion":
            props["isPortion"] = True
            self.p += 1
            t = k[self.p]
        if t == "var":
            props["isVariable"] = True
            self.p += 1
        elif t == "const":
            props["isConstant"] = True
            props["isVariable"] = True
            self.p += 1

    # -------------------------------------------------------------- types

    def type_element(self, i: int, props: dict, meta: list[Node]) -> Node:
        """Type = TypePrefix 'type' TypeDeclaration TypeBody, and the Classifier productions:
        Classifier, DataType, Class, Structure, Association, AssociationStructure, Behavior,
        Function, Predicate, Interaction, Metaclass = TypePrefix <keyword> ClassifierDeclaration
        TypeBody (FunctionBody for Function and Predicate)

        TypePrefix : Type = ( isAbstract ?= 'abstract' )? ( ownedRelationship += PrefixMetadataMember )*"""
        k = self.k
        t = k[self.p]
        self.p += 1
        type = TYPE_KEYWORDS[t]
        if t == "assoc" and k[self.p] == "struct":
            self.p += 1
            type = "AssociationStructure"
        node = Node(type, props)
        if meta:
            node.props["ownedRelationship"] = list(meta)
        if t == "type":
            self.TypeDeclaration(node)
        else:
            self.ClassifierDeclaration(node)
        if t in ("function", "predicate"):
            self.FunctionBody(node)
        else:
            self.TypeBody(node)
        return self.fin(node, i)

    def TypeDeclaration(self, node: Node) -> None:
        """TypeDeclaration : Type = ( isSufficient ?= 'all' )? Identification
        ( ownedRelationship += OwnedMultiplicity )? ( SpecializationPart | ConjugationPart )+
        TypeRelationshipPart*"""
        if self.accept("all"):
            node.props["isSufficient"] = True
        self.Identification(node)
        if self.k[self.p] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
        parts = 0
        while True:
            t = self.k[self.p]
            if t == ":>" or t == "specializes":
                self.SpecializationPart(node)
            elif t == "~" or t == "conjugates":
                self.ConjugationPart(node)
            else:
                break
            parts += 1
        if not parts:
            self.soft_error(self.p, "a type declaration needs ':>' (specializes) or '~' (conjugates)")
        while self.TypeRelationshipPart(node):
            pass

    def SpecializationPart(self, node: Node) -> None:
        """SpecializationPart : Type = SPECIALIZES ownedRelationship += OwnedSpecialization
        ( ',' ownedRelationship += OwnedSpecialization )*
        OwnedSpecialization : Specialization = GeneralType"""
        self.p += 1
        node.add("ownedRelationship", self.general("Specialization", "general"))
        while self.accept(","):
            node.add("ownedRelationship", self.general("Specialization", "general"))

    def ConjugationPart(self, node: Node) -> None:
        """ConjugationPart : Type = CONJUGATES ownedRelationship += OwnedConjugation
        OwnedConjugation : Conjugation = originalType = [QualifiedName]
        | originalType = FeatureChain { ownedRelatedElement += originalType }"""
        self.p += 1
        node.add("ownedRelationship", self.general("Conjugation", "originalType"))

    def TypeRelationshipPart(self, node: Node) -> bool:
        """TypeRelationshipPart : Type = DisjoiningPart | UnioningPart | IntersectingPart | DifferencingPart

        DisjoiningPart : Type = 'disjoint' 'from' ownedRelationship += OwnedDisjoining ( ',' ... )*
        UnioningPart : Type = 'unions' ownedRelationship += Unioning ( ',' ... )*
        IntersectingPart : Type = 'intersects' ownedRelationship += Intersecting ( ',' ... )*
        DifferencingPart : Type = 'differences' ownedRelationship += Differencing ( ',' ... )*"""
        t = self.k[self.p]
        if t == "disjoint":
            self.p += 1
            self.expect("from")
            type, prop = "Disjoining", "disjoiningType"
        elif t == "unions":
            self.p += 1
            type, prop = "Unioning", "unioningType"
        elif t == "intersects":
            self.p += 1
            type, prop = "Intersecting", "intersectingType"
        elif t == "differences":
            self.p += 1
            type, prop = "Differencing", "differencingType"
        else:
            return False
        node.add("ownedRelationship", self._type_relationship(type, prop))
        while self.accept(","):
            node.add("ownedRelationship", self._type_relationship(type, prop))
        return True

    def _type_relationship(self, type: str, prop: str) -> Node:
        """OwnedDisjoining : Disjoining = disjoiningType = [QualifiedName] | disjoiningType = FeatureChain
        { ownedRelatedElement += disjoiningType }
        Unioning = unioningType = [QualifiedName] | ownedRelatedElement += OwnedFeatureChain (Intersecting,
        Differencing alike)"""
        node = self.general(type, prop)
        if type != "Disjoining" and "ownedRelatedElement" in node.props:
            del node.props[prop]
        return node

    def ClassifierDeclaration(self, node: Node) -> None:
        """ClassifierDeclaration : Classifier = ( isSufficient ?= 'all' )? Identification
        ( ownedRelationship += OwnedMultiplicity )? ( SuperclassingPart | ConjugationPart )?
        TypeRelationshipPart*"""
        if self.accept("all"):
            node.props["isSufficient"] = True
        self.Identification(node)
        if self.k[self.p] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
        t = self.k[self.p]
        if t == ":>" or t == "specializes":
            self.SubclassificationPart(node)
        elif t == "~" or t == "conjugates":
            self.ConjugationPart(node)
        while self.TypeRelationshipPart(node):
            pass

    def TypeBody(self, node: Node) -> None:
        """TypeBody : Type = ';' | '{' TypeBodyElement* '}'"""
        if self.accept(";"):
            return
        self.expect("{")
        self.items(node, self.TypeBodyElement)

    def FunctionBody(self, node: Node) -> None:
        """FunctionBody : Type = ';' | '{' FunctionBodyPart '}'"""
        if self.accept(";"):
            return
        self.expect("{")
        self.FunctionBodyPart(node)

    def FunctionBodyPart(self, node: Node) -> None:
        """FunctionBodyPart : Type = ( TypeBodyElement | ownedRelationship += ReturnFeatureMember )*
        ( ownedRelationship += ResultExpressionMember )?   (and the closing '}')"""
        self.items(node, self._function_item)

    def _function_item(self, node: Node) -> None:
        if not self.result_expression(node):
            self.member(node, "function")

    # ----------------------------------------------------------- features

    def FeatureDeclaration(self, node: Node, required: bool = False) -> bool:
        """FeatureDeclaration : Feature = ( isSufficient ?= 'all' )?
        ( FeatureIdentification ( FeatureSpecializationPart | ConjugationPart )?
        | FeatureSpecializationPart | ConjugationPart ) FeatureRelationshipPart*

        FeatureIdentification : Feature = '<' declaredShortName = NAME '>' ( declaredName = NAME )?
        | declaredName = NAME"""
        k = self.k
        start = self.p
        if k[self.p] == "all":
            self.p += 1
            node.props["isSufficient"] = True
        t = k[self.p]
        if t == "<" or t == "NAME":
            self.Identification(node)
            t = k[self.p]
            if t == "~" or t == "conjugates":
                self.ConjugationPart(node)
            else:
                self.FeatureSpecializationPart(node)
        elif t == "~" or t == "conjugates":
            self.ConjugationPart(node)
        elif not self.FeatureSpecializationPart(node):
            if self.p > start or required:
                raise self.error("expected a feature declaration")
            return False
        while self.FeatureRelationshipPart(node):
            pass
        return True

    def FeatureRelationshipPart(self, node: Node) -> bool:
        """FeatureRelationshipPart : Feature = TypeRelationshipPart | ChainingPart | InvertingPart
        | TypeFeaturingPart

        ChainingPart : Feature = 'chains' ( ownedRelationship += OwnedFeatureChaining | FeatureChain )
        InvertingPart : Feature = 'inverse' 'of' ownedRelationship += OwnedFeatureInverting
        TypeFeaturingPart : Feature = 'featured' 'by' ownedRelationship += OwnedTypeFeaturing
        ( ',' ownedTypeFeaturing += OwnedTypeFeaturing )*"""
        t = self.k[self.p]
        if t == "chains":
            self.p += 1
            node.add("ownedRelationship", self.OwnedFeatureChaining())
            while self.k[self.p] == "." and self.scan_qn(self.p + 1) > 0:
                self.p += 1
                node.add("ownedRelationship", self.OwnedFeatureChaining())
            return True
        if t == "inverse":
            self.p += 1
            self.expect("of")
            node.add("ownedRelationship", self.general("FeatureInverting", "invertingFeature"))
            return True
        if t == "featured":
            self.p += 1
            self.expect("by")
            node.add("ownedRelationship", self.OwnedTypeFeaturing())
            while self.accept(","):
                node.add("ownedRelationship", self.OwnedTypeFeaturing())
            return True
        return self.TypeRelationshipPart(node)

    def OwnedTypeFeaturing(self) -> Node:
        """OwnedTypeFeaturing : TypeFeaturing = featuringType = [QualifiedName]"""
        ref = self.QualifiedName()
        return Node("TypeFeaturing", {"featuringType": ref}, ref.span)

    def feature_element(self, i: int, props: dict, rels: list[Node]) -> Node:
        """FeatureElement : Feature = Feature | Step | Expression | BooleanExpression | Invariant
        | Connector | BindingConnector | Succession | Flow | SuccessionFlow   (after FeaturePrefix)"""
        k = self.k
        t = k[self.p]
        self.p += 1
        if t == "succession" and k[self.p] == "flow":
            self.p += 1
            t = "succession flow"
        type = {"feature": "Feature", "step": "Step", "expr": "Expression", "bool": "BooleanExpression",
                "inv": "Invariant", "connector": "Connector", "binding": "BindingConnector",
                "succession": "Succession", "flow": "Flow", "succession flow": "SuccessionFlow"}[t]
        node = Node(type, props)
        if rels:
            node.props["ownedRelationship"] = rels
        if t == "feature":
            # Feature = FeaturePrefix 'feature' FeatureDeclaration? ValuePart? TypeBody
            self.FeatureDeclaration(node)
            self.ValuePart(node)
            self.TypeBody(node)
        elif t == "step":
            # Step = FeaturePrefix 'step' FeatureDeclaration ValuePart? TypeBody
            if not self.FeatureDeclaration(node):
                self.soft_error(self.p, "expected a feature declaration after 'step'")
            self.ValuePart(node)
            self.TypeBody(node)
        elif t in ("expr", "bool", "inv"):
            # Expression = FeaturePrefix 'expr' FeatureDeclaration ValuePart? FunctionBody
            # Invariant = FeaturePrefix 'inv' ( 'true' | isNegated ?= 'false' )? FeatureDeclaration
            # ValuePart? FunctionBody   (the corpus omits the declaration of an inv: GRAMMAR_NOTES.md)
            if t == "inv":
                if self.accept("false"):
                    node.props["isNegated"] = True
                else:
                    self.accept("true")
            if not self.FeatureDeclaration(node) and t != "inv":
                self.soft_error(self.p, f"expected a feature declaration after '{t}'")
            self.ValuePart(node)
            self.FunctionBody(node)
        elif t == "connector":
            self.ConnectorDeclaration(node)
            self.TypeBody(node)
        elif t == "binding":
            self.BindingConnectorDeclaration(node)
            self.TypeBody(node)
        elif t == "succession":
            self.SuccessionDeclaration(node)
            self.TypeBody(node)
        else:
            self.FlowDeclaration(node)
            self.TypeBody(node)
        return self.fin(node, i)

    def ConnectorDeclaration(self, node: Node) -> None:
        """Connector = FeaturePrefix 'connector' ( FeatureDeclaration? ValuePart? | ConnectorDeclaration ) TypeBody

        BinaryConnectorDeclaration : Connector = ( FeatureDeclaration? 'from' | isSufficient ?= 'all' 'from'? )?
        ownedRelationship += ConnectorEndMember 'to' ownedRelationship += ConnectorEndMember
        NaryConnectorDeclaration : Connector = FeatureDeclaration? '(' ownedRelationship += ConnectorEndMember
        ',' ownedRelationship += ConnectorEndMember ( ',' ownedRelationship += ConnectorEndMember )* ')'"""
        k = self.k
        if k[self.p] == "all" and k[self.p + 1] in ("from", "[", "NAME", "$"):
            ends = self.attempt(self._binary_ends, True)
            if ends:
                node.props["isSufficient"] = True
                node.props.setdefault("ownedRelationship", []).extend(ends)
                return
        if k[self.p] not in ("from", "("):
            ends = self.attempt(self._binary_ends, False)
            if ends:
                node.props.setdefault("ownedRelationship", []).extend(ends)
                return
            self.FeatureDeclaration(node)
        if self.accept("from"):
            node.props.setdefault("ownedRelationship", []).extend(self._binary_ends(False))
        elif k[self.p] == "(":
            self._nary_ends(node)
        else:
            self.ValuePart(node)

    def _binary_ends(self, sufficient: bool) -> list[Node]:
        if sufficient:
            self.expect("all")
            self.accept("from")
        first = self.ConnectorEndMember()
        self.expect("to")
        return [first, self.ConnectorEndMember()]

    def _nary_ends(self, node: Node) -> None:
        self.expect("(")
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.expect(",")
        node.add("ownedRelationship", self.ConnectorEndMember())
        while self.accept(","):
            node.add("ownedRelationship", self.ConnectorEndMember())
        self.expect(")")

    def _two_ends(self, node: Node, first_kw: str | None, sep: str) -> bool:
        """( first_kw? ConnectorEndMember sep ConnectorEndMember ) speculatively."""
        def ends():
            if first_kw:
                self.accept(first_kw)
            a = self.ConnectorEndMember()
            self.expect(sep)
            return [a, self.ConnectorEndMember()]
        got = self.attempt(ends)
        if got:
            node.props.setdefault("ownedRelationship", []).extend(got)
            return True
        return False

    def BindingConnectorDeclaration(self, node: Node) -> None:
        """BindingConnectorDeclaration : BindingConnector = FeatureDeclaration
        ( 'of' ownedRelationship += ConnectorEndMember '=' ownedRelationship += ConnectorEndMember )?
        | ( isSufficient ?= 'all' )? ( 'of'? ownedRelationship += ConnectorEndMember
        '=' ownedRelationship += ConnectorEndMember )?"""
        self._declaration_with_ends(node, "of", "=")

    def SuccessionDeclaration(self, node: Node) -> None:
        """SuccessionDeclaration : Succession = FeatureDeclaration
        ( 'first' ownedRelationship += ConnectorEndMember 'then' ownedRelationship += ConnectorEndMember )?
        | ( isSufficient ?= 'all' )? ( 'first'? ownedRelationship += ConnectorEndMember
        'then' ownedRelationship += ConnectorEndMember )?"""
        self._declaration_with_ends(node, "first", "then")

    def _declaration_with_ends(self, node: Node, kw: str, sep: str) -> None:
        k = self.k
        if k[self.p] == "all":
            self.p += 1
            node.props["isSufficient"] = True
            if k[self.p] not in (";", "{"):
                self._ends(node, kw, sep, optional_kw=True)
            return
        if k[self.p] == kw:
            self._ends(node, kw, sep, optional_kw=True)
            return
        if self._two_ends(node, None, sep):
            return
        if self.FeatureDeclaration(node) and k[self.p] == kw:
            self._ends(node, kw, sep, optional_kw=False)

    def _ends(self, node: Node, kw: str, sep: str, optional_kw: bool) -> None:
        if optional_kw:
            self.accept(kw)
        else:
            self.expect(kw)
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.expect(sep)
        node.add("ownedRelationship", self.ConnectorEndMember())

    def FlowDeclaration(self, node: Node) -> None:
        """FlowDeclaration : Flow = FeatureDeclaration ValuePart?
        ( 'of' ownedRelationship += PayloadFeatureMember )?
        ( 'from' ownedRelationship += FlowEndMember 'to' ownedRelationship += FlowEndMember )?
        | ( isSufficient ?= 'all' )? ownedRelationship += FlowEndMember 'to' ownedRelationship += FlowEndMember"""
        k = self.k
        if k[self.p] == "all":
            self.p += 1
            node.props["isSufficient"] = True
            self._flow_ends(node)
            return
        got = self.attempt(self._flow_ends_list)
        if got:
            node.props.setdefault("ownedRelationship", []).extend(got)
            return
        self.FeatureDeclaration(node)
        self.ValuePart(node)
        if self.accept("of"):
            node.add("ownedRelationship", self.PayloadFeatureMember())
        if self.accept("from"):
            self._flow_ends(node)

    def PayloadFeatureMember(self) -> Node:
        """PayloadFeatureMember : FeatureMembership = ownedRelatedElement = PayloadFeature"""
        feature = self.PayloadFeature()
        return Node("FeatureMembership", {"ownedRelatedElement": [feature]}, feature.span)

    def PayloadFeature(self, node: Node | None = None) -> Node:
        """PayloadFeature = Identification PayloadFeatureSpecializationPart ValuePart?
        | Identification ValuePart | ownedRelationship += OwnedFeatureTyping
        ( ownedRelationship += OwnedMultiplicity )? | ownedRelationship += OwnedMultiplicity
        ownedRelationship += OwnedFeatureTyping"""
        k = self.k
        i = self.p
        node = Node("PayloadFeature") if node is None else node
        if k[i] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
            if k[self.p] in SPECIALIZATION_TOKENS or k[self.p] in ("ordered", "nonunique"):
                self.FeatureSpecializationPart(node)
            else:
                node.add("ownedRelationship", self.OwnedFeatureTyping())
            return self.fin(node, i)
        if self._payload_has_identification(i):
            self.Identification(node)
            self.FeatureSpecializationPart(node)
            self.ValuePart(node)
            return self.fin(node, i)
        node.add("ownedRelationship", self.OwnedFeatureTyping())
        if k[self.p] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
        return self.fin(node, i)

    # --------------------------------------------------- annotating elements

    def MetadataFeature(self, i: int | None = None, meta: list[Node] | None = None) -> Node:
        """MetadataFeature = ( ownedRelationship += PrefixMetadataMember )* ( '@' | 'metadata' )
        MetadataFeatureDeclaration ( 'about' ownedRelationship += Annotation
        ( ',' ownedRelationship += Annotation )* )? MetadataBody

        MetadataFeatureDeclaration : MetadataFeature = ( Identification ( ':' | 'typed' 'by' ) )?
        ownedRelationship += OwnedFeatureTyping"""
        if i is None:
            i = self.p
            meta = self.prefix_metadata()
        node = Node(self.METADATA_FEATURE, {"ownedRelationship": list(meta)} if meta else {})
        if self.k[self.p] not in ("@", "metadata"):
            raise self.error("expected '@' or 'metadata'")
        self.p += 1
        self.MetadataFeatureDeclaration(node)
        if self.accept("about"):
            node.add("ownedRelationship", self.Annotation())
            while self.accept(","):
                node.add("ownedRelationship", self.Annotation())
        self.MetadataBody(node)
        return self.fin(node, i)

    def MetadataBody(self, node: Node) -> None:
        """MetadataBody : Feature = ';' | '{' ( ownedRelationship += MetadataBodyElement )* '}'"""
        if self.accept(";"):
            return
        self.expect("{")
        self.items(node, self.MetadataBodyElement)

    def MetadataBodyElement(self, node: Node) -> None:
        """MetadataBodyElement : Membership = NonFeatureMember | MetadataBodyFeatureMember | AliasMember | Import

        MetadataBodyFeatureMember : FeatureMembership = ownedMemberFeature = MetadataBodyFeature"""
        k = self.k
        i = self.p
        t = k[i]
        if t in ("public", "private", "protected"):
            t = k[i + 1]
        if t in ("feature", ":>>", "redefines", "NAME"):
            feature = self.MetadataBodyFeature()
            node.add("ownedRelationship", self.new("FeatureMembership", i, {"ownedRelatedElement": [feature]}))
        else:
            self.member(node, "namespace")

    def MetadataBodyFeature(self) -> Node:
        """MetadataBodyFeature : Feature = 'feature'? ( ':>>' | 'redefines' )?
        ownedRelationship += OwnedRedefinition FeatureSpecializationPart? ValuePart? MetadataBody"""
        i = self.p
        node = Node("Feature")
        self.accept("feature")
        if not self.accept(":>>"):
            self.accept("redefines")
        node.add("ownedRelationship", self.OwnedRedefinition())
        self.FeatureSpecializationPart(node)
        self.ValuePart(node)
        self.MetadataBody(node)
        return self.fin(node, i)

    # ----------------------------------------------- namespaces and packages

    def Namespace(self, i: int, meta: list[Node]) -> Node:
        """Namespace = ( ownedRelationship += PrefixMetadataMember )* NamespaceDeclaration NamespaceBody
        NamespaceDeclaration : Namespace = 'namespace' Identification
        NamespaceBody : Namespace = ';' | '{' NamespaceBodyElement* '}'"""
        node = Node("Namespace", {"ownedRelationship": list(meta)} if meta else {})
        self.expect("namespace")
        self.Identification(node)
        if not self.accept(";"):
            self.expect("{")
            self.items(node, self.NamespaceBodyElement)
        return self.fin(node, i)

    def Package(self, i: int, meta: list[Node], type: str = "Package") -> Node:
        """Package = ( ownedRelationship += PrefixMetadataMember )* PackageDeclaration PackageBody
        PackageDeclaration : Package = 'package' Identification
        PackageBody : Package = ';' | '{' ( NamespaceBodyElement | ownedRelationship += ElementFilterMember )* '}'"""
        node = Node(type, {"ownedRelationship": list(meta)} if meta else {})
        self.expect("package")
        self.Identification(node)
        if not self.accept(";"):
            self.expect("{")
            self.items(node, self.PackageBodyElement)
        return self.fin(node, i)

    def LibraryPackage(self) -> Node:
        """LibraryPackage = ( isStandard ?= 'standard' ) 'library'
        ( ownedRelationship += PrefixMetadataMember )* PackageDeclaration PackageBody"""
        i = self.p
        std = self.accept("standard")
        self.expect("library")
        meta = self.prefix_metadata()
        node = self.Package(i, meta, "LibraryPackage")
        if std:
            node.props["isStandard"] = True
        return node

    # ------------------------------------------- relationships as elements

    def Multiplicity(self) -> Node:
        """Multiplicity = MultiplicitySubset | MultiplicityRange
        MultiplicitySubset : Multiplicity = 'multiplicity' Identification Subsets TypeBody
        MultiplicityRange = 'multiplicity' Identification MultiplicityBounds TypeBody"""
        i = self.expect("multiplicity")
        node = Node("Multiplicity")
        self.Identification(node)
        t = self.k[self.p]
        if t == ":>" or t == "subsets":
            self.p += 1
            node.add("ownedRelationship", self.OwnedSubsetting())
        elif t == "[":
            node.type = "MultiplicityRange"
            self.MultiplicityBounds(node)
        else:
            raise self.error("expected ':>', 'subsets' or '['")
        self.TypeBody(node)
        return self.fin(node, i)

    def _type_or_chain(self, node: Node, prop: str) -> None:
        """SpecificType : Specialization = specific = [QualifiedName]
        | specific += OwnedFeatureChain { ownedRelatedElement += specific }
        (and GeneralType alike), assigning ``prop``: GRAMMAR_NOTES.md section 5"""
        i = self.p
        ref = self.QualifiedName()
        if self.k[self.p] == "." and self.scan_qn(self.p + 1) > 0:
            chain = self.FeatureChain(i)
            node.props[prop] = chain
            node.add("ownedRelatedElement", chain)
        else:
            node.props[prop] = ref

    def relationship_element(self) -> Node:
        """Specialization, Subclassification, FeatureTyping, Subsetting, Redefinition, Conjugation,
        Disjoining, FeatureInverting and TypeFeaturing written as members.

        Specialization = ( 'specialization' Identification )? 'subtype' SpecificType SPECIALIZES
        GeneralType RelationshipBody (and 'subclassifier', 'typing', 'subset', 'redefinition' alike)"""
        k = self.k
        i = self.p
        t = k[i]
        node = Node("Specialization")
        if t == "specialization":
            self.p += 1
            self.Identification(node)
            t = k[self.p]
            if t not in ("subtype", "subclassifier", "typing", "subset", "redefinition"):
                raise self.error("expected 'subtype', 'subclassifier', 'typing', 'subset' or 'redefinition'")
        elif t in ("conjugation", "disjoining", "inverting"):
            self.p += 1
            self.Identification(node)
            t = {"conjugation": "conjugate", "disjoining": "disjoint", "inverting": "inverse"}[t]
            if k[self.p] != t:
                raise self.error(f"expected '{t}'")
        self.p += 1
        if t == "subtype":
            # Specialization
            self._type_or_chain(node, "specific")
            if not self.accept(":>"):
                self.expect("specializes")
            self._type_or_chain(node, "general")
        elif t == "subclassifier":
            # Subclassification = ... 'subclassifier' subclassifier = [QualifiedName]
            # SPECIALIZES superclassifier = [QualifiedName] RelationshipBody
            node.type = "Subclassification"
            node.props["subclassifier"] = self.QualifiedName()
            if not self.accept(":>"):
                self.expect("specializes")
            node.props["superclassifier"] = self.QualifiedName()
        elif t == "typing":
            # FeatureTyping = ... 'typing' typedFeature = [QualifiedName] TYPED_BY GeneralType RelationshipBody
            node.type = "FeatureTyping"
            node.props["typedFeature"] = self.QualifiedName()
            if not self.typed_by():
                raise self.error("expected ':' or 'typed by'")
            self._type_or_chain(node, "type")
        elif t == "subset":
            # Subsetting = ... 'subset' SpecificType SUBSETS GeneralType RelationshipBody
            node.type = "Subsetting"
            self._type_or_chain(node, "subsettingFeature")
            if not self.accept(":>"):
                self.expect("subsets")
            self._type_or_chain(node, "subsettedFeature")
        elif t == "redefinition":
            # Redefinition = ... 'redefinition' SpecificType REDEFINES GeneralType RelationshipBody
            node.type = "Redefinition"
            self._type_or_chain(node, "redefiningFeature")
            if not self.accept(":>>"):
                self.expect("redefines")
            self._type_or_chain(node, "redefinedFeature")
        elif t == "conjugate":
            # Conjugation = ( 'conjugation' Identification )? 'conjugate' ( conjugatedType = [QualifiedName]
            # | conjugatedType = FeatureChain ) CONJUGATES ( originalType = ... ) RelationshipBody
            node.type = "Conjugation"
            self._type_or_chain(node, "conjugatedType")
            if not self.accept("~"):
                self.expect("conjugates")
            self._type_or_chain(node, "originalType")
        elif t == "disjoint":
            # Disjoining = ( 'disjoining' Identification )? 'disjoint' typeDisjoined 'from' disjoiningType
            node.type = "Disjoining"
            self._type_or_chain(node, "typeDisjoined")
            self.expect("from")
            self._type_or_chain(node, "disjoiningType")
        elif t == "inverse":
            # FeatureInverting = ( 'inverting' Identification? )? 'inverse' featureInverted 'of' invertingFeature
            node.type = "FeatureInverting"
            self._type_or_chain(node, "featureInverted")
            self.expect("of")
            self._type_or_chain(node, "invertingFeature")
        elif t == "featuring":
            # TypeFeaturing = 'featuring' ( Identification 'of' )? featureOfType = [QualifiedName]
            # 'by' featuringType = [QualifiedName] RelationshipBody
            node.type = "TypeFeaturing"
            if k[self.p] == "<" or (k[self.p] == "NAME" and k[self.p + 1] == "of"):
                self.Identification(node)
                self.expect("of")
            node.props["featureOfType"] = self.QualifiedName()
            self.expect("by")
            node.props["featuringType"] = self.QualifiedName()
        else:  # pragma: no cover - guarded by RELATIONSHIP_KEYWORDS
            raise self.error("expected a relationship")
        self.RelationshipBody(node)
        return self.fin(node, i)

    def RelationshipOwnedElement(self, node: Node) -> None:
        """RelationshipOwnedElement : Relationship = ownedRelatedElement += OwnedRelatedElement
        | ownedRelationship += OwnedAnnotation
        OwnedRelatedElement : Element = NonFeatureElement | FeatureElement"""
        t = self.k[self.p]
        if t in ("comment", "COMMENT", "locale", "doc", "rep", "language", "@", "metadata"):
            node.add("ownedRelationship", self.OwnedAnnotation())
        else:
            el, _ = self.element()
            node.add("ownedRelatedElement", el)
