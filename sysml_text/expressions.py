"""Expressions (KerML 8.2.5.8), shared by both languages.

Operator expressions are parsed with a Pratt parser using the precedence of
KerML Table 6 (highest to lowest): unary ``+ - ~ not``, extent ``all``;
binary ``^ **`` (right associative), ``* / %``, ``+ -``, ``..``,
``< > <= >=``, ``istype hastype @ @@ as meta``, ``== != === !==``,
``& and``, ``xor``, ``| or``, ``implies``, ``??``; then the conditional
``if ... ? ... else ...``. Primary expressions (feature chains ``.``,
``.?`` select, ``.{`` collect, ``->`` invocations, ``#( )`` indexing,
``[ ]`` brackets) bind tighter than any operator.

The tree follows the grammar exactly, including its wrappers: an operand is a
``ParameterMembership`` owning a ``Feature`` owning a ``FeatureValue`` owning
the operand expression (ArgumentMember), the right operand of a conditional
operator is additionally wrapped as an expression reference
(ArgumentExpressionMember), and operator and invocation expressions end with
an EmptyResultMember.
"""
from __future__ import annotations

from ._base import BaseParser, ParseError
from .ast import Node, Ref, Span

# Binding powers (higher binds tighter).
BP_NULL = 2      # ??
BP_IMPLIES = 3
BP_OR = 4        # | or
BP_XOR = 5
BP_AND = 6       # & and
BP_EQ = 7        # == != === !==
BP_CLASS = 8     # istype hastype @ @@ as meta
BP_REL = 9       # < > <= >=
BP_RANGE = 10    # ..
BP_ADD = 11      # + -
BP_MUL = 12      # * / %
BP_EXP = 13      # ^ ** (right associative)

# operator -> (binding power, kind); kind: "bin", "cond" (ConditionalBinaryOperator),
# "test" (classification test), "cast", "metatest", "metacast"
INFIX = {
    "??": (BP_NULL, "cond"), "implies": (BP_IMPLIES, "cond"),
    "|": (BP_OR, "bin"), "or": (BP_OR, "cond"), "xor": (BP_XOR, "bin"),
    "&": (BP_AND, "bin"), "and": (BP_AND, "cond"),
    "==": (BP_EQ, "bin"), "!=": (BP_EQ, "bin"), "===": (BP_EQ, "bin"), "!==": (BP_EQ, "bin"),
    "istype": (BP_CLASS, "test"), "hastype": (BP_CLASS, "test"), "@": (BP_CLASS, "test"),
    "as": (BP_CLASS, "cast"), "@@": (BP_CLASS, "metatest"), "meta": (BP_CLASS, "metacast"),
    "<": (BP_REL, "bin"), ">": (BP_REL, "bin"), "<=": (BP_REL, "bin"), ">=": (BP_REL, "bin"),
    "..": (BP_RANGE, "bin"),
    "+": (BP_ADD, "bin"), "-": (BP_ADD, "bin"),
    "*": (BP_MUL, "bin"), "/": (BP_MUL, "bin"), "%": (BP_MUL, "bin"),
    "^": (BP_EXP, "bin"), "**": (BP_EXP, "bin"),
}
UNARY = frozenset(("+", "-", "~", "not"))
CLASSIFICATION_PREFIX = frozenset(("istype", "hastype", "@", "as"))

#: tokens that can start an OwnedExpression
EXPRESSION_START = frozenset((
    "NAME", "$", "INT", "REAL", "STRING", "true", "false", "null", "*", "(", "{", "new", "if",
    "all", "+", "-", "~", "not", "istype", "hastype", "@", "as"))


def _wrap(expr: Node, member: str) -> Node:
    """member( Feature( FeatureValue( expr ) ) ): ArgumentMember, PrimaryArgumentMember, ..."""
    sp = expr.span
    fv = Node("FeatureValue", {"ownedRelatedElement": [expr]}, sp)
    f = Node("Feature", {"ownedRelationship": [fv]}, sp)
    return Node(member, {"ownedRelatedElement": [f]}, sp)


class ExpressionParser(BaseParser):
    """Pratt parser for OwnedExpression and the primary expression forms."""

    #: KerML: ArgumentExpressionMember : FeatureMembership; SysML: ParameterMembership
    ARGUMENT_EXPRESSION_MEMBERSHIP = "FeatureMembership"

    # -------------------------------------------------------------- members

    def ArgumentMember(self, expr: Node) -> Node:
        """ArgumentMember : ParameterMembership = ownedMemberParameter = Argument
        Argument : Feature = ownedRelationship += ArgumentValue
        ArgumentValue : FeatureValue = value = OwnedExpression"""
        return _wrap(expr, "ParameterMembership")

    def ArgumentExpressionMember(self, expr: Node) -> Node:
        """ArgumentExpressionMember : FeatureMembership = ownedRelatedElement += ArgumentExpression
        ArgumentExpression : Feature = ownedRelationship += ArgumentExpressionValue
        ArgumentExpressionValue : FeatureValue = value = OwnedExpressionReference"""
        ref = self.OwnedExpressionReference(expr)
        return _wrap(ref, self.ARGUMENT_EXPRESSION_MEMBERSHIP)

    def OwnedExpressionReference(self, expr: Node) -> Node:
        """OwnedExpressionReference : FeatureReferenceExpression = ownedRelationship += OwnedExpressionMember
        OwnedExpressionMember : FeatureMembership = ownedFeatureMember = OwnedExpression"""
        sp = expr.span
        member = Node("FeatureMembership", {"ownedRelatedElement": [expr]}, sp)
        return Node("FeatureReferenceExpression", {"ownedRelationship": [member]}, sp)

    def EmptyResultMember(self) -> Node:
        """EmptyResultMember : ReturnParameterMembership = ownedRelatedElement += EmptyFeature
        EmptyFeature : Feature = { }"""
        f = self.empty("Feature")
        return Node("ReturnParameterMembership", {"ownedRelatedElement": [f]}, f.span)

    def TypeReferenceMember(self, result: bool = False) -> Node:
        """TypeReferenceMember : ParameterMembership = ownedMemberFeature = TypeReference
        TypeResultMember : ReturnParameterMembership = ownedMemberFeature = TypeReference
        TypeReference : Feature = ownedRelationship += ReferenceTyping
        ReferenceTyping : FeatureTyping = type = [QualifiedName]"""
        ref = self.QualifiedName()
        sp = ref.span
        typing = Node("FeatureTyping", {"type": ref}, sp)
        f = Node("Feature", {"ownedRelationship": [typing]}, sp)
        return Node("ReturnParameterMembership" if result else "ParameterMembership",
                    {"ownedRelatedElement": [f]}, sp)

    def _op(self, op: str, i: int, rels: list[Node], type: str = "OperatorExpression") -> Node:
        return Node(type, {"operator": op, "ownedRelationship": rels}, self.span(i))

    # ---------------------------------------------------------- operators

    def OwnedExpression(self) -> Node:
        """OwnedExpression : Expression = ConditionalExpression | ConditionalBinaryOperatorExpression
        | BinaryOperatorExpression | UnaryOperatorExpression | ClassificationExpression
        | MetaclassificationExpression | ExtentExpression | PrimaryExpression"""
        return self.expression(0)

    def expression(self, min_bp: int) -> Node:
        """Operator expressions binding tighter than ``min_bp`` (Pratt loop)."""
        k = self.k
        i = self.p
        if k[i] == "if":
            return self.ConditionalExpression()
        left = self.unary()
        while True:
            op = k[self.p]
            info = INFIX.get(op)
            if info is None:
                return left
            bp, kind = info
            if bp <= min_bp:
                return left
            self.p += 1
            if kind == "bin":
                # BinaryOperatorExpression; ^ and ** are right associative
                right = self.expression(bp - 1 if bp == BP_EXP else bp)
                left = self._op(op, i, [self.ArgumentMember(left), self.ArgumentMember(right),
                                        self.EmptyResultMember()])
            elif kind == "cond":
                # ConditionalBinaryOperatorExpression
                right = self.expression(bp)
                left = self._op(op, i, [self.ArgumentMember(left), self.ArgumentExpressionMember(right),
                                        self.EmptyResultMember()])
            elif kind == "test" or kind == "cast":
                # ClassificationExpression
                tref = self.TypeReferenceMember(result=kind == "cast")
                left = self._op(op, i, [self.ArgumentMember(left), tref, self.EmptyResultMember()])
            else:
                # MetaclassificationExpression: the operand is a MetadataReference
                arg = self.MetadataArgumentMember(left, i)
                tref = self.TypeReferenceMember(result=kind == "metacast")
                left = self._op(op, i, [arg, tref, self.EmptyResultMember()])

    def ConditionalExpression(self) -> Node:
        """ConditionalExpression : OperatorExpression = operator = 'if'
        ownedRelationship += ArgumentMember '?' ownedRelationship += ArgumentExpressionMember 'else'
        ownedRelationship += ArgumentExpressionMember ownedRelationship += EmptyResultMember"""
        i = self.expect("if")
        cond = self.expression(BP_NULL - 1)
        self.expect("?")
        then = self.OwnedExpression()
        self.expect("else")
        other = self.OwnedExpression()
        return self._op("if", i, [self.ArgumentMember(cond), self.ArgumentExpressionMember(then),
                                  self.ArgumentExpressionMember(other), self.EmptyResultMember()])

    def MetadataArgumentMember(self, left: Node, i: int) -> Node:
        """MetadataArgumentMember : ParameterMembership = ownedRelatedElement += MetadataArgument
        MetadataArgument : Feature = ownedRelationship += MetadataValue
        MetadataValue : FeatureValue = value = MetadataReference
        MetadataReference : MetadataAccessExpression = ownedRelationship += ElementReferenceMember"""
        ref = None
        if left.type == "FeatureReferenceExpression":
            member = left.props["ownedRelationship"][0]
            ref = member.props.get("memberElement")
        if not isinstance(ref, Ref):
            raise ParseError(i, "expected a qualified name before a metaclassification operator")
        erm = Node("Membership", {"memberElement": ref}, ref.span)
        mref = Node("MetadataAccessExpression", {"ownedRelationship": [erm]}, ref.span)
        return _wrap(mref, "ParameterMembership")

    def unary(self) -> Node:
        """UnaryOperatorExpression : OperatorExpression = operator = UnaryOperator
        ownedRelationship += ArgumentMember ownedRelationship += EmptyResultMember
        | ExtentExpression | ClassificationExpression (without operand) | PrimaryExpression"""
        k = self.k
        i = self.p
        t = k[i]
        if t in UNARY:
            self.p += 1
            operand = self.unary()
            return self._op(t, i, [self.ArgumentMember(operand), self.EmptyResultMember()])
        if t == "all":
            # ExtentExpression : OperatorExpression = operator = 'all' ownedRelationship += TypeReferenceMember
            self.p += 1
            return self._op("all", i, [self.TypeReferenceMember()])
        if t in CLASSIFICATION_PREFIX:
            # ClassificationExpression without its optional ArgumentMember
            self.p += 1
            tref = self.TypeReferenceMember(result=t == "as")
            return self._op(t, i, [tref, self.EmptyResultMember()])
        return self.PrimaryExpression()

    # ------------------------------------------------------------ primaries

    def PrimaryExpression(self) -> Node:
        """PrimaryExpression : Expression = FeatureChainExpression | NonFeatureChainPrimaryExpression

        A BaseExpression or SequenceExpression followed by any number of
        '.' FeatureChainMember, '.' BodyExpression (collect), '.?' BodyExpression
        (select), '#' '(' ... ')' (index), '[' ... ']' (bracket) and '->' invocations."""
        k = self.k
        i = self.p
        left = self.BaseExpression()
        while True:
            t = k[self.p]
            if t == ".":
                nt = k[self.p + 1]
                if nt == "{":
                    # CollectExpression = ownedRelationship += PrimaryArgumentMember '.'
                    # ownedRelationship += BodyArgumentMember
                    self.p += 1
                    body = _wrap(self.BodyExpression(), "ParameterMembership")
                    left = Node("CollectExpression",
                                {"ownedRelationship": [_wrap(left, "ParameterMembership"), body]},
                                self.span(i))
                elif nt == "NAME" or nt == "$":
                    # FeatureChainExpression = ownedRelationship += NonFeatureChainPrimaryArgumentMember
                    # '.' ownedRelationship += FeatureChainMember
                    self.p += 1
                    member = self.FeatureChainMember()
                    left = Node("FeatureChainExpression",
                                {"ownedRelationship": [_wrap(left, "ParameterMembership"), member]},
                                self.span(i))
                else:
                    return left
            elif t == ".?":
                # SelectExpression = ownedRelationship += PrimaryArgumentMember '.?'
                # ownedRelationship += BodyArgumentMember
                self.p += 1
                body = _wrap(self.BodyExpression(), "ParameterMembership")
                left = Node("SelectExpression",
                            {"ownedRelationship": [_wrap(left, "ParameterMembership"), body]}, self.span(i))
            elif t == "#" and k[self.p + 1] == "(":
                # IndexExpression = ownedRelationship += PrimaryArgumentMember '#'
                # '(' ownedRelationship += SequenceExpressionListMember ')'
                self.p += 2
                lst = self.SequenceExpressionListMember(")")
                self.expect(")")
                left = Node("IndexExpression", {"ownedRelationship": [_wrap(left, "ParameterMembership"), lst]},
                            self.span(i))
            elif t == "[":
                # BracketExpression : OperatorExpression = ownedRelationship += PrimaryArgumentMember
                # operator = '[' ownedRelationship += SequenceExpressionListMember ']'
                self.p += 1
                lst = self.SequenceExpressionListMember("]")
                self.expect("]")
                left = self._op("[", i, [_wrap(left, "ParameterMembership"), lst])
            elif t == "->":
                left = self.FunctionOperationExpression(left, i)
            else:
                return left

    def FunctionOperationExpression(self, left: Node, i: int) -> Node:
        """FunctionOperationExpression : InvocationExpression = ownedRelationship += PrimaryArgumentMember
        '->' ownedRelationship += InstantiatedTypeMember
        ( ownedRelationship += BodyArgumentMember | ownedRelationship += FunctionReferenceArgumentMember
        | ArgumentList ) ownedRelationship += EmptyResultMember"""
        self.expect("->")
        node = Node("InvocationExpression", {"ownedRelationship": [_wrap(left, "ParameterMembership"),
                                                                   self.InstantiatedTypeMember()]})
        t = self.k[self.p]
        if t == "{":
            node.add("ownedRelationship", _wrap(self.BodyExpression(), "ParameterMembership"))
        elif t == "(":
            self.ArgumentList(node)
        elif t == "NAME" or t == "$":
            node.add("ownedRelationship", self.FunctionReferenceArgumentMember())
        else:
            raise self.error("expected '{', '(' or a function name")
        node.add("ownedRelationship", self.EmptyResultMember())
        return self.fin(node, i)

    def FunctionReferenceArgumentMember(self) -> Node:
        """FunctionReferenceArgumentMember : ParameterMembership = ownedMemberParameter = FunctionReferenceArgument
        FunctionReferenceArgument : Feature = ownedRelationship += FunctionReferenceArgumentValue
        FunctionReferenceArgumentValue : FeatureValue = value = FunctionReferenceExpression
        FunctionReferenceExpression : FeatureReferenceExpression = ownedRelationship += FunctionReferenceMember
        FunctionReferenceMember : FeatureMembership = ownedMemberFeature = FunctionReference
        FunctionReference : Expression = ownedRelationship += ReferenceTyping"""
        ref = self.QualifiedName()
        sp = ref.span
        typing = Node("FeatureTyping", {"type": ref}, sp)
        fref = Node("Expression", {"ownedRelationship": [typing]}, sp)
        member = Node("FeatureMembership", {"ownedRelatedElement": [fref]}, sp)
        expr = Node("FeatureReferenceExpression", {"ownedRelationship": [member]}, sp)
        return _wrap(expr, "ParameterMembership")

    def FeatureChainMember(self) -> Node:
        """FeatureChainMember : Membership = FeatureReferenceMember | OwnedFeatureChainMember

        FeatureReferenceMember : Membership = memberElement = FeatureReference
        OwnedFeatureChainMember : OwningMembership = ownedMemberElement = FeatureChain"""
        i = self.p
        ref = self.QualifiedName()
        if self.k[self.p] == "." and self.scan_qn(self.p + 1) > 0:
            chain = self.FeatureChain(i)
            return Node("OwningMembership", {"ownedRelatedElement": [chain]}, chain.span)
        return Node("Membership", {"memberElement": ref}, ref.span)

    def InstantiatedTypeMember(self) -> Node:
        """InstantiatedTypeMember : Membership = memberElement = InstantiatedTypeReference
        | OwnedFeatureChainMember"""
        return self.FeatureChainMember()

    def SequenceExpressionListMember(self, close: str) -> Node:
        """SequenceExpressionListMember : FeatureMembership = ownedMemberFeature = SequenceExpressionList"""
        expr = self.SequenceExpressionList(close)
        return Node("FeatureMembership", {"ownedRelatedElement": [expr]}, expr.span)

    def SequenceExpressionList(self, close: str = ")") -> Node:
        """SequenceExpressionList : Expression = OwnedExpression ','? | SequenceOperatorExpression

        SequenceOperatorExpression : OperatorExpression = ownedRelationship += OwnedExpressionMember
        operator = ',' ownedRelationship += SequenceExpressionListMember"""
        i = self.p
        first = self.OwnedExpression()
        if self.k[self.p] != ",":
            return first
        self.p += 1
        if self.k[self.p] == close:
            return first
        rest = self.SequenceExpressionListMember(close)
        member = Node("FeatureMembership", {"ownedRelatedElement": [first]}, first.span)
        return self._op(",", i, [member, rest])

    def BaseExpression(self) -> Node:
        """BaseExpression : Expression = NullExpression | LiteralExpression | FeatureReferenceExpression
        | MetadataAccessExpression | InvocationExpression | ConstructorExpression | BodyExpression
        (and SequenceExpression = '(' SequenceExpressionList ')')"""
        k = self.k
        i = self.p
        t = k[i]
        if t == "NAME" or t == "$":
            q = self.scan_qn(i)
            nt = k[q]
            if nt == "(":
                return self.InvocationExpression()
            if nt == ".":
                if k[q + 1] == "metadata":
                    return self.MetadataAccessExpression()
                end, n = self.scan_chain(i)
                if n > 1 and k[end] == "(":
                    return self.InvocationExpression()
            return self.FeatureReferenceExpression()
        if t == "(":
            if k[i + 1] == ")":
                # NullExpression = 'null' | '(' ')'
                self.p += 2
                return self.new("NullExpression", i)
            self.p += 1
            expr = self.SequenceExpressionList(")")
            self.expect(")")
            return expr
        if t == "null":
            self.p += 1
            return self.new("NullExpression", i)
        if t == "{":
            return self.BodyExpression()
        if t == "new":
            return self.ConstructorExpression()
        return self.LiteralExpression()

    def LiteralExpression(self) -> Node:
        """LiteralExpression = LiteralBoolean | LiteralString | LiteralInteger | LiteralReal | LiteralInfinity"""
        i = self.p
        t = self.k[i]
        if t == "INT":
            type = "LiteralInteger"
        elif t == "REAL":
            type = "LiteralRational"
        elif t == "STRING":
            type = "LiteralString"
        elif t == "true" or t == "false":
            self.p += 1
            return Node("LiteralBoolean", {"value": t == "true"}, Span(self.s[i], self.e[i], self.src))
        elif t == "*":
            self.p += 1
            return Node("LiteralInfinity", {}, Span(self.s[i], self.e[i], self.src))
        else:
            raise self.error("expected an expression")
        self.p += 1
        return Node(type, {"value": self.v[i]}, Span(self.s[i], self.e[i], self.src))

    def FeatureReferenceExpression(self) -> Node:
        """FeatureReferenceExpression : FeatureReferenceExpression = ownedRelationship += FeatureReferenceMember
        ownedRelationship += EmptyResultMember
        FeatureReferenceMember : Membership = memberElement = FeatureReference"""
        ref = self.QualifiedName()
        member = Node("Membership", {"memberElement": ref}, ref.span)
        return Node("FeatureReferenceExpression", {"ownedRelationship": [member, self.EmptyResultMember()]},
                    ref.span)

    def MetadataAccessExpression(self) -> Node:
        """MetadataAccessExpression = ownedRelationship += ElementReferenceMember '.' 'metadata'
        ElementReferenceMember : Membership = memberElement = [QualifiedName]"""
        i = self.p
        ref = self.QualifiedName()
        self.expect(".")
        self.expect("metadata")
        member = Node("Membership", {"memberElement": ref}, ref.span)
        return self.new("MetadataAccessExpression", i, {"ownedRelationship": [member]})

    def InvocationExpression(self) -> Node:
        """InvocationExpression : InvocationExpression = ownedRelationship += InstantiatedTypeMember
        ArgumentList ownedRelationship += EmptyResultMember"""
        i = self.p
        node = Node("InvocationExpression", {"ownedRelationship": [self.InstantiatedTypeMember()]})
        self.ArgumentList(node)
        node.add("ownedRelationship", self.EmptyResultMember())
        return self.fin(node, i)

    def ConstructorExpression(self) -> Node:
        """ConstructorExpression = 'new' ownedRelationship += InstantiatedTypeMember
        ownedRelationship += ConstructorResultMember
        ConstructorResultMember : ReturnParameterMembership = ownedRelatedElement += ConstructorResult
        ConstructorResult : Feature = ArgumentList"""
        i = self.expect("new")
        node = Node("ConstructorExpression", {"ownedRelationship": [self.InstantiatedTypeMember()]})
        j = self.p
        result = Node("Feature")
        self.ArgumentList(result)
        self.fin(result, j)
        node.add("ownedRelationship", Node("ReturnParameterMembership", {"ownedRelatedElement": [result]},
                                           result.span))
        return self.fin(node, i)

    def ArgumentList(self, node: Node) -> None:
        """ArgumentList : Feature = '(' ( PositionalArgumentList | NamedArgumentList )? ')'

        PositionalArgumentList : Feature = ownedRelationship += ArgumentMember
        ( ',' ownedRelationship += ArgumentMember )*
        NamedArgumentList : Feature = ownedRelationship += NamedArgumentMember
        ( ',' ownedRelationship += NamedArgumentMember )*"""
        self.expect("(")
        k = self.k
        if k[self.p] == ")":
            self.p += 1
            return
        named = k[self.p] in ("NAME", "$") and k[self.scan_qn(self.p)] == "="
        while True:
            if named:
                node.add("ownedRelationship", self.NamedArgumentMember())
            else:
                node.add("ownedRelationship", self.ArgumentMember(self.OwnedExpression()))
            if not self.accept(","):
                break
        self.expect(")")

    def NamedArgumentMember(self) -> Node:
        """NamedArgumentMember : FeatureMembership = ownedMemberFeature = NamedArgument
        NamedArgument : Feature = ownedRelationship += ParameterRedefinition '='
        ownedRelationship += ArgumentValue
        ParameterRedefinition : Redefinition = redefinedFeature = [QualifiedName]"""
        i = self.p
        ref = self.QualifiedName()
        redef = Node("Redefinition", {"redefinedFeature": ref}, ref.span)
        self.expect("=")
        expr = self.OwnedExpression()
        value = Node("FeatureValue", {"ownedRelatedElement": [expr]}, expr.span)
        arg = self.new("Feature", i, {"ownedRelationship": [redef, value]})
        return Node("FeatureMembership", {"ownedRelatedElement": [arg]}, arg.span)

    def BodyExpression(self) -> Node:
        """BodyExpression : FeatureReferenceExpression = ownedRelationship += ExpressionBodyMember
        ExpressionBodyMember : FeatureMembership = ownedMemberFeature = ExpressionBody
        ExpressionBody : Expression = '{' FunctionBodyPart '}'"""
        i = self.expect("{")
        body = Node("Expression")
        self.FunctionBodyPart(body)
        self.fin(body, i)
        member = Node("FeatureMembership", {"ownedRelatedElement": [body]}, body.span)
        return Node("FeatureReferenceExpression", {"ownedRelationship": [member]}, body.span)

    def FunctionBodyPart(self, node: Node) -> None:  # pragma: no cover - per language
        raise NotImplementedError

    # --------------------------------------------- result expressions in bodies

    def result_expression(self, node: Node, member_prefix: bool = True) -> bool:
        """ResultExpressionMember : ResultExpressionMembership = MemberPrefix ownedRelatedElement += OwnedExpression

        Tried at a body item that could start an expression: it is the result
        expression only if it is followed by the closing '}' of the body."""
        k = self.k
        i = self.p
        vis = None
        if member_prefix and k[i] in ("public", "private", "protected"):
            vis = k[i]
            self.p += 1
        if k[self.p] not in EXPRESSION_START:
            self.p = i
            return False
        expr = self.attempt(self._expression_then_close)
        if expr is None:
            self.p = i
            return False
        member = self.new("ResultExpressionMembership", i, {"ownedRelatedElement": [expr]})
        if vis:
            member.props["visibility"] = vis
        node.add("ownedRelationship", member)
        return True

    def _expression_then_close(self) -> Node:
        expr = self.OwnedExpression()
        if self.k[self.p] != "}":
            raise self.error("expected '}'")
        return expr

