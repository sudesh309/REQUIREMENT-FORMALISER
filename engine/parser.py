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

Inside part (and other) definitions, additionally:

    in port <name> : <Type>;          // also `out port`, `inout port`, and
                                      // direction prefixes on other usages
    part <name> [: <Type>] { ... }    // inline component with its own members
    connect <a>.<p> to <b>.<q>;       // connector between ports of sub-parts;
                                      // a bare <p> is a port of the definition

Type names and connector ends may refer to definitions declared later in
the file (they are resolved after the whole unit is read).

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
    (?P<sym>::|\.\.|[{}\[\];:,=*.])
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


_DIRECTIONS = {"in": FeatureDirection.IN, "out": FeatureDirection.OUT,
               "inout": FeatureDirection.INOUT}


def _feature_named(owner, name: str):
    """A feature called `name` of `owner`, its types, or their supertypes."""
    from kerml.types import Type
    scopes = [owner] + list(getattr(owner, "types", []) or [])
    for scope in scopes:
        hit = next((e for e in scope.children if e.name == name), None)
        if hit is not None:
            return hit
        if isinstance(scope, Type):
            hit = next((f for f in scope.inherited_features() if f.name == name), None)
            if hit is not None:
                return hit
    return None


class _Parser:
    def __init__(self, toks: list[Tok]):
        self.toks = toks
        self.pos = 0
        # Forward references, resolved once the whole unit has been read.
        self.pending_types: list[tuple] = []      # (feature, scope, qname)
        self.pending_supers: list[tuple] = []     # (definition, scope, qname)
        self.pending_connects: list[tuple] = []   # (connector, scope, path_a, path_b)

    # --- deferred resolution ------------------------------------------
    def _type_later(self, feature, scope, qname: str) -> None:
        tgt = _resolve_in_scope(scope, qname)
        if tgt is not None:
            feature.add_type(tgt)
        else:
            self.pending_types.append((feature, scope, qname))

    def resolve_pending(self) -> None:
        for defn, scope, qname in self.pending_supers:
            sup = _resolve_in_scope(scope, qname)
            if sup is not None:
                defn.specialize(sup)
        for feature, scope, qname in self.pending_types:
            tgt = _resolve_in_scope(scope, qname)
            if tgt is not None:
                feature.add_type(tgt)
        for conn, scope, path_a, path_b in self.pending_connects:
            ends, ctxs = [], []
            for path in (path_a, path_b):
                ctx, end = self._resolve_path(scope, path)
                if end is not None:
                    ends.append(end)
                    ctxs.append(ctx)
            conn.ends = ends
            conn.end_contexts = tuple(ctxs) if len(ends) == 2 else ()

    @staticmethod
    def _resolve_path(scope, path: list[str]):
        """``a::b.c.d`` -> (context, element): the first segment is a (qualified) name in
        scope, the rest walk features; the context is the first-level part usage."""
        first = _resolve_in_scope(scope, path[0])
        if first is None and "::" in path[0]:
            # `part::port` written with '::': walk features after the first segment.
            head, *rest = path[0].split("::")
            return _Parser._resolve_path(scope, [head, *rest, *path[1:]])
        if first is None or len(path) == 1:
            return None, first
        node = first
        for seg in path[1:]:
            node = _feature_named(node, seg)
            if node is None:
                return None, None
        return first, node

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
            sup = _resolve_in_scope(owner, s)
            if sup is not None:
                defn.specialize(sup)  # type: ignore[arg-type]
            else:
                self.pending_supers.append((defn, owner, s))

        # Empty definition: `def Foo;`
        if self.accept("sym", ";"):
            return
        self.eat("sym", "{")
        self._parse_body(defn)

    def _parse_body(self, owner) -> None:
        """Members of a definition (or of a part usage with a body) up to the closing brace."""
        while not self.accept("sym", "}"):
            t = self.peek()
            if t and t.kind == "doc":
                from kerml.elements import Documentation
                owner.add_annotation(Documentation(body=t.value))
                self.pos += 1
                continue
            if t and t.kind == "kw" and t.value == "doc":
                self.pos += 1
                d = self.eat("doc").value
                if hasattr(owner, "text"):
                    setattr(owner, "text", d)
                continue
            self._parse_member_inside_def(owner)

    def _parse_member_inside_def(self, defn) -> None:
        t = self.peek()
        if t is not None and t.kind == "kw" and t.value == "connect":
            self._parse_connect(defn)
            return
        direction = None
        if t is not None and t.kind == "kw" and t.value in _DIRECTIONS:
            direction = _DIRECTIONS[t.value]
            self.pos += 1
            t = self.peek()
        if t is None or t.kind != "kw" or t.value not in _DEF_KIND:
            where = f"{t.line}:{t.col}" if t else "end of input"
            raise ParseError(f"Expected usage keyword inside definition at {where}")
        kw = t.value
        _, use_cls = _DEF_KIND[kw]
        if use_cls is None:
            raise ParseError(f"Cannot use {kw!r} as a usage")
        self.pos += 1
        name = self._eat_name()
        type_qn: Optional[str] = None
        if self.accept("sym", ":"):
            type_qn = self._parse_qname()
        mult: Optional[MultiplicityRange] = None
        if self.accept("sym", "["):
            mult = self._parse_multiplicity()
            self.eat("sym", "]")
        usage = use_cls(name=name, multiplicity=mult or MultiplicityRange(1, 1))
        if direction is not None:
            usage.direction = direction
        if type_qn:
            self._type_later(usage, defn, type_qn)
        defn.own(usage)
        if self.accept("sym", "{"):
            self._parse_body(usage)      # e.g. an inline component with its own ports
        else:
            self.eat("sym", ";")

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
            self._type_later(u, owner, type_qn)
        owner.own(u)

    def _parse_connect(self, owner) -> None:
        """`connect a to b;` with dotted ends (`part.port`); resolved after the unit is read."""
        self.eat("kw", "connect")
        a = self._parse_path()
        self.eat("kw", "to")
        b = self._parse_path()
        self.eat("sym", ";")
        flat = lambda p: "_".join(p).replace("::", "_")  # noqa: E731
        c = ConnectionUsage(name=f"connect_{flat(a)}_{flat(b)}")
        owner.own(c)
        self.pending_connects.append((c, owner, a, b))

    def _eat_name(self) -> str:
        """An identifier; direction keywords (in/out/inout) are accepted as names too."""
        t = self.peek()
        if t is not None and t.kind == "kw" and t.value in _DIRECTIONS:
            self.pos += 1
            return t.value
        return self.eat("id").value

    def _parse_path(self) -> list[str]:
        """`A::B.c.d` -> ['A::B', 'c', 'd']."""
        parts = [self._parse_qname()]
        while self.accept("sym", "."):
            parts.append(self._eat_name())
        return parts

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


def parse(source: str, *, into: Optional[Package] = None, repo=None) -> Package:
    """Parse `source` text. If `into` is given, members are added to it.

    With ``repo``, every new element is registered and announced through
    ``engine.notify_created`` (so features such as default stereotypes apply).
    """
    pkg = into or Package(name="ParsedRoot")
    before = {id(e) for e in pkg.walk()} if repo is not None else set()
    parser = _Parser(_tokenize(source))
    try:
        parser.parse_unit(pkg)
    finally:
        parser.resolve_pending()
    if repo is not None:
        from .hooks import notify_created
        repo.registry.register_tree(pkg)
        for e in [e for e in pkg.walk() if id(e) not in before]:
            notify_created(e, repo)
    return pkg


# Architecture semantics (port kinds, connector end contexts) persist through codecs
# registered by this module; importing it here makes them active with `import engine`.
from . import architecture as _architecture  # noqa: E402,F401
