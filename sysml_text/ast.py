"""Spec-shaped syntax tree, source spans and diagnostics (ADR 0003, decision 4).

A :class:`Node` is ``Node(type, props, span)``:

- ``type`` is the metaclass the grammar production builds (``PartUsage``,
  ``OwningMembership``, ``FeatureTyping``, ``OperatorExpression``, ...);
- ``props`` maps the property names of the grammar's assignments to values:
  ``+=`` appends to a list, ``=`` sets a value, ``?=`` sets ``True``. Values are
  ``str``, ``bool``, ``int``, ``float``, :class:`Node`, :class:`Ref` or lists of
  nodes and refs;
- cross references (``[QualifiedName]``) are unresolved :class:`Ref` objects.

Ownership is carried by exactly two properties: ``ownedRelationship`` (an
element's relationships) and ``ownedRelatedElement`` (a relationship's owned
elements). Grammar assignments to derived composite properties
(``ownedMemberFeature``, ``ownedMemberParameter``, ``value``, ``condition``,
...) are stored under ``ownedRelatedElement``; see ``GRAMMAR_NOTES.md``.
Other properties may point at a node that is also owned (``general`` of a
specialization to an owned feature chain), so :meth:`Node.walk` follows only
the two ownership properties and visits every node once.
"""
from __future__ import annotations

import bisect
import re
from typing import Iterator

OWNERSHIP = ("ownedRelationship", "ownedRelatedElement")

_LINE_BREAK = re.compile(r"\r\n?|\n")


class Source:
    """A text with lazily computed line starts, shared by the spans into it."""

    __slots__ = ("text", "path", "_lines")

    def __init__(self, text: str, path: str | None = None):
        self.text = text
        self.path = path
        self._lines: list[int] | None = None

    def position(self, offset: int) -> tuple[int, int]:
        """1-based (line, column) of an offset."""
        if self._lines is None:
            self._lines = [0] + [m.end() for m in _LINE_BREAK.finditer(self.text)]
        line = bisect.bisect_right(self._lines, offset)
        return line, offset - self._lines[line - 1] + 1


class Span:
    """A half-open character range ``[start, end)`` of a :class:`Source`."""

    __slots__ = ("start", "end", "source")

    def __init__(self, start: int, end: int, source: Source | None = None):
        self.start = start
        self.end = end
        self.source = source

    @property
    def line(self) -> int:
        return self.source.position(self.start)[0] if self.source else 0

    @property
    def col(self) -> int:
        return self.source.position(self.start)[1] if self.source else 0

    @property
    def end_line(self) -> int:
        return self.source.position(self.end)[0] if self.source else 0

    @property
    def end_col(self) -> int:
        return self.source.position(self.end)[1] if self.source else 0

    @property
    def text(self) -> str:
        return self.source.text[self.start:self.end] if self.source else ""

    def __repr__(self) -> str:
        if self.source is None:
            return f"Span({self.start}, {self.end})"
        return f"Span({self.line}:{self.col}-{self.end_line}:{self.end_col})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Span) and (self.start, self.end) == (other.start, other.end)

    def __hash__(self) -> int:
        return hash((self.start, self.end))


class Ref:
    """An unresolved cross reference ``[QualifiedName]``.

    ``text`` is the qualified name as written (segments joined with ``::``,
    unrestricted names keep their quotes); ``names`` are the segment names with
    quotes removed and escapes resolved. A leading ``$::`` (global scope) is
    kept in ``text`` and reported by :attr:`is_global`, not in ``names``.
    """

    __slots__ = ("text", "span", "names")

    def __init__(self, text: str, span: Span | None = None, names: tuple[str, ...] = ()):
        self.text = text
        self.span = span
        self.names = names or (text,)

    @property
    def is_global(self) -> bool:
        return self.text.startswith("$")

    def __repr__(self) -> str:
        return f"Ref({self.text!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Ref) and self.text == other.text

    def __hash__(self) -> int:
        return hash(self.text)


class Node:
    """An element or relationship built by a grammar production."""

    __slots__ = ("type", "props", "span")

    def __init__(self, type: str, props: dict | None = None, span: Span | None = None):
        self.type = type
        self.props = {} if props is None else props
        self.span = span

    def get(self, name: str, default=None):
        return self.props.get(name, default)

    def __getitem__(self, name: str):
        return self.props[name]

    def __contains__(self, name: str) -> bool:
        return name in self.props

    def add(self, name: str, value) -> None:
        """``name += value``."""
        lst = self.props.get(name)
        if lst is None:
            self.props[name] = [value]
        else:
            lst.append(value)

    @property
    def owned(self) -> list[Node]:
        """Owned nodes: ``ownedRelationship`` then ``ownedRelatedElement``."""
        p = self.props
        return p.get("ownedRelationship", []) + p.get("ownedRelatedElement", [])

    def walk(self) -> Iterator[Node]:
        """Pre-order traversal of this node and every node it owns."""
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            p = node.props
            kids = p.get("ownedRelationship", []) + p.get("ownedRelatedElement", [])
            stack.extend(reversed(kids))

    def find(self, type: str) -> list[Node]:
        """Every owned node (including this one) of the given metaclass."""
        return [n for n in self.walk() if n.type == type]

    def __repr__(self) -> str:
        name = self.props.get("declaredName")
        return f"Node({self.type}{' ' + repr(name) if name else ''})"


ERROR = "error"
WARNING = "warning"


class Diagnostic:
    """A syntax problem: severity, message, source span and the expected tokens."""

    __slots__ = ("severity", "message", "span", "expected")

    def __init__(self, severity: str, message: str, span: Span, expected: tuple[str, ...] = ()):
        self.severity = severity
        self.message = message
        self.span = span
        self.expected = expected

    @property
    def line(self) -> int:
        return self.span.line

    @property
    def col(self) -> int:
        return self.span.col

    def __str__(self) -> str:
        where = self.span.source.path if self.span.source and self.span.source.path else "<text>"
        return f"{where}:{self.line}:{self.col}: {self.severity}: {self.message}"

    def __repr__(self) -> str:
        return f"Diagnostic({self.severity!r}, {self.message!r}, {self.span!r})"


class ParseResult:
    """``root`` (a ``Namespace`` node) and the ``diagnostics`` of one parse."""

    __slots__ = ("root", "diagnostics", "source", "language")

    def __init__(self, root: Node, diagnostics: list[Diagnostic], source: Source, language: str):
        self.root = root
        self.diagnostics = diagnostics
        self.source = source
        self.language = language

    @property
    def ok(self) -> bool:
        return not any(d.severity == ERROR for d in self.diagnostics)

    def __repr__(self) -> str:
        return f"ParseResult({self.language}, {len(self.diagnostics)} diagnostics)"


def _scalar(v) -> str:
    if isinstance(v, Ref):
        return f"-> {v.text}"
    return repr(v)


def dump(node: Node, indent: str = "  ", spans: bool = False) -> str:
    """A readable multi-line rendering of a tree, for debugging and tests."""
    lines: list[str] = []
    seen: set[int] = set()

    def visit(n: Node, depth: int, label: str) -> None:
        pad = indent * depth
        head = f"{pad}{label}{n.type}"
        if spans and n.span is not None:
            head += f" @{n.span.line}:{n.span.col}"
        if id(n) in seen:
            lines.append(head + " (see above)")
            return
        seen.add(id(n))
        scalars = []
        children = []
        for k, v in n.props.items():
            if isinstance(v, Node):
                children.append((k, [v]))
            elif isinstance(v, list) and any(isinstance(x, Node) for x in v):
                children.append((k, v))
            elif isinstance(v, list):
                scalars.append(f"{k}=[{', '.join(_scalar(x) for x in v)}]")
            else:
                scalars.append(f"{k}={_scalar(v)}")
        lines.append(head + (" " + " ".join(scalars) if scalars else ""))
        for k, vs in children:
            for v in vs:
                if isinstance(v, Node):
                    if k not in OWNERSHIP and id(v) in seen:
                        lines.append(f"{pad}{indent}{k}: {v.type} (owned)")
                    elif k in OWNERSHIP:
                        visit(v, depth + 1, "" if k == "ownedRelationship" else "+ ")
                    else:
                        lines.append(f"{pad}{indent}{k}: {v.type} (owned)")
                else:
                    lines.append(f"{pad}{indent}{k}: {_scalar(v)}")

    visit(node, 0, "")
    return "\n".join(lines)
