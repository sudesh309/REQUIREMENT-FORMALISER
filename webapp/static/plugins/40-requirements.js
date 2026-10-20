// Requirements perspective and traceability (System Composer Requirements Toolbox style).
//
//   * "Requirements" tab: toolstrip, tree-table of requirement sets with inline editing,
//     add / child / delete, indent / outdent / move, filter, implementation and verification
//     bars, detail form with long text and links, test cases view, import / export / report,
//     Link to Selection / Link from Selection, context menu and drag source.
//   * "Traceability" tab: traceability matrix (click a cell to link / unlink) and a Mermaid
//     traceability diagram (upstream / downstream links, depth 1-3).
//   * Inspector section "Requirements links" for any linkable element (navigate, highlight).
//   * Drag a requirement (grip) onto a tree node or, via `drop-on-element`, a canvas element.
//
// Backend: webapp/routes/requirements.py (see docs/features/requirements.md).

const STYLES = `
.rq-root { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; background:#fff; }
.rq-toolstrip { display:flex; flex-wrap:wrap; align-items:stretch; background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:4px 4px 0; }
.rq-ts-section { display:flex; flex-direction:column; justify-content:space-between; padding:0 6px; border-right:1px solid #e2e8f0; }
.rq-ts-buttons { display:flex; gap:2px; align-items:flex-start; }
.rq-ts-btn { display:flex; flex-direction:column; align-items:center; gap:2px; min-width:40px; padding:3px 4px; border-radius:4px; font-size:11px; line-height:1.1; color:#334155; white-space:nowrap; text-align:center; }
.rq-ts-btn:hover:not(:disabled) { background:#e2e8f0; }
.rq-ts-btn:focus-visible { outline:2px solid #2563eb; }
.rq-ts-btn:disabled { opacity:.35; cursor:not-allowed; }
.rq-ts-btn.on { background:#dbeafe; color:#1d4ed8; }
.rq-ts-icon { font-size:16px; line-height:18px; color:#1d4ed8; }
.rq-ts-label { font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:#94a3b8; text-align:center; padding:2px 0 3px; }
.rq-ts-col { display:flex; flex-direction:column; gap:2px; justify-content:center; }
.rq-ts-select { font-size:11px; border:1px solid #cbd5e1; border-radius:4px; padding:2px 4px; background:#fff; width:136px; }
.rq-ts-note { font-size:10px; line-height:12px; color:#64748b; max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rq-ts-note.sel { color:#1d4ed8; }
.rq-subbar { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px 8px; border-bottom:1px solid #e2e8f0; font-size:12px; }
.rq-seg { display:inline-flex; border:1px solid #cbd5e1; border-radius:5px; overflow:hidden; }
.rq-seg button { padding:2px 9px; font-size:12px; color:#475569; background:#fff; }
.rq-seg button + button { border-left:1px solid #cbd5e1; }
.rq-seg button.on { background:#dbeafe; color:#1d4ed8; font-weight:500; }
.rq-filter { width:190px !important; font-size:12px !important; padding:.2rem .45rem !important; }
.rq-small-select { font-size:12px; border:1px solid #cbd5e1; border-radius:4px; padding:2px 4px; background:#fff; }
.rq-rollup { margin-left:auto; display:flex; align-items:center; gap:10px; color:#475569; }
.rq-body { flex:1; display:flex; flex-direction:column; min-height:0; }
.rq-table-wrap { flex:1; overflow:auto; min-height:80px; outline:none; }
.rq-table-wrap:focus-visible { box-shadow: inset 0 0 0 2px #93c5fd; }
.rq-table { border-collapse:collapse; width:100%; font-size:12px; }
.rq-table th { position:sticky; top:0; z-index:1; background:#f1f5f9; text-align:left; font-weight:600; color:#475569; padding:4px 6px; border-bottom:1px solid #cbd5e1; border-right:1px solid #e2e8f0; white-space:nowrap; }
.rq-table td { border-bottom:1px solid #eef2f7; border-right:1px solid #f1f5f9; padding:0; vertical-align:middle; white-space:nowrap; }
.rq-table td input, .rq-table td select { width:100%; min-width:40px; border:1px solid transparent; background:transparent; padding:3px 5px; font-size:12px; border-radius:2px; }
.rq-table td input:hover, .rq-table td select:hover { border-color:#e2e8f0; }
.rq-table td input:focus, .rq-table td select:focus { outline:none; border-color:#2563eb; background:#fff; }
.rq-table tr.sel > td { background:#eff6ff; }
.rq-table tr.dim > td { opacity:.55; }
.rq-table tr.rq-drop > td { background:#fef3c7; }
.rq-idx { display:flex; align-items:center; gap:2px; padding:0 4px; color:#64748b; font-variant-numeric:tabular-nums; }
.rq-grip { cursor:grab; color:#cbd5e1; padding:0 2px; user-select:none; }
.rq-grip:hover { color:#64748b; }
.rq-twisty { width:14px; text-align:center; cursor:pointer; color:#64748b; user-select:none; }
.rq-twisty.empty { cursor:default; color:transparent; }
.rq-barwrap { display:flex; align-items:center; gap:4px; padding:0 6px; }
.rq-bar { width:64px; height:8px; border-radius:4px; background:#e2e8f0; overflow:hidden; display:flex; flex:none; }
.rq-bar i { display:block; height:100%; }
.rq-seg-impl { background:#2563eb; } .rq-seg-pass { background:#16a34a; } .rq-seg-fail { background:#dc2626; }
.rq-seg-unex { background:#f59e0b; } .rq-seg-miss { background:#e2e8f0; }
.rq-pct { font-size:11px; color:#475569; min-width:30px; font-variant-numeric:tabular-nums; }
.rq-linkcell { padding:0 6px !important; color:#475569; }
.rq-warn { color:#b45309; font-weight:600; }
.rq-splitter { height:5px; background:#e2e8f0; cursor:row-resize; flex:none; }
.rq-splitter:hover { background:#93c5fd; }
.rq-detail { flex:none; overflow:auto; padding:8px 10px; background:#fcfcfd; font-size:12px; }
.rq-detail-head { display:flex; align-items:center; gap:8px; margin-bottom:6px; flex-wrap:wrap; }
.rq-detail-head b { font-size:13px; }
.rq-detail-grid { display:grid; grid-template-columns: minmax(0,1.2fr) minmax(0,1fr); gap:12px; }
.rq-detail label { display:block; color:#475569; font-size:11px; margin-bottom:4px; }
.rq-detail textarea, .rq-detail input.input { font-size:12px; margin-top:2px; }
.rq-empty { padding:24px; color:#64748b; font-style:italic; font-size:13px; }
.rq-chip { display:inline-flex; align-items:center; gap:3px; padding:0 6px; border-radius:9999px; font-size:11px; background:#eef2ff; color:#3730a3; white-space:nowrap; }
.rq-chip.t-implement { background:#dbeafe; color:#1e40af; } .rq-chip.t-verify { background:#dcfce7; color:#166534; }
.rq-chip.t-refine { background:#f3e8ff; color:#6b21a8; } .rq-chip.t-derive { background:#ffedd5; color:#9a3412; }
.rq-chip.t-relate { background:#f1f5f9; color:#334155; } .rq-chip.t-confirm { background:#ccfbf1; color:#115e59; }
.rq-links { display:flex; flex-direction:column; gap:3px; }
.rq-link { display:flex; align-items:center; gap:6px; padding:2px 4px; border-radius:4px; font-size:12px; }
.rq-link:hover { background:#f1f5f9; }
.rq-link.suspect { background:#fffbeb; }
.rq-link .rq-verb { color:#64748b; white-space:nowrap; }
.rq-a { color:#1d4ed8; cursor:pointer; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rq-a:hover { text-decoration:underline; }
.rq-x { color:#94a3b8; padding:0 4px; border-radius:3px; margin-left:auto; }
.rq-x:hover { color:#dc2626; background:#fee2e2; }
.rq-mini { font-size:11px; padding:1px 6px; border:1px solid #e2e8f0; border-radius:4px; background:#fff; color:#334155; white-space:nowrap; }
.rq-mini:hover { background:#f1f5f9; }
.rq-menu { position:fixed; z-index:60; background:#fff; border:1px solid #cbd5e1; border-radius:6px; box-shadow:0 10px 25px rgba(15,23,42,.18); padding:4px 0; min-width:210px; font-size:12px; }
.rq-menu button { display:flex; width:100%; text-align:left; padding:4px 12px; color:#0f172a; gap:8px; }
.rq-menu button:hover:not(:disabled), .rq-menu button:focus { background:#eff6ff; outline:none; }
.rq-menu button:disabled { color:#94a3b8; }
.rq-menu hr { margin:3px 0; border-color:#e2e8f0; }
.rq-tm-body { flex:1; overflow:auto; min-height:0; position:relative; }
.rq-matrix { border-collapse:separate; border-spacing:0; font-size:12px; }
.rq-matrix th, .rq-matrix td { border-right:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; }
.rq-matrix thead th { position:sticky; top:0; z-index:2; background:#f1f5f9; vertical-align:bottom; padding:4px 2px; }
.rq-matrix thead th.corner { left:0; z-index:3; text-align:left; padding:6px; color:#64748b; font-weight:500; min-width:260px; }
.rq-vert { writing-mode:vertical-rl; transform:rotate(180deg); white-space:nowrap; max-height:150px; overflow:hidden; text-overflow:ellipsis; font-weight:500; color:#334155; padding:2px 0; }
.rq-matrix th.rq-rowhead { position:sticky; left:0; z-index:1; background:#fff; text-align:left; font-weight:400; padding:3px 8px; white-space:nowrap; max-width:340px; overflow:hidden; text-overflow:ellipsis; }
.rq-matrix .unlinked { background:#fef3c7 !important; }
.rq-cell { width:28px; min-width:28px; height:24px; text-align:center; cursor:pointer; }
.rq-cell:hover { background:#eff6ff; outline:1px solid #93c5fd; }
.rq-cell.self { background:#f1f5f9; cursor:not-allowed; }
.rq-mlink { display:inline-block; padding:0 2px; border-radius:3px; font-size:13px; line-height:16px; }
.rq-mlink:hover { background:#fee2e2; }
.rq-mlink.suspect { outline:1px dashed #f59e0b; }
.rq-legend { display:flex; flex-wrap:wrap; gap:8px; padding:4px 8px; border-bottom:1px solid #e2e8f0; font-size:11px; color:#475569; }
.rq-diagram { padding:12px; }
.rq-diagram-nodes { display:flex; flex-wrap:wrap; gap:4px; padding:0 12px 12px; }
#tree li.tree-node.rq-drop-target > .row { background:#fef3c7; outline:1px dashed #f59e0b; }
.rq-table td.rq-pad { padding:2px 6px; }
.rq-table tr.rq-linkrow.suspect > td { background:#fffbeb; }
.rq-check { display:inline-flex; align-items:center; gap:4px; color:#475569; }
.rq-dock { flex:none; display:flex; flex-direction:column; height:240px; min-height:0; background:#fff; border-top:1px solid #cbd5e1; box-shadow:0 -2px 6px rgba(15,23,42,.06); }
.rq-dock.rq-off { display:none; }
.rq-dock-head { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px 8px; background:#f8fafc; border-bottom:1px solid #e2e8f0; font-size:12px; }
.rq-dock-title { font-weight:600; color:#334155; font-size:11px; letter-spacing:.06em; text-transform:uppercase; cursor:help; }
.rq-dock-head .rq-small-select { max-width:150px; }
.rq-dock-head .rq-filter { width:150px !important; }
.rq-dock-body { flex:1; overflow:auto; min-height:0; outline:none; }
.rq-dock-body:focus-visible { box-shadow: inset 0 0 0 2px #93c5fd; }
.rq-dock tr.rq-row { cursor:grab; }
.rq-dock tr.rq-row:hover > td { background:#f8fafc; }
.rq-dock tr.rq-row.sel > td { background:#eff6ff; }
[data-plugin-button="req-perspective"].rq-on { background:#dbeafe; color:#1d4ed8; border-color:#bfdbfe; }
`;

const ICONS = { implement: "⚙", verify: "✓", refine: "⇣", derive: "⇡", relate: "↔", confirm: "☑" };
const INCOMING = { implement: "implemented by", verify: "verified by", refine: "refined by",
                   derive: "has derived", relate: "related from", confirm: "confirmed by" };
const OUTGOING = { implement: "implements", verify: "verifies", refine: "refines",
                   derive: "derives from", relate: "relates to", confirm: "confirms" };
// For "Link to Selection": design / test elements are always the source of these types.
const ELEMENT_IS_SOURCE = new Set(["implement", "verify", "confirm"]);

export default async function install(studio) {
  // studio.api logs HTTP errors to the Output pane; tag them so run() does not log twice.
  const api = async (...args) => {
    try { return await studio.api(...args); }
    catch (e) { e.fromApi = true; throw e; }
  };
  const esc = (v) => studio.escapeHtml(String(v ?? ""));
  const style = document.createElement("style");
  style.dataset.plugin = "requirements";
  style.textContent = STYLES;
  document.head.appendChild(style);

  // Operations in flight are published as <body data-rq-pending> (UI tests wait for "0").
  let pending = 0;
  const mark = (d) => { pending += d; document.body.dataset.rqPending = String(pending); };
  mark(0);
  const run = (fn) => async (...args) => {
    mark(1);
    try { return await fn(...args); }
    catch (e) {
      if (!e?.fromApi) { console.error(e); studio.log(`Requirements: ${e}`, "error"); }
      return undefined;
    } finally { mark(-1); }
  };

  const meta = await api("GET", "/api/req/meta");
  const typeMeta = Object.fromEntries(meta.link_types.map((t) => [t.name, t]));

  const S = {
    table: null, setId: "", selId: null, collapsed: new Set(),
    filter: { text: "", type: "", status: "" }, view: "requirements", linkType: "implement",
    detailH: 230, visible: { req: false, tm: false }, dirty: { req: true, tm: true },
    detailLinks: null, detailToken: 0, skipModelChanged: false,
    tm: { setId: null, columns: "components", columnSet: "", view: "matrix", element: "", depth: "2", data: null },
    insp: null,
    links: [], linksSuspectOnly: false,      // "Links" view of the Requirements tab
    dockOn: false, dockFilter: "", dockH: 240, // Requirements Perspective dock
  };
  try { S.dockOn = localStorage.getItem("rq.dock") === "1"; } catch { /* storage unavailable */ }

  // ------------------------------------------------------------------ helpers
  const opt = (value, label, selected) =>
    `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label ?? value)}</option>`;
  const enumOptions = (values, current, blank = "—") =>
    opt("", blank, !current) + values.map((v) => opt(v, v, v === current)).join("");
  const rows = () => S.table?.rows || [];
  const rowById = (id) => rows().find((r) => r.id === id);
  const selRow = () => rowById(S.selId);
  const sets = () => S.table?.sets || [];
  const currentSet = () => sets().find((s) => s.id === S.setId) || null;
  const targetSetId = () => S.setId || selRow()?.set_id || sets()[0]?.id || null;
  const reqLabel = (r) => `${r.req_id || "?"} ${r.summary || ""}`.trim();
  const otherLabel = (o) => (o.req_id ? `${o.req_id} ${o.name || ""}` : (o.name || o.qualified_name || "?"));
  const chip = (type) => `<span class="rq-chip t-${esc(type)}" title="${esc(typeMeta[type]?.description || "")}">${ICONS[type] || "•"} ${esc(typeMeta[type]?.label || type)}</span>`;

  function openModal(title, html, onSubmit) {
    studio.modal(esc(title), html, onSubmit);
    const root = document.getElementById("modal-root");
    const form = root.querySelector("#modal-form");
    const submit = () => root.querySelector("[data-modal-submit]")?.click();
    form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && e.target.type !== "file") { e.preventDefault(); submit(); }
    });
    root.querySelector(".modal")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); root.querySelector("[data-modal-cancel]")?.click(); }
    });
    setTimeout(() => form.querySelector("input:not([type=hidden]), select, textarea")?.focus(), 0);
    return root;
  }
  const confirmModal = (title, message, onYes) =>
    openModal(title, `<p class="text-sm text-slate-700">${message}</p>`, onYes);

  async function refreshTree() {
    S.skipModelChanged = true;
    try { await studio.refreshTree(); } finally { S.skipModelChanged = false; }
  }

  // After any change: reload what is visible, mark the rest dirty.
  async function afterChange({ tree = false } = {}) {
    S.dirty.tm = true;
    await loadTable();
    if (S.visible.tm) await loadTraceability();
    if (tree) await refreshTree();
    await renderInspector();
  }

  // ------------------------------------------------------------------ Requirements tab
  let reqPane, tbody, tableWrap, detailEl, subbarEl, setSelect, selNote, splitter, theadRow;
  let dockEl = null, dockBody = null, dockBtn = null;   // Requirements Perspective dock (below)

  reqPane = studio.registerTab({
    id: "requirements", title: "Requirements", order: 40,
    mount(pane) {
      reqPane = pane;
      pane.innerHTML = `
      <div class="rq-root" data-rq="root">
        <div class="rq-toolstrip" role="toolbar" aria-label="Requirements toolstrip">
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <div class="rq-ts-col"><select class="rq-ts-select" data-rq="set-select" title="Requirement set shown"></select>
              <span class="rq-ts-note" data-rq="set-note"></span></div>
            <button class="rq-ts-btn" data-rq="new-set" title="New requirement set"><span class="rq-ts-icon">▤</span>New<br>Set</button>
            <button class="rq-ts-btn" data-rq="set-props" title="Rename, change ID prefix or delete the set"><span class="rq-ts-icon">✎</span>Set<br>Properties</button>
          </div><div class="rq-ts-label">Set</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-rq="add" title="Add requirement after the selected one (Insert)"><span class="rq-ts-icon">＋</span>Add</button>
            <button class="rq-ts-btn" data-rq="add-child" title="Add child requirement (Shift+Insert)"><span class="rq-ts-icon">↳</span>Child</button>
            <button class="rq-ts-btn" data-rq="delete" title="Delete requirement and its children (Delete)"><span class="rq-ts-icon">✕</span>Delete</button>
          </div><div class="rq-ts-label">Requirement</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-rq="up" title="Move up (Alt+Shift+↑)"><span class="rq-ts-icon">▲</span>Up</button>
            <button class="rq-ts-btn" data-rq="down" title="Move down (Alt+Shift+↓)"><span class="rq-ts-icon">▼</span>Down</button>
            <button class="rq-ts-btn" data-rq="indent" title="Make child of the previous requirement (Alt+Shift+→)"><span class="rq-ts-icon">⇥</span>Indent</button>
            <button class="rq-ts-btn" data-rq="outdent" title="Move up one level (Alt+Shift+←)"><span class="rq-ts-icon">⇤</span>Outdent</button>
          </div><div class="rq-ts-label">Arrange</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <div class="rq-ts-col"><select class="rq-ts-select" data-rq="link-type" title="Link type used by Link to / from Selection"></select>
              <span class="rq-ts-note" data-rq="link-dir" title="Link direction (source → destination)"></span>
              <span class="rq-ts-note sel" data-rq="sel-note" title="Current model selection (tree / canvas)">Selection: none</span></div>
            <button class="rq-ts-btn" data-rq="link-to" title="Link the selected requirement with the selected model element(s)"><span class="rq-ts-icon">⇠</span>Link to<br>Selection</button>
            <button class="rq-ts-btn" data-rq="link-from" title="Selected model element(s) become the link source"><span class="rq-ts-icon">⇢</span>Link from<br>Selection</button>
          </div><div class="rq-ts-label">Link</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-rq="add-test" title="Add a test case to the set"><span class="rq-ts-icon">⚗</span>Test<br>Case</button>
            <button class="rq-ts-btn" data-rq="clear-suspect" title="Clear every suspect link of the selected requirement"><span class="rq-ts-icon">⚠</span>Clear<br>Suspect</button>
          </div><div class="rq-ts-label">Verify / Track</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-rq="import" title="Import CSV or ReqIF"><span class="rq-ts-icon">⭳</span>Import</button>
            <button class="rq-ts-btn" data-rq="export" title="Export CSV / ReqIF / report"><span class="rq-ts-icon">⭱</span>Export</button>
            <button class="rq-ts-btn" data-rq="report" title="Download the HTML traceability report"><span class="rq-ts-icon">▦</span>Report</button>
          </div><div class="rq-ts-label">Share</div></div>
        </div>
        <div class="rq-subbar" data-rq="subbar"></div>
        <div class="rq-body">
          <div class="rq-table-wrap" tabindex="0" data-rq="table-wrap">
            <table class="rq-table"><thead><tr data-rq="thead"></tr></thead><tbody data-rq="tbody"></tbody></table>
          </div>
          <div class="rq-splitter" data-rq="splitter" title="Drag to resize"></div>
          <div class="rq-detail" data-rq="detail"></div>
        </div>
      </div>`;
      const q = (k) => pane.querySelector(`[data-rq="${k}"]`);
      tbody = q("tbody"); tableWrap = q("table-wrap"); detailEl = q("detail"); subbarEl = q("subbar");
      setSelect = q("set-select"); selNote = q("sel-note"); splitter = q("splitter"); theadRow = q("thead");
      q("link-type").innerHTML = meta.link_types.map((t) =>
        opt(t.name, `${ICONS[t.name]} ${t.label}`, t.name === S.linkType)).join("");
      q("link-type").addEventListener("change", (e) => setLinkType(e.target.value));
      setLinkType(S.linkType);
      setSelect.addEventListener("change", run((e) => chooseSet(e.target.value)));
      wireToolstrip(pane);
      wireTable();
      wireSplitter();
    },
    onShow() { S.visible.req = true; if (S.dirty.req) run(loadTable)(); else renderAll(); },
  });

  function shortRule(rule) {
    return { requirement: "requirement", test: "test case", design: "design element", any: "any" }[rule] || rule;
  }

  // The toolstrip link-type picker; the note under it spells out the direction.
  function setLinkType(name) {
    S.linkType = name;
    const t = typeMeta[name];
    for (const sel of [reqPane?.querySelector('[data-rq="link-type"]'), dockEl?.querySelector('[data-dock="link-type"]')]) {
      if (sel && sel.value !== name) sel.value = name;
    }
    const note = reqPane?.querySelector('[data-rq="link-dir"]');
    if (note && t) {
      note.textContent = `${shortRule(t.source)} → ${shortRule(t.target)}`;
      note.title = t.description;
    }
    const dsel = dockEl?.querySelector('[data-dock="link-type"]');
    if (dsel && t) dsel.title = `${t.label}: ${shortRule(t.source)} → ${shortRule(t.target)}. ${t.description}`;
  }

  function wireToolstrip(pane) {
    const on = (k, fn) => pane.querySelector(`[data-rq="${k}"]`).addEventListener("click", run(fn));
    on("new-set", newSetDialog);
    on("set-props", setPropsDialog);
    on("add", () => addRequirement(false));
    on("add-child", () => addRequirement(true));
    on("delete", deleteSelected);
    for (const dir of ["up", "down", "indent", "outdent"]) on(dir, () => moveSelected(dir));
    on("link-to", () => linkWithSelection("to"));
    on("link-from", () => linkWithSelection("from"));
    on("add-test", addTestCaseDialog);
    on("clear-suspect", clearSuspectSelected);
    on("import", importDialog);
    on("export", exportDialog);
    on("report", () => downloadExport("report-html", targetSetId()));
  }

  function wireSplitter() {
    splitter.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startY = e.clientY, startH = S.detailH;
      const move = (ev) => { S.detailH = Math.max(90, Math.min(600, startH - (ev.clientY - startY))); detailEl.style.height = `${S.detailH}px`; };
      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  }

  async function loadTable() {
    const q = S.setId ? `?set=${encodeURIComponent(S.setId)}` : "";
    let data;
    try { data = await api("GET", `/api/req/table${q}`); }
    catch (e) {
      if (S.setId) { S.setId = ""; data = await api("GET", "/api/req/table"); } else throw e;
    }
    S.table = data;
    if (S.setId && !data.sets.some((s) => s.id === S.setId)) S.setId = "";
    if (S.selId && !rowById(S.selId)) S.selId = null;
    if (S.view === "links") await loadLinks();
    S.dirty.req = false;
    renderAll();
  }

  async function loadLinks() {
    const p = new URLSearchParams();
    if (S.setId) p.set("set", S.setId);
    S.links = (await api("GET", `/api/req/links?${p}`)).links;
  }

  async function showView(view) {
    S.view = view;
    if (view === "links") await loadLinks();
    renderAll();
  }

  function renderAll() {
    if (!tbody) return;
    renderSetSelect();
    renderSubbar();
    if (S.view === "tests") renderTests();
    else if (S.view === "links") renderLinksView();
    else renderTable();
    renderDetail();
    updateToolstrip();
    renderDock();
  }

  async function chooseSet(id) { S.setId = id; S.selId = null; await loadTable(); }

  const setOptions = () => opt("", sets().length ? "All sets" : "No sets yet", !S.setId) +
    sets().map((s) => opt(s.id, `${s.name} (${s.count})`, s.id === S.setId)).join("");

  function renderSetSelect() {
    setSelect.innerHTML = setOptions();
    const cs = currentSet();
    reqPane.querySelector('[data-rq="set-note"]').textContent = cs ? `ID prefix ${cs.prefix || "—"}` : `${sets().length} set(s)`;
  }

  function rollupTotals() {
    const list = currentSet() ? [currentSet()] : sets();
    const t = { impl: { done: 0, total: 0 }, ver: { passed: 0, failed: 0, unexecuted: 0, missing: 0, total: 0 } };
    for (const s of list) {
      t.impl.done += s.implementation.done; t.impl.total += s.implementation.total;
      for (const k of ["passed", "failed", "unexecuted", "missing", "total"]) t.ver[k] += s.verification[k];
    }
    const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
    return { impl: { ...t.impl, pct: pct(t.impl.done, t.impl.total) }, ver: { ...t.ver, pct: pct(t.ver.passed, t.ver.total) } };
  }

  function renderSubbar() {
    const nReq = rows().length, nTc = (S.table?.test_cases || []).length;
    const nLinks = S.table?.link_count || 0, nSus = S.table?.suspect_link_count || 0;
    const tot = rollupTotals();
    const reqFilters = `
      <select class="rq-small-select" data-rq="filter-type" title="Filter by type">${enumOptions(meta.types, S.filter.type, "All types")}</select>
      <select class="rq-small-select" data-rq="filter-status" title="Filter by status">${enumOptions(meta.statuses, S.filter.status, "All statuses")}</select>`;
    const linkFilters = `
      <label class="rq-check"><input type="checkbox" data-rq="suspect-only" ${S.linksSuspectOnly ? "checked" : ""} /> Suspect only</label>
      <button class="rq-mini" data-rq="clear-all-suspect" ${nSus ? "" : "disabled"} title="Mark every suspect link shown as reviewed">⚠ Clear all suspect (${nSus})</button>`;
    subbarEl.innerHTML = `
      <span class="rq-seg" role="tablist">
        <button data-rq="view-req" class="${S.view === "requirements" ? "on" : ""}">Requirements (${nReq})</button>
        <button data-rq="view-tests" class="${S.view === "tests" ? "on" : ""}">Test cases (${nTc})</button>
        <button data-rq="view-links" class="${S.view === "links" ? "on" : ""}" title="Every trace link with change information">Links (${nLinks}${nSus ? ` · ⚠ ${nSus}` : ""})</button>
      </span>
      <input class="input rq-filter" data-rq="filter-text" placeholder="Filter text / ID…" value="${esc(S.filter.text)}" />
      ${S.view === "links" ? linkFilters : S.view === "requirements" ? reqFilters : ""}
      <span class="rq-rollup" data-rq="rollup" data-impl-pct="${tot.impl.pct}" data-ver-pct="${tot.ver.pct}">
        <span title="Implemented leaf requirements">Implemented ${implBar(tot.impl)}</span>
        <span title="Verified (passed) leaf requirements">Verified ${verBar(tot.ver)}</span>
      </span>`;
    const q = (k) => subbarEl.querySelector(`[data-rq="${k}"]`);
    q("view-req").onclick = run(() => showView("requirements"));
    q("view-tests").onclick = run(() => showView("tests"));
    q("view-links").onclick = run(() => showView("links"));
    const ft = q("filter-text");
    ft.addEventListener("input", () => {
      S.filter.text = ft.value;
      if (S.view === "requirements") renderTable();
      else if (S.view === "links") renderLinksView();
    });
    if (S.view === "requirements") {
      q("filter-type").onchange = (e) => { S.filter.type = e.target.value; renderTable(); };
      q("filter-status").onchange = (e) => { S.filter.status = e.target.value; renderTable(); };
    }
    if (S.view === "links") {
      q("suspect-only").onchange = (e) => { S.linksSuspectOnly = e.target.checked; renderLinksView(); };
      q("clear-all-suspect").onclick = run(async () => {
        const out = await api("POST", "/api/req/clear-suspect", S.setId ? { element: S.setId } : {});
        studio.log(`Cleared ${out.cleared} suspect link(s)`, "ok");
        await afterChange();
      });
    }
  }

  function implBar(impl) {
    return `<span class="rq-barwrap" title="${impl.done}/${impl.total} implemented${impl.direct ? " (has an Implement link)" : ""}"><span class="rq-bar"><i class="rq-seg-impl" style="width:${impl.pct}%"></i></span><span class="rq-pct">${impl.pct}%</span></span>`;
  }
  function verBar(v) {
    const w = (n) => (v.total ? (100 * n) / v.total : 0);
    const title = `${v.passed} passed, ${v.failed} failed, ${v.unexecuted} unexecuted, ${v.missing} without test` + (v.state ? ` — ${v.state}` : "");
    return `<span class="rq-barwrap" title="${esc(title)}"><span class="rq-bar"><i class="rq-seg-pass" style="width:${w(v.passed)}%"></i><i class="rq-seg-fail" style="width:${w(v.failed)}%"></i><i class="rq-seg-unex" style="width:${w(v.unexecuted)}%"></i></span><span class="rq-pct">${v.pct}%</span></span>`;
  }

  // --- tree-table ---------------------------------------------------------
  function visibleRows(f = S.filter) {
    const all = rows();
    const byId = new Map(all.map((r) => [r.id, r]));
    const text = (f.text || "").trim().toLowerCase();
    const filtering = !!(text || f.type || f.status);
    const match = (r) =>
      (!text || [r.req_id, r.summary, r.description, r.rationale].some((v) => (v || "").toLowerCase().includes(text)))
      && (!f.type || r.type === f.type) && (!f.status || r.status === f.status);
    const keep = new Set();
    if (filtering) {
      for (const r of all) {
        if (!match(r)) continue;
        keep.add(r.id);
        for (let p = r.parent_id; p; p = byId.get(p)?.parent_id) keep.add(p);
      }
    }
    const collapsedAncestor = (r) => {
      for (let p = r.parent_id; p; p = byId.get(p)?.parent_id) if (S.collapsed.has(p)) return true;
      return false;
    };
    const out = [];
    for (const r of all) {
      if (filtering ? !keep.has(r.id) : collapsedAncestor(r)) continue;
      out.push({ r, dim: filtering && !match(r) });
    }
    return out;
  }

  function renderTable() {
    theadRow.innerHTML = `<th style="width:72px">#</th><th style="width:88px">ID</th><th>Summary</th><th style="width:118px">Type</th>
      <th style="width:84px">Priority</th><th style="width:104px">Status</th><th style="width:112px">Verification method</th>
      <th style="width:104px">Implemented</th><th style="width:104px">Verified</th><th style="width:58px">Links</th>`;
    const focus = captureFocus();
    if (!sets().length) {
      tbody.innerHTML = `<tr><td colspan="10"><div class="rq-empty">No requirement sets yet. Click <b>New Set</b> (or <b>Import</b>) to start.</div></td></tr>`;
      return;
    }
    const vis = visibleRows();
    if (!vis.length) {
      tbody.innerHTML = `<tr><td colspan="10"><div class="rq-empty">${rows().length ? "No requirement matches the filter." : "This set is empty. Click <b>Add</b> to create the first requirement."}</div></td></tr>`;
      return;
    }
    let lastSet = null;
    const html = [];
    for (const { r, dim } of vis) {
      if (!S.setId && r.set_id !== lastSet) {
        lastSet = r.set_id;
        const s = sets().find((x) => x.id === r.set_id);
        html.push(`<tr class="rq-sethead"><td colspan="10" style="background:#f8fafc;padding:3px 8px;font-weight:600;color:#334155">▤ ${esc(s?.name || "")}</td></tr>`);
      }
      const twisty = r.has_children ? (S.collapsed.has(r.id) ? "▸" : "▾") : "";
      const sus = r.suspect_count ? ` <span class="rq-warn" title="${r.suspect_count} suspect link(s)">⚠</span>` : "";
      html.push(`<tr class="rq-row${r.id === S.selId ? " sel" : ""}${dim ? " dim" : ""}" data-id="${esc(r.id)}" data-req-id="${esc(r.req_id || "")}">
        <td><div class="rq-idx"><span class="rq-grip" draggable="true" title="Drag onto a model element to create an Implement link">⠿</span><span class="rq-twisty${twisty ? "" : " empty"}" data-rq="twisty">${twisty || "·"}</span>${esc(r.index)}</div></td>
        <td><input data-f="id" value="${esc(r.req_id || "")}" aria-label="ID" /></td>
        <td><input data-f="summary" value="${esc(r.summary || "")}" style="padding-left:${5 + 16 * r.depth}px" aria-label="Summary" /></td>
        <td><select data-f="type" aria-label="Type">${enumOptions(meta.types, r.type)}</select></td>
        <td><select data-f="priority" aria-label="Priority">${enumOptions(meta.priorities, r.priority)}</select></td>
        <td><select data-f="status" aria-label="Status">${enumOptions(meta.statuses, r.status)}</select></td>
        <td><select data-f="verification_method" aria-label="Verification method">${enumOptions(meta.verification_methods, r.verification_method)}</select></td>
        <td data-impl-pct="${r.implementation.pct}">${implBar(r.implementation)}</td>
        <td data-ver-state="${esc(r.verification.state)}">${verBar(r.verification)}</td>
        <td class="rq-linkcell" data-links="${r.link_count}" data-suspect="${r.suspect_count}">${r.link_count}${sus}</td>
      </tr>`);
    }
    tbody.innerHTML = html.join("");
    restoreFocus(focus);
  }

  function captureFocus() {
    const a = document.activeElement;
    if (!a || !tbody?.contains(a)) return null;
    const tr = a.closest("tr[data-id]");
    return tr ? { id: tr.dataset.id, f: a.dataset.f, start: a.selectionStart, end: a.selectionEnd } : null;
  }
  function restoreFocus(f) {
    if (!f) return;
    const el = tbody.querySelector(`tr[data-id="${CSS.escape(f.id)}"] [data-f="${CSS.escape(f.f || "")}"]`);
    if (!el) return;
    el.focus();
    try { if (f.start != null) el.setSelectionRange(f.start, f.end); } catch { /* selects */ }
  }

  function wireTable() {
    tbody.addEventListener("mousedown", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr && !e.target.closest("[data-rq=twisty]")) selectRow(tr.dataset.id);
    });
    tbody.addEventListener("focusin", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr && tr.dataset.id !== S.selId) selectRow(tr.dataset.id);
    });
    tbody.addEventListener("click", (e) => {
      if (S.view === "links") { run(onLinkAction)(e, S.links); return; }
      const tw = e.target.closest("[data-rq=twisty]");
      if (!tw || tw.classList.contains("empty")) return;
      toggleCollapsed(tw.closest("tr").dataset.id);
    });
    tbody.addEventListener("change", (e) => {
      const f = e.target.dataset.f;
      const tr = e.target.closest("tr[data-id]");
      if (!f || !tr) return;
      if (S.view === "tests") run(commitTestField)(tr.dataset.id, f, e.target.value);
      else run(commitField)(tr.dataset.id, f, e.target.value);
    });
    tbody.addEventListener("dragstart", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr || !e.target.classList.contains("rq-grip")) return;
      e.dataTransfer.setData("application/x-sysml-element", tr.dataset.id);
      e.dataTransfer.setData("application/x-sysml-requirement", tr.dataset.id);
      e.dataTransfer.setData("text/plain", tr.dataset.reqId || tr.dataset.id);
      e.dataTransfer.effectAllowed = "copyLink";
    });
    tbody.addEventListener("contextmenu", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr || S.view !== "requirements") return;
      e.preventDefault();
      selectRow(tr.dataset.id);
      openRowMenu(e.clientX, e.clientY);
    });
    tableWrap.addEventListener("keydown", onTableKey);
  }

  function toggleCollapsed(id) {
    if (S.collapsed.has(id)) S.collapsed.delete(id); else S.collapsed.add(id);
    if (S.view === "requirements") renderTable();
    renderDock();
  }

  function selectRow(id) {
    if (S.selId === id) return;
    S.selId = id;
    S.tm.element = id;   // the traceability diagram follows the latest selection
    for (const host of [tbody, dockBody]) {
      if (!host) continue;
      host.querySelectorAll("tr.sel").forEach((t) => t.classList.remove("sel"));
      host.querySelector(`tr[data-id="${CSS.escape(id)}"]`)?.classList.add("sel");
    }
    renderDetail();
    updateToolstrip();
    updateDockButtons();
  }

  function onTableKey(e) {
    const inText = e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA";
    const inSelect = e.target.tagName === "SELECT";
    const tr = e.target.closest("tr[data-id]");
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (S.view !== "requirements") return;
    if (e.altKey && e.shiftKey && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
      handled();
      run(moveSelected)({ ArrowUp: "up", ArrowDown: "down", ArrowRight: "indent", ArrowLeft: "outdent" }[e.key]);
      return;
    }
    if (e.key === "Insert") { handled(); run(addRequirement)(e.shiftKey); return; }
    if (e.key === "Escape" && inText && tr) {
      handled();
      const r = rowById(tr.dataset.id);
      e.target.value = (e.target.dataset.f === "id" ? r?.req_id : r?.[e.target.dataset.f]) || "";
      tableWrap.focus();
      return;
    }
    if ((e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") && !inSelect && !e.altKey && !e.ctrlKey) {
      if (e.key === "Enter" && !inText) return;
      const vis = [...tbody.querySelectorAll("tr[data-id]")];
      if (!vis.length) return;
      const cur = tr || tbody.querySelector(`tr[data-id="${CSS.escape(S.selId || "")}"]`);
      const i = cur ? vis.indexOf(cur) : -1;
      const next = e.key === "ArrowUp" ? i - 1 : i + 1;
      handled();
      if (next < 0 || next >= vis.length) {
        if (inText) tableWrap.focus();   // leaving the field commits it (change event)
        return;
      }
      const field = (inText && e.target.dataset.f) || "summary";
      selectRow(vis[next].dataset.id);
      vis[next].querySelector(`[data-f="${field}"]`)?.focus();
      return;
    }
    if (e.key === "F2" && !inText) {
      handled();
      tbody.querySelector(`tr[data-id="${CSS.escape(S.selId || "")}"] [data-f=summary]`)?.focus();
      return;
    }
    if (e.key === "Delete" && !inText && !inSelect) {
      // Keep the core "delete selected tree element" shortcut from firing here.
      handled();
      run(deleteSelected)();
    }
  }

  async function commitField(id, field, value) {
    const r = rowById(id);
    if (!r) return;
    const current = field === "id" ? r.req_id : r[field];
    if ((current ?? "") === value) return;
    // Typing the summary of a just-added requirement joins its creation's undo step.
    const created = S.createdReq === id && field === "summary" ? id : null;
    S.createdReq = null;
    try {
      await api("PATCH", `/api/req/requirements/${encodeURIComponent(id)}`, { [field]: value }, { undoMerge: created });
      studio.log(`Updated ${field} of ${r.req_id || r.summary}`, "ok");
    } finally {
      await afterChange({ tree: field === "summary" || field === "id" });
    }
  }

  // --- toolstrip actions ----------------------------------------------------
  function updateToolstrip() {
    if (!reqPane) return;
    const r = selRow();
    const has = !!r;
    const q = (k) => reqPane.querySelector(`[data-rq="${k}"]`);
    const siblings = has ? rows().filter((x) => x.parent_id === r.parent_id && x.set_id === r.set_id) : [];
    const i = has ? siblings.findIndex((x) => x.id === r.id) : -1;
    q("add").disabled = !targetSetId();
    q("add-child").disabled = !has;
    q("delete").disabled = !has;
    q("up").disabled = !has || i <= 0;
    q("down").disabled = !has || i === siblings.length - 1;
    q("indent").disabled = !has || i <= 0;
    q("outdent").disabled = !has || !r.parent_id;
    q("link-to").disabled = !has;
    q("link-from").disabled = !has;
    q("clear-suspect").disabled = !has || !r.suspect_count;
    q("set-props").disabled = !currentSet();
    q("add-test").disabled = !targetSetId();
    q("export").disabled = !sets().length;
    q("report").disabled = !sets().length;
    updateSelectionNote();
  }

  function updateSelectionNote() {
    const ids = studio.getSelection();
    const names = ids.map((id) => {
      const n = studio.state.treeIndex.get(id);
      return n ? `${n.name || "?"} (${n.kind})` : id.slice(0, 8);
    });
    const text = names.length ? `Selection: ${names.join(", ")}` : "Selection: none";
    for (const note of [selNote, dockEl?.querySelector('[data-dock="sel-note"]')]) {
      if (!note) continue;
      note.textContent = text;
      note.title = names.length ? `Current model selection: ${names.join(", ")}` : "Select a model element in the tree or on the canvas";
    }
  }

  async function newSetDialog() {
    openModal("New requirement set", `
      <label class="block text-sm">Name <input class="input" name="name" value="${esc(uniqueSetName())}" /></label>
      <label class="block text-sm">ID prefix <input class="input" name="prefix" value="REQ-" /></label>
      <label class="block text-sm">Description <textarea class="input h-16" name="description"></textarea></label>
    `, async (o) => {
      const s = await api("POST", "/api/req/sets", { name: o.name, prefix: o.prefix, description: o.description || null });
      S.setId = s.id; S.selId = null;
      studio.log(`Created requirement set ${s.name}`, "ok");
      await afterChange({ tree: true });
    });
  }
  const uniqueSetName = () => {
    const taken = new Set(sets().map((s) => s.name));
    let n = 1, name = "Requirements";
    while (taken.has(name)) name = `Requirements ${++n}`;
    return name;
  };

  async function setPropsDialog() {
    const s = currentSet();
    if (!s) return;
    openModal(`Requirement set ${s.name}`, `
      <label class="block text-sm">Name <input class="input" name="name" value="${esc(s.name)}" /></label>
      <label class="block text-sm">ID prefix <input class="input" name="prefix" value="${esc(s.prefix || "")}" /></label>
      <label class="block text-sm">Description <textarea class="input h-16" name="description">${esc(s.description || "")}</textarea></label>
      <label class="inline-flex items-center gap-2 text-sm text-red-700"><input type="checkbox" name="delete" /> Delete this set with its ${s.count} requirement(s) and their links</label>
    `, async (o) => {
      if (o.delete === "on") {
        await api("DELETE", `/api/element/${encodeURIComponent(s.id)}`);
        studio.log(`Deleted requirement set ${s.name}`, "warning");
        S.setId = ""; S.selId = null;
      } else {
        await api("PATCH", `/api/req/sets/${encodeURIComponent(s.id)}`, { name: o.name, prefix: o.prefix, description: o.description });
        studio.log(`Updated requirement set ${o.name}`, "ok");
      }
      await afterChange({ tree: true });
    });
  }

  async function addRequirement(child) {
    const r = selRow();
    let body;
    if (child) {
      if (!r) return;
      body = { parent: r.id };
      S.collapsed.delete(r.id);
    } else if (r) {
      body = { parent: r.parent_id || r.set_id, after: r.id };
    } else {
      const sid = targetSetId();
      if (!sid) { studio.log("Create a requirement set first (New Set).", "warning"); return; }
      body = { parent: sid };
    }
    const created = await api("POST", "/api/req/requirements", body);
    S.selId = created.id;
    S.createdReq = created.id;
    S.view = "requirements";
    studio.log(`Added requirement ${created.req_id}`, "ok");
    await afterChange({ tree: true });
    const input = tbody.querySelector(`tr[data-id="${CSS.escape(created.id)}"] [data-f=summary]`);
    input?.focus();
    input?.select();
  }

  async function deleteSelected() {
    const r = selRow();
    if (!r) return;
    const kids = rows().filter((x) => isDescendant(x, r.id)).length;
    confirmModal("Delete requirement", `Delete <b>${esc(reqLabel(r))}</b>${kids ? ` and its ${kids} child requirement(s)` : ""}? Links to ${kids ? "them" : "it"} are removed too.`,
      async () => {
        await api("DELETE", `/api/req/requirements/${encodeURIComponent(r.id)}`);
        studio.log(`Deleted ${reqLabel(r)}`, "warning");
        S.selId = null;
        await afterChange({ tree: true });
        tableWrap.focus();
      });
  }
  const isDescendant = (row, ancestorId) => {
    for (let p = row.parent_id; p; p = rowById(p)?.parent_id) if (p === ancestorId) return true;
    return false;
  };

  async function moveSelected(direction) {
    const r = selRow();
    if (!r) return;
    await api("POST", `/api/req/requirements/${encodeURIComponent(r.id)}/move`, { direction });
    await afterChange({ tree: true });
    tbody.querySelector(`tr[data-id="${CSS.escape(r.id)}"] [data-f=summary]`)?.focus();
  }

  async function linkWithSelection(mode) {
    const r = selRow();
    if (!r) return;
    const ids = studio.getSelection().filter((id) => id !== r.id);
    if (!ids.length) {
      studio.log("Select a model element first (containment tree or canvas), then the requirement.", "warning");
      return;
    }
    const type = S.linkType;
    const body = (mode === "from" || ELEMENT_IS_SOURCE.has(type))
      ? { type, sources: ids, target: r.id }
      : { type, source: r.id, targets: ids };
    const out = await api("POST", "/api/req/links/batch", body);
    for (const l of out.created) studio.log(`Linked: ${otherLabel(l.source)} ${l.verb} ${otherLabel(l.target)}`, "ok");
    for (const m of out.errors) studio.log(`Not linked: ${m}`, "warning");
    await afterChange({ tree: true });
  }

  async function clearSuspectSelected() {
    const r = selRow();
    if (!r) return;
    const out = await api("POST", "/api/req/clear-suspect", { element: r.id });
    studio.log(`Cleared ${out.cleared} suspect link(s) of ${reqLabel(r)}`, "ok");
    await afterChange();
  }

  // --- detail panel ---------------------------------------------------------
  function renderDetail() {
    if (!detailEl) return;
    detailEl.style.height = `${S.detailH}px`;
    if (S.view === "tests") {
      detailEl.innerHTML = `<div class="rq-empty" style="padding:8px">Set a test case result to drive verification status; add <b>Verify</b> links from the <i>Verifies</i> column or the Traceability matrix (columns: Test cases).</div>`;
      return;
    }
    const r = selRow();
    if (!r) {
      detailEl.dataset.rowId = "";
      detailEl.innerHTML = `<div class="rq-empty" style="padding:8px">Select a requirement to edit its description, rationale and links. Tip: select a component in the tree, then a requirement, then <b>Link to Selection</b>.</div>`;
      return;
    }
    // Re-rendering the same requirement keeps the focused field and its uncommitted text.
    const a = document.activeElement;
    const keep = a && detailEl.contains(a) && a.dataset.d && detailEl.dataset.rowId === r.id
      ? { d: a.dataset.d, value: a.value, start: a.selectionStart, end: a.selectionEnd } : null;
    detailEl.dataset.rowId = r.id;
    const stereo = (r.stereotypes || []).map((s) =>
      `<div><span class="rq-chip">«${esc(s.name)}»</span> ${Object.entries(s.values || {}).map(([k, v]) => `${esc(k)} = <b>${esc(v ?? "")}</b>`).join(", ")}</div>`).join("");
    const tcs = S.table?.test_cases || [];
    detailEl.innerHTML = `
      <div class="rq-detail-head">
        <b data-rq="detail-title">${esc(reqLabel(r))}</b>
        <span class="text-slate-500">${esc(r.qualified_name)}</span>
        <span class="flex-1"></span>
        <button class="rq-mini" data-rq="d-nav" title="Select in the containment tree">Show in tree</button>
        <button class="rq-mini" data-rq="d-props" title="Open in the Properties tab (stereotypes and custom attributes)">Properties</button>
        <button class="rq-mini" data-rq="d-diagram" title="Open the traceability diagram around this requirement">Trace diagram</button>
        <button class="rq-mini" data-rq="d-highlight" title="Highlight linked elements on the canvas">Highlight links</button>
      </div>
      <div class="rq-detail-grid">
        <div>
          <label>Summary <input class="input" data-d="summary" value="${esc(r.summary || "")}" /></label>
          <label>Description <textarea class="input" rows="4" data-d="description" placeholder="The system shall …">${esc(r.description || "")}</textarea></label>
          <label>Rationale <textarea class="input" rows="2" data-d="rationale">${esc(r.rationale || "")}</textarea></label>
          ${stereo ? `<div class="mt-1"><div class="text-slate-500 text-xs mb-1">Custom attributes (stereotypes; edit them under <b>Properties</b>)</div>${stereo}</div>` : ""}
        </div>
        <div>
          <div class="flex items-center gap-2 mb-1"><span class="w-24 text-slate-500">Implementation</span>${implBar(r.implementation)}</div>
          <div class="flex items-center gap-2 mb-2"><span class="w-24 text-slate-500">Verification</span>${verBar(r.verification)}<span class="text-slate-500">${esc(r.verification.state)}</span></div>
          <div class="text-slate-500 text-xs mb-1">Links</div>
          <div class="rq-links" data-rq="detail-links"><span class="text-slate-400">Loading…</span></div>
          <div class="flex items-center gap-1 mt-2">
            <select class="rq-small-select" data-rq="d-tc" title="Test case">${opt("", tcs.length ? "Verified by test case…" : "No test cases in view")}${tcs.map((t) => opt(t.id, `${t.name} (${t.result})`)).join("")}</select>
            <button class="rq-mini" data-rq="d-verify" ${tcs.length ? "" : "disabled"}>Add Verify link</button>
          </div>
        </div>
      </div>`;
    const q = (k) => detailEl.querySelector(`[data-rq="${k}"]`);
    detailEl.querySelectorAll("[data-d]").forEach((el) => {
      el.addEventListener("change", () => run(commitField)(r.id, el.dataset.d, el.value));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || el.tagName === "INPUT")) { e.preventDefault(); el.blur(); }
      });
    });
    q("d-nav").onclick = () => studio.emit("navigate", { id: r.id });
    q("d-props").onclick = () => { studio.emit("navigate", { id: r.id }); studio.switchTab("properties"); };
    q("d-diagram").onclick = () => run(openDiagramFor)(r.id);
    q("d-highlight").onclick = () => highlightLinks(r.id, S.detailLinks);
    q("d-verify").onclick = run(async () => {
      const tc = q("d-tc").value;
      if (!tc) { studio.log("Choose a test case first.", "warning"); return; }
      await api("POST", "/api/req/links", { type: "verify", source: tc, target: r.id });
      studio.log(`Verify link added to ${reqLabel(r)}`, "ok");
      await afterChange();
    });
    if (keep) {
      const el = detailEl.querySelector(`[data-d="${keep.d}"]`);
      if (el) {
        el.value = keep.value;
        el.focus();
        try { el.setSelectionRange(keep.start, keep.end); } catch { /* not a text field */ }
      }
    }
    run(loadDetailLinks)(r.id);
  }

  async function loadDetailLinks(id) {
    const token = ++S.detailToken;
    const data = await api("GET", `/api/req/links?element=${encodeURIComponent(id)}`);
    if (token !== S.detailToken) return;
    S.detailLinks = data.links;
    const host = detailEl.querySelector('[data-rq="detail-links"]');
    if (host) renderLinkList(host, data.links);
  }

  // Shared by the detail panel and the inspector section.
  function renderLinkList(host, links) {
    if (!links.length) {
      host.innerHTML = `<span class="text-slate-400">No links yet.</span>`;
      return;
    }
    host.innerHTML = links.map((l) => {
      const verb = l.direction === "outgoing" ? OUTGOING[l.type] : INCOMING[l.type];
      const arrow = l.direction === "outgoing" ? "→" : "←";
      const sus = l.suspect
        ? `<span class="rq-warn" title="The requirement text changed after this link was made (${esc(l.suspect_ends.join(", "))})">⚠ suspect</span>
           <button class="rq-mini" data-act="clear" data-link="${esc(l.id)}" title="Mark the link as reviewed">Clear</button>` : "";
      return `<div class="rq-link${l.suspect ? " suspect" : ""}" data-link-id="${esc(l.id)}" data-type="${esc(l.type)}" data-suspect="${l.suspect}">
        ${chip(l.type)} <span class="rq-verb">${arrow} ${esc(verb)}</span>
        <a class="rq-a" data-act="nav" data-id="${esc(l.other.id)}" title="${esc(l.other.qualified_name)} (${esc(l.other.kind)})">${esc(otherLabel(l.other))}</a>
        ${sus}<button class="rq-x" data-act="del" data-link="${esc(l.id)}" title="Delete this link" aria-label="Delete link">✕</button></div>`;
    }).join("");
    host.onclick = run((e) => onLinkAction(e, links));
  }

  // Click on [data-act] inside a link list: nav (navigate), clear (suspect flag), del (delete link).
  async function onLinkAction(e, links) {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    if (b.dataset.act === "nav") { studio.emit("navigate", { id: b.dataset.id }); return; }
    if (b.dataset.act === "clear") {
      await api("POST", `/api/req/links/${encodeURIComponent(b.dataset.link)}/clear-suspect`);
      studio.log("Suspect flag cleared", "ok");
      await afterChange();
    }
    if (b.dataset.act === "del") {
      const l = links.find((x) => x.id === b.dataset.link);
      if (!l) return;
      confirmModal("Delete link", `Delete the link <b>${esc(otherLabel(l.source))}</b> ${esc(l.verb)} <b>${esc(otherLabel(l.target))}</b>?`, async () => {
        await api("DELETE", `/api/req/links/${encodeURIComponent(l.id)}`);
        studio.log(`Deleted ${l.label} link`, "warning");
        await afterChange({ tree: true });
      });
    }
  }

  // --- links view (System Composer "Show Links": every link with change information) ---------
  const changeInfo = (l) => {
    if (l.suspect) {
      const what = l.suspect_ends.map((end) => (end === "source" ? "Source changed" : "Destination changed")).join(", ");
      return `<span class="rq-warn" title="The requirement text changed after the link was made">⚠ ${esc(what)}</span>`;
    }
    return `<span class="text-slate-400">${l.tracked ? "No change" : "Not tracked yet"}</span>`;
  };

  function renderLinksView() {
    theadRow.innerHTML = `<th style="width:118px">Type</th><th>Source</th><th style="width:120px">Relationship</th>
      <th>Destination</th><th style="width:190px">Change information</th><th style="width:90px"></th>`;
    const text = S.filter.text.trim().toLowerCase();
    const all = S.links || [];
    const list = all.filter((l) => (!S.linksSuspectOnly || l.suspect)
      && (!text || [otherLabel(l.source), otherLabel(l.target), l.label].some((v) => v.toLowerCase().includes(text))));
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="rq-empty">${all.length ? "No link matches the filter."
        : "No trace links yet. Use <b>Link to Selection</b>, drag a requirement onto a model element, or click a cell in the Traceability matrix."}</div></td></tr>`;
      return;
    }
    const end = (o) => `<a class="rq-a" data-act="nav" data-id="${esc(o.id)}" title="${esc(o.qualified_name)} (${esc(o.kind)})">${esc(otherLabel(o))}</a>`;
    tbody.innerHTML = list.map((l) => `
      <tr class="rq-linkrow${l.suspect ? " suspect" : ""}" data-link-id="${esc(l.id)}" data-type="${esc(l.type)}" data-suspect="${l.suspect}">
        <td class="rq-pad">${chip(l.type)}</td>
        <td class="rq-pad">${end(l.source)}</td>
        <td class="rq-pad text-slate-500">${esc(l.verb)} →</td>
        <td class="rq-pad">${end(l.target)}</td>
        <td class="rq-pad">${changeInfo(l)}</td>
        <td class="rq-pad" style="text-align:right">${l.suspect ? `<button class="rq-mini" data-act="clear" data-link="${esc(l.id)}" title="Mark the link as reviewed">Clear</button>` : ""}<button class="rq-x" data-act="del" data-link="${esc(l.id)}" title="Delete this link" aria-label="Delete link">✕</button></td>
      </tr>`).join("");
  }

  function highlightLinks(id, links) {
    const ids = [id, ...(links || []).map((l) => l.other.id)];
    studio.emit("highlight", { ids, color: "#f59e0b", reason: "trace" });
    studio.log(`Highlighted ${ids.length - 1} linked element(s)`, "info");
  }

  // --- test cases view -------------------------------------------------------
  function renderTests() {
    theadRow.innerHTML = `<th style="width:220px">Test case</th><th>Description</th><th style="width:120px">Result</th><th>Verifies</th><th style="width:40px"></th>`;
    const tcs = S.table?.test_cases || [];
    if (!tcs.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="rq-empty">No test cases. Click <b>Test Case</b> to add one, then link it to requirements with <b>Verify</b>.</div></td></tr>`;
      return;
    }
    const reqs = rows();
    tbody.innerHTML = tcs.map((t) => `
      <tr class="rq-row" data-id="${esc(t.id)}">
        <td><input data-f="name" value="${esc(t.name || "")}" aria-label="Test case name" /></td>
        <td><input data-f="description" value="${esc(t.description || "")}" aria-label="Description" /></td>
        <td><select data-f="result" aria-label="Result">${meta.test_results.map((v) => opt(v, v, v === t.result)).join("")}</select></td>
        <td style="padding:0 4px">${t.verifies.map((v) => `<span class="rq-chip t-verify" data-link="${esc(v.link_id)}">${esc(v.req_id || "")} ${v.suspect ? "⚠" : ""}<button class="rq-x" data-act="unverify" data-link="${esc(v.link_id)}" title="Remove Verify link">✕</button></span>`).join(" ")}
          <select class="rq-small-select" data-act="verify" aria-label="Add verified requirement">${opt("", "+ verifies…")}${reqs.map((r) => opt(r.id, reqLabel(r))).join("")}</select></td>
        <td><button class="rq-x" data-act="del-tc" title="Delete test case" aria-label="Delete test case">✕</button></td>
      </tr>`).join("");
    tbody.querySelectorAll("[data-act=verify]").forEach((sel) => sel.addEventListener("change", run(async () => {
      if (!sel.value) return;
      const tc = sel.closest("tr").dataset.id;
      await api("POST", "/api/req/links", { type: "verify", source: tc, target: sel.value });
      await afterChange();
    })));
    tbody.querySelectorAll("[data-act=unverify]").forEach((b) => b.addEventListener("click", run(async () => {
      await api("DELETE", `/api/req/links/${encodeURIComponent(b.dataset.link)}`);
      await afterChange();
    })));
    tbody.querySelectorAll("[data-act=del-tc]").forEach((b) => b.addEventListener("click", () => {
      const t = tcs.find((x) => x.id === b.closest("tr").dataset.id);
      confirmModal("Delete test case", `Delete test case <b>${esc(t.name)}</b> and its Verify links?`, async () => {
        await api("DELETE", `/api/req/test-cases/${encodeURIComponent(t.id)}`);
        await afterChange({ tree: true });
      });
    }));
  }

  async function commitTestField(id, field, value) {
    if (!["name", "description", "result"].includes(field)) return;
    try {
      await api("PATCH", `/api/req/test-cases/${encodeURIComponent(id)}`, { [field]: value });
      studio.log(`Updated test case ${field}`, "ok");
    } finally {
      await afterChange({ tree: field === "name" });
    }
  }

  async function addTestCaseDialog() {
    const sid = targetSetId();
    if (!sid) { studio.log("Create a requirement set first.", "warning"); return; }
    const r = selRow();
    openModal("New test case", `
      <label class="block text-sm">Name <input class="input" name="name" value="Test ${(S.table?.test_cases || []).length + 1}" /></label>
      <label class="block text-sm">Description <textarea class="input h-16" name="description"></textarea></label>
      <label class="block text-sm">Result <select class="input" name="result">${meta.test_results.map((v) => opt(v, v)).join("")}</select></label>
      ${r ? `<label class="inline-flex items-center gap-2 text-sm"><input type="checkbox" name="verify" checked /> Verifies ${esc(reqLabel(r))}</label>` : ""}
    `, async (o) => {
      const tc = await api("POST", "/api/req/test-cases", { parent: sid, name: o.name, description: o.description || null, result: o.result });
      if (r && o.verify === "on") await api("POST", "/api/req/links", { type: "verify", source: tc.id, target: r.id });
      studio.log(`Added test case ${tc.name}`, "ok");
      await afterChange({ tree: true });
    });
  }

  // --- context menu -----------------------------------------------------------
  let menuEl = null;
  function closeMenu() { menuEl?.remove(); menuEl = null; }
  function openRowMenu(x, y) {
    const r = selRow();
    if (!r) return;
    const type = typeMeta[S.linkType];
    const items = [
      ["Add requirement after", () => addRequirement(false)],
      ["Add child requirement", () => addRequirement(true)],
      null,
      ...meta.link_types.map((t) => [`Link to Selection as ${t.label}`, () => { setLinkType(t.name); return linkWithSelection("to"); }]),
      [`Link from Selection (${type.label})`, () => linkWithSelection("from")],
      null,
      ["Indent", () => moveSelected("indent"), !!reqPane.querySelector('[data-rq="indent"]').disabled],
      ["Outdent", () => moveSelected("outdent"), !r.parent_id],
      ["Move up", () => moveSelected("up"), !!reqPane.querySelector('[data-rq="up"]').disabled],
      ["Move down", () => moveSelected("down"), !!reqPane.querySelector('[data-rq="down"]').disabled],
      null,
      ["Show traceability diagram", () => openDiagramFor(r.id)],
      ["Show in containment tree", () => studio.emit("navigate", { id: r.id })],
      ["Clear suspect links", clearSuspectSelected, !r.suspect_count],
      null,
      ["Delete", deleteSelected],
    ];
    closeMenu();
    menuEl = document.createElement("div");
    menuEl.className = "rq-menu";
    menuEl.setAttribute("role", "menu");
    menuEl.dataset.rq = "context-menu";
    items.forEach((it) => {
      if (!it) { menuEl.appendChild(document.createElement("hr")); return; }
      const b = document.createElement("button");
      b.textContent = it[0];
      b.disabled = !!it[2];
      b.setAttribute("role", "menuitem");
      b.onclick = () => { closeMenu(); run(it[1])(); };
      menuEl.appendChild(b);
    });
    document.body.appendChild(menuEl);
    const rect = menuEl.getBoundingClientRect();
    menuEl.style.left = `${Math.min(x, window.innerWidth - rect.width - 4)}px`;
    menuEl.style.top = `${Math.min(y, window.innerHeight - rect.height - 4)}px`;
    menuEl.querySelector("button:not(:disabled)")?.focus();
    menuEl.addEventListener("keydown", (e) => {
      const btns = [...menuEl.querySelectorAll("button:not(:disabled)")];
      const i = btns.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); closeMenu(); tableWrap.focus(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); btns[(i + 1) % btns.length]?.focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length]?.focus(); }
    });
  }
  document.addEventListener("mousedown", (e) => { if (menuEl && !menuEl.contains(e.target)) closeMenu(); });

  // --- import / export ----------------------------------------------------------
  async function importDialog() {
    openModal("Import requirements", `
      <label class="block text-sm">File (CSV with columns id, summary, description, type, priority, parent_id — or ReqIF 1.2 .reqif)
        <input class="input" type="file" name="file" accept=".csv,.txt,.reqif,.xml" /></label>
      <label class="block text-sm">Format <select class="input" name="format"><option value="auto">Detect from file</option><option value="csv">CSV</option><option value="reqif">ReqIF</option></select></label>
      <label class="block text-sm">Into <select class="input" name="set">${opt("", "A new set")}${sets().map((s) => opt(s.id, s.name, s.id === S.setId)).join("")}</select></label>
      <label class="block text-sm">New set name (when importing into a new set) <input class="input" name="new_set" placeholder="Taken from the ReqIF title or the file name" /></label>
      <p class="text-xs text-slate-500">Requirements whose ID already exists in the set are updated; the others are created.</p>
    `, async (o) => {
      const file = o.file;
      if (!file || !file.name) throw new Error("Choose a file to import.");
      const text = await file.text();
      let format = o.format;
      if (format === "auto") format = /\.(reqif|xml)$/i.test(file.name) || text.trimStart().startsWith("<") ? "reqif" : "csv";
      const body = { format, text };
      if (o.set) body.set = o.set; else body.new_set = o.new_set || (format === "csv" ? file.name.replace(/\.[^.]+$/, "") : null);
      const rep = await api("POST", "/api/req/import", body);
      studio.log(`Imported ${rep.created} new and ${rep.updated} updated requirement(s) into ${rep.set}${rep.linked ? `, ${rep.linked} link(s)` : ""}`, "ok");
      for (const w of rep.warnings || []) studio.log(`  ${w}`, "warning");
      S.setId = rep.set_id;
      await afterChange({ tree: true });
    });
  }

  async function exportDialog() {
    openModal("Export requirements", `
      <label class="block text-sm">Format <select class="input" name="format">
        <option value="csv">Requirements · CSV</option>
        <option value="reqif">Requirements · ReqIF 1.2 (.reqif)</option>
        <option value="report-html">Traceability report · HTML</option>
        <option value="report-csv">Traceability report · CSV</option>
      </select></label>
      <label class="block text-sm">Set <select class="input" name="set">${opt("", "All sets")}${sets().map((s) => opt(s.id, s.name, s.id === S.setId)).join("")}</select></label>
    `, async (o) => downloadExport(o.format, o.set));
  }

  async function downloadExport(format, setId, columns) {
    const p = new URLSearchParams({ format });
    if (setId) p.set("set", setId);
    if (columns) p.set("columns", columns);
    const out = await api("GET", `/api/req/export?${p}`);
    studio.download(out.filename, out.text);
    studio.log(`Exported ${out.filename}`, "ok");
  }

  // ------------------------------------------------------------------ Traceability tab
  let tmPane, tmBody;
  tmPane = studio.registerTab({
    id: "traceability", title: "Traceability", order: 45,
    mount(pane) {
      tmPane = pane;
      pane.innerHTML = `
      <div class="rq-root" data-tm="root">
        <div class="rq-toolstrip" role="toolbar" aria-label="Traceability toolstrip">
          <div class="rq-ts-section"><div class="rq-ts-buttons"><div class="rq-ts-col">
            <select class="rq-ts-select" data-tm="set" title="Rows: requirements of this set"></select>
            <span class="rq-ts-note">rows</span></div></div><div class="rq-ts-label">Requirements</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons"><div class="rq-ts-col">
            <select class="rq-ts-select" data-tm="columns" title="Columns">${meta.column_kinds.map((k) => opt(k.key, k.label, k.key === S.tm.columns)).join("")}</select>
            <select class="rq-ts-select" data-tm="column-set" title="Requirement set used for columns"></select></div></div><div class="rq-ts-label">Columns</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-tm="view-matrix"><span class="rq-ts-icon">▦</span>Matrix</button>
            <button class="rq-ts-btn" data-tm="view-diagram"><span class="rq-ts-icon">⇄</span>Diagram</button>
            <div class="rq-ts-col"><select class="rq-ts-select" data-tm="element" title="Diagram focus element"></select>
              <select class="rq-ts-select" data-tm="depth" title="Diagram depth">${["1", "2", "3"].map((d) => opt(d, `Depth ${d}`, d === S.tm.depth)).join("")}</select></div>
          </div><div class="rq-ts-label">View</div></div>
          <div class="rq-ts-section"><div class="rq-ts-buttons">
            <button class="rq-ts-btn" data-tm="export-csv" title="Download the matrix as CSV"><span class="rq-ts-icon">⭱</span>Matrix CSV</button>
            <button class="rq-ts-btn" data-tm="report-html" title="Traceability report (HTML)"><span class="rq-ts-icon">▤</span>Report</button>
            <button class="rq-ts-btn" data-tm="report-csv" title="Traceability report (CSV)"><span class="rq-ts-icon">≡</span>Report CSV</button>
          </div><div class="rq-ts-label">Share</div></div>
        </div>
        <div class="rq-legend" data-tm="legend">${meta.link_types.map((t) =>
          `<span title="${esc(t.description)}">${chip(t.name)} ${esc(shortRule(t.source))} → ${esc(shortRule(t.target))}</span>`).join("")}
          <span><span style="background:#fef3c7;padding:0 4px">amber</span> = not linked</span><span>⚠ dashed = suspect</span></div>
        <div class="rq-tm-body" data-tm="body"></div>
      </div>`;
      const q = (k) => pane.querySelector(`[data-tm="${k}"]`);
      tmBody = q("body");
      q("set").addEventListener("change", run(async (e) => { S.tm.setId = e.target.value; await loadTraceability(); }));
      q("columns").addEventListener("change", run(async (e) => { S.tm.columns = e.target.value; await loadTraceability(); }));
      q("column-set").addEventListener("change", run(async (e) => { S.tm.columnSet = e.target.value; await loadTraceability(); }));
      q("view-matrix").addEventListener("click", run(async () => { S.tm.view = "matrix"; await loadTraceability(); }));
      q("view-diagram").addEventListener("click", run(async () => { S.tm.view = "diagram"; await loadTraceability(); }));
      q("element").addEventListener("change", run(async (e) => { S.tm.element = e.target.value; await loadTraceability(); }));
      q("depth").addEventListener("change", run(async (e) => { S.tm.depth = e.target.value; await loadTraceability(); }));
      q("export-csv").addEventListener("click", run(() => downloadExport("matrix-csv", S.tm.setId, S.tm.columns)));
      q("report-html").addEventListener("click", run(() => downloadExport("report-html", S.tm.setId)));
      q("report-csv").addEventListener("click", run(() => downloadExport("report-csv", S.tm.setId)));
      tmBody.addEventListener("click", run(onMatrixClick));
    },
    onShow() { S.visible.tm = true; run(loadTraceability)(); },
  });

  async function loadTraceability() {
    if (!tmPane) return;
    if (!S.table) await loadTable();
    if (S.tm.setId === null) S.tm.setId = S.setId || sets()[0]?.id || "";
    if (S.tm.setId && !sets().some((s) => s.id === S.tm.setId)) S.tm.setId = sets()[0]?.id || "";
    const q = (k) => tmPane.querySelector(`[data-tm="${k}"]`);
    q("set").innerHTML = opt("", "All sets", !S.tm.setId) + sets().map((s) => opt(s.id, s.name, s.id === S.tm.setId)).join("");
    q("column-set").innerHTML = opt("", "All sets", !S.tm.columnSet) + sets().map((s) => opt(s.id, s.name, s.id === S.tm.columnSet)).join("");
    q("column-set").style.display = S.tm.columns === "requirements" ? "" : "none";
    q("view-matrix").classList.toggle("on", S.tm.view === "matrix");
    q("view-diagram").classList.toggle("on", S.tm.view === "diagram");
    q("element").style.display = q("depth").style.display = S.tm.view === "diagram" ? "" : "none";
    S.dirty.tm = false;
    if (!sets().length) {
      tmBody.innerHTML = `<div class="rq-empty">No requirement sets yet. Create one in the Requirements tab.</div>`;
      return;
    }
    if (S.tm.view === "diagram") await renderDiagram(); else await renderMatrix();
  }

  async function renderMatrix() {
    const p = new URLSearchParams({ columns: S.tm.columns });
    if (S.tm.setId) p.set("set", S.tm.setId);
    if (S.tm.columns === "requirements" && S.tm.columnSet) p.set("column_set", S.tm.columnSet);
    const m = await api("GET", `/api/req/matrix?${p}`);
    S.tm.data = m;
    const kindLabel = meta.column_kinds.find((k) => k.key === m.columns_kind)?.label || m.columns_kind;
    if (!m.rows.length || !m.columns.length) {
      tmBody.innerHTML = `<div class="rq-empty">${!m.rows.length ? "No requirements in this set." : `No ${esc(kindLabel.toLowerCase())} in the model yet.`}</div>`;
      return;
    }
    const cells = new Map(m.cells.map((c) => [`${c.row}|${c.col}`, c.links]));
    const unlinkedRows = new Set(m.unlinked_rows), unlinkedCols = new Set(m.unlinked_columns);
    const head = m.columns.map((c) => `<th class="${unlinkedCols.has(c.id) ? "unlinked" : ""}" data-col="${esc(c.id)}" title="${esc(c.qualified_name)} (${esc(c.kind)})${unlinkedCols.has(c.id) ? " — not linked" : ""}"><div class="rq-vert">${esc(c.label)}</div></th>`).join("");
    const body = m.rows.map((r) => {
      const tds = m.columns.map((c) => {
        if (c.id === r.id) return `<td class="rq-cell self" title="Same requirement"></td>`;
        const links = cells.get(`${r.id}|${c.id}`) || [];
        const icons = links.map((l) => `<span class="rq-mlink${l.suspect ? " suspect" : ""}" data-link="${esc(l.id)}" title="${esc(otherLabel(l.source))} ${esc(l.verb)} ${esc(otherLabel(l.target))}${l.suspect ? " — SUSPECT" : ""}. Click to delete.">${ICONS[l.type] || "•"}${l.suspect ? "⚠" : ""}</span>`).join("");
        return `<td class="rq-cell" data-row="${esc(r.id)}" data-col="${esc(c.id)}" title="${links.length ? "" : "Click to create a link"}">${icons}</td>`;
      }).join("");
      return `<tr><th class="rq-rowhead${unlinkedRows.has(r.id) ? " unlinked" : ""}" data-row-head="${esc(r.id)}" style="padding-left:${8 + 14 * r.depth}px" title="${esc(r.summary || "")}${unlinkedRows.has(r.id) ? " — not linked" : ""}">${esc(r.index)} <b>${esc(r.req_id || "")}</b> ${esc(r.summary || "")}</th>${tds}</tr>`;
    }).join("");
    tmBody.innerHTML = `<table class="rq-matrix" data-tm="matrix"><thead><tr><th class="corner">Requirements ╲ ${esc(kindLabel)} <span class="text-xs">(${m.unlinked_rows.length} unlinked row(s), ${m.unlinked_columns.length} unlinked column(s))</span></th>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  async function onMatrixClick(e) {
    const icon = e.target.closest(".rq-mlink");
    const m = S.tm.data;
    if (icon && m) {
      const link = m.cells.flatMap((c) => c.links).find((l) => l.id === icon.dataset.link);
      if (!link) return;
      confirmModal("Delete link", `Delete <b>${esc(otherLabel(link.source))}</b> ${esc(link.verb)} <b>${esc(otherLabel(link.target))}</b>?${link.suspect ? " <span class='rq-warn'>(suspect)</span>" : ""}`, async () => {
        await api("DELETE", `/api/req/links/${encodeURIComponent(link.id)}`);
        studio.log(`Deleted ${link.label} link`, "warning");
        await afterChange({ tree: true });
      });
      return;
    }
    const head = e.target.closest("[data-row-head]");
    if (head) { studio.emit("navigate", { id: head.dataset.rowHead }); return; }
    const td = e.target.closest("td.rq-cell[data-row]");
    if (!td || !m) return;
    const row = m.rows.find((r) => r.id === td.dataset.row);
    const col = m.columns.find((c) => c.id === td.dataset.col);
    if (row && col) cellLinkDialog(row, col, m.columns_kind);
  }

  function cellLinkDialog(row, col, kind) {
    const R = { id: row.id, label: `${row.req_id || ""} ${row.summary || ""}`.trim() };
    const C = { id: col.id, label: col.label };
    let choices;
    if (kind === "requirements") {
      choices = [["derive", R, C], ["derive", C, R], ["refine", R, C], ["refine", C, R], ["relate", R, C]];
    } else if (kind === "test-cases") {
      choices = [["verify", C, R], ["confirm", C, R], ["relate", R, C]];
    } else {
      choices = [["implement", C, R], ["confirm", C, R], ["relate", R, C]];
    }
    const options = choices.map(([t, s, d], i) =>
      opt(`${t}|${s.id}|${d.id}`, `${ICONS[t]} ${typeMeta[t].label}: ${s.label} ${OUTGOING[t]} ${d.label}`, i === 0)).join("");
    openModal("Create trace link", `
      <p class="text-sm text-slate-600">Row <b>${esc(R.label)}</b> × column <b>${esc(C.label)}</b></p>
      <label class="block text-sm">Link type and direction <select class="input" name="choice" data-tm="choice">${options}</select></label>
    `, async (o) => {
      const [type, source, target] = o.choice.split("|");
      const l = await api("POST", "/api/req/links", { type, source, target });
      studio.log(`Linked: ${otherLabel(l.source)} ${l.verb} ${otherLabel(l.target)}`, "ok");
      await afterChange({ tree: true });
    });
  }

  let mermaidSeq = 0;
  async function renderDiagram() {
    const q = (k) => tmPane.querySelector(`[data-tm="${k}"]`);
    const candidates = rows();
    const sel = studio.getSelection()[0];
    const selNode = sel ? studio.state.treeIndex.get(sel) : null;
    const exists = (id) => !!id && (candidates.some((r) => r.id === id) || studio.state.treeIndex.has(id));
    if (!exists(S.tm.element)) S.tm.element = (exists(S.selId) && S.selId) || candidates[0]?.id || "";
    let optsHtml = candidates.map((r) => opt(r.id, reqLabel(r), r.id === S.tm.element)).join("");
    if (selNode && !candidates.some((r) => r.id === sel)) optsHtml = opt(sel, `Selection: ${selNode.name}`, sel === S.tm.element) + optsHtml;
    if (S.tm.element && !candidates.some((r) => r.id === S.tm.element) && S.tm.element !== sel) {
      const n = studio.state.treeIndex.get(S.tm.element);
      optsHtml = opt(S.tm.element, n?.name || S.tm.element, true) + optsHtml;
    }
    q("element").innerHTML = optsHtml;
    if (!S.tm.element) { tmBody.innerHTML = `<div class="rq-empty">Choose an element.</div>`; return; }
    const d = await api("GET", `/api/req/diagram?element=${encodeURIComponent(S.tm.element)}&depth=${S.tm.depth}`);
    const id = `rqm${++mermaidSeq}`;
    tmBody.innerHTML = `<div class="rq-diagram" data-tm="diagram"><div class="mermaid" id="${id}">${esc(d.text)}</div></div>
      <div class="rq-diagram-nodes">${d.nodes.map((n) => `<button class="rq-mini" data-nav="${esc(n.id)}" title="${esc(n.kind)}">${esc(n.label)}</button>`).join("")}
      ${d.truncated ? `<span class="rq-warn">Diagram truncated</span>` : ""}</div>`;
    tmBody.querySelectorAll("[data-nav]").forEach((b) => { b.onclick = () => studio.emit("navigate", { id: b.dataset.nav }); });
    try { await window.mermaid.run({ nodes: [tmBody.querySelector(`#${id}`)] }); }
    catch (err) { tmBody.querySelector(".rq-diagram").innerHTML = `<pre class="text-xs text-red-700 whitespace-pre-wrap">${esc(String(err))}\n\n${esc(d.text)}</pre>`; }
  }

  async function openDiagramFor(id) {
    S.tm.view = "diagram";
    S.tm.element = id;
    studio.switchTab("traceability");
  }

  // ------------------------------------------------------------------ inspector section
  studio.registerInspectorSection({
    id: "requirements-links", title: "Requirements links", order: 40,
    render(el, box) {
      if (!el?.traceable) { S.insp = null; return false; }
      S.insp = { el, box };
      run(renderInspector)();
      return undefined;
    },
  });

  async function renderInspector() {
    const ctx = S.insp;
    if (!ctx || !ctx.box.isConnected) return;
    const { el, box } = ctx;
    box.innerHTML = `
      <div class="flex flex-wrap gap-1 mb-2">
        <button class="rq-mini" data-insp="link">＋ Link requirement…</button>
        <button class="rq-mini" data-insp="highlight" title="Highlight linked elements on the canvas">Highlight on canvas</button>
        <button class="rq-mini" data-insp="diagram">Trace diagram</button>
      </div>
      <div class="rq-links" data-insp="links"><span class="text-slate-400 text-xs">Loading…</span></div>`;
    let data;
    try { data = await api("GET", `/api/req/links?element=${encodeURIComponent(el.id)}`); }
    catch { return; }
    if (S.insp !== ctx || !box.isConnected) return;
    renderLinkList(box.querySelector('[data-insp="links"]'), data.links);
    box.querySelector('[data-insp="highlight"]').onclick = () => highlightLinks(el.id, data.links);
    box.querySelector('[data-insp="diagram"]').onclick = () => run(openDiagramFor)(el.id);
    box.querySelector('[data-insp="link"]').onclick = run(() => linkRequirementDialog(el));
  }

  // Requirements of every set (the Requirements tab may be showing just one), grouped by set.
  async function allRequirementOptions(excludeId) {
    const t = await api("GET", "/api/req/table");
    const groups = t.sets.map((s) => {
      const items = t.rows.filter((r) => r.set_id === s.id && r.id !== excludeId);
      return items.length ? `<optgroup label="${esc(s.name)}">${items.map((r) =>
        opt(r.id, `${"  ".repeat(r.depth)}${reqLabel(r)}`)).join("")}</optgroup>` : "";
    }).join("");
    return { html: groups, count: t.rows.filter((r) => r.id !== excludeId).length };
  }

  async function linkRequirementDialog(el) {
    const all = await allRequirementOptions(el.id);
    if (!all.count) { studio.log("There are no requirements to link to yet.", "warning"); return; }
    const category = el.requirement ? "requirement" : (el.verification_result ? "test" : "design");
    const types = category === "requirement" ? ["derive", "refine", "relate", "confirm"]
      : category === "test" ? ["verify", "confirm", "relate"] : ["implement", "confirm", "relate"];
    openModal(`Link ${el.name || ""} to a requirement`, `
      <label class="block text-sm">Link type <select class="input" name="type">${types.map((t) =>
        opt(t, `${ICONS[t]} ${typeMeta[t].label}: ${el.name} ${OUTGOING[t]} the requirement`)).join("")}</select></label>
      <label class="block text-sm">Requirement <select class="input" name="target">${all.html}</select></label>
    `, async (o) => {
      const l = await api("POST", "/api/req/links", { type: o.type, source: el.id, target: o.target });
      studio.log(`Linked: ${otherLabel(l.source)} ${l.verb} ${otherLabel(l.target)}`, "ok");
      await afterChange({ tree: true });
    });
  }

  // ------------------------------------------------------------------ drag and drop
  async function linkFromDrop(reqId, targetId) {
    if (!reqId || !targetId || reqId === targetId) return;
    const target = await api("GET", `/api/element/${encodeURIComponent(targetId)}`);
    if (!target.traceable) { studio.log(`${target.name || target.kind} cannot be linked to requirements.`, "warning"); return; }
    if (target.requirement) {
      const r = rowById(reqId);
      openModal("Link requirements", `
        <label class="block text-sm">Link type <select class="input" name="choice">${[["derive", reqId, targetId], ["derive", targetId, reqId], ["refine", reqId, targetId], ["refine", targetId, reqId], ["relate", reqId, targetId]].map(([t, s, d]) =>
          opt(`${t}|${s}|${d}`, `${typeMeta[t].label}: ${s === reqId ? (r ? reqLabel(r) : "dragged") : target.name} ${OUTGOING[t]} ${d === reqId ? (r ? reqLabel(r) : "dragged") : target.name}`)).join("")}</select></label>
      `, async (o) => {
        const [type, source, tgt] = o.choice.split("|");
        await api("POST", "/api/req/links", { type, source, target: tgt });
        await afterChange({ tree: true });
      });
      return;
    }
    const type = target.verification_result ? "verify" : "implement";
    const l = await api("POST", "/api/req/links", { type, source: targetId, target: reqId });
    studio.log(`Linked: ${otherLabel(l.source)} ${l.verb} ${otherLabel(l.target)}`, "ok");
    await afterChange({ tree: true });
  }

  // Canvas (or any plugin) reports drops of dragged elements onto model elements.
  studio.on("drop-on-element", (p) => {
    if (!p?.dragged_id || !p?.target_id) return;
    const known = rowById(p.dragged_id);
    run(async () => {
      if (!known) {
        const d = await api("GET", `/api/element/${encodeURIComponent(p.dragged_id)}`);
        if (!d.requirement) return;   // not a requirement: another feature's drop
      }
      await linkFromDrop(p.dragged_id, p.target_id);
    })();
  });

  // Requirement rows can also be dropped onto containment-tree nodes.
  const treeEl = document.getElementById("tree");
  const clearDrop = () => treeEl.querySelectorAll(".rq-drop-target").forEach((n) => n.classList.remove("rq-drop-target"));
  treeEl.addEventListener("dragover", (e) => {
    if (!e.dataTransfer?.types?.includes("application/x-sysml-requirement")) return;
    const node = e.target.closest(".tree-node");
    if (!node) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "link";
    clearDrop();
    node.classList.add("rq-drop-target");
  });
  treeEl.addEventListener("dragleave", (e) => { if (!treeEl.contains(e.relatedTarget)) clearDrop(); });
  treeEl.addEventListener("drop", (e) => {
    const reqId = e.dataTransfer?.getData("application/x-sysml-requirement");
    const node = e.target.closest(".tree-node");
    clearDrop();
    if (!reqId || !node) return;
    e.preventDefault();
    run(linkFromDrop)(reqId, node.dataset.id);
  });

  // ------------------------------------------------------------------ Requirements Perspective dock
  // System Composer's Requirements Perspective docks the requirements browser under the
  // architecture canvas so requirements can be dragged onto components. The dock shows under
  // every tab except the Requirements tab itself (which shows the full editor) and shares the
  // current set, selected requirement and link type with it.
  dockEl = document.createElement("div");
  dockEl.className = "rq-dock rq-off";
  dockEl.dataset.rq = "dock";
  dockEl.setAttribute("role", "region");
  dockEl.setAttribute("aria-label", "Requirements perspective");
  dockEl.innerHTML = `
    <div class="rq-splitter" data-dock="splitter" title="Drag to resize"></div>
    <div class="rq-dock-head">
      <span class="rq-dock-title" title="Requirements Perspective: drag a row onto a model element (tree or canvas) to create an Implement link, or select an element and use Link to Selection. Double-click a row to edit it.">Requirements</span>
      <select class="rq-small-select" data-dock="set" title="Requirement set"></select>
      <input class="input rq-filter" data-dock="filter" placeholder="Filter text / ID…" aria-label="Filter requirements" />
      <select class="rq-small-select" data-dock="link-type" aria-label="Link type">${meta.link_types.map((t) => opt(t.name, `${ICONS[t.name]} ${t.label}`, t.name === S.linkType)).join("")}</select>
      <button class="rq-mini" data-dock="link-to" title="Link the selected requirement with the selected model element(s)">⇠ Link to Selection</button>
      <button class="rq-mini" data-dock="link-from" title="Selected model element(s) become the link source">⇢ Link from Selection</button>
      <span class="rq-ts-note sel" data-dock="sel-note">Selection: none</span>
      <span class="flex-1"></span>
      <button class="rq-mini" data-dock="open" title="Edit the selected requirement in the Requirements tab">Open in editor</button>
      <button class="rq-x" data-dock="close" title="Close the Requirements Perspective (Alt+Shift+R)" aria-label="Close requirements perspective">✕</button>
    </div>
    <div class="rq-dock-body" tabindex="0" data-dock="body">
      <table class="rq-table"><thead><tr><th style="width:70px">#</th><th style="width:96px">ID</th><th>Summary</th>
        <th style="width:104px">Implemented</th><th style="width:104px">Verified</th><th style="width:56px">Links</th></tr></thead>
        <tbody data-dock="tbody"></tbody></table>
    </div>`;
  {
    const panes = document.getElementById("tab-panes");
    panes.parentElement.insertBefore(dockEl, panes.nextSibling);
  }
  dockBody = dockEl.querySelector('[data-dock="tbody"]');
  const dq = (k) => dockEl.querySelector(`[data-dock="${k}"]`);

  const dockVisible = () => S.dockOn && !S.visible.req;
  function applyDockVisibility() {
    dockEl.classList.toggle("rq-off", !dockVisible());
    dockEl.style.height = `${S.dockH}px`;
    dockBtn?.classList.toggle("rq-on", S.dockOn);
  }

  function setDock(on) {
    S.dockOn = on;
    try { localStorage.setItem("rq.dock", on ? "1" : "0"); } catch { /* storage unavailable */ }
    applyDockVisibility();
    if (dockVisible()) {
      run(async () => { if (S.dirty.req || !S.table) await loadTable(); else renderDock(); })();
    }
  }

  function updateDockButtons() {
    if (!dockVisible()) return;
    const has = !!selRow();
    dq("link-to").disabled = dq("link-from").disabled = dq("open").disabled = !has;
  }

  function renderDock() {
    if (!dockVisible()) return;
    dq("set").innerHTML = setOptions();
    const f = dq("filter");
    if (document.activeElement !== f) f.value = S.dockFilter;
    if (!sets().length) {
      dockBody.innerHTML = `<tr><td colspan="6"><div class="rq-empty">No requirement sets yet. Open the <b>Requirements</b> tab to create or import one.</div></td></tr>`;
    } else {
      const vis = visibleRows({ text: S.dockFilter });
      let lastSet = null;
      dockBody.innerHTML = vis.length ? vis.map(({ r, dim }) => {
        const twisty = r.has_children ? (S.collapsed.has(r.id) ? "▸" : "▾") : "";
        const sus = r.suspect_count ? ` <span class="rq-warn" title="${r.suspect_count} suspect link(s)">⚠</span>` : "";
        let head = "";
        if (!S.setId && r.set_id !== lastSet) {
          lastSet = r.set_id;
          head = `<tr class="rq-sethead"><td colspan="6" style="background:#f8fafc;padding:2px 8px;font-weight:600;color:#334155">▤ ${esc(sets().find((x) => x.id === r.set_id)?.name || "")}</td></tr>`;
        }
        return `${head}<tr class="rq-row${r.id === S.selId ? " sel" : ""}${dim ? " dim" : ""}" draggable="true" data-id="${esc(r.id)}" data-req-id="${esc(r.req_id || "")}" title="Drag onto a model element to create an Implement link">
          <td class="rq-pad"><div class="rq-idx"><span class="rq-grip">⠿</span><span class="rq-twisty${twisty ? "" : " empty"}" data-rq="twisty">${twisty || "·"}</span>${esc(r.index)}</div></td>
          <td class="rq-pad">${esc(r.req_id || "")}</td>
          <td class="rq-pad" style="padding-left:${6 + 16 * r.depth}px">${esc(r.summary || "")}</td>
          <td data-impl-pct="${r.implementation.pct}">${implBar(r.implementation)}</td>
          <td data-ver-state="${esc(r.verification.state)}">${verBar(r.verification)}</td>
          <td class="rq-pad" data-links="${r.link_count}">${r.link_count}${sus}</td></tr>`;
      }).join("") : `<tr><td colspan="6"><div class="rq-empty">${rows().length ? "No requirement matches the filter." : "This set is empty."}</div></td></tr>`;
    }
    updateSelectionNote();
    updateDockButtons();
  }

  function openInEditor(id) {
    if (id) S.selId = id;
    studio.switchTab("requirements");
    S.view = "requirements";
    renderAll();
    if (S.selId) tbody.querySelector(`tr[data-id="${CSS.escape(S.selId)}"] [data-f=summary]`)?.focus();
  }

  dq("set").addEventListener("change", run((e) => chooseSet(e.target.value)));
  dq("filter").addEventListener("input", (e) => { S.dockFilter = e.target.value; renderDock(); });
  dq("link-type").addEventListener("change", (e) => setLinkType(e.target.value));
  dq("link-to").addEventListener("click", run(() => linkWithSelection("to")));
  dq("link-from").addEventListener("click", run(() => linkWithSelection("from")));
  dq("open").addEventListener("click", () => openInEditor(S.selId));
  dq("close").addEventListener("click", () => setDock(false));
  dockBody.addEventListener("mousedown", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr && !e.target.closest("[data-rq=twisty]")) selectRow(tr.dataset.id);
  });
  dockBody.addEventListener("click", (e) => {
    const tw = e.target.closest("[data-rq=twisty]");
    if (tw && !tw.classList.contains("empty")) toggleCollapsed(tw.closest("tr").dataset.id);
  });
  dockBody.addEventListener("dblclick", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openInEditor(tr.dataset.id);
  });
  dockBody.addEventListener("dragstart", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    selectRow(tr.dataset.id);
    e.dataTransfer.setData("application/x-sysml-element", tr.dataset.id);
    e.dataTransfer.setData("application/x-sysml-requirement", tr.dataset.id);
    e.dataTransfer.setData("text/plain", tr.dataset.reqId || tr.dataset.id);
    e.dataTransfer.effectAllowed = "copyLink";
  });
  dockBody.addEventListener("contextmenu", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    e.preventDefault();
    selectRow(tr.dataset.id);
    openRowMenu(e.clientX, e.clientY);
  });
  dq("body").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
    const vis = [...dockBody.querySelectorAll("tr[data-id]")];
    if (!vis.length) return;
    e.preventDefault();
    if (e.key === "Enter") { openInEditor(S.selId); return; }
    const i = vis.findIndex((t) => t.dataset.id === S.selId);
    const next = vis[Math.max(0, Math.min(vis.length - 1, e.key === "ArrowUp" ? i - 1 : i + 1))];
    selectRow(next.dataset.id);
    next.scrollIntoView({ block: "nearest" });
  });
  dq("splitter").addEventListener("mousedown", (e) => {
    e.preventDefault();
    const startY = e.clientY, startH = S.dockH;
    const move = (ev) => { S.dockH = Math.max(110, Math.min(window.innerHeight - 220, startH - (ev.clientY - startY))); dockEl.style.height = `${S.dockH}px`; };
    const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });

  dockBtn = studio.registerToolbarButton({
    id: "req-perspective", label: "Req Perspective", group: "Requirements",
    title: "Show the requirements browser under the current view (Alt+Shift+R)",
    onClick: () => setDock(!S.dockOn),
  });
  studio.registerShortcut({ key: "r", alt: true, shift: true, handler: () => setDock(!S.dockOn) });

  // ------------------------------------------------------------------ events
  studio.on("tab-shown", (id) => {
    S.visible.req = id === "requirements";
    S.visible.tm = id === "traceability";
    applyDockVisibility();
    if (dockVisible()) run(async () => { if (S.dirty.req || !S.table) await loadTable(); else renderDock(); })();
  });
  let pendingReload = null;
  studio.on("model-changed", () => {
    if (S.skipModelChanged) return;
    S.dirty.req = true; S.dirty.tm = true;
    clearTimeout(pendingReload);
    pendingReload = setTimeout(() => {
      if (S.visible.req || dockVisible()) run(loadTable)();
      if (S.visible.tm) run(loadTraceability)();
    }, 40);
  });
  // An edit saved in place elsewhere (no tree refresh): hidden views reload when shown.
  studio.on("element-changed", () => {
    if (!S.visible.req && !dockVisible()) S.dirty.req = true;
    if (!S.visible.tm) S.dirty.tm = true;
  });
  studio.on("select", (el) => {
    updateSelectionNote();
    if (el?.traceable && el.id !== S.tm.element) {
      S.tm.element = el.id;
      if (S.visible.tm && S.tm.view === "diagram") run(loadTraceability)();
    }
    if (el?.requirement && rowById(el.id) && S.visible.req) selectRow(el.id);
  });
  studio.on("selection-changed", updateSelectionNote);
  studio.on("navigate", ({ id } = {}) => {
    if (id && rowById(id) && (S.visible.req || dockVisible())) selectRow(id);
  });

  applyDockVisibility();   // a dock left open in an earlier session reopens (it loads on the first model-changed)
}
