// Allocation Editor (System Composer style).
//
// Tab "Allocation": toolstrip (set/scenario commands, element-kind chips, filters, analysis),
// left browser of allocation sets and scenarios, centre allocation matrix (rows = source
// elements, columns = target elements; click a cell to allocate/deallocate, Alt+click to select,
// arrow keys + Space/Enter), right panel with Properties / Coverage / Chain.
// Also adds an "Allocations" inspector section for allocatable elements, allocations, sets and
// scenarios. Backend: /api/allocation/* (webapp/routes/allocation.py).
//
// Cross-feature events: selecting a matrix row/column emits
//   highlight {ids: [allocated counterparts], color: "#8b5cf6", reason: "allocation"}
// and "Show in architecture" emits navigate {id}.

const ACCENT = "#8b5cf6";
const CATS = [["component", "Components", "C"], ["port", "Ports", "P"],
              ["connector", "Connectors", "↔"], ["function", "Functions", "ƒ"]];
const CAT_ICON = Object.fromEntries(CATS.map(([k, , i]) => [k, i]));
const LS_SCENARIO = "allocation.scenario";

const STYLE = `
#tab-allocation { background:#f8fafc; }
.alloc-toolstrip { display:flex; flex-wrap:wrap; align-items:stretch; background:#fff; border-bottom:1px solid #e2e8f0; padding:.2rem .4rem 0; }
.alloc-tsg { display:flex; flex-direction:column; justify-content:space-between; padding:0 .55rem; border-right:1px solid #e2e8f0; }
.alloc-tsg:last-child { border-right:0; }
.alloc-tsg-body { display:flex; align-items:center; gap:.2rem; flex-wrap:wrap; min-height:2.7rem; }
.alloc-tsg-label { font-size:.58rem; letter-spacing:.09em; color:#94a3b8; text-align:center; text-transform:uppercase; padding:.05rem 0 .2rem; }
.alloc-tsb { display:flex; flex-direction:column; align-items:center; gap:.05rem; padding:.15rem .3rem; border-radius:.25rem; font-size:.68rem; color:#334155; border:1px solid transparent; min-width:3.1rem; cursor:pointer; white-space:nowrap; }
.alloc-tsb:hover:not([disabled]) { background:#f1f5f9; border-color:#e2e8f0; }
.alloc-tsb:focus-visible { outline:2px solid #2563eb; }
.alloc-tsb[disabled] { opacity:.38; cursor:default; }
.alloc-tsb .ico { font-size:1rem; line-height:1.15rem; color:#7c3aed; }
.alloc-chiprow { display:flex; align-items:center; gap:.2rem; font-size:.65rem; color:#64748b; }
.alloc-chiprow > span:first-child { width:3.1rem; text-align:right; margin-right:.15rem; }
.alloc-chip { font-size:.65rem; padding:.05rem .4rem; border:1px solid #cbd5e1; border-radius:999px; color:#475569; background:#fff; cursor:pointer; }
.alloc-chip[aria-pressed="true"] { background:#ede9fe; border-color:#c4b5fd; color:#5b21b6; }
.alloc-filters { display:grid; grid-template-columns:auto auto; gap:.15rem .3rem; align-items:center; font-size:.65rem; color:#64748b; }
.alloc-filters select { border:1px solid #cbd5e1; border-radius:.25rem; padding:.05rem .2rem; font-size:.7rem; width:8.6rem; background:#fff; }
.alloc-fbar { display:flex; align-items:center; gap:.35rem; padding:.25rem .7rem; border-bottom:1px solid #e2e8f0; background:#f8fafc; color:#94a3b8; }
.alloc-fbar input { border:1px solid #cbd5e1; border-radius:.25rem; padding:.1rem .4rem; font-size:.72rem; width:10rem; background:#fff; color:#0f172a; }
.alloc-fbar input:focus { outline:none; border-color:#8b5cf6; box-shadow:0 0 0 2px rgb(139 92 246 / .2); }
.alloc-body { flex:1; display:flex; min-height:0; }
.alloc-browser { width:13.5rem; flex:none; background:#fff; border-right:1px solid #e2e8f0; display:flex; flex-direction:column; min-height:0; }
.alloc-center { flex:1; min-width:0; display:flex; flex-direction:column; }
.alloc-side { width:19.5rem; flex:none; background:#fff; border-left:1px solid #e2e8f0; display:flex; flex-direction:column; min-height:0; }
.alloc-title { font-size:.62rem; text-transform:uppercase; letter-spacing:.07em; color:#64748b; font-weight:600; padding:.4rem .6rem; border-bottom:1px solid #e2e8f0; background:#f8fafc; }
.alloc-tree { list-style:none; margin:0; padding:.25rem 0; overflow:auto; flex:1; font-size:.8rem; }
.alloc-tree .node { display:flex; align-items:center; gap:.3rem; padding:.18rem .5rem; cursor:pointer; border-radius:.25rem; margin:0 .25rem; white-space:nowrap; }
.alloc-tree .node:hover { background:#f1f5f9; }
.alloc-tree .node:focus-visible { outline:2px solid #2563eb; }
.alloc-tree .node.sel { background:#ede9fe; color:#5b21b6; }
.alloc-tree .node.current .nm { font-weight:600; }
.alloc-tree .scen { padding-left:1.5rem; }
.alloc-tree .meta { margin-left:auto; font-size:.62rem; color:#94a3b8; }
.alloc-tree .glyph { color:#7c3aed; width:1rem; text-align:center; }
.alloc-mhead { display:flex; align-items:center; gap:.5rem; padding:.35rem .7rem; border-bottom:1px solid #e2e8f0; background:#fff; font-size:.78rem; }
.alloc-mhead .crumb { font-weight:600; color:#1e293b; }
.alloc-mhead .stat { color:#64748b; font-size:.7rem; }
.alloc-mwrap { flex:1; overflow:auto; position:relative; }
.alloc-legend { font-size:.65rem; color:#94a3b8; padding:.25rem .7rem; border-top:1px solid #e2e8f0; background:#fff; }
.alloc-empty { margin:3rem auto; max-width:28rem; text-align:center; color:#64748b; font-size:.85rem; }
.alloc-matrix { border-collapse:separate; border-spacing:0; font-size:.74rem; background:#fff; }
.alloc-matrix th, .alloc-matrix td { border-right:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; }
.alloc-matrix thead th { position:sticky; top:0; background:#f8fafc; z-index:2; }
.alloc-matrix .row-head { position:sticky; left:0; background:#fff; z-index:1; text-align:left; white-space:nowrap; font-weight:400; min-width:12rem; max-width:20rem; overflow:hidden; text-overflow:ellipsis; padding:.15rem .5rem .15rem 0; cursor:pointer; }
.alloc-matrix thead .corner { left:0; z-index:3; vertical-align:bottom; text-align:left; font-size:.62rem; color:#94a3b8; padding:.3rem .5rem; }
.alloc-matrix .col-head { vertical-align:bottom; height:8.5rem; width:1.9rem; min-width:1.9rem; padding:.3rem 0; cursor:pointer; font-weight:400; }
.alloc-matrix .col-head .vtext { writing-mode:vertical-rl; transform:rotate(180deg); white-space:nowrap; margin:0 auto; max-height:7rem; overflow:hidden; text-overflow:ellipsis; }
.alloc-matrix .col-head .ind { color:#c4b5fd; letter-spacing:-.1em; }
.alloc-matrix .col-head .alloc-cat { margin:.2rem 0 0; }
.alloc-matrix td.cell { width:1.9rem; min-width:1.9rem; height:1.55rem; text-align:center; cursor:pointer; }
.alloc-matrix td.cell:hover { background:#f5f3ff; }
.alloc-matrix td.cell:focus { outline:2px solid #2563eb; outline-offset:-2px; }
.alloc-matrix td.cell .dot { display:inline-block; width:.8rem; height:.8rem; border-radius:.2rem; background:${ACCENT}; vertical-align:middle; }
.alloc-matrix td.cell.sel { box-shadow:inset 0 0 0 2px #5b21b6; }
.alloc-matrix td.cell.na { background:#f8fafc; cursor:default; }
.alloc-matrix tr.ctx .row-head, .alloc-matrix .col-head.ctx { color:#94a3b8; font-style:italic; }
.alloc-matrix .row-head.sel, .alloc-matrix .col-head.sel { background:#ede9fe; color:#5b21b6; font-weight:600; }
.alloc-matrix .row-head.hl, .alloc-matrix .col-head.hl { background:#f5f3ff; color:#6d28d9; }
.alloc-matrix tr.hlrow td.cell:not(.na), .alloc-matrix td.cell.hlcol:not(.na) { background:#faf5ff; }
.alloc-matrix .count { color:#64748b; text-align:center; min-width:2rem; font-size:.68rem; }
.alloc-matrix tfoot .row-head { font-size:.65rem; color:#64748b; text-transform:uppercase; letter-spacing:.05em; }
.alloc-matrix .twisty { display:inline-block; width:1rem; text-align:center; color:#94a3b8; }
.alloc-cat { display:inline-block; min-width:.95rem; text-align:center; font-size:.58rem; font-weight:700; border-radius:.2rem; margin-right:.3rem; padding:0 .1rem; }
.alloc-cat.component { background:#dbeafe; color:#1d4ed8; }
.alloc-cat.port { background:#cffafe; color:#0e7490; }
.alloc-cat.connector { background:#fef9c3; color:#a16207; }
.alloc-cat.function { background:#dcfce7; color:#15803d; }
.alloc-cat.none { background:#f1f5f9; color:#64748b; }
.alloc-sidetabs { display:flex; border-bottom:1px solid #e2e8f0; background:#f8fafc; }
.alloc-sidetabs button { flex:1; font-size:.72rem; padding:.4rem 0; color:#475569; border-bottom:2px solid transparent; }
.alloc-sidetabs button[aria-selected="true"] { color:#6d28d9; border-bottom-color:${ACCENT}; font-weight:600; background:#fff; }
.alloc-sidebody { flex:1; overflow:auto; padding:.6rem .7rem; font-size:.78rem; }
.alloc-card { border:1px solid #e2e8f0; border-radius:.4rem; margin-bottom:.7rem; }
.alloc-card > h4 { font-size:.62rem; text-transform:uppercase; letter-spacing:.07em; color:#64748b; font-weight:600; padding:.35rem .55rem; border-bottom:1px solid #e2e8f0; background:#f8fafc; border-radius:.4rem .4rem 0 0; }
.alloc-card > .in { padding:.5rem .55rem; display:flex; flex-direction:column; gap:.35rem; }
.alloc-kv { display:grid; grid-template-columns:5.2rem 1fr; gap:.2rem .4rem; align-items:center; }
.alloc-kv > span:nth-child(odd) { color:#64748b; font-size:.7rem; }
.alloc-link { color:#4338ca; text-decoration:underline; text-underline-offset:2px; cursor:pointer; text-align:left; }
.alloc-mini { font-size:.68rem; padding:.1rem .45rem; border:1px solid #cbd5e1; border-radius:.25rem; background:#fff; color:#334155; }
.alloc-mini:hover { background:#f1f5f9; }
.alloc-mini.danger { color:#b91c1c; border-color:#fecaca; }
.alloc-stereo { display:inline-block; font-size:.68rem; color:#6d28d9; background:#f5f3ff; border:1px solid #ddd6fe; border-radius:.25rem; padding:0 .3rem; margin:0 .2rem .2rem 0; }
.alloc-bar { height:.45rem; background:#f1f5f9; border-radius:999px; overflow:hidden; }
.alloc-bar > div { height:100%; background:${ACCENT}; }
.alloc-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.15rem; }
.alloc-list li { display:flex; align-items:center; gap:.3rem; }
.alloc-chain .mermaid svg { max-width:100%; height:auto; }
.alloc-muted { color:#94a3b8; font-size:.72rem; }
#modal-root .alloc-danger { background:#dc2626; }
`;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m]));
const enc = (s) => encodeURIComponent(s);

function lsGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function lsSet(key, value) { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } }

export default function install(studio) {
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);

  const st = {
    sets: [], archs: [],
    scenarioId: null,
    browserSel: null,                     // {type: "set"|"scenario", id}
    rowKinds: new Set(["component", "function"]),
    colKinds: new Set(["component"]),
    show: "all", colShow: "all", q: "", colQ: "",
    matrix: null,
    selAlloc: null,                       // allocation id
    selAxis: null,                        // {axis: "row"|"col", id}
    focus: { r: 0, c: 0 },
    collapsed: new Set(),
    sideTab: "properties",
    visible: false, dirty: true,
    pendingFocus: null,                   // element id to select once the matrix loads
    queue: Promise.resolve(),
  };
  const els = {};

  /* ---------------- data loading ---------------- */

  let loading = null, again = false;
  function reload() {
    if (loading) { again = true; return loading; }
    loading = (async () => {
      do { again = false; await doReload(); } while (again);
    })().catch((e) => studio.log(`Allocation editor: ${e.message || e}`, "error"))
      .finally(() => { loading = null; });
    return loading;
  }

  function allScenarios() {
    return st.sets.flatMap((s) => s.scenarios.map((sc) => ({ ...sc, set: s })));
  }
  function currentSet() {
    return st.sets.find((s) => s.scenarios.some((sc) => sc.id === st.scenarioId)) || null;
  }
  function currentScenario() {
    return allScenarios().find((sc) => sc.id === st.scenarioId) || null;
  }

  function matrixQuery() {
    const p = new URLSearchParams();
    p.set("rows", [...st.rowKinds].join(",") || "component");
    p.set("cols", [...st.colKinds].join(",") || "component");
    p.set("show", st.show); p.set("col_show", st.colShow);
    if (st.q) p.set("q", st.q);
    if (st.colQ) p.set("col_q", st.colQ);
    return p.toString();
  }

  async function doReload() {
    const [sets, archs] = await Promise.all([
      studio.api("GET", "/api/allocation/sets"),
      studio.api("GET", "/api/allocation/architectures"),
    ]);
    st.sets = sets; st.archs = archs;
    const scs = allScenarios();
    if (!scs.some((sc) => sc.id === st.scenarioId)) {
      const remembered = lsGet(LS_SCENARIO);
      st.scenarioId = (scs.find((sc) => sc.id === remembered) || scs[0] || {}).id || null;
    }
    const sel = st.browserSel;
    const selOk = sel && (sel.type === "set" ? sets.some((s) => s.id === sel.id) : scs.some((sc) => sc.id === sel.id));
    if (!selOk) st.browserSel = st.scenarioId ? { type: "scenario", id: st.scenarioId } : null;
    if (st.scenarioId) {
      lsSet(LS_SCENARIO, st.scenarioId);
      st.matrix = await studio.api("GET", `/api/allocation/scenarios/${enc(st.scenarioId)}/matrix?${matrixQuery()}`);
    } else {
      st.matrix = null;
    }
    if (st.selAlloc && !st.matrix?.allocations.some((a) => a.id === st.selAlloc)) st.selAlloc = null;
    if (st.pendingFocus && st.matrix) {
      const id = st.pendingFocus; st.pendingFocus = null;
      const axis = st.matrix.rows.some((r) => r.id === id) ? "row" : st.matrix.columns.some((c) => c.id === id) ? "col" : null;
      if (axis) st.selAxis = { axis, id };
    }
    st.dirty = false;
    renderAll();
  }

  async function afterModelEdit() {
    await studio.refreshTree();           // emits model-changed, which reloads this editor
    await (loading || reload());
  }

  /* ---------------- layout ---------------- */

  function tsButton(act, icon, label, title) {
    return `<button type="button" class="alloc-tsb" data-alloc-act="${act}" title="${esc(title)}"><span class="ico">${icon}</span>${esc(label)}</button>`;
  }

  function chipRow(axis, label) {
    const kinds = axis === "row" ? st.rowKinds : st.colKinds;
    return `<div class="alloc-chiprow"><span>${label}</span>${CATS.map(([k, name]) =>
      `<button type="button" class="alloc-chip" data-alloc-chip="${axis}:${k}" aria-pressed="${kinds.has(k)}" title="${axis === "row" ? "Rows" : "Columns"}: ${name}">${name}</button>`).join("")}</div>`;
  }

  function mount(pane) {
    pane.innerHTML = `
      <div class="alloc-toolstrip" role="toolbar" aria-label="Allocation toolstrip">
        <div class="alloc-tsg"><div class="alloc-tsg-body">
          ${tsButton("new-set", "▦", "New Set", "Create an allocation set between two architectures")}
          ${tsButton("new-scenario", "＋", "New Scenario", "Add a scenario to the current allocation set")}
          ${tsButton("duplicate", "⧉", "Duplicate", "Duplicate the current scenario with its allocations")}
          ${tsButton("rename", "✎", "Rename", "Rename the selected set or scenario (F2)")}
          ${tsButton("delete", "✕", "Delete", "Delete the selected set or scenario (Delete)")}
        </div><div class="alloc-tsg-label">Allocation set</div></div>
        <div class="alloc-tsg"><div class="alloc-tsg-body" style="flex-direction:column;align-items:flex-start;justify-content:center;gap:.15rem">
          ${chipRow("row", "Rows")}${chipRow("col", "Columns")}
        </div><div class="alloc-tsg-label">Element kinds</div></div>
        <div class="alloc-tsg"><div class="alloc-tsg-body"><div class="alloc-filters">
          <label for="alloc-show">Rows</label>
          <select id="alloc-show" title="Show only allocated or unallocated source elements">
            <option value="all">All sources</option><option value="allocated">Allocated only</option><option value="unallocated">Unallocated only</option>
          </select>
          <label for="alloc-col-show">Columns</label>
          <select id="alloc-col-show" title="Show only allocated or unallocated target elements">
            <option value="all">All targets</option><option value="allocated">Allocated only</option><option value="unallocated">Unallocated only</option>
          </select>
        </div></div><div class="alloc-tsg-label">Show</div></div>
        <div class="alloc-tsg"><div class="alloc-tsg-body">
          ${tsButton("coverage", "◔", "Coverage", "Coverage of the current scenario")}
          ${tsButton("chain", "⇶", "Chain", "Allocation chain of the selected element across sets")}
          ${tsButton("show-arch", "⌖", "Show", "Show the selected element in the architecture")}
          ${tsButton("refresh", "↻", "Refresh", "Reload the allocation editor")}
        </div><div class="alloc-tsg-label">Analyze</div></div>
      </div>
      <div class="alloc-body">
        <aside class="alloc-browser" aria-label="Allocation sets">
          <div class="alloc-title">Allocation sets</div>
          <ul class="alloc-tree" id="alloc-browser" role="tree"></ul>
        </aside>
        <section class="alloc-center">
          <div class="alloc-mhead" id="alloc-mhead"></div>
          <div class="alloc-fbar" role="search">
            <span aria-hidden="true">⌕</span>
            <input id="alloc-q" type="search" placeholder="Filter rows…" autocomplete="off" aria-label="Filter rows by name" />
            <input id="alloc-col-q" type="search" placeholder="Filter columns…" autocomplete="off" aria-label="Filter columns by name" />
            <button type="button" class="alloc-mini" data-alloc-do="clear-filters" title="Reset kinds, show and text filters">Clear filters</button>
          </div>
          <div class="alloc-mwrap" id="alloc-mwrap"></div>
          <div class="alloc-legend">Click a cell to allocate / deallocate · Alt+click selects an allocation ·
            arrow keys move, Space toggles · click a row or column header to highlight its allocations</div>
        </section>
        <aside class="alloc-side" aria-label="Allocation properties">
          <div class="alloc-sidetabs" role="tablist">
            <button type="button" role="tab" data-alloc-side="properties">Properties</button>
            <button type="button" role="tab" data-alloc-side="coverage">Coverage</button>
            <button type="button" role="tab" data-alloc-side="chain">Chain</button>
          </div>
          <div class="alloc-sidebody" id="alloc-side"></div>
        </aside>
      </div>`;
    els.pane = pane;
    els.browser = pane.querySelector("#alloc-browser");
    els.mhead = pane.querySelector("#alloc-mhead");
    els.mwrap = pane.querySelector("#alloc-mwrap");
    els.side = pane.querySelector("#alloc-side");
    wire(pane);
  }

  /* ---------------- rendering ---------------- */

  function renderAll() {
    renderToolstrip();
    renderBrowser();
    renderMatrix();
    renderSide();
  }

  function renderToolstrip() {
    const p = els.pane; if (!p) return;
    const sel = st.browserSel;
    const has = (act, on) => { p.querySelector(`[data-alloc-act="${act}"]`).disabled = !on; };
    has("new-scenario", !!currentSet());
    has("duplicate", !!currentScenario());
    has("rename", !!sel);
    has("delete", !!sel);
    has("chain", !!focusElementId());
    has("show-arch", !!focusElementId());
    has("coverage", !!currentScenario());
    p.querySelectorAll("[data-alloc-chip]").forEach((b) => {
      const [axis, k] = b.dataset.allocChip.split(":");
      b.setAttribute("aria-pressed", String((axis === "row" ? st.rowKinds : st.colKinds).has(k)));
    });
    p.querySelector("#alloc-show").value = st.show;
    p.querySelector("#alloc-col-show").value = st.colShow;
    p.querySelectorAll("[data-alloc-side]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.allocSide === st.sideTab)));
  }

  function renderBrowser() {
    if (!els.browser) return;
    if (!st.sets.length) {
      els.browser.innerHTML = `<li class="alloc-muted" style="padding:.6rem">No allocation sets.</li>`;
      return;
    }
    const sel = st.browserSel || {};
    els.browser.innerHTML = st.sets.map((s) => `
      <li role="treeitem" aria-expanded="true">
        <div class="node${sel.type === "set" && sel.id === s.id ? " sel" : ""}" tabindex="0" data-alloc-node="${s.id}" data-type="set"
             title="${esc(s.qualified_name)}: ${esc(s.source_architecture?.name || "∅")} → ${esc(s.target_architecture?.name || "∅")}">
          <span class="glyph">▦</span><span class="nm">${esc(s.name)}</span>
          <span class="meta">${esc(s.source_architecture?.name || "∅")} → ${esc(s.target_architecture?.name || "∅")}</span>
        </div>
        <ul role="group" style="list-style:none;margin:0;padding:0">${s.scenarios.map((sc) => `
          <li role="treeitem"><div class="node scen${sel.type === "scenario" && sel.id === sc.id ? " sel" : ""}${sc.id === st.scenarioId ? " current" : ""}"
               tabindex="0" data-alloc-node="${sc.id}" data-type="scenario" title="${esc(sc.qualified_name)}">
            <span class="glyph">◇</span><span class="nm">${esc(sc.name)}</span><span class="meta">${sc.allocation_count}</span>
          </div></li>`).join("")}
        </ul>
      </li>`).join("");
  }

  function catBadge(row) {
    const c = row.category || "none";
    return `<span class="alloc-cat ${c}" title="${esc(row.kind)}">${CAT_ICON[c] || "▤"}</span>`;
  }

  function visibleRows(rows) {
    if (!st.collapsed.size) return rows;
    const byKey = new Map(rows.map((r) => [r.key, r]));
    return rows.filter((r) => {
      let p = r.parent_key;
      while (p) {
        if (st.collapsed.has(p)) return false;
        p = byKey.get(p)?.parent_key;
      }
      return true;
    });
  }

  function axisCounterparts(axis, id) {
    const m = st.matrix; if (!m) return [];
    return axis === "row"
      ? m.allocations.filter((a) => a.source_id === id).map((a) => a.target_id)
      : m.allocations.filter((a) => a.target_id === id).map((a) => a.source_id);
  }

  function renderMatrix() {
    if (!els.mwrap) return;
    const m = st.matrix;
    const sc = currentScenario();
    if (!st.sets.length) {
      els.mhead.innerHTML = `<span class="crumb">Allocation Editor</span>`;
      els.mwrap.innerHTML = `<div class="alloc-empty"><p class="mb-3">No allocation sets yet.</p>
        <p class="mb-4">An allocation set maps the elements of a source architecture (for example functions or
        logical components) onto a target architecture (for example LRUs and IMA modules).</p>
        <button type="button" class="btn-primary" data-alloc-act="new-set">New allocation set…</button></div>`;
      return;
    }
    if (!m || !sc) { els.mwrap.innerHTML = ""; els.mhead.innerHTML = ""; return; }
    const rows = visibleRows(m.rows);
    const cols = m.columns;
    const allocatedRows = m.rows.filter((r) => !r.context && r.count).length;
    const realRows = m.rows.filter((r) => !r.context).length;
    els.mhead.innerHTML = `<span class="crumb">${esc(sc.set.name)} › ${esc(sc.name)}</span>
      <span class="stat">${esc(m.set.source_architecture?.name || "∅")} → ${esc(m.set.target_architecture?.name || "∅")}</span>
      <span class="flex-1"></span>
      <span class="stat" id="alloc-stats">${m.allocations.length} allocation${m.allocations.length === 1 ? "" : "s"} · ${allocatedRows}/${realRows} rows allocated</span>`;
    if (!m.set.source_architecture || !m.set.target_architecture) {
      els.mwrap.innerHTML = `<div class="alloc-empty">This set has no ${!m.set.source_architecture ? "source" : "target"} architecture
        (it was deleted). Choose one in the Properties panel.</div>`;
      return;
    }
    if (!rows.length || !cols.length) {
      els.mwrap.innerHTML = `<div class="alloc-empty">No ${!rows.length ? "source" : "target"} elements match the current
        element kinds and filters.</div>`;
      return;
    }
    const on = new Map(m.allocations.map((a) => [`${a.source_id}|${a.target_id}`, a]));
    const sel = st.selAxis;
    const hlIds = new Set(sel ? axisCounterparts(sel.axis, sel.id) : []);
    const fr = Math.min(st.focus.r, rows.length - 1), fc = Math.min(st.focus.c, cols.length - 1);
    const head = cols.map((c) => {
      const cls = ["col-head", c.context ? "ctx" : "", sel?.axis === "col" && sel.id === c.id ? "sel" : "",
                   sel?.axis === "row" && hlIds.has(c.id) ? "hl" : ""].join(" ");
      const indent = c.depth ? `<span class="ind">${"··".repeat(c.depth)} </span>` : "";
      return `<th class="${cls}" data-axis="col" data-id="${c.id}" scope="col" title="${esc(c.qualified_name)} (${esc(c.kind)})">
        <div class="vtext">${indent}<span class="nm">${esc(c.name)}</span></div>${catBadge(c)}</th>`;
    }).join("");
    const body = rows.map((r, i) => {
      const rowSel = sel?.axis === "row" && sel.id === r.id;
      const rowHl = sel?.axis === "col" && hlIds.has(r.id);
      const twisty = r.has_children
        ? `<span class="twisty" data-twisty="${esc(r.key)}" role="button" aria-label="Expand or collapse">${st.collapsed.has(r.key) ? "▸" : "▾"}</span>`
        : `<span class="twisty"></span>`;
      const cells = cols.map((c, j) => {
        const a = on.get(`${r.id}|${c.id}`);
        const na = r.context || c.context;
        const cls = ["cell", a ? "on" : "", na ? "na" : "", a && a.id === st.selAlloc ? "sel" : "",
                     sel?.axis === "col" && sel.id === c.id ? "hlcol" : ""].join(" ");
        const title = na ? "" : `${r.name} → ${c.name}: ${a ? "allocated (click to deallocate)" : "click to allocate"}`;
        return `<td class="${cls}" role="gridcell" aria-selected="${!!a}" data-r="${i}" data-c="${j}" data-src="${r.id}" data-tgt="${c.id}"${a ? ` data-alloc="${a.id}"` : ""}
          tabindex="${i === fr && j === fc ? 0 : -1}" title="${esc(title)}">${a ? `<span class="dot"></span>` : ""}</td>`;
      }).join("");
      return `<tr class="${r.context ? "ctx" : ""}${rowSel ? " hlrow" : ""}" data-key="${esc(r.key)}">
        <th class="row-head${rowSel ? " sel" : ""}${rowHl ? " hl" : ""}" data-axis="row" data-id="${r.id}" scope="row"
            title="${esc(r.qualified_name)} (${esc(r.kind)})" style="padding-left:${0.3 + r.depth * 0.9}rem">${twisty}${catBadge(r)}<span class="nm">${esc(r.name)}</span></th>
        ${cells}<td class="count">${r.context ? "" : r.count}</td></tr>`;
    }).join("");
    const foot = cols.map((c) => `<td class="count">${c.context ? "" : c.count}</td>`).join("");
    const scrollTop = els.mwrap.scrollTop, scrollLeft = els.mwrap.scrollLeft;
    els.mwrap.innerHTML = `<table class="alloc-matrix" role="grid" aria-label="Allocation matrix" id="alloc-matrix">
      <thead><tr><th class="corner row-head">Sources ▾ / Targets ▸</th>${head}<th class="count" title="Allocations per source">Σ</th></tr></thead>
      <tbody>${body}</tbody>
      <tfoot><tr><th class="row-head">Per target</th>${foot}<td class="count">${m.allocations.length}</td></tr></tfoot></table>`;
    els.mwrap.scrollTop = scrollTop; els.mwrap.scrollLeft = scrollLeft;
  }

  function focusElementId() {
    if (st.selAxis) return st.selAxis.id;
    const a = selectedAllocation();
    return a ? a.source_id : null;
  }
  function selectedAllocation() {
    return st.matrix?.allocations.find((a) => a.id === st.selAlloc) || null;
  }
  function findAxisRow(id) {
    const m = st.matrix; if (!m) return null;
    return m.rows.find((r) => r.id === id) || m.columns.find((c) => c.id === id) || null;
  }

  function renderSide() {
    if (!els.side) return;
    const active = document.activeElement;
    if (active && els.side.contains(active) && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)) return;
    renderToolstrip();
    if (st.sideTab === "coverage") return renderCoverage();
    if (st.sideTab === "chain") return renderChain();
    renderProperties();
  }

  function archOptions(selectedId) {
    const opts = st.archs.map((a) => `<option value="${a.id}"${a.id === selectedId ? " selected" : ""}>${esc(a.qualified_name)} (${esc(a.kind)})</option>`);
    if (!selectedId) opts.unshift(`<option value="" selected>— choose —</option>`);
    return opts.join("");
  }

  function elementLink(ref) {
    if (!ref) return `<span class="alloc-muted">∅</span>`;
    return `<button type="button" class="alloc-link" data-alloc-goto="${ref.id}" title="${esc(ref.qualified_name)}">${esc(ref.name)}</button>
            <span class="alloc-muted">${esc(ref.kind)}</span>`;
  }

  function renderProperties() {
    const parts = [];
    const a = selectedAllocation();
    if (a) {
      parts.push(`<section class="alloc-card" data-alloc-card="allocation"><h4>Allocation</h4><div class="in">
        <div class="alloc-kv"><span>Source</span><span>${elementLink(a.source)}</span>
          <span>Target</span><span>${elementLink(a.target)}</span>
          <span>Scenario</span><span>${esc(a.set)} / ${esc(a.scenario)}</span>
          <span>Stereotypes</span><span>${a.stereotypes.length ? a.stereotypes.map((s) =>
            `<span class="alloc-stereo" title="${esc(JSON.stringify(s.values))}">«${esc(s.name)}»</span>`).join("") : `<span class="alloc-muted">none</span>`}</span></div>
        <label class="alloc-muted" for="alloc-a-doc">Description</label>
        <textarea id="alloc-a-doc" class="input" rows="2">${esc(a.doc)}</textarea>
        <div class="flex gap-1 flex-wrap">
          <button type="button" class="alloc-mini" data-alloc-do="save-alloc-doc">Save description</button>
          <button type="button" class="alloc-mini" data-alloc-do="inspect" title="Edit stereotypes and properties in the Properties inspector">Inspector ▸</button>
          <button type="button" class="alloc-mini danger" data-alloc-do="deallocate">Deallocate</button>
        </div></div></section>`);
    }
    const sel = st.selAxis && findAxisRow(st.selAxis.id);
    if (sel) {
      const m = st.matrix;
      const mine = st.selAxis.axis === "row"
        ? m.allocations.filter((x) => x.source_id === sel.id).map((x) => x.target)
        : m.allocations.filter((x) => x.target_id === sel.id).map((x) => x.source);
      parts.push(`<section class="alloc-card" data-alloc-card="element"><h4>${st.selAxis.axis === "row" ? "Source" : "Target"} element</h4><div class="in">
        <div class="alloc-kv"><span>Name</span><span>${elementLink(sel)}</span>
          <span>Kind</span><span>${esc(sel.kind)} · ${esc(sel.category || "")}</span>
          <span>${st.selAxis.axis === "row" ? "Allocated to" : "Allocated from"}</span>
          <span>${mine.length ? mine.map(elementLink).join("<br>") : `<span class="alloc-muted">nothing in this scenario</span>`}</span></div>
        <div class="flex gap-1 flex-wrap">
          <button type="button" class="alloc-mini" data-alloc-do="show-arch">Show in architecture</button>
          <button type="button" class="alloc-mini" data-alloc-do="chain">Allocation chain</button>
        </div></div></section>`);
    }
    const s = currentSet(), sc = currentScenario();
    if (s && sc) {
      parts.push(`<section class="alloc-card" data-alloc-card="scenario"><h4>Scenario</h4><div class="in">
        <div class="alloc-kv"><span>Name</span><input id="alloc-sc-name" class="input" value="${esc(sc.name)}" />
          <span>Allocations</span><span>${sc.allocation_count}</span></div>
        <div><button type="button" class="alloc-mini" data-alloc-do="save-scenario">Apply</button></div></div></section>`);
      parts.push(`<section class="alloc-card" data-alloc-card="set"><h4>Allocation set</h4><div class="in">
        <div class="alloc-kv"><span>Name</span><input id="alloc-set-name" class="input" value="${esc(s.name)}" />
          <span>Source</span><select id="alloc-set-src" class="input">${archOptions(s.source_architecture?.id)}</select>
          <span>Target</span><select id="alloc-set-tgt" class="input">${archOptions(s.target_architecture?.id)}</select></div>
        <label class="alloc-muted" for="alloc-set-desc">Description</label>
        <textarea id="alloc-set-desc" class="input" rows="2">${esc(s.description)}</textarea>
        <label class="flex items-center gap-1"><input type="checkbox" id="alloc-set-cov"${s.require_complete_coverage ? " checked" : ""} />
          Require complete coverage <span class="alloc-muted">(validator warns on unallocated leaf components)</span></label>
        <div><button type="button" class="alloc-mini" data-alloc-do="save-set">Apply</button></div></div></section>`);
    }
    if (!parts.length) parts.push(`<p class="alloc-muted">Create an allocation set to start allocating.</p>`);
    els.side.innerHTML = parts.join("");
  }

  async function renderCoverage() {
    const sc = currentScenario();
    if (!sc) { els.side.innerHTML = `<p class="alloc-muted">No scenario selected.</p>`; return; }
    const leaves = els.side.dataset.leaves !== "0";
    const kinds = [...st.rowKinds].join(",") || "component";
    els.side.innerHTML = `<p class="alloc-muted">Computing coverage…</p>`;
    let cov;
    try {
      cov = await studio.api("GET", `/api/allocation/scenarios/${enc(sc.id)}/coverage?kinds=${enc(kinds)}&leaves=${leaves ? 1 : 0}`);
    } catch { els.side.innerHTML = `<p class="alloc-muted">Coverage unavailable.</p>`; return; }
    if (st.sideTab !== "coverage") return;
    const pct = Math.round(cov.ratio * 100);
    const maxCount = Math.max(1, ...cov.per_target.map((t) => t.count));
    els.side.innerHTML = `
      <section class="alloc-card" data-alloc-card="coverage"><h4>Coverage · ${esc(cov.set)} / ${esc(cov.scenario)}</h4><div class="in">
        <div class="flex items-baseline gap-2"><span class="text-xl font-semibold" id="alloc-cov-pct">${pct}%</span>
          <span class="alloc-muted">${cov.allocated} of ${cov.total} ${leaves ? "leaf " : ""}${esc(cov.kinds.join(" / "))} elements allocated</span></div>
        <div class="alloc-bar"><div style="width:${pct}%"></div></div>
        <label class="flex items-center gap-1 alloc-muted"><input type="checkbox" data-alloc-do="cov-leaves"${leaves ? " checked" : ""} /> leaf elements only</label>
      </div></section>
      <section class="alloc-card"><h4>Unallocated sources (${cov.unallocated.length})</h4><div class="in">
        ${cov.unallocated.length ? `<ul class="alloc-list" id="alloc-cov-unallocated">${cov.unallocated.map((u) =>
          `<li><span class="alloc-cat ${u.category}">${CAT_ICON[u.category]}</span><button type="button" class="alloc-link" data-alloc-pick="${u.id}" title="${esc(u.qualified_name)}">${esc(u.name)}</button></li>`).join("")}</ul>`
          : `<span class="alloc-muted">Every source element is allocated.</span>`}
      </div></section>
      <section class="alloc-card"><h4>Allocations per target</h4><div class="in">
        <ul class="alloc-list">${cov.per_target.map((t) => `<li>
          <button type="button" class="alloc-link" data-alloc-pick="${t.id}" style="width:7.5rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.qualified_name)}">${esc(t.name)}</button>
          <div class="alloc-bar" style="flex:1"><div style="width:${(t.count / maxCount) * 100}%"></div></div>
          <span class="alloc-muted" style="width:1.5rem;text-align:right">${t.count}</span></li>`).join("")}</ul>
      </div></section>`;
  }

  let chainSeq = 0;
  async function renderChain() {
    const id = focusElementId();
    if (!id) {
      els.side.innerHTML = `<p class="alloc-muted">Select a row or column header (or an allocation) to follow its
        allocations through every allocation set, e.g. function → logical component → LRU.</p>`;
      return;
    }
    els.side.innerHTML = `<p class="alloc-muted">Following allocations…</p>`;
    let chain;
    try { chain = await studio.api("GET", `/api/allocation/chain/${enc(id)}?direction=TB`); }
    catch { els.side.innerHTML = `<p class="alloc-muted">Chain unavailable.</p>`; return; }
    if (st.sideTab !== "chain") return;
    const mid = `alloc-chain-${++chainSeq}`;
    els.side.innerHTML = `<section class="alloc-card alloc-chain" data-alloc-card="chain"><h4>Allocation chain · ${esc(chain.focus.name)}</h4><div class="in">
        <div class="mermaid" id="${mid}">${esc(chain.mermaid)}</div>
        ${chain.edges.length ? "" : `<span class="alloc-muted">No allocations involve this element yet.</span>`}
        <ul class="alloc-list" id="alloc-chain-steps">${chain.edges.map((e) => {
          const s = chain.nodes.find((n) => n.id === e.source_id), t = chain.nodes.find((n) => n.id === e.target_id);
          return `<li style="display:block"><button type="button" class="alloc-link" data-alloc-goto="${s.id}">${esc(s.name)}</button> →
            <button type="button" class="alloc-link" data-alloc-goto="${t.id}">${esc(t.name)}</button>
            <div class="alloc-muted">${esc(e.set)} / ${esc(e.scenario)}</div></li>`;
        }).join("")}</ul></div></section>`;
    try { await window.mermaid.run({ nodes: [document.getElementById(mid)] }); }
    catch (e) { studio.log(`Chain diagram: ${e.message || e}`, "warning"); }
  }

  /* ---------------- selection + navigation ---------------- */

  function emitHighlight() {
    if (!st.selAxis) { studio.emit("highlight", null); return; }
    studio.emit("highlight", { ids: axisCounterparts(st.selAxis.axis, st.selAxis.id), color: ACCENT, reason: "allocation" });
  }

  async function selectAxis(axis, id) {
    st.selAxis = { axis, id };
    st.selAlloc = null;
    renderMatrix(); renderSide();
    emitHighlight();
    try { await studio.selectElement(id); } catch { /* logged by studio.api */ }
  }

  async function selectAllocation(id) {
    st.selAlloc = id;
    st.sideTab = st.sideTab === "coverage" ? "properties" : st.sideTab;
    renderMatrix(); renderSide();
    try { await studio.selectElement(id); } catch { /* logged */ }
  }

  function showInArchitecture(id) {
    if (!id) return;
    studio.emit("navigate", { id });
    const tab = ["canvas", "architecture", "arch"].find((t) => document.querySelector(`#tab-bar .tab[data-tab="${t}"]`));
    studio.switchTab(tab || "properties");
  }

  function clearSelection() {
    st.selAxis = null; st.selAlloc = null;
    emitHighlight();
    renderMatrix(); renderSide();
  }

  /* ---------------- commands ---------------- */

  function openModal(title, html, onSubmit, { submitLabel = "OK", danger = false } = {}) {
    studio.modal(esc(title), html, onSubmit);
    const root = document.getElementById("modal-root");
    const form = root.querySelector("#modal-form");
    const submit = root.querySelector("[data-modal-submit]");
    const cancel = root.querySelector("[data-modal-cancel]");
    submit.textContent = submitLabel;
    if (danger) submit.classList.add("alloc-danger");
    form.addEventListener("submit", (e) => { e.preventDefault(); submit.click(); });
    root.querySelector(".modal-backdrop").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); cancel.click(); }
    });
    setTimeout(() => (form.querySelector("input:not([type=checkbox]), select, textarea") || submit).focus(), 0);
  }

  async function cmdNewSet() {
    if (!st.archs.length) st.archs = await studio.api("GET", "/api/allocation/architectures");
    const n = st.sets.length + 1;
    const src = st.archs[0]?.id, tgt = st.archs[1]?.id || st.archs[0]?.id;
    const opt = (sel) => st.archs.map((a) => `<option value="${a.id}"${a.id === sel ? " selected" : ""}>${esc(a.qualified_name)} (${esc(a.kind)})</option>`).join("");
    const none = st.archs.length ? "" : `<p class="text-sm text-amber-700">Create at least one architecture (Part Def) or package first.</p>`;
    openModal("New allocation set", `${none}
      <label class="block">Name <input class="input" name="name" value="AllocationSet${n}" required /></label>
      <label class="block">Source architecture <select class="input" name="source">${opt(src)}</select></label>
      <label class="block">Target architecture <select class="input" name="target">${opt(tgt)}</select></label>
      <label class="block">First scenario <input class="input" name="scenario" value="Scenario 1" /></label>
      <label class="block">Description <textarea class="input" name="description" rows="2"></textarea></label>
      <label class="inline-flex items-center gap-1"><input type="checkbox" name="require_complete_coverage" /> Require complete coverage</label>`,
    async (o) => {
      const s = await studio.api("POST", "/api/allocation/sets", {
        name: o.name, source: o.source, target: o.target, scenario: o.scenario || "Scenario 1",
        description: o.description || "", require_complete_coverage: o.require_complete_coverage === "on",
      });
      st.scenarioId = s.scenarios[0].id;
      st.browserSel = { type: "set", id: s.id };
      st.selAxis = null; st.selAlloc = null;
      studio.log(`Created allocation set ${s.name} (${s.source_architecture.name} → ${s.target_architecture.name})`, "ok");
      await afterModelEdit();
    }, { submitLabel: "Create" });
  }

  function cmdNewScenario() {
    const s = currentSet(); if (!s) return;
    const used = new Set(s.scenarios.map((x) => x.name));
    let i = 1; while (used.has(`Scenario ${i}`)) i++;
    openModal(`New scenario in ${s.name}`, `<label class="block">Name <input class="input" name="name" value="Scenario ${i}" /></label>`,
      async (o) => {
        const sc = await studio.api("POST", `/api/allocation/sets/${enc(s.id)}/scenarios`, { name: o.name });
        st.scenarioId = sc.id; st.browserSel = { type: "scenario", id: sc.id }; st.selAlloc = null;
        studio.log(`Created scenario ${s.name}/${sc.name}`, "ok");
        await afterModelEdit();
      }, { submitLabel: "Create" });
  }

  function cmdDuplicate() {
    const sc = currentScenario(); if (!sc) return;
    openModal(`Duplicate ${sc.name}`, `<label class="block">Name of the copy <input class="input" name="name" value="${esc(sc.name)} copy" /></label>`,
      async (o) => {
        const copy = await studio.api("POST", `/api/allocation/scenarios/${enc(sc.id)}/duplicate`, { name: o.name });
        st.scenarioId = copy.id; st.browserSel = { type: "scenario", id: copy.id }; st.selAlloc = null;
        studio.log(`Duplicated ${sc.name} as ${copy.name} (${copy.allocation_count} allocations)`, "ok");
        await afterModelEdit();
      }, { submitLabel: "Duplicate" });
  }

  function browserTarget() {
    const sel = st.browserSel; if (!sel) return null;
    if (sel.type === "set") { const s = st.sets.find((x) => x.id === sel.id); return s && { ...sel, name: s.name, obj: s }; }
    const sc = allScenarios().find((x) => x.id === sel.id);
    return sc && { ...sel, name: sc.name, obj: sc };
  }

  function cmdRename() {
    const t = browserTarget(); if (!t) return;
    openModal(`Rename ${t.type === "set" ? "allocation set" : "scenario"}`,
      `<label class="block">Name <input class="input" name="name" value="${esc(t.name)}" /></label>`,
      async (o) => {
        const path = t.type === "set" ? `/api/allocation/sets/${enc(t.id)}` : `/api/allocation/scenarios/${enc(t.id)}`;
        await studio.api("PATCH", path, { name: o.name });
        studio.log(`Renamed ${t.name} to ${o.name}`, "ok");
        await afterModelEdit();
      }, { submitLabel: "Rename" });
  }

  function cmdDelete() {
    const t = browserTarget(); if (!t) return;
    const what = t.type === "set"
      ? `allocation set <b>${esc(t.name)}</b> with its ${t.obj.scenarios.length} scenario(s)`
      : `scenario <b>${esc(t.name)}</b> with its ${t.obj.allocation_count} allocation(s)`;
    openModal("Delete", `<p class="text-sm">Delete ${what}? The architectures are not changed.</p>`, async () => {
      const path = t.type === "set" ? `/api/allocation/sets/${enc(t.id)}` : `/api/allocation/scenarios/${enc(t.id)}`;
      await studio.api("DELETE", path);
      studio.log(`Deleted ${t.type === "set" ? "allocation set" : "scenario"} ${t.name}`, "warning");
      st.browserSel = null; st.selAlloc = null; st.selAxis = null;
      await afterModelEdit();
    }, { submitLabel: "Delete", danger: true });
  }

  function toggleCell(src, tgt, allocId) {
    const scenario = st.scenarioId;
    st.queue = st.queue.then(async () => {
      try {
        const r = await studio.api("POST", "/api/allocation/toggle", { scenario, source: src, target: tgt });
        if (r.allocated) {
          st.selAlloc = r.allocation.id;
          studio.log(`Allocated ${r.allocation.label}`, "ok");
        } else {
          if (st.selAlloc === allocId) st.selAlloc = null;
          studio.log("Deallocated", "info");
        }
        await afterModelEdit();
        if (r.allocated) await studio.selectElement(r.allocation.id);
        else if (studio.state.selectedId === allocId) await studio.selectElement(src);
      } catch { /* studio.api already logged the reason */ }
    });
    return st.queue;
  }

  async function deallocateSelected() {
    const a = selectedAllocation(); if (!a) return;
    await toggleCell(a.source_id, a.target_id, a.id);
  }

  async function saveSet() {
    const s = currentSet(); if (!s) return;
    const body = {
      name: els.side.querySelector("#alloc-set-name").value.trim(),
      description: els.side.querySelector("#alloc-set-desc").value,
      require_complete_coverage: els.side.querySelector("#alloc-set-cov").checked,
    };
    const src = els.side.querySelector("#alloc-set-src").value, tgt = els.side.querySelector("#alloc-set-tgt").value;
    if (src && src !== s.source_architecture?.id) body.source = src;
    if (tgt && tgt !== s.target_architecture?.id) body.target = tgt;
    const apply = async (force) => {
      await studio.api("PATCH", `/api/allocation/sets/${enc(s.id)}`, { ...body, force });
      studio.log(`Updated allocation set ${body.name}`, "ok");
      document.activeElement?.blur?.();
      await afterModelEdit();
    };
    const moving = body.source || body.target;
    const stale = moving ? s.scenarios.reduce((n, sc) => n + sc.allocation_count, 0) : 0;
    if (stale) {
      openModal("Change architecture", `<p class="text-sm">Changing the ${body.source ? "source" : "target"} architecture deletes every
        allocation whose element is not part of the new architecture (this set has ${stale}). Continue?</p>`,
      () => apply(true), { submitLabel: "Change", danger: true });
    } else {
      try { await apply(false); } catch { /* logged */ }
    }
  }

  async function saveScenario() {
    const sc = currentScenario(); if (!sc) return;
    const name = els.side.querySelector("#alloc-sc-name").value.trim();
    try {
      await studio.api("PATCH", `/api/allocation/scenarios/${enc(sc.id)}`, { name });
      studio.log(`Renamed scenario to ${name}`, "ok");
      document.activeElement?.blur?.();
      await afterModelEdit();
    } catch { /* logged */ }
  }

  async function saveAllocationDoc() {
    const a = selectedAllocation(); if (!a) return;
    try {
      await studio.api("PATCH", `/api/element/${enc(a.id)}`, { props: { doc: els.side.querySelector("#alloc-a-doc").value } });
      studio.log(`Saved description of ${a.label}`, "ok");
      document.activeElement?.blur?.();
      await reload();
    } catch { /* logged */ }
  }

  function setSideTab(tab) {
    st.sideTab = tab;
    renderSide();
  }

  function pickInMatrix(id) {
    const axis = st.matrix?.rows.some((r) => r.id === id) ? "row" : st.matrix?.columns.some((c) => c.id === id) ? "col" : null;
    if (!axis) { studio.emit("navigate", { id }); return; }
    selectAxis(axis, id).then(() => {
      els.mwrap.querySelector(`[data-axis="${axis}"][data-id="${id}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }

  /* ---------------- events ---------------- */

  function wire(pane) {
    pane.addEventListener("click", (e) => {
      const act = e.target.closest("[data-alloc-act]");
      if (act && !act.disabled) {
        const a = act.dataset.allocAct;
        const run = { "new-set": cmdNewSet, "new-scenario": cmdNewScenario, duplicate: cmdDuplicate, rename: cmdRename,
                      delete: cmdDelete, refresh: reload,
                      coverage: () => setSideTab("coverage"), chain: () => setSideTab("chain"),
                      "show-arch": () => showInArchitecture(focusElementId()) }[a];
        Promise.resolve(run?.()).catch(() => {});
        return;
      }
      const chip = e.target.closest("[data-alloc-chip]");
      if (chip) {
        const [axis, k] = chip.dataset.allocChip.split(":");
        const set = axis === "row" ? st.rowKinds : st.colKinds;
        if (set.has(k) && set.size > 1) set.delete(k); else set.add(k);
        reload();
        return;
      }
      const tab = e.target.closest("[data-alloc-side]");
      if (tab) { setSideTab(tab.dataset.allocSide); return; }
      const go = e.target.closest("[data-alloc-goto]");
      if (go) { showInArchitecture(go.dataset.allocGoto); return; }
      const pick = e.target.closest("[data-alloc-pick]");
      if (pick) { pickInMatrix(pick.dataset.allocPick); return; }
      const doBtn = e.target.closest("[data-alloc-do]");
      if (doBtn && doBtn.tagName === "BUTTON") {
        const d = doBtn.dataset.allocDo;
        if (d === "save-set") saveSet();
        else if (d === "save-scenario") saveScenario();
        else if (d === "save-alloc-doc") saveAllocationDoc();
        else if (d === "deallocate") deallocateSelected();
        else if (d === "inspect") { const a = selectedAllocation(); if (a) studio.selectElement(a.id).then(() => studio.switchTab("properties")).catch(() => {}); }
        else if (d === "show-arch") showInArchitecture(focusElementId());
        else if (d === "chain") setSideTab("chain");
        else if (d === "clear-filters") {
          st.rowKinds = new Set(["component", "function"]); st.colKinds = new Set(["component"]);
          st.show = "all"; st.colShow = "all"; st.q = ""; st.colQ = ""; st.collapsed.clear();
          pane.querySelector("#alloc-q").value = ""; pane.querySelector("#alloc-col-q").value = "";
          reload();
        }
        return;
      }
      const node = e.target.closest("[data-alloc-node]");
      if (node) { browserSelect(node.dataset.type, node.dataset.allocNode); }
    });
    pane.addEventListener("change", (e) => {
      if (e.target.matches("[data-alloc-do=cov-leaves]")) {
        els.side.dataset.leaves = e.target.checked ? "1" : "0";
        renderCoverage();
      } else if (e.target.id === "alloc-show") { st.show = e.target.value; reload(); }
      else if (e.target.id === "alloc-col-show") { st.colShow = e.target.value; reload(); }
    });
    let debounce = null;
    pane.addEventListener("input", (e) => {
      if (e.target.id !== "alloc-q" && e.target.id !== "alloc-col-q") return;
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        st.q = pane.querySelector("#alloc-q").value.trim();
        st.colQ = pane.querySelector("#alloc-col-q").value.trim();
        reload();
      }, 200);
    });
    pane.addEventListener("dblclick", (e) => {
      const node = e.target.closest("[data-alloc-node]");
      if (node) { browserSelect(node.dataset.type, node.dataset.allocNode); cmdRename(); }
    });
    pane.addEventListener("keydown", (e) => {
      const node = e.target.closest("[data-alloc-node]");
      if (node) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); browserSelect(node.dataset.type, node.dataset.allocNode); }
        else if (e.key === "F2") { e.preventDefault(); browserSelect(node.dataset.type, node.dataset.allocNode); cmdRename(); }
        else if (e.key === "Delete") { e.preventDefault(); e.stopPropagation(); browserSelect(node.dataset.type, node.dataset.allocNode); cmdDelete(); }
        else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const all = [...els.browser.querySelectorAll("[data-alloc-node]")];
          all[Math.max(0, Math.min(all.length - 1, all.indexOf(node) + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
        }
        return;
      }
      const cell = e.target.closest("td.cell");
      if (cell) matrixKey(e, cell);
      else if (e.key === "Escape" && !e.target.closest("input, textarea, select")) clearSelection();
    });
    els.mwrap.addEventListener("click", (e) => {
      const tw = e.target.closest("[data-twisty]");
      if (tw) {
        const k = tw.dataset.twisty;
        if (st.collapsed.has(k)) st.collapsed.delete(k); else st.collapsed.add(k);
        renderMatrix();
        return;
      }
      const head = e.target.closest("[data-axis]");
      if (head) { selectAxis(head.dataset.axis, head.dataset.id); return; }
      const cell = e.target.closest("td.cell");
      if (!cell || cell.classList.contains("na")) return;
      st.focus = { r: +cell.dataset.r, c: +cell.dataset.c };
      if (e.altKey || e.ctrlKey || e.metaKey) {
        if (cell.dataset.alloc) selectAllocation(cell.dataset.alloc);
        return;
      }
      toggleCell(cell.dataset.src, cell.dataset.tgt, cell.dataset.alloc);
    });
  }

  function matrixKey(e, cell) {
    const r = +cell.dataset.r, c = +cell.dataset.c;
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[e.key]) {
      e.preventDefault();
      const [dr, dc] = moves[e.key];
      const next = els.mwrap.querySelector(`td.cell[data-r="${r + dr}"][data-c="${c + dc}"]`);
      if (next) {
        cell.tabIndex = -1; next.tabIndex = 0; next.focus();
        st.focus = { r: r + dr, c: c + dc };
      }
    } else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (cell.classList.contains("na")) return;
      if (e.altKey && cell.dataset.alloc) { selectAllocation(cell.dataset.alloc); return; }
      st.focus = { r, c };
      toggleCell(cell.dataset.src, cell.dataset.tgt, cell.dataset.alloc).then(() => {
        els.mwrap.querySelector(`td.cell[data-r="${r}"][data-c="${c}"]`)?.focus();
      });
    } else if (e.key === "Delete" || e.key === "Backspace") {
      // Never let the global Delete shortcut delete the selected model element from here.
      e.preventDefault(); e.stopPropagation();
      if (cell.dataset.alloc) toggleCell(cell.dataset.src, cell.dataset.tgt, cell.dataset.alloc);
    } else if (e.key === "Escape") {
      clearSelection();
    }
  }

  function browserSelect(type, id) {
    st.browserSel = { type, id };
    const prev = st.scenarioId;
    if (type === "scenario") st.scenarioId = id;
    else {
      const s = st.sets.find((x) => x.id === id);
      if (s && !s.scenarios.some((sc) => sc.id === st.scenarioId)) st.scenarioId = s.scenarios[0]?.id || null;
    }
    if (st.scenarioId !== prev) { st.selAlloc = null; reload(); }
    else { renderBrowser(); renderSide(); }
  }

  /* ---------------- registration ---------------- */

  studio.registerTab({
    id: "allocation", title: "Allocation", order: 50,
    mount,
    onShow() { st.visible = true; reload(); },
  });
  studio.on("tab-shown", (id) => { st.visible = id === "allocation"; });
  studio.on("model-changed", () => { if (st.visible) reload(); else st.dirty = true; });
  studio.on("select", (el) => {
    if (!el || !st.matrix) return;
    if (el.kind === "Allocation") {
      if (st.matrix.allocations.some((a) => a.id === el.id) && st.selAlloc !== el.id) {
        st.selAlloc = el.id; renderMatrix(); renderSide();
      }
    } else if (!st.selAxis || st.selAxis.id !== el.id) {
      const axis = st.matrix.rows.some((r) => r.id === el.id) ? "row" : st.matrix.columns.some((c) => c.id === el.id) ? "col" : null;
      if (axis) { st.selAxis = { axis, id: el.id }; renderMatrix(); renderSide(); }
    }
  });

  function openInEditor(el, scenarioId) {
    if (el.kind === "AllocationScenario") { st.scenarioId = el.id; st.browserSel = { type: "scenario", id: el.id }; }
    else if (el.kind === "AllocationSet") st.browserSel = { type: "set", id: el.id };
    else if (el.allocation?.scenario_id) { st.scenarioId = el.allocation.scenario_id; st.selAlloc = el.id; }
    else { st.pendingFocus = el.id; if (scenarioId) st.scenarioId = scenarioId; }
    if (el.kind === "AllocationSet") {
      const s = st.sets.find((x) => x.id === el.id);
      if (s?.scenarios[0]) st.scenarioId = s.scenarios[0].id;
    }
    studio.switchTab("allocation");
  }

  studio.registerInspectorSection({
    id: "allocation", title: "Allocations", order: 50,
    render(el, box) {
      const openBtn = `<button type="button" class="btn-action" data-alloc-open>Open in Allocation Editor</button>`;
      if (el.kind === "Allocation" && el.allocation) {
        const a = el.allocation;
        box.innerHTML = `<div class="text-sm space-y-1"><div><b>${esc(a.source?.name)}</b> → <b>${esc(a.target?.name)}</b></div>
          <div class="text-slate-500 text-xs">${esc(a.set)} / ${esc(a.scenario)}</div>${openBtn}</div>`;
      } else if (el.kind === "AllocationSet" || el.kind === "AllocationScenario") {
        box.innerHTML = `<div class="text-sm space-y-1">${el.kind === "AllocationSet" && el.allocation_set
          ? `<div>${esc(el.allocation_set.source_architecture?.name || "∅")} → ${esc(el.allocation_set.target_architecture?.name || "∅")}</div>` : ""}${openBtn}</div>`;
      } else if (el.allocation_category) {
        box.innerHTML = `<div class="text-xs text-slate-500">Loading allocations…</div>`;
        studio.api("GET", `/api/allocation/element/${enc(el.id)}`).then((info) => {
          const line = (a, other) => `<li><button type="button" class="alloc-link" data-alloc-nav="${other.id}">${esc(other.name)}</button>
            <span class="text-xs text-slate-500">${esc(a.set)} / ${esc(a.scenario)}</span></li>`;
          const to = info.to.map((a) => line(a, a.target)).join(""), from = info.from.map((a) => line(a, a.source)).join("");
          box.dataset.scenario = (info.to[0] || info.from[0])?.scenario_id || "";
          box.innerHTML = `<div class="text-sm space-y-2">
            ${to ? `<div><div class="text-xs text-slate-500">Allocated to</div><ul class="alloc-list">${to}</ul></div>` : ""}
            ${from ? `<div><div class="text-xs text-slate-500">Allocated from</div><ul class="alloc-list">${from}</ul></div>` : ""}
            ${!to && !from ? `<div class="text-xs text-slate-500">Not allocated in any scenario.</div>` : ""}
            ${st.sets.length || to || from ? openBtn : ""}</div>`;
        }).catch(() => { box.textContent = ""; });
      } else {
        return false;
      }
      box.addEventListener("click", (e) => {
        if (e.target.closest("[data-alloc-open]")) openInEditor(el, box.dataset.scenario || null);
        const nav = e.target.closest("[data-alloc-nav]");
        if (nav) studio.emit("navigate", { id: nav.dataset.allocNav });
      });
      return undefined;
    },
  });

  studio.allocation = { reload, state: st };
}
