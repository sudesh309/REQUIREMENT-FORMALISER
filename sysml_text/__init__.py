"""Parser for the KerML and SysML textual notations to a spec-shaped AST (ADR 0003).

    >>> from sysml_text import parse
    >>> result = parse("part def Vehicle { attribute mass : Real; }")
    >>> result.diagnostics
    []
    >>> result.root.find("PartDefinition")[0]["declaredName"]
    'Vehicle'

``parse`` never raises on bad input: syntax errors become
:class:`Diagnostic` objects and the parser recovers at ``;`` and ``}``.
The package is pure: it imports nothing from ``kerml``, ``sysmlv2`` or
``engine``. See ``GRAMMAR_NOTES.md`` for where the parser follows the
published corpus rather than the ``.kebnf`` grammars, and for the AST
conventions.
"""
from __future__ import annotations

from pathlib import Path

from .ast import ERROR, WARNING, Diagnostic, Node, ParseResult, Ref, Source, Span, dump
from .kerml import KerMLParser
from .lexer import KERML_KEYWORDS, SYSML_KEYWORDS, Token, tokenize
from .sysml import SysMLParser

__all__ = ["parse", "parse_file", "language_of", "ParseResult", "Node", "Ref", "Span", "Source",
           "Diagnostic", "ERROR", "WARNING", "dump", "tokenize", "Token", "KERML_KEYWORDS",
           "SYSML_KEYWORDS"]

PARSERS = {"kerml": KerMLParser, "sysml": SysMLParser}


def parse(text: str, language: str = "sysml", path: str | None = None) -> ParseResult:
    """Parse KerML (``language="kerml"``) or SysML text into a ``Namespace`` root and diagnostics."""
    try:
        parser = PARSERS[language]
    except KeyError:
        raise ValueError(f"unknown language {language!r}; expected 'sysml' or 'kerml'") from None
    return parser(text, path).parse()


def language_of(path: str | Path) -> str:
    """``kerml`` for ``.kerml`` files, ``sysml`` otherwise."""
    return "kerml" if Path(path).suffix.lower() == ".kerml" else "sysml"


def parse_file(path: str | Path, language: str | None = None) -> ParseResult:
    """Parse a ``.sysml`` or ``.kerml`` file (UTF-8); the language follows the extension."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return parse(text, language or language_of(path), str(path))
