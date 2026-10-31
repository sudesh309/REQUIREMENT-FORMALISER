"""Diagnostics instead of exceptions, recovery at ';' and '}', spec rules, and the parse API."""
import random
import tempfile
import unittest
from pathlib import Path

from sysml_text import ERROR, language_of, parse, parse_file


def names(root):
    return [n["declaredName"] for n in root.walk() if "declaredName" in n.props]


class DiagnosticTests(unittest.TestCase):

    def test_error_has_position_message_and_expected(self):
        r = parse("package P {\n  part x : ;\n}")
        self.assertEqual(len(r.diagnostics), 1)
        d = r.diagnostics[0]
        self.assertEqual((d.severity, d.line, d.col), (ERROR, 2, 12))
        self.assertIn("expected a name", d.message)
        self.assertIn("found ';'", d.message)
        self.assertEqual(d.expected, ("NAME",))
        self.assertFalse(r.ok)

    def test_recovery_at_semicolon_and_brace(self):
        r = parse("""package P {
            part def A :> { part inner; }
            part def B { attribute x = 1 + ; attribute y = 2; }
            part c : C;
        }
        part def D;""")
        self.assertEqual([d.line for d in r.diagnostics], [2, 3])
        self.assertEqual(names(r.root), ["P", "B", "y", "c", "D"])

    def test_unclosed_body_is_reported_once(self):
        r = parse("package P { part def A { part b;")
        self.assertEqual(len(r.diagnostics), 1)
        self.assertIn("expected '}'", r.diagnostics[0].message)
        self.assertEqual(names(r.root), ["P", "A", "b"])

    def test_stray_closing_brace(self):
        r = parse("part a; } part b;")
        self.assertEqual(len(r.diagnostics), 1)
        self.assertEqual(names(r.root), ["a", "b"])

    def test_invalid_input_is_rejected(self):
        bad_sysml = ["part def A : B;", 'requirement def R id="R1";', "attribute a = ;", "connect a to ;",
                     "part def A { part b }", "part p : P[1..];", "in part def A;", "ref part def A;",
                     "import A::*::*;", "doc A;", "calc def C { x + }", "part p = (1, 2;",
                     "accept s;", "transition first a then b;", "view v { public expose A::*; }",
                     "action def A { then; }", "metadata def M; @M { part p; }"]
        for src in bad_sysml:
            with self.subTest(src=src):
                self.assertTrue(parse(src).diagnostics)
        bad_kerml = ["class A : B;", "feature x : ;", "part def A;", "function f { in x; x + }",
                     "connector a to ;", "classifier C specializes ;"]
        for src in bad_kerml:
            with self.subTest(src=src):
                self.assertTrue(parse(src, "kerml").diagnostics)

    def test_spec_rules_reported_but_tree_built(self):
        r = parse("import A::*;")
        self.assertEqual(len(r.diagnostics), 1)
        self.assertIn("visibility", r.diagnostics[0].message)
        self.assertEqual(r.root["ownedRelationship"][0].type, "NamespaceImport")
        r = parse("type T;", "kerml")
        self.assertEqual(len(r.diagnostics), 1)
        self.assertEqual(r.root.find("Type")[0]["declaredName"], "T")

    def test_lexical_errors(self):
        r = parse("part def 'bad;\npart def Good;\nattribute s = \"open;\npart q;")
        self.assertEqual([d.message for d in r.diagnostics], ["unterminated name", "unterminated string"])
        self.assertEqual(names(r.root), ["Good", "q"])
        r = parse("part a; /* never closed\npart b;")
        self.assertEqual(r.diagnostics[0].message, "unterminated comment")

    def test_garbage_never_raises(self):
        rng = random.Random(7)
        alphabet = list("abc{}[]();:=.,<>~#@*/+-'\"\n ") + ["part ", "def ", "if ", "then ", "accept ",
                                                           "state ", "action ", "end ", "connect ", "/*", "*/"]
        for _ in range(300):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))
            for language in ("sysml", "kerml"):
                r = parse(text, language)
                self.assertIsNotNone(r.root)

    def test_deeply_nested_input(self):
        self.assertEqual(parse("package P {" * 150 + "}" * 150).diagnostics, [])
        self.assertEqual(parse("attribute a = " + "(" * 150 + "1" + ")" * 150 + ";").diagnostics, [])
        # too deep: a diagnostic, not a RecursionError, and parsing goes on after it
        r = parse("attribute a = " + "(" * 400 + "1" + ")" * 400 + "; part def After;")
        self.assertIn("nesting deeper", r.diagnostics[0].message)
        self.assertEqual(names(r.root)[-1], "After")
        r = parse("package P {" * 300 + "}" * 300)
        self.assertIn("nesting deeper", r.diagnostics[0].message)
        r = parse("attribute a = " + "-" * 20000 + "1;")
        self.assertTrue(r.diagnostics)


class ApiTests(unittest.TestCase):

    def test_language_from_extension(self):
        self.assertEqual(language_of("x.kerml"), "kerml")
        self.assertEqual(language_of("x.sysml"), "sysml")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.kerml"
            path.write_text("class A;", encoding="utf-8")
            r = parse_file(path)
            self.assertEqual((r.language, r.diagnostics), ("kerml", []))
            self.assertEqual(r.root.find("Class")[0]["declaredName"], "A")
            path = Path(tmp) / "m.sysml"
            path.write_text("part def A { part x; }", encoding="utf-8")
            r = parse_file(path)
            self.assertEqual(r.language, "sysml")
            self.assertIn("m.sysml", str(parse_file(path, "sysml").source.path))

    def test_unknown_language(self):
        with self.assertRaises(ValueError):
            parse("x", "uml")

    def test_empty_text(self):
        r = parse("")
        self.assertEqual((r.diagnostics, r.root.type, r.root.props), ([], "Namespace", {}))


if __name__ == "__main__":
    unittest.main()
