// Interop, automation and reporting (System Composer style).
//
//   * "Import / Export" tab (id "interop", order 80): toolstrip with Export Tables (XLSX /
//     ZIP of CSV), Export SysML v2 text, Import Tables / SysML v2 text / XMI, Generate Report,
//     Compare with file, Compare with last saved and Three-way merge. Views:
//       - Model Tables: the exported tables in an editable grid; Apply runs the table importer
//         (create / update matched by ID) so spreadsheet-style edits reach the model;
//       - SysML Text: the SysML v2 textual export (copy / download);
//       - Report: the HTML architecture report previewed in a sandboxed frame (Mermaid diagrams
//         render with the vendored library) and downloadable;
//       - Activity: results of imports and exports (counts, warnings).
//   * "Compare" tab (id "compare", order 85): expandable diff tree (added / removed / modified
//     with property-level differences), filters, search, navigate; three-way merge with
//     per-conflict Mine / Theirs choice.
//   * "Model Check" tab (id "checks", order 90): validator + advisor checks, severity / rule
//     filters, search, click or Enter to navigate, counts badge on the tab.
//
// Backend: webapp/routes/interop.py (see docs/features/interop.md).

const STYLES = `
.io-root { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; background:#fff; }
.io-toolstrip { display:flex; flex-wrap:wrap; align-items:stretch; background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:4px 4px 0; flex:none; }
.io-ts-section { display:flex; flex-direction:column; justify-content:space-between; padding:0 6px; border-right:1px solid #e2e8f0; }
.io-ts-buttons { display:flex; gap:2px; align-items:flex-start; }
.io-ts-btn { display:flex; flex-direction:column; align-items:center; gap:2px; min-width:46px; padding:3px 5px; border-radius:4px; font-size:11px; line-height:1.1; color:#334155; white-space:nowrap; text-align:center; }
.io-ts-btn:hover:not(:disabled) { background:#e2e8f0; }
.io-ts-btn:focus-visible { outline:2px solid #2563eb; }
.io-ts-btn:disabled { opacity:.35; cursor:not-allowed; }
.io-ts-btn.on { background:#dbeafe; color:#1d4ed8; }
.io-ts-icon { font-size:16px; line-height:18px; color:#1d4ed8; font-weight:600; }
.io-ts-label { font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:#94a3b8; text-align:center; padding:2px 0 3px; }
.io-ts-col { display:flex; flex-direction:column; gap:3px; justify-content:center; font-size:11px; color:#475569; }
.io-subbar { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px 8px; border-bottom:1px solid #e2e8f0; font-size:12px; flex:none; }
.io-seg { display:inline-flex; border:1px solid #cbd5e1; border-radius:5px; overflow:hidden; }
.io-seg button { padding:2px 10px; font-size:12px; color:#475569; background:#fff; }
.io-seg button + button { border-left:1px solid #cbd5e1; }
.io-seg button.on { background:#dbeafe; color:#1d4ed8; font-weight:500; }
.io-seg button:focus-visible { outline:2px solid #2563eb; outline-offset:-2px; }
.io-filter { width:200px !important; font-size:12px !important; padding:.2rem .45rem !important; }
.io-small { font-size:12px; border:1px solid #cbd5e1; border-radius:4px; padding:2px 4px; background:#fff; }
.io-mini { font-size:11px; padding:1px 7px; border:1px solid #e2e8f0; border-radius:4px; background:#fff; color:#334155; white-space:nowrap; }
.io-mini:hover:not(:disabled) { background:#f1f5f9; }
.io-mini:disabled { opacity:.4; cursor:not-allowed; }
.io-mini.primary { background:#2563eb; border-color:#2563eb; color:#fff; }
.io-mini.primary:hover:not(:disabled) { background:#1d4ed8; }
.io-spacer { flex:1; }
.io-muted { color:#64748b; }
.io-body { flex:1; min-height:0; overflow:auto; position:relative; }
.io-view { position:absolute; inset:0; display:flex; flex-direction:column; min-height:0; }
.io-view.io-off { display:none; }
.io-banner { margin:6px 8px 0; padding:6px 10px; border-radius:6px; font-size:12px; white-space:pre-wrap; flex:none; }
.io-banner.err { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
.io-banner.ok { background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }
.io-banner.warn { background:#fffbeb; color:#92400e; border:1px solid #fde68a; }
.io-banner.info { background:#eff6ff; color:#1e40af; border:1px solid #bfdbfe; }
.io-sheets { display:flex; gap:2px; padding:4px 8px 0; border-bottom:1px solid #e2e8f0; flex:none; overflow-x:auto; }
.io-sheet { padding:3px 10px; font-size:12px; color:#475569; border:1px solid transparent; border-bottom:none; border-radius:5px 5px 0 0; white-space:nowrap; }
.io-sheet:hover { background:#f1f5f9; }
.io-sheet.on { background:#fff; border-color:#cbd5e1; color:#1d4ed8; font-weight:500; margin-bottom:-1px; }
.io-sheet .n { color:#94a3b8; font-size:10px; margin-left:3px; }
.io-sheet .dirty { color:#d97706; margin-left:2px; }
.io-gridwrap { flex:1; overflow:auto; min-height:0; outline:none; }
.io-grid { border-collapse:collapse; font-size:12px; }
.io-grid th { position:sticky; top:0; z-index:1; background:#f1f5f9; text-align:left; font-weight:600; color:#475569; padding:4px 6px; border-bottom:1px solid #cbd5e1; border-right:1px solid #e2e8f0; white-space:nowrap; }
.io-grid th.stereo { color:#7c3aed; }
.io-grid td { border-bottom:1px solid #eef2f7; border-right:1px solid #f1f5f9; padding:2px 6px; white-space:nowrap; max-width:280px; overflow:hidden; text-overflow:ellipsis; height:22px; cursor:cell; }
.io-grid td.rownum { position:sticky; left:0; background:#f8fafc; color:#94a3b8; text-align:right; cursor:pointer; font-variant-numeric:tabular-nums; }
.io-grid td.rownum:hover { color:#1d4ed8; text-decoration:underline; }
.io-grid td.ro { color:#94a3b8; cursor:default; font-family:ui-monospace,monospace; font-size:11px; }
.io-grid td.edited { background:#fef9c3; }
.io-grid tr.new td:not(.rownum) { background:#f0fdf4; }
.io-grid td.active { outline:2px solid #2563eb; outline-offset:-2px; }
.io-grid td.editing { padding:0; overflow:visible; }
.io-grid td.editing input { width:100%; min-width:120px; border:none; outline:2px solid #2563eb; padding:2px 6px; font-size:12px; }
.io-status { display:flex; gap:10px; align-items:center; padding:3px 8px; border-top:1px solid #e2e8f0; font-size:11px; color:#64748b; flex:none; }
.io-pre { flex:1; margin:0; overflow:auto; padding:10px 12px; font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; background:#fcfcfd; white-space:pre; color:#0f172a; }
.io-frame { flex:1; width:100%; border:0; border-top:1px solid #e2e8f0; background:#fff; min-height:0; }
.io-check { display:inline-flex; align-items:center; gap:3px; color:#475569; white-space:nowrap; }
.io-cards { padding:8px; display:flex; flex-direction:column; gap:8px; overflow:auto; }
.io-card { border:1px solid #e2e8f0; border-radius:8px; padding:8px 10px; font-size:12px; }
.io-card h4 { font-size:13px; font-weight:600; margin:0 0 4px; display:flex; gap:8px; align-items:baseline; }
.io-card h4 .t { font-weight:400; color:#94a3b8; font-size:11px; }
.io-card ul { margin:4px 0 0 16px; list-style:disc; color:#92400e; }
.io-kv { display:flex; flex-wrap:wrap; gap:4px 14px; color:#334155; }
.io-kv b { font-variant-numeric:tabular-nums; }
.io-empty { padding:24px; color:#64748b; font-style:italic; font-size:13px; }
.io-chip { display:inline-flex; align-items:center; gap:3px; padding:0 7px; border-radius:9999px; font-size:11px; font-weight:500; white-space:nowrap; }
.io-chip.added { background:#dcfce7; color:#166534; }
.io-chip.removed { background:#fee2e2; color:#991b1b; }
.io-chip.modified { background:#fef3c7; color:#92400e; }
.io-chip.neutral { background:#f1f5f9; color:#334155; }
.io-chip.conflict { background:#fee2e2; color:#991b1b; }
.io-summary { padding:8px 10px; border-bottom:1px solid #e2e8f0; font-size:12px; display:flex; flex-wrap:wrap; gap:8px; align-items:center; flex:none; }
.io-nodiff { margin:24px auto; text-align:center; color:#166534; font-size:15px; font-weight:500; }
.io-nodiff small { display:block; color:#64748b; font-weight:400; font-size:12px; margin-top:4px; }
.io-tree { list-style:none; margin:0; padding:4px 0 12px; font-size:12px; }
.io-tree ul { list-style:none; margin:0; padding-left:18px; }
.io-tnode > .io-trow { display:flex; align-items:center; gap:6px; padding:2px 8px; border-radius:4px; cursor:default; outline:none; }
.io-tnode > .io-trow:hover { background:#f8fafc; }
.io-tnode > .io-trow:focus-visible, .io-tnode > .io-trow.focus { background:#eff6ff; box-shadow: inset 0 0 0 1px #93c5fd; }
.io-twisty { width:14px; text-align:center; color:#64748b; cursor:pointer; user-select:none; flex:none; }
.io-twisty.empty { color:transparent; cursor:default; }
.io-mark { width:16px; height:16px; border-radius:4px; display:inline-flex; align-items:center; justify-content:center; font-weight:700; font-size:11px; flex:none; }
.io-mark.added { background:#dcfce7; color:#166534; }
.io-mark.removed { background:#fee2e2; color:#991b1b; }
.io-mark.modified { background:#fef3c7; color:#92400e; }
.io-mark.none { background:#f1f5f9; color:#94a3b8; }
.io-tname { color:#0f172a; }
.io-tname.link { color:#1d4ed8; cursor:pointer; }
.io-tname.link:hover { text-decoration:underline; }
.io-tname.removed { text-decoration:line-through; color:#991b1b; }
.io-tname.ctx { color:#94a3b8; }
.io-tkind { color:#94a3b8; font-size:11px; }
.io-props { margin:2px 0 6px 44px; border-collapse:collapse; font-size:12px; }
.io-props th { text-align:left; color:#64748b; font-weight:500; padding:2px 10px 2px 0; border-bottom:1px solid #e2e8f0; white-space:nowrap; }
.io-props td { padding:2px 10px 2px 0; border-bottom:1px solid #f1f5f9; vertical-align:top; max-width:420px; overflow-wrap:anywhere; }
.io-props td.old { color:#991b1b; }
.io-props td.new { color:#166534; }
.io-table { border-collapse:collapse; width:100%; font-size:12px; }
.io-table th { position:sticky; top:0; z-index:1; background:#f1f5f9; text-align:left; font-weight:600; color:#475569; padding:4px 8px; border-bottom:1px solid #cbd5e1; white-space:nowrap; }
.io-table td { border-bottom:1px solid #eef2f7; padding:3px 8px; vertical-align:top; }
.io-table tr.io-issue { cursor:pointer; outline:none; }
.io-table tr.io-issue:hover td { background:#f8fafc; }
.io-table tr.io-issue:focus td, .io-table tr.io-issue.sel td { background:#eff6ff; }
.io-sev { display:inline-flex; align-items:center; gap:4px; padding:0 7px; border-radius:9999px; font-size:11px; font-weight:600; }
.io-sev.error { background:#fee2e2; color:#b91c1c; }
.io-sev.warning { background:#fef3c7; color:#92400e; }
.io-sev.info { background:#e0f2fe; color:#075985; }
.io-sevbtn { display:inline-flex; align-items:center; gap:4px; padding:1px 8px; border-radius:9999px; font-size:12px; border:1px solid #e2e8f0; color:#94a3b8; background:#fff; }
.io-sevbtn.on.error { background:#fee2e2; color:#b91c1c; border-color:#fecaca; }
.io-sevbtn.on.warning { background:#fef3c7; color:#92400e; border-color:#fde68a; }
.io-sevbtn.on.info { background:#e0f2fe; color:#075985; border-color:#bae6fd; }
.io-sevbtn:focus-visible { outline:2px solid #2563eb; }
.io-rule { font-family:ui-monospace,monospace; font-size:11px; color:#64748b; }
.io-qn { font-family:ui-monospace,monospace; font-size:11px; color:#334155; }
.io-tab-badge { margin-left:6px; padding:0 6px; border-radius:9999px; font-size:10px; font-weight:600; background:#e2e8f0; color:#475569; }
.io-tab-badge.error { background:#fee2e2; color:#b91c1c; }
.io-tab-badge.warning { background:#fef3c7; color:#92400e; }
.io-tab-badge.stale { opacity:.55; }
.io-choice { display:inline-flex; border:1px solid #cbd5e1; border-radius:5px; overflow:hidden; }
.io-choice label { padding:1px 8px; font-size:11px; cursor:pointer; color:#475569; }
.io-choice label + label { border-left:1px solid #cbd5e1; }
.io-choice input { position:absolute; opacity:0; width:0; height:0; }
.io-choice label.on { background:#dbeafe; color:#1d4ed8; font-weight:600; }
.io-choice label:focus-within { outline:2px solid #2563eb; outline-offset:-2px; }
.io-val { font-family:ui-monospace,monospace; font-size:11px; overflow-wrap:anywhere; }
.io-section-title { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:#64748b; font-weight:600; padding:8px 10px 4px; }
.io-modal-error { color:#b91c1c; font-size:12px; white-space:pre-wrap; }
.io-field { display:block; font-size:13px; }
.io-field > span { display:block; color:#475569; font-size:12px; margin-bottom:2px; }
.io-radio { display:flex; flex-direction:column; gap:3px; font-size:13px; }
.io-hint { color:#64748b; font-size:11px; }
`;

const SEVERITIES = ["error", "warning", "info"];
const SEV_ICON = { error: "●", warning: "▲", info: "i" };
const SEV_LABEL = { error: "Errors", warning: "Warnings", info: "Info" };
const CHANGE_MARK = { added: "+", removed: "−", modified: "~" };
const KIND_HINTS = {
  Components: ["PartDefinition", "PartUsage"],
  Ports: ["PortUsage"],
  Connections: ["ConnectionUsage", "InterfaceUsage"],
  Interfaces: ["PortDefinition", "InterfaceDefinition", "AttributeUsage", "ItemUsage", "ItemDefinition"],
  Requirements: ["RequirementDefinition", "RequirementUsage"],
  Elements: ["Package", "AttributeDefinition", "AttributeUsage", "ItemDefinition", "ActionDefinition",
             "ActionUsage", "StateDefinition", "ConstraintDefinition", "EnumerationDefinition"],
};

export default async function install(studio) {
  const style = document.createElement("style");
  style.dataset.plugin = "interop";
  style.textContent = STYLES;
  document.head.appendChild(style);

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m]));
  const now = () => new Date().toLocaleTimeString();

  /* ---------- file helpers ---------- */

  function bytesToB64(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }
  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function saveFile(name, data, mime = "application/octet-stream") {
    const blob = new Blob([data], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  }
  const hasFile = (f) => f && typeof f === "object" && "size" in f && f.size > 0;
  const isBinaryName = (name) => /\.(xlsx|zip)$/i.test(name || "");
  async function fileBody(file) {
    // Binary files travel as base64; text files as text (the API speaks JSON only).
    if (isBinaryName(file.name)) {
      return { base64: bytesToB64(new Uint8Array(await file.arrayBuffer())), filename: file.name };
    }
    return { text: await file.text(), filename: file.name };
  }

  /* ---------- modal wrapper (Enter submits, Escape cancels, inline errors) ---------- */

  function openModal(title, html, onSubmit, { submitLabel = "OK" } = {}) {
    studio.modal(esc(title), `${html}<div class="io-modal-error" data-io-modal-error></div>`, async (values) => {
      const box = document.querySelector("#modal-root [data-io-modal-error]");
      if (box) box.textContent = "";
      try {
        await onSubmit(values);
      } catch (e) {
        if (box) box.textContent = String(e?.message || e);
        throw e;
      }
    });
    const root = document.getElementById("modal-root");
    const form = root.querySelector("#modal-form");
    const submitBtn = root.querySelector("[data-modal-submit]");
    if (submitBtn) submitBtn.textContent = submitLabel;
    const submit = () => submitBtn?.click();
    form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && e.target.type !== "file") {
        e.preventDefault(); submit();
      }
    });
    root.querySelector(".modal")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); root.querySelector("[data-modal-cancel]")?.click(); }
    });
    // Mirror the radio choice into a class so segmented radios look selected.
    form.addEventListener("change", () => {
      form.querySelectorAll(".io-choice label").forEach((l) => l.classList.toggle("on", !!l.querySelector("input")?.checked));
    });
    setTimeout(() => form.querySelector("input:not([type=hidden]):not([type=file]), select, textarea, input[type=file]")?.focus(), 0);
    return form;
  }

  const modeField = (defaultMode, newLabel = "As a new project (replaces the current one)") => `
    <div class="io-field"><span>Import into</span>
      <div class="io-radio">
        <label><input type="radio" name="mode" value="merge" ${defaultMode === "merge" ? "checked" : ""}/> The current project (create / update elements by ID)</label>
        <label><input type="radio" name="mode" value="new" ${defaultMode === "new" ? "checked" : ""}/> ${esc(newLabel)}</label>
      </div>
    </div>
    <label class="io-field"><span>New project name (optional)</span><input class="input" name="name" placeholder="from the file" /></label>`;

  async function afterProjectChange() {
    // The selected element may no longer exist (new project); start from a clean selection.
    studio.state.selectedId = null;
    await studio.refreshTree();
  }

  /* ---------- shared toolstrip markup ---------- */

  const tsBtn = (id, icon, label, title) =>
    `<button class="io-ts-btn" data-io="${id}" title="${esc(title)}"><span class="io-ts-icon">${icon}</span><span>${esc(label)}</span></button>`;
  const tsSection = (label, buttons) =>
    `<div class="io-ts-section"><div class="io-ts-buttons">${buttons}</div><div class="io-ts-label">${esc(label)}</div></div>`;

  /* =====================================================================
   *  Import / Export tab
   * ===================================================================== */

  const IO = {
    pane: null, view: "tables", info: null,
    tables: null, work: null, sheet: "Components", edited: new Map(), newRows: new Map(),
    active: null, filter: "", tablesStale: true, activity: [], sysml: null, report: null,
  };

  studio.registerTab({
    id: "interop", title: "Import / Export", order: 80,
    mount(pane) {
      IO.pane = pane;
      pane.innerHTML = `
        <div class="io-root">
          <div class="io-toolstrip" role="toolbar" aria-label="Import and export">
            ${tsSection("Export",
              tsBtn("export-xlsx", "▦", "Tables XLSX", "Export the architecture as an Excel workbook (one sheet per table)") +
              tsBtn("export-csv", "▤", "Tables CSV", "Export the architecture as a ZIP of CSV files") +
              tsBtn("export-sysml", "{ }", "SysML v2 Text", "Download the model as SysML v2 textual notation"))}
            ${tsSection("Import",
              tsBtn("import-tables", "⇪", "Tables…", "Import tables (.xlsx, ZIP of CSV, single .csv) into this or a new project") +
              tsBtn("import-sysml", "⟨⟩", "SysML v2 Text…", "Parse SysML v2 text into this or a new project") +
              tsBtn("import-xmi", "⤓", "XMI…", "Import a SysML 1.x XMI 2.5.1 file (Cameo / MagicDraw)"))}
            ${tsSection("Report",
              tsBtn("report", "▣", "Generate Report", "System architecture report (HTML) with diagrams and traceability"))}
            ${tsSection("Compare",
              tsBtn("compare-file", "⇄", "Compare with File…", "Compare the current project with a project JSON or tables file") +
              tsBtn("compare-saved", "⟲", "Compare with Last Saved", "Compare with the project as it was when last saved") +
              tsBtn("merge", "⑂", "Three-way Merge…", "Merge base / theirs / mine; resolve conflicts"))}
          </div>
          <div class="io-subbar">
            <div class="io-seg" role="tablist" aria-label="View">
              <button data-io-view="tables" class="on">Model Tables</button>
              <button data-io-view="sysml">SysML Text</button>
              <button data-io-view="report">Report</button>
              <button data-io-view="activity">Activity</button>
            </div>
            <span class="io-spacer"></span>
            <span class="io-muted" data-io-hint></span>
          </div>
          <div class="io-body">
            <div class="io-view" data-io-pane="tables"></div>
            <div class="io-view io-off" data-io-pane="sysml"></div>
            <div class="io-view io-off" data-io-pane="report"></div>
            <div class="io-view io-off" data-io-pane="activity"></div>
          </div>
        </div>`;
      pane.querySelector(".io-toolstrip").addEventListener("click", (e) => {
        const b = e.target.closest("[data-io]");
        if (b) runAction(b.dataset.io);
      });
      pane.querySelector(".io-seg").addEventListener("click", (e) => {
        const b = e.target.closest("[data-io-view]");
        if (b) showView(b.dataset.ioView);
      });
      buildTablesView(pane.querySelector('[data-io-pane="tables"]'));
      buildSysmlView(pane.querySelector('[data-io-pane="sysml"]'));
      buildReportView(pane.querySelector('[data-io-pane="report"]'));
      renderActivity();
    },
    onShow() { refreshView(); },
  });

  const ioVisible = () => studio.state.tab === "interop";

  function showView(view) {
    IO.view = view;
    IO.pane.querySelectorAll("[data-io-view]").forEach((b) => b.classList.toggle("on", b.dataset.ioView === view));
    IO.pane.querySelectorAll("[data-io-pane]").forEach((p) => p.classList.toggle("io-off", p.dataset.ioPane !== view));
    refreshView();
  }

  function refreshView() {
    if (IO.view === "tables" && (IO.tablesStale || !IO.tables)) loadTables().catch(() => {});
    if (IO.view === "sysml" && !IO.sysml) loadSysml().catch(() => {});
    if (IO.view === "report" && !IO.report) generateReport().catch(() => {});
  }

  async function runAction(action) {
    try {
      if (action === "export-xlsx") await exportTables("xlsx");
      else if (action === "export-csv") await exportTables("csv");
      else if (action === "export-sysml") await exportSysml();
      else if (action === "import-tables") importTablesDialog();
      else if (action === "import-sysml") importSysmlDialog();
      else if (action === "import-xmi") importXmiDialog();
      else if (action === "report") {
        const shown = !!IO.report;      // showing the view generates the first report itself
        showView("report");
        if (shown) await generateReport();
      }
      else if (action === "compare-file") compareFileDialog();
      else if (action === "compare-saved") { studio.switchTab("compare"); await compareSnapshot(); }
      else if (action === "merge") mergeDialog();
    } catch (e) {
      console.warn(e);  // the API helper already logged the server message
    }
  }

  function addActivity(title, kv = {}, warnings = [], level = "ok") {
    IO.activity.unshift({ title, time: now(), kv, warnings, level });
    IO.activity = IO.activity.slice(0, 40);
    renderActivity();
  }

  function renderActivity() {
    const host = IO.pane?.querySelector('[data-io-pane="activity"]');
    if (!host) return;
    if (!IO.activity.length) {
      host.innerHTML = `<div class="io-empty">Imports and exports you run appear here with their results.</div>`;
      return;
    }
    host.innerHTML = `<div class="io-cards">${IO.activity.map((a) => `
      <div class="io-card">
        <h4><span>${esc(a.title)}</span><span class="t">${esc(a.time)}</span></h4>
        <div class="io-kv">${Object.entries(a.kv).map(([k, v]) => `<span>${esc(k)}: <b>${esc(v)}</b></span>`).join("")}</div>
        ${a.warnings?.length ? `<ul>${a.warnings.slice(0, 30).map((w) => `<li>${esc(w)}</li>`).join("")}${a.warnings.length > 30 ? `<li>… ${a.warnings.length - 30} more</li>` : ""}</ul>` : ""}
      </div>`).join("")}</div>`;
  }

  /* ---------- exports ---------- */

  async function exportTables(fmt) {
    const r = await studio.api("GET", `/api/interop/tables?format=${fmt}`);
    saveFile(r.filename, b64ToBytes(r.base64), r.mime);
    studio.log(`Exported tables to ${r.filename} (${Math.round(r.size / 1024) || 1} KB)`, "ok");
    addActivity(`Exported ${fmt === "xlsx" ? "XLSX workbook" : "ZIP of CSV files"}`, { file: r.filename, bytes: r.size });
  }

  async function exportSysml() {
    const r = await studio.api("GET", "/api/interop/sysml");
    saveFile(r.filename, r.text, "text/plain;charset=utf-8");
    IO.sysml = r;
    renderSysml();
    studio.log(`Exported SysML v2 text to ${r.filename}`, "ok");
    addActivity("Exported SysML v2 text", { file: r.filename, lines: r.text.split("\n").length });
  }

  /* ---------- imports ---------- */

  function importTablesDialog() {
    openModal("Import tables", `
      <label class="io-field"><span>Tables file (.xlsx workbook, ZIP of CSV files or one CSV named after its table)</span>
        <input class="input" type="file" name="file" accept=".xlsx,.zip,.csv" /></label>
      ${modeField("new")}
      <p class="io-hint">Rows are matched by their ID column (else by owner and name): existing elements are updated,
        new rows create elements. Nothing is deleted. The import is atomic: any error leaves the model unchanged.</p>`,
    async (o) => {
      if (!hasFile(o.file)) throw new Error("Choose a tables file to import");
      const r = await studio.api("POST", "/api/interop/tables/import", {
        ...(await fileBody(o.file)), mode: o.mode || "new", name: o.name || undefined,
      });
      await afterProjectChange();
      const rep = r.report;
      studio.log(`Imported tables from ${o.file.name}: ${rep.created} created, ${rep.updated} updated`, "ok");
      addActivity(`Imported tables from ${o.file.name}`, {
        mode: r.mode, project: r.project.name, created: rep.created, updated: rep.updated,
        unchanged: rep.unchanged, "links created": rep.links_created, "stereotypes applied": rep.stereotypes_applied,
      }, rep.warnings);
      markStale();
      showView("activity");
    }, { submitLabel: "Import" });
  }

  function importSysmlDialog() {
    openModal("Import SysML v2 text", `
      <label class="io-field"><span>SysML v2 file (.sysml)</span>
        <input class="input" type="file" name="file" accept=".sysml,.kerml,.txt" /></label>
      <label class="io-field"><span>… or paste the text</span>
        <textarea class="input font-mono" style="height:120px;font-size:12px" name="text" placeholder="package Avionics { part def FlightManagementComputer; }"></textarea></label>
      ${modeField("merge")}`,
    async (o) => {
      const text = hasFile(o.file) ? await o.file.text() : (o.text || "");
      if (!text.trim()) throw new Error("Choose a .sysml file or paste SysML v2 text");
      const r = await studio.api("POST", "/api/interop/sysml/import", { text, mode: o.mode || "merge", name: o.name || undefined });
      await afterProjectChange();
      studio.log(`Imported SysML v2 text: ${r.created} element(s) created`, "ok");
      addActivity("Imported SysML v2 text", { mode: r.mode, project: r.project.name, created: r.created });
      markStale();
      showView("activity");
    }, { submitLabel: "Import" });
  }

  function importXmiDialog() {
    openModal("Import SysML 1.x XMI", `
      <label class="io-field"><span>XMI 2.5.1 file exported from Cameo / MagicDraw (.xmi, .xml, .uml)</span>
        <input class="input" type="file" name="file" accept=".xmi,.xml,.uml" /></label>
      ${modeField("new", "As a new project named after the XMI model")}
      <p class="io-hint">Blocks, part properties, ports (flow / proxy), connectors, requirements (Id, Text),
        satisfy / verify / derive links and profile stereotypes are imported. XMI ids become element ids,
        so importing the same file again updates instead of duplicating.</p>`,
    async (o) => {
      if (!hasFile(o.file)) throw new Error("Choose an XMI file to import");
      const r = await studio.api("POST", "/api/interop/xmi/import", {
        text: await o.file.text(), mode: o.mode || "new", name: o.name || undefined,
      });
      await afterProjectChange();
      const rep = r.report;
      studio.log(`Imported XMI model ${rep.model_name}: ${rep.created} created, ${rep.links_created} links`, "ok");
      addActivity(`Imported XMI ${o.file.name}`, {
        mode: r.mode, model: rep.model_name, created: rep.created, updated: rep.updated,
        "links created": rep.links_created, "stereotypes applied": rep.stereotypes_applied,
      }, rep.warnings);
      markStale();
      showView("activity");
    }, { submitLabel: "Import" });
  }

  /* ---------- Model Tables view (editable grid -> table importer) ---------- */

  function buildTablesView(host) {
    host.innerHTML = `
      <div class="io-subbar">
        <button class="io-mini" data-t="reload" title="Reload the tables from the model">⟳ Reload</button>
        <button class="io-mini" data-t="add" title="Append a new row (fill Name and the owner column)">＋ Add row</button>
        <button class="io-mini" data-t="revert" title="Discard edits">Revert</button>
        <button class="io-mini primary" data-t="apply" title="Apply the edited rows to the model (table import)">Apply to model</button>
        <input class="input io-filter" data-t="filter" placeholder="Filter rows…" aria-label="Filter rows" />
        <span class="io-spacer"></span>
        <span class="io-muted">Double-click, Enter or F2 to edit · Tab / Enter to commit · Esc to cancel · click a row number to go to the element</span>
      </div>
      <div data-t="banner"></div>
      <div class="io-sheets" role="tablist" data-t="sheets"></div>
      <div class="io-gridwrap" tabindex="0" data-t="grid"></div>
      <div class="io-status" data-t="status"></div>
      <datalist id="io-kind-list"></datalist>`;
    host.addEventListener("click", (e) => {
      const b = e.target.closest("[data-t]");
      if (!b || b.tagName === "INPUT") return;
      const t = b.dataset.t;
      if (t === "reload") loadTables(true).catch(() => {});
      else if (t === "add") addRow();
      else if (t === "revert") { resetWork(); renderTables(); }
      else if (t === "apply") applyTables().catch(() => {});
    });
    host.querySelector('[data-t="filter"]').addEventListener("input", (e) => {
      IO.filter = e.target.value.trim().toLowerCase(); renderGrid();
    });
    host.querySelector('[data-t="sheets"]').addEventListener("click", (e) => {
      const b = e.target.closest("[data-sheet]");
      if (b) { IO.sheet = b.dataset.sheet; IO.active = null; renderTables(); }
    });
    const grid = host.querySelector('[data-t="grid"]');
    grid.addEventListener("click", (e) => {
      const num = e.target.closest("td.rownum");
      if (num) {
        const id = rowId(Number(num.parentElement.dataset.r));
        if (id) studio.emit("navigate", { id });
        return;
      }
      const td = e.target.closest("td[data-c]");
      if (td && !td.classList.contains("editing")) setActive(Number(td.parentElement.dataset.r), Number(td.dataset.c));
    });
    grid.addEventListener("dblclick", (e) => {
      const td = e.target.closest("td[data-c]");
      if (td) startEdit(Number(td.parentElement.dataset.r), Number(td.dataset.c));
    });
    grid.addEventListener("keydown", onGridKey);
  }

  const sheetRows = () => IO.work?.[IO.sheet] || [];
  const header = () => sheetRows()[0] || [];
  const col = (name) => header().indexOf(name);
  function rowId(r) {
    const c = col("ID");
    return c >= 0 ? String(sheetRows()[r]?.[c] ?? "") : "";
  }
  function resetWork() {
    IO.work = JSON.parse(JSON.stringify(IO.tables || {}));
    IO.edited = new Map();
    IO.newRows = new Map();
    IO.active = null;
  }
  const editedCount = () => [...IO.edited.values()].reduce((n, s) => n + s.size, 0) +
    [...IO.newRows.values()].reduce((n, s) => n + s.size, 0);
  const isDirty = () => editedCount() > 0;

  function markStale() {
    IO.tablesStale = true;
    IO.sysml = null;
    IO.report = null;
    if (ioVisible()) refreshView();
  }

  let tablesLoading = null;
  async function loadTables(force = false) {
    if (isDirty() && !force) { banner("warn", "The model changed since the tables were loaded. Apply or Revert your edits, then Reload."); return; }
    if (tablesLoading) return tablesLoading;
    tablesLoading = (async () => {
      try {
        if (!KIND_HINTS.Links) {
          const kinds = await studio.api("GET", "/api/link_kinds").catch(() => []);
          KIND_HINTS.Links = kinds.map((k) => k.name);
        }
        const r = await studio.api("GET", "/api/interop/tables?format=json");
        IO.tables = r.tables;
        IO.tablesStale = false;
        if (!IO.tables[IO.sheet]) IO.sheet = Object.keys(IO.tables).find((k) => k !== "Model") || "Model";
        resetWork();
        banner();
        renderTables();
      } finally { tablesLoading = null; }
    })();
    return tablesLoading;
  }

  function banner(kind, text) {
    const host = IO.pane?.querySelector('[data-io-pane="tables"] [data-t="banner"]');
    if (!host) return;
    host.innerHTML = kind ? `<div class="io-banner ${kind}">${esc(text)}</div>` : "";
  }

  function renderTables() {
    const host = IO.pane.querySelector('[data-io-pane="tables"]');
    const sheets = host.querySelector('[data-t="sheets"]');
    sheets.innerHTML = Object.keys(IO.work || {}).map((name) => {
      const n = Math.max(0, (IO.work[name] || []).length - 1);
      const dirty = (IO.edited.get(name)?.size || 0) + (IO.newRows.get(name)?.size || 0);
      return `<button class="io-sheet ${name === IO.sheet ? "on" : ""}" role="tab" data-sheet="${esc(name)}">${esc(name)}<span class="n">${n}</span>${dirty ? `<span class="dirty" title="${dirty} edited row(s)">●</span>` : ""}</button>`;
    }).join("");
    const dl = host.querySelector("#io-kind-list");
    dl.innerHTML = (KIND_HINTS[IO.sheet] || []).map((k) => `<option value="${esc(k)}">`).join("");
    renderGrid();
  }

  // The Model sheet describes the export; an existing row's ID is its identity.
  const readOnlyCol = (name, r) => IO.sheet === "Model" || (name === "ID" && !IO.newRows.get(IO.sheet)?.has(r));

  function renderGrid() {
    const host = IO.pane.querySelector('[data-io-pane="tables"]');
    const grid = host.querySelector('[data-t="grid"]');
    const rows = sheetRows();
    if (!rows.length) { grid.innerHTML = `<div class="io-empty">No tables loaded.</div>`; updateStatus(); return; }
    const hdr = rows[0];
    const edited = IO.edited.get(IO.sheet) || new Map();
    const fresh = IO.newRows.get(IO.sheet) || new Set();
    const filter = IO.filter;
    let html = `<table class="io-grid"><thead><tr><th>#</th>${hdr.map((h) =>
      `<th class="${/\./.test(h) ? "stereo" : ""}" title="${esc(h)}">${esc(h)}</th>`).join("")}</tr></thead><tbody>`;
    let shown = 0;
    for (let r = 1; r < rows.length; r++) {
      const row = rows[r];
      if (filter && !row.some((v) => String(v ?? "").toLowerCase().includes(filter))) continue;
      shown++;
      const ed = edited.get?.(r) || new Set();
      html += `<tr data-r="${r}" class="${fresh.has(r) ? "new" : ""}"><td class="rownum" title="${rowId(r) ? "Go to element" : ""}">${r}</td>`;
      for (let c = 0; c < hdr.length; c++) {
        const v = row[c];
        const cls = [readOnlyCol(hdr[c], r) ? "ro" : "", ed.has(c) ? "edited" : "",
                     IO.active && IO.active.r === r && IO.active.c === c ? "active" : ""].join(" ").trim();
        html += `<td data-c="${c}" class="${cls}" title="${esc(v)}">${esc(v)}</td>`;
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    grid.innerHTML = html;
    if (!shown) grid.insertAdjacentHTML("beforeend", `<div class="io-empty">${rows.length > 1 ? "No rows match the filter." : "This table is empty. Use “Add row” to create elements."}</div>`);
    updateStatus();
  }

  function updateStatus() {
    const host = IO.pane.querySelector('[data-io-pane="tables"] [data-t="status"]');
    const n = Math.max(0, sheetRows().length - 1);
    const dirty = editedCount();
    host.innerHTML = `<span>${esc(IO.sheet)}: ${n} row(s)</span>` +
      (dirty ? `<span style="color:#b45309">${dirty} edited row(s) not applied</span>` : `<span>no pending edits</span>`) +
      `<span class="io-spacer"></span><span>Columns “X ID” hold element ids and win over the name column “X”; editing a name clears its id.</span>`;
    host.parentElement.querySelector('[data-t="apply"]').disabled = !dirty;
    host.parentElement.querySelector('[data-t="revert"]').disabled = !dirty;
    host.parentElement.querySelector('[data-t="add"]').disabled = IO.sheet === "Model";
  }

  function cellTd(r, c) {
    return IO.pane.querySelector(`[data-io-pane="tables"] tr[data-r="${r}"] td[data-c="${c}"]`);
  }

  function setActive(r, c) {
    IO.pane.querySelectorAll('[data-io-pane="tables"] td.active').forEach((x) => x.classList.remove("active"));
    IO.active = { r, c };
    const td = cellTd(r, c);
    if (td) { td.classList.add("active"); td.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    IO.pane.querySelector('[data-io-pane="tables"] [data-t="grid"]').focus({ preventScroll: true });
  }

  function visibleRows() {
    return [...IO.pane.querySelectorAll('[data-io-pane="tables"] tbody tr')].map((tr) => Number(tr.dataset.r));
  }

  function moveActive(dr, dc) {
    if (!IO.active) { const vr = visibleRows(); if (vr.length) setActive(vr[0], 0); return; }
    const vr = visibleRows();
    let i = vr.indexOf(IO.active.r);
    i = Math.max(0, Math.min(vr.length - 1, i + dr));
    const c = Math.max(0, Math.min(header().length - 1, IO.active.c + dc));
    if (vr.length) setActive(vr[i], c);
  }

  function onGridKey(e) {
    if (e.target.tagName === "INPUT") return;
    // Handled keys stay in the grid (the studio's global Delete / plugin shortcuts must not fire).
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (!IO.active) { if (e.key.startsWith("Arrow")) { handled(); moveActive(0, 0); } return; }
    const { r, c } = IO.active;
    if (e.key === "ArrowDown") { handled(); moveActive(1, 0); }
    else if (e.key === "ArrowUp") { handled(); moveActive(-1, 0); }
    else if (e.key === "ArrowRight") { handled(); moveActive(0, 1); }
    else if (e.key === "ArrowLeft") { handled(); moveActive(0, -1); }
    else if (e.key === "Enter" || e.key === "F2") { handled(); startEdit(r, c); }
    else if (e.key === "Delete" || e.key === "Backspace") { handled(); commitCell(r, c, ""); }
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { handled(); startEdit(r, c, e.key); }
  }

  function startEdit(r, c, initial) {
    const name = header()[c];
    if (name === undefined || readOnlyCol(name, r)) {
      if (name !== undefined) studio.setStatus(`${name} is read-only here`);
      return;
    }
    setActive(r, c);
    const td = cellTd(r, c);
    if (!td) return;
    const old = sheetRows()[r][c];
    td.classList.add("editing");
    const listAttr = name === "Kind" ? 'list="io-kind-list"' : "";
    td.innerHTML = `<input ${listAttr} aria-label="${esc(name)}" />`;
    const input = td.querySelector("input");
    input.value = initial !== undefined ? initial : String(old ?? "");
    input.focus();
    if (initial === undefined) input.select();
    let done = false;
    const finish = (commit, dr = 0, dc = 0) => {
      if (done) return;
      done = true;
      if (commit) commitCell(r, c, input.value);
      else renderGrid();
      setActive(r, c);
      if (dr || dc) moveActive(dr, dc);
    };
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); finish(true, 1, 0); }
      else if (e.key === "Tab") { e.preventDefault(); finish(true, 0, e.shiftKey ? -1 : 1); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  }

  function commitCell(r, c, value) {
    const rows = sheetRows();
    const name = header()[c];
    if (!rows[r] || readOnlyCol(name, r)) return;
    const before = rows[r][c];
    if (String(before ?? "") === value) { renderGrid(); return; }
    rows[r][c] = value;
    markEdited(r, c);
    // A reference is "X ID" (ids) + "X" (qualified names); ids win on import, so editing
    // the name clears the id of the same reference. (Profiles rows are matched by their ids.)
    const idCol = IO.sheet === "Profiles" ? -1 : col(`${name} ID`);
    if (idCol >= 0 && String(rows[r][idCol] ?? "")) {
      rows[r][idCol] = "";
      markEdited(r, idCol);
    }
    renderTables();
  }

  function markEdited(r, c) {
    if (!IO.edited.has(IO.sheet)) IO.edited.set(IO.sheet, new Map());
    const m = IO.edited.get(IO.sheet);
    if (!m.has(r)) m.set(r, new Set());
    m.get(r).add(c);
  }

  function addRow() {
    if (!IO.work || IO.sheet === "Model") return;
    const rows = sheetRows();
    const blank = header().map(() => "");
    // Sensible defaults: the kind most rows of this table use.
    const k = col("Kind");
    if (k >= 0) blank[k] = (KIND_HINTS[IO.sheet] || [""])[IO.sheet === "Components" ? 1 : 0] || "";
    rows.push(blank);
    const r = rows.length - 1;
    if (!IO.newRows.has(IO.sheet)) IO.newRows.set(IO.sheet, new Set());
    IO.newRows.get(IO.sheet).add(r);
    IO.filter = "";
    IO.pane.querySelector('[data-io-pane="tables"] [data-t="filter"]').value = "";
    renderTables();
    const nameCol = Math.max(0, col("Name"));
    setActive(r, nameCol);
    startEdit(r, nameCol);
  }

  async function applyTables() {
    if (!isDirty()) return;
    const payload = { Model: IO.work.Model || [] };
    for (const name of Object.keys(IO.work)) {
      if (name === "Model") continue;
      const rows = new Set([...(IO.edited.get(name)?.keys() || []), ...(IO.newRows.get(name) || [])]);
      if (!rows.size) continue;
      payload[name] = [IO.work[name][0], ...[...rows].sort((a, b) => a - b).map((r) => IO.work[name][r])];
    }
    let r;
    try {
      r = await studio.api("POST", "/api/interop/tables/import", { tables: payload, mode: "merge" });
    } catch (e) {
      banner("err", `Not applied (the model is unchanged):\n${e.message || e}`);
      return;
    }
    const rep = r.report;
    await studio.refreshTree();
    await loadTables(true);
    banner(rep.warnings.length ? "warn" : "ok",
      `Applied: ${rep.created} created, ${rep.updated} updated, ${rep.unchanged} unchanged.` +
      (rep.warnings.length ? `\n${rep.warnings.join("\n")}` : ""));
    studio.log(`Applied table edits: ${rep.created} created, ${rep.updated} updated`, "ok");
    addActivity("Applied table edits", { created: rep.created, updated: rep.updated, unchanged: rep.unchanged }, rep.warnings);
  }

  /* ---------- SysML text view ---------- */

  function buildSysmlView(host) {
    host.innerHTML = `
      <div class="io-subbar">
        <button class="io-mini" data-s="refresh">⟳ Refresh</button>
        <button class="io-mini" data-s="copy">Copy</button>
        <button class="io-mini primary" data-s="download">Download .sysml</button>
        <span class="io-spacer"></span>
        <span class="io-muted" data-s="caps"></span>
      </div>
      <pre class="io-pre" data-s="text" tabindex="0" aria-label="SysML v2 text"></pre>`;
    host.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-s]");
      if (!b) return;
      try {
        if (b.dataset.s === "refresh") await loadSysml();
        else if (b.dataset.s === "download") await exportSysml();
        else if (b.dataset.s === "copy" && IO.sysml) {
          await navigator.clipboard?.writeText(IO.sysml.text).catch(() => {});
          studio.log("SysML v2 text copied to the clipboard", "ok");
        }
      } catch (err) { console.warn(err); }
    });
  }

  async function loadSysml() {
    IO.sysml = await studio.api("GET", "/api/interop/sysml");
    renderSysml();
  }

  function renderSysml() {
    const host = IO.pane?.querySelector('[data-io-pane="sysml"]');
    if (!host || !IO.sysml) return;
    host.querySelector('[data-s="text"]').textContent = IO.sysml.text;
    const caps = IO.sysml.parser_capabilities || {};
    const off = Object.entries(caps).filter(([, v]) => !v).map(([k]) => k);
    host.querySelector('[data-s="caps"]').textContent =
      off.length ? `Kept as comments (the parser does not read them yet): ${off.join(", ")}` : "Everything is exported as parsable SysML v2.";
  }

  /* ---------- Report view ---------- */

  function buildReportView(host) {
    host.innerHTML = `
      <div class="io-subbar">
        <label class="io-check">Title <input class="input" style="width:200px;font-size:12px;padding:.15rem .4rem" data-r="title" placeholder="System Architecture Report" /></label>
        <label class="io-check">Author <input class="input" style="width:140px;font-size:12px;padding:.15rem .4rem" data-r="author" /></label>
        <span data-r="sections" class="flex flex-wrap gap-2"></span>
      </div>
      <div class="io-subbar">
        <button class="io-mini primary" data-r="generate">Generate</button>
        <button class="io-mini" data-r="download" title="Save the report as one HTML file">Download HTML</button>
        <label class="io-check" title="Embed the Mermaid library (≈3 MB) so the downloaded file renders diagrams offline"><input type="checkbox" data-r="inline" checked /> embed diagrams library</label>
        <button class="io-mini" data-r="open" title="Open the report in a new browser tab">Open in new tab</button>
        <span class="io-spacer"></span>
        <span class="io-muted" data-r="meta"></span>
      </div>
      <iframe class="io-frame" data-r="frame" title="Report preview" sandbox="allow-scripts"></iframe>`;
    host.addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-r]");
      if (!b) return;
      try {
        if (b.dataset.r === "generate") await generateReport();
        else if (b.dataset.r === "download") await downloadReport();
        else if (b.dataset.r === "open") await openReport();
      } catch (err) { console.warn(err); }
    });
    host.querySelector('[data-r="title"]').addEventListener("keydown", (e) => { if (e.key === "Enter") generateReport().catch(() => {}); });
  }

  async function reportInfo() {
    if (!IO.info) IO.info = await studio.api("GET", "/api/interop/info");
    const host = IO.pane.querySelector('[data-io-pane="report"] [data-r="sections"]');
    if (!host.childElementCount) {
      host.innerHTML = IO.info.report_sections.map((s) =>
        `<label class="io-check"><input type="checkbox" data-section="${esc(s)}" checked /> ${esc(s)}</label>`).join("");
    }
    return IO.info;
  }

  function reportQuery(mermaid) {
    const host = IO.pane.querySelector('[data-io-pane="report"]');
    const params = new URLSearchParams({ mermaid });
    const title = host.querySelector('[data-r="title"]').value.trim();
    const author = host.querySelector('[data-r="author"]').value.trim();
    if (title) params.set("title", title);
    if (author) params.set("author", author);
    const boxes = [...host.querySelectorAll("[data-section]")];
    const chosen = boxes.filter((b) => b.checked).map((b) => b.dataset.section);
    if (chosen.length && chosen.length !== boxes.length) params.set("sections", chosen.join(","));
    if (!chosen.length && boxes.length) throw new Error("Choose at least one report section");
    return params;
  }

  // In-page anchors must scroll inside the preview frame (its base URL is the studio's).
  const ANCHOR_FIX = "<script>document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[href^=\"#\"]');" +
    "if(!a)return;e.preventDefault();var t=document.getElementById(a.getAttribute('href').slice(1));if(t)t.scrollIntoView();});</script>";

  async function generateReport() {
    await reportInfo();
    let params;
    try { params = reportQuery("link"); } catch (e) { studio.log(String(e.message), "warning"); return; }
    const r = await studio.api("GET", `/api/interop/report?${params}`);
    IO.report = r;
    const host = IO.pane.querySelector('[data-io-pane="report"]');
    host.querySelector('[data-r="frame"]').srcdoc = r.html.replace("</body>", `${ANCHOR_FIX}</body>`);
    host.querySelector('[data-r="meta"]').textContent = `${r.filename} · generated ${now()}`;
    studio.log(`Generated report ${r.filename}`, "ok");
  }

  async function downloadReport() {
    await reportInfo();
    const inline = IO.pane.querySelector('[data-io-pane="report"] [data-r="inline"]').checked;
    const r = await studio.api("GET", `/api/interop/report?${reportQuery(inline ? "inline" : "link")}`);
    let html = r.html;
    if (!inline) html = html.replace('src="/static/vendor/', `src="${location.origin}/static/vendor/`);
    saveFile(r.filename, html, "text/html;charset=utf-8");
    studio.log(`Downloaded report ${r.filename}`, "ok");
    addActivity("Downloaded report", { file: r.filename, bytes: html.length });
  }

  async function openReport() {
    if (!IO.report) await generateReport();
    if (!IO.report) return;
    const html = IO.report.html.replace('src="/static/vendor/', `src="${location.origin}/static/vendor/`);
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 120000);
  }

  /* =====================================================================
   *  Compare tab (diff tree + three-way merge)
   * ===================================================================== */

  const CMP = {
    pane: null, mode: "empty", diff: null, merge: null, last: null,
    filters: { added: true, removed: true, modified: true }, search: "", collapsed: new Set(),
    choices: {}, includeLayout: false,
  };

  studio.registerTab({
    id: "compare", title: "Compare", order: 85,
    mount(pane) {
      CMP.pane = pane;
      pane.innerHTML = `
        <div class="io-root">
          <div class="io-toolstrip" role="toolbar" aria-label="Compare">
            ${tsSection("Compare",
              tsBtn("compare-file", "⇄", "With File…", "Compare the current project with a project JSON or tables file") +
              tsBtn("compare-saved", "⟲", "With Last Saved", "Compare with the project as it was when last saved") +
              tsBtn("snapshot", "⊙", "Set Baseline", "Remember the current project as the baseline for “With Last Saved”") +
              tsBtn("refresh", "⟳", "Refresh", "Run the last comparison again"))}
            ${tsSection("Merge", tsBtn("merge", "⑂", "Three-way Merge…", "Merge base / theirs / mine; resolve conflicts"))}
            <div class="io-ts-section"><div class="io-ts-col" data-c="filters">
              <label class="io-check"><input type="checkbox" data-filter="added" checked /> <span class="io-mark added">+</span> Added</label>
              <label class="io-check"><input type="checkbox" data-filter="removed" checked /> <span class="io-mark removed">−</span> Removed</label>
              <label class="io-check"><input type="checkbox" data-filter="modified" checked /> <span class="io-mark modified">~</span> Modified</label>
            </div><div class="io-ts-label">Show</div></div>
            <div class="io-ts-section"><div class="io-ts-col">
              <input class="input io-filter" data-c="search" placeholder="Search name or property…" aria-label="Search differences" />
              <span class="flex gap-1">
                <button class="io-mini" data-c="expand">Expand all</button>
                <button class="io-mini" data-c="collapse">Collapse all</button>
                <label class="io-check" title="Also compare UI layout data (tool_data)"><input type="checkbox" data-c="layout" /> layout</label>
              </span>
            </div><div class="io-ts-label">Filter</div></div>
          </div>
          <div class="io-body"><div class="io-view" data-c="body"></div></div>
        </div>`;
      pane.querySelector(".io-toolstrip").addEventListener("click", (e) => {
        const b = e.target.closest("[data-io]");
        if (!b) return;
        const a = b.dataset.io;
        const go = async () => {
          if (a === "compare-file") compareFileDialog();
          else if (a === "compare-saved") await compareSnapshot();
          else if (a === "snapshot") await takeSnapshot();
          else if (a === "refresh") await rerunCompare();
          else if (a === "merge") mergeDialog();
        };
        go().catch((err) => console.warn(err));
      });
      pane.querySelector('[data-c="filters"]').addEventListener("change", (e) => {
        const f = e.target.dataset.filter;
        if (f) { CMP.filters[f] = e.target.checked; renderCompare(); }
      });
      pane.querySelector('[data-c="search"]').addEventListener("input", (e) => {
        CMP.search = e.target.value.trim().toLowerCase(); renderCompare();
      });
      pane.querySelector('[data-c="expand"]').addEventListener("click", () => { CMP.collapsed.clear(); renderCompare(); });
      pane.querySelector('[data-c="collapse"]').addEventListener("click", () => {
        const walk = (nodes) => nodes.forEach((n) => { CMP.collapsed.add(n.id); walk(n.children || []); });
        walk(CMP.diff?.tree || []);
        renderCompare();
      });
      pane.querySelector('[data-c="layout"]').addEventListener("change", (e) => {
        CMP.includeLayout = e.target.checked;
        rerunCompare().catch(() => {});
      });
      const body = pane.querySelector('[data-c="body"]');
      body.addEventListener("click", onCompareClick);
      body.addEventListener("keydown", onCompareKey);
      body.addEventListener("change", onMergeChoice);
      renderCompare();
    },
  });

  async function takeSnapshot(label) {
    const r = await studio.api("POST", "/api/interop/snapshot", { label: label || `Baseline ${now()}` });
    studio.log(`Baseline set: ${r.label} (${r.elements} elements)`, "ok");
    return r;
  }

  // "Last saved": the core Save JSON command snapshots the project for comparison.
  document.addEventListener("click", (e) => {
    if (e.target?.closest?.('[data-cmd="save"]')) {
      studio.api("POST", "/api/interop/snapshot", { label: "Last saved" }).catch(() => {});
    }
  }, true);

  async function runCompare(request) {
    CMP.last = request;
    const diff = await studio.api("POST", "/api/interop/compare", { ...request, include_layout: CMP.includeLayout });
    CMP.diff = diff;
    CMP.mode = "diff";
    CMP.collapsed = new Set();
    studio.switchTab("compare");
    renderCompare();
    const s = diff.summary;
    studio.log(diff.identical ? `Compare with ${diff.old.label}: no differences`
      : `Compare with ${diff.old.label}: ${s.added} added, ${s.removed} removed, ${s.modified} modified`, "ok");
  }

  async function rerunCompare() {
    if (CMP.last) await runCompare(CMP.last);
  }

  async function compareSnapshot() {
    const snap = await studio.api("GET", "/api/interop/snapshot");
    if (snap.exists === false) {
      CMP.mode = "message";
      CMP.message = { kind: "info", text: "There is no saved version of this project yet. Use Save JSON (or Set Baseline) first, or compare with a file." };
      studio.switchTab("compare");
      renderCompare();
      return;
    }
    await runCompare({ against: "snapshot" });
  }

  function compareFileDialog() {
    openModal("Compare with file", `
      <label class="io-field"><span>Other version: project JSON (.json), tables workbook (.xlsx) or ZIP of CSV files</span>
        <input class="input" type="file" name="file" accept=".json,.xlsx,.zip" /></label>
      <p class="io-hint">Differences are shown from the file (old) to the current project (new): added, removed and
        modified elements with property-level changes. Elements are matched by ID.</p>`,
    async (o) => {
      if (!hasFile(o.file)) throw new Error("Choose the file to compare with");
      await runCompare(await fileBody(o.file));
    }, { submitLabel: "Compare" });
  }

  const fmtVal = (v) => {
    if (v === null || v === undefined || v === "") return `<span class="io-muted">—</span>`;
    if (Array.isArray(v)) return v.length ? v.map((x) => esc(typeof x === "object" ? JSON.stringify(x) : x)).join(", ") : `<span class="io-muted">[]</span>`;
    if (typeof v === "object") return esc(JSON.stringify(v));
    return esc(v);
  };

  function nodeMatches(n) {
    if (n.change && !CMP.filters[n.change]) return false;
    if (!n.change) return false;
    if (!CMP.search) return true;
    const q = CMP.search;
    return String(n.name || "").toLowerCase().includes(q) || String(n.kind || "").toLowerCase().includes(q) ||
      (n.properties || []).some((p) => String(p.property).toLowerCase().includes(q) ||
        JSON.stringify(p.old ?? "").toLowerCase().includes(q) || JSON.stringify(p.new ?? "").toLowerCase().includes(q));
  }

  function visibleTree(nodes) {
    const out = [];
    for (const n of nodes) {
      const kids = visibleTree(n.children || []);
      if (nodeMatches(n) || kids.length) out.push({ ...n, children: kids, matched: nodeMatches(n) });
    }
    return out;
  }

  function renderTreeNodes(nodes, oldLabel) {
    return nodes.map((n) => {
      const open = !CMP.collapsed.has(n.id);
      const hasBody = (n.children?.length || 0) + ((n.matched && n.properties?.length) ? 1 : 0) > 0;
      const change = n.change || "none";
      const nameCls = n.change === "removed" ? "removed" : (n.change ? "link" : "ctx link");
      const props = n.matched && n.properties?.length && open ? `
        <table class="io-props"><thead><tr><th>Property</th><th>${esc(oldLabel)}</th><th>Current project</th></tr></thead><tbody>
        ${n.properties.map((p) => `<tr><td>${esc(p.property)}</td><td class="old io-val">${fmtVal(p.old)}</td><td class="new io-val">${fmtVal(p.new)}</td></tr>`).join("")}
        </tbody></table>` : "";
      return `<li class="io-tnode" data-id="${esc(n.id)}">
        <div class="io-trow" tabindex="-1" data-row="${esc(n.id)}" data-change="${esc(change)}">
          <span class="io-twisty ${hasBody ? "" : "empty"}" data-toggle="${esc(n.id)}">${hasBody ? (open ? "▾" : "▸") : "·"}</span>
          <span class="io-mark ${change}" title="${esc(n.change || "unchanged (contains changes)")}">${CHANGE_MARK[n.change] || "·"}</span>
          <span class="io-tname ${nameCls}" ${n.change === "removed" ? "" : `data-nav="${esc(n.id)}"`} title="${n.change === "removed" ? "Removed: not in the current project" : "Go to element"}">${esc(n.name || `<${n.kind}>`)}</span>
          <span class="io-tkind">${esc(n.kind)}</span>
          ${n.matched && n.properties?.length ? `<span class="io-muted">${n.properties.length} change(s)</span>` : ""}
        </div>
        ${props}
        ${n.children?.length && open ? `<ul>${renderTreeNodes(n.children, oldLabel)}</ul>` : ""}
      </li>`;
    }).join("");
  }

  function renderCompare() {
    const body = CMP.pane?.querySelector('[data-c="body"]');
    if (!body) return;
    const filterBox = CMP.pane.querySelector('[data-c="filters"]').closest(".io-ts-section");
    filterBox.style.opacity = CMP.mode === "diff" ? "" : ".45";
    if (CMP.mode === "empty") {
      body.innerHTML = `<div class="io-empty">Compare the current project with another version: a project JSON file, a tables
        workbook (.xlsx / ZIP of CSV) or the last saved version. Use Three-way Merge to combine two versions derived from
        a common base.</div>`;
      return;
    }
    if (CMP.mode === "message") {
      body.innerHTML = `<div class="io-banner ${CMP.message.kind}">${esc(CMP.message.text)}</div>`;
      return;
    }
    if (CMP.mode === "merge") { renderMerge(body); return; }
    const d = CMP.diff;
    const s = d.summary;
    const head = `<div class="io-summary">
      <span>Comparing <b>${esc(d.old.label)}</b> <span class="io-muted">(${esc(d.old.name)}, ${d.old.elements} elements)</span>
        → <b>current project</b> <span class="io-muted">(${esc(d.new.name)}, ${d.new.elements} elements)</span></span>
      <span class="io-spacer"></span>
      <span class="io-chip added" data-count="added">+${s.added} added</span>
      <span class="io-chip removed" data-count="removed">−${s.removed} removed</span>
      <span class="io-chip modified" data-count="modified">~${s.modified} modified</span>
    </div>`;
    if (d.identical) {
      body.innerHTML = `${head}<div class="io-nodiff" data-c="nodiff">✓ No differences<small>The current project and ${esc(d.old.label)} contain the same elements, properties and links.</small></div>`;
      return;
    }
    const project = d.project?.length ? `<div class="io-section-title">Project</div>
      <table class="io-props" style="margin-left:12px"><thead><tr><th>Property</th><th>${esc(d.old.label)}</th><th>Current project</th></tr></thead><tbody>
      ${d.project.map((p) => `<tr><td>${esc(p.property)}</td><td class="old io-val">${fmtVal(p.old)}</td><td class="new io-val">${fmtVal(p.new)}</td></tr>`).join("")}
      </tbody></table>` : "";
    const tree = visibleTree(d.tree || []);
    body.innerHTML = `${head}${project}
      <div style="overflow:auto;flex:1;min-height:0">${tree.length
        ? `<ul class="io-tree" role="tree">${renderTreeNodes(tree, d.old.label)}</ul>`
        : `<div class="io-empty">No differences match the filters.</div>`}</div>`;
  }

  function onCompareClick(e) {
    const t = e.target.closest("[data-toggle]");
    if (t && !t.classList.contains("empty")) {
      const id = t.dataset.toggle;
      CMP.collapsed.has(id) ? CMP.collapsed.delete(id) : CMP.collapsed.add(id);
      renderCompare();
      CMP.pane.querySelector(`[data-row="${CSS.escape(id)}"]`)?.focus();
      return;
    }
    const nav = e.target.closest("[data-nav]");
    if (nav) { studio.emit("navigate", { id: nav.dataset.nav }); return; }
    const row = e.target.closest(".io-trow");
    if (row) row.focus();
    const b = e.target.closest("[data-merge]");
    if (b) {
      const a = b.dataset.merge;
      if (a === "all-mine" || a === "all-theirs") {
        for (const c of CMP.merge.conflicts) CMP.choices[c.id] = a === "all-mine" ? "mine" : "theirs";
        renderCompare();
      } else if (a === "apply") applyMerge().catch((err) => console.warn(err));
      else if (a === "cancel") { CMP.mode = CMP.diff ? "diff" : "empty"; CMP.merge = null; renderCompare(); }
    }
  }

  function onCompareKey(e) {
    const row = e.target.closest(".io-trow");
    if (!row) return;
    const rows = [...CMP.pane.querySelectorAll(".io-trow")];
    const i = rows.indexOf(row);
    const id = row.dataset.row;
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown") { handled(); rows[i + 1]?.focus(); }
    else if (e.key === "ArrowUp") { handled(); rows[i - 1]?.focus(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      handled();
      if (e.key === "ArrowLeft") CMP.collapsed.add(id); else CMP.collapsed.delete(id);
      renderCompare();
      CMP.pane.querySelector(`[data-row="${CSS.escape(id)}"]`)?.focus();
    } else if (e.key === "Enter" && row.dataset.change !== "removed") {
      handled(); studio.emit("navigate", { id });
    }
  }

  /* ---------- three-way merge ---------- */

  function mergeDialog() {
    openModal("Three-way merge", `
      <label class="io-field"><span>Base: the common ancestor (project JSON or tables file)</span>
        <input class="input" type="file" name="base" accept=".json,.xlsx,.zip" /></label>
      <label class="io-field"><span>Theirs: the other changed version</span>
        <input class="input" type="file" name="theirs" accept=".json,.xlsx,.zip" /></label>
      <label class="io-field"><span>Mine: leave empty to use the current project</span>
        <input class="input" type="file" name="mine" accept=".json,.xlsx,.zip" /></label>
      <p class="io-hint">Changes made on one side only are merged automatically. Properties changed differently on both
        sides are conflicts: choose Mine or Theirs for each, then Apply. The result becomes the current project.</p>`,
    async (o) => {
      if (!hasFile(o.base) || !hasFile(o.theirs)) throw new Error("Choose the base and theirs files");
      const body = { base: await fileBody(o.base), theirs: await fileBody(o.theirs) };
      if (hasFile(o.mine)) body.mine = await fileBody(o.mine);
      const r = await studio.api("POST", "/api/interop/merge", body);
      CMP.merge = { ...r, labels: { base: o.base.name, theirs: o.theirs.name, mine: hasFile(o.mine) ? o.mine.name : "current project" } };
      CMP.choices = Object.fromEntries(r.conflicts.map((c) => [c.id, "mine"]));
      CMP.mode = "merge";
      studio.switchTab("compare");
      renderCompare();
      studio.log(`Three-way merge: ${r.auto.length} change(s) merged automatically, ${r.conflicts.length} conflict(s)`,
        r.conflicts.length ? "warning" : "ok");
    }, { submitLabel: "Merge" });
  }

  function renderMerge(body) {
    const m = CMP.merge;
    const choice = (c) => {
      const v = CMP.choices[c.id] || "mine";
      return `<span class="io-choice" role="radiogroup" aria-label="Resolution for ${esc(c.element)} ${esc(c.property)}">
        <label class="${v === "mine" ? "on" : ""}"><input type="radio" name="choice-${esc(c.id)}" value="mine" data-conflict="${esc(c.id)}" ${v === "mine" ? "checked" : ""}/>Mine</label>
        <label class="${v === "theirs" ? "on" : ""}"><input type="radio" name="choice-${esc(c.id)}" value="theirs" data-conflict="${esc(c.id)}" ${v === "theirs" ? "checked" : ""}/>Theirs</label>
      </span>`;
    };
    const conflicts = m.conflicts.length ? `
      <table class="io-table" data-c="conflicts"><thead><tr><th>Element</th><th>Property</th><th>Base</th><th>Mine</th><th>Theirs</th><th>Use</th></tr></thead><tbody>
      ${m.conflicts.map((c) => `<tr data-conflict-row="${esc(c.id)}">
        <td><span class="io-tname link" data-nav="${esc(c.element_id)}">${esc(c.element)}</span>
          <div class="io-muted" style="font-size:11px">${esc(c.kind)}</div></td>
        <td>${esc(c.property)}</td>
        <td class="io-val">${fmtVal(c.base)}</td>
        <td class="io-val" style="${CMP.choices[c.id] === "mine" ? "font-weight:600" : ""}">${fmtVal(c.mine)}</td>
        <td class="io-val" style="${CMP.choices[c.id] === "theirs" ? "font-weight:600" : ""}">${fmtVal(c.theirs)}</td>
        <td>${choice(c)}</td></tr>`).join("")}
      </tbody></table>` : `<div class="io-banner ok">No conflicts: every change can be merged automatically.</div>`;
    const auto = m.auto.length ? `
      <details ${m.conflicts.length ? "" : "open"} style="padding:0 10px 10px">
        <summary class="io-section-title" style="cursor:pointer;padding-left:0">Merged automatically (${m.auto.length})</summary>
        <table class="io-table"><thead><tr><th>Element</th><th>Change</th><th>From</th></tr></thead><tbody>
        ${m.auto.map((a) => `<tr><td>${esc(a.element)}</td><td>${esc(a.property)}</td><td><span class="io-chip ${a.from === "mine" ? "neutral" : "modified"}">${esc(a.from)}</span></td></tr>`).join("")}
        </tbody></table></details>` : "";
    const notes = m.notes?.length ? `<div class="io-banner warn">${m.notes.map(esc).join("\n")}</div>` : "";
    body.innerHTML = `
      <div class="io-summary">
        <span>Three-way merge · base <b>${esc(m.labels.base)}</b> · theirs <b>${esc(m.labels.theirs)}</b> · mine <b>${esc(m.labels.mine)}</b></span>
        <span class="io-spacer"></span>
        <span class="io-chip neutral">${m.auto.length} auto-merged</span>
        <span class="io-chip ${m.conflicts.length ? "conflict" : "added"}" data-c="conflict-count">${m.conflicts.length} conflict(s)</span>
      </div>
      <div class="io-subbar">
        <button class="io-mini" data-merge="all-mine" ${m.conflicts.length ? "" : "disabled"}>Take all Mine</button>
        <button class="io-mini" data-merge="all-theirs" ${m.conflicts.length ? "" : "disabled"}>Take all Theirs</button>
        <span class="io-spacer"></span>
        <button class="io-mini" data-merge="cancel">Discard merge</button>
        <button class="io-mini primary" data-merge="apply">Apply merge</button>
      </div>
      <div style="overflow:auto;flex:1;min-height:0">
        ${notes}
        <div class="io-section-title">Conflicts</div>
        <div style="padding:0 10px 8px">${conflicts}</div>
        ${auto}
      </div>`;
  }

  function onMergeChoice(e) {
    const id = e.target.dataset?.conflict;
    if (!id) return;
    CMP.choices[id] = e.target.value;
    renderCompare();
    CMP.pane.querySelector(`input[name="choice-${CSS.escape(id)}"][value="${e.target.value}"]`)?.focus();
  }

  async function applyMerge() {
    const m = CMP.merge;
    const r = await studio.api("POST", "/api/interop/merge/resolve", { token: m.token, choices: CMP.choices });
    await afterProjectChange();
    CMP.merge = null;
    CMP.mode = "message";
    CMP.message = {
      kind: r.notes?.length ? "warn" : "ok",
      text: `Merge applied: the result is now the current project (${r.project.element_count} elements, ` +
        `${r.conflicts_resolved} conflict(s) resolved).` + (r.notes?.length ? `\n${r.notes.join("\n")}` : ""),
    };
    renderCompare();
    markStale();
    studio.log(`Merge applied (${r.conflicts_resolved} conflict(s) resolved)`, "ok");
    addActivity("Three-way merge applied", { elements: r.project.element_count, "conflicts resolved": r.conflicts_resolved }, r.notes || []);
  }

  /* =====================================================================
   *  Model Check tab
   * ===================================================================== */

  const CHK = { pane: null, result: null, sev: new Set(SEVERITIES), rule: "", q: "", stale: true, running: null, sel: null };

  studio.registerTab({
    id: "checks", title: "Model Check", order: 90,
    mount(pane) {
      CHK.pane = pane;
      pane.innerHTML = `
        <div class="io-root">
          <div class="io-toolstrip" role="toolbar" aria-label="Model Check">
            ${tsSection("Check", tsBtn("run", "▶", "Run Checks", "Validate the model and run the advisor checks"))}
            <div class="io-ts-section"><div class="io-ts-col" style="flex-direction:row;align-items:center;gap:4px;height:100%" data-k="sev"></div><div class="io-ts-label">Severity</div></div>
            <div class="io-ts-section"><div class="io-ts-col">
              <select class="io-small" data-k="rule" aria-label="Rule filter" style="width:240px"><option value="">All rules</option></select>
              <input class="input io-filter" data-k="search" placeholder="Search element or message…" aria-label="Search issues" style="width:240px !important" />
            </div><div class="io-ts-label">Filter</div></div>
            <div class="io-ts-section" style="border-right:none"><div class="io-ts-col" data-k="meta"></div><div class="io-ts-label">Result</div></div>
          </div>
          <div class="io-body"><div class="io-view" style="overflow:auto" data-k="body"></div></div>
        </div>`;
      pane.querySelector('[data-io="run"]').addEventListener("click", () => runChecks().catch(() => {}));
      pane.querySelector('[data-k="sev"]').addEventListener("click", (e) => {
        const b = e.target.closest("[data-sev]");
        if (!b) return;
        const s = b.dataset.sev;
        CHK.sev.has(s) ? CHK.sev.delete(s) : CHK.sev.add(s);
        renderChecks();
      });
      pane.querySelector('[data-k="rule"]').addEventListener("change", (e) => { CHK.rule = e.target.value; renderChecks(); });
      pane.querySelector('[data-k="search"]').addEventListener("input", (e) => { CHK.q = e.target.value.trim().toLowerCase(); renderChecks(); });
      const body = pane.querySelector('[data-k="body"]');
      body.addEventListener("click", (e) => {
        const tr = e.target.closest("tr.io-issue");
        if (tr) { CHK.sel = Number(tr.dataset.i); tr.focus(); studio.emit("navigate", { id: tr.dataset.id }); }
      });
      body.addEventListener("keydown", (e) => {
        const tr = e.target.closest("tr.io-issue");
        if (!tr) return;
        const go = (next) => {
          e.preventDefault(); e.stopPropagation();
          if (!next) return;
          tr.tabIndex = -1; next.tabIndex = 0; next.focus();
        };
        if (e.key === "ArrowDown") go(tr.nextElementSibling);
        else if (e.key === "ArrowUp") go(tr.previousElementSibling);
        else if (e.key === "Home") go(tr.parentElement.firstElementChild);
        else if (e.key === "End") go(tr.parentElement.lastElementChild);
        else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); tr.click(); }
      });
      renderChecks();
    },
    onShow() { if (CHK.stale || !CHK.result) runChecks().catch(() => {}); },
  });

  function tabBadge() {
    const tab = document.querySelector('#tab-bar .tab[data-tab="checks"]');
    if (!tab) return;
    let b = tab.querySelector(".io-tab-badge");
    if (!CHK.result) { b?.remove(); return; }
    if (!b) { b = document.createElement("span"); tab.appendChild(b); }
    const c = CHK.result.counts;
    const worst = c.error ? "error" : (c.warning ? "warning" : "");
    b.className = `io-tab-badge ${worst} ${CHK.stale ? "stale" : ""}`.trim();
    b.textContent = String(CHK.result.total);
    b.title = `${c.error} error(s), ${c.warning} warning(s), ${c.info} info${CHK.stale ? " (model changed since the last run)" : ""}`;
  }

  async function runChecks() {
    if (CHK.running) return CHK.running;
    CHK.running = (async () => {
      try {
        CHK.result = await studio.api("GET", "/api/interop/check");
        CHK.stale = false;
        CHK.ranAt = now();
        renderChecks();
        tabBadge();
        const c = CHK.result.counts;
        studio.log(`Model Check: ${c.error} error(s), ${c.warning} warning(s), ${c.info} info`,
          c.error ? "error" : (c.warning ? "warning" : "ok"));
      } finally { CHK.running = null; }
    })();
    return CHK.running;
  }

  function shownIssues() {
    const r = CHK.result;
    if (!r) return [];
    return r.issues.filter((i) => CHK.sev.has(i.severity) && (!CHK.rule || i.rule === CHK.rule) &&
      (!CHK.q || `${i.qualified_name} ${i.message} ${i.rule}`.toLowerCase().includes(CHK.q)));
  }

  function renderChecks() {
    if (!CHK.pane) return;
    const r = CHK.result;
    const sevHost = CHK.pane.querySelector('[data-k="sev"]');
    sevHost.innerHTML = SEVERITIES.map((s) => `<button class="io-sevbtn ${s} ${CHK.sev.has(s) ? "on" : ""}" data-sev="${s}" aria-pressed="${CHK.sev.has(s)}" title="Show ${SEV_LABEL[s].toLowerCase()}">${SEV_ICON[s]} <span data-sev-count="${s}">${r ? r.counts[s] : 0}</span> ${SEV_LABEL[s]}</button>`).join("");
    const sel = CHK.pane.querySelector('[data-k="rule"]');
    if (r) {
      const titles = Object.fromEntries((r.rules || []).map((x) => [x.id, x.title]));
      const ids = Object.keys(r.by_rule).sort();
      if (CHK.rule && !ids.includes(CHK.rule)) CHK.rule = "";
      sel.innerHTML = `<option value="">All rules (${r.total})</option>` + ids.map((id) =>
        `<option value="${esc(id)}" ${id === CHK.rule ? "selected" : ""}>${esc(titles[id] && titles[id] !== id ? `${titles[id]} · ${id}` : id)} (${r.by_rule[id]})</option>`).join("");
    }
    CHK.pane.querySelector('[data-k="meta"]').innerHTML = r
      ? `<span><b>${r.total}</b> issue(s)</span><span class="io-muted">${CHK.stale ? "model changed · run again" : `last run ${esc(CHK.ranAt || "")}`}</span>`
      : `<span class="io-muted">not run yet</span>`;
    const body = CHK.pane.querySelector('[data-k="body"]');
    if (!r) { body.innerHTML = `<div class="io-empty">Run Checks validates the model (the same rules as Validate / F5) plus the advisor checks: empty compositions, unconnected ports, duplicate sibling names, components without ports and missing documentation.</div>`; return; }
    const desc = Object.fromEntries((r.rules || []).map((x) => [x.id, x]));
    const rows = shownIssues();
    body.innerHTML = rows.length ? `
      <table class="io-table" data-k="issues"><thead><tr><th style="width:90px">Severity</th><th>Rule</th><th>Element</th><th>Message</th></tr></thead><tbody>
      ${rows.map((i, n) => `<tr class="io-issue ${CHK.sel === n ? "sel" : ""}" tabindex="${(CHK.sel ?? 0) === n ? 0 : -1}" data-i="${n}" data-id="${esc(i.element_id)}" data-sev="${esc(i.severity)}" title="Go to ${esc(i.qualified_name)}">
        <td><span class="io-sev ${esc(i.severity)}">${SEV_ICON[i.severity] || ""} ${esc(i.severity)}</span></td>
        <td title="${esc(desc[i.rule]?.description || "")}">${esc(desc[i.rule]?.title && desc[i.rule].title !== i.rule ? desc[i.rule].title : "")} <span class="io-rule">${esc(i.rule)}</span></td>
        <td class="io-qn">${esc(i.qualified_name)}</td>
        <td>${esc(i.message)}</td></tr>`).join("")}
      </tbody></table>` : `<div class="io-empty">${r.total ? "No issues match the filters." : "✓ No issues found."}</div>`;
  }

  /* ---------- keep views in sync with the model ---------- */

  let checkTimer = null;
  studio.on("model-changed", () => {
    // Tables / text / report views reload lazily; the open Model Check re-runs (debounced).
    IO.tablesStale = true;
    IO.sysml = null;
    if (ioVisible() && IO.view === "tables") loadTables().catch(() => {});
    if (CHK.result) { CHK.stale = true; tabBadge(); renderChecks(); }
    if (studio.state.tab === "checks") {
      clearTimeout(checkTimer);
      checkTimer = setTimeout(() => runChecks().catch(() => {}), 300);
    }
  });

  // The studio's Validate (button or F5) also refreshes the Model Check results and badge.
  const afterValidate = () => setTimeout(() => runChecks().catch(() => {}), 0);
  document.addEventListener("click", (e) => { if (e.target?.closest?.('[data-cmd="validate"]')) afterValidate(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "F5" && !e.target.closest?.("input, textarea, select")) afterValidate(); });

  // Keyboard: Ctrl+Shift+K opens Model Check and runs it.
  studio.registerShortcut({
    key: "k", ctrl: true, shift: true,
    handler() { studio.switchTab("checks"); runChecks().catch(() => {}); },
  });
}
