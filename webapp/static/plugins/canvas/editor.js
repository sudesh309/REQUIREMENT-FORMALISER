// Interactive System Composer-style architecture canvas (pure SVG, no libraries).
//
// Shows one composition (an architecture or a component's inside) from
// GET /api/arch/view/<id>: the frame with its boundary ports, component blocks with
// ports, and orthogonal connectors. Every edit goes through /api/arch/* (so it is
// validated and undoable) and the canvas re-renders on the studio's model-changed.
//
// Cross-feature contracts (docs/EXTENDING.md): listens to navigate, highlight,
// canvas-filter, selection-changed, select and model-changed; publishes its selection
// with studio.setSelection / studio.selectElement; emits drop-on-element for HTML5
// drops of application/x-sysml-element onto a block, port or connector (holding such a
// drag over the Architecture tab opens the canvas).
import * as G from "./geometry.js";
import { Markers, blockSvg, connectorColor, connectorLabelSvg, connectorSvg, frameSvg, labelText, portSvg, staticDefs } from "./render.js";
import { icon, toolstripHtml, updateToolstrip } from "./toolstrip.js";
import { createInlineEditor, createMenu, createToasts } from "./ui.js";
import { createDock } from "./dock.js";
import { injectCanvasStyles } from "./styles.js";
import { clipboard, copyComponents, esc, openForm, reload } from "./common.js";

const SVGNS = "http://www.w3.org/2000/svg";
const STORE = "sysml.archCanvas";
const DRAG_START = 4;
const ELEMENT_MIME = "application/x-sysml-element";
const SPRING_OPEN_MS = 300;
const EDGE_ZONE = 28;
const SIDES = ["left", "right", "top", "bottom"];
const FOLLOW_KINDS = new Set(["PartUsage", "PortUsage", "ConnectionUsage", "PartDefinition"]);

const ck = id => `c:${id}`;
const kk = id => `k:${id}`;
const pk = (ctx, id) => `p:${ctx || ""}:${id}`;
function parseKey(key) {
  const [t, a, b] = String(key).split(":");
  if (t === "p") return { type: "port", ctx: a || null, id: b };
  return { type: t === "c" ? "component" : "connector", id: a };
}

const store = {
  get() { try { return JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch { return {}; } },
  set(patch) { try { localStorage.setItem(STORE, JSON.stringify({ ...store.get(), ...patch })); } catch { /* storage off */ } },
};

export function installCanvas(studio, { undo }) {
  injectCanvasStyles();
  let editor = null;
  studio.registerTab({
    id: "architecture", title: "Architecture", order: -10,
    mount(pane) { editor = new CanvasEditor(studio, pane, undo); },
    onShow() { editor?.shown(); },
  });
  return editor;
}

class CanvasEditor {
  constructor(studio, pane, undo) {
    this.studio = studio;
    this.undoApi = undo;
    this.compId = null;
    this.path = [];
    this.view = null;
    this.scene = null;
    this.dom = new Map();
    this.vp = { zoom: 1, panX: 0, panY: 0 };
    this.viewports = new Map();
    this.needFit = false;
    this.sel = new Set();
    this.primary = null;
    this.mode = "select";
    this.hl = null;
    this.filter = null;
    this.connect = null;
    this.drag = null;
    this.pending = null;
    this.space = false;
    this.spaceUsed = false;
    this.frameLock = null;
    this.over = { boxes: new Map(), ports: new Map(), points: new Map() };
    this.undoState = {};
    this.seq = 0;
    this.refreshing = Promise.resolve();
    this.visible = false;
    this.dockOpen = store.get().dock !== false;
    this.nudgeTimer = 0;
    this.build(pane);
    this.bind();
  }

  // ------------------------------------------------------------------ DOM
  build(pane) {
    pane.classList.add("arch-pane");
    pane.innerHTML = `${toolstripHtml()}
      <div class="arch-bar">
        <nav class="arch-path" aria-label="Breadcrumbs"></nav>
        <div class="arch-banners"></div>
        <span class="arch-spacer"></span>
        <label class="arch-open">Open <select class="input" data-canvas="open" aria-label="Open an architecture or definition"></select></label>
      </div>
      <div class="arch-main">
        <div class="arch-host" tabindex="0" role="application" aria-label="Architecture canvas">
          <svg class="arch-svg" xmlns="${SVGNS}">
            <defs>${staticDefs()}</defs><defs class="arch-markers"></defs>
            <rect class="arch-bgrect" width="100%" height="100%" fill="url(#arch-grid)"/>
            <g class="arch-vp">
              <g class="arch-l-frame"></g><g class="arch-l-conns"></g><g class="arch-l-blocks"></g>
              <g class="arch-l-labels"></g><g class="arch-l-bports"></g><g class="arch-l-over"><g class="arch-o-handles"></g><g class="arch-o-temp"></g></g>
            </g>
          </svg>
          <div class="arch-empty" hidden><div class="arch-empty-card">
            <div class="arch-empty-title">No architecture yet</div>
            <p>Create an architecture, then add components, ports and connectors right here on the canvas.</p>
            <button type="button" class="btn-primary" data-canvas-act="new-architecture">New architecture</button>
          </div></div>
          <div class="arch-status" aria-live="polite"></div>
        </div>
        <aside class="arch-dock" aria-label="Property Inspector"></aside>
      </div>`;
    this.pane = pane;
    const $ = s => pane.querySelector(s);
    this.strip = $(".arch-toolstrip");
    this.crumbs = $(".arch-path");
    this.banners = $(".arch-banners");
    this.openSel = $('[data-canvas="open"]');
    this.host = $(".arch-host");
    this.svg = $(".arch-svg");
    this.vpG = $(".arch-vp");
    this.L = { frame: $(".arch-l-frame"), conns: $(".arch-l-conns"), blocks: $(".arch-l-blocks"),
               labels: $(".arch-l-labels"), bports: $(".arch-l-bports"), handles: $(".arch-o-handles"), temp: $(".arch-o-temp") };
    this.markerDefs = $(".arch-markers");
    this.grid = $("#arch-grid");
    this.empty = $(".arch-empty");
    this.statusEl = $(".arch-status");
    this.dockEl = $(".arch-dock");
    this.toast = createToasts(this.host);
    this.menu = createMenu(this.host, (cmd, ctx) => this.command(cmd, ctx));
    this.inline = createInlineEditor(this.host);
    this.dock = createDock(this.dockEl, this.studio, this.dockActions());
  }

  bind() {
    const s = this.studio;
    this.pane.addEventListener("click", (e) => {
      const b = e.target.closest("[data-canvas-act]");
      if (b && !b.disabled) {
        // Keyboard shortcuts keep working after a toolstrip click; a modal or the inline
        // editor opened by the command takes the focus afterwards.
        this.host.focus({ preventScroll: true });
        this.command(b.dataset.canvasAct);
        return;
      }
      const c = e.target.closest("[data-crumb]");
      if (c) { const i = Number(c.dataset.crumb); this.open(this.path[i], this.path.slice(0, i + 1)); return; }
      if (e.target.closest("[data-crumb-up]")) { this.up(); return; }
      const bc = e.target.closest("[data-banner-clear]");
      if (bc) {
        if (bc.dataset.bannerClear === "filter") s.emit("canvas-filter", null);
        else s.emit("highlight", null);
      }
    });
    this.pane.addEventListener("change", (e) => {
      if (e.target === this.openSel && e.target.value) this.open(e.target.value, [e.target.value]);
      if (e.target.matches("[data-banner-hide]") && this.filter) {
        this.filter.hide = e.target.checked;
        this.render();
      }
    });
    // The studio's global Delete handler would delete the tree selection (with a confirm()).
    this.pane.addEventListener("keydown", (e) => {
      if ((e.key === "Delete" || e.key === "Backspace") && !e.target.closest("input, textarea, select")) e.stopPropagation();
    });
    const svg = this.svg;
    svg.addEventListener("pointerdown", e => this.onPointerDown(e));
    svg.addEventListener("pointermove", e => this.onPointerMove(e));
    svg.addEventListener("pointerup", e => this.onPointerUp(e));
    svg.addEventListener("pointercancel", () => this.cancelInteractions());
    svg.addEventListener("dblclick", e => this.onDblClick(e));
    svg.addEventListener("contextmenu", e => this.onContextMenu(e));
    svg.addEventListener("wheel", e => this.onWheel(e), { passive: false });
    this.host.addEventListener("keydown", e => this.onKeyDown(e));
    this.host.addEventListener("keyup", e => this.onKeyUp(e));
    this.host.addEventListener("dragover", e => this.onDragOver(e));
    this.host.addEventListener("dragleave", () => this.clearDropTarget());
    this.host.addEventListener("drop", e => this.onDrop(e));
    new ResizeObserver(() => { if (this.needFit) this.fit(); }).observe(this.host);

    s.on("model-changed", () => {
      this.decorateTree();
      this.fillOpenList();
      this.refreshing = this.refresh();
    });
    // An edit saved elsewhere without a tree refresh (Properties tab, tables): redraw the
    // blocks, badges and the Property Inspector from the current model.
    s.on("element-changed", p => {
      if (p?.selected && this.external?.id === p.selected.id) this.external = p.selected;
      this.refreshing = this.refresh();
    });
    s.on("tab-shown", id => { this.visible = id === "architecture"; if (this.visible) this.shown(); });
    s.on("select", el => this.onStudioSelect(el));
    s.on("selection-changed", ids => this.onStudioSelection(ids));
    s.on("navigate", p => { if (p?.id) this.reveal(p.id); });
    s.on("highlight", p => this.setHighlight(p));
    s.on("canvas-filter", p => this.setFilter(p));
    s.on("undo-state", st => { this.undoState = st || {}; this.updateChrome(); });
    const tree = document.getElementById("tree");
    tree?.addEventListener("dragstart", (e) => {
      const li = e.target.closest?.(".tree-node");
      if (!li?.dataset.id || !e.dataTransfer) return;
      e.dataTransfer.setData(ELEMENT_MIME, li.dataset.id);
      e.dataTransfer.setData("text/plain", s.state.treeIndex.get(li.dataset.id)?.qualified_name || li.dataset.id);
      e.dataTransfer.effectAllowed = "copyLink";
    });
    // Spring-loaded tab: holding a dragged element over the Architecture tab opens the canvas,
    // so elements can be dragged here from other tabs (Interface Editor, Requirements editor).
    const tabBtn = document.querySelector('#tab-bar .tab[data-tab="architecture"]');
    let spring = 0;
    tabBtn?.addEventListener("dragenter", (e) => {
      if (!e.dataTransfer?.types?.includes(ELEMENT_MIME) || s.state.tab === "architecture") return;
      e.preventDefault();      // become the drag's current target so dragleave reaches the tab
      clearTimeout(spring);
      spring = setTimeout(() => { if (s.state.tab !== "architecture") s.switchTab("architecture"); }, SPRING_OPEN_MS);
    });
    tabBtn?.addEventListener("dragleave", () => clearTimeout(spring));
  }

  shown() {
    this.visible = true;
    if (this.needFit) requestAnimationFrame(() => this.fit());
  }

  decorateTree() {
    for (const row of document.querySelectorAll("#tree .tree-node > .row")) row.draggable = true;
  }

  fillOpenList() {
    const defs = [...this.studio.state.treeIndex.values()].filter(n => n.kind === "PartDefinition");
    const root = this.path[0] || this.compId;
    this.openSel.innerHTML = `<option value="">${defs.length ? "— choose —" : "— none —"}</option>`
      + defs.map(n => `<option value="${esc(n.id)}"${n.id === root ? " selected" : ""}>${esc(n.qualified_name || n.name)}</option>`).join("");
  }

  // ------------------------------------------------------------------ loading
  async refresh() {
    const idx = this.studio.state.treeIndex;
    if (!this.compId || !idx.has(this.compId) || this.path.some(id => !idx.has(id))) {
      const pick = await this.pickDefault();
      if (!pick) {
        this.compId = null; this.path = []; this.view = null; this.sel = new Set(); this.primary = null;
        this.render();
        return;
      }
      this.compId = pick.compId;
      this.path = pick.path;
    }
    await this.loadView();
  }

  async pickDefault() {
    const idx = this.studio.state.treeIndex;
    const saved = store.get();
    if (saved.compId && idx.has(saved.compId) && (saved.path || []).every(id => idx.has(id))) {
      return { compId: saved.compId, path: saved.path?.length ? saved.path : [saved.compId] };
    }
    let r;
    try { r = await this.studio.api("GET", "/api/arch/roots"); } catch { return null; }
    const pick = r.roots.find(x => x.component_count) || r.roots[0] || r.definitions[0];
    return pick ? { compId: pick.id, path: [pick.id] } : null;
  }

  async loadView() {
    if (this.drag) { this.reloadAfterDrag = true; return; }    // never redraw under the pointer
    const seq = ++this.seq;
    const q = this.path.length > 1 ? `?path=${encodeURIComponent(this.path.join(","))}` : "";
    let v;
    try { v = await this.studio.api("GET", `/api/arch/view/${encodeURIComponent(this.compId)}${q}`); } catch { return; }
    if (seq !== this.seq) return;
    const switched = !this.view || this.view.composition.id !== v.composition.id;
    this.view = v;
    this.path = v.composition.breadcrumbs.map(b => b.id);
    this.over = { boxes: new Map(), ports: new Map(), points: new Map() };
    this.frameLock = null;
    if (this.connect) this.endConnect();
    this.render();
    const keep = [...this.sel].filter(k => this.dom.has(k));
    if (keep.length !== this.sel.size) this.setSel(keep);
    if (switched) {
      const saved = this.viewports.get(v.composition.id);
      if (saved) this.setViewport(saved); else this.fit();
    }
    this.fillOpenList();
    store.set({ compId: this.compId, path: this.path });
  }

  async open(id, path = null) {
    if (!id) return;
    if (this.view) this.viewports.set(this.compId, { ...this.vp });
    this.cancelInteractions();
    this.compId = id;
    this.path = path || [id];
    this.sel = new Set();
    this.primary = null;
    await this.loadView();
    this.publishSelection();
    this.host.focus({ preventScroll: true });
  }

  openComponent(id) { this.open(id, [...this.path, id]); }

  up() { if (this.path.length > 1) this.open(this.path[this.path.length - 2], this.path.slice(0, -1)); }

  // ------------------------------------------------------------------ scene + render
  portWith(key, p) {
    const o = this.over.ports.get(key);
    return o ? { ...p, ...o } : p;
  }

  computeScene() {
    const v = this.view;
    const blocks = [];
    const ports = new Map();
    for (const c of v.components) {
      const key = ck(c.id);
      const box = this.over.boxes.get(key) || c.layout;
      const b = { key, c, box, ports: [] };
      for (const p0 of c.ports) {
        const k = pk(c.id, p0.id);
        const p = this.portWith(k, p0);
        const pt = { key: k, p, ctx: c.id, owner: b, inward: false,
                     local: G.portPoint({ x: 0, y: 0, w: box.w, h: box.h }, p.side, p.offset),
                     labelWidth: Math.max(28, box.w / 2 - 16) };
        b.ports.push(pt);
        ports.set(k, pt);
      }
      blocks.push(b);
    }
    const frame = this.frameLock || G.frameFor(blocks.map(b => b.box));
    const bports = v.boundary_ports.map(p0 => {
      const k = pk(null, p0.id);
      const p = this.portWith(k, p0);
      const pt = { key: k, p, ctx: null, owner: null, inward: true, local: G.portPoint(frame, p.side, p.offset), labelWidth: 120 };
      ports.set(k, pt);
      return pt;
    });
    const sc = { frame, blocks, bports, ports, conns: [], byComp: new Map(), byPort: new Map(), comp: v.composition,
                 blockByKey: new Map(blocks.map(b => [b.key, b])), connByKey: new Map() };
    const push = (m, k, x) => { if (!m.has(k)) m.set(k, []); m.get(k).push(x); };
    for (const c of v.connectors) {
      if (!c.source?.port_id || !c.target?.port_id) continue;
      const a = ports.get(pk(c.source.component_id, c.source.port_id));
      const b = ports.get(pk(c.target.component_id, c.target.port_id));
      if (!a || !b) continue;
      const k = { key: kk(c.id), c, a, b, color: connectorColor(c, a.p), filtered: false, pts: null };
      k.pts = this.routeOf(k, frame, blocks);
      if (this.filter) k.filtered = [a, b].some(e => e.ctx && !this.filter.ids.has(e.ctx));
      sc.conns.push(k);
      sc.connByKey.set(k.key, k);
      for (const e of [a, b]) { push(sc.byPort, e.key, k); push(sc.byComp, e.ctx ? ck(e.ctx) : "frame", k); }
    }
    const boxes = blocks.map(b => b.box);
    for (const k of sc.conns) k.labelPos = k.c.label ? G.labelPlacement(k.pts, labelText(k.c), boxes) : null;
    return sc;
  }

  attachOf(pt, frame) {
    return pt.owner ? G.attachPoint(pt.owner.box, pt.p.side, pt.p.offset, false)
      : G.attachPoint(frame, pt.p.side, pt.p.offset, true);
  }

  routeOf(k, frame, blocks = this.scene?.blocks || []) {
    const points = this.over.points.has(k.key) ? this.over.points.get(k.key) : k.c.points;
    const ends = [k.a.owner, k.b.owner];
    const obstacles = points ? [] : blocks.filter(b => !ends.includes(b)).map(b => b.box);
    return G.route(this.attachOf(k.a, frame), this.attachOf(k.b, frame),
                   { points, avoid: ends.filter(Boolean).map(b => b.box), obstacles });
  }

  renderOpts() {
    return { sel: this.sel, hl: this.hl, filter: this.filter, markers: this.markers, connect: this.connect?.targets || null };
  }

  render() {
    const v = this.view;
    this.empty.hidden = !!v;
    this.svg.classList.toggle("is-empty", !v);
    if (!v) {
      for (const l of Object.values(this.L)) l.innerHTML = "";
      this.scene = null;
      this.dom = new Map();
      this.updateChrome();
      return;
    }
    const sc = this.scene = this.computeScene();
    this.markers = new Markers();
    const o = this.renderOpts();
    this.L.frame.innerHTML = frameSvg(sc, o);
    this.L.blocks.innerHTML = sc.blocks.map(b => blockSvg(b, b.ports, o)).join("");
    this.L.bports.innerHTML = sc.bports.map(pt => portSvg(pt, o)).join("");
    this.L.conns.innerHTML = sc.conns.map(k => connectorSvg(k, o)).join("");
    this.L.labels.innerHTML = sc.conns.map(k => connectorLabelSvg(k, o)).join("");
    this.markerDefs.innerHTML = this.markers.defs();
    this.indexDom();
    if (this.connect) this.dom.get(this.connect.from)?.classList.add("source");
    this.renderHandles();
    this.applyViewport();
    this.updateChrome();
  }

  indexDom() {
    this.dom = new Map();
    for (const el of this.svg.querySelectorAll("[data-key]")) this.dom.set(el.dataset.key, el);
    this.labels = new Map();
    for (const el of this.L.labels.querySelectorAll("[data-label-for]")) this.labels.set(el.dataset.labelFor, el);
  }

  replaceEl(key, html) {
    const old = this.dom.get(key);
    if (!old) return null;
    const tmp = document.createElementNS(SVGNS, "g");
    tmp.innerHTML = html;
    const fresh = tmp.firstElementChild;
    old.replaceWith(fresh);
    this.dom.set(key, fresh);
    for (const d of fresh.querySelectorAll("[data-key]")) this.dom.set(d.dataset.key, d);
    return fresh;
  }

  updateConnector(k) {
    k.pts = this.routeOf(k, this.scene.frame);
    const el = this.dom.get(k.key);
    if (!el) return;
    const d = G.pathD(k.pts);
    el.querySelector(".arch-conn-hit")?.setAttribute("d", d);
    el.querySelector(".arch-conn-line")?.setAttribute("d", d);
    const t = this.labels?.get(k.key)?.querySelector("text");
    if (t) {
      k.labelPos = G.labelPlacement(k.pts, labelText(k.c), this.scene.blocks.map(b => b.box));
      t.setAttribute("x", Math.round(k.labelPos.x * 10) / 10);
      t.setAttribute("y", Math.round(k.labelPos.y * 10) / 10);
      t.setAttribute("text-anchor", k.labelPos.anchor);
    }
  }

  redrawFrame() {
    const sc = this.scene;
    for (const pt of sc.bports) pt.local = G.portPoint(sc.frame, pt.p.side, pt.p.offset);
    const o = this.renderOpts();
    this.L.frame.innerHTML = frameSvg(sc, o);
    this.L.bports.innerHTML = sc.bports.map(pt => portSvg(pt, o)).join("");
    for (const pt of sc.bports) this.dom.set(pt.key, this.L.bports.querySelector(`[data-key="${CSS.escape(pt.key)}"]`));
    for (const k of sc.byComp.get("frame") || []) this.updateConnector(k);
  }

  renderHandles() {
    let html = "";
    if (this.sel.size === 1 && this.scene && !this.drag) {
      const k = this.scene.connByKey.get([...this.sel][0]);
      if (k) {
        html = G.segmentHandles(k.pts).map(s => `<rect class="arch-seg" data-seg="${s.i}" x="${s.x - 4.5}" y="${s.y - 4.5}"
          width="9" height="9" rx="2" style="cursor:${s.horizontal ? "ns-resize" : "ew-resize"}"><title>Drag to move this segment</title></rect>`).join("");
      }
    }
    this.L.handles.innerHTML = html;
  }

  applySelectionClasses() {
    for (const [k, el] of this.dom) el.classList.toggle("sel", this.sel.has(k));
    for (const [k, el] of this.labels || []) el.classList.toggle("sel", this.sel.has(k));
  }

  // ------------------------------------------------------------------ chrome
  selectedComponents() {
    if (!this.scene) return [];
    return [...this.sel].filter(k => k.startsWith("c:")).map(k => this.scene.blockByKey.get(k)?.c).filter(Boolean);
  }

  updateChrome() {
    const u = this.undoState || {};
    updateToolstrip(this.strip, {
      view: this.view, allowedKinds: this.view?.allowed_port_kinds || [], comps: this.selectedComponents(),
      selCount: this.sel.size, clipboard: clipboard.ids.length, canUndo: !!u.can_undo, canRedo: !!u.can_redo,
      undoLabel: u.undo_label, redoLabel: u.redo_label, componentCount: this.view?.components.length || 0,
      mode: this.mode, dockOpen: this.dockOpen, zoom: this.vp.zoom, readOnlyChildren: false,
    });
    const bc = this.view?.composition.breadcrumbs || [];
    this.crumbs.innerHTML = (bc.length > 1 ? `<button type="button" class="arch-up" data-crumb-up title="Up one level (Alt+↑)" aria-label="Up one level">${icon("up")}</button>` : "")
      + bc.map((b, i) => i === bc.length - 1 ? `<b aria-current="page">${esc(b.name)}</b>`
        : `<button type="button" data-crumb="${i}">${esc(b.name)}</button>`).join(`<span class="arch-crumb-sep">›</span>`);
    this.renderBanners();
    this.updateStatus();
    this.dockEl.hidden = !this.dockOpen;
    if (this.dockOpen) {
      const external = this.external && this.studio.state.treeIndex.has(this.external.id) ? this.external : null;
      this.dock.render({ view: this.view, sel: [...this.sel], primary: this.primary, info: this.primaryInfo(), external });
    }
  }

  updateStatus(hint) {
    const v = this.view;
    if (!v) { this.statusEl.textContent = ""; return; }
    const hints = {
      select: "Drag from a port to connect · Shift+drag a port to move it · Double-click a block to open it · Right-click for more",
      connect: "Connect: click a port, then a port, a block or the frame edge · Esc to stop",
      pan: "Pan: drag the background · Esc returns to Select",
    };
    const parts = [`${v.components.length} components`, `${v.connectors.length} connectors`, `${Math.round(this.vp.zoom * 100)}%`];
    if (this.sel.size) parts.push(`${this.sel.size} selected`);
    this.statusEl.textContent = `${parts.join(" · ")}  —  ${hint || hints[this.mode]}`;
  }

  renderBanners() {
    const out = [];
    if (this.filter) {
      const n = this.view ? this.view.components.filter(c => this.filter.ids.has(c.id)).length : 0;
      out.push(`<span class="arch-banner" data-banner="filter"><b>View:</b> ${esc(this.filter.label || "filtered")}
        <span class="arch-dock-muted">${n} of ${this.view?.components.length || 0}</span>
        <label><input type="checkbox" data-banner-hide ${this.filter.hide ? "checked" : ""}/> hide others</label>
        <button type="button" class="arch-x" data-banner-clear="filter" title="Show all components" aria-label="Clear view filter">×</button></span>`);
    }
    if (this.hl) {
      out.push(`<span class="arch-banner hl" data-banner="highlight" style="--hl:${esc(this.hl.color)}"><i></i>${esc(this.hl.reason || "Highlighted")}
        <span class="arch-dock-muted">${this.hl.ids.size}</span>
        <button type="button" class="arch-x" data-banner-clear="highlight" title="Clear highlight" aria-label="Clear highlight">×</button></span>`);
    }
    this.banners.innerHTML = out.join("");
  }

  primaryInfo() {
    const key = this.primary;
    if (!key || !this.scene) return null;
    if (key.startsWith("c:")) { const b = this.scene.blockByKey.get(key); return b ? { type: "component", c: b.c } : null; }
    if (key.startsWith("p:")) { const pt = this.scene.ports.get(key); return pt ? { type: "port", p: pt.p, ctxName: pt.owner?.c.name } : null; }
    const k = this.scene.connByKey.get(key);
    return k ? { type: "connector", k: k.c, from: this.epLabel(k.a), to: this.epLabel(k.b) } : null;
  }

  epLabel(pt) { return pt.owner ? `${pt.owner.c.name}.${pt.p.name}` : `${pt.p.name} (boundary)`; }

  // ------------------------------------------------------------------ viewport
  applyViewport() {
    const { zoom, panX, panY } = this.vp;
    const t = `translate(${Math.round(panX * 10) / 10},${Math.round(panY * 10) / 10}) scale(${Math.round(zoom * 1000) / 1000})`;
    this.vpG.setAttribute("transform", t);
    this.grid?.setAttribute("patternTransform", t);
    const z = this.strip.querySelector('[data-canvas-act="zoom-reset"]');
    if (z) z.textContent = `${Math.round(zoom * 100)}%`;
  }

  setViewport(vp) {
    if (this.inline.active) this.inline.el.blur();     // commit an open name edit before the view moves
    this.vp = vp;
    this.applyViewport();
    this.updateStatus();
    if (this.compId) this.viewports.set(this.compId, { ...vp });
  }

  svgRect() { return this.svg.getBoundingClientRect(); }

  // Fit the frame (and the boundary port labels outside it) into the view. Automatic fits
  // (opening a composition) stop at 100%; the Fit button may zoom in further.
  fit(maxZoom = 1) {
    if (!this.scene) return;
    const r = this.svgRect();
    if (r.width < 40 || r.height < 40) { this.needFit = true; return; }
    this.needFit = false;
    const f = this.scene.frame;
    this.setViewport(G.fitTransform({ x: f.x - 80, y: f.y - 24, w: f.w + 160, h: f.h + 48 }, r.width, r.height - 18,
                                    { pad: 12, maxZoom }));
    this.renderHandles();
  }

  zoomBy(f, cx, cy) {
    const r = this.svgRect();
    this.setViewport(G.zoomAt(this.vp, f, cx ?? r.width / 2, cy ?? r.height / 2));
  }

  setZoom(z) { this.zoomBy(z / this.vp.zoom); }

  toModel(e) {
    const r = this.svgRect();
    return { x: (e.clientX - r.left - this.vp.panX) / this.vp.zoom, y: (e.clientY - r.top - this.vp.panY) / this.vp.zoom };
  }

  visibleArea(inset = 0) {
    const r = this.svgRect();
    const z = this.vp.zoom;
    return { x: (inset - this.vp.panX) / z, y: (inset - this.vp.panY) / z,
             w: Math.max(0, r.width - 2 * inset) / z, h: Math.max(0, r.height - 2 * inset) / z };
  }

  boundsOf(key) {
    const sc = this.scene;
    if (!sc) return null;
    const b = sc.blockByKey.get(key);
    if (b) return b.box;
    const pt = sc.ports.get(key);
    if (pt) { const p = pt.owner ? G.portPoint(pt.owner.box, pt.p.side, pt.p.offset) : pt.local; return { x: p.x - 10, y: p.y - 10, w: 20, h: 20 }; }
    const k = sc.connByKey.get(key);
    if (k) { const xs = k.pts.map(p => p.x), ys = k.pts.map(p => p.y); return G.rectFrom({ x: Math.min(...xs), y: Math.min(...ys) }, { x: Math.max(...xs), y: Math.max(...ys) }); }
    return null;
  }

  // Pan just enough to bring an element into view (centre it when it is larger than the view).
  scrollIntoView(key) {
    const b = this.boundsOf(key);
    const r = this.svgRect();
    if (!b || r.width < 40) return;
    const z = this.vp.zoom, m = 24;
    const shift = (lo, hi, size, pan) => {
      const a = lo * z + pan, c = hi * z + pan;
      if (c - a > size - 2 * m) return size / 2 - ((lo + hi) / 2) * z;
      if (a < m) return pan + (m - a);
      if (c > size - m) return pan - (c - (size - m));
      return pan;
    };
    const panX = shift(b.x, b.x + b.w, r.width, this.vp.panX);
    const panY = shift(b.y, b.y + b.h, r.height - 22, this.vp.panY);
    if (panX !== this.vp.panX || panY !== this.vp.panY) this.setViewport({ ...this.vp, panX, panY });
  }

  // ------------------------------------------------------------------ selection
  setSel(keys, { emit = false, primary = null } = {}) {
    this.external = null;
    this.sel = new Set(keys);
    this.primary = primary && this.sel.has(primary) ? primary : (keys.length ? keys[keys.length - 1] : null);
    this.applySelectionClasses();
    this.renderHandles();
    this.updateChrome();
    if (emit) this.publishSelection();
  }

  publishSelection() {
    const s = this.studio;
    const ids = [...new Set([...this.sel].map(k => parseKey(k).id))];
    this.emitting = true;
    try { s.setSelection(ids); } finally { this.emitting = false; }
    const id = this.primary ? parseKey(this.primary).id : this.compId;
    if (id && s.state.selectedId !== id && s.state.treeIndex.has(id)) {
      this.selfSelect = id;
      s.selectElement(id).catch(() => {});
    }
  }

  keyFor(id) {
    const sc = this.scene;
    if (!sc || !id) return null;
    if (sc.blockByKey.has(ck(id))) return ck(id);
    if (sc.connByKey.has(kk(id))) return kk(id);
    for (const key of sc.ports.keys()) if (key.endsWith(`:${id}`)) return key;
    return null;
  }

  onStudioSelect(el) {
    if (!el?.id) return;
    // selectElement sets selectedId at once and fires "select" after its fetch: an event
    // for anything else is stale (rapid clicks) and must not pull the selection back.
    if (el.id !== this.studio.state.selectedId) return;
    if (this.selfSelect === el.id) { this.selfSelect = null; return; }
    if (this.primary && parseKey(this.primary).id === el.id) return;
    if (!this.view || el.id === this.compId) return;
    const key = this.keyFor(el.id);
    if (key) { this.setSel([key]); this.scrollIntoView(key); return; }
    // The canvas follows the model browser; anything it does not draw is shown in the dock.
    if (FOLLOW_KINDS.has(el.kind)) this.reveal(el.id).then(found => { if (!found) this.showExternal(el); });
    else this.showExternal(el);
  }

  showExternal(el) {
    if (this.studio.state.selectedId !== el.id) return;      // the selection moved on meanwhile
    this.external = el;
    this.sel = new Set();
    this.primary = null;
    this.applySelectionClasses();
    this.renderHandles();
    this.updateChrome();
  }

  onStudioSelection(ids) {
    if (this.emitting || !this.scene || !Array.isArray(ids)) return;
    const keys = ids.map(id => this.keyFor(id)).filter(Boolean);
    if (!keys.length) {
      if (!ids.length && this.sel.size) this.setSel([]);
      return;
    }
    const same = keys.length === this.sel.size && keys.every(k => this.sel.has(k));
    if (!same) this.setSel(keys);
  }

  // Open the composition that shows an element and select it there (navigate contract).
  async reveal(id) {
    const s = this.studio;
    if (!s.state.treeIndex.has(id)) return false;
    const here = this.keyFor(id);
    if (here) { this.setSel([here]); this.scrollIntoView(here); return true; }
    let r;
    try { r = await s.api("GET", `/api/arch/locate/${encodeURIComponent(id)}`); } catch { return false; }
    if (!r.composition) return false;
    if (r.composition !== this.compId) {
      if (this.view) this.viewports.set(this.compId, { ...this.vp });
      this.cancelInteractions();
      this.compId = r.composition;
      this.path = [r.composition];
      this.sel = new Set();
      this.primary = null;
      await this.loadView();
    }
    const key = r.select ? this.keyFor(r.select) : null;
    if (key) { this.setSel([key]); this.scrollIntoView(key); }
    return true;
  }

  // ------------------------------------------------------------------ contracts
  setHighlight(p) {
    this.hl = p && Array.isArray(p.ids) && p.ids.length
      ? { ids: new Set(p.ids), color: p.color || "#f59e0b", reason: p.reason || "" } : null;
    if (this.view) this.render(); else this.renderBanners();
  }

  setFilter(p) {
    this.filter = p && Array.isArray(p.ids) ? { ids: new Set(p.ids), label: p.label || "", hide: !!p.hide } : null;
    if (this.view) this.render(); else this.renderBanners();
  }

  // ------------------------------------------------------------------ pointer
  hit(target) {
    const el = target?.closest?.("[data-kind]");
    if (!el || !this.svg.contains(el)) return null;
    const role = target.closest("[data-role]")?.dataset.role || null;
    return { kind: el.dataset.kind, key: el.dataset.key || el.dataset.labelFor || null, id: el.dataset.id, el, role };
  }

  hitAt(e) { return this.hit(document.elementFromPoint(e.clientX, e.clientY)); }

  capture(e) { try { this.svg.setPointerCapture(e.pointerId); } catch { /* not active */ } }

  onPointerDown(e) {
    if (!this.view) return;
    this.host.focus({ preventScroll: true });
    if (this.drag) return;
    if (e.button === 1 || (e.button === 0 && (this.space || this.mode === "pan"))) {
      e.preventDefault();
      this.startPan(e);
      return;
    }
    if (e.button !== 0) return;
    const pt = this.toModel(e);
    const seg = e.target.closest?.("[data-seg]");
    if (seg) { e.preventDefault(); this.startSegmentDrag(Number(seg.dataset.seg), e, pt); return; }
    const h = this.hit(e.target);
    if (h?.role === "resize" && h.kind === "component") { e.preventDefault(); this.startResize(h.key, e, pt); return; }
    this.pending = { x: e.clientX, y: e.clientY, pt0: pt, h, shift: e.shiftKey, alt: e.altKey,
                     toggle: e.shiftKey || e.ctrlKey || e.metaKey };
    this.capture(e);
    e.preventDefault();
  }

  onPointerMove(e) {
    if (this.drag) { this.drag.move(e); return; }
    if (this.pending) {
      if (Math.hypot(e.clientX - this.pending.x, e.clientY - this.pending.y) < DRAG_START) return;
      const p = this.pending;
      this.pending = null;
      this.beginDrag(p, e);
      return;
    }
    if (this.connect?.click) this.connectHover(e);
  }

  onPointerUp(e) {
    try { this.svg.releasePointerCapture(e.pointerId); } catch { /* none */ }
    if (this.drag) {
      const d = this.drag;
      this.drag = null;
      d.end(e);
      if (this.reloadAfterDrag) { this.reloadAfterDrag = false; this.refreshing = this.loadView(); }
      return;
    }
    if (this.pending) { const p = this.pending; this.pending = null; this.click(p, e); }
  }

  beginDrag(p, e) {
    const h = p.h;
    if (h?.kind === "port") {
      if (p.shift || p.alt) this.startPortMove(h.key, e);
      else this.startConnectDrag(h.key, e);
    } else if (h?.kind === "component") {
      if (!this.sel.has(h.key)) this.setSel(p.toggle ? [...this.sel, h.key] : [h.key], { emit: true });
      this.startMove(p, e);
    } else if (!h || h.kind === "frame") {
      this.startBand(p, e);
    }
  }

  click(p) {
    const h = p.h;
    if (this.mode === "connect") {
      if (h?.kind === "port") {
        if (!this.connect) { this.beginConnect(h.key, true); return; }
        if (h.key === this.connect.from) { this.endConnect(); return; }
        this.finishConnect(h, p.pt0);
        return;
      }
      if (this.connect) { this.finishConnect(h, p.pt0); return; }
    }
    if (!h || h.kind === "frame") { if (!p.toggle) this.setSel([], { emit: true }); return; }
    if (!h.key) return;
    if (p.toggle) {
      const s = new Set(this.sel);
      if (s.has(h.key)) s.delete(h.key); else s.add(h.key);
      this.setSel([...s], { emit: true, primary: s.has(h.key) ? h.key : null });
    } else {
      this.setSel([h.key], { emit: true });
    }
  }

  rafDrag(apply, end) {
    let raf = 0, last = null;
    const run = () => { raf = 0; if (last) apply(last); };
    return {
      move: (ev) => { last = ev; if (!raf) raf = requestAnimationFrame(run); },
      end: (ev) => { if (raf) cancelAnimationFrame(raf); raf = 0; last = ev; apply(ev); end(ev); },
    };
  }

  startPan(e) {
    const v0 = { ...this.vp };
    const x0 = e.clientX, y0 = e.clientY;
    this.spaceUsed = true;
    this.host.classList.add("panning");
    this.capture(e);
    this.drag = this.rafDrag(
      ev => this.setViewport({ ...v0, panX: v0.panX + ev.clientX - x0, panY: v0.panY + ev.clientY - y0 }),
      () => this.host.classList.remove("panning"));
  }

  startMove(p) {
    const sc = this.scene;
    const keys = [...this.sel].filter(k => sc.blockByKey.has(k));
    if (!keys.length) return;
    const start = new Map(keys.map(k => [k, { ...sc.blockByKey.get(k).box }]));
    const frame0 = sc.frame;
    this.frameLock = frame0;
    this.host.classList.add("dragging");
    this.L.handles.innerHTML = "";
    this.drag = this.rafDrag((ev) => {
      const m = this.toModel(ev);
      const dx = m.x - p.pt0.x, dy = m.y - p.pt0.y;
      for (const [k, b0] of start) {
        const box = { ...b0, x: ev.altKey ? b0.x + dx : G.snap(b0.x + dx), y: ev.altKey ? b0.y + dy : G.snap(b0.y + dy) };
        this.over.boxes.set(k, box);
        sc.blockByKey.get(k).box = box;
        this.dom.get(k)?.setAttribute("transform", `translate(${box.x},${box.y})`);
      }
      this.afterBoxesChanged(keys, frame0);
    }, () => {
      this.host.classList.remove("dragging");
      this.frameLock = null;
      const items = [];
      for (const [k, b0] of start) {
        const b = this.over.boxes.get(k);
        if (b && (b.x !== b0.x || b.y !== b0.y)) items.push({ id: parseKey(k).id, x: b.x, y: b.y });
      }
      if (!items.length) { this.over.boxes.clear(); this.renderHandles(); return; }
      this.run(() => this.studio.api("POST", "/api/arch/layout", { items }));
    });
  }

  afterBoxesChanged(keys, frame0) {
    const sc = this.scene;
    const want = G.union(frame0, G.frameFor(sc.blocks.map(b => b.box)));
    if (want.x !== sc.frame.x || want.y !== sc.frame.y || want.w !== sc.frame.w || want.h !== sc.frame.h) {
      sc.frame = want;
      this.frameLock = want;
      this.redrawFrame();
    }
    const done = new Set();
    for (const k of keys) {
      for (const c of sc.byComp.get(k) || []) {
        if (!done.has(c)) { done.add(c); this.updateConnector(c); }
      }
    }
  }

  startResize(key, e, pt0) {
    const sc = this.scene;
    const b = sc.blockByKey.get(key);
    if (!b) return;
    const b0 = { ...b.box };
    this.frameLock = sc.frame;
    this.capture(e);
    this.host.classList.add("resizing");
    this.drag = this.rafDrag((ev) => {
      const m = this.toModel(ev);
      const box = { ...b0, w: Math.max(G.MIN_W, G.snap(b0.w + m.x - pt0.x)), h: Math.max(G.MIN_H, G.snap(b0.h + m.y - pt0.y)) };
      if (box.w === b.box.w && box.h === b.box.h) return;
      this.over.boxes.set(key, box);
      b.box = box;
      for (const pt of b.ports) {
        pt.local = G.portPoint({ x: 0, y: 0, w: box.w, h: box.h }, pt.p.side, pt.p.offset);
        pt.labelWidth = Math.max(28, box.w / 2 - 16);
      }
      this.replaceEl(key, blockSvg(b, b.ports, this.renderOpts()));
      this.afterBoxesChanged([key], sc.frame);
    }, () => {
      this.host.classList.remove("resizing");
      this.frameLock = null;
      const box = this.over.boxes.get(key);
      if (!box || (box.w === b0.w && box.h === b0.h)) return;
      this.run(() => this.studio.api("POST", "/api/arch/layout",
                                     { items: [{ id: parseKey(key).id, x: box.x, y: box.y, w: box.w, h: box.h }] }));
    });
  }

  startPortMove(key, e) {
    const sc = this.scene;
    const pt = sc.ports.get(key);
    if (!pt) return;
    const orig = { side: pt.p.side, offset: pt.p.offset };
    this.frameLock = sc.frame;
    this.host.classList.add("dragging");
    this.drag = this.rafDrag((ev) => {
      const box = pt.owner ? pt.owner.box : sc.frame;
      const pos = G.nearestSide(box, this.toModel(ev));
      if (pos.side === pt.p.side && pos.offset === pt.p.offset) return;
      this.over.ports.set(key, pos);
      pt.p = { ...pt.p, ...pos };
      pt.local = pt.owner ? G.portPoint({ x: 0, y: 0, w: box.w, h: box.h }, pos.side, pos.offset) : G.portPoint(box, pos.side, pos.offset);
      this.replaceEl(key, portSvg(pt, this.renderOpts()));
      for (const k of sc.byPort.get(key) || []) this.updateConnector(k);
    }, () => {
      this.host.classList.remove("dragging");
      this.frameLock = null;
      const o = this.over.ports.get(key);
      if (!o || (o.side === orig.side && o.offset === orig.offset)) return;
      this.run(() => this.studio.api("POST", "/api/arch/layout", { items: [{ id: pt.p.id, side: o.side, offset: o.offset }] }));
    });
    this.drag.move(e);
  }

  startBand(p) {
    const base = p.toggle ? new Set(this.sel) : new Set();
    const rect = document.createElementNS(SVGNS, "rect");
    rect.setAttribute("class", "arch-band");
    this.L.temp.appendChild(rect);
    this.drag = this.rafDrag((ev) => {
      const r = G.rectFrom(p.pt0, this.toModel(ev));
      for (const [a, v] of [["x", r.x], ["y", r.y], ["width", r.w], ["height", r.h]]) rect.setAttribute(a, v);
      const sel = new Set(base);
      for (const b of this.scene.blocks) {
        if (this.filter?.hide && !this.filter.ids.has(b.c.id)) continue;
        if (G.intersects(r, b.box)) sel.add(b.key);
      }
      for (const pt of this.scene.bports) if (G.inside(pt.local, r)) sel.add(pt.key);
      for (const k of this.scene.conns) if (k.pts.every(q => G.inside(q, r))) sel.add(k.key);
      this.sel = sel;
      this.applySelectionClasses();
    }, () => {
      rect.remove();
      this.setSel([...this.sel], { emit: true });
    });
  }

  startSegmentDrag(i, e, pt0) {
    const key = [...this.sel][0];
    const k = this.scene?.connByKey.get(key);
    if (!k) return;
    const pts0 = k.pts.map(q => ({ ...q }));
    const horizontal = Math.abs(pts0[i].y - pts0[i + 1].y) < 0.01;
    let stored = null;
    this.capture(e);
    this.drag = this.rafDrag((ev) => {
      const m = this.toModel(ev);
      const dx = G.snap(pts0[i].x + m.x - pt0.x) - pts0[i].x;
      const dy = G.snap(pts0[i].y + m.y - pt0.y) - pts0[i].y;
      stored = G.moveSegment(pts0, i, horizontal ? 0 : dx, horizontal ? dy : 0);
      this.over.points.set(key, stored);
      this.updateConnector(k);
    }, () => {
      this.renderHandles();
      if (!stored) return;
      this.run(() => this.studio.api("POST", "/api/arch/layout", { items: [{ id: k.c.id, points: stored }] }));
    });
  }

  // ------------------------------------------------------------------ connecting
  endpointOf(key) {
    const { ctx, id } = parseKey(key);
    return { component: ctx || null, port: id };
  }

  startConnectDrag(fromKey, e) {
    this.beginConnect(fromKey, false);
    this.drag = this.rafDrag(ev => this.connectHover(ev), (ev) => {
      const h = this.hitAt(ev);
      this.finishConnect(h, this.toModel(ev));
    });
    this.connectHover(e);
  }

  beginConnect(fromKey, click) {
    if (!this.scene?.ports.has(fromKey)) return;
    this.endConnect();
    const c = { from: fromKey, click, targets: null };
    this.connect = c;
    this.host.classList.add("connecting");
    this.dom.get(fromKey)?.classList.add("source");
    const { ctx, id } = parseKey(fromKey);
    const q = new URLSearchParams({ composition: this.compId, source_port: id });
    if (ctx) q.set("source_component", ctx);
    c.loading = this.studio.api("GET", `/api/arch/connect-targets?${q}`).then((r) => {
      if (this.connect !== c) return;
      c.targets = new Map(r.targets.map(t => [pk(t.component_id, t.port_id), t]));
      for (const [key, t] of c.targets) {
        const el = this.dom.get(key);
        if (!el) continue;
        el.classList.add(t.ok ? "can" : "cannot");
        if (t.reason) el.dataset.reason = t.reason;
      }
    }).catch(() => {});
    this.updateStatus();
  }

  nearFrameEdge(pt) {
    const f = this.scene.frame;
    const inner = { x: f.x + EDGE_ZONE, y: f.y + EDGE_ZONE, w: f.w - 2 * EDGE_ZONE, h: f.h - 2 * EDGE_ZONE };
    return G.inside(pt, f, EDGE_ZONE) && !G.inside(pt, inner);
  }

  connectHover(ev) {
    const c = this.connect;
    if (!c || !this.scene) return;
    const from = this.scene.ports.get(c.from);
    if (!from) return;
    const a = this.attachOf(from, this.scene.frame);
    const pt = this.toModel(ev);
    const h = this.hitAt(ev);
    let end = pt, state = "free", note = "";
    for (const el of this.svg.querySelectorAll(".hover-target")) el.classList.remove("hover-target");
    if (h?.kind === "port" && h.key !== c.from && this.scene.ports.has(h.key)) {
      end = this.attachOf(this.scene.ports.get(h.key), this.scene.frame);
      const t = c.targets?.get(h.key);
      state = t ? (t.ok ? "ok" : "bad") : "free";
      note = t ? (t.ok ? `Release to connect${t.swapped ? " (direction fixed automatically)" : ""}` : `✗ ${t.reason}`) : "";
      h.el.classList.add("hover-target");
    } else if (h?.kind === "component" && h.key !== ck(from.ctx)) {
      state = "new";
      note = `Release to add a matching port to ${this.scene.blockByKey.get(h.key)?.c.name}`;
      h.el.classList.add("hover-target");
    } else if (this.nearFrameEdge(pt)) {
      state = "new";
      note = "Release to add a boundary port here";
    }
    this.L.temp.innerHTML = `<path class="arch-rubber ${state}" d="M${a.x} ${a.y} L${end.x} ${end.y}"/>`;
    this.updateStatus(note || undefined);
  }

  endConnect() {
    if (!this.connect) return;
    this.connect = null;
    this.host.classList.remove("connecting");
    for (const el of this.svg.querySelectorAll(".can, .cannot, .source, .hover-target")) {
      el.classList.remove("can", "cannot", "source", "hover-target");
      delete el.dataset.reason;
    }
    this.L.temp.innerHTML = "";
    this.updateStatus();
  }

  async canConnect(fromKey, toKey) {
    const a = parseKey(fromKey), b = parseKey(toKey);
    const q = new URLSearchParams({ composition: this.compId, source_port: a.id, target_port: b.id });
    if (a.ctx) q.set("source_component", a.ctx);
    if (b.ctx) q.set("target_component", b.ctx);
    try { return await this.studio.api("GET", `/api/arch/can-connect?${q}`); } catch { return null; }
  }

  async finishConnect(h, pt) {
    const c = this.connect;
    if (!c || !this.scene) return;
    const fromKey = c.from;
    const from = this.scene.ports.get(fromKey);
    this.endConnect();
    if (!from) return;
    const src = this.endpointOf(fromKey);
    const composition = this.compId;
    if (h?.kind === "port" && h.key && h.key !== fromKey) {
      const t = c.targets?.get(h.key) || await this.canConnect(fromKey, h.key);
      if (!t) return;
      if (!t.ok) { this.toast(`Cannot connect: ${t.reason}`, "error"); this.studio.log(`Cannot connect: ${t.reason}`, "warning"); return; }
      await this.run(() => this.studio.api("POST", "/api/arch/connector", { composition, source: src, target: this.endpointOf(h.key) }),
                     { selectKeys: r => [kk(r.id)], ok: r => `Connected (${r.kind})${r.label ? ` ${r.label}` : ""}` });
      return;
    }
    if (h?.kind === "component") {
      const b = this.scene.blockByKey.get(h.key);
      if (!b) return;
      if (from.ctx === b.c.id) { this.toast(`Cannot connect ${from.p.name} to a new port of its own component`, "error"); return; }
      const pos = G.nearestSide(b.box, pt);
      await this.run(() => this.studio.api("POST", "/api/arch/connector", { composition, source: src, target: { component: b.c.id, new_port: pos } }),
                     { selectKeys: r => [kk(r.id)], ok: r => `Connected to new port ${r.created_port?.name} of ${b.c.name}` });
      return;
    }
    if (pt && this.nearFrameEdge(pt)) {
      const pos = G.nearestSide(this.scene.frame, pt);
      await this.run(() => this.studio.api("POST", "/api/arch/connector", { composition, source: src, target: { new_port: pos } }),
                     { selectKeys: r => [kk(r.id)], ok: r => `Connected to new boundary port ${r.created_port?.name}` });
    }
  }

  // ------------------------------------------------------------------ other input
  onDblClick(e) {
    // With pointer capture the event targets the <svg>; hit-test where the pointer is.
    const h = this.hitAt(e);
    if (!h || this.mode === "connect") return;
    if (h.kind === "component") {
      if (h.role === "name") this.rename(h.key);
      else this.openComponent(h.id);
    } else if (h.kind === "port" || h.kind === "connector") this.rename(h.key);
    else if (h.kind === "frame" && h.role === "frame-name") this.renameComposition();
  }

  onWheel(e) {
    if (!this.view) return;
    e.preventDefault();
    const r = this.svgRect();
    const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    this.zoomBy(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
  }

  onContextMenu(e) {
    e.preventDefault();
    if (!this.view) return;
    const h = this.hit(e.target);
    const pt = this.toModel(e);
    if (h?.key && !this.sel.has(h.key)) this.setSel([h.key], { emit: true });
    const hr = this.host.getBoundingClientRect();
    this.menu.open(this.menuItems(h, pt), e.clientX - hr.left, e.clientY - hr.top, { h, pt });
  }

  openMenuForSelection() {
    if (!this.view) return;
    const key = this.primary;
    const el = key ? this.dom.get(key) : null;
    const hr = this.host.getBoundingClientRect();
    const r = el?.getBoundingClientRect();
    const x = r ? r.left - hr.left + r.width / 2 : hr.width / 2;
    const y = r ? r.top - hr.top + r.height / 2 : hr.height / 2;
    const h = el ? { kind: el.dataset.kind, key, id: el.dataset.id, el } : null;
    const pt = this.toModel({ clientX: hr.left + x, clientY: hr.top + y });
    this.menu.open(this.menuItems(h, pt), x, y, { h, pt });
  }

  onKeyDown(e) {
    if (e.target !== this.host) return;
    const ctrl = e.ctrlKey || e.metaKey;
    const k = e.key;
    const lk = k.length === 1 ? k.toLowerCase() : k;
    let handled = true;
    if (k === "Delete" || k === "Backspace") this.deleteSelection();
    else if (k === "Escape") {
      if (this.drag || this.pending) this.cancelInteractions();
      else if (this.connect) this.endConnect();
      else if (this.mode !== "select") this.setMode("select");
      else this.setSel([], { emit: true });
    }
    else if (ctrl && !e.shiftKey && lk === "c") this.copy();
    else if (ctrl && !e.shiftKey && lk === "v") this.paste();
    else if (ctrl && !e.shiftKey && lk === "d") this.duplicate();
    else if (ctrl && !e.shiftKey && lk === "a") this.selectAll();
    else if (ctrl && !e.shiftKey && lk === "g") this.group();
    else if (ctrl) handled = false;                 // Ctrl+Z / Ctrl+Y reach the studio shortcuts
    else if (k === "F2") { if (this.primary) this.rename(this.primary); }
    else if (k === "Enter") { const c = this.selectedComponents(); if (c.length === 1) this.openComponent(c[0].id); }
    else if (e.altKey && k === "ArrowUp") this.up();
    else if (k.startsWith("Arrow")) this.nudge(k, e.shiftKey ? 1 : G.GRID);
    else if (k === "+" || k === "=") this.zoomBy(1.2);
    else if (k === "-" || k === "_") this.zoomBy(1 / 1.2);
    else if (k === "0") this.setZoom(1);
    else if (k === "ContextMenu" || (e.shiftKey && k === "F10")) this.openMenuForSelection();
    else if (k === " ") {
      if (!e.repeat) { this.space = true; this.spaceUsed = false; this.host.classList.add("space"); }
    }
    else handled = false;
    if (handled) { e.preventDefault(); e.stopPropagation(); }
  }

  onKeyUp(e) {
    if (e.key !== " " || !this.space) return;
    this.space = false;
    this.host.classList.remove("space");
    if (!this.spaceUsed) this.fit();
    e.preventDefault();
    e.stopPropagation();
  }

  nudge(key, step) {
    const sc = this.scene;
    const keys = [...this.sel].filter(k => sc?.blockByKey.has(k));
    if (!keys.length) return;
    const [dx, dy] = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[key] || [0, 0];
    const frame0 = sc.frame;
    for (const k of keys) {
      const b = sc.blockByKey.get(k);
      b.box = { ...b.box, x: b.box.x + dx, y: b.box.y + dy };
      this.over.boxes.set(k, b.box);
      this.dom.get(k)?.setAttribute("transform", `translate(${b.box.x},${b.box.y})`);
    }
    this.afterBoxesChanged(keys, frame0);
    this.renderHandles();
    clearTimeout(this.nudgeTimer);
    this.nudgeTimer = setTimeout(() => {
      const items = [...this.over.boxes].map(([k, b]) => ({ id: parseKey(k).id, x: b.x, y: b.y }));
      if (items.length) this.run(() => this.studio.api("POST", "/api/arch/layout", { items }));
    }, 450);
  }

  cancelInteractions() {
    if (this.drag || this.pending) {
      this.drag = null;
      this.pending = null;
      this.over = { boxes: new Map(), ports: new Map(), points: new Map() };
      this.frameLock = null;
      this.L.temp.innerHTML = "";
      if (this.view) this.render();
    }
    this.host.classList.remove("dragging", "panning", "resizing");
    this.endConnect();
    this.menu.close();
  }

  setMode(mode) {
    this.mode = mode;
    if (mode !== "connect") this.endConnect();
    this.host.classList.toggle("mode-connect", mode === "connect");
    this.host.classList.toggle("mode-pan", mode === "pan");
    this.updateChrome();
  }

  // ------------------------------------------------------------------ HTML5 drop
  onDragOver(e) {
    if (!e.dataTransfer?.types?.includes(ELEMENT_MIME) || !this.view) return;
    e.preventDefault();
    const allowed = e.dataTransfer.effectAllowed || "all";
    e.dataTransfer.dropEffect = /link|all|uninitialized/i.test(allowed) ? "link" : /copy/i.test(allowed) ? "copy" : "move";
    const h = this.hit(e.target);
    const el = h && h.kind !== "frame" ? h.el : null;
    if (el !== this.dropEl) {
      this.clearDropTarget();
      this.dropEl = el;
      el?.classList.add("drop-target");
    }
  }

  clearDropTarget() {
    this.dropEl?.classList.remove("drop-target");
    this.dropEl = null;
  }

  onDrop(e) {
    if (!e.dataTransfer?.types?.includes(ELEMENT_MIME) || !this.view) return;
    e.preventDefault();
    this.clearDropTarget();
    const dragged = e.dataTransfer.getData(ELEMENT_MIME);
    if (!dragged) return;
    const h = this.hit(e.target);
    // The canvas only reports the drop; the feature that owns the dragged element reacts
    // (requirements link it, the interfaces feature assigns an interface dropped on a port).
    if (h && h.kind !== "frame") {
      this.studio.emit("drop-on-element", { dragged_id: dragged, target_id: h.id });
      return;
    }
    const node = this.studio.state.treeIndex.get(dragged);
    if (node?.kind === "PartDefinition" && dragged !== this.compId && !this.path.includes(dragged)) {
      const m = this.toModel(e);
      this.run(() => this.studio.api("POST", "/api/arch/component", {
        composition: this.compId, definition: dragged, layout: { x: G.snap(m.x - 80), y: G.snap(m.y - 45) } }),
               { selectKeys: c => [ck(c.id)], ok: c => `Added reference component ${c.name} : ${node.name}` });
      return;
    }
    this.studio.emit("drop-on-element", { dragged_id: dragged, target_id: this.compId });
  }

  // ------------------------------------------------------------------ menus + commands
  portChoices() {
    const out = [];
    for (const k of this.view?.allowed_port_kinds || []) {
      if (k === "data") out.push({ label: "In", kind: "data", dir: "in" }, { label: "Out", kind: "data", dir: "out" },
                                 { label: "InOut", kind: "data", dir: "inout" });
      else out.push({ label: k[0].toUpperCase() + k.slice(1), kind: k, dir: "inout" });
    }
    return out;
  }

  menuItems(h) {
    const kinds = this.portChoices();
    const nothing = !clipboard.ids.length;
    if (!h || h.kind === "frame") {
      return [
        { label: "Add Component here", cmd: "add-component-here" },
        { group: "Boundary port", items: kinds.map(k => ({ label: k.label, cmd: `boundary-here:${k.kind}:${k.dir}`, hint: `Add a ${k.label} boundary port` })) },
        { label: "Paste here", cmd: "paste", hint: "Ctrl+V", disabled: nothing },
        "-",
        { label: "Select all", cmd: "select-all", hint: "Ctrl+A" },
        { label: "Arrange", cmd: "arrange" },
        { label: "Fit to view", cmd: "fit", hint: "Space" },
        ...(this.path.length > 1 ? [{ label: "Up one level", cmd: "up", hint: "Alt+↑" }] : []),
        { label: `Rename ${this.view.composition.name}`, cmd: "rename-composition" },
      ];
    }
    if (h.kind === "component") {
      const c = this.scene.blockByKey.get(h.key)?.c;
      const multi = this.selectedComponents().length > 1;
      if (!c) return [];
      return [
        { label: `Open ${c.name}`, cmd: "open", hint: "Enter", disabled: multi },
        { label: "Rename", cmd: "rename", hint: "F2", disabled: multi },
        { group: "Add port", items: kinds.map(k => ({ label: k.label, cmd: `port:${k.kind}:${k.dir}`, hint: `Add a ${k.label} port` })) },
        "-",
        { label: "Copy", cmd: "copy", hint: "Ctrl+C" },
        { label: "Paste inside", cmd: "paste-inside", disabled: nothing || multi },
        { label: "Duplicate", cmd: "duplicate", hint: "Ctrl+D" },
        { label: "Group into Component", cmd: "group", hint: "Ctrl+G" },
        c.is_reference ? { label: "Inline", cmd: "inline", disabled: multi } : { label: "Save as Reference…", cmd: "save-ref", disabled: multi },
        ...(!c.is_reference && c.has_children ? [{ label: "Expand", cmd: "expand", disabled: multi }] : []),
        ...(c.sized ? [{ label: "Auto size", cmd: "reset-size" }] : []),
        "-",
        { label: "Properties", cmd: "properties" },
        { label: "Delete", cmd: "delete", hint: "Del", danger: true },
      ];
    }
    if (h.kind === "port") {
      const pt = this.scene.ports.get(h.key);
      if (!pt) return [];
      return [
        { label: "Rename", cmd: "rename", hint: "F2" },
        { label: "Start connection here", cmd: "connect-from" },
        ...(pt.p.kind === "data" ? [{ group: "Direction", items: ["in", "out", "inout"].map(d => ({ label: d, cmd: `dir:${d}`, disabled: pt.p.direction === d })) }] : []),
        { group: "Side", items: SIDES.map(s => ({ label: s, cmd: `side:${s}`, disabled: pt.p.side === s })) },
        "-",
        { label: "Properties", cmd: "properties" },
        { label: "Delete", cmd: "delete", hint: "Del", danger: true },
      ];
    }
    const k = this.scene.connByKey.get(h.key);
    return [
      { label: "Rename", cmd: "rename", hint: "F2" },
      { label: "Reset route", cmd: "reset-route", disabled: !(k?.c.points || this.over.points.get(h.key)) },
      "-",
      { label: "Properties", cmd: "properties" },
      { label: "Delete", cmd: "delete", hint: "Del", danger: true },
    ];
  }

  command(cmd, ctx = {}) {
    const h = ctx.h, at = ctx.pt;
    const [name, a, b] = cmd.split(":");
    switch (name) {
      case "new-architecture": return this.newArchitecture();
      case "add-component": return this.addComponent();
      case "add-component-here": return this.addComponent(at);
      case "add-port-in": return this.addPort("data", "in");
      case "add-port-out": return this.addPort("data", "out");
      case "add-port-inout": return this.addPort("data", "inout");
      case "add-port-physical": return this.addPort("physical", "inout");
      case "add-port-client": return this.addPort("client", "inout");
      case "add-port-server": return this.addPort("server", "inout");
      case "port": return this.addPort(a, b);
      case "add-boundary": {
        const r = this.strip.querySelector('[data-canvas-act="add-boundary"]').getBoundingClientRect();
        const hr = this.host.getBoundingClientRect();
        this.menu.open([{ group: "Boundary port", items: this.portChoices().map(k => ({ label: k.label, cmd: `boundary:${k.kind}:${k.dir}`, hint: `Add a ${k.label} boundary port` })) }],
                       r.left - hr.left, 4, {});
        return undefined;
      }
      case "boundary": return this.addBoundaryPort(a, b);
      case "boundary-here": return this.addBoundaryPort(a, b, at);
      case "connect": return this.setMode(this.mode === "connect" ? "select" : "connect");
      case "connect-from": this.setMode("connect"); return this.beginConnect(h?.key || this.primary, true);
      case "pan": return this.setMode(this.mode === "pan" ? "select" : "pan");
      case "group": return this.group();
      case "expand": return this.expand();
      case "save-ref": return this.saveAsReference();
      case "inline": return this.inlineComponent();
      case "copy": return this.copy();
      case "paste": return this.paste();
      case "paste-inside": return this.paste(h?.id);
      case "duplicate": return this.duplicate();
      case "delete": return this.deleteSelection();
      case "undo": return this.undoApi?.undo();
      case "redo": return this.undoApi?.redo();
      case "arrange": return this.arrange();
      case "zoom-in": return this.zoomBy(1.25);
      case "zoom-out": return this.zoomBy(0.8);
      case "zoom-reset": return this.setZoom(1);
      case "fit": return this.fit(1.5);
      case "dock": return this.toggleDock();
      case "select-all": return this.selectAll();
      case "up": return this.up();
      case "open": return h?.id && this.openComponent(h.id);
      case "rename": return this.rename(h?.key || this.primary);
      case "rename-composition": return this.renameComposition();
      case "dir": return this.updatePort(parseKey(h?.key || this.primary).id, { direction: a });
      case "side": return this.movePortSide(h?.key || this.primary, a);
      case "reset-route": return this.resetRoute(h?.id);
      case "reset-size": return this.resetSize(h?.id);
      case "properties": return this.showProperties(h?.id);
      default: return undefined;
    }
  }

  // ------------------------------------------------------------------ edits
  async run(fn, { selectKeys = null, ok = null } = {}) {
    try {
      const r = await fn();
      if (selectKeys) this.setSel(selectKeys(r));
      if (ok) this.studio.log(typeof ok === "function" ? ok(r) : ok, "ok");
      await this.sync();
      if (selectKeys) this.setSel([...this.sel].filter(k => this.dom.has(k)), { emit: true });
      return r ?? true;
    } catch (e) {
      this.toast(String(e?.message || e), "error");
      this.over = { boxes: new Map(), ports: new Map(), points: new Map() };
      await this.sync();
      return null;
    }
  }

  // Reload the tree (which emits model-changed and so refreshes this canvas), keep the
  // studio selection on the canvas's primary element, and wait for the new view.
  async sync() {
    await reload(this.studio, this.primary ? parseKey(this.primary).id : this.compId);
    await this.refreshing;
  }

  async newArchitecture() {
    const a = await this.run(() => this.studio.api("POST", "/api/arch/architecture", {}), { ok: r => `New architecture ${r.name}` });
    if (!a) return;
    await this.open(a.id, [a.id]);
    this.renameComposition();
  }

  // Where a new component goes: the visible part of the frame's inside (else the view).
  addArea() {
    const vis = this.visibleArea(40);
    const f = this.scene.frame;
    const inner = { x: f.x + 40, y: f.y + 50, w: f.w - 80, h: f.h - 80 };
    const x = Math.max(vis.x, inner.x), y = Math.max(vis.y, inner.y);
    const w = Math.min(vis.x + vis.w, inner.x + inner.w) - x, h = Math.min(vis.y + vis.h, inner.y + inner.h) - y;
    return w > 200 && h > 120 ? { x, y, w, h } : vis;
  }

  async addComponent(at = null) {
    if (!this.view) return;
    const pos = at ? { x: G.snap(at.x - 80), y: G.snap(at.y - 45) }
      : G.freeSpot(this.scene.blocks.map(b => b.box), 160, 90, this.addArea());
    const r = await this.run(() => this.studio.api("POST", "/api/arch/component", { composition: this.compId, layout: pos }),
                             { selectKeys: c => [ck(c.id)], ok: c => `Added component ${c.name}` });
    if (r) { this.scrollIntoView(ck(r.id)); this.rename(ck(r.id), r.id); }
  }

  async addPort(kind, dir, compIds = null) {
    const ids = compIds || this.selectedComponents().map(c => c.id);
    if (!ids.length) { this.toast("Select a component first (use Boundary for a port on the frame)", "warning"); return; }
    const made = [];
    const r = await this.run(async () => {
      for (const id of ids) made.push({ ctx: id, p: await this.studio.api("POST", "/api/arch/port", { owner: id, kind, direction: dir }) });
      return made;
    }, { selectKeys: () => made.map(x => pk(x.ctx, x.p.id)), ok: () => `Added port ${made.map(x => x.p.name).join(", ")}` });
    if (r && made.length === 1) this.rename(pk(made[0].ctx, made[0].p.id), made[0].p.id);
  }

  async addBoundaryPort(kind, dir, at = null) {
    if (!this.view) return;
    const body = { owner: this.compId, kind, direction: dir };
    if (at && this.scene) Object.assign(body, G.nearestSide(this.scene.frame, at));
    const r = await this.run(() => this.studio.api("POST", "/api/arch/port", body),
                             { selectKeys: p => [pk(null, p.id)], ok: p => `Added boundary port ${p.name}` });
    if (r) this.rename(pk(null, r.id), r.id);
  }

  nameProblem(key, name) {
    if (/::|[.\t\r\n]/.test(name)) return `A name may not contain '::', '.', tabs or line breaks: ${name}`;
    const { type, id } = parseKey(key);
    const v = this.view;
    let taken, owner = v.composition.name;
    if (type === "port") {
      const pt = this.scene.ports.get(key);
      if (pt?.owner) { taken = pt.owner.c.ports; owner = pt.owner.c.name; }
      else taken = [...v.boundary_ports, ...v.components, ...v.connectors];
    } else {
      taken = [...v.components, ...v.connectors, ...v.boundary_ports];
    }
    return taken.some(x => x.id !== id && x.name === name) ? `${owner} already has a member named '${name}'` : null;
  }

  // `created` = the id of an element just added: naming it joins its creation's undo step.
  rename(key, created = null) {
    if (!key || !this.scene) return;
    const el = this.dom.get(key);
    if (!el) return;
    const { type } = parseKey(key);
    if (type === "component") {
      const b = this.scene.blockByKey.get(key);
      this.inline.edit(el.querySelector('[data-role="name"]'), b.c.name, n => this.commitRename(key, n, created),
                       { minWidth: Math.max(110, b.box.w * this.vp.zoom - 10) });
    } else if (type === "port") {
      const pt = this.scene.ports.get(key);
      this.inline.edit(el.querySelector('[data-role="port-label"]') || el, pt.p.name, n => this.commitRename(key, n, created));
    } else {
      const k = this.scene.connByKey.get(key);
      if (!k) return;
      this.inline.edit(this.labels.get(key)?.querySelector("text") || el.querySelector(".arch-conn-line"), k.c.name,
                       n => this.commitRename(key, n, created));
    }
  }

  commitRename(key, name, created = null) {
    name = String(name || "").trim();
    if (!name || !this.view) return null;
    const bad = this.nameProblem(key, name);
    if (bad) { this.toast(bad, "error"); this.updateChrome(); return null; }
    const { type, id } = parseKey(key);
    const url = type === "component" ? `/api/arch/component/${id}` : type === "port" ? `/api/arch/port/${id}` : `/api/arch/connector/${id}`;
    return this.run(() => this.studio.api("PATCH", url, { name }, { undoMerge: created }), { ok: `Renamed to ${name}` });
  }

  renameComposition(created = null) {
    if (!this.view) return;
    const t = this.L.frame.querySelector('[data-role="frame-name"]');
    if (t) this.inline.edit(t, this.view.composition.name, n => this.commitCompositionName(n, created), { minWidth: 160 });
  }

  commitCompositionName(name, created = null) {
    name = String(name || "").trim();
    const c = this.view?.composition;
    if (!c || !name || name === c.name) return null;
    if (/::|[.\t\r\n]/.test(name)) { this.toast(`A name may not contain '::', '.', tabs or line breaks: ${name}`, "error"); return null; }
    return this.run(() => (c.kind === "PartUsage"
      ? this.studio.api("PATCH", `/api/arch/component/${c.id}`, { name }, { undoMerge: created })
      : this.studio.api("PATCH", `/api/element/${c.id}`, { props: { name } }, { undoMerge: created })), { ok: `Renamed to ${name}` });
  }

  updatePort(id, body) {
    return this.run(() => this.studio.api("PATCH", `/api/arch/port/${id}`, body), { ok: "Updated port" });
  }

  movePortSide(key, side) {
    if (!key) return null;
    return this.run(() => this.studio.api("POST", "/api/arch/layout", { items: [{ id: parseKey(key).id, side, offset: 0.5 }] }));
  }

  resetRoute(id) {
    if (!id) return null;
    return this.run(() => this.studio.api("POST", "/api/arch/layout", { items: [{ id, points: null }] }), { ok: "Route reset" });
  }

  resetSize(id) {
    const b = this.scene?.blockByKey.get(ck(id));
    if (!b) return null;
    return this.run(() => this.studio.api("POST", "/api/arch/layout", { items: [{ id, x: b.box.x, y: b.box.y, w: null, h: null }] }));
  }

  async deleteSelection() {
    if (!this.sel.size) return;
    const ids = [...new Set([...this.sel].map(k => parseKey(k).id))].filter(id => this.studio.state.treeIndex.has(id));
    const n = ids.length;
    this.setSel([]);
    if (!n) return;
    await this.run(() => this.studio.api("POST", "/api/arch/delete", { ids }), { ok: `Deleted ${n} element(s)` });
  }

  selectAll() {
    if (!this.scene) return;
    this.setSel(this.scene.blocks.filter(b => !(this.filter?.hide && !this.filter.ids.has(b.c.id))).map(b => b.key), { emit: true });
  }

  copy() {
    const comps = this.selectedComponents();
    if (!comps.length) { this.toast("Select components to copy", "warning"); return; }
    copyComponents(comps.map(c => c.id), comps.map(c => c.name));
    this.toast(`Copied ${comps.map(c => c.name).join(", ")}`, "info", 2000);
    this.updateChrome();
  }

  async paste(target = null) {
    const into = target || this.compId;
    const ids = clipboard.ids.filter(id => this.studio.state.treeIndex.has(id));
    if (!ids.length) { this.toast("Nothing to paste: copy components first", "warning"); return; }
    if (ids.some(id => this.path.includes(id) || id === into)) { this.toast("Cannot paste a component into itself", "error"); return; }
    const here = into === this.compId;
    await this.run(() => this.studio.api("POST", "/api/arch/duplicate", { ids, target: into }),
                   { selectKeys: r => (here ? r.components.map(c => ck(c.id)) : [ck(into)]),
                     ok: r => `Pasted ${r.components.map(c => c.name).join(", ")}` });
  }

  async duplicate() {
    const comps = this.selectedComponents();
    if (!comps.length) { this.toast("Select components to duplicate", "warning"); return; }
    await this.run(() => this.studio.api("POST", "/api/arch/duplicate", { ids: comps.map(c => c.id) }),
                   { selectKeys: r => r.components.map(c => ck(c.id)), ok: r => `Duplicated as ${r.components.map(c => c.name).join(", ")}` });
  }

  async group() {
    const comps = this.selectedComponents();
    if (!comps.length) { this.toast("Select the components to group", "warning"); return; }
    const g = await this.run(() => this.studio.api("POST", "/api/arch/group", { composition: this.compId, component_ids: comps.map(c => c.id) }),
                             { selectKeys: r => [ck(r.id)], ok: r => `Created ${r.name} from ${comps.length} component(s)` });
    if (g) this.rename(ck(g.id), g.id);
  }

  async expand() {
    const [c] = this.selectedComponents();
    if (!c) return;
    await this.run(() => this.studio.api("POST", "/api/arch/expand", { component: c.id }),
                   { selectKeys: r => r.components.map(ck), ok: `Expanded ${c.name}` });
  }

  saveAsReference() {
    const [c] = this.selectedComponents();
    if (!c || c.is_reference) return;
    const base = (c.name || "Component").replace(/^./, ch => ch.toUpperCase());
    openForm(this.studio, `Save ${c.name} as reference`, `
      <label class="block text-sm">Definition name
        <input class="input" name="name" value="${esc(base)}" autocomplete="off" /></label>
      <p class="text-xs text-slate-500">The ports and internals of ${esc(c.name)} move into a new part definition that other
        components can reference; ${esc(c.name)} becomes a reference to it.</p>`, async (v) => {
      await this.run(() => this.studio.api("POST", "/api/arch/save-as-reference", { component: c.id, name: v.name?.trim() || undefined }),
                     { selectKeys: () => [ck(c.id)], ok: r => `Saved ${c.name} as reference ${r.definition.name}` });
    });
  }

  async inlineComponent() {
    const [c] = this.selectedComponents();
    if (!c?.is_reference) return;
    await this.run(() => this.studio.api("POST", "/api/arch/inline", { component: c.id }),
                   { selectKeys: () => [ck(c.id)], ok: `${c.name} is now an inline component` });
  }

  async arrange() {
    if (!this.view) return;
    const r = await this.run(() => this.studio.api("POST", "/api/arch/auto-layout", { composition: this.compId }),
                             { ok: `Arranged ${this.view.composition.name}` });
    if (r) this.fit();
  }

  showProperties(id = null) {
    const target = id || (this.primary ? parseKey(this.primary).id : this.compId);
    if (!target) return;
    this.studio.selectElement(target).then(() => this.studio.switchTab("properties")).catch(() => {});
  }

  toggleDock(on = !this.dockOpen) {
    this.dockOpen = on;
    store.set({ dock: on });
    this.updateChrome();
    requestAnimationFrame(() => this.applyViewport());
  }

  dockActions() {
    return {
      rename: (key, name) => this.commitRename(key, name),
      renameComposition: name => this.commitCompositionName(name),
      setDefinition: (id, def) => this.run(() => this.studio.api("PATCH", `/api/arch/component/${id}`, { definition: def }),
                                           { ok: def ? "Component now references the definition" : "Component is now inline" }),
      updatePort: (id, body) => this.updatePort(id, body),
      movePort: (key, side) => this.movePortSide(key, side),
      addPort: (kind, dir) => {
        const c = this.primaryInfo();
        if (c?.type === "component") this.addPort(kind, dir, [c.c.id]);
      },
      deleteIds: ids => this.run(() => this.studio.api("POST", "/api/arch/delete", { ids }), { ok: "Deleted" }),
      deleteSelection: () => this.deleteSelection(),
      resetSize: id => this.resetSize(id),
      resetRoute: id => this.resetRoute(id),
      open: id => this.openComponent(id),
      showProperties: id => this.showProperties(id),
      arrange: () => this.arrange(),
      fit: () => this.fit(),
      group: () => this.group(),
      duplicate: () => this.duplicate(),
      toggleDock: on => this.toggleDock(on),
    };
  }
}
