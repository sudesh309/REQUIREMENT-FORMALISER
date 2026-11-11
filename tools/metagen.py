"""Generate the metamodel registry data from the reflective abstract-syntax models.

    python -m tools.metagen            # (re)write the generated modules
    python -m tools.metagen --check    # exit 1 if the committed modules are stale

Reads ``KerML.kerml`` and ``SysML.sysml`` (``sysml_spec``) and writes two data
modules (ADR 0002, decision 1):

- ``kerml/_metamodel_kerml.py``: the KerML metaclasses and enumerations;
- ``sysmlv2/_metamodel_sysml.py``: the SysML ones.

The reflective models use a small, regular subset of the textual notation:
packages, imports, ``doc`` comments, ``[abstract] metaclass`` (KerML) and
``[abstract] metadata def`` (SysML) declarations with ``specializes`` lists,
property features (``derived``, ``abstract``, ``composite``, ``var``, ``ref``;
``feature`` / ``item`` / ``attribute``; ``ordered``, ``nonunique``, ``subsets``,
``redefines``), and enumerations written as a ``datatype`` of ``member
feature``s (KerML) or as an ``enum def`` (SysML). Anything else is an error, so
a new construct in a future release is noticed rather than skipped.

``subsets`` / ``redefines`` names are resolved to ``Metaclass::property`` in
the owner (``subsets`` only) or its supertypes, nearest first. References to the
library plumbing that makes the reflective model valid KerML/SysML, rather than
part of the abstract syntax, are dropped: ``subsets Metadata::metadataItems``
(every SysML property) and ``redefines annotatedElement`` where it names
``Metaobjects::Metaobject::annotatedElement`` (``AnnotatingElement`` and
``Annotation``).

Composite: KerML says ``composite``; in SysML an ``item`` without ``ref`` is
composite, a ``ref item`` or an ``attribute`` is not.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import sysml_spec

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = {"KerML": ROOT / "kerml" / "_metamodel_kerml.py",
           "SysML": ROOT / "sysmlv2" / "_metamodel_sysml.py"}
SOURCES = {"KerML": sysml_spec.KERML_REFLECTIVE, "SysML": sysml_spec.SYSML_REFLECTIVE}

# Types of attribute-like properties (ScalarValues); everything else must be a
# metaclass or an enumeration of the reflective models.
SCALAR_TYPES = {"Boolean", "String", "Integer", "Natural", "Rational", "Real",
                "UnlimitedNatural", "Number", "Complex"}
# Plumbing: names of the reflective libraries, not of the abstract syntax.
PLUMBING_QUALIFIED_PREFIXES = ("Metadata::", "Metaobjects::")
PLUMBING_INHERITED = {"annotatedElement": "Metaobjects::Metaobject::annotatedElement"}

_MODIFIERS = {"derived", "abstract", "composite", "var", "const", "readonly", "ref",
              "portion", "end"}
_FEATURE_KEYWORDS = {"feature", "item", "attribute"}
_VISIBILITY = {"public", "private", "protected"}


class MetagenError(ValueError):
    """The reflective model contains something the generator does not understand."""


# --- model ------------------------------------------------------------------

@dataclass
class Prop:
    name: str
    type: str
    lower: int
    upper: int | None
    ordered: bool = False
    unique: bool = True
    derived: bool = False
    composite: bool = False
    abstract: bool = False
    var: bool = False
    readonly: bool = False
    subsets: list[str] = field(default_factory=list)
    redefines: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class Meta:
    name: str
    package: str
    abstract: bool
    supertypes: list[str]
    properties: list[Prop]
    line: int = 0


@dataclass
class Enum:
    name: str
    package: str
    literals: list[str]


@dataclass
class Model:
    language: str
    source: Path
    metaclasses: list[Meta] = field(default_factory=list)
    enums: list[Enum] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)   # plumbing reference -> count


# --- lexer ------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<doc>\bdoc\b\s*/\*.*?\*/)
  | (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<qname>'(?:[^'\\]|\\.)*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<number>\d+)
  | (?P<sym>:>>|:>|::|\.\.|\*\*|[:;,{}\[\]*])
""", re.VERBOSE | re.DOTALL)


@dataclass
class Tok:
    kind: str      # "name", "number", "sym", "eof"
    text: str
    line: int


def tokenize(text: str) -> list[Tok]:
    out: list[Tok] = []
    pos, line = 0, 1
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise MetagenError(f"line {line}: unexpected character {text[pos]!r}")
        kind, value = m.lastgroup, m.group()
        if kind == "qname":
            out.append(Tok("name", value[1:-1].replace("\\'", "'"), line))
        elif kind in ("name", "number", "sym"):
            out.append(Tok(kind, value, line))
        line += value.count("\n")
        pos = m.end()
    out.append(Tok("eof", "", line))
    return out


# --- parser -----------------------------------------------------------------

class _Parser:
    def __init__(self, model: Model, tokens: list[Tok]):
        self.model, self.toks, self.i = model, tokens, 0

    # token helpers
    def peek(self, ahead: int = 0) -> Tok:
        return self.toks[min(self.i + ahead, len(self.toks) - 1)]

    def next(self) -> Tok:
        tok = self.peek()
        self.i += 1
        return tok

    def accept(self, text: str) -> bool:
        if self.peek().text == text and self.peek().kind != "eof":
            self.i += 1
            return True
        return False

    def expect(self, text: str) -> Tok:
        tok = self.next()
        if tok.text != text:
            raise MetagenError(f"{self.model.source.name}:{tok.line}: expected {text!r}, "
                               f"found {tok.text or 'end of file'!r}")
        return tok

    def name(self) -> str:
        tok = self.next()
        if tok.kind != "name":
            raise MetagenError(f"{self.model.source.name}:{tok.line}: expected a name, "
                               f"found {tok.text!r}")
        return tok.text

    def qualified_name(self) -> str:
        parts = [self.name()]
        while self.peek().text == "::" and self.peek(1).kind == "name":
            self.next()
            parts.append(self.name())
        return "::".join(parts)

    def error(self, what: str) -> MetagenError:
        tok = self.peek()
        return MetagenError(f"{self.model.source.name}:{tok.line}: {what} (at {tok.text!r})")

    # grammar
    def file(self) -> None:
        self.accept("standard")
        self.accept("library")
        self.expect("package")
        top = self.name()
        if top != self.model.language:
            raise self.error(f"top-level package is {top!r}, expected {self.model.language!r}")
        self.expect("{")
        self.body([])
        self.expect("}")
        if self.peek().kind != "eof":
            raise self.error("text after the top-level package")

    def body(self, path: list[str]) -> None:
        while self.peek().text != "}" and self.peek().kind != "eof":
            tok = self.peek()
            if tok.text == "doc":                       # doc without a comment body
                self.next()
            elif tok.text in _VISIBILITY or tok.text == "import":
                self.import_()
            elif tok.text == "package":
                self.next()
                name = self.name()
                self.expect("{")
                self.body(path + [name])
                self.expect("}")
            elif tok.text in ("abstract", "metaclass", "metadata"):
                self.metaclass(path)
            elif tok.text == "datatype":
                self.datatype(path)
            elif tok.text == "enum" and self.peek(1).text == "def":
                self.enum_def(path)
            else:
                raise self.error("unexpected declaration")

    def import_(self) -> None:
        self.accept("public") or self.accept("private") or self.accept("protected")
        self.expect("import")
        self.qualified_name()
        while self.accept("::"):
            if not (self.accept("*") or self.accept("**")):
                raise self.error("expected '*' in import")
        self.expect(";")

    def specializes(self) -> list[str]:
        if not (self.accept("specializes") or self.accept(":>")):
            return []
        names = [self.qualified_name()]
        while self.accept(","):
            names.append(self.qualified_name())
        return [n.split("::")[-1] for n in names]

    def metaclass(self, path: list[str]) -> None:
        line = self.peek().line
        abstract = self.accept("abstract")
        if self.accept("metadata"):
            self.expect("def")
        else:
            self.expect("metaclass")
        meta = Meta(self.name(), "::".join(path), abstract, [], [], line)
        meta.supertypes = self.specializes()
        if not path:
            raise self.error(f"metaclass {meta.name} outside a package")
        if not self.accept(";"):
            self.expect("{")
            while not self.accept("}"):
                if self.peek().text == "doc":
                    self.next()
                    continue
                meta.properties.append(self.property())
        self.model.metaclasses.append(meta)

    def multiplicity(self) -> tuple[int, int | None]:
        self.expect("[")

        def bound() -> int | None:
            tok = self.next()
            if tok.text == "*":
                return None
            if tok.kind != "number":
                raise MetagenError(f"{self.model.source.name}:{tok.line}: bad multiplicity "
                                   f"bound {tok.text!r}")
            return int(tok.text)

        first = bound()
        if self.accept(".."):
            lower, upper = first, bound()
        else:                                   # [n] is n..n, [*] is 0..*
            lower, upper = (0, None) if first is None else (first, first)
        self.expect("]")
        if lower is None:
            raise self.error("lower bound '*'")
        return lower, upper

    def property(self) -> Prop:
        line = self.peek().line
        mods: set[str] = set()
        while self.peek().text in _MODIFIERS:
            mods.add(self.next().text)
        keyword = self.next().text
        if keyword not in _FEATURE_KEYWORDS:
            raise MetagenError(f"{self.model.source.name}:{line}: expected a property "
                               f"declaration, found {keyword!r}")
        name = self.name()
        self.expect(":")
        type_ = self.qualified_name().split("::")[-1]
        if self.peek().text != "[":
            raise self.error(f"property {name} has no multiplicity")
        lower, upper = self.multiplicity()
        prop = Prop(name, type_, lower, upper, line=line,
                    derived="derived" in mods, abstract="abstract" in mods,
                    var="var" in mods, readonly=bool(mods & {"const", "readonly"}))
        if keyword == "feature":
            prop.composite = "composite" in mods
        else:   # SysML usages: `item` is composite unless `ref`; attributes never are
            prop.composite = "composite" in mods or (keyword == "item" and "ref" not in mods)
        while not self.accept(";"):
            tok = self.next()
            if tok.text == "ordered":
                prop.ordered = True
            elif tok.text == "nonunique":
                prop.unique = False
            elif tok.text in ("subsets", ":>", "redefines", ":>>"):
                target = prop.subsets if tok.text in ("subsets", ":>") else prop.redefines
                target.append(self.qualified_name())
                while self.accept(","):
                    target.append(self.qualified_name())
            else:
                raise MetagenError(f"{self.model.source.name}:{tok.line}: unexpected "
                                   f"{tok.text!r} in property {name}")
        return prop

    def datatype(self, path: list[str]) -> None:
        """A KerML enumeration: ``datatype K { member feature 'x' : K[1]; ... }``."""
        self.expect("datatype")
        name = self.name()
        literals: list[str] = []
        self.expect("{")
        while not self.accept("}"):
            self.expect("member")
            self.expect("feature")
            literals.append(self.name())
            self.expect(":")
            if self.qualified_name().split("::")[-1] != name:
                raise self.error(f"datatype {name}: only enumeration literals are supported")
            if self.peek().text == "[":
                self.multiplicity()
            self.expect(";")
        self.model.enums.append(Enum(name, "::".join(path), literals))

    def enum_def(self, path: list[str]) -> None:
        self.expect("enum")
        self.expect("def")
        name = self.name()
        literals: list[str] = []
        self.expect("{")
        while not self.accept("}"):
            self.expect("enum")
            literals.append(self.name())
            self.expect(";")
        self.model.enums.append(Enum(name, "::".join(path), literals))


def parse(language: str, source: Path) -> Model:
    model = Model(language, source)
    _Parser(model, tokenize(source.read_text(encoding="utf-8"))).file()
    return model


# --- resolution -------------------------------------------------------------

def _closure(name: str, metas: dict[str, Meta]) -> list[str]:
    """Supertypes of ``name``, breadth first in declaration order, without duplicates."""
    out: list[str] = []
    queue = list(metas[name].supertypes)
    while queue:
        n = queue.pop(0)
        if n not in out:
            out.append(n)
            queue.extend(metas[n].supertypes)
    return out


def resolve(models: list[Model]) -> None:
    """Check names and resolve ``subsets`` / ``redefines`` in place (all models together)."""
    metas: dict[str, Meta] = {}
    enums: set[str] = set()
    for model in models:
        for e in model.enums:
            if e.name in enums:
                raise MetagenError(f"enumeration {e.name} declared twice")
            enums.add(e.name)
        for m in model.metaclasses:
            if m.name in metas:
                raise MetagenError(f"metaclass {m.name} declared twice")
            metas[m.name] = m
    for model in models:
        for m in model.metaclasses:
            for s in m.supertypes:
                if s not in metas:
                    raise MetagenError(f"{model.source.name}:{m.line}: {m.name} specializes "
                                       f"unknown {s}")
    for model in models:
        for m in model.metaclasses:
            search = [m.name] + _closure(m.name, metas)
            for p in m.properties:
                if p.type not in metas and p.type not in enums and p.type not in SCALAR_TYPES:
                    raise MetagenError(f"{model.source.name}:{p.line}: {m.name}::{p.name} has "
                                       f"unknown type {p.type}")
                for refs in (p.subsets, p.redefines):
                    resolved: list[str] = []
                    for ref in refs:
                        target = _resolve_ref(ref, p, search, metas, model)
                        if target is not None and target not in resolved:
                            resolved.append(target)
                    refs[:] = resolved


def _resolve_ref(ref: str, prop: Prop, search: list[str], metas: dict[str, Meta],
                 model: Model) -> str | None:
    if ref.startswith(PLUMBING_QUALIFIED_PREFIXES):
        model.dropped[ref] = model.dropped.get(ref, 0) + 1
        return None
    simple = ref.split("::")[-1]
    for owner in search:
        for q in metas[owner].properties:
            if q.name == simple and q is not prop:
                return f"{owner}::{simple}"
    if simple in PLUMBING_INHERITED:
        key = PLUMBING_INHERITED[simple]
        model.dropped[key] = model.dropped.get(key, 0) + 1
        return None
    raise MetagenError(f"{model.source.name}:{prop.line}: {search[0]}::{prop.name} refers to "
                       f"unknown property {ref}")


def load() -> list[Model]:
    models = [parse(lang, path) for lang, path in SOURCES.items()]
    resolve(models)
    return models


# --- output -----------------------------------------------------------------

_WIDTH = 99
_DEFAULTS = {"ordered": False, "unique": True, "derived": False, "composite": False,
             "abstract": False, "var": False, "readonly": False}


def _pack(items: list[str], first: str, indent: str, last: str) -> list[str]:
    """``first + items joined by ', ' + last``, wrapped at _WIDTH with ``indent``."""
    lines, cur = [], first
    for i, item in enumerate(items):
        piece = item + (", " if i < len(items) - 1 else last)
        if len(cur) + len(piece.rstrip()) > _WIDTH and cur.strip() not in ("", first.strip()):
            lines.append(cur.rstrip())
            cur = indent
        cur += piece
    lines.append(cur.rstrip())
    return lines


def _q(text: str) -> str:
    return json.dumps(text)


def _tuple_items(key: str, values: list[str]) -> list[str]:
    """``"key": ("a", "b")`` as pieces that ``_pack`` joins with ', ' (and may wrap)."""
    if len(values) == 1:
        return [f'"{key}": ({_q(values[0])},)']
    pieces = [_q(v) for v in values]
    pieces[0] = f'"{key}": (' + pieces[0]
    pieces[-1] += ")"
    return pieces


def _prop_lines(p: Prop) -> list[str]:
    items = [f'"name": {_q(p.name)}', f'"type": {_q(p.type)}', f'"lower": {p.lower}',
             f'"upper": {p.upper!r}']
    for key, default in _DEFAULTS.items():
        value = getattr(p, key)
        if value != default:
            items.append(f'"{key}": {value!r}')
    if p.subsets:
        items += _tuple_items("subsets", p.subsets)
    if p.redefines:
        items += _tuple_items("redefines", p.redefines)
    return _pack(items, "            {", "             ", "},")


def render(model: Model) -> str:
    rel = model.source.relative_to(ROOT).as_posix()
    n_props = sum(len(m.properties) for m in model.metaclasses)
    dropped = "; ".join(f"``{k}`` x{v}" for k, v in sorted(model.dropped.items())) or "none"
    out = [
        f'"""{model.language} metaclasses and enumerations of the reflective abstract-syntax model.',
        "",
        "GENERATED by ``python -m tools.metagen``: do not edit, regenerate.",
        "",
        f"- Source: ``{rel}``",
        f"- Release: {sysml_spec.RELEASE} (``sysml_spec.RELEASE``), {sysml_spec.SOURCE}",
        f"- {len(model.metaclasses)} metaclasses, {len(model.enums)} enumerations, "
        f"{n_props} owned properties",
        f"- Dropped references to library plumbing: {dropped}",
        "",
        "Data only; ``kerml.metamodel`` turns it into ``MetaclassSpec`` / ``PropertySpec`` /",
        "``EnumSpec``. Properties are in declaration order. Keys left out have their",
        "defaults: ordered=False, unique=True, derived=False, composite=False,",
        "abstract=False, var=False, readonly=False, subsets=(), redefines=(). ``upper``",
        "None is ``*``. ``subsets`` / ``redefines`` are resolved ``Metaclass::property`` names.",
        '"""',
        "",
        f"LANGUAGE = {_q(model.language)}",
        f"RELEASE = {_q(sysml_spec.RELEASE)}",
        f"SOURCE = {_q(rel)}",
        "",
        "METACLASSES = (",
    ]
    for m in model.metaclasses:
        out.append("    {")
        out.append(f'        "name": {_q(m.name)}, "package": {_q(m.package)}, '
                   f'"is_abstract": {m.abstract!r},')
        if m.supertypes:
            out.extend(_pack([_q(s) for s in m.supertypes], '        "supertypes": (',
                             "                       ",
                             ",)," if len(m.supertypes) == 1 else "),"))
        else:
            out.append('        "supertypes": (),')
        if m.properties:
            out.append('        "properties": (')
            for p in m.properties:
                out.extend(_prop_lines(p))
            out.append("        ),")
        else:
            out.append('        "properties": (),')
        out.append("    },")
    out.append(")")
    out.append("")
    out.append("ENUMS = (")
    for e in model.enums:
        out.extend(_pack([f'"name": {_q(e.name)}', f'"package": {_q(e.package)}']
                         + _tuple_items("literals", e.literals), "    {", "     ", "},"))
    out.append(")")
    return "\n".join(out) + "\n"


def generate() -> dict[Path, str]:
    """Output path -> generated text."""
    out = {OUTPUTS[m.language]: render(m) for m in load()}
    for path, text in out.items():
        compile(text, str(path), "exec")        # never write a module that cannot load
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.metagen")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a generated module is missing or differs")
    args = ap.parse_args(argv)
    stale = []
    for path, text in generate().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        stale.append(path)
        if not args.check:
            path.write_text(text, encoding="utf-8")
    rel = ", ".join(p.relative_to(ROOT).as_posix() for p in stale)
    if args.check:
        if stale:
            print(f"stale generated module(s): {rel}; run `python -m tools.metagen`")
            return 1
        print("generated metamodel modules are up to date")
    else:
        print(f"wrote {rel}" if stale else "generated metamodel modules are up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
