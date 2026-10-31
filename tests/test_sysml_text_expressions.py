"""Expressions (KerML 8.2.5.8): operator precedence and associativity (Table 6), primary forms,
and the grammar's argument wrappers."""
import unittest

from sysml_text import parse


def value_of(text, language="sysml"):
    """The expression of ``attribute v = <text>;`` (``feature v = <text>;`` in KerML)."""
    kw = "attribute" if language == "sysml" else "feature"
    r = parse(f"{kw} v = {text};", language)
    assert not r.diagnostics, r.diagnostics
    feature = r.root["ownedRelationship"][0]["ownedRelatedElement"][0]
    value = [m for m in feature["ownedRelationship"] if m.type == "FeatureValue"][0]
    return value["ownedRelatedElement"][0]


def arg(member):
    """The operand held by an argument member (ArgumentMember, ArgumentExpressionMember, ...)."""
    f = member["ownedRelatedElement"][0]
    rels = f.get("ownedRelationship", [])
    if f.type == "Feature" and rels and rels[0].type == "FeatureValue":
        return sx(rels[0]["ownedRelatedElement"][0])
    if f.type == "Feature" and rels and rels[0].type == "FeatureTyping":
        return ":" + rels[0]["type"].text
    return sx(f)


def is_empty_result(member):
    return member.type == "ReturnParameterMembership" and not member["ownedRelatedElement"][0].props


def sx(e):
    """An s-expression for an expression tree."""
    t = e.type
    rels = [m for m in e.get("ownedRelationship", []) if not is_empty_result(m)]
    if t == "OperatorExpression":
        return "(" + " ".join([e["operator"]] + [arg(m) for m in rels]) + ")"
    if t == "FeatureReferenceExpression":
        m = rels[0]
        if m.type == "Membership":
            return m["memberElement"].text
        inner = m["ownedRelatedElement"][0]
        if inner.type == "Expression":  # body expression
            return "{" + " ".join(arg(x) if x.type != "ResultExpressionMembership"
                                  else sx(x["ownedRelatedElement"][0]) for x in inner.get("ownedRelationship", [])
                                  if x.type in ("ResultExpressionMembership",)) + "}"
        return sx(inner)  # expression reference (lazy operand)
    if t in ("LiteralInteger", "LiteralRational", "LiteralString", "LiteralBoolean"):
        return repr(e["value"])
    if t == "LiteralInfinity":
        return "*"
    if t == "NullExpression":
        return "null"
    if t in ("FeatureChainExpression",):
        member = rels[1]
        if member.type == "Membership":
            target = member["memberElement"].text
        else:
            chain = member["ownedRelatedElement"][0]
            target = ".".join(c["chainingFeature"].text for c in chain["ownedRelationship"])
        return f"(. {arg(rels[0])} {target})"
    if t in ("InvocationExpression", "ConstructorExpression"):
        head = rels[1 if rels[0].type == "ParameterMembership" else 0]
        name = head["memberElement"].text if "memberElement" in head.props else "chain"
        args = []
        for m in rels:
            if m is head:
                continue
            if m.type == "ReturnParameterMembership":  # constructor result: ArgumentList
                args += [arg(x) for x in m["ownedRelatedElement"][0].get("ownedRelationship", [])]
            elif m.type == "FeatureMembership":  # named argument
                f = m["ownedRelatedElement"][0]
                redef, value = f["ownedRelationship"]
                args.append(f"{redef['redefinedFeature'].text}={sx(value['ownedRelatedElement'][0])}")
            else:
                args.append(arg(m))
        return f"({'new ' if t == 'ConstructorExpression' else 'call '}{name} {' '.join(args)})".replace(" )", ")")
    if t in ("IndexExpression", "CollectExpression", "SelectExpression"):
        op = {"IndexExpression": "#", "CollectExpression": "collect", "SelectExpression": "select"}[t]
        second = rels[1]
        inner = arg(second) if second["ownedRelatedElement"][0].type == "Feature" else \
            sx(second["ownedRelatedElement"][0])
        return f"({op} {arg(rels[0])} {inner})"
    if t == "MetadataAccessExpression":
        return f"(metadata {rels[0]['memberElement'].text})"
    raise AssertionError(f"unexpected {t}")


def s(text, language="sysml"):
    return sx(value_of(text, language))


class PrecedenceTests(unittest.TestCase):

    def test_arithmetic(self):
        self.assertEqual(s("a + b * c"), "(+ a (* b c))")
        self.assertEqual(s("(a + b) * c"), "(* (+ a b) c)")
        self.assertEqual(s("a * b % c / d"), "(/ (% (* a b) c) d)")

    def test_left_associativity(self):
        self.assertEqual(s("a - b - c"), "(- (- a b) c)")
        self.assertEqual(s("a / b / c"), "(/ (/ a b) c)")

    def test_exponentiation_is_right_associative(self):
        self.assertEqual(s("a ** b ** c"), "(** a (** b c))")
        self.assertEqual(s("a ^ b * c"), "(* (^ a b) c)")

    def test_unary_binds_tighter_than_exponentiation(self):
        self.assertEqual(s("-a ** 2"), "(** (- a) 2)")
        self.assertEqual(s("not a and b"), "(and (not a) b)")
        self.assertEqual(s("- - a"), "(- (- a))")

    def test_range_comparison_classification_equality(self):
        self.assertEqual(s("1 .. n + 1"), "(.. 1 (+ n 1))")
        self.assertEqual(s("a < b == c > d"), "(== (< a b) (> c d))")
        self.assertEqual(s("x istype T == y"), "(== (istype x :T) y)")
        self.assertEqual(s("x as T"), "(as x :T)")

    def test_logical_operators(self):
        # & and | or xor: and > xor > or > implies > ??
        self.assertEqual(s("a or b and c"), "(or a (and b c))")
        self.assertEqual(s("a | b xor c & d"), "(| a (xor b (& c d)))")
        self.assertEqual(s("a implies b or c"), "(implies a (or b c))")
        self.assertEqual(s("a ?? b implies c"), "(?? a (implies b c))")
        self.assertEqual(s("a and b and c"), "(and (and a b) c)")

    def test_conditional(self):
        self.assertEqual(s("if a or b ? 1 else 2"), "(if (or a b) 1 2)")
        self.assertEqual(s("if a ? 1 else if b ? 2 else 3"), "(if a 1 (if b 2 3))")
        self.assertEqual(s("if a ? x + 1 else y * 2"), "(if a (+ x 1) (* y 2))")

    def test_classification_without_operand(self):
        self.assertEqual(s("@Safety and istype Part"), "(and (@ :Safety) (istype :Part))")

    def test_metaclassification(self):
        self.assertEqual(s("x @@ SysML::PartUsage"), "(@@ (metadata x) :SysML::PartUsage)")
        self.assertEqual(s("x meta SysML::PartUsage"), "(meta (metadata x) :SysML::PartUsage)")


class OperandWrapperTests(unittest.TestCase):

    def test_binary_operands_are_argument_members(self):
        e = value_of("a + 1")
        first, second, result = e["ownedRelationship"]
        self.assertEqual([first.type, second.type, result.type],
                         ["ParameterMembership", "ParameterMembership", "ReturnParameterMembership"])
        feature = first["ownedRelatedElement"][0]
        self.assertEqual(feature.type, "Feature")
        self.assertEqual(feature["ownedRelationship"][0].type, "FeatureValue")

    def test_conditional_operands_are_expression_references(self):
        e = value_of("a and b")
        lazy = e["ownedRelationship"][1]
        self.assertEqual(lazy.type, "ParameterMembership")  # SysML ArgumentExpressionMember
        ref = lazy["ownedRelatedElement"][0]["ownedRelationship"][0]["ownedRelatedElement"][0]
        self.assertEqual(ref.type, "FeatureReferenceExpression")
        self.assertEqual(ref["ownedRelationship"][0].type, "FeatureMembership")
        kerml = value_of("a and b", "kerml")["ownedRelationship"][1]
        self.assertEqual(kerml.type, "FeatureMembership")  # KerML ArgumentExpressionMember

    def test_extent_has_no_result_member(self):
        e = value_of("all T")
        self.assertEqual(e["operator"], "all")
        self.assertEqual(len(e["ownedRelationship"]), 1)


class PrimaryExpressionTests(unittest.TestCase):

    def test_literals(self):
        self.assertEqual(s("1"), "1")
        self.assertEqual(s("2.5e3"), "2500.0")
        self.assertEqual(s('"text"'), "'text'")
        self.assertEqual(s("true"), "True")
        self.assertEqual(s("*"), "*")
        self.assertEqual(s("null"), "null")
        self.assertEqual(s("()"), "null")
        self.assertEqual(value_of("1.5").type, "LiteralRational")

    def test_feature_chains(self):
        self.assertEqual(s("a.b"), "(. a b)")
        self.assertEqual(s("a.b.c"), "(. a b.c)")
        self.assertEqual(s("A::x.y"), "(. A::x y)")
        self.assertEqual(s("f(x).y"), "(. (call f x) y)")

    def test_invocations(self):
        self.assertEqual(s("f(1, x)"), "(call f 1 x)")
        self.assertEqual(s("f(a = 1, b = 2)"), "(call f a=1 b=2)")
        self.assertEqual(s("f()"), "(call f)")
        self.assertEqual(s("new T(1)"), "(new T 1)")
        self.assertEqual(s("a.b(1)"), "(call chain 1)")

    def test_arrow_invocations(self):
        self.assertEqual(s("xs->size()"), "(call size xs)")
        self.assertEqual(s("a.b->including(c)"), "(call including (. a b) c)")
        e = value_of("xs->forAll { in x; x > 0 }")
        self.assertEqual(e.type, "InvocationExpression")
        body = e["ownedRelationship"][2]["ownedRelatedElement"][0]["ownedRelationship"][0]["ownedRelatedElement"][0]
        self.assertEqual(body.type, "FeatureReferenceExpression")  # BodyExpression
        expr = body["ownedRelationship"][0]["ownedRelatedElement"][0]
        self.assertEqual(expr.type, "Expression")
        self.assertEqual([m.type for m in expr["ownedRelationship"]],
                         ["FeatureMembership", "ResultExpressionMembership"])

    def test_function_reference_argument(self):
        e = value_of("xs->reduce '+'")
        fref = e["ownedRelationship"][2]["ownedRelatedElement"][0]["ownedRelationship"][0]
        expr = fref["ownedRelatedElement"][0]
        self.assertEqual(expr.type, "FeatureReferenceExpression")
        function = expr["ownedRelationship"][0]["ownedRelatedElement"][0]
        self.assertEqual(function["ownedRelationship"][0]["type"].text, "'+'")

    def test_index_bracket_select_collect(self):
        self.assertEqual(s("a#(1)"), "(# a 1)")
        self.assertEqual(s("5 [kg]"), "([ 5 kg)")
        self.assertEqual(s("9.81 [m/s^2]"), "([ 9.81 (/ m (^ s 2)))")
        self.assertEqual(s("xs.?{in x; x > 1}"), "(select xs {(> x 1)})")
        self.assertEqual(s("xs.{in x; x * 2}"), "(collect xs {(* x 2)})")

    def test_sequences(self):
        self.assertEqual(s("(1, 2, 3)"), "(, 1 (, 2 3))")
        self.assertEqual(s("(1,)"), "1")
        self.assertEqual(s("(a)"), "a")

    def test_metadata_access(self):
        self.assertEqual(s("x.metadata"), "(metadata x)")

    def test_global_scope_name(self):
        ref = value_of("$::A::b")["ownedRelationship"][0]["memberElement"]
        self.assertTrue(ref.is_global)
        self.assertEqual(ref.names, ("A", "b"))


if __name__ == "__main__":
    unittest.main()
