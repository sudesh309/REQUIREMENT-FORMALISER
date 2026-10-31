"""Lexer for the KerML and SysML textual notations (KerML 8.2.2, SysML 8.2.2.1.2).

Token kinds are plain strings:

- a reserved keyword or a symbol is its own kind (``'part'``, ``':>>'``);
- ``NAME`` is a basic or unrestricted name; the value is the represented name
  (quotes removed, escapes resolved);
- ``INT`` (``DECIMAL_VALUE``), ``REAL`` (a whole real literal, see
  ``GRAMMAR_NOTES.md``), ``STRING`` (value unescaped), ``COMMENT`` (a
  ``/* ... */`` regular comment: comments are elements, not whitespace; the
  value is the raw text);
- ``ERROR`` for a character no token starts with, and ``EOF``.

White space, ``//`` single-line notes and ``//* ... */`` multiline notes are
skipped.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from .ast import Source

KERML_KEYWORDS = frozenset("""
about abstract alias all and as assoc behavior binding bool by chains class
classifier comment composite conjugate conjugates conjugation connector const
crosses datatype default dependency derived differences disjoining disjoint doc
else end expr false feature featured featuring filter first flow for from
function hastype if implies import in inout interaction intersects inv inverse
inverting istype language library locale member meta metaclass metadata
multiplicity namespace new nonunique not null of or ordered out package portion
predicate private protected public redefines redefinition references rep return
specialization specializes standard step struct subclassifier subset subsets
subtype succession then to true type typed typing unions var xor
""".split())

SYSML_KEYWORDS = frozenset("""
about abstract accept action actor after alias all allocate allocation analysis
and as assert assign assume at attribute bind binding by calc case comment
concern connect connection constant constraint crosses decide def default
defined dependency derived do doc else end entry enum event exhibit exit expose
false filter first flow for fork frame from hastype if implies import in include
individual inout interface istype item join language library locale loop merge
message meta metadata new nonunique not null objective occurrence of or ordered
out package parallel part perform port private protected public redefines ref
references render rendering rep require requirement return satisfy send snapshot
specializes stakeholder standard state subject subsets succession terminate then
timeslice to transition true until use variant variation verification verify via
view viewpoint when while xor
""".split())

KEYWORDS = {"kerml": KERML_KEYWORDS, "sysml": SYSML_KEYWORDS}

# Longest first, so that input is grouped into the longest possible symbol.
SYMBOLS = ("::>", ":>>", "===", "!==",
           "::", ":>", ":=", "==", "!=", "<=", ">=", "=>", "->", "..", ".?", "??", "**", "@@",
           "~", "}", "|", "{", "^", "]", "[", "@", "?", ">", "=", "<", ";", ":", "/", ".",
           "-", ",", "+", "*", ")", "(", "&", "%", "$", "#")

_ESCAPES = {"'": "'", '"': '"', "b": "\b", "f": "\f", "t": "\t", "n": "\n", "r": "\r",
            "v": "\v", "\\": "\\"}
_ESCAPE = re.compile(r"\\(.)", re.S)

_TOKEN = re.compile(r"""
    (?P<ws>[ \t\f\r\n]+)
  | (?P<note>//\*.*?\*/|//[^\r\n]*)
  | (?P<comment>/\*.*?\*/)
  | (?P<unclosed>/\*)
  | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<qname>'(?:[^'\\\r\n]|\\.)*')
  | (?P<real>[0-9]+\.[0-9]+(?:[eE][+-]?[0-9]+)?|\.[0-9]+(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)
  | (?P<int>[0-9]+)
  | (?P<string>"(?:[^"\\\r\n]|\\.)*")
  | (?P<sym>""" + "|".join(re.escape(s) for s in SYMBOLS) + r""")
  | (?P<unclosed_line>['"])
  | (?P<error>.)
""", re.S | re.X)


def unescape(body: str) -> str:
    """Resolve the escape sequences of a name or string body (quotes removed)."""
    if "\\" not in body:
        return body
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(1)), body)


def comment_body(raw: str) -> str:
    """The body of a ``/* ... */`` comment, processed as KerML 8.2.3.3.2 Note 1 says."""
    text = raw[2:-2] if raw.endswith("*/") else raw[2:]
    # White space right after "/*", up to and including the first line terminator.
    m = re.match(r"[ \t\f]*(\r\n?|\n)?", text)
    text = text[m.end():]
    out = []
    for i, line in enumerate(re.split(r"(\r\n?|\n)", text)):
        if i % 2:  # a line terminator
            out.append(line)
            continue
        if i:  # every line after the first
            line = line.lstrip(" \t\f")
            if line.startswith("*"):
                line = line[1:]
                if line.startswith(" "):
                    line = line[1:]
        out.append(line)
    return "".join(out).rstrip(" \t\f")


class Token(NamedTuple):
    kind: str
    value: object
    start: int
    end: int
    line: int
    col: int


class Tokens:
    """The token stream of one text as parallel lists (fast to index)."""

    __slots__ = ("kinds", "values", "starts", "ends", "source", "errors")

    def __init__(self, source: Source, language: str = "sysml"):
        self.source = source
        keywords = KEYWORDS[language]
        kinds: list[str] = []
        values: list = []
        starts: list[int] = []
        ends: list[int] = []
        errors: list[tuple[int, int, str]] = []
        ka, va, sa, ea = kinds.append, values.append, starts.append, ends.append
        text = source.text
        for m in _TOKEN.finditer(text):
            group = m.lastgroup
            if group == "ws" or group == "note":
                continue
            s, e = m.span()
            if group == "name":
                word = m.group()
                ka(word if word in keywords else "NAME")
                va(word)
            elif group == "sym":
                ka(m.group())
                va(None)
            elif group == "qname":
                ka("NAME")
                va(unescape(text[s + 1:e - 1]))
            elif group == "int":
                ka("INT")
                va(int(m.group()))
            elif group == "real":
                ka("REAL")
                va(float(m.group()))
            elif group == "string":
                ka("STRING")
                va(unescape(text[s + 1:e - 1]))
            elif group == "comment":
                ka("COMMENT")
                va(m.group())
            elif group == "unclosed":
                # an unterminated comment runs to the end of the text
                errors.append((s, len(text), "unterminated comment"))
                ka("ERROR")
                va(m.group())
                sa(s)
                ea(len(text))
                break
            elif group == "unclosed_line":
                # an unterminated name or string (no closing quote on its line): report the
                # quote and go on lexing after it
                errors.append((s, e, f"unterminated {'name' if text[s] == chr(39) else 'string'}"))
                ka("ERROR")
                va(m.group())
            else:
                errors.append((s, e, f"unexpected character {m.group()!r}"))
                ka("ERROR")
                va(m.group())
            sa(s)
            ea(e)
        n = len(text)
        ka("EOF")
        va(None)
        sa(n)
        ea(n)
        self.kinds, self.values, self.starts, self.ends, self.errors = kinds, values, starts, ends, errors


def tokenize(text: str, language: str = "sysml") -> list[Token]:
    """The tokens of a text (with line and column), ending with ``EOF``."""
    source = Source(text)
    toks = Tokens(source, language)
    out = []
    for k, v, s, e in zip(toks.kinds, toks.values, toks.starts, toks.ends):
        line, col = source.position(s)
        out.append(Token(k, v, s, e, line, col))
    return out
