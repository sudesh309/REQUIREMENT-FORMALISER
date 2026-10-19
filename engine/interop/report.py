"""HTML system architecture report (System Composer *Report Generator* style).

``generate_report(repo)`` returns one self-contained HTML document:

1. title page (title, model, author, date, contents)
2. model summary (counts, elements by kind)
3. architecture diagrams (Mermaid, one per root architecture) and traceability diagram
4. component hierarchy
5. components: documentation, reference definition, stereotype property values,
   ports (direction, kind, interface) and connectors
6. interfaces with their elements
7. requirements and traceability (satisfied / verified / derived ...) with coverage
8. validation issues (the Model Check result)
9. links appendix

Mermaid diagrams render in the page when the Mermaid script is available:
``mermaid="link"`` (default) loads ``mermaid_src`` (the studio's vendored copy),
``"inline"`` embeds the vendored script so the file works offline, ``"none"``
leaves the diagram sources as text.
"""
from __future__ import annotations

import datetime as _dt
import html
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from engine.structure import component_tree, components_of, connectors_of, definition_of, ports_of
from kerml.elements import Element
from kerml.features import Feature, FeatureDirection
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ConnectionUsage, PartDefinition, PartUsage, PortUsage, RequirementDefinition,
    RequirementUsage,
)

from .checks import run_model_check
from .common import (
    documentation, extra_attributes, format_multiplicity, in_library, is_profile_content,
    link_kind_name, model_links, project_elements, relative_qname, stereotype_full_name,
)
from .tables import _connection_end, _is_interface, table_of

SECTIONS = ["summary", "diagrams", "hierarchy", "components", "interfaces", "requirements",
            "validation", "links"]
SECTION_TITLES = {
    "summary": "Model summary", "diagrams": "Architecture diagrams",
    "hierarchy": "Component hierarchy", "components": "Components",
    "interfaces": "Interfaces", "requirements": "Requirements and traceability",
    "validation": "Validation", "links": "Links",
}
DEFAULT_MERMAID_SRC = "/static/vendor/mermaid-10.9.8.min.js"
_VENDOR = Path(__file__).resolve().parents[2] / "webapp" / "static" / "vendor"

_CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#1d4ed8; --soft:#f1f5f9; }
* { box-sizing: border-box; }
body { font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink);
       margin: 0; background: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 40px 64px; }
h1 { font-size: 30px; margin: 0 0 8px; }
h2 { font-size: 21px; margin: 40px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--accent); }
h3 { font-size: 16px; margin: 26px 0 8px; }
h4 { font-size: 13px; margin: 14px 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.title-page { min-height: 60vh; display: flex; flex-direction: column; justify-content: center;
              border-bottom: 1px solid var(--line); margin-bottom: 24px; }
.subtitle { font-size: 18px; color: var(--muted); margin-bottom: 24px; }
.meta { color: var(--muted); }
.meta td { padding: 2px 16px 2px 0; }
table.data { border-collapse: collapse; width: 100%; margin: 6px 0 12px; font-size: 13px; }
table.data th { text-align: left; background: var(--soft); border-bottom: 1px solid var(--line);
                padding: 5px 8px; font-weight: 600; }
table.data td { border-bottom: 1px solid var(--line); padding: 4px 8px; vertical-align: top; }
.kind { color: var(--muted); font-size: 12px; }
.stereo { color: #7c3aed; font-size: 12px; }
.badge { display: inline-block; padding: 0 6px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.sev-error { background: #fee2e2; color: #b91c1c; }
.sev-warning { background: #fef3c7; color: #92400e; }
.sev-info { background: #e0f2fe; color: #075985; }
.doc { white-space: pre-wrap; margin: 4px 0 8px; }
.empty { color: var(--muted); font-style: italic; }
.toc a { color: var(--accent); text-decoration: none; }
ul.tree { list-style: none; padding-left: 18px; margin: 4px 0; }
ul.tree > li { margin: 2px 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.card .n { font-size: 22px; font-weight: 700; }
.card .l { color: var(--muted); font-size: 12px; }
pre.mermaid, pre.mermaid-source { background: #fff; border: 1px solid var(--line); border-radius: 8px;
              padding: 12px; overflow: auto; }
pre.mermaid-source { font-size: 12px; }
.diagram-note { color: var(--muted); font-size: 12px; }
@media print { h2 { page-break-before: always; } .title-page { page-break-after: always; }
               main { padding: 0; } }
"""


def _e(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def _label(text: Any) -> str:
    """Text safe inside a quoted Mermaid label."""
    s = re.sub(r"\s+", " ", str(text or ""))
    return (s.replace("#", "#35;").replace('"', "#quot;").replace("<", "#lt;")
             .replace(">", "#gt;").replace("`", "'").replace("[", "(").replace("]", ")")
             .replace("{", "(").replace("}", ")").replace("|", "/"))


def _stereo_names(e: Element) -> str:
    return ", ".join(stereotype_full_name(a.stereotype) for a in stereotypes_on(e))


def _type_names(e: Element, repo) -> str:
    return ", ".join(relative_qname(t, repo) for t in getattr(e, "types", []) or []) \
        if isinstance(e, Feature) else ""


def root_architectures(repo) -> list[Element]:
    """Compositions at the top of the hierarchy (not used as a component type elsewhere)."""
    used = set()
    elements = project_elements(repo)
    for e in elements:
        if isinstance(e, PartUsage):
            d = definition_of(e)
            if d is not None:
                used.add(id(d))
    roots = [e for e in elements if isinstance(e, PartDefinition) and not is_profile_content(e)
             and id(e) not in used and components_of(e)]
    roots += [e for e in elements if isinstance(e, PartUsage) and not
              isinstance(e.owner, (PartDefinition, PartUsage)) and components_of(e)]
    return roots


class _Report:
    def __init__(self, repo, *, title: Optional[str], author: str, date: Optional[str],
                 sections: Iterable[str], mermaid: str, mermaid_src: str):
        self.repo = repo
        self.title = title or f"{repo.name} system architecture"
        self.author = author
        self.date = date or _dt.date.today().isoformat()
        self.sections = [s for s in SECTIONS if s in set(sections)]
        self.mermaid = mermaid
        self.mermaid_src = mermaid_src
        self.out: list[str] = []
        self.elements = project_elements(repo)
        self.links = model_links(repo)
        self.check = run_model_check(repo) if "validation" in self.sections or \
            "summary" in self.sections else None
        self.diagram_count = 0

    def w(self, s: str) -> None:
        self.out.append(s)

    # --- helpers ----------------------------------------------------------------
    def table(self, headers: list[str], rows: list[list[str]], empty: str = "None.") -> None:
        if not rows:
            self.w(f'<p class="empty">{_e(empty)}</p>')
            return
        self.w('<table class="data"><thead><tr>' + "".join(f"<th>{_e(h)}</th>" for h in headers)
               + "</tr></thead><tbody>")
        for r in rows:
            self.w("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
        self.w("</tbody></table>")

    def anchor(self, e: Element) -> str:
        return f"el-{re.sub(r'[^A-Za-z0-9_-]', '_', e.element_id)}"

    def ref(self, e: Optional[Element]) -> str:
        if e is None:
            return ""
        if in_library(e):
            return _e(e.qualified_name)
        return f'<a href="#{self.anchor(e)}">{_e(relative_qname(e, self.repo))}</a>'

    def diagram(self, source: str, caption: str) -> None:
        self.diagram_count += 1
        cls = "mermaid-source" if self.mermaid == "none" else "mermaid"
        self.w(f'<figure><pre class="{cls}" data-diagram="{self.diagram_count}">{_e(source)}</pre>'
               f'<figcaption class="diagram-note">{_e(caption)}</figcaption></figure>')

    # --- sections ------------------------------------------------------------------
    def title_page(self) -> None:
        self.w('<section class="title-page">')
        self.w(f"<h1>{_e(self.title)}</h1>")
        self.w('<div class="subtitle">System Architecture Report</div>')
        self.w('<table class="meta">')
        for k, v in (("Model", self.repo.name), ("Author", self.author), ("Date", self.date),
                     ("Generated by", "SysML v2 Studio")):
            if v:
                self.w(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>")
        self.w("</table>")
        doc = documentation(self.repo.root_package)
        if doc:
            self.w(f'<p class="doc">{_e(doc)}</p>')
        self.w('<h4>Contents</h4><ol class="toc">')
        for s in self.sections:
            self.w(f'<li><a href="#sec-{s}">{_e(SECTION_TITLES[s])}</a></li>')
        self.w("</ol></section>")

    def summary(self) -> None:
        tables: dict[str, int] = {}
        for e in self.elements:
            t = table_of(e)
            if t:
                tables[t] = tables.get(t, 0) + 1
        comps = [e for e in self.elements if isinstance(e, PartUsage)]
        archs = [e for e in self.elements if isinstance(e, PartDefinition)]
        reqs = [e for e in self.elements if isinstance(e, (RequirementDefinition, RequirementUsage))]
        cards = [("Architectures / component types", len(archs)), ("Components", len(comps)),
                 ("Ports", tables.get("Ports", 0)), ("Connectors", tables.get("Connections", 0)),
                 ("Interfaces", sum(1 for e in self.elements if _is_interface(e))),
                 ("Requirements", len(reqs)), ("Links", len(self.links)),
                 ("Stereotype applications", sum(len(stereotypes_on(e)) for e in self.elements))]
        if self.check:
            c = self.check["counts"]
            cards += [("Errors", c["error"]), ("Warnings", c["warning"])]
        self.w('<div class="cards">' + "".join(
            f'<div class="card"><div class="n">{n}</div><div class="l">{_e(l)}</div></div>'
            for l, n in cards) + "</div>")
        kinds: dict[str, int] = {}
        for e in self.elements:
            if not is_profile_content(e):
                kinds[e.kind] = kinds.get(e.kind, 0) + 1
        self.w("<h4>Elements by kind</h4>")
        self.table(["Kind", "Count"], [[_e(k), str(v)] for k, v in sorted(kinds.items())])

    def architecture_mermaid(self, root: Element) -> str:
        lines = ["flowchart LR"]
        ids: dict[int, str] = {}

        def nid(x: Element) -> str:
            if id(x) not in ids:
                ids[id(x)] = f"n{len(ids) + 1}"
            return ids[id(x)]

        lines.append(f'  subgraph {nid(root)}["{_label(root.name)}"]')
        lines.append("    direction LR")
        subs = components_of(root)
        for c in subs:
            d = definition_of(c)
            text = c.name or "?"
            if d is not None:
                text += f" : {d.name}"
            nested = len(components_of(c))
            if nested:
                text += f" ({nested} sub-components)"
            lines.append(f'    {nid(c)}["{_label(text)}"]')
        boundary = [p for p in ports_of(root)]
        for p in boundary:
            lines.append(f'    {nid(p)}(("{_label(p.name)}"))')
        lines.append("  end")
        for conn in connectors_of(root):
            ends = [x for x in conn.ends if x is not None]
            if len(ends) < 2:
                continue
            nodes = []
            for i in range(2):
                comp, port = _connection_end(conn, i)
                if port in boundary:
                    nodes.append(nid(port))
                else:
                    target = next((c for c in subs if comp is c or definition_of(c) is comp
                                   or port.owner is c or port.owner is definition_of(c)), None)
                    nodes.append(nid(target) if target is not None else None)
            if None in nodes:
                continue
            label = f"{ends[0].name} to {ends[1].name}"
            arrow = "-->" if ends[0].direction is FeatureDirection.OUT or \
                ends[1].direction is FeatureDirection.IN else "---"
            lines.append(f'  {nodes[0]} {arrow}|"{_label(label)}"| {nodes[1]}')
        return "\n".join(lines)

    def trace_mermaid(self, reqs: list[Element]) -> Optional[str]:
        rel = [l for l in self.links if l.source is not None and l.target is not None]
        if not reqs or not rel:
            return None
        ids: dict[int, str] = {}
        lines = ["flowchart LR"]

        def nid(x: Element) -> str:
            if id(x) not in ids:
                ids[id(x)] = f"t{len(ids) + 1}"
                rid = getattr(x, "req_id", None)
                text = f"{rid} {x.name}" if rid else (x.name or x.kind)
                shape = ('["', '"]') if isinstance(x, (RequirementDefinition, RequirementUsage)) \
                    else ('("', '")')
                lines.append(f"  {ids[id(x)]}{shape[0]}{_label(text)}{shape[1]}")
            return ids[id(x)]

        for l in rel[:200]:
            a, b = nid(l.source), nid(l.target)
            lines.append(f'  {a} -->|"{_label(link_kind_name(l))}"| {b}')
        return "\n".join(lines)

    def diagrams(self) -> None:
        roots = root_architectures(self.repo)
        if not roots:
            self.w('<p class="empty">No architecture with components.</p>')
        for r in roots:
            self.w(f"<h3>{_e(r.name)}</h3>")
            self.diagram(self.architecture_mermaid(r), f"Architecture of {r.name}")
        reqs = [e for e in self.elements if isinstance(e, (RequirementDefinition, RequirementUsage))]
        src = self.trace_mermaid(reqs)
        if src:
            self.w("<h3>Traceability</h3>")
            self.diagram(src, "Requirements and the elements linked to them")

    def hierarchy(self) -> None:
        roots = root_architectures(self.repo)
        if not roots:
            self.w('<p class="empty">No architecture with components.</p>')
            return
        for r in roots:
            stack_depth = -1
            self.w('<ul class="tree">')
            for comp, depth, _parent in component_tree(r):
                while stack_depth >= depth:
                    self.w("</ul></li>")
                    stack_depth -= 1
                d = definition_of(comp)
                stereo = _stereo_names(comp)
                self.w(f'<li><a href="#{self.anchor(comp)}">{_e(comp.name)}</a>'
                       f' <span class="kind">{_e(comp.kind)}'
                       f'{" : " + _e(d.name) if d is not None and d is not comp else ""}</span>'
                       f'{" <span class=stereo>«" + _e(stereo) + "»</span>" if stereo else ""}'
                       '<ul class="tree">')
                stack_depth = depth
            while stack_depth >= 0:
                self.w("</ul></li>")
                stack_depth -= 1
            self.w("</ul>")

    def component_section(self, comp: Element) -> None:
        stereo = _stereo_names(comp)
        self.w(f'<h3 id="{self.anchor(comp)}">{_e(comp.name)} '
               f'<span class="kind">{_e(comp.kind)}</span>'
               f'{" <span class=stereo>«" + _e(stereo) + "»</span>" if stereo else ""}</h3>')
        self.w(f'<div class="kind">{_e(relative_qname(comp, self.repo))}</div>')
        d = definition_of(comp)
        if d is not None and d is not comp:
            self.w(f"<p>Reference component of {self.ref(d)}"
                   f" [{_e(format_multiplicity(comp.multiplicity))}]</p>")
        doc = documentation(comp) or (documentation(d) if d is not None else "")
        if doc:
            self.w(f'<p class="doc">{_e(doc)}</p>')
        values = []
        for app in stereotypes_on(comp):
            for k, v in (app.values or {}).items():
                values.append([_e(stereotype_full_name(app.stereotype)), _e(k), _e(v)])
        if values:
            self.w("<h4>Stereotype properties</h4>")
            self.table(["Stereotype", "Property", "Value"], values)
        ports = ports_of(comp)
        self.w("<h4>Ports</h4>")
        self.table(["Port", "Direction", "Kind", "Interface", "Description"], [
            [_e(p.name), _e(p.direction.value if p.direction is not FeatureDirection.NONE else ""),
             _e(getattr(p, "port_kind", "") or ""),
             ", ".join(self.ref(t) for t in p.types), _e(documentation(p))]
            for p in ports], "No ports.")
        conns = connectors_of(comp)
        if conns:
            self.w("<h4>Connectors</h4>")
            rows = []
            for c in conns:
                cells = []
                for i in range(2):
                    owner, port = _connection_end(c, i)
                    cells.append(f"{_e(owner.name if owner is not None else '')}."
                                 f"{_e(port.name if port is not None else '?')}")
                rows.append([_e(c.name), cells[0], cells[1],
                             ", ".join(self.ref(t) for t in c.types)])
            self.table(["Connector", "Source", "Destination", "Type"], rows)

    def components(self) -> None:
        seen: set[int] = set()
        order: list[Element] = []
        for r in root_architectures(self.repo):
            for comp, _depth, _parent in component_tree(r):
                if id(comp) not in seen:
                    seen.add(id(comp))
                    order.append(comp)
        for e in self.elements:
            if isinstance(e, (PartDefinition, PartUsage)) and id(e) not in seen \
                    and not is_profile_content(e):
                seen.add(id(e))
                order.append(e)
        if not order:
            self.w('<p class="empty">No components.</p>')
        for comp in order:
            self.component_section(comp)

    def interfaces(self) -> None:
        ifaces = [e for e in self.elements if _is_interface(e) and not is_profile_content(e)]
        if not ifaces:
            self.w('<p class="empty">No interfaces.</p>')
        for i in ifaces:
            stereo = _stereo_names(i)
            self.w(f'<h3 id="{self.anchor(i)}">{_e(i.name)} <span class="kind">{_e(i.kind)}</span>'
                   f'{" <span class=stereo>«" + _e(stereo) + "»</span>" if stereo else ""}</h3>')
            doc = documentation(i)
            if doc:
                self.w(f'<p class="doc">{_e(doc)}</p>')
            rows = []
            for el in [c for c in i.owned_elements if isinstance(c, Feature)]:
                extras = extra_attributes(el)
                details = "; ".join(f"{k} = {v}" for k, v in sorted(extras.items())
                                    if not isinstance(v, (list, dict)))
                rows.append([_e(el.name), _e(_type_names(el, self.repo)),
                             _e(el.direction.value if el.direction is not FeatureDirection.NONE
                                else ""),
                             _e(format_multiplicity(el.multiplicity)), _e(details),
                             _e(documentation(el))])
            self.table(["Element", "Type", "Direction", "Multiplicity", "Details", "Description"],
                       rows, "No elements.")
            users = [p for p in self.elements if isinstance(p, PortUsage) and i in p.types]
            if users:
                self.w("<p>Used by ports: " + ", ".join(self.ref(p) for p in users) + "</p>")

    def requirements(self) -> None:
        reqs = [e for e in self.elements if isinstance(e, (RequirementDefinition, RequirementUsage))]
        if not reqs:
            self.w('<p class="empty">No requirements.</p>')
            return
        incoming: dict[int, list] = {}
        outgoing: dict[int, list] = {}
        for l in self.links:
            incoming.setdefault(id(l.target), []).append(l)
            outgoing.setdefault(id(l.source), []).append(l)
        rows = []
        satisfied = verified = 0
        for r in reqs:
            inc = incoming.get(id(r), [])
            out = outgoing.get(id(r), [])
            sat = [l.source for l in inc if link_kind_name(l) in ("satisfy", "implement")]
            ver = [l.source for l in inc if link_kind_name(l) == "verify"]
            other = [f"{_e(link_kind_name(l))} ← {self.ref(l.source)}" for l in inc
                     if l.source not in sat and l.source not in ver]
            other += [f"{_e(link_kind_name(l))} → {self.ref(l.target)}" for l in out]
            satisfied += bool(sat)
            verified += bool(ver)
            rows.append([f'<span id="{self.anchor(r)}">{_e(getattr(r, "req_id", "") or "")}</span>',
                         _e(r.name), _e(getattr(r, "text", "") or ""),
                         ", ".join(self.ref(x) for x in sat), ", ".join(self.ref(x) for x in ver),
                         "<br>".join(other)])
        n = len(reqs)
        self.w(f"<p>{satisfied} of {n} requirements are implemented "
               f"({round(100 * satisfied / n)}%), {verified} of {n} are verified "
               f"({round(100 * verified / n)}%).</p>")
        self.table(["ID", "Requirement", "Text", "Implemented by", "Verified by", "Other links"],
                   rows)

    def validation(self) -> None:
        chk = self.check or run_model_check(self.repo)
        c = chk["counts"]
        self.w(f"<p>{c['error']} error(s), {c['warning']} warning(s), {c['info']} info.</p>")
        rows = [[f'<span class="badge sev-{_e(i["severity"])}">{_e(i["severity"])}</span>',
                 _e(i["rule"]), _e(i["qualified_name"]), _e(i["message"])]
                for i in chk["issues"]]
        self.table(["Severity", "Rule", "Element", "Message"], rows, "No issues.")

    def links_appendix(self) -> None:
        self.table(["Kind", "Source", "Target"],
                   [[_e(link_kind_name(l)), self.ref(l.source), self.ref(l.target)]
                    for l in self.links], "No links.")

    # --- assembly ----------------------------------------------------------------------
    def mermaid_script(self) -> str:
        if self.mermaid == "none" or not self.diagram_count:
            return ""
        init = ("<script>(function(){var m=window.mermaid;var blocks=document.querySelectorAll"
                "('pre.mermaid');if(!m){blocks.forEach(function(b){b.className='mermaid-source';});"
                "return;}m.initialize({startOnLoad:false,theme:'neutral',securityLevel:'strict'});"
                "m.run({nodes:blocks,suppressErrors:true}).catch(function(){});})();</script>")
        if self.mermaid == "inline":
            files = sorted(_VENDOR.glob("mermaid-*.min.js"))
            if files:
                js = files[-1].read_text(encoding="utf-8").replace("</script", "<\\/script")
                return f"<script>{js}</script>{init}"
        return f'<script src="{_e(self.mermaid_src)}"></script>{init}'

    def render(self) -> str:
        self.title_page()
        builders = {"summary": self.summary, "diagrams": self.diagrams,
                    "hierarchy": self.hierarchy, "components": self.components,
                    "interfaces": self.interfaces, "requirements": self.requirements,
                    "validation": self.validation, "links": self.links_appendix}
        for s in self.sections:
            self.w(f'<section id="sec-{s}"><h2>{_e(SECTION_TITLES[s])}</h2>')
            builders[s]()
            self.w("</section>")
        body = "\n".join(self.out)
        return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>{_e(self.title)}</title><style>{_CSS}</style></head>"
                f"<body><main>\n{body}\n</main>{self.mermaid_script()}</body></html>\n")


def generate_report(repo, *, title: Optional[str] = None, author: str = "",
                    date: Optional[str] = None, sections: Optional[Iterable[str]] = None,
                    mermaid: str = "link", mermaid_src: str = DEFAULT_MERMAID_SRC) -> str:
    """The HTML report for `repo` (see the module docstring for the options)."""
    if mermaid not in ("link", "inline", "none"):
        raise ValueError("mermaid must be 'link', 'inline' or 'none'")
    chosen = list(sections) if sections else list(SECTIONS)
    unknown = [s for s in chosen if s not in SECTIONS]
    if unknown:
        raise ValueError(f"unknown report section(s) {unknown}; choose from {SECTIONS}")
    return _Report(repo, title=title, author=author, date=date, sections=chosen,
                   mermaid=mermaid, mermaid_src=mermaid_src).render()
