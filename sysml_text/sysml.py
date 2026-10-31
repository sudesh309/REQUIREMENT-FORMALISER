"""SysML textual notation (SysML 2.0, 8.2.2): ``SysML-textual-bnf.kebnf``.

Expressions and the Kernel productions the grammar takes from KerML
(connector ends, flow ends, multiplicities, feature values) come from the
base classes. Body items are parsed by one dispatcher, :meth:`SysMLParser.body_item`,
for every kind of body (package, definition, interface, action, calculation,
state, requirement, case, view, enumeration, metadata); the context decides
which items are allowed and which memberships own them.
"""
from __future__ import annotations

from ._base import DIRECTIONS, MULTIPLICITY_TOKENS, SPECIALIZATION_TOKENS, ParseError
from .ast import Node
from .expressions import EXPRESSION_START, ExpressionParser, _wrap

# kind keyword -> (Definition metaclass, body context)
DEFINITIONS = {
    "attribute": ("AttributeDefinition", "definition"), "enum": ("EnumerationDefinition", "enum"),
    "occurrence": ("OccurrenceDefinition", "definition"), "item": ("ItemDefinition", "definition"),
    "part": ("PartDefinition", "definition"), "connection": ("ConnectionDefinition", "definition"),
    "flow": ("FlowDefinition", "definition"), "interface": ("InterfaceDefinition", "interface"),
    "allocation": ("AllocationDefinition", "definition"), "port": ("PortDefinition", "definition"),
    "action": ("ActionDefinition", "action"), "calc": ("CalculationDefinition", "calc"),
    "state": ("StateDefinition", "state"), "constraint": ("ConstraintDefinition", "calc"),
    "requirement": ("RequirementDefinition", "requirement"), "concern": ("ConcernDefinition", "requirement"),
    "case": ("CaseDefinition", "case"), "analysis": ("AnalysisCaseDefinition", "case"),
    "verification": ("VerificationCaseDefinition", "case"), "use": ("UseCaseDefinition", "case"),
    "view": ("ViewDefinition", "viewdef"), "viewpoint": ("ViewpointDefinition", "requirement"),
    "rendering": ("RenderingDefinition", "definition"), "metadata": ("MetadataDefinition", "definition"),
}

# Usages written <keyword> Usage
SIMPLE_USAGES = {"attribute": "AttributeUsage", "enum": "EnumerationUsage", "occurrence": "OccurrenceUsage",
                 "item": "ItemUsage", "part": "PartUsage", "port": "PortUsage", "rendering": "RenderingUsage"}
# Usages written <keyword> ConstraintUsageDeclaration <body>
CONSTRAINT_USAGES = {"constraint": ("ConstraintUsage", "calc"), "requirement": ("RequirementUsage", "requirement"),
                     "concern": ("ConcernUsage", "requirement"), "viewpoint": ("ViewpointUsage", "requirement"),
                     "case": ("CaseUsage", "case"), "analysis": ("AnalysisCaseUsage", "case"),
                     "verification": ("VerificationCaseUsage", "case")}
ACTION_NODES = frozenset(("accept", "send", "assign", "terminate", "if", "while", "loop", "for"))
CONTROL_NODES = {"merge": "MergeNode", "decide": "DecisionNode", "join": "JoinNode", "fork": "ForkNode"}

#: keywords that start the kind of a usage (after its prefix)
USAGE_KEYWORDS = frozenset(SIMPLE_USAGES) | frozenset(CONSTRAINT_USAGES) | ACTION_NODES | frozenset(CONTROL_NODES) | {
    "event", "connection", "connect", "interface", "allocation", "allocate", "flow", "message", "succession",
    "binding", "bind", "first", "action", "calc", "state", "use", "view", "perform", "exhibit", "include",
    "assert", "satisfy", "metadata", "@", "transition", "ref"}
#: tokens that may start a UsageDeclaration or a usage's value
DECLARATION_START = SPECIALIZATION_TOKENS | MULTIPLICITY_TOKENS | {"NAME", "<", "specializes"}

ACTION_CONTEXTS = frozenset(("action", "calc", "case"))
RESULT_CONTEXTS = frozenset(("calc", "case"))


class SysMLParser(ExpressionParser):
    """Parser for ``.sysml`` text."""

    LANGUAGE = "sysml"
    TYPED_BY = "defined"
    ARGUMENT_EXPRESSION_MEMBERSHIP = "ParameterMembership"
    METADATA_FEATURE = "MetadataUsage"
    CONNECTOR_END = "ReferenceUsage"
    FLOW_FEATURE = "ReferenceUsage"

    def __init__(self, text: str, path: str | None = None):
        super().__init__(text, path)
        self._entry_members: set[int] = set()

    def root_item(self, node: Node) -> None:
        self.body_item(node, "package")

    # ------------------------------------------------------------- bodies

    def body(self, node: Node, ctx: str) -> None:
        """';' | '{' <ctx>BodyItem* '}'"""
        if self.accept(";"):
            return
        self.expect("{")
        self.items(node, lambda n: self.body_item(n, ctx))

    def PackageBody(self, node: Node) -> None:
        """PackageBody : Package = ';' | '{' PackageBodyElement* '}'"""
        self.body(node, "package")

    def DefinitionBody(self, node: Node) -> None:
        """DefinitionBody : Type = ';' | '{' DefinitionBodyItem* '}'"""
        self.body(node, "definition")

    UsageBody = DefinitionBody

    def ActionBody(self, node: Node) -> None:
        """ActionBody : Type = ';' | '{' ActionBodyItem* '}'"""
        self.body(node, "action")

    def CalculationBody(self, node: Node) -> None:
        """CalculationBody : Type = ';' | '{' CalculationBodyPart '}'
        CalculationBodyPart : Type = CalculationBodyItem* ( ownedRelationship += ResultExpressionMember )?"""
        self.body(node, "calc")

    def CaseBody(self, node: Node) -> None:
        """CaseBody : Type = ';' | '{' CaseBodyItem* ( ownedRelationship += ResultExpressionMember )? '}'"""
        self.body(node, "case")

    def RequirementBody(self, node: Node) -> None:
        """RequirementBody : Type = ';' | '{' RequirementBodyItem* '}'"""
        self.body(node, "requirement")

    def StateBody(self, node: Node) -> None:
        """StateDefBody : StateDefinition = ';' | ( isParallel ?= 'parallel' )? '{' StateBodyItem* '}'
        StateUsageBody : StateUsage = ';' | ( isParallel ?= 'parallel' )? '{' StateBodyItem* '}'"""
        if self.accept("parallel"):
            node.props["isParallel"] = True
            self.expect("{")
            self.items(node, lambda n: self.body_item(n, "state"))
        else:
            self.body(node, "state")

    def InterfaceBody(self, node: Node) -> None:
        """InterfaceBody : Type = ';' | '{' InterfaceBodyItem* '}'"""
        self.body(node, "interface")

    def FunctionBodyPart(self, node: Node) -> None:
        """ExpressionBody : Expression = '{' FunctionBodyPart '}': in SysML the body of an
        expression is a CalculationBodyPart (GRAMMAR_NOTES.md)."""
        self.items(node, lambda n: self.body_item(n, "calc"))

    # ---------------------------------------------------------- body items

    def body_item(self, node: Node, ctx: str) -> None:
        """One item of a body; ``ctx`` names the body production:

        PackageBodyElement : Package = ownedRelationship += PackageMember | ElementFilterMember | AliasMember | Import
        DefinitionBodyItem : Type = ownedRelationship += DefinitionMember | VariantUsageMember
        | NonOccurrenceUsageMember | ( SourceSuccessionMember )? OccurrenceUsageMember | AliasMember | Import
        ActionBodyItem, CalculationBodyItem, StateBodyItem, RequirementBodyItem, CaseBodyItem,
        InterfaceBodyItem, ViewDefinitionBodyItem, ViewBodyItem, EnumerationBody, MetadataBody: see the
        dispatch below."""
        k = self.k
        if ctx in RESULT_CONTEXTS and self.result_expression(node):
            return
        if ctx == "enum":
            self.enum_item(node)
            return
        if ctx == "metadata":
            self.metadata_item(node)
            return
        i = self.p
        vis = self.VisibilityIndicator()
        t = k[self.p]
        add = node.add
        if t == "import":
            add("ownedRelationship", self.Import(i, vis))
            return
        if t == "alias":
            m = self.membership("Membership", vis)
            self.AliasMember(m)
            add("ownedRelationship", self.fin(m, i))
            return
        if t == "filter" and ctx in ("package", "viewdef", "view"):
            m = self.membership("ElementFilterMembership", vis)
            self.ElementFilterMember(m)
            add("ownedRelationship", self.fin(m, i))
            return
        if t == "expose" and ctx == "view":
            add("ownedRelationship", self.Import(i, vis, expose=True))
            return
        if ctx != "package":
            member = self.special_member(i, vis, t, ctx, node)
            if member is not None:
                add("ownedRelationship", member)
                return
        el, is_usage = self.element(ctx)
        mtype = "FeatureMembership" if is_usage and ctx != "package" else "OwningMembership"
        m = self.new(mtype, i, {"ownedRelatedElement": [el]})
        if vis:
            m.props["visibility"] = vis
        add("ownedRelationship", m)

    def membership(self, type: str, vis: str | None) -> Node:
        return Node(type, {"visibility": vis} if vis else {})

    def special_member(self, i: int, vis: str | None, t: str, ctx: str, node: Node) -> Node | None:
        """Body items introduced by their own keyword (memberships other than owning and feature
        memberships, successions and transitions); None when the item is an ordinary element."""
        k = self.k
        mtype = None
        if t == "variant":
            # VariantUsageMember : VariantMembership = MemberPrefix 'variant' ownedVariantUsage = VariantUsageElement
            self.p += 1
            el = self.VariantUsageElement(ctx)
            mtype = "VariantMembership"
        elif t == "render" and ctx in ("viewdef", "view"):
            self.p += 1
            el = self.ViewRenderingUsage()
            mtype = "ViewRenderingMembership"
        elif t == "return" and ctx in ("calc", "case"):
            # ReturnParameterMember : ReturnParameterMembership = MemberPrefix? 'return' ownedRelatedElement += UsageElement
            self.p += 1
            el, _ = self.element(ctx)
            mtype = "ReturnParameterMembership"
        elif ctx in ("requirement", "case") and t in ("subject", "actor", "objective", "stakeholder", "assume",
                                                       "require", "frame", "verify"):
            return self.requirement_member(i, vis, t, ctx)
        elif ctx == "state" and t in ("entry", "do", "exit"):
            # EntryActionMember : StateSubactionMembership = MemberPrefix kind = 'entry'
            # ownedRelatedElement += StateActionUsage (DoActionMember, ExitActionMember alike)
            self.p += 1
            el = self.StateActionUsage()
            m = self.new("StateSubactionMembership", i, {"kind": t, "ownedRelatedElement": [el]})
            if vis:
                m.props["visibility"] = vis
            if t == "entry":
                self._entry_members.add(id(m))
            return m
        elif ctx == "state" and t in ("then", "accept", "if", "transition"):
            return self.state_transition_member(i, vis, t, node)
        elif t == "then":
            return self.then_member(i, vis, ctx)
        elif ctx in ACTION_CONTEXTS and t in ("first", "if", "else"):
            return self.action_succession_member(i, vis, t, ctx)
        else:
            return None
        m = self.new(mtype, i, {"ownedRelatedElement": [el]})
        if vis:
            m.props["visibility"] = vis
        return m

    # ------------------------------------------------------------ elements

    def element(self, ctx: str) -> tuple[Node, bool]:
        """DefinitionElement | UsageElement, with their prefixes. Returns (element, is a usage).

        DefinitionPrefix : Definition = BasicDefinitionPrefix? DefinitionExtensionKeyword*
        OccurrenceDefinitionPrefix : OccurrenceDefinition = BasicDefinitionPrefix?
        ( isIndividual ?= 'individual' ownedRelationship += EmptyMultiplicityMember )? DefinitionExtensionKeyword*
        UsagePrefix : Usage = UnextendedUsagePrefix UsageExtensionKeyword*
        OccurrenceUsagePrefix : OccurrenceUsage = BasicUsagePrefix ( isIndividual ?= 'individual' )?
        ( portionKind = PortionKind { isPortion = true } )? UsageExtensionKeyword*"""
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
        props: dict = {}
        rels: list[Node] = []
        if t == "end":
            # EndUsagePrefix : Usage = isEnd ?= 'end' ( ownedRelationship += OwnedCrossFeatureMember )?
            self.p += 1
            props["isEnd"] = True
            t = k[self.p]
            if t not in USAGE_KEYWORDS and t != "#" and (t in DECLARATION_START or t in DIRECTIONS):
                j = self.p
                decl = Node("ReferenceUsage")
                self.BasicUsagePrefix(decl.props)
                self.UsageDeclaration(decl)
                if k[self.p] in USAGE_KEYWORDS or k[self.p] == "#":
                    # OwnedCrossFeatureMember : OwningMembership = ownedRelatedElement += OwnedCrossFeature
                    self.fin(decl, j)
                    rels.append(self.new("OwningMembership", j, {"ownedRelatedElement": [decl]}))
                else:
                    # An end feature without a usage keyword (GRAMMAR_NOTES.md):
                    # DefaultInterfaceEnd : PortUsage = isEnd ?= 'end' Usage in interfaces, else a ReferenceUsage
                    node = Node("PortUsage" if ctx == "interface" else "ReferenceUsage", props)
                    node.props.update(decl.props)
                    self.UsageCompletion(node)
                    return self.fin(node, i), True
        else:
            self.RefPrefix(props)
        is_ref = False
        if k[self.p] == "ref":
            # BasicUsagePrefix : Usage = RefPrefix ( isReference ?= 'ref' )?
            self.p += 1
            is_ref = True
        if k[self.p] == "individual":
            self.p += 1
            props["isIndividual"] = True
            if k[self.p] == "def" or (k[self.p] in DEFINITIONS and k[self.p + 1] == "def") or k[self.p] == "#":
                rels.append(self.EmptyMultiplicityMember())
        if k[self.p] in ("snapshot", "timeslice"):
            props["portionKind"] = k[self.p]
            props["isPortion"] = True
            self.p += 1
        meta = self.prefix_metadata()
        rels += meta
        t = k[self.p]
        if t == "def" or (t in DEFINITIONS and k[self.p + 1] == "def") or (
                t == "use" and k[self.p + 1] == "case" and k[self.p + 2] == "def"):
            bad = set(props) - {"isAbstract", "isVariation", "isIndividual"}
            if bad or is_ref:
                raise ParseError(i, f"a definition cannot have the usage prefix {self.describe(i)}")
            return self.definition(i, props, rels), False
        if t in ("package", "dependency", "@", "metadata"):
            if props or is_ref or (rels and t != "@" and t != "metadata" and not meta):
                raise ParseError(i, f"unexpected {self.describe(i)} before '{t}'")
            if t == "package":
                return self.Package(i, meta), False
            if t == "dependency":
                for m in meta:
                    m.type = "Annotation"
                return self.Dependency(i, meta), False
            return self.MetadataUsage(i, rels), False
        node = Node("ReferenceUsage", props)
        if rels:
            node.props["ownedRelationship"] = rels
        if is_ref and t not in USAGE_KEYWORDS:
            if meta:
                # ExtendedUsage : Usage = UnextendedUsagePrefix UsageExtensionKeyword+ Usage
                node.type = "Usage"
            # ReferenceUsage = ( EndUsagePrefix | RefPrefix ) 'ref' Usage
            node.props["isReference"] = True
            self.Usage(node)
            return self.fin(node, i), True
        if is_ref:
            node.props["isReference"] = True
        if t in USAGE_KEYWORDS:
            self.usage(node, ctx)
            return self.fin(node, i), True
        if meta:
            node.type = "Usage"  # ExtendedUsage
        elif "isIndividual" in props or "isPortion" in props:
            node.type = "OccurrenceUsage"  # IndividualUsage, PortionUsage
        elif not props and t not in DECLARATION_START and t not in ("=", ":=", "default"):
            raise self.error("expected a member")
        # DefaultReferenceUsage : ReferenceUsage = RefPrefix Usage
        self.Usage(node)
        return self.fin(node, i), True

    def RefPrefix(self, props: dict) -> None:
        """RefPrefix : Usage = ( direction = FeatureDirection )? ( isDerived ?= 'derived' )?
        ( isAbstract ?= 'abstract' | isVariation ?= 'variation' )? ( isConstant ?= 'constant' )?"""
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
        elif t == "variation":
            props["isVariation"] = True
            self.p += 1
            t = k[self.p]
        if t == "constant":
            props["isConstant"] = True
            self.p += 1

    def BasicUsagePrefix(self, props: dict) -> None:
        """BasicUsagePrefix : Usage = RefPrefix ( isReference ?= 'ref' )?"""
        self.RefPrefix(props)
        if self.accept("ref"):
            props["isReference"] = True

    def EmptyMultiplicityMember(self) -> Node:
        """EmptyMultiplicityMember : OwningMembership = ownedRelatedElement += EmptyMultiplicity
        EmptyMultiplicity : Multiplicity = { }"""
        m = self.empty("Multiplicity")
        return Node("OwningMembership", {"ownedRelatedElement": [m]}, m.span)

    # -------------------------------------------------------- definitions

    def definition(self, i: int, props: dict, rels: list[Node]) -> Node:
        """<Kind>Definition = <Prefix> <keyword> 'def' Definition (or DefinitionDeclaration <Kind>Body)

        Definition = DefinitionDeclaration DefinitionBody
        DefinitionDeclaration : Definition = Identification SubclassificationPart?
        IndividualDefinition : OccurrenceDefinition = BasicDefinitionPrefix? isIndividual ?= 'individual'
        DefinitionExtensionKeyword* 'def' Definition ownedRelationship += EmptyMultiplicityMember
        ExtendedDefinition : Definition = BasicDefinitionPrefix? DefinitionExtensionKeyword+ 'def' Definition"""
        k = self.k
        t = k[self.p]
        individual_def = False
        if t == "def":
            if props.get("isIndividual"):
                type, ctx = "OccurrenceDefinition", "definition"
                individual_def = True
                rels = [r for r in rels if not (r.type == "OwningMembership" and
                                                r.props["ownedRelatedElement"][0].type == "Multiplicity")]
            else:
                type, ctx = "Definition", "definition"
            self.p += 1
        else:
            type, ctx = DEFINITIONS[t]
            self.p += 3 if t == "use" else 2
        node = Node(type, props)
        if rels:
            node.props["ownedRelationship"] = list(rels)
        self.Identification(node)
        t = k[self.p]
        if t == ":>" or t == "specializes":
            self.SubclassificationPart(node)
        if ctx == "state":
            self.StateBody(node)
        elif ctx == "enum":
            self.EnumerationBody(node)
        else:
            self.body(node, ctx)
        if type == "PortDefinition":
            # ownedRelationship += ConjugatedPortDefinitionMember
            # ConjugatedPortDefinitionMember : OwningMembership = ownedRelatedElement += ConjugatedPortDefinition
            # ConjugatedPortDefinition = ownedRelationship += PortConjugation; PortConjugation = {}
            conj = self.empty("PortConjugation")
            cpd = Node("ConjugatedPortDefinition", {"ownedRelationship": [conj]}, conj.span)
            node.add("ownedRelationship", Node("OwningMembership", {"ownedRelatedElement": [cpd]}, conj.span))
        if individual_def:
            node.add("ownedRelationship", self.EmptyMultiplicityMember())
        return self.fin(node, i)

    def EnumerationBody(self, node: Node) -> None:
        """EnumerationBody : EnumerationDefinition = ';'
        | '{' ( ownedRelationship += AnnotatingMember | ownedRelationship += EnumerationUsageMember )* '}'"""
        self.body(node, "enum")

    def enum_item(self, node: Node) -> None:
        """AnnotatingMember : OwningMembership = MemberPrefix ownedRelatedElement += AnnotatingElement
        EnumerationUsageMember : VariantMembership = MemberPrefix ownedRelatedElement += EnumeratedValue
        EnumeratedValue : EnumerationUsage = 'enum'? Usage"""
        i = self.p
        vis = self.VisibilityIndicator()
        t = self.k[self.p]
        if t in ("comment", "COMMENT", "locale", "doc", "rep", "language", "@", "metadata", "#"):
            el = self.AnnotatingElement()
            m = self.new("OwningMembership", i, {"ownedRelatedElement": [el]})
        else:
            j = self.p
            self.accept("enum")
            el = Node("EnumerationUsage")
            self.Usage(el)
            self.fin(el, j)
            m = self.new("VariantMembership", i, {"ownedRelatedElement": [el]})
        if vis:
            m.props["visibility"] = vis
        node.add("ownedRelationship", m)

    # -------------------------------------------------------------- usages

    def Usage(self, node: Node, body: str = "definition") -> None:
        """Usage = UsageDeclaration UsageCompletion"""
        self.UsageDeclaration(node)
        self.UsageCompletion(node, body)

    def UsageDeclaration(self, node: Node) -> None:
        """UsageDeclaration : Usage = Identification FeatureSpecializationPart?"""
        self.Identification(node)
        self.FeatureSpecializationPart(node)

    def UsageCompletion(self, node: Node, body: str = "definition") -> None:
        """UsageCompletion : Usage = ValuePart? UsageBody"""
        self.ValuePart(node)
        self.body(node, body)

    def FeatureTyping(self) -> Node:
        """FeatureTyping = OwnedFeatureTyping | ConjugatedPortTyping
        ConjugatedPortTyping : ConjugatedPortTyping = '~' originalPortDefinition = ~[QualifiedName]"""
        if self.k[self.p] == "~":
            i = self.p
            self.p += 1
            ref = self.QualifiedName()
            return self.new("ConjugatedPortTyping", i, {"originalPortDefinition": ref})
        return self.OwnedFeatureTyping()

    def usage(self, node: Node, ctx: str) -> None:
        """The usage kinds after their prefix (StructureUsageElement, BehaviorUsageElement,
        NonOccurrenceUsageElement); ``node`` already holds the prefix properties."""
        k = self.k
        t = k[self.p]
        if t in SIMPLE_USAGES:
            # AttributeUsage = UsagePrefix 'attribute' Usage (and the other <keyword> Usage forms)
            node.type = SIMPLE_USAGES[t]
            self.p += 1
            self.Usage(node)
        elif t in CONSTRAINT_USAGES:
            # ConstraintUsage = OccurrenceUsagePrefix 'constraint' ConstraintUsageDeclaration CalculationBody
            # RequirementUsage = OccurrenceUsagePrefix 'requirement' ConstraintUsageDeclaration RequirementBody
            node.type, body = CONSTRAINT_USAGES[t]
            self.p += 1
            self.ConstraintUsageDeclaration(node)
            self.body(node, body)
        elif t == "use":
            # UseCaseUsage = OccurrenceUsagePrefix 'use' 'case' ConstraintUsageDeclaration CaseBody
            node.type = "UseCaseUsage"
            self.p += 1
            self.expect("case")
            self.ConstraintUsageDeclaration(node)
            self.CaseBody(node)
        elif t == "action":
            self.ActionUsage(node, ctx)
        elif t in ACTION_NODES:
            if ctx not in ACTION_CONTEXTS:
                raise self.error("this action node is only allowed in an action body")
            self.action_node(node, ctx)
        elif t in CONTROL_NODES:
            # MergeNode = ControlNodePrefix isComposite ?= 'merge' UsageDeclaration ActionBody
            node.type = CONTROL_NODES[t]
            node.props["isComposite"] = True
            self.p += 1
            self.UsageDeclaration(node)
            self.ActionBody(node)
        elif t == "calc":
            # CalculationUsage : CalculationUsage = OccurrenceUsagePrefix 'calc' ActionUsageDeclaration CalculationBody
            node.type = "CalculationUsage"
            self.p += 1
            self.ActionUsageDeclaration(node)
            self.CalculationBody(node)
        elif t == "state":
            # StateUsage = OccurrenceUsagePrefix 'state' ActionUsageDeclaration StateUsageBody
            node.type = "StateUsage"
            self.p += 1
            self.ActionUsageDeclaration(node)
            self.StateBody(node)
        elif t == "event":
            self.EventOccurrenceUsage(node)
        elif t == "connection" or t == "connect":
            self.ConnectionUsage(node)
        elif t == "interface":
            self.InterfaceUsage(node)
        elif t == "allocation" or t == "allocate":
            self.AllocationUsage(node)
        elif t == "flow":
            # FlowUsage = OccurrenceUsagePrefix 'flow' FlowDeclaration DefinitionBody
            node.type = "FlowUsage"
            self.p += 1
            self.FlowDeclaration(node)
            self.DefinitionBody(node)
        elif t == "message":
            self.Message(node)
        elif t == "succession":
            self.succession(node, ctx)
        elif t == "binding" or t == "bind":
            self.BindingConnectorAsUsage(node)
        elif t == "first":
            self.SuccessionAsUsage(node)
        elif t == "view":
            # ViewUsage = OccurrenceUsagePrefix 'view' UsageDeclaration? ValuePart? ViewBody
            node.type = "ViewUsage"
            self.p += 1
            self.UsageDeclaration(node)
            self.ValuePart(node)
            self.body(node, "view")
        elif t == "perform":
            self.PerformActionUsage(node)
        elif t == "exhibit":
            self.ExhibitStateUsage(node)
        elif t == "include":
            self.IncludeUseCaseUsage(node)
        elif t == "assert" or t == "satisfy":
            self.assert_usage(node)
        elif t == "transition":
            node.type = "TransitionUsage"
            self.TransitionUsage(node)
        elif t == "ref":
            # ReferenceUsage = ( EndUsagePrefix | RefPrefix ) 'ref' Usage   (after 'end')
            self.p += 1
            node.props["isReference"] = True
            self.Usage(node)
        elif t == "metadata" or t == "@":
            raise self.error("metadata usage is not allowed here")
        else:  # pragma: no cover - guarded by USAGE_KEYWORDS
            raise self.error("expected a usage")

    def ConstraintUsageDeclaration(self, node: Node) -> None:
        """ConstraintUsageDeclaration : ConstraintUsage = UsageDeclaration ValuePart?"""
        self.UsageDeclaration(node)
        self.ValuePart(node)

    ActionUsageDeclaration = ConstraintUsageDeclaration
    ActionUsageDeclaration.__doc__ = """ActionUsageDeclaration : ActionUsage = UsageDeclaration ValuePart?"""

    def EventOccurrenceUsage(self, node: Node) -> None:
        """EventOccurrenceUsage = OccurrenceUsagePrefix 'event' ( ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? | 'occurrence' UsageDeclaration? ) UsageCompletion"""
        node.type = "EventOccurrenceUsage"
        self.p += 1
        if self.accept("occurrence"):
            self.UsageDeclaration(node)
        else:
            self.owned_reference(node)
        self.UsageCompletion(node)

    def owned_reference(self, node: Node, specialization: str = "part") -> None:
        """ownedRelationship += OwnedReferenceSubsetting FeatureSpecializationPart?
        (``specialization="list"``: FeatureSpecialization*)"""
        node.add("ownedRelationship", self.OwnedReferenceSubsetting())
        if specialization == "list":
            while self.k[self.p] in SPECIALIZATION_TOKENS and self.FeatureSpecialization(node):
                pass
        else:
            self.FeatureSpecializationPart(node)

    # ---------------------------------------------------- connections

    def ConnectionUsage(self, node: Node) -> None:
        """ConnectionUsage = OccurrenceUsagePrefix ( 'connection' UsageDeclaration ValuePart?
        ( 'connect' ConnectorPart )? | 'connect' ConnectorPart ) UsageBody"""
        node.type = "ConnectionUsage"
        if self.accept("connection"):
            self.UsageDeclaration(node)
            self.ValuePart(node)
            if self.accept("connect"):
                self.ConnectorPart(node)
        else:
            self.expect("connect")
            self.ConnectorPart(node)
        self.UsageBody(node)

    def ConnectorPart(self, node: Node, end=None) -> None:
        """ConnectorPart : ConnectionUsage = BinaryConnectorPart | NaryConnectorPart
        BinaryConnectorPart : ConnectionUsage = ownedRelationship += ConnectorEndMember 'to'
        ownedRelationship += ConnectorEndMember
        NaryConnectorPart : ConnectionUsage = '(' ownedRelationship += ConnectorEndMember ','
        ownedRelationship += ConnectorEndMember ( ',' ownedRelationship += ConnectorEndMember )* ')'"""
        end = end or self.ConnectorEndMember
        if self.accept("("):
            node.add("ownedRelationship", end())
            self.expect(",")
            node.add("ownedRelationship", end())
            while self.accept(","):
                node.add("ownedRelationship", end())
            self.expect(")")
        else:
            node.add("ownedRelationship", end())
            self.expect("to")
            node.add("ownedRelationship", end())

    def InterfaceEndMember(self) -> Node:
        """InterfaceEndMember : EndFeatureMembership = ownedRelatedElement += InterfaceEnd
        InterfaceEnd : PortUsage = ( ownedRelationship += OwnedCrossMultiplicityMember )?
        ( declaredName = NAME REFERENCES )? ownedRelationship += OwnedReferenceSubsetting"""
        member = self.ConnectorEndMember()
        member.props["ownedRelatedElement"][0].type = "PortUsage"
        return member

    def InterfaceUsage(self, node: Node) -> None:
        """InterfaceUsage = OccurrenceUsagePrefix 'interface' InterfaceUsageDeclaration InterfaceBody
        InterfaceUsageDeclaration : InterfaceUsage = UsageDeclaration ValuePart?
        ( 'connect' InterfacePart )? | InterfacePart"""
        node.type = "InterfaceUsage"
        self.expect("interface")
        if self.k[self.p] == "(":
            self.ConnectorPart(node, self.InterfaceEndMember)
        elif not self._attempt_binary(node, self.InterfaceEndMember):
            self.UsageDeclaration(node)
            self.ValuePart(node)
            if self.accept("connect"):
                self.ConnectorPart(node, self.InterfaceEndMember)
        self.InterfaceBody(node)

    def _attempt_binary(self, node: Node, end) -> bool:
        def binary():
            a = end()
            self.expect("to")
            return [a, end()]
        got = self.attempt(binary)
        if got:
            node.props.setdefault("ownedRelationship", []).extend(got)
            return True
        return False

    def AllocationUsage(self, node: Node) -> None:
        """AllocationUsage = OccurrenceUsagePrefix AllocationUsageDeclaration UsageBody
        AllocationUsageDeclaration : AllocationUsage = 'allocation' UsageDeclaration
        ( 'allocate' ConnectorPart )? | 'allocate' ConnectorPart"""
        node.type = "AllocationUsage"
        if self.accept("allocation"):
            self.UsageDeclaration(node)
            if self.accept("allocate"):
                self.ConnectorPart(node)
        else:
            self.expect("allocate")
            self.ConnectorPart(node)
        self.UsageBody(node)

    def BindingConnectorAsUsage(self, node: Node) -> None:
        """BindingConnectorAsUsage = UsagePrefix ( 'binding' UsageDeclaration )?
        'bind' ownedRelationship += ConnectorEndMember '=' ownedRelationship += ConnectorEndMember UsageBody"""
        node.type = "BindingConnectorAsUsage"
        if self.accept("binding"):
            self.UsageDeclaration(node)
        self.expect("bind")
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.expect("=")
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.UsageBody(node)

    def SuccessionAsUsage(self, node: Node) -> None:
        """SuccessionAsUsage = UsagePrefix ( 'succession' UsageDeclaration )?
        'first' ownedRelationship += ConnectorEndMember 'then' ownedRelationship += ConnectorEndMember UsageBody"""
        node.type = "SuccessionAsUsage"
        self.expect("first")
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.expect("then")
        node.add("ownedRelationship", self.ConnectorEndMember())
        self.UsageBody(node)

    def succession(self, node: Node, ctx: str) -> None:
        """'succession' 'flow' FlowDeclaration DefinitionBody (SuccessionFlowUsage)
        | 'succession' UsageDeclaration 'first' ... (SuccessionAsUsage, or GuardedSuccession in actions)"""
        self.expect("succession")
        if self.accept("flow"):
            node.type = "SuccessionFlowUsage"
            self.FlowDeclaration(node)
            self.DefinitionBody(node)
            return
        self.UsageDeclaration(node)
        if ctx in ACTION_CONTEXTS and self._guarded_first():
            self.GuardedSuccession(node)
        else:
            self.SuccessionAsUsage(node)

    def _guarded_first(self) -> bool:
        """At 'first' FeatureChainMember 'if' (a GuardedSuccession)?"""
        k = self.k
        if k[self.p] != "first":
            return False
        end, _ = self.scan_chain(self.p + 1)
        return end > 0 and k[end] == "if"

    # ----------------------------------------------------------- flows

    def FlowDeclaration(self, node: Node) -> None:
        """FlowDeclaration : FlowUsage = UsageDeclaration ValuePart?
        ( 'of' ownedRelationship += FlowPayloadFeatureMember )?
        ( 'from' ownedRelationship += FlowEndMember 'to' ownedRelationship += FlowEndMember )?
        | ownedRelationship += FlowEndMember 'to' ownedRelationship += FlowEndMember"""
        got = self.attempt(self._flow_ends_list)
        if got:
            node.props.setdefault("ownedRelationship", []).extend(got)
            return
        self.UsageDeclaration(node)
        self.ValuePart(node)
        if self.accept("of"):
            node.add("ownedRelationship", self.FlowPayloadFeatureMember())
        if self.accept("from"):
            self._flow_ends(node)

    def FlowPayloadFeatureMember(self) -> Node:
        """FlowPayloadFeatureMember : FeatureMembership = ownedRelatedElement += FlowPayloadFeature
        FlowPayloadFeature : PayloadFeature = PayloadFeature"""
        feature = self.PayloadFeature()
        return Node("FeatureMembership", {"ownedRelatedElement": [feature]}, feature.span)

    def PayloadFeature(self, node: Node | None = None) -> Node:
        """PayloadFeature : Feature = Identification? PayloadFeatureSpecializationPart ValuePart?
        | ownedRelationship += OwnedFeatureTyping ( ownedRelationship += OwnedMultiplicity )?
        | ownedRelationship += OwnedMultiplicity ownedRelationship += OwnedFeatureTyping"""
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
        if self._payload_has_identification(i) or k[i] in SPECIALIZATION_TOKENS:
            self.Identification(node)
            self.FeatureSpecializationPart(node)
            self.ValuePart(node)
            return self.fin(node, i)
        node.add("ownedRelationship", self.OwnedFeatureTyping())
        if k[self.p] == "[":
            node.add("ownedRelationship", self.OwnedMultiplicity())
        return self.fin(node, i)

    def Message(self, node: Node) -> None:
        """Message : FlowUsage = OccurrenceUsagePrefix 'message' MessageDeclaration DefinitionBody
        { isAbstract = true }
        MessageDeclaration : FlowUsage = UsageDeclaration ValuePart?
        ( 'of' ownedRelationship += FlowPayloadFeatureMember )?
        ( 'from' ownedRelationship += MessageEventMember 'to' ownedRelationship += MessageEventMember )?
        | ownedRelationship += MessageEventMember 'to' ownedRelationship += MessageEventMember"""
        node.type = "FlowUsage"
        self.expect("message")

        def events():
            a = self.MessageEventMember()
            self.expect("to")
            return [a, self.MessageEventMember()]
        got = self.attempt(events)
        if got:
            node.props.setdefault("ownedRelationship", []).extend(got)
        else:
            self.UsageDeclaration(node)
            self.ValuePart(node)
            if self.accept("of"):
                node.add("ownedRelationship", self.FlowPayloadFeatureMember())
            if self.accept("from"):
                node.props.setdefault("ownedRelationship", []).extend(events())
        self.DefinitionBody(node)
        node.props["isAbstract"] = True

    def MessageEventMember(self) -> Node:
        """MessageEventMember : ParameterMembership = ownedRelatedElement += MessageEvent
        MessageEvent : EventOccurrenceUsage = ownedRelationship += OwnedReferenceSubsetting"""
        sub = self.OwnedReferenceSubsetting()
        event = Node("EventOccurrenceUsage", {"ownedRelationship": [sub]}, sub.span)
        return Node("ParameterMembership", {"ownedRelatedElement": [event]}, sub.span)

    # --------------------------------------------------------- actions

    def ActionUsage(self, node: Node, ctx: str) -> None:
        """ActionUsage = OccurrenceUsagePrefix 'action' ActionUsageDeclaration ActionBody

        or an ActionNode whose ActionNodePrefix has an ActionNodeUsageDeclaration:
        ActionNodeUsageDeclaration : ActionUsage = 'action' UsageDeclaration?"""
        node.type = "ActionUsage"
        self.expect("action")
        self.UsageDeclaration(node)
        if self.k[self.p] in ACTION_NODES and ctx in ACTION_CONTEXTS:
            self.action_node(node, ctx)
            return
        self.ValuePart(node)
        self.ActionBody(node)

    def action_node(self, node: Node, ctx: str) -> None:
        """ActionNode : ActionUsage = ControlNode | SendNode | AcceptNode | AssignmentNode | TerminateNode
        | IfNode | WhileLoopNode | ForLoopNode   (after the prefix and optional 'action' declaration)"""
        t = self.k[self.p]
        if t == "accept":
            # AcceptNode : AcceptActionUsage = OccurrenceUsagePrefix AcceptNodeDeclaration ActionBody
            node.type = "AcceptActionUsage"
            self.p += 1
            self.AcceptParameterPart(node)
            self.ActionBody(node)
        elif t == "send":
            node.type = "SendActionUsage"
            self.SendNode(node)
            self.ActionBody(node)
        elif t == "assign":
            node.type = "AssignmentActionUsage"
            self.AssignmentNodeDeclaration(node)
            self.ActionBody(node)
        elif t == "terminate":
            # TerminateNode : TerminateActionUsage = OccurrenceUsagePrefix ActionNodeUsageDeclaration?
            # 'terminate' ( ownedRelationship += NodeParameterMember )? ActionBody
            node.type = "TerminateActionUsage"
            self.p += 1
            if self.k[self.p] not in (";", "{"):
                node.add("ownedRelationship", self.NodeParameterMember())
            self.ActionBody(node)
        elif t == "if":
            node.type = "IfActionUsage"
            self.IfNode(node)
        elif t == "while" or t == "loop":
            node.type = "WhileLoopActionUsage"
            self.WhileLoopNode(node)
        else:
            node.type = "ForLoopActionUsage"
            self.ForLoopNode(node)

    def AcceptParameterPart(self, node: Node) -> None:
        """AcceptParameterPart : AcceptActionUsage = ownedRelationship += PayloadParameterMember
        ( 'via' ownedRelationship += NodeParameterMember )?"""
        node.add("ownedRelationship", self.PayloadParameterMember())
        if self.accept("via"):
            node.add("ownedRelationship", self.NodeParameterMember())

    def PayloadParameterMember(self) -> Node:
        """PayloadParameterMember : ParameterMembership = ownedRelatedElement += PayloadParameter
        PayloadParameter : ReferenceUsage = PayloadFeature
        | Identification PayloadFeatureSpecializationPart? TriggerValuePart"""
        k = self.k
        i = self.p
        param = Node("ReferenceUsage")
        t = k[i]
        if t in ("when", "at", "after"):
            self.TriggerValuePart(param)
        elif (t == "NAME" and k[i + 1] in ("when", "at", "after")) or t == "<" and self._trigger_after_name(i):
            self.Identification(param)
            self.FeatureSpecializationPart(param)
            self.TriggerValuePart(param)
        else:
            self.PayloadFeature(param)
            if k[self.p] in ("when", "at", "after"):
                self.TriggerValuePart(param)
        self.fin(param, i)
        return Node("ParameterMembership", {"ownedRelatedElement": [param]}, param.span)

    def _trigger_after_name(self, i: int) -> bool:
        k = self.k
        j = i
        while k[j] not in ("when", "at", "after", ";", "{", "EOF"):
            j += 1
        return k[j] in ("when", "at", "after")

    def TriggerValuePart(self, node: Node) -> None:
        """TriggerValuePart : Feature = ownedRelationship += TriggerFeatureValue
        TriggerFeatureValue : FeatureValue = ownedRelatedElement += TriggerExpression
        TriggerExpression : TriggerInvocationExpression = kind = ( 'at' | 'after' )
        ownedRelationship += ArgumentMember | kind = 'when' ownedRelationship += ArgumentExpressionMember"""
        i = self.p
        kind = self.k[i]
        self.p += 1
        expr = self.OwnedExpression()
        arg = self.ArgumentExpressionMember(expr) if kind == "when" else self.ArgumentMember(expr)
        trigger = self.new("TriggerInvocationExpression", i, {"kind": kind, "ownedRelationship": [arg]})
        node.add("ownedRelationship", Node("FeatureValue", {"ownedRelatedElement": [trigger]}, trigger.span))

    def NodeParameterMember(self) -> Node:
        """NodeParameterMember : ParameterMembership = ownedRelatedElement += NodeParameter
        NodeParameter : ReferenceUsage = ownedRelationship += FeatureBinding
        FeatureBinding : FeatureValue = ownedRelatedElement += OwnedExpression"""
        expr = self.OwnedExpression()
        sp = expr.span
        binding = Node("FeatureValue", {"ownedRelatedElement": [expr]}, sp)
        param = Node("ReferenceUsage", {"ownedRelationship": [binding]}, sp)
        return Node("ParameterMembership", {"ownedRelatedElement": [param]}, sp)

    def EmptyParameterMember(self) -> Node:
        """EmptyParameterMember : ParameterMembership = ownedRelatedElement += EmptyUsage
        EmptyUsage : ReferenceUsage = {}"""
        u = self.empty("ReferenceUsage")
        return Node("ParameterMembership", {"ownedRelatedElement": [u]}, u.span)

    def SendNode(self, node: Node) -> None:
        """SendNode : SendActionUsage = OccurrenceUsagePrefix ActionUsageDeclaration? 'send'
        ( ownedRelationship += NodeParameterMember SenderReceiverPart?
        | ownedRelationship += EmptyParameterMember SenderReceiverPart )? ActionBody

        SenderReceiverPart : SendActionUsage = 'via' ownedRelationship += NodeParameterMember
        ( 'to' ownedRelationship += NodeParameterMember )?
        | ownedRelationship += EmptyParameterMember 'to' ownedRelationship += NodeParameterMember"""
        self.expect("send")
        k = self.k
        t = k[self.p]
        if t in ("via", "to"):
            node.add("ownedRelationship", self.EmptyParameterMember())
            self.SenderReceiverPart(node)
        elif t not in (";", "{") or (t == "{" and self._body_expression_ahead()):
            node.add("ownedRelationship", self.NodeParameterMember())
            if k[self.p] in ("via", "to"):
                self.SenderReceiverPart(node)

    def _body_expression_ahead(self) -> bool:
        """At '{': is it a body expression argument rather than the ActionBody?"""
        depth = 0
        j = self.p
        k = self.k
        while True:
            t = k[j]
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    return k[j + 1] in ("via", "to")
            elif t == "EOF":
                return False
            j += 1

    def SenderReceiverPart(self, node: Node) -> None:
        if self.accept("via"):
            node.add("ownedRelationship", self.NodeParameterMember())
            if self.accept("to"):
                node.add("ownedRelationship", self.NodeParameterMember())
        else:
            node.add("ownedRelationship", self.EmptyParameterMember())
            self.expect("to")
            node.add("ownedRelationship", self.NodeParameterMember())

    def AssignmentNodeDeclaration(self, node: Node) -> None:
        """AssignmentNodeDeclaration : ActionUsage = ( ActionNodeUsageDeclaration )? 'assign'
        ownedRelationship += AssignmentTargetMember ownedRelationship += FeatureChainMember ':='
        ownedRelationship += NodeParameterMember

        AssignmentTargetMember : ParameterMembership = ownedRelatedElement += AssignmentTargetParameter
        AssignmentTargetParameter : ReferenceUsage = ( ownedRelationship += AssignmentTargetBinding '.' )?
        AssignmentTargetBinding : FeatureValue = ownedRelatedElement += NonFeatureChainPrimaryExpression"""
        self.expect("assign")
        k = self.k
        i = self.p
        target = Node("ReferenceUsage")
        end, n = self.scan_chain(i)
        if end > 0 and k[end] == ":=":
            if n > 1:
                # target binding: the first segment; the member: the rest of the chain
                expr = self.FeatureReferenceExpression()
                target.add("ownedRelationship", Node("FeatureValue", {"ownedRelatedElement": [expr]}, expr.span))
                self.expect(".")
        else:
            expr = self.non_feature_chain_primary()
            target.add("ownedRelationship", Node("FeatureValue", {"ownedRelatedElement": [expr]}, expr.span))
            self.expect(".")
        self.fin(target, i)
        node.add("ownedRelationship", Node("ParameterMembership", {"ownedRelatedElement": [target]}, target.span))
        node.add("ownedRelationship", self.FeatureChainMember())
        self.expect(":=")
        node.add("ownedRelationship", self.NodeParameterMember())

    def non_feature_chain_primary(self) -> Node:
        """NonFeatureChainPrimaryExpression: a primary expression whose last postfix is not a '.' chain
        (the assignment target before its final '.' FeatureChainMember)."""
        k = self.k
        save = self.p
        # Parse the longest primary, then back off the trailing feature chain.
        expr = self.PrimaryExpression()
        if expr.type == "FeatureChainExpression":
            first = expr.props["ownedRelationship"][0]
            inner = first.props["ownedRelatedElement"][0].props["ownedRelationship"][0].props["ownedRelatedElement"][0]
            # rewind to the '.' that starts the chain member
            member = expr.props["ownedRelationship"][1]
            start = member.span.start
            j = save
            while self.s[j] < start:
                j += 1
            self.p = j - 1
            return inner
        if k[self.p] != ".":
            raise self.error("expected '.' before the assigned feature")
        return expr

    def IfNode(self, node: Node) -> None:
        """IfNode : IfActionUsage = ActionNodePrefix 'if' ownedRelationship += ExpressionParameterMember
        ownedRelationship += ActionBodyParameterMember
        ( 'else' ownedRelationship += ( ActionBodyParameterMember | IfNodeParameterMember ) )?"""
        self.expect("if")
        node.add("ownedRelationship", self.ExpressionParameterMember())
        node.add("ownedRelationship", self.ActionBodyParameterMember())
        if self.accept("else"):
            if self.k[self.p] == "if":
                # IfNodeParameterMember : ParameterMembership = ownedRelatedElement += IfNode
                i = self.p
                inner = Node("IfActionUsage")
                self.IfNode(inner)
                self.fin(inner, i)
                node.add("ownedRelationship", Node("ParameterMembership", {"ownedRelatedElement": [inner]},
                                                   inner.span))
            else:
                node.add("ownedRelationship", self.ActionBodyParameterMember())

    def ExpressionParameterMember(self) -> Node:
        """ExpressionParameterMember : ParameterMembership = ownedRelatedElement += OwnedExpression"""
        expr = self.OwnedExpression()
        return Node("ParameterMembership", {"ownedRelatedElement": [expr]}, expr.span)

    def ActionBodyParameterMember(self) -> Node:
        """ActionBodyParameterMember : ParameterMembership = ownedRelatedElement += ActionBodyParameter
        ActionBodyParameter : ActionUsage = ( 'action' UsageDeclaration? )? '{' ActionBodyItem* '}'"""
        i = self.p
        param = Node("ActionUsage")
        if self.accept("action"):
            self.UsageDeclaration(param)
        self.expect("{")
        self.items(param, lambda n: self.body_item(n, "action"))
        self.fin(param, i)
        return Node("ParameterMembership", {"ownedRelatedElement": [param]}, param.span)

    def WhileLoopNode(self, node: Node) -> None:
        """WhileLoopNode : WhileLoopActionUsage = ActionNodePrefix ( 'while' ownedRelationship +=
        ExpressionParameterMember | 'loop' ownedRelationship += EmptyParameterMember )
        ownedRelationship += ActionBodyParameterMember ( 'until' ownedRelationship += ExpressionParameterMember ';' )?"""
        if self.accept("while"):
            node.add("ownedRelationship", self.ExpressionParameterMember())
        else:
            self.expect("loop")
            node.add("ownedRelationship", self.EmptyParameterMember())
        node.add("ownedRelationship", self.ActionBodyParameterMember())
        if self.accept("until"):
            node.add("ownedRelationship", self.ExpressionParameterMember())
            self.expect(";")

    def ForLoopNode(self, node: Node) -> None:
        """ForLoopNode : ForLoopActionUsage = ActionNodePrefix 'for' ownedRelationship += ForVariableDeclarationMember
        'in' ownedRelationship += NodeParameterMember ownedRelationship += ActionBodyParameterMember

        ForVariableDeclarationMember : FeatureMembership = ownedRelatedElement += UsageDeclaration
        ForVariableDeclaration : ReferenceUsage = UsageDeclaration"""
        self.expect("for")
        i = self.p
        var = Node("ReferenceUsage")
        self.UsageDeclaration(var)
        self.fin(var, i)
        node.add("ownedRelationship", Node("FeatureMembership", {"ownedRelatedElement": [var]}, var.span))
        self.expect("in")
        node.add("ownedRelationship", self.NodeParameterMember())
        node.add("ownedRelationship", self.ActionBodyParameterMember())

    def PerformActionUsage(self, node: Node) -> None:
        """PerformActionUsage = OccurrenceUsagePrefix 'perform' PerformActionUsageDeclaration ActionBody
        PerformActionUsageDeclaration : PerformActionUsage = ( ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? | 'action' UsageDeclaration ) ValuePart?"""
        node.type = "PerformActionUsage"
        self.expect("perform")
        self.PerformActionUsageDeclaration(node)
        self.ActionBody(node)

    def PerformActionUsageDeclaration(self, node: Node) -> None:
        if self.accept("action"):
            self.UsageDeclaration(node)
        else:
            self.owned_reference(node)
        self.ValuePart(node)

    def ExhibitStateUsage(self, node: Node) -> None:
        """ExhibitStateUsage = OccurrenceUsagePrefix 'exhibit' ( ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? | 'state' UsageDeclaration ) ValuePart? StateUsageBody"""
        node.type = "ExhibitStateUsage"
        self.expect("exhibit")
        if self.accept("state"):
            self.UsageDeclaration(node)
        else:
            self.owned_reference(node)
        self.ValuePart(node)
        self.StateBody(node)

    def IncludeUseCaseUsage(self, node: Node) -> None:
        """IncludeUseCaseUsage = OccurrenceUsagePrefix 'include' ( ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? | 'use' 'case' UsageDeclaration ) ValuePart? CaseBody"""
        node.type = "IncludeUseCaseUsage"
        self.expect("include")
        if self.accept("use"):
            self.expect("case")
            self.UsageDeclaration(node)
        else:
            self.owned_reference(node)
        self.ValuePart(node)
        self.CaseBody(node)

    def assert_usage(self, node: Node) -> None:
        """AssertConstraintUsage = OccurrenceUsagePrefix 'assert' ( isNegated ?= 'not' )?
        ( ownedRelationship += OwnedReferenceSubsetting FeatureSpecializationPart?
        | 'constraint' ConstraintUsageDeclaration ) CalculationBody

        SatisfyRequirementUsage = OccurrenceUsagePrefix ( 'assert' ( isNegated ?= 'not' )? )? 'satisfy'
        ( ownedRelationship += OwnedReferenceSubsetting FeatureSpecializationPart?
        | 'requirement' UsageDeclaration ) ValuePart? ( 'by' ownedRelationship += SatisfactionSubjectMember )?
        RequirementBody"""
        if self.accept("assert"):
            if self.accept("not"):
                node.props["isNegated"] = True
            if not self.accept("satisfy"):
                node.type = "AssertConstraintUsage"
                if self.accept("constraint"):
                    self.ConstraintUsageDeclaration(node)
                else:
                    self.owned_reference(node)
                self.CalculationBody(node)
                return
        else:
            self.expect("satisfy")
        node.type = "SatisfyRequirementUsage"
        if self.accept("requirement"):
            self.UsageDeclaration(node)
        else:
            self.owned_reference(node)
        self.ValuePart(node)
        if self.accept("by"):
            node.add("ownedRelationship", self.SatisfactionSubjectMember())
        self.RequirementBody(node)

    def SatisfactionSubjectMember(self) -> Node:
        """SatisfactionSubjectMember : SubjectMembership = ownedRelatedElement += SatisfactionParameter
        SatisfactionParameter : ReferenceUsage = ownedRelationship += SatisfactionFeatureValue
        SatisfactionFeatureValue : FeatureValue = ownedRelatedElement += SatisfactionReferenceExpression
        SatisfactionReferenceExpression : FeatureReferenceExpression = ownedRelationship += FeatureChainMember"""
        member = self.FeatureChainMember()
        sp = member.span
        expr = Node("FeatureReferenceExpression", {"ownedRelationship": [member]}, sp)
        value = Node("FeatureValue", {"ownedRelatedElement": [expr]}, sp)
        param = Node("ReferenceUsage", {"ownedRelationship": [value]}, sp)
        return Node("SubjectMembership", {"ownedRelatedElement": [param]}, sp)

    # ---------------------------------------------- successions in actions

    def then_member(self, i: int, vis: str | None, ctx: str) -> Node:
        """'then' in a body: ActionTargetSuccessionMember (action bodies: 'then' target) or
        SourceSuccessionMember followed by an occurrence usage member.

        SourceSuccessionMember : FeatureMembership = 'then' ownedRelatedElement += SourceSuccession
        SourceSuccession : SuccessionAsUsage = ownedRelationship += SourceEndMember
        SourceEndMember : EndFeatureMembership = ownedRelatedElement += SourceEnd
        SourceEnd : ReferenceUsage = ( ownedRelationship += OwnedMultiplicity )?"""
        k = self.k
        if ctx in ACTION_CONTEXTS and self._then_target():
            # ActionTargetSuccessionMember : FeatureMembership = MemberPrefix ownedRelatedElement += ActionTargetSuccession
            succ = self.TargetSuccession()
            self.UsageBody(succ)
            self.fin(succ, i if vis is None else i + 1)
            return self._member("FeatureMembership", i, vis, succ)
        j = self.expect("then")
        end = Node("ReferenceUsage")
        if k[self.p] == "[":
            end.add("ownedRelationship", self.OwnedMultiplicity())
        self.fin(end, j)
        end_member = Node("EndFeatureMembership", {"ownedRelatedElement": [end]}, end.span)
        succ = self.new("SuccessionAsUsage", j, {"ownedRelationship": [end_member]})
        source = self.new("FeatureMembership", i, {"ownedRelatedElement": [succ]})
        if vis:
            source.props["visibility"] = vis
        # ... ownedRelationship += OccurrenceUsageMember (returned to the caller as a second member)
        self._pending = source
        el, _ = self.element(ctx)
        return self._member("FeatureMembership", self.s.index(el.span.start) if False else j, None, el)

    def _member(self, type: str, i: int, vis: str | None, el: Node) -> Node:
        m = Node(type, {"ownedRelatedElement": [el]}, None)
        m.span = self.span(i)
        if vis:
            m.props["visibility"] = vis
        return m

    def _then_target(self) -> bool:
        """After 'then': a target (QualifiedName, chain or '[' mult target) rather than a new usage?"""
        k = self.k
        p = self.p + 1
        t = k[p]
        if t == "NAME" or t == "$":
            return True
        if t == "[":
            while k[p] not in ("]", "EOF"):
                p += 1
            return k[p + 1] in ("NAME", "$")
        return False

    def TargetSuccession(self) -> Node:
        """TargetSuccession : SuccessionAsUsage = ownedRelationship += SourceEndMember
        'then' ownedRelationship += ConnectorEndMember"""
        end = self.empty("ReferenceUsage")
        source = Node("EndFeatureMembership", {"ownedRelatedElement": [end]}, end.span)
        self.expect("then")
        return Node("SuccessionAsUsage", {"ownedRelationship": [source, self.ConnectorEndMember()]})

    def action_succession_member(self, i: int, vis: str | None, t: str, ctx: str) -> Node | None:
        """InitialNodeMember, GuardedSuccessionMember, GuardedTargetSuccession, DefaultTargetSuccession and
        IfNode / SuccessionAsUsage starting with 'first', 'if' or 'else' in an action body."""
        k = self.k
        if t == "first":
            end, _ = self.scan_chain(self.p + 1)
            if end > 0 and k[end] in (";", "{"):
                # InitialNodeMember : FeatureMembership = MemberPrefix 'first' memberFeature = [QualifiedName]
                # RelationshipBody
                self.p += 1
                m = Node("Membership", {"memberElement": self.QualifiedName()})
                if vis:
                    m.props["visibility"] = vis
                self.RelationshipBody(m)
                return self.fin(m, i)
            if end > 0 and k[end] == "if":
                # GuardedSuccessionMember : FeatureMembership = MemberPrefix ownedRelatedElement += GuardedSuccession
                j = self.p
                succ = Node("TransitionUsage")
                self.GuardedSuccession(succ)
                self.fin(succ, j)
                return self._member("FeatureMembership", i, vis, succ)
            return None
        if t == "else":
            # DefaultTargetSuccession : TransitionUsage = 'else' ownedRelationship += TransitionSuccessionMember
            j = self.p
            self.p += 1
            succ = Node("TransitionUsage", {"ownedRelationship": [self.TransitionSuccessionMember()]})
            self.UsageBody(succ)
            self.fin(succ, j)
            return self._member("FeatureMembership", i, vis, succ)
        # 'if': GuardedTargetSuccession (if guard then target) or an IfNode
        j = self.p
        guard = self.attempt(self._guard_then)
        if guard is None:
            return None
        succ = Node("TransitionUsage", {"ownedRelationship": [guard, self.TransitionSuccessionMember()]})
        self.UsageBody(succ)
        self.fin(succ, j)
        return self._member("FeatureMembership", i, vis, succ)

    def _guard_then(self) -> Node:
        guard = self.GuardExpressionMember()
        self.expect("then")
        return guard

    def GuardedSuccession(self, node: Node) -> None:
        """GuardedSuccession : TransitionUsage = ( 'succession' UsageDeclaration )?
        'first' ownedRelationship += FeatureChainMember ownedRelationship += GuardExpressionMember
        'then' ownedRelationship += TransitionSuccessionMember UsageBody"""
        node.type = "TransitionUsage"
        self.expect("first")
        node.add("ownedRelationship", self.FeatureChainMember())
        node.add("ownedRelationship", self.GuardExpressionMember())
        self.expect("then")
        node.add("ownedRelationship", self.TransitionSuccessionMember())
        self.UsageBody(node)

    def GuardExpressionMember(self) -> Node:
        """GuardExpressionMember : TransitionFeatureMembership = 'if' { kind = 'guard' }
        ownedRelatedElement += OwnedExpression"""
        i = self.expect("if")
        expr = self.OwnedExpression()
        return self.new("TransitionFeatureMembership", i, {"kind": "guard", "ownedRelatedElement": [expr]})

    def TransitionSuccessionMember(self) -> Node:
        """TransitionSuccessionMember : OwningMembership = ownedRelatedElement += TransitionSuccession
        TransitionSuccession : Succession = ownedRelationship += EmptyEndMember ownedRelationship += ConnectorEndMember
        EmptyEndMember : EndFeatureMembership = ownedRelatedElement += EmptyFeature
        EmptyFeature : ReferenceUsage = {}"""
        empty = self.empty("ReferenceUsage")
        end = Node("EndFeatureMembership", {"ownedRelatedElement": [empty]}, empty.span)
        target = self.ConnectorEndMember()
        succ = Node("Succession", {"ownedRelationship": [end, target]}, target.span)
        return Node("OwningMembership", {"ownedRelatedElement": [succ]}, target.span)

    # ---------------------------------------------------------- states

    def StateActionUsage(self) -> Node:
        """StateActionUsage : ActionUsage = EmptyActionUsage ';' | StatePerformActionUsage
        | StateAcceptActionUsage | StateSendActionUsage | StateAssignmentActionUsage

        StatePerformActionUsage : PerformActionUsage = PerformActionUsageDeclaration ActionBody (and the
        accept, send and assignment forms with their node declarations)"""
        k = self.k
        i = self.p
        if k[i] == ";":
            self.p += 1
            return self.empty("ActionUsage")
        node = self.effect_action(i, "state")
        return self.fin(node, i)

    def effect_action(self, i: int, where: str) -> Node:
        """The perform / accept / send / assign action of a state subaction or transition effect.
        ``where`` "state": followed by ActionBody; "transition": by ( '{' ActionBodyItem* '}' )?"""
        k = self.k
        node = Node("ActionUsage")
        decl = False
        if k[self.p] == "action":
            j = self.p
            self.p += 1
            self.UsageDeclaration(node)
            decl = True
            if k[self.p] not in ("accept", "send", "assign"):
                # PerformActionUsageDeclaration: 'action' UsageDeclaration ValuePart?
                node.type = "PerformActionUsage"
                self.ValuePart(node)
                self._effect_body(node, where)
                return node
        t = k[self.p]
        if t == "accept":
            # AcceptNodeDeclaration : AcceptActionUsage = ActionNodeUsageDeclaration? 'accept' AcceptParameterPart
            node.type = "AcceptActionUsage"
            self.p += 1
            self.AcceptParameterPart(node)
        elif t == "send":
            # SendNodeDeclaration : SendActionUsage = ActionNodeUsageDeclaration? 'send'
            # ownedRelationship += NodeParameterMember SenderReceiverPart?
            node.type = "SendActionUsage"
            self.SendNode(node)
        elif t == "assign":
            node.type = "AssignmentActionUsage"
            self.AssignmentNodeDeclaration(node)
        else:
            node.type = "PerformActionUsage"
            self.owned_reference(node)
            self.ValuePart(node)
        self._effect_body(node, where)
        return node

    def _effect_body(self, node: Node, where: str) -> None:
        if where == "state":
            self.ActionBody(node)
        elif self.accept("{"):
            self.items(node, lambda n: self.body_item(n, "action"))

    def state_transition_member(self, i: int, vis: str | None, t: str, node: Node) -> Node | None:
        """In a state body: EntryTransitionMember (after an entry action), TransitionUsageMember,
        TargetTransitionUsageMember, or SourceSuccessionMember with a behavior usage ('then' state ...).

        EntryTransitionMember : FeatureMembership = MemberPrefix ( ownedRelatedElement += GuardedTargetSuccession
        | 'then' ownedRelatedElement += TargetSuccession ) ';'
        TransitionUsageMember : FeatureMembership = MemberPrefix ownedRelatedElement += TransitionUsage
        TargetTransitionUsageMember : FeatureMembership = MemberPrefix ownedRelatedElement += TargetTransitionUsage"""
        k = self.k
        rels = node.props.get("ownedRelationship")
        after_entry = bool(rels) and id(rels[-1]) in self._entry_members
        j = self.p
        if t == "then" and not self._then_target():
            return self.then_member(i, vis, "state")
        if after_entry and t in ("then", "if"):
            if t == "then":
                succ = self.TargetSuccession()
            else:
                guard = self.GuardExpressionMember()
                self.expect("then")
                succ = Node("TransitionUsage", {"ownedRelationship": [guard, self.TransitionSuccessionMember()]})
            self.expect(";")
            self.fin(succ, j)
            m = self._member("FeatureMembership", i, vis, succ)
            self._entry_members.add(id(m))
            return m
        succ = Node("TransitionUsage")
        if t == "transition" and k[self.p + 1] not in ("accept", "if", "do", "then"):
            self.p += 1
            self.TransitionUsage(succ)
        else:
            self.TargetTransitionUsage(succ)
        self.fin(succ, j)
        return self._member("FeatureMembership", i, vis, succ)

    def TransitionUsage(self, node: Node) -> None:
        """TransitionUsage = 'transition' ( UsageDeclaration 'first' )?
        ownedRelationship += FeatureChainMember ownedRelationship += EmptyParameterMember
        ( ownedRelationship += EmptyParameterMember ownedRelationship += TriggerActionMember )?
        ( ownedRelationship += GuardExpressionMember )? ( ownedRelationship += EffectBehaviorMember )?
        'then' ownedRelationship += TransitionSuccessionMember ActionBody   ('transition' already consumed)"""
        k = self.k
        if k[self.p - 1] != "transition":
            self.expect("transition")
        if k[self.p] == "first":
            self.p += 1
        else:
            def declaration():
                self.UsageDeclaration(node)
                self.expect("first")
                return True
            save = dict(node.props)
            if not self.attempt(declaration):
                node.props = save
        node.add("ownedRelationship", self.FeatureChainMember())
        node.add("ownedRelationship", self.EmptyParameterMember())
        self._transition_tail(node)

    def TargetTransitionUsage(self, node: Node) -> None:
        """TargetTransitionUsage : TransitionUsage = ownedRelationship += EmptyParameterMember
        ( 'transition' ( ownedRelationship += EmptyParameterMember ownedRelationship += TriggerActionMember )?
        ( ownedRelationship += GuardExpressionMember )? ( ownedRelationship += EffectBehaviorMember )?
        | ownedRelationship += EmptyParameterMember ownedRelationship += TriggerActionMember
        ( ownedRelationship += GuardExpressionMember )? ( ownedRelationship += EffectBehaviorMember )?
        | ownedRelationship += GuardExpressionMember ( ownedRelationship += EffectBehaviorMember )? )?
        'then' ownedRelationship += TransitionSuccessionMember ActionBody"""
        node.add("ownedRelationship", self.EmptyParameterMember())
        self.accept("transition")
        self._transition_tail(node)

    def _transition_tail(self, node: Node) -> None:
        k = self.k
        if k[self.p] == "accept":
            node.add("ownedRelationship", self.EmptyParameterMember())
            node.add("ownedRelationship", self.TriggerActionMember())
        if k[self.p] == "if":
            node.add("ownedRelationship", self.GuardExpressionMember())
        if k[self.p] == "do":
            node.add("ownedRelationship", self.EffectBehaviorMember())
        self.expect("then")
        node.add("ownedRelationship", self.TransitionSuccessionMember())
        self.ActionBody(node)

    def TriggerActionMember(self) -> Node:
        """TriggerActionMember : TransitionFeatureMembership = 'accept' { kind = 'trigger' }
        ownedRelatedElement += TriggerAction
        TriggerAction : AcceptActionUsage = AcceptParameterPart"""
        i = self.expect("accept")
        j = self.p
        action = Node("AcceptActionUsage")
        self.AcceptParameterPart(action)
        self.fin(action, j)
        return self.new("TransitionFeatureMembership", i, {"kind": "trigger", "ownedRelatedElement": [action]})

    def EffectBehaviorMember(self) -> Node:
        """EffectBehaviorMember : TransitionFeatureMembership = 'do' { kind = 'effect' }
        ownedRelatedElement += EffectBehaviorUsage
        EffectBehaviorUsage : ActionUsage = EmptyActionUsage | TransitionPerformActionUsage
        | TransitionAcceptActionUsage | TransitionSendActionUsage | TransitionAssignmentActionUsage"""
        i = self.expect("do")
        j = self.p
        if self.k[j] == "then":
            action = self.empty("ActionUsage")
        else:
            action = self.fin(self.effect_action(j, "transition"), j)
        return self.new("TransitionFeatureMembership", i, {"kind": "effect", "ownedRelatedElement": [action]})

    # ---------------------------------------------- requirements and cases

    def requirement_member(self, i: int, vis: str | None, t: str, ctx: str) -> Node | None:
        """SubjectMember, ActorMember, StakeholderMember, ObjectiveMember, RequirementConstraintMember,
        FramedConcernMember and RequirementVerificationMember.

        SubjectMember : SubjectMembership = MemberPrefix ownedRelatedElement += SubjectUsage
        SubjectUsage : ReferenceUsage = 'subject' UsageExtensionKeyword* Usage
        ActorUsage : PartUsage = 'actor' UsageExtensionKeyword* Usage
        StakeholderUsage : PartUsage = 'stakeholder' UsageExtensionKeyword* Usage
        ObjectiveMember : ObjectiveMembership = MemberPrefix 'objective' ownedRelatedElement += ObjectiveRequirementUsage
        ObjectiveRequirementUsage : RequirementUsage = UsageExtensionKeyword* ConstraintUsageDeclaration RequirementBody
        RequirementConstraintMember : RequirementConstraintMembership = MemberPrefix? RequirementKind
        ownedRelatedElement += RequirementConstraintUsage
        RequirementKind : RequirementConstraintMembership = 'assume' { kind = 'assumption' }
        | 'require' { kind = 'requirement' }
        FramedConcernMember : FramedConcernMembership = MemberPrefix? 'frame' ownedRelatedElement += FramedConcernUsage
        RequirementVerificationMember : RequirementVerificationMembership = MemberPrefix 'verify'
        { kind = 'requirement' } ownedRelatedElement += RequirementVerificationUsage"""
        if ctx == "case" and t not in ("subject", "actor", "objective"):
            return None
        if ctx == "requirement" and t == "objective":
            return None
        self.p += 1
        j = self.p
        props: dict = {}
        if t in ("subject", "actor", "stakeholder"):
            el = Node({"subject": "ReferenceUsage"}.get(t, "PartUsage"))
            meta = self.prefix_metadata()
            if meta:
                el.props["ownedRelationship"] = meta
            self.Usage(el)
            mtype = {"subject": "SubjectMembership", "actor": "ActorMembership",
                     "stakeholder": "StakeholderMembership"}[t]
        elif t == "objective":
            el = Node("RequirementUsage")
            meta = self.prefix_metadata()
            if meta:
                el.props["ownedRelationship"] = meta
            self.ConstraintUsageDeclaration(el)
            self.RequirementBody(el)
            mtype = "ObjectiveMembership"
        elif t in ("assume", "require"):
            props["kind"] = "assumption" if t == "assume" else "requirement"
            el = self.constraint_member_usage("ConstraintUsage", "constraint", "calc")
            mtype = "RequirementConstraintMembership"
        elif t == "frame":
            el = self.constraint_member_usage("ConcernUsage", "concern", "requirement")
            mtype = "FramedConcernMembership"
        else:
            props["kind"] = "requirement"
            el = self.constraint_member_usage("RequirementUsage", "requirement", "requirement", "list")
            mtype = "RequirementVerificationMembership"
        self.fin(el, j)
        props["ownedRelatedElement"] = [el]
        m = self.new(mtype, i, props)
        if vis:
            m.props["visibility"] = vis
        return m

    def constraint_member_usage(self, type: str, keyword: str, body: str, spec: str = "part") -> Node:
        """RequirementConstraintUsage : ConstraintUsage = ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? RequirementBody | ( UsageExtensionKeyword* 'constraint'
        | UsageExtensionKeyword+ ) ConstraintUsageDeclaration CalculationBody
        (FramedConcernUsage and RequirementVerificationUsage alike, with 'concern' / 'requirement')"""
        el = Node(type)
        meta = self.prefix_metadata()
        if meta:
            el.props["ownedRelationship"] = meta
        if self.accept(keyword) or meta:
            self.ConstraintUsageDeclaration(el)
            self.body(el, body)
        else:
            self.owned_reference(el, spec)
            self.RequirementBody(el)
        return el

    def VariantUsageElement(self, ctx: str) -> Node:
        """VariantUsageElement : Usage = VariantReference | ReferenceUsage | AttributeUsage | ...
        VariantReference : ReferenceUsage = ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecialization* UsageBody"""
        k = self.k
        if k[self.p] in ("NAME", "$"):
            i = self.p
            node = Node("ReferenceUsage")
            self.owned_reference(node, "list")
            self.UsageBody(node)
            return self.fin(node, i)
        el, _ = self.element(ctx)
        return el

    def ViewRenderingUsage(self) -> Node:
        """ViewRenderingUsage : RenderingUsage = ownedRelationship += OwnedReferenceSubsetting
        FeatureSpecializationPart? UsageBody | ( UsageExtensionKeyword* 'rendering' | UsageExtensionKeyword+ ) Usage"""
        i = self.p
        node = Node("RenderingUsage")
        meta = self.prefix_metadata()
        if meta:
            node.props["ownedRelationship"] = meta
        if self.accept("rendering") or meta:
            self.Usage(node)
        else:
            self.owned_reference(node)
            self.UsageBody(node)
        return self.fin(node, i)

    # ------------------------------------------------------------ metadata

    def MetadataUsage(self, i: int, rels: list[Node]) -> Node:
        """MetadataUsage = UsageExtensionKeyword* ( '@' | 'metadata' ) MetadataUsageDeclaration
        ( 'about' ownedRelationship += Annotation ( ',' ownedRelationship += Annotation )* )? MetadataBody

        MetadataUsageDeclaration : MetadataUsage = ( Identification ( ':' | 'typed' 'by' ) )?
        ownedRelationship += OwnedFeatureTyping"""
        node = Node("MetadataUsage", {"ownedRelationship": list(rels)} if rels else {})
        self.p += 1
        self.MetadataFeatureDeclaration(node)
        if self.accept("about"):
            node.add("ownedRelationship", self.Annotation())
            while self.accept(","):
                node.add("ownedRelationship", self.Annotation())
        self.body(node, "metadata")
        return self.fin(node, i)

    def MetadataFeature(self) -> Node:
        """AnnotatingElement's MetadataUsage (with its UsageExtensionKeywords)."""
        i = self.p
        meta = self.prefix_metadata()
        if self.k[self.p] not in ("@", "metadata"):
            raise self.error("expected '@' or 'metadata'")
        return self.MetadataUsage(i, meta)

    def metadata_item(self, node: Node) -> None:
        """MetadataBody : Type = ';' | '{' ( ownedRelationship += DefinitionMember
        | ownedRelationship += MetadataBodyUsageMember | ownedRelationship += AliasMember
        | ownedRelationship += Import )* '}'

        MetadataBodyUsageMember : FeatureMembership = ownedMemberFeature = MetadataBodyUsage
        MetadataBodyUsage : ReferenceUsage = 'ref'? ( ':>>' | 'redefines' )? ownedRelationship += OwnedRedefinition
        FeatureSpecializationPart? ValuePart? MetadataBody"""
        k = self.k
        i = self.p
        t = k[i]
        if t in ("ref", ":>>", "redefines", "NAME"):
            node.add("ownedRelationship", self.MetadataBodyUsageMember())
            return
        vis = self.VisibilityIndicator()
        t = k[self.p]
        if t == "import":
            node.add("ownedRelationship", self.Import(i, vis))
        elif t == "alias":
            m = self.membership("Membership", vis)
            self.AliasMember(m)
            node.add("ownedRelationship", self.fin(m, i))
        else:
            el, is_usage = self.element("metadata")
            if is_usage:
                raise ParseError(i, "expected a definition or a redefinition in a metadata body")
            m = self.new("OwningMembership", i, {"ownedRelatedElement": [el]})
            if vis:
                m.props["visibility"] = vis
            node.add("ownedRelationship", m)

    def MetadataBodyUsageMember(self) -> Node:
        i = self.p
        node = Node("ReferenceUsage")
        self.accept("ref")
        if not self.accept(":>>"):
            self.accept("redefines")
        node.add("ownedRelationship", self.OwnedRedefinition())
        self.FeatureSpecializationPart(node)
        self.ValuePart(node)
        self.body(node, "metadata")
        self.fin(node, i)
        return Node("FeatureMembership", {"ownedRelatedElement": [node]}, node.span)

    # ----------------------------------------------------------- packages

    def Package(self, i: int, meta: list[Node], type: str = "Package") -> Node:
        """Package = ( ownedRelationship += PrefixMetadataMember )* PackageDeclaration PackageBody
        PackageDeclaration : Package = 'package' Identification"""
        node = Node(type, {"ownedRelationship": list(meta)} if meta else {})
        self.expect("package")
        self.Identification(node)
        self.PackageBody(node)
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
