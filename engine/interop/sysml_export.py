"""Export a project to SysML v2 textual notation.

The output is standard SysML v2 syntax restricted to what ``engine.parse`` reads,
so ``engine.parse(export_sysml(repo), into=new_repo.root_package)`` recreates
packages, definitions (with specializations), usages (with types, multiplicities
and, where the parser supports them, directions), requirement ids and text,
documentation and connections.

Constructs the engine parser cannot read yet are still written, as ``//`` line
comments in SysML v2 form (for example ``// transition first Off then On;`` or
stereotype values ``// #LRU { mass = 2.5; }``), so the text stays readable and
re-parsable. Which constructs need a comment is decided by probing the parser
(directions, usage bodies, connectors inside definitions, forward references),
so an extended parser is used to its full extent without changing this module.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from kerml.elements import Annotation, Element, Relationship
from kerml.features import Feature, FeatureDirection
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, effective_applications
from sysmlv2.definitions import (
    ActionDefinition, ActionUsage, AnalysisCaseDefinition, AttributeDefinition,
    AttributeUsage, CalculationDefinition, CalculationUsage, ConcernDefinition,
    ConnectionDefinition, ConnectionUsage, ConstraintDefinition, ConstraintUsage, Definition,
    EnumerationDefinition, EnumerationUsage, InterfaceDefinition, ItemDefinition, ItemUsage,
    PartDefinition, PartUsage, PortDefinition, PortUsage, RequirementDefinition,
    RequirementUsage, StateDefinition, StateUsage, TransitionUsage, Usage, UseCaseDefinition,
    VerificationCaseDefinition, ViewpointDefinition,
)

from .common import (
    documentation, format_multiplicity, in_library, link_kind_name, model_links,
    relative_qname,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {
    "package", "def", "part", "item", "attribute", "port", "interface", "connection",
    "action", "state", "constraint", "requirement", "enum", "doc", "id", "to", "connect",
    "abstract", "in", "out", "inout",
}

# Keywords the engine parser understands, most specific class first.
_DEF_KEYWORDS: list[tuple[type, str, bool]] = [
    (ViewpointDefinition, "viewpoint", False),
    (ConcernDefinition, "concern", False),
    (RequirementDefinition, "requirement", True),
    (ConstraintDefinition, "constraint", True),
    (VerificationCaseDefinition, "verification", False),
    (AnalysisCaseDefinition, "analysis", False),
    (UseCaseDefinition, "use case", False),
    (CalculationDefinition, "calc", False),
    (StateDefinition, "state", True),
    (ActionDefinition, "action", True),
    (PartDefinition, "part", True),
    (ItemDefinition, "item", True),
    (PortDefinition, "port", True),
    (InterfaceDefinition, "interface", True),
    (ConnectionDefinition, "connection", True),
    (AttributeDefinition, "attribute", True),
]
_USAGE_KEYWORDS: list[tuple[type, str, bool]] = [
    (RequirementUsage, "requirement", True),
    (ConstraintUsage, "constraint", False),
    (TransitionUsage, "transition", False),
    (StateUsage, "state", True),
    (CalculationUsage, "calc", False),
    (ActionUsage, "action", True),
    (PartUsage, "part", True),
    (ItemUsage, "item", True),
    (PortUsage, "port", True),
    (ConnectionUsage, "connection", True),
    (AttributeUsage, "attribute", True),
]


# --- parser capability probes ------------------------------------------------

def _probe(source: str, check) -> bool:
    from engine.parser import parse
    from kerml.namespaces import Package as _Pkg
    try:
        root = parse(source, into=_Pkg(name="Probe"))
        return bool(check(root))
    except Exception:  # noqa: BLE001 - any failure means "not supported"
        return False


@lru_cache(maxsize=1)
def parser_capabilities() -> dict[str, bool]:
    """What the installed ``engine.parse`` supports beyond the documented subset."""
    def find(root, name):
        return next((e for e in root.walk() if e.name == name), None)

    return {
        "direction": _probe("part def A { in port p; }",
                            lambda r: find(r, "p").direction is FeatureDirection.IN),
        "usage_body": _probe("part def A { part b { port c; } }",
                             lambda r: find(r, "c") is not None and find(r, "c").owner.name == "b"),
        "connect_in_def": _probe(
            "part def B { port p; } part def A { part x : B; part y : B; connect x.p to y.p; }",
            lambda r: any(isinstance(e, ConnectionUsage) and len(e.ends) == 2 for e in r.walk())),
        "forward_ref": _probe("part def A { part b : B; } part def B;",
                              lambda r: bool(find(r, "b").types)),
        "keyword_names": _probe("part def A { port in; }", lambda r: find(r, "in") is not None),
        "scoped_package_usages": _probe("package P { part def T; } package Q { part x : P::T; }",
                                        lambda r: bool(find(r, "x").types)),
    }


# --- helpers -------------------------------------------------------------------

def _keyword(e: Element, table) -> tuple[Optional[str], bool]:
    for cls, kw, ok in table:
        if isinstance(e, cls):
            return kw, ok
    return None, False


def _doc_text(text: str) -> str:
    return (text or "").replace("*/", "* /")


def _children(e: Element) -> list[Element]:
    return [c for c in e.owned_elements if not isinstance(c, (Relationship, Annotation))]


def _resolve_in_scope(start: Optional[Element], qname: str) -> Optional[Element]:
    node = start
    while node is not None:
        if isinstance(node, Namespace):
            hit = node.resolve(qname)
            if hit is not None:
                return hit
        node = node.owner
    return None


def _lib_relative(e: Element) -> str:
    """``KerML::ScalarValues::Real`` -> ``ScalarValues::Real`` (the project root imports both libraries)."""
    qn = e.qualified_name
    return qn.split("::", 1)[1] if "::" in qn else qn


class _Writer:
    def __init__(self, repo, caps: dict[str, bool]):
        self.repo = repo
        self.root = repo.root_package
        self.caps = caps
        self.lines: list[str] = []

    # --- names --------------------------------------------------------------
    def name_ok(self, name: Optional[str], *, allow_keywords: bool = False) -> bool:
        if not name or not _IDENT.match(name):
            return False
        if name in _RESERVED:
            return allow_keywords and name in ("in", "out", "inout") and self.caps["keyword_names"]
        return True

    @staticmethod
    def show_name(name: Optional[str]) -> str:
        if name and _IDENT.match(name) and name not in _RESERVED:
            return name
        return "'" + (name or "").replace("'", "\\'") + "'"

    def ref(self, target: Element, scope: Element, *, walk_up: bool = True) -> str:
        """A name for `target` that the parser resolves from `scope`."""
        resolve = (lambda q: _resolve_in_scope(scope, q)) if walk_up else \
            (lambda q: scope.resolve(q) if isinstance(scope, Namespace) else None)
        candidates = []
        if target.name:
            candidates.append(target.name)
        if in_library(target):
            candidates.append(_lib_relative(target))
        else:
            # Path relative to each enclosing namespace, nearest first, then from the root.
            node: Optional[Element] = scope
            while node is not None:
                rel = self._path_from(node, target)
                if rel:
                    candidates.append(rel)
                node = node.owner
            candidates.append(relative_qname(target, self.repo))
        for c in candidates:
            if all(self.name_ok(p) for p in c.split("::")) and resolve(c) is target:
                return c
        best = candidates[-1] if candidates else "?"
        return "::".join(self.show_name(p) for p in best.split("::"))

    @staticmethod
    def _path_from(ancestor: Element, e: Element) -> Optional[str]:
        parts: list[str] = []
        node: Optional[Element] = e
        while node is not None and node is not ancestor:
            if not node.name:
                return None
            parts.append(node.name)
            node = node.owner
        return "::".join(reversed(parts)) if node is ancestor and parts else None

    # --- output -----------------------------------------------------------------
    def emit(self, depth: int, text: str, commented: bool) -> None:
        pad = "    " * depth
        prefix = "// " if commented else ""
        for line in text.split("\n"):
            self.lines.append(f"{pad}{prefix}{line}".rstrip())

    def comment(self, depth: int, text: str) -> None:
        self.emit(depth, text, True)

    def stereotype_comments(self, e: Element, depth: int) -> None:
        """``#Profile.Stereotype { mass = 1.5 [kg]; }`` (metadata usage with unit literals).

        A reference component lists the values it reads: its own and, for a stereotype it
        inherits from its definition, the definition's (the line says so)."""
        for app in effective_applications(e):
            values = []
            tags = [t for _st, props in app.stereotype.property_groups() for t in props]
            for tag in tags:                    # inherited (base) properties first
                v = app.get(tag.name)
                if v is None:
                    continue
                unit = f" [{tag.unit}]" if tag.unit and isinstance(v, (int, float)) \
                    and not isinstance(v, bool) else ""
                values.append(f"{tag.name} = {self.literal(v)}{unit}")
            body = f" {{ {'; '.join(values)}; }}" if values else ""
            where = f"  (inherited from {app.definition.name})" if app.inherited else ""
            self.comment(depth, f"#{app.stereotype.full_name}{body}{where}")

    @staticmethod
    def literal(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    # --- ordering ---------------------------------------------------------------
    def ordered(self, owner: Element) -> list[Element]:
        kids = _children(owner)
        if self.caps["forward_ref"] or len(kids) < 2:
            return kids
        index = {id(k): i for i, k in enumerate(kids)}

        def top(x: Element) -> Optional[int]:
            node: Optional[Element] = x
            while node is not None and node.owner is not owner:
                node = node.owner
            return index.get(id(node)) if node is not None else None

        deps: dict[int, set[int]] = {i: set() for i in range(len(kids))}
        for i, k in enumerate(kids):
            for x in k.walk():
                refs = list(getattr(x, "types", []) if isinstance(x, Feature) else [])
                refs += [s.target for s in getattr(x, "specializations", []) if s.target]
                refs += [end for end in getattr(x, "ends", []) or [] if end is not None]
                for r in refs:
                    j = top(r)
                    if j is not None and j != i:
                        deps[i].add(j)
        done: list[int] = []
        placed: set[int] = set()
        while len(done) < len(kids):
            ready = [i for i in range(len(kids)) if i not in placed and deps[i] <= placed]
            if not ready:          # a cycle: keep the remaining order
                ready = [min(i for i in range(len(kids)) if i not in placed)]
            done.append(ready[0])
            placed.add(ready[0])
        return [kids[i] for i in done]

    # --- members ----------------------------------------------------------------
    def member(self, e: Element, depth: int, ctx: str, commented: bool) -> None:
        """ctx: 'package' (package/root body), 'def' (definition body), 'usage' (usage body)."""
        if isinstance(e, Stereotype):
            self.stereotype_def(e, depth)
        elif isinstance(e, Package):
            self.package(e, depth, ctx, commented)
        elif isinstance(e, EnumerationDefinition):
            self.enum(e, depth, ctx, commented)
        elif isinstance(e, ConnectionUsage):
            self.connection(e, depth, ctx, commented)
        elif isinstance(e, TransitionUsage):
            self.transition(e, depth)
        elif isinstance(e, Definition):
            self.definition(e, depth, ctx, commented)
        elif isinstance(e, Usage):
            self.usage(e, depth, ctx, commented)
        else:
            self.comment(depth, f"{e.kind.lower()} {self.show_name(e.name)};")

    def package(self, p: Package, depth: int, ctx: str, commented: bool) -> None:
        ok = commented or (ctx == "package" and self.name_ok(p.name))
        c = commented or not ok
        doc = documentation(p)
        if doc:
            self.comment(depth, f"doc /* {_doc_text(doc)} */")
        self.stereotype_comments(p, depth)
        self.emit(depth, f"package {self.show_name(p.name)} {{", c)
        for child in self.ordered(p):
            self.member(child, depth + 1, "package", c)
        self.emit(depth, "}", c)

    def stereotype_def(self, st: Stereotype, depth: int) -> None:
        tags = [t for t in getattr(st, "tags", [])]
        base = f" :> {st.base.full_name}" if st.base is not None else ""
        self.comment(depth, f"metadata def {self.show_name(st.name)}{base} {{")
        for t in tags:
            typ = getattr(t, "prop_type", "") or ""
            unit = getattr(t, "unit", "") or ""
            default = f" = {self.literal(t.default_value)}" if t.default_value is not None else ""
            suffix = f"  /* {unit} */" if unit else ""
            self.comment(depth + 1, f"attribute {self.show_name(t.name)}"
                                    f"{' : ' + typ if typ else ''}{default};{suffix}")
        self.comment(depth, "}")

    def enum(self, e: EnumerationDefinition, depth: int, ctx: str, commented: bool) -> None:
        c = commented or ctx != "package" or not self.name_ok(e.name) or any(
            not self.name_ok(lit.name) for lit in _children(e))
        doc = documentation(e)
        if doc:
            self.emit(depth, f"/* {_doc_text(doc)} */", c)
        self.emit(depth, f"enum def {self.show_name(e.name)} {{", c)
        for lit in _children(e):
            if isinstance(lit, EnumerationUsage):
                self.emit(depth + 1, f"{self.show_name(lit.name)};", c)
            else:
                self.comment(depth + 1, f"{lit.kind} {self.show_name(lit.name)};")
        self.emit(depth, "}", c)

    def definition(self, d: Definition, depth: int, ctx: str, commented: bool) -> None:
        kw, supported = _keyword(d, _DEF_KEYWORDS)
        if kw is None:
            kw = d.kind.replace("Definition", "").lower() or "occurrence"
            supported = False
        c = commented or not (supported and ctx == "package" and self.name_ok(d.name))
        head = "abstract " if d.is_abstract else ""
        head += f"{kw} def {self.show_name(d.name)}"
        gens = [s.target for s in getattr(d, "specializations", []) if s.target is not None]
        if gens:
            head += " : " + ", ".join(self.ref(g, d.owner or self.root) for g in gens)
        if isinstance(d, RequirementDefinition) and d.req_id:
            head += f' id="{d.req_id.replace(chr(34), chr(39))}"'
        self.stereotype_comments(d, depth)
        if d.is_abstract and not c:
            # The parser has no `abstract` keyword: keep it as a comment above the definition.
            self.comment(depth, "abstract")
            head = head[len("abstract "):]
        doc = documentation(d)
        text = getattr(d, "text", None) if isinstance(d, RequirementDefinition) else None
        kids = self.ordered(d)
        if not doc and not text and not kids:
            self.emit(depth, head + ";", c)
            return
        self.emit(depth, head + " {", c)
        if doc:
            self.emit(depth + 1, f"/* {_doc_text(doc)} */", c)
        if text:
            self.emit(depth + 1, f"doc /* {_doc_text(text)} */", c)
        for child in kids:
            self.member(child, depth + 1, "def", c)
        self.emit(depth, "}", c)

    def usage(self, u: Usage, depth: int, ctx: str, commented: bool) -> None:
        kw, supported = _keyword(u, _USAGE_KEYWORDS)
        if kw is None:
            kw = u.kind.replace("Usage", "").lower() or "ref"
            supported = False
        if isinstance(u, ConnectionUsage):
            supported = True
        in_body = ctx in ("def", "usage")
        if ctx == "usage" and not self.caps["usage_body"]:
            supported = False
        name_ok = self.name_ok(u.name, allow_keywords=in_body)
        c = commented or not (supported and name_ok)
        direction = u.direction if u.direction is not FeatureDirection.NONE else None
        prefix = ""
        trailing: list[str] = []
        if direction is not None:
            if c or (in_body and self.caps["direction"]):
                prefix = f"{direction.value} "
            else:
                trailing.append(direction.value)
        name = u.name if name_ok else self.show_name(u.name)
        line = f"{prefix}{kw} {name}"
        scope = u.owner or self.root
        walk_up = in_body or self.caps["scoped_package_usages"]
        if u.types:
            line += " : " + ", ".join(self.ref(t, scope, walk_up=walk_up) for t in u.types)
        if (u.multiplicity.lower, u.multiplicity.upper) != (1, 1):
            m = format_multiplicity(u.multiplicity)
            line += f" [{'0..*' if m == '*' else m}]"
        if u.default_value is not None and not callable(u.default_value):
            trailing.append(f"= {self.literal(u.default_value)}")
        doc = documentation(u)
        text = getattr(u, "text", None) if isinstance(u, RequirementUsage) else None
        req_id = getattr(u, "req_id", None) if isinstance(u, RequirementUsage) else None
        kids = self.ordered(u)
        body_ok = c or (in_body and self.caps["usage_body"])
        self.stereotype_comments(u, depth)
        if req_id:
            self.comment(depth, f"id = \"{req_id}\"")
        if not (doc or text or kids) or not body_ok:
            tail = f"  // {' '.join(trailing)}" if trailing and not c else (
                f" /* {' '.join(trailing)} */" if trailing else "")
            self.emit(depth, line + ";" + tail, c)
            if doc:
                self.comment(depth + 1, f"doc /* {_doc_text(doc)} */")
            if text:
                self.comment(depth + 1, f"doc /* {_doc_text(text)} */  (requirement text)")
            for child in kids:
                self.member(child, depth + 1, "usage", True)
            return
        if trailing and not c:
            self.comment(depth, " ".join(trailing))
        self.emit(depth, line + " {", c)
        if doc:
            self.emit(depth + 1, f"/* {_doc_text(doc)} */", c)
        if text:
            self.emit(depth + 1, f"doc /* {_doc_text(text)} */", c)
        for child in kids:
            self.member(child, depth + 1, "usage", c)
        self.emit(depth, "}", c)

    def _end_path(self, conn: ConnectionUsage, i: int, end: Element) -> Optional[list[str]]:
        """Dotted path of a connector end as seen from the connector's owner."""
        comp = conn.owner
        owners = [comp] + [t for t in (getattr(comp, "types", []) or [])]
        ctx = tuple(getattr(conn, "end_contexts", ()) or ())
        context = ctx[i] if len(ctx) == len(conn.ends) else None
        if context is not None and end.name and context.name:
            return [context.name, end.name]
        if any(end.owner is o for o in owners) and end.name:
            return [end.name]
        o = end.owner
        if o is not None and o.owner is not None and any(o.owner is x for x in owners) \
                and o.name and end.name:
            return [o.name, end.name]
        for c in [x for x in (comp.owned_elements if comp else []) if isinstance(x, PartUsage)]:
            if any(t is end.owner for t in c.types) and c.name and end.name:
                return [c.name, end.name]
        return None

    def connection(self, conn: ConnectionUsage, depth: int, ctx: str, commented: bool) -> None:
        ends = [x for x in conn.ends if x is not None]
        type_part = (" : " + ", ".join(self.ref(t, conn.owner or self.root) for t in conn.types)
                     if conn.types else "")
        label = f"connection {self.show_name(conn.name)}{type_part}" if conn.name else "connection"
        self.stereotype_comments(conn, depth)
        doc = documentation(conn)
        if doc:
            self.comment(depth, f"doc /* {_doc_text(doc)} */")
        if len(ends) < 2:
            self.comment(depth, f"{label};  (fewer than two ends)")
            return
        if ctx == "package":
            paths = []
            for end in ends[:2]:
                p = self._path_from(conn.owner, end) if conn.owner is not None else None
                if p is None or not all(self.name_ok(s) for s in p.split("::")) or \
                        (conn.owner.resolve(p) if isinstance(conn.owner, Namespace) else None) \
                        is not end:
                    paths = []
                    break
                paths.append(p)
            ok = bool(paths) and not commented
            text_ends = paths or [relative_qname(e_, self.repo) for e_ in ends[:2]]
        else:
            raw = [self._end_path(conn, i, end) for i, end in enumerate(ends[:2])]
            ok = (not commented and ctx == "def" and self.caps["connect_in_def"]
                  and all(r is not None for r in raw)
                  and all(self.name_ok(s, allow_keywords=True) for r in raw for s in r))
            text_ends = [".".join(r) if r is not None else relative_qname(ends[i], self.repo)
                         for i, r in enumerate(raw)]
        if ok:
            if conn.name or conn.types:
                self.comment(depth, f"{label}")
            self.emit(depth, f"connect {text_ends[0]} to {text_ends[1]};", False)
        else:
            self.comment(depth, f"{label} connect {text_ends[0]} to {text_ends[1]};")
        for extra in ends[2:]:
            self.comment(depth, f"  (additional end {relative_qname(extra, self.repo)})")

    def transition(self, t: TransitionUsage, depth: int) -> None:
        src = getattr(t, "transition_source", None)
        tgt = getattr(t, "transition_target", None)
        parts = [f"transition {self.show_name(t.name)}"]
        if src is not None:
            parts.append(f"first {self.show_name(src.name)}")
        trig = getattr(t, "trigger_event", None)
        if isinstance(trig, str) and trig:
            parts.append(f"accept {trig}")
        guard = getattr(t, "guard", None)
        if isinstance(guard, str) and guard:
            parts.append(f"if {guard}")
        effect = getattr(t, "effect", None)
        if isinstance(effect, str) and effect:
            parts.append(f"do {effect}")
        if tgt is not None:
            parts.append(f"then {self.show_name(tgt.name)}")
        self.comment(depth, " ".join(parts) + ";")

    def links(self) -> None:
        rels = model_links(self.repo)
        if not rels:
            return
        self.lines.append("")
        self.lines.append("// Traceability links")
        for rel in rels:
            kind = link_kind_name(rel)
            src = relative_qname(rel.source, self.repo)
            tgt = relative_qname(rel.target, self.repo)
            if kind == "satisfy":
                text = f"satisfy {tgt} by {src};"
            elif kind == "verify":
                text = f"verify {tgt} by {src};"
            else:
                text = f"#{kind} dependency from {src} to {tgt};"
            self.comment(0, text)

    def unit(self) -> str:
        self.lines.append(f"// SysML v2 textual notation: project {self.repo.name}")
        self.lines.append("// Exported by SysML v2 Studio. Lines that start with // hold "
                          "constructs the engine parser does not read yet.")
        self.lines.append("")
        doc = documentation(self.root)
        if doc:
            self.comment(0, f"doc /* {_doc_text(doc)} */")
        for child in self.ordered(self.root):
            self.member(child, 0, "package", False)
        self.links()
        return "\n".join(self.lines) + "\n"


def export_sysml(repo) -> str:
    """The whole project as SysML v2 text (parse it back with ``engine.parse``)."""
    return _Writer(repo, parser_capabilities()).unit()


def import_sysml(repo, text: str) -> list[Element]:
    """Parse SysML v2 text into `repo`'s root; returns the new elements (creation hooks run)."""
    from engine.hooks import notify_created
    from engine.parser import parse
    before = {id(e) for e in repo.root_package.walk()}
    parse(text, into=repo.root_package)
    created = [e for e in repo.root_package.walk() if id(e) not in before]
    repo.registry.register_tree(repo.root_package)
    for e in created:
        notify_created(e, repo)
    return created
