"""Lexer of the textual notations (KerML 8.2.2, SysML 8.2.2.1.2): names, literals, notes vs. comments."""
import unittest

from sysml_text import tokenize
from sysml_text.lexer import KERML_KEYWORDS, SYSML_KEYWORDS, comment_body


def kinds(text, language="sysml"):
    return [t.kind for t in tokenize(text, language)][:-1]  # without EOF


def values(text, language="sysml"):
    return [t.value for t in tokenize(text, language)][:-1]


class NameTests(unittest.TestCase):

    def test_basic_names_and_keywords(self):
        self.assertEqual(kinds("part def Vehicle_1"), ["part", "def", "NAME"])
        self.assertEqual(values("part def Vehicle_1")[2], "Vehicle_1")

    def test_reserved_words_differ_per_language(self):
        # 'part' is a SysML keyword but a name in KerML; 'type' the other way round
        self.assertEqual(kinds("part type", "kerml"), ["NAME", "type"])
        self.assertEqual(kinds("part type", "sysml"), ["part", "NAME"])
        self.assertIn("new", KERML_KEYWORDS)  # used by ConstructorExpression (GRAMMAR_NOTES D12)
        self.assertNotIn("feature", SYSML_KEYWORDS)

    def test_unrestricted_names_with_escapes(self):
        toks = tokenize(r"'Vehicle A' 'it\'s' 'a\\b' 'tab\tx'")
        self.assertEqual([t.kind for t in toks][:-1], ["NAME"] * 4)
        self.assertEqual([t.value for t in toks][:-1], ["Vehicle A", "it's", "a\\b", "tab\tx"])

    def test_quoted_keyword_is_a_name(self):
        self.assertEqual(kinds("'part'"), ["NAME"])
        self.assertEqual(values("'part'"), ["part"])


class LiteralTests(unittest.TestCase):

    def test_integers_and_reals(self):
        self.assertEqual(kinds("42 1.5 .5 1e3 2.5E-3 7e+2"), ["INT", "REAL", "REAL", "REAL", "REAL", "REAL"])
        self.assertEqual(values("42 1.5 .5 1e3 2.5E-3"), [42, 1.5, 0.5, 1000.0, 0.0025])

    def test_range_is_not_a_real(self):
        self.assertEqual(kinds("0..*"), ["INT", "..", "*"])
        self.assertEqual(kinds("[1..n]"), ["[", "INT", "..", "NAME", "]"])

    def test_strings_with_escapes(self):
        toks = tokenize(r'"say \"hi\"\n"')
        self.assertEqual(toks[0].kind, "STRING")
        self.assertEqual(toks[0].value, 'say "hi"\n')


class CommentTests(unittest.TestCase):

    def test_single_line_notes_are_skipped(self):
        self.assertEqual(kinds("part // a note\n x"), ["part", "NAME"])

    def test_multiline_notes_are_skipped(self):
        self.assertEqual(kinds("part //* a\n multiline note */ x"), ["part", "NAME"])

    def test_regular_comments_are_tokens(self):
        toks = tokenize("doc /* The doc. */ part")
        self.assertEqual([t.kind for t in toks][:-1], ["doc", "COMMENT", "part"])
        self.assertEqual(toks[1].value, "/* The doc. */")

    def test_comment_body_processing(self):
        raw = "/*\n     * First line\n     *   indented\n     */"
        self.assertEqual(comment_body(raw), "First line\n  indented\n")
        self.assertEqual(comment_body("/* one line */"), "one line")


class SymbolAndPositionTests(unittest.TestCase):

    def test_longest_match(self):
        # "a:::b" is "a", "::", ":", "b" (KerML 8.2.2.7)
        self.assertEqual(kinds("a:::b"), ["NAME", "::", ":", "NAME"])
        self.assertEqual(kinds(":>> :> ::> => === !== ?? .? -> ** @@"),
                         [":>>", ":>", "::>", "=>", "===", "!==", "??", ".?", "->", "**", "@@"])

    def test_line_and_column(self):
        toks = tokenize("package P {\n\tpart x;\r\n  part y;\n}")
        y = [t for t in toks if t.value == "y"][0]
        self.assertEqual((y.line, y.col), (3, 8))
        self.assertEqual(toks[-1].kind, "EOF")

    def test_errors_become_error_tokens(self):
        toks = tokenize("part ` x 'open\npart z")
        self.assertEqual([t.kind for t in toks][:-1], ["part", "ERROR", "NAME", "ERROR", "NAME", "part", "NAME"])


if __name__ == "__main__":
    unittest.main()
