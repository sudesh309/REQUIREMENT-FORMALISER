"""Minimal textual parser for a SysML v2 / KerML-flavoured surface syntax.

This is intentionally a *subset* of the OMG textual notation, sufficient
for round-tripping the bundled examples. Supported:

    package <Name> { ... }
    part def <Name> [: <Super>] { ... }
    item def <Name> { ... }
    attribute def <Name> { ... }
    port def <Name> { ... }
    interface def <Name> { ... }
    connection def <Name> { ... }
    action def <Name> { ... }
    state def <Name> { ... }
    constraint def <Name> { ... }
    requirement def <Name> [id="..."] { doc /* text */ ... }
    enum def <Name> { Lit1; Lit2; ... }

    part <name> : <Type> [<lo>..<hi>];
    attribute <name> : <Type>;
    port <name> : <Type>;
    action <name> : <Type>;
    state <name> : <Type>;
    requirement <name> : <Type>;
    connect <a> to <b>;

    doc /* free text */
    // line comment

The grammar is hand-written (recursive-descent). Errors raise ParseError
with a 1-based line/column.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from kerml.features import FeatureDirection, MultiplicityRange
from kerml.namespaces import Package
from sysmlv2.definitions import (
    ActionDefinition, ActionUsage,
    AttributeDefinition, AttributeUsage,
    ConnectionDefinition, ConnectionUsage,
    ConstraintDefinition,
    EnumerationDefinition, EnumerationUsage,
    InterfaceDefinition,
    ItemDefinition, ItemUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage,
    StateDefinition, StateUsage,
)


class ParseError(SyntaxError):
    pass


_TOKEN = re.compile(
    r"""
    \s+                                        |       # whitespace
    //[^\n]*                                   |       # line comment
    /\*(?P<doc>.*?)\*/                         |       # block / doc comment
    (?P<num>\d+)                               |
    (?P<str>"(?:[^"\\]|\\.)*")                |
    (?P<id>[A-Za-z_][A-Za-z0-9_]*)             |
    (?P<sym>::|\.\.|[{}\[\];:,=*])
    """,
    re.VERBOSE | re.DOTALL,
)

_KW = {
    "package", "def", "part", "item", "attribute", "port", "interface",
    "connection", "action", "state", "constraint", "requirement", "enum",
    "doc", "id", "to", "connect", "abstract", "in", "out", "inout",
}


@dataclass
class Tok:
    kind: str   # 'kw', 'id', 'num', 'str', 'sym', 'doc'
    value: str
    line: int
    col: int


def _tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    line = 1
    col = 1
    i = 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise ParseError(f"Unexpected character {src[i]!r} at {line}:{col}")
        text = m.group(0)
        if m.lastgroup == "doc":
            toks.append(Tok("doc", m.group("doc").strip(), line, col))
        elif m.lastgroup == "num":
            toks.append(Tok("num", text, line, col))
        elif m.lastgroup == "str":
            toks.append(Tok("str", text[1:-1], line, col))
        elif m.lastgroup == "id":
            toks.append(Tok("kw" if text in _KW else "id", text, line, col))
        elif m.lastgroup == "sym":
            toks.append(Tok("sym", text, line, col))
        # Otherwise it's whitespace / line comment — skip.
        nl = text.count("\n")
        if nl:
            line += nl
            col = len(text) - text.rfind("\n")
        else:
            col += len(text)
        i = m.end()
    return toks


_DEF_KIND = {
    "part": (PartDefinition, PartUsage),
    "item": (ItemDefinition, ItemUsage),
    "attribute": (AttributeDefinition, AttributeUsage),
    "port": (PortDefinition, PortUsage),
    "action": (ActionDefinition, ActionUsage),
    "state": (StateDefinition, StateUsage),
    "interface": (InterfaceDefinition, None),
    "connection": (ConnectionDefinition, ConnectionUsage),
    "constraint": (ConstraintDefinition, None),
    "requirement": (RequirementDefinition, RequirementUsage),
}


def _resolve_in_scope(start, qname: str):
    """Walk up the owner chain looking for a Namespace that resolves `qname`."""
    from kerml.namespaces import Namespace
    node = start
    while node is not None:
        if isinstance(node, Namespace):
            hit = node.resolve(qname)
            if hit is not None:
                return hit
        node = node.owner
    return None


class _Parser:
    def __init__(self, toks: list[Tok]):
        self.toks = toks
        self.pos = 0

    # --- low-level helpers -------------------------------------------
    def peek(self, k: int = 0) -> Optional[Tok]:
        i = self.pos + k
        return self.toks[i] if i < len(self.toks) else None

    def eat(self, kind: str, value: Optional[str] = None) -> Tok:
        t = self.peek()
        if t is None:
            raise ParseError(f"Unexpected end of input; expected {kind} {value or ''}")
        if t.kind != kind or (value is not None and t.value != value):
            raise ParseError(
                f"Expected {kind} {value!r} but got {t.kind} {t.value!r} "
                f"at {t.line}:{t.col}"
            )
        self.pos += 1
        return t

    def accept(self, kind: str, value: Optional[str] = None) -> Optional[Tok]:
        t = self.peek()
        if t and t.kind == kind and (value is None or t.value == value):
            self.pos += 1
            return t
        return None

    # --- top-level ---------------------------------------------------
    def parse_unit(self, owner: Package) -> Package:
        while self.peek() is not None:
            self._parse_member(owner)
        return owner

    def _parse_member(self, owner: Package) -> None:
        # Skip free-floating doc comments — attach to next element later.
        doc = None
        while (t := self.peek()) and t.kind == "doc":
            doc = t.value
            self.pos += 1

        t = self.peek()
        if t is None:
            return
        if t.kind != "kw":
            raise ParseError(f"Expected keyword at {t.line}:{t.col}, got {t.value!r}")

        if t.value == "package":
            self._parse_package(owner)
        elif t.value == "enum":
            self._parse_enum(owner, doc)
        elif t.value == "connect":
            self._parse_connect(owner)
        elif t.value in _DEF_KIND:
            # Either a def or a usage: distinguished by next token.
            kw = t.value
            self.pos += 1
            if self.accept("kw", "def"):
                self._parse_def(owner, kw, doc)
            else:
                self._parse_usage(owner, kw)
        else:
            raise ParseError(f"Unexpected keyword {t.value!r} at {t.line}:{t.col}")

    def _parse_package(self, owner: Package) -> None:
        self.eat("kw", "package")
        name = self.eat("id").value
        pkg = Package(name=name)
        owner.own(pkg)
        self.eat("sym", "{")
        while not self.accept("sym", "}"):
            self._parse_member(pkg)

    def _parse_def(self, owner: Package, kw: str, doc: Optional[str]) -> None:
        def_cls, _ = _DEF_KIND[kw]
        name = self.eat("id").value
        kwargs = {"name": name}
        # Optional `: Super`
        supers: list[str] = []
        if self.accept("sym", ":"):
            supers.append(self._parse_qname())
            while self.accept("sym", ","):
                supers.append(self._parse_qname())
        # Optional `id="REQ-1"` for requirements.
        req_id = None
        if kw == "requirement" and self.accept("kw", "id"):
            self.eat("sym", "=")
            req_id = self.eat("str").value
            kwargs["req_id"] = req_id
        defn = def_cls(**kwargs)
        if doc:
            from kerml.elements import Documentation
            defn.add_annotation(Documentation(body=doc))
        owner.own(defn)
        for s in supers:
            sup = owner.resolve(s) or owner.root().resolve(s) if hasattr(owner, "resolve") else None
            if sup is not None:
                defn.specialize(sup)  # type: ignore[arg-type]

        # Empty definition: `def Foo;`
        if self.accept("sym", ";"):
            return
        self.eat("sym", "{")
        while not self.accept("sym", "}"):
            t = self.peek()
            if t and t.kind == "doc":
                from kerml.elements import Documentation
                defn.add_annotation(Documentation(body=t.value))
                self.pos += 1
                continue
            if t and t.kind == "kw" and t.value == "doc":
                self.pos += 1
                d = self.eat("doc").value
                if hasattr(defn, "text"):
                    setattr(defn, "text", d)
                continue
            self._parse_member_inside_def(defn)

    def _parse_member_inside_def(self, defn) -> None:
        t = self.peek()
        if t is None or t.kind != "kw" or t.value not in _DEF_KIND:
            raise ParseError(
                f"Expected usage keyword inside definition at {t.line if t else '?'}"
            )
        kw = t.value
        _, use_cls = _DEF_KIND[kw]
        if use_cls is None:
            raise ParseError(f"Cannot use {kw!r} as a usage")
        self.pos += 1
        name = self.eat("id").value
        type_qn: Optional[str] = None
        if self.accept("sym", ":"):
            type_qn = self._parse_qname()
        mult: Optional[MultiplicityRange] = None
        if self.accept("sym", "["):
            mult = self._parse_multiplicity()
            self.eat("sym", "]")
        self.eat("sym", ";")
        usage = use_cls(name=name, multiplicity=mult or MultiplicityRange(1, 1))
        if type_qn:
            tgt = _resolve_in_scope(defn, type_qn)
            if tgt is not None:
                usage.add_type(tgt)
        defn.own(usage)
        if hasattr(defn, "addFeature"):
            defn.addFeature(usage)  # pragma: no cover - compat

    def _parse_usage(self, owner: Package, kw: str) -> None:
        _, use_cls = _DEF_KIND[kw]
        if use_cls is None:
            raise ParseError(f"Cannot use {kw!r} at namespace level")
        name = self.eat("id").value
        type_qn: Optional[str] = None
        if self.accept("sym", ":"):
            type_qn = self._parse_qname()
        mult = None
        if self.accept("sym", "["):
            mult = self._parse_multiplicity()
            self.eat("sym", "]")
        self.eat("sym", ";")
        u = use_cls(name=name, multiplicity=mult or MultiplicityRange(1, 1))
        if type_qn:
            tgt = owner.resolve(type_qn)
            if tgt is not None:
                u.add_type(tgt)
        owner.own(u)

    def _parse_connect(self, owner: Package) -> None:
        self.eat("kw", "connect")
        a = self._parse_qname()
        self.eat("kw", "to")
        b = self._parse_qname()
        self.eat("sym", ";")
        c = ConnectionUsage(name=f"connect_{a.replace('::','_')}_{b.replace('::','_')}")
        ea = owner.resolve(a)
        eb = owner.resolve(b)
        if ea is not None: c.ends.append(ea)  # type: ignore[arg-type]
        if eb is not None: c.ends.append(eb)  # type: ignore[arg-type]
        owner.own(c)

    def _parse_enum(self, owner: Package, doc: Optional[str]) -> None:
        self.eat("kw", "enum")
        self.eat("kw", "def")
        name = self.eat("id").value
        e = EnumerationDefinition(name=name)
        owner.own(e)
        self.eat("sym", "{")
        while not self.accept("sym", "}"):
            lit_name = self.eat("id").value
            self.accept("sym", ";")
            lit = EnumerationUsage(name=lit_name)
            lit.add_type(e)
            e.own(lit)
            e.literals.append(lit)

    def _parse_qname(self) -> str:
        parts = [self.eat("id").value]
        while self.accept("sym", "::"):
            parts.append(self.eat("id").value)
        return "::".join(parts)

    def _parse_multiplicity(self) -> MultiplicityRange:
        lo_tok = self.peek()
        if lo_tok and lo_tok.kind == "num":
            lo = int(lo_tok.value); self.pos += 1
        elif self.accept("sym", "*"):
            return MultiplicityRange(0, None)
        else:
            raise ParseError("Expected multiplicity")
        if self.accept("sym", ".."):
            t = self.peek()
            if t and t.kind == "num":
                hi = int(t.value); self.pos += 1
                return MultiplicityRange(lo, hi)
            if self.accept("sym", "*"):
                return MultiplicityRange(lo, None)
            raise ParseError("Expected upper bound")
        return MultiplicityRange(lo, lo)


def parse(source: str, *, into: Optional[Package] = None) -> Package:
    """Parse `source` text. If `into` is given, members are added to it."""
    pkg = into or Package(name="ParsedRoot")
    _Parser(_tokenize(source)).parse_unit(pkg)
    return pkg
