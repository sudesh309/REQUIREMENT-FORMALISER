"""Printer from the spec-shaped AST to canonical text: formatting, AST round trip, the view interface."""
import textwrap
import time
import unittest

from sysml_text import Node, PrintError, Ref, diff, parse, print_tree
from sysml_text.printer import Printer
from tools.conformance.metrics import printer as printer_metric


def fmt(text, language="sysml"):
    r = parse(text, language)
    assert not r.diagnostics, [str(d) for d in r.diagnostics]
    return print_tree(r.root, language)


def expect(text):
    return textwrap.dedent(text).lstrip("\n")


class FormattingTests(unittest.TestCase):

    def test_layout_and_short_forms(self):
        self.assertEqual(fmt("package P{part def A specializes B{attribute x defined by Real=1.5[kg];}}"), expect("""
            package P {
                part def A :> B {
                    attribute x : Real = 1.5 [kg];
                }
            }
            """))
        self.assertEqual(fmt("part p subsets q redefines r references s crosses t;"),
                         "part p :> q :>> r ::> s => t;\n")
        self.assertEqual(fmt("class A specializes B, C;", "kerml"), "class A :> B, C;\n")

    def test_members_with_bodies_are_set_off(self):
        self.assertEqual(fmt("part def A; part def B { part x; } part def C;"), expect("""
            part def A;

            part def B {
                part x;
            }

            part def C;
            """))

    def test_names(self):
        self.assertEqual(fmt("part 'my part' : 'part'; attribute 'it\\'s' : T; part 'plain';"),
                         "part 'my part' : 'part';\nattribute 'it\\'s' : T;\npart plain;\n")
        # 'part' is a name in KerML, 'type' in SysML
        self.assertEqual(fmt("feature 'part' : 'type';", "kerml"), "feature part : 'type';\n")
        self.assertEqual(fmt("attribute 'type' : T;"), "attribute type : T;\n")
        self.assertEqual(fmt("requirement def <'R1'> 'Mass Req';"), "requirement def <R1> 'Mass Req';\n")

    def test_references_are_written_as_given(self):
        self.assertEqual(fmt("part p : 'Pkg'::'T'; part q : $::A::B;"), "part p : 'Pkg'::'T';\npart q : $::A::B;\n")

    def test_expression_parentheses(self):
        cases = {
            "(x + y) * z": "(x + y) * z",
            "x + (y * z)": "x + y * z",
            "(a - b) - c": "a - b - c",
            "a - (b - c)": "a - (b - c)",
            "(a ** b) ** c": "(a ** b) ** c",
            "a ** (b ** c)": "a ** b ** c",
            "(-a) ** 2": "-a ** 2",
            "-(a ** 2)": "-(a ** 2)",
            "not (a and b) or c": "not (a and b) or c",
            "(a or b) and c": "(a or b) and c",
            "(if a ? b else c) + 1": "(if a ? b else c) + 1",
            "if (if a ? b else c) ? d else e": "if (if a ? b else c) ? d else e",
            "(a.b).c": "(a.b).c",
            "(a + b).c": "(a + b).c",
            "((1, 2), 3)": "((1, 2), 3)",
            "(1, (2, 3))": "(1, 2, 3)",  # the same tree: SequenceExpressionList nests to the right
            "x istype T and @S": "x istype T and @S",
            "(a == b) istype T": "(a == b) istype T",
            "1..n + 1": "1..n + 1",
        }
        for src, out in cases.items():
            with self.subTest(src=src):
                self.assertEqual(fmt(f"attribute v = {src};"), f"attribute v = {out};\n")

    def test_primary_expressions(self):
        cases = ["f(1, x)", "f(a = 1, b = 2)", "new T(1)", "xs->size()", "xs->reduce '+'",
                 "xs->select { in x; x > 0 }", "xs.?{ in x; x > 0 }", "xs.{ in x; x * 2 }", "a#(1, 2)",
                 "9.81 [m / s ^ 2]", "x.metadata", "x meta SysML::PartUsage", "null", "*", "true", "2.5",
                 '"a \\"quoted\\" string"', "a.b.c->including(d)", "all T"]
        for src in cases:
            with self.subTest(src=src):
                self.assertEqual(fmt(f"attribute v = {src};"), f"attribute v = {src};\n")

    def test_multiplicity_and_values(self):
        self.assertEqual(fmt("part ps : P[0..*] ordered nonunique; attribute m default := 1;"),
                         "part ps : P[0..*] ordered nonunique;\nattribute m default := 1;\n")
        self.assertEqual(fmt("feature x[1] ordered;", "kerml"), "feature x[1] ordered;\n")

    def test_metadata(self):
        self.assertEqual(fmt('#Safety part p; @Issue about p { text = "x"; } metadata m : M;'), expect("""
            #Safety part p;

            @Issue about p {
                text = "x";
            }

            metadata m : M;
            """))

    def test_imports_and_aliases(self):
        src = "private import Q::*::**[@Safety and not @Draft]; public import all R::x::**; alias <y> Y for R::y;"
        self.assertEqual(fmt(src), "private import Q::*::**[@Safety and not @Draft];\n"
                                   "public import all R::x::**;\nalias <y> Y for R::y;\n")

    def test_comments_keep_their_bodies(self):
        src = 'part def A { doc /* One line. */ doc /*\n * Two\n *   indented\n */ ' \
              'comment c about A locale "en" /* About. */ /* plain */ }'
        out = fmt(src)
        self.assertEqual(out, expect("""
            part def A {
                doc /* One line. */
                doc
                /*
                 * Two
                 *   indented
                 */
                comment c about A locale "en" /* About. */
                /* plain */
            }
            """))
        bodies = [n["body"] for n in parse(out).root.walk() if "body" in n.props]
        self.assertEqual(bodies, ["One line.", "Two\n  indented\n", "About.", "plain"])

    def test_behavior_and_requirements(self):
        self.assertEqual(fmt("""state def S { entry; then off; state off; accept Go then on;
            transition t first on accept s : Sig if g do send done() to y then off; }"""), expect("""
            state def S {
                entry;
                then off;
                state off;
                accept Go then on;
                transition t first on accept s : Sig if g do send done() to y then off;
            }
            """))
        self.assertEqual(fmt("action def A { first start; then action a1; if x > 0 then a2; else a3; }"), expect("""
            action def A {
                first start;
                then action a1;
                if x > 0 then a2;
                else a3;
            }
            """))
        self.assertEqual(fmt("requirement def R { subject v : V; require constraint { v.m <= 10 } assume a1; }"),
                         expect("""
            requirement def R {
                subject v : V;

                require constraint {
                    v.m <= 10
                }

                assume a1;
            }
            """))

    def test_transition_keyword_where_needed(self):
        # right after an entry action, a bare 'then' would be an entry transition
        self.assertEqual(fmt("state def S { entry; transition then off; transition do a then on; }"),
                         expect("""
            state def S {
                entry;
                transition then off;
                transition do a then on;
            }
            """))


ROUND_TRIP_SYSML = [
    "package P { private import Q::*; part def A :> B { attribute x : Real[1] = 2 * y; } }",
    "abstract part def V { in ref part p : P[0..*] ordered :> ps; variation part v; variant part a; variant b; }",
    "individual part def I; individual def J; individual #M part def K; snapshot s : T; timeslice t;",
    "enum def Color { enum red; green = 1; doc /* d */ #M enum blue; }",
    "port def FP { out item fuel : Fuel; } part p { port fp : ~FP; }",
    "part s { connect (a, b, c); connection c : C connect a to b; allocate x to y; allocation al : A; }",
    "part s { message m of M from a to b; message a to b; succession flow f from a.x to b.y; abstract flow g; }",
    "interface def I { end p1 : P; end [1] port p2 : ~P; } part s { interface a to b; }",
    "action def A { accept s : S via p; accept when t > 1 [s]; accept at T; accept after 5; send S() via p to q;"
    " send x to q; send via p to q; assign self.x := 1; terminate; terminate x;"
    " if a { } else if b { } else { } while i < 3 { } until done; loop { } for i in 1..3 { }"
    " merge m; decide; join j; fork; first start; then a; then [1] b; succession s first a if g then b; }",
    "action a { action b accept s; action c send x to y; action d if x { } }",
    "state def S parallel { entry action e { } do x; exit send s to t; state s1; then state s2; "
    "transition first s1 then s2; if g then s1; accept s then s2 { } }",
    "use case def U { subject s; actor a; objective { doc /* goal */ } include use case u2; include u3; }",
    "verification def V { objective { verify r; verify requirement r2 : R; } return v : V; v }",
    "concern def C { stakeholder s : S; } viewpoint def VP { frame concern c; frame c2; }",
    "view def VD { filter @Safety; render rendering r; render asTree; } view v { expose P::**; expose Q::*[@S]; }",
    "satisfy R by p; assert not satisfy requirement r : R by q; assert constraint c { x > 0 } assert not c2;",
    "part p { perform action a; perform b; exhibit state s parallel { } exhibit t; event occurrence e; event f; }",
    "metadata def M { ref :>> annotatedElement : SysML::Usage; attribute level : Integer; }",
    "@M { level = 1; } metadata m : M about a, b; #M #N dependency D from a to b, c;",
    "calc def C { in x : Real; return : Real; if x > 0 ? x else -x }",
    "attribute a = xs->collect { in x; x * 2 }.size; attribute b = (1, 2)#(1); attribute c = f(x).g;",
    "constraint def C { in x; x istype T implies x as T != null }",
    "connection def CD { end part a : A; end ref b; end c :>> d; end x [*] occurrence y; }",
    "standard library package L { comment about A /* c */ rep r language \"ocl\" /* self */ }",
]
ROUND_TRIP_KERML = [
    "package P { class A specializes B, C { feature f : T[0..*] ordered nonunique subsets g redefines h; } }",
    "abstract classifier C [1] unions A, B intersects D differences E disjoint from F;",
    "type T :> U ~ V; type all W :> X;",
    "function f { in x : Real; return : Real; x * 2 } predicate p { in x : Real; x > 0 }",
    "assoc struct S { end [0..1] feature a : A; const end b : B; end c : C; }",
    "behavior B { step s1 : S; step s2; succession first s1 then s2; connector c : C from x to y;"
    " binding of a = b; binding x : X of a = b; flow of P from a.o to b.i; succession flow f from s.o to t.i; }",
    "feature v : T chains a.b.c; feature w featured by X, Y inverse of z; composite var feature x; derived f;",
    "inv { x > 0 } inv false n { x < 0 } expr e : Real = 1; bool b { true }",
    "specialization S subtype A :> B { doc /* about S */ feature f; } subclassifier C :> D; typing f : T;"
    " subset a.b :> c; redefinition x :>> y; conjugation cj conjugate P ~ Q; disjoining disjoint A from B;"
    " featuring f by T; inverting inverse a of b;",
    "dependency from x to y, z; dependency D from a to b { feature e; }",
    "metaclass M; #M feature x; @M { a = 1; } metadata m : M about x;",
    "multiplicity m [1..2]; multiplicity n :> m;",
    "namespace N { feature f; } library package L { filter @M; }",
    "class A { member feature f; private feature g; protected class C; }",
]


class RoundTripTests(unittest.TestCase):

    def check(self, src, language):
        first = parse(src, language)
        self.assertEqual(first.diagnostics, [], src)
        text = print_tree(first.root, language)
        second = parse(text, language)
        self.assertEqual(second.diagnostics, [], text)
        self.assertIsNone(diff(first.root, second.root), text)
        self.assertEqual(print_tree(second.root, language), text)  # stable: printing is idempotent

    def test_sysml_snippets(self):
        for src in ROUND_TRIP_SYSML:
            with self.subTest(src=src[:60]):
                self.check(src, "sysml")

    def test_kerml_snippets(self):
        for src in ROUND_TRIP_KERML:
            with self.subTest(src=src[:60]):
                self.check(src, "kerml")

    def test_diff_reports_the_first_difference(self):
        a = parse("part def A { attribute x : Real; }").root
        b = parse("part def A { attribute y : Real; }").root
        self.assertIn("declaredName: 'x' != 'y'", diff(a, b))
        c = parse("part def A { attribute x : Integer; }").root
        self.assertIn("Real != Integer", diff(a, c))
        self.assertIsNone(diff(a, parse("part def A {\n    attribute x : Real;\n}").root))

    def test_printing_a_single_element(self):
        root = parse("package P { part def A { part b; } }").root
        a = root.find("PartDefinition")[0]
        self.assertEqual(print_tree(a), "part def A {\n    part b;\n}\n")

    def test_unknown_node_is_an_error(self):
        with self.assertRaises(PrintError):
            print_tree(Node("Namespace", {"ownedRelationship": [Node("Bogus", {})]}))


class DictView:
    """A view over plain dicts, standing in for a model adapter: a node is
    {"@type": ..., <property>: value}, a reference is {"@ref": "qualified name"}."""

    def type(self, node):
        return node["@type"]

    def get(self, node, name, default=None):
        return node.get(name, default)

    def ref(self, value, owner):
        return value["@ref"]


def to_dicts(value, memo):
    if isinstance(value, Node):
        if id(value) not in memo:
            d = memo[id(value)] = {"@type": value.type}
            d.update({k: to_dicts(v, memo) for k, v in value.props.items()})
        return memo[id(value)]
    if isinstance(value, Ref):
        return {"@ref": value.text}
    if isinstance(value, list):
        return [to_dicts(v, memo) for v in value]
    return value


class ViewInterfaceTests(unittest.TestCase):

    def test_printer_reads_only_through_the_view(self):
        for src, language in [(ROUND_TRIP_SYSML[8], "sysml"), (ROUND_TRIP_SYSML[2], "sysml"),
                              (ROUND_TRIP_KERML[5], "kerml"), (ROUND_TRIP_KERML[8], "kerml")]:
            with self.subTest(src=src[:40]):
                root = parse(src, language).root
                expected = print_tree(root, language)
                tree = to_dicts(root, {})
                self.assertEqual(Printer(language, DictView()).print(tree), expected)

    def test_defaults_are_absent_values(self):
        # a model adapter returns None for default values; the printer writes nothing for them
        view = DictView()
        part = {"@type": "PartUsage", "declaredName": "p", "isAbstract": False, "isUnique": True,
                "ownedRelationship": [{"@type": "FeatureTyping", "type": {"@ref": "P"}}]}
        root = {"@type": "Namespace", "ownedRelationship": [
            {"@type": "OwningMembership", "visibility": None, "ownedRelatedElement": [part]}]}
        self.assertEqual(Printer("sysml", view).print(root), "part p : P;\n")


class CorpusRoundTripTests(unittest.TestCase):

    def test_every_corpus_file_round_trips(self):
        started = time.perf_counter()
        metrics = {m["name"]: m for m in printer_metric.collect()}
        self.assertEqual(metrics["print.library.ast_roundtrip_ok"]["detail"], [])
        self.assertEqual(metrics["print.examples.ast_roundtrip_ok"]["detail"], [])
        self.assertEqual(metrics["print.library.ast_roundtrip_ok"]["value"], 1.0)
        self.assertEqual(metrics["print.examples.ast_roundtrip_ok"]["value"], 1.0)
        self.assertLess(time.perf_counter() - started, 60)


if __name__ == "__main__":
    unittest.main()
