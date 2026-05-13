"""Tkinter Canvas-based diagram view.

Renders a Block Definition Diagram (BDD) or Requirements diagram of the
current project — no external dependencies. The layout is a simple
force-free grid layout: nodes are placed on concentric layers based on
their distance from the root, edges drawn as straight lines with arrowheads.

For users who have Graphviz installed, the same module exports DOT text
through the engine, which can be rendered to SVG/PNG out-of-process.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Iterable, Optional

from engine import bdd, requirements as req_dot, ibd as ibd_dot, state_machine as sm_dot
from kerml.elements import Element
from kerml.namespaces import Namespace
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import (
    ConnectionUsage, Definition, PartDefinition, PortUsage, RequirementDefinition,
    StateUsage, TransitionUsage, Usage,
)
from sysmlv2.state_machines import StateMachineDefinition, state_machines_of


NODE_W, NODE_H = 170, 80
H_GAP, V_GAP = 80, 60


def _node_label(e: Element) -> str:
    stereo = stereotypes_on(e)
    parts: list[str] = []
    if stereo:
        parts.append("«" + ", ".join(a.stereotype.name for a in stereo) + "»")
    parts.append(f"«{e.kind}»")
    parts.append(e.name or "?")
    return "\n".join(parts)


class DiagramView(ttk.Frame):
    """A Canvas pane with toolbar to choose diagram kind + export DOT."""

    def __init__(self, master, *, get_root: callable, log: callable):
        super().__init__(master)
        self._get_root = get_root
        self._log = log

        bar = ttk.Frame(self); bar.pack(side="top", fill="x")
        self._mode = tk.StringVar(value="BDD")
        for label in ("BDD", "IBD", "Requirements", "StateMachine"):
            ttk.Radiobutton(bar, text=label, value=label,
                            variable=self._mode, command=self.refresh
                            ).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Refresh",     command=self.refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Export DOT…", command=self._export_dot).pack(side="left", padx=2)

        self.canvas = tk.Canvas(self, background="white", scrollregion=(0, 0, 4000, 3000))
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        vsb = ttk.Scrollbar(self, orient="vertical",   command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="we")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._element_target: Optional[Element] = None  # for IBD

    # --- API ----------------------------------------------------------
    def set_target(self, element: Element) -> None:
        self._element_target = element
        if isinstance(element, StateMachineDefinition):
            self._mode.set("StateMachine")
        elif isinstance(element, PartDefinition):
            # If the part owns a state machine, default to that view.
            sms = state_machines_of(element)
            if sms:
                self._element_target = sms[0]
                self._mode.set("StateMachine")
            else:
                self._mode.set("IBD")
        self.refresh()

    def refresh(self) -> None:
        self.canvas.delete("all")
        root = self._get_root()
        if root is None:
            return
        mode = self._mode.get()
        if mode == "BDD":
            self._draw_bdd(root)
        elif mode == "IBD" and isinstance(self._element_target, PartDefinition):
            self._draw_ibd(self._element_target)
        elif mode == "IBD":
            self.canvas.create_text(20, 20, anchor="nw",
                                    text="Select a PartDefinition in the tree to render its IBD.",
                                    fill="#666")
        elif mode == "StateMachine":
            sm = self._element_target if isinstance(self._element_target, StateMachineDefinition) else None
            if sm is None and isinstance(self._element_target, PartDefinition):
                sms = state_machines_of(self._element_target)
                sm = sms[0] if sms else None
            if sm is None:
                self.canvas.create_text(20, 20, anchor="nw",
                                        text="Select a Part with a state machine, or a StateMachineDefinition.",
                                        fill="#666")
            else:
                self._draw_state_machine(sm)
        else:
            self._draw_requirements(root)

    # --- drawing primitives ------------------------------------------
    def _draw_node(self, x: int, y: int, label: str, *, kind: str) -> tuple[int, int]:
        fill = {
            "PartDefinition": "#e7f1ff",
            "ItemDefinition": "#eef7e6",
            "PortDefinition": "#fff2cc",
            "AttributeDefinition": "#fdf2f8",
            "RequirementDefinition": "#fffbe6",
            "ConnectionUsage": "#f3f3f3",
            "Stereotype": "#ede7f6",
        }.get(kind, "#f8f9fa")
        self.canvas.create_rectangle(x, y, x + NODE_W, y + NODE_H,
                                     fill=fill, outline="#444", width=1)
        self.canvas.create_text(x + NODE_W // 2, y + NODE_H // 2,
                                text=label, font=("Helvetica", 9),
                                width=NODE_W - 12, justify="center")
        return (x + NODE_W // 2, y + NODE_H // 2)

    def _arrow(self, src: tuple[int, int], tgt: tuple[int, int],
               label: str = "", *, dashed: bool = False,
               arrow: str = "last") -> None:
        opts = {"arrow": arrow, "fill": "#333"}
        if dashed:
            opts["dash"] = (4, 3)
        self.canvas.create_line(src[0], src[1], tgt[0], tgt[1], **opts)
        if label:
            mid = ((src[0] + tgt[0]) // 2, (src[1] + tgt[1]) // 2 - 8)
            self.canvas.create_text(*mid, text=label, font=("Helvetica", 8),
                                    fill="#555")

    # --- BDD ---------------------------------------------------------
    def _draw_bdd(self, root: Namespace) -> None:
        defs = [e for e in root.walk() if isinstance(e, Definition)]
        if not defs:
            self.canvas.create_text(20, 20, anchor="nw",
                                    text="No definitions in this scope.", fill="#666")
            return
        # Layered grid: 4 per row.
        coords: dict[str, tuple[int, int]] = {}
        for i, d in enumerate(defs):
            row, col = divmod(i, 4)
            x = 20 + col * (NODE_W + H_GAP)
            y = 20 + row * (NODE_H + V_GAP)
            coords[d.element_id] = self._draw_node(x, y, _node_label(d), kind=d.kind)
        # Edges
        for d in defs:
            for s in getattr(d, "specializations", []):
                if s.target and s.target.element_id in coords:
                    self._arrow(coords[d.element_id], coords[s.target.element_id],
                                label="«specializes»")
            if isinstance(d, PartDefinition):
                for u in d.owned_features:
                    if isinstance(u, ConnectionUsage):
                        continue
                    for t in getattr(u, "types", []):
                        if isinstance(t, Definition) and t.element_id in coords:
                            self._arrow(coords[d.element_id], coords[t.element_id],
                                        label=f"◆ {u.name or ''}", arrow="none")

    # --- IBD ---------------------------------------------------------
    def _draw_ibd(self, part: PartDefinition) -> None:
        # Inner usages laid out in a row; ports drawn on each box border.
        inner = [u for u in part.owned_features if not isinstance(u, ConnectionUsage)]
        coords: dict[str, tuple[int, int]] = {}
        for i, u in enumerate(inner):
            x = 40 + i * (NODE_W + H_GAP)
            y = 80
            coords[u.element_id] = self._draw_node(x, y, _node_label(u), kind=u.kind)
            # Ports on the right edge.
            ports = [s for s in u.owned_elements if isinstance(s, PortUsage)]
            for j, p in enumerate(ports):
                px = x + NODE_W
                py = y + 20 + j * 20
                self.canvas.create_rectangle(px - 6, py - 6, px + 6, py + 6,
                                             fill="#fff2cc", outline="#444")
                self.canvas.create_text(px + 10, py, text=p.name or "?", anchor="w",
                                        font=("Helvetica", 8))
                coords[p.element_id] = (px, py)
        self.canvas.create_text(20, 20, anchor="nw",
                                text=f"IBD: {part.qualified_name}",
                                font=("Helvetica", 11, "bold"))
        for c in part.owned_features:
            if not isinstance(c, ConnectionUsage) or len(c.ends) < 2:
                continue
            a_id, b_id = c.ends[0].element_id, c.ends[1].element_id
            if a_id in coords and b_id in coords:
                self._arrow(coords[a_id], coords[b_id], label=c.name or "", arrow="none")

    # --- Requirements ------------------------------------------------
    def _draw_requirements(self, root: Namespace) -> None:
        reqs = [e for e in root.walk() if isinstance(e, RequirementDefinition)]
        if not reqs:
            self.canvas.create_text(20, 20, anchor="nw",
                                    text="No requirements in this scope.", fill="#666")
            return
        coords: dict[str, tuple[int, int]] = {}
        for i, r in enumerate(reqs):
            row, col = divmod(i, 3)
            x = 20 + col * (NODE_W + H_GAP)
            y = 20 + row * (NODE_H + V_GAP)
            coords[r.element_id] = self._draw_node(x, y, _node_label(r), kind=r.kind)
        # Satisfy / verify edges from anywhere into requirements.
        from sysmlv2.relationships import Satisfy, Verify, Refine, Trace, DeriveRequirement
        for e in root.walk():
            for rel in getattr(e, "owned_relationships", []):
                pred = None
                if   isinstance(rel, Satisfy): pred = "satisfy"
                elif isinstance(rel, Verify):  pred = "verify"
                elif isinstance(rel, Refine):  pred = "refine"
                elif isinstance(rel, Trace):   pred = "trace"
                elif isinstance(rel, DeriveRequirement): pred = "derive"
                if pred is None or rel.target is None or rel.source is None:
                    continue
                tgt_id = rel.target.element_id
                src = rel.source
                if tgt_id not in coords:
                    continue
                if src.element_id not in coords:
                    # Drop a stub node for non-requirement sources.
                    x = 20 + (len(coords) % 3) * (NODE_W + H_GAP)
                    y = 20 + (len(coords) // 3) * (NODE_H + V_GAP)
                    coords[src.element_id] = self._draw_node(x, y, _node_label(src), kind=src.kind)
                self._arrow(coords[src.element_id], coords[tgt_id],
                            label=f"«{pred}»", dashed=True)

    # --- StateMachine -------------------------------------------------
    def _draw_state_machine(self, sm: StateMachineDefinition) -> None:
        self.canvas.create_text(20, 20, anchor="nw",
                                text=f"StateMachine: {sm.qualified_name}",
                                font=("Helvetica", 11, "bold"))
        coords: dict[str, tuple[int, int]] = {}
        states = sm.states
        for i, s in enumerate(states):
            row, col = divmod(i, 3)
            x = 30 + col * (NODE_W + H_GAP)
            y = 50 + row * (NODE_H + V_GAP)
            rows = [f"«state»", s.name or "?"]
            for kind, attr in (("entry", "entry_action"), ("do", "do_action"),
                               ("exit", "exit_action")):
                val = getattr(s, attr, None)
                if val:
                    rows.append(f"{kind}/ {val}")
            label = "\n".join(rows)
            fill = "#fef9e7"
            if s is sm.initial_state:
                fill = "#d6eaf8"
            if getattr(s, "is_final", False):
                fill = "#fadbd8"
            self.canvas.create_rectangle(x, y, x + NODE_W, y + NODE_H + 20,
                                         fill=fill, outline="#444", width=1)
            self.canvas.create_text(x + NODE_W // 2, y + (NODE_H + 20) // 2,
                                    text=label, font=("Helvetica", 9),
                                    width=NODE_W - 12, justify="center")
            coords[s.element_id] = (x + NODE_W // 2, y + (NODE_H + 20) // 2)
        # Initial marker.
        if sm.initial_state and sm.initial_state.element_id in coords:
            cx, cy = coords[sm.initial_state.element_id]
            self.canvas.create_oval(20, cy - 6, 32, cy + 6, fill="black")
            self.canvas.create_line(32, cy, cx - NODE_W // 2, cy, arrow="last", fill="#333")
        # Transitions.
        for t in sm.transitions:
            src, tgt = t.transition_source, t.transition_target
            if src is None or tgt is None: continue
            if src.element_id not in coords or tgt.element_id not in coords:
                continue
            bits = []
            if t.trigger_event: bits.append(t.trigger_event)
            if t.guard is not None:
                bits.append("[" + (t.guard if isinstance(t.guard, str) else "λ") + "]")
            if t.effect is not None:
                bits.append("/ " + (t.effect if isinstance(t.effect, str) else "λ"))
            self._arrow(coords[src.element_id], coords[tgt.element_id],
                        label=" ".join(bits))

    # --- Export ------------------------------------------------------
    def _export_dot(self) -> None:
        from tkinter import filedialog, messagebox
        root = self._get_root()
        if root is None:
            return
        mode = self._mode.get()
        try:
            if mode == "BDD":
                dot = bdd(root)
            elif mode == "IBD" and isinstance(self._element_target, PartDefinition):
                dot = ibd_dot(self._element_target)
            elif mode == "StateMachine":
                sm = self._element_target if isinstance(self._element_target, StateMachineDefinition) else (
                    state_machines_of(self._element_target)[0]
                    if isinstance(self._element_target, PartDefinition)
                    and state_machines_of(self._element_target) else None
                )
                if sm is None:
                    raise ValueError("Select a state machine first")
                dot = sm_dot(sm)
            else:
                dot = req_dot(root)
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Export failed", str(ex))
            return
        path = filedialog.asksaveasfilename(
            title="Export Graphviz DOT",
            defaultextension=".dot",
            filetypes=[("Graphviz DOT", "*.dot"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(dot)
        self._log(f"Exported {mode} diagram to {path}")
