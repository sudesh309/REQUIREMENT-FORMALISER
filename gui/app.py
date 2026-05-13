"""Cameo-style Tkinter GUI for the SysML v2 core engine.

Three panes:
  - left:   containment tree (Treeview rooted at the project Package)
  - right:  properties editor for the selected element
  - bottom: validation + output log

Toolbar provides one-click creation of every common SysML v2 element kind
(Package, PartDefinition / Usage, AttributeDefinition / Usage, PortDefinition /
Usage, ConnectionUsage, ActionDefinition / Usage, StateDefinition / Usage,
RequirementDefinition / Usage, ConstraintDefinition / Usage, EnumerationDefinition).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Optional

from engine import Repository, parse, to_json, from_json
from engine.graph_export import EXPORTERS, export_knowledge_graph
from engine.links import (
    LINK_KINDS, create_link, describe_link, link_kind, links_of, list_link_kinds,
)
from engine.validator import Severity, Validator
from kerml.elements import Documentation, Element
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Namespace, Package
from kerml.stereotypes import Stereotype, stereotypes_on
from kerml.types import Type
from sysmlv2 import (
    ActionDefinition, ActionUsage,
    AttributeDefinition, AttributeUsage,
    CalculationDefinition, CalculationUsage,
    ConnectionUsage,
    ConstraintDefinition, ConstraintUsage,
    EnumerationDefinition,
    InterfaceDefinition, InterfaceUsage,
    ParameterDefinition, ParameterUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage,
    StateDefinition, StateUsage,
)
from .diagram_view import DiagramView


# Order matters: shown left-to-right in toolbar.
ELEMENT_KINDS: list[tuple[str, type[Element]]] = [
    ("Package",       Package),
    ("Part Def",      PartDefinition),
    ("Part",          PartUsage),
    ("Attribute Def", AttributeDefinition),
    ("Attribute",     AttributeUsage),
    ("Port Def",      PortDefinition),
    ("Port",          PortUsage),
    ("Interface Def", InterfaceDefinition),
    ("Interface",     InterfaceUsage),
    ("Connection",    ConnectionUsage),
    ("Action Def",    ActionDefinition),
    ("Action",        ActionUsage),
    ("State Def",     StateDefinition),
    ("State",         StateUsage),
    ("Requirement Def", RequirementDefinition),
    ("Requirement",   RequirementUsage),
    ("Constraint Def", ConstraintDefinition),
    ("Constraint",    ConstraintUsage),
    ("Enum Def",      EnumerationDefinition),
    ("Stereotype",    Stereotype),
    ("Parameter",     ParameterUsage),
    ("Calc Def",      CalculationDefinition),
]


class SysMLApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SysML v2 Core Engine")
        self.geometry("1200x780")
        self.option_add("*tearOff", False)

        self.repo: Repository = Repository(name="UntitledProject")
        self.current_path: Optional[str] = None
        self.element_by_iid: dict[str, Element] = {}

        self._build_menu()
        self._build_toolbar()
        self._build_panes()
        self._refresh_tree()
        self._log(f"Started new project {self.repo.name!r}")

    # --- chrome --------------------------------------------------------
    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        self["menu"] = menu

        file_menu = tk.Menu(menu)
        menu.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New project",  command=self.cmd_new,        accelerator="Ctrl+N")
        file_menu.add_command(label="Open JSON…",   command=self.cmd_open_json,  accelerator="Ctrl+O")
        file_menu.add_command(label="Save JSON…",   command=self.cmd_save_json,  accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Import .sysml…", command=self.cmd_import_sysml)
        file_menu.add_command(label="Export .sysml.json…", command=self.cmd_save_json)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.destroy)

        edit_menu = tk.Menu(menu)
        menu.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Rename selected…", command=self.cmd_rename, accelerator="F2")
        edit_menu.add_command(label="Delete selected",  command=self.cmd_delete, accelerator="Del")

        model_menu = tk.Menu(menu)
        menu.add_cascade(label="Model", menu=model_menu)
        model_menu.add_command(label="Validate", command=self.cmd_validate, accelerator="F5")
        model_menu.add_command(label="Expand all", command=lambda: self._expand_all(True))
        model_menu.add_command(label="Collapse all", command=lambda: self._expand_all(False))

        link_menu = tk.Menu(menu)
        menu.add_cascade(label="Links", menu=link_menu)
        link_menu.add_command(label="Create link…", command=self.cmd_create_link,
                              accelerator="Ctrl+L")
        link_menu.add_command(label="Show links on selection",
                              command=self.cmd_show_links)
        link_menu.add_command(label="List all link kinds", command=self.cmd_list_link_kinds)
        link_menu.add_separator()
        link_menu.add_command(label="Add parameter to selection…",
                              command=self.cmd_add_parameter)
        link_menu.add_command(label="New requirement…",
                              command=self.cmd_new_requirement)

        self.bind_all("<Control-l>", lambda _e: self.cmd_create_link())

        stereo_menu = tk.Menu(menu)
        menu.add_cascade(label="Stereotypes", menu=stereo_menu)
        stereo_menu.add_command(label="Define stereotype…", command=self.cmd_define_stereotype)
        stereo_menu.add_command(label="Apply to selection…", command=self.cmd_apply_stereotype)
        stereo_menu.add_command(label="Define tag on stereotype…", command=self.cmd_add_stereotype_tag)

        export_menu = tk.Menu(menu)
        menu.add_cascade(label="Export", menu=export_menu)
        for fmt in ("turtle", "json-ld", "graphml", "cypher"):
            export_menu.add_command(
                label=f"Knowledge graph: {fmt}…",
                command=lambda f=fmt: self.cmd_export_graph(f),
            )

        self.bind_all("<Control-n>", lambda _e: self.cmd_new())
        self.bind_all("<Control-o>", lambda _e: self.cmd_open_json())
        self.bind_all("<Control-s>", lambda _e: self.cmd_save_json())
        self.bind_all("<F5>",       lambda _e: self.cmd_validate())
        self.bind_all("<F2>",       lambda _e: self.cmd_rename())
        self.bind_all("<Delete>",   lambda _e: self.cmd_delete())

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(4, 4))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="New",      command=self.cmd_new).pack(side="left", padx=2)
        ttk.Button(bar, text="Open",     command=self.cmd_open_json).pack(side="left", padx=2)
        ttk.Button(bar, text="Save",     command=self.cmd_save_json).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Validate", command=self.cmd_validate).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        add_lbl = ttk.Label(bar, text="Add:")
        add_lbl.pack(side="left", padx=(8, 4))
        for label, cls in ELEMENT_KINDS:
            ttk.Button(bar, text=label, width=12,
                       command=lambda c=cls, n=label: self.cmd_add_element(c, n)
                       ).pack(side="left", padx=1)

    def _build_panes(self) -> None:
        outer = ttk.PanedWindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True)

        # --- left: containment tree ---
        tree_frame = ttk.Frame(outer)
        outer.add(tree_frame, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("kind",), show="tree headings")
        self.tree.heading("#0",   text="Element")
        self.tree.heading("kind", text="Kind")
        self.tree.column("kind", width=160, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Button-3>", self._on_tree_context)

        # --- right: notebook (props + diagram) + log ---
        right = ttk.PanedWindow(outer, orient="vertical")
        outer.add(right, weight=3)

        nb = ttk.Notebook(right)
        right.add(nb, weight=4)

        self.props = PropertiesPane(nb, on_apply=self._on_props_apply)
        nb.add(self.props, text="Properties")

        self.diagram = DiagramView(nb, get_root=lambda: self.repo.root_package,
                                   log=self._log)
        nb.add(self.diagram, text="Diagram")
        self._notebook = nb

        log_frame = ttk.LabelFrame(right, text="Output / Validation")
        right.add(log_frame, weight=1)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=log_sb.set)

        # Status bar
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken"
                  ).pack(side="bottom", fill="x")

    # --- tree population ----------------------------------------------
    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.element_by_iid.clear()
        self._insert_node("", self.repo.root_package)

    def _insert_node(self, parent_iid: str, e: Element) -> str:
        iid = e.element_id
        text = e.name or f"<{e.kind}>"
        self.tree.insert(parent_iid, "end", iid=iid, text=text, values=(e.kind,), open=True)
        self.element_by_iid[iid] = e
        for child in e.owned_elements:
            self._insert_node(iid, child)
        return iid

    def _selected(self) -> Optional[Element]:
        sel = self.tree.selection()
        return self.element_by_iid.get(sel[0]) if sel else None

    def _select_in_tree(self, e: Element) -> None:
        self.tree.see(e.element_id)
        self.tree.selection_set(e.element_id)

    def _on_select(self) -> None:
        e = self._selected()
        if e is not None:
            self.props.show(e)
            self.diagram.set_target(e)
            self.status.set(f"{e.kind}  {e.qualified_name}")

    def _on_tree_context(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Rename", command=self.cmd_rename)
        menu.add_command(label="Delete", command=self.cmd_delete)
        menu.add_separator()
        for label, cls in ELEMENT_KINDS:
            menu.add_command(label=f"Add {label}",
                             command=lambda c=cls, n=label: self.cmd_add_element(c, n))
        menu.tk_popup(event.x_root, event.y_root)

    def _expand_all(self, expand: bool) -> None:
        for iid in self.element_by_iid:
            self.tree.item(iid, open=expand)

    # --- properties apply ---------------------------------------------
    def _on_props_apply(self, e: Element, fields: dict) -> None:
        e.name = fields.get("name") or e.name
        e.short_name = fields.get("short_name") or None
        if hasattr(e, "is_abstract"):
            e.is_abstract = bool(fields.get("is_abstract"))
        if isinstance(e, Feature):
            lo = int(fields.get("mult_lower") or 0)
            up_raw = (fields.get("mult_upper") or "").strip()
            up = None if up_raw in ("*", "") else int(up_raw)
            e.multiplicity = MultiplicityRange(lo, up)
            tname = (fields.get("typed_by") or "").strip()
            if tname:
                hit = self.repo.resolve(tname)
                if isinstance(hit, Type):
                    e.feature_typings = []
                    e.add_type(hit)
                else:
                    self._log(f"Cannot resolve type {tname!r}")
        for attr in ("req_id", "text"):
            if attr in fields and hasattr(e, attr):
                setattr(e, attr, fields[attr] or None)
        # Documentation: replace first Documentation annotation if present.
        doc = fields.get("doc")
        if doc is not None:
            for a in list(e.annotations):
                if isinstance(a, Documentation):
                    e.annotations.remove(a)
            if doc.strip():
                e.add_annotation(Documentation(body=doc.strip()))
        # Refresh tree label.
        self.tree.item(e.element_id, text=e.name or f"<{e.kind}>")
        self.status.set(f"Updated {e.qualified_name}")

    # --- commands ------------------------------------------------------
    def cmd_new(self) -> None:
        if not self._confirm_discard():
            return
        name = simpledialog.askstring("New project", "Project name:", initialvalue="UntitledProject")
        if not name:
            return
        self.repo = Repository(name=name)
        self.current_path = None
        self._refresh_tree()
        self._log(f"New project {name!r}")

    def cmd_open_json(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open project",
            filetypes=[("SysML v2 JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.repo = from_json(f.read())
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Open failed", str(ex))
            return
        self.current_path = path
        self._refresh_tree()
        self._log(f"Opened {path}")

    def cmd_save_json(self) -> None:
        path = self.current_path or filedialog.asksaveasfilename(
            title="Save project as JSON",
            defaultextension=".json",
            filetypes=[("SysML v2 JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_json(self.repo))
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Save failed", str(ex))
            return
        self.current_path = path
        self._log(f"Saved {path}")

    def cmd_import_sysml(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Import .sysml",
            filetypes=[("SysML v2 source", "*.sysml *.kerml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.repo = Repository(name="Imported")
            parse(src, into=self.repo.root_package)
            self.repo.registry.register_tree(self.repo.root_package)
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Import failed", str(ex))
            return
        self._refresh_tree()
        self._log(f"Imported {path}")

    def cmd_add_element(self, cls: type[Element], label: str) -> None:
        parent = self._selected() or self.repo.root_package
        # If selected isn't a Namespace, fall back to its owning namespace.
        if not isinstance(parent, Namespace):
            n = parent.owner
            while n is not None and not isinstance(n, Namespace):
                n = n.owner
            parent = n or self.repo.root_package
        name = simpledialog.askstring(f"Add {label}", "Name:", initialvalue=label.replace(" ", ""))
        if not name:
            return
        try:
            elem = cls(name=name)  # type: ignore[call-arg]
        except TypeError:
            elem = cls()  # type: ignore[call-arg]
            elem.name = name
        parent.own(elem)
        self.repo.registry.register_tree(elem)
        self._insert_node(parent.element_id, elem)
        self._select_in_tree(elem)
        self._log(f"Added {label} {name!r} into {parent.qualified_name}")

    def cmd_rename(self) -> None:
        e = self._selected()
        if e is None:
            return
        new_name = simpledialog.askstring("Rename", "New name:", initialvalue=e.name or "")
        if not new_name:
            return
        e.name = new_name
        self.tree.item(e.element_id, text=new_name)
        self.props.show(e)

    def cmd_delete(self) -> None:
        e = self._selected()
        if e is None or e is self.repo.root_package:
            return
        if not messagebox.askyesno("Delete", f"Delete {e.qualified_name!r} and all its descendants?"):
            return
        self.repo.remove(e)
        self.tree.delete(e.element_id)
        self.element_by_iid.pop(e.element_id, None)
        self._log(f"Deleted {e.qualified_name}")

    # --- link & requirement commands ----------------------------------
    def cmd_create_link(self) -> None:
        src = self._selected()
        if src is None:
            messagebox.showerror("Create link", "Select the link source in the tree first.")
            return
        LinkDialog(self, source=src, repo=self.repo, on_create=self._on_link_created)

    def _on_link_created(self, rel) -> None:
        SESSION = None  # placeholder for readability
        self.repo.registry.register(rel)
        info = describe_link(rel)
        self._log(f"Link «{info['kind']}»: {info['source']} → {info['target']}")
        self.diagram.refresh()

    def cmd_show_links(self) -> None:
        e = self._selected()
        if e is None:
            return
        self._log(f"--- Links on {e.qualified_name} ---")
        for r in links_of(e, direction="both"):
            d = describe_link(r)
            arrow = "→" if r.source is e else "←"
            other = d["target"] if r.source is e else d["source"]
            self._log(f"  «{d['kind']}» {arrow} {other}")

    def cmd_list_link_kinds(self) -> None:
        self._log("--- Link kinds ---")
        for lk in LINK_KINDS:
            self._log(f"  {lk.name:20s} — {lk.description}")

    def cmd_add_parameter(self) -> None:
        owner = self._selected()
        if owner is None:
            messagebox.showerror("Add parameter", "Select a behavior-like element in the tree.")
            return
        name = simpledialog.askstring("Add parameter", "Parameter name:")
        if not name:
            return
        kind = simpledialog.askstring(
            "Add parameter",
            "Parameter direction (in / out / inout / return):",
            initialvalue="in",
        ) or "in"
        if kind not in {"in", "out", "inout", "return"}:
            messagebox.showerror("Add parameter", f"Invalid direction {kind!r}")
            return
        p = ParameterUsage(name=name, parameter_kind=kind)
        owner.own(p)
        self.repo.registry.register_tree(p)
        self._insert_node(owner.element_id, p)
        self._select_in_tree(p)
        self._log(f"Added {kind} parameter {name!r} to {owner.qualified_name}")

    def cmd_new_requirement(self) -> None:
        RequirementDialog(self, repo=self.repo, on_create=self._on_requirement_created)

    def _on_requirement_created(self, req) -> None:
        self.repo.registry.register_tree(req)
        self._refresh_tree()
        self._select_in_tree(req)
        self._log(f"Created requirement {req.qualified_name} "
                  f"(id={req.req_id!r})")

    # --- stereotype commands ------------------------------------------
    def cmd_define_stereotype(self) -> None:
        name = simpledialog.askstring("Define stereotype", "Stereotype name:")
        if not name:
            return
        s = Stereotype(name=name)
        self.repo.root_package.own(s)
        self.repo.registry.register_tree(s)
        self._insert_node(self.repo.root_package.element_id, s)
        self._log(f"Defined stereotype «{name}»")

    def cmd_add_stereotype_tag(self) -> None:
        e = self._selected()
        if not isinstance(e, Stereotype):
            messagebox.showerror("Add tag", "Select a Stereotype in the tree first.")
            return
        name = simpledialog.askstring("Add tag", "Tag name:")
        if not name:
            return
        default = simpledialog.askstring("Add tag", f"Default value for {name!r} (optional):") or None
        e.define_tag(name, default=default)
        self.repo.registry.register_tree(e)
        self._refresh_tree()
        self._select_in_tree(e)
        self._log(f"Added tag {name!r} to stereotype «{e.name}»")

    def cmd_apply_stereotype(self) -> None:
        target = self._selected()
        if target is None:
            messagebox.showerror("Apply stereotype", "Select a target element in the tree.")
            return
        stereos = [e for e in self.repo.all_elements() if isinstance(e, Stereotype)]
        if not stereos:
            messagebox.showerror("Apply stereotype",
                                 "No stereotypes defined. Use Stereotypes › Define first.")
            return
        names = [s.qualified_name for s in stereos]
        choice = simpledialog.askstring(
            "Apply stereotype",
            "Stereotype qualified name:\n  " + "\n  ".join(names),
            initialvalue=names[0],
        )
        if not choice:
            return
        sel = next((s for s in stereos if s.qualified_name == choice or s.name == choice), None)
        if sel is None:
            messagebox.showerror("Apply stereotype", f"No stereotype {choice!r}")
            return
        values: dict = {}
        for tag in sel.all_tags():
            v = simpledialog.askstring("Apply stereotype",
                                       f"Value for tag {tag.name!r}:",
                                       initialvalue=str(tag.default_value or ""))
            if v is not None:
                values[tag.name] = v
        try:
            sel.apply(target, values)
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Apply stereotype", str(ex))
            return
        self._log(f"Applied «{sel.name}» to {target.qualified_name} {values}")
        self.props.show(target)
        self.diagram.refresh()

    def cmd_export_graph(self, fmt: str) -> None:
        ext = {"turtle": ".ttl", "json-ld": ".jsonld",
               "graphml": ".graphml", "cypher": ".cypher"}.get(fmt, ".txt")
        path = filedialog.asksaveasfilename(
            title=f"Export as {fmt}",
            defaultextension=ext,
            filetypes=[(fmt, f"*{ext}"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text = export_knowledge_graph(self.repo.root_package, fmt)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Export failed", str(ex))
            return
        self._log(f"Exported knowledge graph ({fmt}) to {path}")

    def cmd_validate(self) -> None:
        issues = Validator().validate(self.repo)
        self._log("--- Validation ---")
        if not issues:
            self._log("No issues found.")
            self.status.set("Validation: clean")
            return
        for i in issues:
            self._log(str(i))
        errs = sum(1 for i in issues if i.severity is Severity.ERROR)
        warns = sum(1 for i in issues if i.severity is Severity.WARNING)
        self.status.set(f"Validation: {errs} error(s), {warns} warning(s)")

    # --- helpers -------------------------------------------------------
    def _confirm_discard(self) -> bool:
        # Without a dirty flag we just confirm unconditionally.
        return messagebox.askyesno("Discard current?",
                                   "Discard current project and continue?")

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


# ----------------------------------------------------------------------
class PropertiesPane(ttk.LabelFrame):
    """A simple form rendering and editing the selected element's fields."""

    def __init__(self, master, *, on_apply: Callable[[Element, dict], None]):
        super().__init__(master, text="Properties")
        self._on_apply = on_apply
        self._element: Optional[Element] = None
        self._vars: dict[str, tk.Variable] = {}
        self._doc_widget: Optional[tk.Text] = None
        self._form = ttk.Frame(self)
        self._form.pack(fill="both", expand=True, padx=8, pady=8)
        self._placeholder = ttk.Label(self._form,
                                      text="Select an element in the tree to edit its properties.",
                                      foreground="#666")
        self._placeholder.pack(pady=20)

    def _clear(self) -> None:
        for w in self._form.winfo_children():
            w.destroy()
        self._vars.clear()
        self._doc_widget = None

    def _row(self, parent: tk.Widget, label: str, var: tk.Variable, row: int,
             *, key: str, width: int = 50, readonly: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=2)
        e = ttk.Entry(parent, textvariable=var, width=width,
                      state=("readonly" if readonly else "normal"))
        e.grid(row=row, column=1, sticky="we", padx=4, pady=2)
        self._vars[key] = var

    def show(self, element: Element) -> None:
        self._clear()
        self._element = element

        ttk.Label(self._form, text=f"{element.kind}", font=("TkDefaultFont", 11, "bold")
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self._form.columnconfigure(1, weight=1)

        self._row(self._form, "ID:", tk.StringVar(value=element.element_id), 1,
                  key="id", readonly=True, width=40)
        self._row(self._form, "Qualified name:",
                  tk.StringVar(value=element.qualified_name), 2,
                  key="qname", readonly=True)
        self._row(self._form, "Name:", tk.StringVar(value=element.name or ""), 3, key="name")
        self._row(self._form, "Short name:",
                  tk.StringVar(value=element.short_name or ""), 4, key="short_name")

        row = 5
        if hasattr(element, "is_abstract"):
            v = tk.BooleanVar(value=bool(element.is_abstract))
            ttk.Checkbutton(self._form, text="abstract", variable=v).grid(
                row=row, column=1, sticky="w", padx=4)
            self._vars["is_abstract"] = v
            row += 1

        if isinstance(element, Feature):
            ttk.Separator(self._form, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="we", pady=6); row += 1
            self._row(self._form, "Lower mult:",
                      tk.StringVar(value=str(element.multiplicity.lower)), row,
                      key="mult_lower", width=10); row += 1
            up_default = "*" if element.multiplicity.upper is None else str(element.multiplicity.upper)
            self._row(self._form, "Upper mult:",
                      tk.StringVar(value=up_default), row,
                      key="mult_upper", width=10); row += 1
            type_qn = ", ".join(t.qualified_name for t in element.types) if element.types else ""
            self._row(self._form, "Typed by (qname):",
                      tk.StringVar(value=type_qn), row, key="typed_by"); row += 1

        for attr in ("req_id", "text"):
            if hasattr(element, attr):
                self._row(self._form, attr.replace("_", " ").title() + ":",
                          tk.StringVar(value=getattr(element, attr) or ""), row,
                          key=attr); row += 1

        # Documentation.
        ttk.Label(self._form, text="Documentation:").grid(
            row=row, column=0, sticky="nw", padx=4, pady=(8, 2))
        doc = next((a.body for a in element.annotations if isinstance(a, Documentation)), "")
        self._doc_widget = tk.Text(self._form, height=6, wrap="word")
        self._doc_widget.insert("1.0", doc)
        self._doc_widget.grid(row=row, column=1, sticky="nsew", padx=4, pady=(8, 2))
        self._form.rowconfigure(row, weight=1)
        row += 1

        ttk.Button(self._form, text="Apply changes", command=self._apply
                   ).grid(row=row, column=1, sticky="e", padx=4, pady=8)

    def _apply(self) -> None:
        if self._element is None:
            return
        fields: dict = {k: v.get() for k, v in self._vars.items()}
        if self._doc_widget is not None:
            fields["doc"] = self._doc_widget.get("1.0", "end").rstrip("\n")
        self._on_apply(self._element, fields)


class LinkDialog(tk.Toplevel):
    """Dialog for picking a target element and a link kind."""

    def __init__(self, master, *, source, repo, on_create):
        super().__init__(master)
        self.title("Create link")
        self.geometry("520x340")
        self._source = source
        self._repo = repo
        self._on_create = on_create

        ttk.Label(self, text=f"Source: {source.qualified_name}",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))

        ttk.Label(self, text="Link kind:").pack(anchor="w", padx=10)
        self._kind = tk.StringVar(value=list_link_kinds()[0])
        cb = ttk.Combobox(self, textvariable=self._kind, values=list_link_kinds(),
                          state="readonly", width=30)
        cb.pack(anchor="w", padx=10, pady=2)

        self._desc = tk.StringVar()
        ttk.Label(self, textvariable=self._desc, foreground="#555", wraplength=480
                  ).pack(anchor="w", padx=10, pady=(0, 8))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_desc())
        self._refresh_desc()

        ttk.Label(self, text="Target element (qualified name or UUID):"
                  ).pack(anchor="w", padx=10)
        self._target_var = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self._target_var, width=60)
        entry.pack(anchor="w", padx=10, pady=2)

        ttk.Label(self, text="Existing elements (double-click to fill):",
                  foreground="#444").pack(anchor="w", padx=10, pady=(8, 2))
        self._listbox = tk.Listbox(self, height=8)
        self._listbox.pack(fill="both", expand=True, padx=10, pady=2)
        for e in repo.all_elements():
            if e.name and e is not source:
                self._listbox.insert("end", e.qualified_name)
        self._listbox.bind("<Double-Button-1>", self._pick)

        btns = ttk.Frame(self); btns.pack(fill="x", pady=8, padx=10)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Create", command=self._create).pack(side="right", padx=4)

    def _refresh_desc(self) -> None:
        lk = link_kind(self._kind.get())
        self._desc.set(lk.description if lk else "")

    def _pick(self, _event) -> None:
        sel = self._listbox.curselection()
        if sel:
            self._target_var.set(self._listbox.get(sel[0]))

    def _create(self) -> None:
        tgt_ref = self._target_var.get().strip()
        if not tgt_ref:
            messagebox.showerror("Create link", "Enter a target.", parent=self)
            return
        tgt = self._repo.by_id(tgt_ref) or self._repo.resolve(tgt_ref)
        if tgt is None:
            messagebox.showerror("Create link", f"Target {tgt_ref!r} not found.", parent=self)
            return
        try:
            rel = create_link(self._kind.get(), self._source, tgt)
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Create link", str(ex), parent=self)
            return
        self._on_create(rel)
        self.destroy()


class RequirementDialog(tk.Toplevel):
    """Dialog for creating a fully-specified Requirement."""

    def __init__(self, master, *, repo, on_create):
        super().__init__(master)
        self.title("New requirement")
        self.geometry("520x420")
        self._repo = repo
        self._on_create = on_create

        form = ttk.Frame(self); form.pack(fill="both", expand=True, padx=10, pady=10)
        form.columnconfigure(1, weight=1)

        self._name = tk.StringVar()
        self._req_id = tk.StringVar()
        self._subject = tk.StringVar()
        self._stakeholders = tk.StringVar()
        self._actors = tk.StringVar()

        rows = [
            ("Name:",         self._name),
            ("Requirement id:", self._req_id),
            ("Subject (qname):", self._subject),
            ("Stakeholders (comma qnames):", self._stakeholders),
            ("Actors (comma qnames):",       self._actors),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=4)
            ttk.Entry(form, textvariable=var).grid(row=i, column=1, sticky="we", padx=4, pady=4)

        ttk.Label(form, text="Text:").grid(row=len(rows), column=0, sticky="nw", padx=4, pady=4)
        self._text = tk.Text(form, height=8, wrap="word")
        self._text.grid(row=len(rows), column=1, sticky="nsew", padx=4, pady=4)
        form.rowconfigure(len(rows), weight=1)

        btns = ttk.Frame(self); btns.pack(fill="x", pady=8, padx=10)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Create", command=self._create).pack(side="right", padx=4)

    def _create(self) -> None:
        name = self._name.get().strip()
        if not name:
            messagebox.showerror("New requirement", "Name is required.", parent=self)
            return
        r = RequirementDefinition(name=name)
        r.req_id = self._req_id.get().strip() or None
        r.text = self._text.get("1.0", "end").strip() or None
        self._repo.root_package.own(r)
        subj_qn = self._subject.get().strip()
        if subj_qn:
            s = self._repo.by_id(subj_qn) or self._repo.resolve(subj_qn)
            if s is not None:
                rel = create_link("subject", r, s)
                self._repo.registry.register(rel)
                r.subject = s
        for ref in [x.strip() for x in self._stakeholders.get().split(",") if x.strip()]:
            s = self._repo.by_id(ref) or self._repo.resolve(ref)
            if s is not None:
                rel = create_link("stakeholder", r, s)
                self._repo.registry.register(rel)
                r.stakeholders.append(s)
        for ref in [x.strip() for x in self._actors.get().split(",") if x.strip()]:
            a = self._repo.by_id(ref) or self._repo.resolve(ref)
            if a is not None:
                rel = create_link("actor", r, a)
                self._repo.registry.register(rel)
                r.actors.append(a)
        self._on_create(r)
        self.destroy()


def main() -> None:
    SysMLApp().mainloop()


if __name__ == "__main__":
    main()
