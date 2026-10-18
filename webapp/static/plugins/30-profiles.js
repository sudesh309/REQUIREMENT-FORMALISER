// Profiles, stereotypes and typed stereotype properties (System Composer Profile Editor).
//
//  - "Profiles" tab: Profile Editor (profile browser, stereotype details, style,
//    default stereotypes, editable property table, import / export).
//  - "Stereotypes" inspector section: applied stereotypes as collapsible groups
//    with typed editors (number + unit, checkbox, enumeration select, text).
//  - "Apply stereotype…" dialog: batch application over a scope.
//  - Tree badges «Name» coloured with the stereotype style.
// Backend: webapp/routes/profiles.py (engine/profiles.py).

const STYLE = `
.pf-editor { display:flex; flex-direction:column; width:100%; height:100%; background:#fff; }
.pf-strip { display:flex; align-items:stretch; background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:4px 6px 0; flex-wrap:wrap; }
.pf-group { display:flex; flex-direction:column; padding:0 6px; border-right:1px solid #e2e8f0; }
.pf-group:last-child { border-right:0; }
.pf-group-tools { display:flex; gap:2px; }
.pf-group-label { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#94a3b8; text-align:center; padding:2px 0 3px; }
.pf-tool { display:flex; flex-direction:column; align-items:center; gap:2px; padding:4px 6px; min-width:60px; border:1px solid transparent; border-radius:4px; font-size:11px; color:#334155; background:transparent; cursor:pointer; }
.pf-tool:hover:not(:disabled) { background:#e0f2fe; border-color:#bae6fd; }
.pf-tool:focus-visible { outline:2px solid #2563eb; }
.pf-tool:disabled { opacity:.4; cursor:not-allowed; }
.pf-tool svg { width:20px; height:20px; }
.pf-body { display:flex; flex:1; min-height:0; }
.pf-browser { width:250px; min-width:200px; border-right:1px solid #e2e8f0; overflow:auto; padding:4px 0; outline:none; }
.pf-browser:focus-visible { box-shadow:inset 0 0 0 2px #93c5fd; }
.pf-pane-title { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#64748b; padding:4px 10px 6px; border-bottom:1px solid #f1f5f9; margin-bottom:2px; }
.pf-row { display:flex; align-items:center; gap:6px; padding:3px 8px; cursor:pointer; font-size:13px; white-space:nowrap; border-radius:3px; margin:0 4px; }
.pf-row:hover { background:#f1f5f9; }
.pf-row.sel { background:#dbeafe; color:#1d4ed8; }
.pf-row .pf-sub { color:#94a3b8; font-size:11px; margin-left:auto; }
.pf-row.st { padding-left:26px; }
.pf-row.abstract .pf-name { font-style:italic; }
.pf-row svg { width:14px; height:14px; flex:none; }
.pf-details { flex:1; overflow:auto; padding:12px 18px 40px; min-width:0; }
.pf-h { display:flex; align-items:baseline; gap:10px; margin-bottom:6px; }
.pf-h .pf-title { font-size:17px; font-weight:600; }
.pf-chip { font-size:10px; padding:1px 6px; border-radius:9px; background:#f1f5f9; color:#64748b; white-space:nowrap; }
.pf-section-title { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:#64748b; font-weight:600; margin:16px 0 6px; }
.pf-form { display:grid; grid-template-columns:170px minmax(0, 1fr); gap:6px 12px; align-items:center; max-width:760px; font-size:13px; }
.pf-form label { color:#334155; }
.pf-inline { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.pf-color { width:34px; height:26px; padding:0; border:1px solid #cbd5e1; border-radius:4px; background:#fff; }
.pf-color[data-empty="1"] { opacity:.35; }
.pf-x { border:1px solid #e2e8f0; border-radius:4px; padding:0 6px; font-size:12px; color:#64748b; background:#fff; line-height:22px; }
.pf-x:hover { background:#fee2e2; color:#b91c1c; }
.pf-preview { display:inline-flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; min-width:150px; height:58px; border:2px solid #64748b; border-radius:6px; background:#fff; font-size:12px; padding:0 10px; }
.pf-preview svg { width:16px; height:16px; }
.pf-line-preview { width:120px; height:10px; }
.pf-table-wrap { overflow-x:auto; border:1px solid #e2e8f0; border-radius:6px; max-width:1100px; }
.pf-table { border-collapse:collapse; width:100%; font-size:12px; table-layout:fixed; min-width:640px; }
.pf-table.pf-auto { table-layout:auto; min-width:0; }
.pf-table col.c-num { width:26px; } .pf-table col.c-name { width:15%; } .pf-table col.c-type { width:12%; }
.pf-table col.c-unit { width:9%; } .pf-table col.c-default { width:11%; } .pf-table col.c-min, .pf-table col.c-max { width:7%; }
.pf-table col.c-lits { width:14%; } .pf-table col.c-act { width:74px; }
.pf-table th.pf-actions-h { text-align:center; }
.pf-table th { text-align:left; font-weight:600; color:#475569; background:#f8fafc; border-bottom:1px solid #e2e8f0; border-right:1px solid #f1f5f9; padding:5px 6px; white-space:nowrap; }
.pf-table td { border-bottom:1px solid #f1f5f9; border-right:1px solid #f1f5f9; padding:0; }
.pf-table td.pf-num-cell { color:#94a3b8; text-align:center; width:28px; }
.pf-table td input, .pf-table td select { width:100%; border:0; padding:5px 6px; font-size:12px; background:transparent; min-width:0; }
.pf-table td input:disabled, .pf-table td select:disabled { color:#cbd5e1; }
.pf-table td input:focus, .pf-table td select:focus { outline:2px solid #2563eb; outline-offset:-2px; background:#fff; }
.pf-table tr.pf-inherited td { background:#f8fafc; color:#94a3b8; padding:5px 6px; }
.pf-table tr.pf-grouprow td { background:#f1f5f9; color:#475569; font-weight:600; padding:4px 6px; font-size:11px; }
.pf-table tr.pf-pending td { background:#fffbeb; }
.pf-table .pf-actions { white-space:nowrap; width:78px; text-align:center; }
.pf-icon-btn { border:0; background:transparent; padding:2px 5px; border-radius:3px; color:#64748b; font-size:12px; cursor:pointer; }
.pf-icon-btn:hover:not(:disabled) { background:#e2e8f0; color:#0f172a; }
.pf-icon-btn.danger:hover { background:#fee2e2; color:#b91c1c; }
.pf-icon-btn:disabled { opacity:.3; cursor:default; }
.pf-msg { min-height:18px; font-size:12px; margin:6px 0; }
.pf-msg.err { color:#b91c1c; }
.pf-msg.ok { color:#15803d; }
.pf-empty { color:#64748b; font-style:italic; padding:24px; font-size:13px; }
.pf-swatch { width:16px; height:12px; display:inline-block; flex:none; }
/* inspector section */
.pf-insp-bar { display:flex; gap:6px; align-items:center; margin-bottom:8px; }
.pf-insp-bar select { max-width:280px; }
.pf-app { border:1px solid #e2e8f0; border-radius:6px; margin-bottom:8px; background:#fff; }
.pf-app > summary { display:flex; align-items:center; gap:8px; padding:5px 8px; cursor:pointer; background:#f8fafc; border-radius:6px; list-style:none; font-size:13px; }
.pf-app > summary::-webkit-details-marker { display:none; }
.pf-app > summary .pf-caret { color:#94a3b8; width:10px; display:inline-block; transition:transform .1s; }
.pf-app[open] > summary .pf-caret { transform:rotate(90deg); }
.pf-app[open] > summary { border-bottom:1px solid #e2e8f0; border-radius:6px 6px 0 0; }
.pf-app > summary .pf-name { font-weight:600; color:#6d28d9; }
.pf-props { display:grid; grid-template-columns:150px minmax(0, 1fr) 70px; gap:4px 8px; padding:8px; align-items:center; font-size:13px; }
.pf-props .pf-ghead { grid-column:1 / -1; font-size:11px; color:#64748b; border-bottom:1px dashed #e2e8f0; padding-top:4px; }
.pf-props label { color:#334155; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.pf-props .pf-unit { font-size:11px; color:#64748b; }
.pf-props .pf-field-err { grid-column:2 / -1; color:#b91c1c; font-size:11px; margin-top:-2px; }
.pf-props input.pf-invalid { border-color:#ef4444; background:#fef2f2; }
.pf-props input[type=checkbox] { width:16px; height:16px; justify-self:start; }
/* the profiles plugin renders stereotypes as styled badges (display contract);
   hide the core's legacy inline «…» text and the raw JSON line */
#tree li.tree-node > .row > span:nth-child(2) > span { display:none; }
#props-stereotypes { display:none; }
/* The Properties pane is a flex row (.tab-pane); give the element form and the
   inspector sections stable side-by-side columns that wrap on narrow windows. */
#tab-properties { flex-wrap:wrap; align-content:flex-start; align-items:flex-start; column-gap:1.5rem; }
#tab-properties > #props-form { flex:1 1 420px; min-width:0; }
#tab-properties > #inspector-sections { flex:1 1 420px; min-width:0; margin-top:0; }
/* The Profile Editor and the Stereotypes inspector supersede the raw-JSON legacy dialogs. */
[data-cmd="define-stereotype"], [data-cmd="apply-stereotype"] { display:none !important; }
#tree .tree-badge.pf-badge { display:inline-flex; align-items:center; gap:2px; border:1px solid transparent; }
#tree .tree-badge.pf-badge svg { width:10px; height:10px; }
`;

// Small fixed icon set (stroke icons, 24x24 viewBox).
const ICONS = {
  component: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 9h16"/>',
  sensor: '<circle cx="12" cy="12" r="3"/><path d="M7 7a7 7 0 0 0 0 10M17 7a7 7 0 0 1 0 10M4 4a11 11 0 0 0 0 16M20 4a11 11 0 0 1 0 16"/>',
  actuator: '<circle cx="12" cy="12" r="4"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/>',
  computer: '<rect x="5" y="5" width="14" height="14" rx="1"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  display: '<rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4"/>',
  network: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5M12 12l-6 5M12 12l6 5"/>',
  power: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  antenna: '<path d="M12 10v12M8 22h8M5 4a10 10 0 0 0 0 10M19 4a10 10 0 0 1 0 10M8.5 6.5a5 5 0 0 0 0 5M15.5 6.5a5 5 0 0 1 0 5"/><circle cx="12" cy="9" r="1"/>',
  software: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
  storage: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  controller: '<rect x="3" y="7" width="18" height="10" rx="5"/><path d="M7 12h4M9 10v4"/><circle cx="15" cy="11" r="1"/><circle cx="17" cy="13" r="1"/>',
};
const TOOL_ICONS = {
  "new-profile": '<path d="M4 4h10l6 6v10H4z"/><path d="M14 4v6h6M12 13v6M9 16h6"/>',
  "new-stereotype": '<path d="M7 6l-4 6 4 6M17 6l4 6-4 6"/><path d="M12 9v6M9 12h6"/>',
  "add-property": '<path d="M4 6h10M4 12h10M4 18h6"/><path d="M18 14v6M15 17h6"/>',
  delete: '<path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  import: '<path d="M12 3v12M7 10l5 5 5-5M4 19h16"/>',
  export: '<path d="M12 15V3M7 8l5-5 5 5M4 19h16"/>',
  batch: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 17.5h7M17.5 14v7"/>',
  profile: '<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  manage: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="10" cy="18" r="1.6"/>',
};
const svg = (paths) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const DASH = { dashed: "6 4", dotted: "2 3", dashdot: "8 3 2 3" };
/** Small tag shape filled / outlined with a stereotype's style colours. */
const swatch = (st = {}) =>
  `<svg class="pf-swatch" viewBox="0 0 16 12" aria-hidden="true"><path d="M1.5 1.5h9l4 4.5-4 4.5h-9z"
     fill="${esc(st.fill || "#ffffff")}" stroke="${esc(st.stroke || "#94a3b8")}" stroke-width="1.3" stroke-linejoin="round"/></svg>`;
const CATEGORY_LABEL = c => c || "All elements";
const NUMERIC = new Set(["double", "single", "int8", "int16", "int32", "int64",
                         "uint8", "uint16", "uint32", "uint64"]);

let META = { types: [], categories: [], icons: [], line_styles: [], units: [] };
const collapsed = new Set();          // inspector groups the user collapsed (stereotype ids)

export default async function install(studio) {
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);
  try { META = await studio.api("GET", "/api/profiles/meta"); } catch { /* logged by api() */ }

  const editor = new ProfileEditor(studio);
  studio.registerTab({
    id: "profiles", title: "Profiles", order: 30,
    mount(pane) { editor.mount(pane); },
    onShow() { editor.refresh(); },
  });
  studio.registerInspectorSection({
    id: "stereotypes", title: "Stereotypes", order: 10,
    render(el, box) { return renderInspector(studio, editor, el, box); },
  });
  studio.registerToolbarButton({ id: "profile-editor", label: "Profile Editor", group: "Profiles",
                                 title: "Open the Profile Editor", onClick() { studio.switchTab("profiles"); } });
  studio.registerToolbarButton({ id: "batch-apply-stereotype", label: "Apply stereotypes…", group: "Profiles",
                                 title: "Apply a stereotype to the selection, a composition or the whole model",
                                 onClick() { openBatchDialog(studio); } });
  studio.on("model-changed", () => {
    decorateTree(studio);
    if (editor.visible()) editor.refresh();
  });
  studio.profiles = { editor, openBatchDialog: () => openBatchDialog(studio) };
}

/* ------------------------------------------------------------------ helpers */

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m])); }

function option(value, label, selected) {
  return `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label)}</option>`;
}

function errorText(e) { return String(e?.message || e).replace(/^Error:\s*/, ""); }

/** True the first time `value` is committed from `input` (Enter and the following
 *  change event must not send the same edit twice); typing again re-arms it. */
function once(input, value) {
  if (!input._pfArmed) {
    input._pfArmed = true;
    input.addEventListener("input", () => { delete input._pfSent; });
  }
  const key = String(value);
  if (input._pfSent === key) return false;
  input._pfSent = key;
  return true;
}

/** studio.modal with keyboard support (Enter submits, Escape cancels) and inline errors. */
function openModal(studio, title, html, onSubmit) {
  studio.modal(title, `${html}<div class="pf-msg err" data-pf-modal-msg></div>`, async (values) => {
    const msg = document.querySelector("[data-pf-modal-msg]");
    try { await onSubmit(values); }
    catch (e) { if (msg) msg.textContent = errorText(e); throw e; }
  });
  const root = document.getElementById("modal-root");
  const form = root.querySelector("#modal-form");
  const submit = root.querySelector("[data-modal-submit]");
  const cancel = root.querySelector("[data-modal-cancel]");
  submit.type = "button"; cancel.type = "button";
  form.addEventListener("submit", (e) => { e.preventDefault(); submit.click(); });
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") { e.preventDefault(); submit.click(); }
  });
  root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); cancel.click(); } });
  setTimeout(() => {
    const first = form.querySelector("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select, textarea");
    first?.focus(); first?.select?.();
  }, 0);
  return form;
}

function uniqueName(base, taken) {
  if (!taken.has(base)) return base;
  let i = 1;
  while (taken.has(`${base}${i}`)) i++;
  return `${base}${i}`;
}

function colorFor(hex) {
  // readable text colour on a fill
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  if (!m) return "";
  const [r, g, b] = m.slice(1).map(x => parseInt(x, 16));
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? "#0f172a" : "#ffffff";
}

function expandHex(hex) {
  const m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(hex || "");
  return m ? `#${m[1]}${m[1]}${m[2]}${m[2]}${m[3]}${m[3]}` : (hex || "");
}

/* ------------------------------------------------------------------ tree badges */

function decorateTree(studio) {
  for (const li of document.querySelectorAll("#tree .tree-node")) {
    const node = studio.state.treeIndex.get(li.dataset.id);
    if (!node?.stereotypes?.length) continue;
    const byBadge = new Map(node.stereotypes.map(s => [`«${s.name}»`, s]));
    for (const b of li.querySelector(":scope > .row").querySelectorAll(":scope > .tree-badge")) {
      const app = byBadge.get(b.textContent);
      if (!app) continue;                      // a badge from another feature
      const st = app.style || {};
      b.classList.add("pf-badge");
      b.title = app.qualified_name || app.name;
      if (st.fill) { b.style.background = st.fill; b.style.color = st.text || colorFor(expandHex(st.fill)); }
      else if (st.text) b.style.color = st.text;
      if (st.stroke) b.style.borderColor = st.stroke;
      if (st.icon && ICONS[st.icon] && !b.querySelector("svg")) b.insertAdjacentHTML("afterbegin", svg(ICONS[st.icon]));
    }
  }
}

/* ------------------------------------------------------------------ inspector section */

function renderInspector(studio, editor, el, box) {
  if (["Profile", "Stereotype", "StereotypeTag"].includes(el.kind)) {
    box.innerHTML = `<div class="text-sm text-slate-600 flex items-center gap-2">
        ${el.kind === "Profile" ? "This profile" : el.kind === "Stereotype" ? "This stereotype" : "This stereotype property"}
        is edited in the Profile Editor.
        <button type="button" class="btn-action" data-pf="open-editor">Open in Profile Editor</button></div>`;
    box.querySelector("[data-pf=open-editor]").onclick = () => {
      const id = el.kind === "StereotypeTag" ? el.owner_id : el.id;
      editor.pendingSelect = { kind: el.kind === "Profile" ? "profile" : "stereotype", id };
      studio.switchTab("profiles");
    };
    return;
  }
  if (el.id === undefined || !el.owner_id) return false;     // the project root takes no stereotypes
  box.innerHTML = `<div class="text-xs text-slate-400">Loading stereotypes…</div>`;
  box.dataset.pfElement = el.id;
  studio.api("GET", `/api/elements/${encodeURIComponent(el.id)}/stereotypes`)
    .then(view => { if (box.dataset.pfElement === el.id) fillInspector(studio, box, view); })
    .catch(e => { box.innerHTML = `<div class="pf-msg err">${esc(errorText(e))}</div>`; });
}

function fillInspector(studio, box, view) {
  const eid = view.element.id;
  const applicable = view.applicable || [];
  const bar = `
    <div class="pf-insp-bar">
      <select class="input" data-pf="add-stereotype" aria-label="Add stereotype" ${applicable.length ? "" : "disabled"}
              title="Stereotypes of the model's profiles that apply to this ${esc(view.element.kind)}">
        <option value="">${applicable.length ? "Add stereotype…" : "No applicable stereotypes"}</option>
        ${applicable.map(s => option(s.id, s.qualified_name, false)).join("")}
      </select>
      <button type="button" class="btn-action" data-pf="open-editor" title="Define profiles and stereotypes">Profile Editor…</button>
      <span class="flex-1"></span>
      <button type="button" class="btn-action" data-pf="remove-all" ${view.applied.length ? "" : "disabled"}>Remove all</button>
    </div>`;
  const groups = view.applied.map(app => {
    const st = app.style || {};
    const sw = st.fill || st.stroke ? swatch(st) : "";
    const icon = st.icon && ICONS[st.icon] ? `<span class="text-slate-500" style="width:14px;display:inline-flex">${svg(ICONS[st.icon])}</span>` : "";
    const multi = app.groups.filter(g => g.properties.length).length > 1;
    const rows = app.groups.map(g => {
      if (!g.properties.length) return "";
      const head = multi ? `<div class="pf-ghead">${esc(g.stereotype)}</div>` : "";
      return head + g.properties.map(p => propertyEditor(p)).join("");
    }).join("");
    return `
      <details class="pf-app" data-app="${esc(app.id)}" ${collapsed.has(app.id) ? "" : "open"}>
        <summary title="${esc(app.description || "")}">
          <span class="pf-caret">▸</span>${sw}${icon}
          <span class="pf-name">«${esc(app.qualified_name)}»</span>
          <span class="flex-1"></span>
          <button type="button" class="pf-icon-btn danger" data-pf="remove" data-st="${esc(app.id)}"
                  title="Remove «${esc(app.qualified_name)}»" aria-label="Remove ${esc(app.qualified_name)}">✕</button>
        </summary>
        <div class="pf-props">${rows || '<div class="text-xs text-slate-400 col-span-3">No properties.</div>'}</div>
      </details>`;
  }).join("");
  box.innerHTML = bar + (groups || `<div class="text-xs text-slate-400">No stereotypes applied.</div>`) +
                  `<div class="pf-msg" data-pf="msg"></div>`;

  const msg = (text, cls) => { const m = box.querySelector("[data-pf=msg]"); if (m) { m.textContent = text; m.className = `pf-msg ${cls || ""}`; } };
  const rerender = (v) => fillInspector(studio, box, v);

  box.querySelector("[data-pf=add-stereotype]").addEventListener("change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    try {
      const v = await studio.api("POST", `/api/elements/${encodeURIComponent(eid)}/stereotypes`, { stereotype: id });
      const name = applicable.find(s => s.id === id)?.qualified_name || id;
      studio.log(`Applied «${name}» to ${view.element.qualified_name}`, "ok");
      rerender(v);
      await studio.refreshTree();
    } catch (err) { msg(errorText(err), "err"); e.target.value = ""; }
  });
  box.querySelector("[data-pf=open-editor]").addEventListener("click", () => studio.switchTab("profiles"));
  box.querySelector("[data-pf=remove-all]").addEventListener("click", async () => {
    try {
      const v = await studio.api("DELETE", `/api/elements/${encodeURIComponent(eid)}/stereotypes`);
      studio.log(`Removed ${v.removed} stereotype(s) from ${view.element.qualified_name}`, "warning");
      rerender(v);
      await studio.refreshTree();
    } catch (err) { msg(errorText(err), "err"); }
  });
  for (const btn of box.querySelectorAll("[data-pf=remove]")) {
    btn.addEventListener("click", async (e) => {
      e.preventDefault(); e.stopPropagation();
      try {
        const v = await studio.api("DELETE", `/api/elements/${encodeURIComponent(eid)}/stereotypes/${encodeURIComponent(btn.dataset.st)}`);
        studio.log(`Removed stereotype from ${view.element.qualified_name}`, "warning");
        rerender(v);
        await studio.refreshTree();
      } catch (err) { msg(errorText(err), "err"); }
    });
  }
  for (const det of box.querySelectorAll("details.pf-app")) {
    det.addEventListener("toggle", () => { det.open ? collapsed.delete(det.dataset.app) : collapsed.add(det.dataset.app); });
  }
  for (const input of box.querySelectorAll("[data-path]")) {
    const commit = async () => {
      const path = input.dataset.path;
      const value = input.type === "checkbox" ? input.checked : input.value;
      if (input.type !== "checkbox" && value === input.dataset.orig) return;
      if (!once(input, value)) return;
      try {
        const v = await studio.api("PATCH", `/api/elements/${encodeURIComponent(eid)}/stereotypes`, { property: path, value });
        const shown = findValue(v, path);
        studio.log(`${view.element.name}: ${path} = ${shown?.display ?? ""}`, "ok");
        const focusPath = document.activeElement === input ? path : null;
        rerender(v);
        if (focusPath) box.querySelector(`[data-path="${CSS.escape(focusPath)}"]`)?.focus();
        msg(`${path} = ${shown?.display ?? ""}`, "ok");
      } catch (err) {
        input.classList.add("pf-invalid");
        input.setAttribute("aria-invalid", "true");
        input.title = errorText(err);
        msg(errorText(err), "err");
      }
    };
    input.addEventListener("change", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      if (e.key === "Escape" && input.dataset.orig !== undefined) { input.value = input.dataset.orig; input.classList.remove("pf-invalid"); }
    });
  }
}

function findValue(view, path) {
  for (const app of view.applied || []) for (const g of app.groups) for (const p of g.properties) if (p.path === path) return p;
  return null;
}

function propertyEditor(p) {
  const id = `pf-v-${p.id}-${Math.random().toString(36).slice(2, 7)}`;
  const tip = [p.description, p.type + (p.unit ? ` [${p.unit}]` : ""),
               p.min != null ? `min ${p.min}` : "", p.max != null ? `max ${p.max}` : ""].filter(Boolean).join(" · ");
  const label = `<label for="${id}" title="${esc(tip)}">${esc(p.name)}</label>`;
  const invalid = p.valid === false ? " pf-invalid" : "";
  let editor;
  if (p.type === "boolean") {
    editor = `<input type="checkbox" id="${id}" data-path="${esc(p.path)}" ${p.value ? "checked" : ""}/>`;
  } else if (p.type === "enumeration") {
    const lits = [...p.literals];
    const cur = p.value ?? "";
    editor = `<select class="input${invalid}" id="${id}" data-path="${esc(p.path)}" data-orig="${esc(cur)}">
      ${cur === "" || !lits.includes(cur) ? option(cur, cur === "" ? "—" : `${cur} (invalid)`, true) : ""}
      ${lits.map(l => option(l, l, l === cur)).join("")}</select>`;
  } else {
    const text = p.value === null || p.value === undefined ? "" :
      (NUMERIC.has(p.type) && typeof p.value === "number" ? (p.display || "").replace(new RegExp(`\\s*${escapeRe(p.unit)}$`), "") : String(p.value));
    const hint = NUMERIC.has(p.type)
      ? `Number, expression (2*0.75)${p.unit ? ` or value with a compatible unit (e.g. 3 ${p.unit === "kg" ? "lb" : p.unit})` : ""}`
      : "Text";
    editor = `<input class="input${invalid}" id="${id}" data-path="${esc(p.path)}" data-orig="${esc(text)}" value="${esc(text)}"
              ${NUMERIC.has(p.type) ? 'inputmode="decimal"' : ""} placeholder="${esc(hint)}" title="${esc(p.problem || hint)}" autocomplete="off"/>`;
  }
  const unit = `<span class="pf-unit">${esc(p.unit || "")}</span>`;
  const problem = p.valid === false && p.problem ? `<div class="pf-field-err">${esc(p.problem)}</div>` : "";
  return label + editor + unit + problem;
}

function escapeRe(s) { return String(s || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

/* ------------------------------------------------------------------ batch dialog */

async function openBatchDialog(studio, presetStereotype) {
  let data;
  try { data = await studio.api("GET", "/api/profiles"); } catch { return; }
  const all = [...data.profiles.flatMap(p => p.stereotypes), ...data.ungrouped].filter(s => !s.abstract);
  if (!all.length) { studio.log("Define a (non-abstract) stereotype in the Profile Editor first.", "warning"); return; }
  const sel = studio.getSelection();
  const current = studio.selected;
  const pick = presetStereotype || all[0].id;
  const scopeDefault = sel.length > 1 ? "selection" : (current ? "composition" : "model");
  openModal(studio, "Apply stereotype to elements", `
    <label class="block text-sm">Stereotype
      <select class="input" name="stereotype" data-pf="batch-stereotype">
        ${all.map(s => option(s.id, `${s.qualified_name} — ${CATEGORY_LABEL(s.effective_applies_to)}`, s.id === pick)).join("")}
      </select></label>
    <fieldset class="text-sm space-y-1 mt-2"><legend class="text-slate-600 mb-1">Scope</legend>
      <label class="flex items-center gap-2"><input type="radio" name="scope" value="selection" ${sel.length ? "" : "disabled"} ${scopeDefault === "selection" ? "checked" : ""}/>
        Selected elements (${sel.length})</label>
      <label class="flex items-center gap-2"><input type="radio" name="scope" value="composition" ${current ? "" : "disabled"} ${scopeDefault === "composition" ? "checked" : ""}/>
        Current package / composition: <b>${esc(current?.name || "—")}</b> and everything inside it</label>
      <label class="flex items-center gap-2"><input type="radio" name="scope" value="model" ${scopeDefault === "model" ? "checked" : ""}/>
        Whole model</label>
    </fieldset>
    <label class="block text-sm mt-2">Only elements of category
      <select class="input" name="category" data-pf="batch-category">
        ${option("", "(the stereotype's applies-to)", true)}
        ${META.categories.map(c => option(c, c, false)).join("")}
      </select></label>`, async (o) => {
    const body = { scope: o.scope || "model", category: o.category || null };
    if (body.scope === "selection") body.ids = sel;
    if (body.scope === "composition") body.root = current?.id;
    const out = await studio.api("POST", `/api/stereotypes/${encodeURIComponent(o.stereotype)}/batch`, body);
    studio.log(`Applied «${out.stereotype}» to ${out.count} element(s)` +
               (out.skipped.length ? `; skipped ${out.skipped.length} (${[...new Set(out.skipped.map(s => s.reason))].join(", ")})` : ""),
               out.count ? "ok" : "warning");
    await studio.refreshTree();
    if (studio.state.selectedId) await studio.selectElement(studio.state.selectedId);
  });
}

/* ------------------------------------------------------------------ Profile Editor */

class ProfileEditor {
  constructor(studio) {
    this.studio = studio;
    this.data = { profiles: [], ungrouped: [], imports: [] };
    this.sel = null;              // {kind: "profile"|"stereotype", id}
    this.pendingSelect = null;
    this.pendingEnum = new Map(); // property id -> true while waiting for literals
    this.loading = null;
  }

  visible() { return this.pane && !this.pane.classList.contains("hidden"); }

  mount(pane) {
    this.pane = pane;
    const tool = (cmd, label, title) =>
      `<button type="button" class="pf-tool" data-pf-cmd="${cmd}" title="${esc(title)}">${svg(TOOL_ICONS[cmd])}<span>${esc(label)}</span></button>`;
    pane.innerHTML = `
      <div class="pf-editor">
        <div class="pf-strip" role="toolbar" aria-label="Profile Editor">
          <div class="pf-group"><div class="pf-group-tools">
              ${tool("new-profile", "New Profile", "Create a profile")}
              ${tool("import", "Import", "Import a profile file (.json)")}
              ${tool("export", "Export", "Export the selected profile to a file")}
              ${tool("manage", "Manage", "Profiles in this model and their import history")}
            </div><div class="pf-group-label">Profile</div></div>
          <div class="pf-group"><div class="pf-group-tools">
              ${tool("new-stereotype", "New Stereotype", "Add a stereotype to the selected profile")}
              ${tool("add-property", "Add Property", "Add a property to the selected stereotype")}
              ${tool("delete", "Delete", "Delete the selected profile or stereotype (Del)")}
            </div><div class="pf-group-label">Stereotype</div></div>
          <div class="pf-group"><div class="pf-group-tools">
              ${tool("batch", "Apply to Elements", "Apply the selected stereotype to many elements")}
            </div><div class="pf-group-label">Model</div></div>
        </div>
        <div class="pf-body">
          <aside class="pf-browser" tabindex="0" role="tree" aria-label="Profiles and stereotypes">
            <div class="pf-pane-title">Profile browser</div>
            <div data-pf="tree"></div>
          </aside>
          <section class="pf-details" data-pf="details"></section>
        </div>
      </div>`;
    pane.querySelector(".pf-strip").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-pf-cmd]");
      if (btn && !btn.disabled) this.command(btn.dataset.pfCmd);
    });
    const tree = pane.querySelector(".pf-browser");
    tree.addEventListener("click", (e) => {
      const row = e.target.closest(".pf-row");
      if (row) { this.select(row.dataset.kind, row.dataset.pfId); tree.focus(); }
    });
    tree.addEventListener("keydown", (e) => this.treeKey(e));
  }

  async load() {
    this.data = await this.studio.api("GET", "/api/profiles");
    this.index = new Map();
    for (const p of this.data.profiles) {
      this.index.set(p.id, { kind: "profile", obj: p });
      for (const s of p.stereotypes) this.index.set(s.id, { kind: "stereotype", obj: s, profile: p });
    }
    for (const s of this.data.ungrouped) this.index.set(s.id, { kind: "stereotype", obj: s, profile: null });
  }

  allStereotypes() { return [...this.data.profiles.flatMap(p => p.stereotypes), ...this.data.ungrouped]; }

  async refresh() {
    if (!this.pane) return;
    // Coalesce refresh storms (model-changed after every edit).
    if (this.loading) { this.again = true; return this.loading; }
    this.loading = (async () => {
      try {
        do {
          this.again = false;
          await this.load();
        } while (this.again);
        if (this.pendingSelect) { this.sel = this.pendingSelect; this.pendingSelect = null; }
        if (this.sel && this.sel.kind !== "manage" && !this.index.has(this.sel.id)) this.sel = null;
        if (!this.sel && this.data.profiles.length) this.sel = { kind: "profile", id: this.data.profiles[0].id };
        this.render();
      } catch { /* logged by api() */ }
      finally { this.loading = null; }
    })();
    return this.loading;
  }

  current() { return this.sel ? this.index.get(this.sel.id) : null; }
  currentProfile() {
    const c = this.current();
    return c ? (c.kind === "profile" ? c.obj : c.profile) : null;
  }

  select(kind, id) {
    this.sel = { kind, id };
    this.render();
  }

  render() {
    this.renderTree();
    this.withFocus(() => this.renderDetails());
    this.updateTools();
  }

  updateTools() {
    const c = this.current();
    const set = (cmd, on) => { const b = this.pane.querySelector(`[data-pf-cmd="${cmd}"]`); if (b) b.disabled = !on; };
    set("export", !!this.currentProfile());
    set("new-stereotype", !!this.currentProfile());
    set("add-property", c?.kind === "stereotype");
    set("delete", !!c);
    set("batch", c?.kind === "stereotype" && !c.obj.abstract);
  }

  renderTree() {
    const host = this.pane.querySelector("[data-pf=tree]");
    const row = (kind, obj, label, sub, extra = "") => {
      const sel = this.sel && this.sel.id === obj.id ? " sel" : "";
      return `<div class="pf-row ${kind === "stereotype" ? "st" : ""}${obj.abstract ? " abstract" : ""}${sel}" role="treeitem"
                   aria-selected="${sel ? "true" : "false"}" data-kind="${kind}" data-pf-id="${esc(obj.id)}">${extra}
                <span class="pf-name">${label}</span><span class="pf-sub">${esc(sub)}</span></div>`;
    };
    const stRow = (s) => {
      const st = s.effective_style || {};
      const sw = swatch(st);
      return row("stereotype", s, `«${esc(s.name)}»`, s.applies_to || (s.effective_applies_to ? `(${s.effective_applies_to})` : "All"), sw);
    };
    let html = "";
    for (const p of this.data.profiles) {
      html += row("profile", p, esc(p.name), p.version ? `v${p.version}` : "", `<span class="text-slate-500">${svg(TOOL_ICONS.profile)}</span>`);
      html += p.stereotypes.map(stRow).join("");
    }
    if (this.data.ungrouped.length) {
      html += `<div class="pf-pane-title" style="margin-top:8px">Stereotypes without a profile</div>`;
      html += this.data.ungrouped.map(stRow).join("");
    }
    host.innerHTML = html || `<div class="pf-empty">No profiles yet. Use <b>New Profile</b> or <b>Import</b>.</div>`;
  }

  treeKey(e) {
    if (e.target.closest("input, select, textarea")) return;
    const rows = [...this.pane.querySelectorAll(".pf-row")];
    const i = rows.findIndex(r => r.classList.contains("sel"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (next) this.select(next.dataset.kind, next.dataset.pfId);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault(); e.stopPropagation();       // never let the core delete the tree element
      this.command("delete");
    } else if (e.key === "Enter" || e.key === "F2") {
      e.preventDefault();
      this.pane.querySelector('[data-pf="details"] [data-field="name"]')?.focus();
    }
  }

  /** Re-render while keeping keyboard focus on the same logical field. */
  withFocus(fn) {
    const a = document.activeElement;
    const key = a && this.pane.contains(a) ? a.dataset.focusKey : null;
    fn();
    if (key) {
      const el = this.pane.querySelector(`[data-focus-key="${CSS.escape(key)}"]`);
      if (el) { el.focus(); if (el.select && el.tagName === "INPUT" && el.type === "text") el.select(); }
    }
  }

  message(text, cls = "") {
    const m = this.pane.querySelector("[data-pf=msg]");
    if (m) { m.textContent = text; m.className = `pf-msg ${cls}`; }
  }

  async command(cmd) {
    const c = this.current();
    if (cmd === "new-profile") return this.newProfile();
    if (cmd === "new-stereotype") return this.newStereotype();
    if (cmd === "add-property" && c?.kind === "stereotype") return this.addProperty(c.obj);
    if (cmd === "delete" && c) return this.deleteCurrent();
    if (cmd === "export") return this.exportProfile();
    if (cmd === "import") return this.importProfile();
    if (cmd === "manage") return this.select("manage", "manage");
    if (cmd === "batch") return openBatchDialog(this.studio, c?.kind === "stereotype" ? c.obj.id : undefined);
  }

  newProfile() {
    const name = uniqueName("Profile", new Set(this.data.profiles.map(p => p.name)));
    openModal(this.studio, "New profile", `
      <label class="block text-sm">Name <input class="input" name="name" value="${esc(name)}" autocomplete="off"/></label>
      <label class="block text-sm">Version <input class="input" name="version" value="1.0" autocomplete="off"/></label>
      <label class="block text-sm">Description <textarea class="input h-16" name="description"></textarea></label>`,
      async (o) => {
        const p = await this.studio.api("POST", "/api/profiles", o);
        this.studio.log(`Created profile ${p.name}`, "ok");
        this.pendingSelect = { kind: "profile", id: p.id };
        await this.studio.refreshTree();
        await this.refresh();
      });
  }

  newStereotype() {
    const prof = this.currentProfile();
    if (!prof) return;
    const name = uniqueName("Stereotype", new Set(prof.stereotypes.map(s => s.name)));
    openModal(this.studio, `New stereotype in ${esc(prof.name)}`, `
      <label class="block text-sm">Name <input class="input" name="name" value="${esc(name)}" autocomplete="off"/></label>
      <label class="block text-sm">Applies to
        <select class="input" name="applies_to">${["", ...META.categories].map(c => option(c, CATEGORY_LABEL(c), c === "Component")).join("")}</select></label>
      <label class="block text-sm">Base stereotype
        <select class="input" name="base">${option("", "(none)", true)}${this.allStereotypes().map(s => option(s.id, s.qualified_name, false)).join("")}</select></label>
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="abstract"/> Abstract (only used as a base)</label>
      <label class="block text-sm">Description <textarea class="input h-14" name="description"></textarea></label>`,
      async (o) => {
        const body = { name: o.name, applies_to: o.applies_to || "", base: o.base || null,
                       abstract: o.abstract === "on", description: o.description || "" };
        const st = await this.studio.api("POST", `/api/profiles/${encodeURIComponent(prof.id)}/stereotypes`, body);
        this.studio.log(`Created stereotype «${st.qualified_name}»`, "ok");
        this.pendingSelect = { kind: "stereotype", id: st.id };
        await this.studio.refreshTree();
        await this.refresh();
      });
  }

  async addProperty(st) {
    try {
      const out = await this.studio.api("POST", `/api/stereotypes/${encodeURIComponent(st.id)}/properties`, {});
      this.studio.log(`Added property ${out.path}`, "ok");
      await this.refresh();
      const input = this.pane.querySelector(`tr[data-prop-id="${CSS.escape(out.id)}"] [data-col="name"]`);
      input?.focus(); input?.select();
    } catch (e) { this.message(errorText(e), "err"); }
  }

  deleteCurrent(c = this.current()) {
    if (!c?.obj) return;
    const isProfile = c.kind === "profile";
    const o = c.obj;
    const apps = isProfile ? o.stereotypes.reduce((n, s) => n + (s.application_count || 0), 0) : (o.application_count || 0);
    const what = isProfile ? `profile <b>${esc(o.name)}</b> and its ${o.stereotypes.length} stereotype(s)`
                           : `stereotype <b>«${esc(o.qualified_name)}»</b>`;
    openModal(this.studio, isProfile ? "Delete profile" : "Delete stereotype", `
      <p class="text-sm">Delete ${what}?</p>
      ${apps ? `<p class="text-sm text-amber-700 mt-2">It is applied to ${apps} element(s); those applications and their values will be removed.</p>` : ""}
      ${!isProfile && o.derived?.length ? `<p class="text-sm text-amber-700 mt-2">Derived stereotypes lose their base: ${o.derived.map(esc).join(", ")}</p>` : ""}`,
      async () => {
        const url = isProfile ? `/api/profiles/${encodeURIComponent(o.id)}` : `/api/stereotypes/${encodeURIComponent(o.id)}`;
        const out = await this.studio.api("DELETE", url);
        this.studio.log(`Deleted ${out.deleted} (${out.applications_removed} application(s) removed)`, "warning");
        if (this.sel?.kind !== "manage") this.sel = isProfile || !c.profile ? null : { kind: "profile", id: c.profile.id };
        await this.studio.refreshTree();
        await this.refresh();
      });
  }

  async exportProfile(prof = this.currentProfile()) {
    if (!prof) return;
    try {
      const out = await this.studio.api("GET", `/api/profiles/${encodeURIComponent(prof.id)}/export`);
      this.studio.download(out.file_name, out.text);
      this.studio.log(`Exported profile ${prof.name} to ${out.file_name}`, "ok");
    } catch { /* logged */ }
  }

  importProfile() {
    // Own picker (not studio.openFile) so the import log records the file name.
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".json,application/json";
    inp.onchange = async () => {
      const f = inp.files?.[0];
      if (f) await this.importText(await f.text(), f.name);
    };
    inp.click();
  }

  /** Import profile file content; asks before replacing an existing profile. */
  async importText(text, fileName = "") {
    let name = null;
    try { const d = JSON.parse(text); name = (d.profile || d).name; }
    catch (e) { this.studio.log(`Not a profile file: ${errorText(e)}`, "error"); return; }
    const run = async (replace) => {
      const out = await this.studio.api("POST", "/api/profiles/import", { text, replace, file_name: fileName || "" });
      this.studio.log(`${out.created ? "Imported" : "Updated"} profile ${out.profile.name} (version ${out.profile.version || "?"})`, "ok");
      for (const r of out.report) this.studio.log(`  ${r}`, "info");
      this.pendingSelect = { kind: "profile", id: out.profile.id };
      await this.studio.refreshTree();
      await this.refresh();
    };
    const existing = this.data.profiles.find(p => p.name === name);
    if (!existing) { try { await run(false); } catch { /* logged */ } return; }
    openModal(this.studio, "Profile already in the model", `
      <p class="text-sm">The model already has profile <b>${esc(name)}</b> (version ${esc(existing.version || "?")}).</p>
      <p class="text-sm mt-2">Replace it with the file? Stereotypes and properties are matched by id and name;
      values follow renames and unit changes, and anything missing from the file is removed from the model.</p>`,
      () => run(true));
  }

  /* ---------------- details ---------------- */

  renderDetails() {
    const host = this.pane.querySelector("[data-pf=details]");
    if (this.sel?.kind === "manage") return this.renderManage(host);
    const c = this.current();
    if (!c) {
      host.innerHTML = `<div class="pf-empty">Create a profile with <b>New Profile</b>, or import one, then add stereotypes
        with typed properties (mass, power, DAL, ATA chapter, MTBF…). Apply them to elements from the
        <b>Stereotypes</b> section of the Properties tab.</div>`;
      return;
    }
    if (c.kind === "profile") this.renderProfile(host, c.obj);
    else this.renderStereotype(host, c.obj, c.profile);
  }

  /** Profiles in the model with their provenance, and the import history. */
  renderManage(host) {
    const profiles = this.data.profiles;
    const apps = (p) => p.stereotypes.reduce((n, s) => n + (s.application_count || 0), 0);
    const source = (p) => p.source?.imported_at
      ? `${esc(p.source.file || "file")} <span class="text-slate-400">(${esc(p.source.imported_at)})</span>` : "created in this model";
    const imports = this.data.imports || [];
    host.innerHTML = `
      <div class="pf-h"><span class="pf-title">Profiles in this model</span><span class="pf-chip">${profiles.length} profile(s)</span></div>
      <p class="text-sm text-slate-600 mb-3" style="max-width:760px">Profiles are stored in the project. Export one to share it as a
        <code>.profile.json</code> file; import a file to add it to another model (an import with the same name updates the
        profile in place). Removing a profile removes its stereotypes from every element.</p>
      ${profiles.length ? `<div class="pf-table-wrap" style="max-width:900px"><table class="pf-table pf-auto" data-pf="manage-table">
        <thead><tr><th>Profile</th><th>Version</th><th>Stereotypes</th><th>Applications</th><th>Source</th><th class="pf-actions-h">Actions</th></tr></thead><tbody>
        ${profiles.map(p => `<tr data-profile-id="${esc(p.id)}"><td style="padding:5px 6px"><a href="#" data-goto-profile="${esc(p.id)}" class="text-blue-700">${esc(p.name)}</a></td>
          <td style="padding:5px 6px">${esc(p.version)}</td><td style="padding:5px 6px">${p.stereotype_count}</td>
          <td style="padding:5px 6px">${apps(p)}</td><td style="padding:5px 6px">${source(p)}</td>
          <td class="pf-actions" style="width:150px"><button type="button" class="pf-icon-btn" data-export-profile="${esc(p.id)}">Export</button>
            <button type="button" class="pf-icon-btn danger" data-remove-profile="${esc(p.id)}">Remove</button></td></tr>`).join("")}
        </tbody></table></div>` : `<div class="pf-empty">No profiles yet. Use <b>New Profile</b> or <b>Import</b>.</div>`}
      <div class="pf-section-title">Import history</div>
      ${imports.length ? `<ul class="text-sm space-y-1" data-pf="import-log">${imports.map(x => `<li><b>${esc(x.name)}</b> ${esc(x.version || "")}
          — ${esc(x.mode)} from <code>${esc(x.file || "(text)")}</code> on ${esc(x.imported_at)}</li>`).join("")}</ul>`
        : `<div class="text-sm text-slate-500">No profile has been imported into this model.</div>`}
      <div class="pf-msg" data-pf="msg"></div>`;
    for (const a of host.querySelectorAll("[data-goto-profile]")) {
      a.addEventListener("click", (e) => { e.preventDefault(); this.select("profile", a.dataset.gotoProfile); });
    }
    for (const b of host.querySelectorAll("[data-export-profile]")) {
      b.addEventListener("click", () => this.exportProfile(profiles.find(p => p.id === b.dataset.exportProfile)));
    }
    for (const b of host.querySelectorAll("[data-remove-profile]")) {
      b.addEventListener("click", () => this.deleteCurrent({ kind: "profile", obj: profiles.find(p => p.id === b.dataset.removeProfile) }));
    }
  }

  renderProfile(host, p) {
    const roots = p.stereotypes.filter(s => !s.abstract && ["", "Component", "Architecture"].includes(s.effective_applies_to));
    const src = p.source?.file || p.source?.imported_at
      ? `Imported${p.source.file ? ` from <code>${esc(p.source.file)}</code>` : ""}${p.source.imported_at ? ` on ${esc(p.source.imported_at)}` : ""}` : "Created in this model";
    host.innerHTML = `
      <div class="pf-h"><span class="pf-title">${esc(p.name)}</span><span class="pf-chip">Profile</span>
        <span class="pf-chip">${p.stereotype_count} stereotype(s)</span></div>
      <div class="pf-form" data-pf="profile-form">
        <label for="pf-p-name">Name</label><input class="input" id="pf-p-name" data-field="name" data-focus-key="p-name" value="${esc(p.name)}" autocomplete="off"/>
        <label for="pf-p-version">Version</label><input class="input" id="pf-p-version" data-field="version" data-focus-key="p-version" value="${esc(p.version)}" autocomplete="off"/>
        <label for="pf-p-desc" class="self-start pt-1">Description</label><textarea class="input h-16" id="pf-p-desc" data-field="description" data-focus-key="p-desc">${esc(p.description)}</textarea>
        <label for="pf-p-root">Model root stereotype</label>
        <select class="input" id="pf-p-root" data-field="root_stereotype" data-focus-key="p-root">
          ${option("", "(none)", !p.root_stereotype_id)}
          ${roots.map(s => option(s.id, s.qualified_name, s.id === p.root_stereotype_id)).join("")}
        </select>
        <label>Source</label><div class="text-sm text-slate-600">${src}</div>
      </div>
      <div class="pf-msg" data-pf="msg"></div>
      <div class="pf-section-title">Stereotypes</div>
      ${p.stereotypes.length ? `<table class="pf-table pf-auto" style="max-width:760px" data-pf="profile-stereotypes"><thead><tr><th>Stereotype</th><th>Applies to</th><th>Base</th><th>Properties</th><th>Applied to</th></tr></thead><tbody>
        ${p.stereotypes.map(s => `<tr class="pf-inherited" style="cursor:pointer" data-goto="${esc(s.id)}"><td style="color:#334155">«${esc(s.name)}»${s.abstract ? " <i>(abstract)</i>" : ""}</td>
          <td>${esc(CATEGORY_LABEL(s.effective_applies_to))}</td><td>${esc(s.base || "")}</td><td>${s.properties.length}</td><td>${s.application_count}</td></tr>`).join("")}
        </tbody></table>` : `<div class="text-sm text-slate-500">No stereotypes yet — use <b>New Stereotype</b>.</div>`}`;
    for (const tr of host.querySelectorAll("[data-goto]")) tr.onclick = () => this.select("stereotype", tr.dataset.goto);
    this.bindFields(host, async (field, value) => {
      const out = await this.studio.api("PATCH", `/api/profiles/${encodeURIComponent(p.id)}`, { [field]: value || (field === "root_stereotype" ? null : value) });
      if (out.root_applied?.length) this.studio.log(`Applied model root stereotype to ${out.root_applied.join(", ")}`, "ok");
      return `Profile ${out.name}: ${field} updated`;
    }, true);
  }

  renderStereotype(host, s, prof) {
    const all = this.allStereotypes();
    const descendants = new Set([s.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const x of all) if (x.base_id && descendants.has(x.base_id) && !descendants.has(x.id)) { descendants.add(x.id); grew = true; }
    }
    const baseChoices = all.filter(x => !descendants.has(x.id));
    const st = s.style || {};
    const eff = s.effective_style || {};
    const colorField = (key, label) => `
      <label for="pf-s-${key}">${label}</label>
      <div class="pf-inline">
        <input type="color" class="pf-color" id="pf-s-${key}" data-style="${key}" data-focus-key="s-${key}" value="${esc(expandHex(st[key]) || "#ffffff")}" data-empty="${st[key] ? 0 : 1}" aria-label="${label}"/>
        <button type="button" class="pf-x" data-clear-style="${key}" title="Clear ${label.toLowerCase()}" ${st[key] ? "" : "disabled"}>none</button>
        ${!st[key] && eff[key] ? `<span class="text-xs text-slate-500">inherited ${esc(eff[key])}</span>` : ""}
      </div>`;
    const isComp = ["", "Component", "Architecture"].includes(s.effective_applies_to);
    const defaultSelect = (slot, cat) => {
      const choices = all.filter(x => !x.abstract && ["", cat].includes(x.effective_applies_to));
      const cur = s.defaults?.[slot] || "";
      return `<label for="pf-d-${slot}">Default ${slot} stereotype</label>
        <select class="input" id="pf-d-${slot}" data-default="${slot}" data-focus-key="d-${slot}">
          ${option("", "(none)", !cur)}${choices.map(x => option(x.id, x.qualified_name, x.qualified_name === cur)).join("")}</select>`;
    };
    const preview = `<div class="pf-preview" style="background:${esc(eff.fill || "#fff")};border-color:${esc(eff.stroke || "#64748b")};color:${esc(eff.text || colorFor(expandHex(eff.fill)) || "#0f172a")}">
        ${eff.icon && ICONS[eff.icon] ? svg(ICONS[eff.icon]) : ""}<span>«${esc(s.name)}»</span><span style="font-size:11px">Component</span></div>
      <svg class="pf-line-preview" viewBox="0 0 120 10" aria-label="connector line preview"><line x1="2" y1="5" x2="118" y2="5" stroke="${esc(eff.stroke || "#334155")}" stroke-width="2" ${eff.line && DASH[eff.line] ? `stroke-dasharray="${DASH[eff.line]}"` : ""}/></svg>`;
    host.innerHTML = `
      <div class="pf-h"><span class="pf-title">«${esc(s.qualified_name)}»</span>
        <span class="pf-chip">Stereotype</span>${s.abstract ? '<span class="pf-chip">abstract</span>' : ""}
        <span class="pf-chip" title="Elements this stereotype is applied to">applied to ${s.application_count}</span></div>
      <div class="pf-section-title">General</div>
      <div class="pf-form" data-pf="stereotype-form">
        <label for="pf-s-name">Name</label><input class="input" id="pf-s-name" data-field="name" data-focus-key="s-name" value="${esc(s.name)}" autocomplete="off"/>
        <label for="pf-s-desc" class="self-start pt-1">Description</label><textarea class="input h-14" id="pf-s-desc" data-field="description" data-focus-key="s-desc">${esc(s.description)}</textarea>
        <label for="pf-s-applies">Applies to</label>
        <select class="input" id="pf-s-applies" data-field="applies_to" data-focus-key="s-applies">
          ${["", ...META.categories].map(c => option(c, c ? c : (s.base && s.effective_applies_to ? `(inherit: ${s.effective_applies_to})` : "All elements"), c === s.applies_to)).join("")}
        </select>
        <label for="pf-s-base">Base stereotype</label>
        <select class="input" id="pf-s-base" data-field="base" data-focus-key="s-base">
          ${option("", "(none)", !s.base_id)}${baseChoices.map(x => option(x.id, x.qualified_name, x.id === s.base_id)).join("")}
        </select>
        <label for="pf-s-abstract">Abstract</label>
        <div class="pf-inline"><input type="checkbox" id="pf-s-abstract" data-field="abstract" data-focus-key="s-abstract" ${s.abstract ? "checked" : ""}/>
          <span class="text-xs text-slate-500">abstract stereotypes cannot be applied; use them as a base</span></div>
      </div>
      <div class="pf-section-title">Properties</div>
      ${this.propertyTable(s)}
      <div class="mt-2 flex gap-2"><button type="button" class="btn-action" data-pf="add-prop">+ Add property</button></div>
      <div class="pf-msg" data-pf="msg"></div>
      <div class="pf-section-title">Style</div>
      <div class="pf-form">
        ${colorField("fill", "Fill colour")}
        ${colorField("stroke", "Border / line colour")}
        ${colorField("text", "Text colour")}
        <label for="pf-s-icon">Icon</label>
        <select class="input" id="pf-s-icon" data-style="icon" data-focus-key="s-icon">${option("", "(none)", !st.icon)}${META.icons.map(i => option(i, i, i === st.icon)).join("")}</select>
        <label for="pf-s-line">Connector line style</label>
        <select class="input" id="pf-s-line" data-style="line" data-focus-key="s-line">${option("", "(default)", !st.line)}${META.line_styles.map(l => option(l, l, l === st.line)).join("")}</select>
        <label>Preview</label><div class="pf-inline">${preview}</div>
      </div>
      ${isComp ? `<div class="pf-section-title">Default stereotypes for new elements inside</div>
      <div class="pf-form">${defaultSelect("component", "Component")}${defaultSelect("port", "Port")}${defaultSelect("connector", "Connector")}</div>` : ""}`;
    host.querySelector("[data-pf=add-prop]").onclick = () => this.addProperty(s);
    this.bindFields(host.querySelector("[data-pf=stereotype-form]"), async (field, value) => {
      const body = { [field]: field === "base" ? (value || null) : value };
      const out = await this.studio.api("PATCH", `/api/stereotypes/${encodeURIComponent(s.id)}`, body);
      return `«${out.qualified_name}»: ${field === "applies_to" ? "applies to" : field} updated`;
    });
    // style
    const patchStyle = async (key, value) => {
      const style = { ...(s.style || {}) };
      if (value) style[key] = value; else delete style[key];
      await this.save(async () => {
        await this.studio.api("PATCH", `/api/stereotypes/${encodeURIComponent(s.id)}`, { style });
        return `«${s.qualified_name}»: style updated`;
      }, true);
    };
    for (const el of host.querySelectorAll("[data-style]")) el.addEventListener("change", () => patchStyle(el.dataset.style, el.value));
    for (const b of host.querySelectorAll("[data-clear-style]")) b.addEventListener("click", () => patchStyle(b.dataset.clearStyle, ""));
    for (const el of host.querySelectorAll("[data-default]")) {
      el.addEventListener("change", () => this.save(async () => {
        const defaults = {};
        for (const d of host.querySelectorAll("[data-default]")) defaults[d.dataset.default] = d.value || null;
        await this.studio.api("PATCH", `/api/stereotypes/${encodeURIComponent(s.id)}`, { defaults });
        return `«${s.qualified_name}»: default ${el.dataset.default} stereotype updated`;
      }));
    }
    this.bindPropertyTable(host, s);
  }

  propertyTable(s) {
    const groups = s.groups || [];
    const inherited = groups.filter(g => g.id !== s.id && g.properties.length);
    const cols = `<colgroup><col class="c-num"><col class="c-name"><col class="c-type"><col class="c-unit"><col class="c-default">
      <col class="c-min"><col class="c-max"><col class="c-lits"><col class="c-desc"><col class="c-act"></colgroup>`;
    const head = `${cols}<thead><tr><th>#</th><th>Name</th><th>Type</th><th>Unit</th><th>Default</th><th>Min</th><th>Max</th>
      <th title="Enumeration literals, comma separated">Literals</th><th>Description</th><th class="pf-actions-h">Order</th></tr></thead>`;
    const fmt = (v) => v === null || v === undefined ? "" : String(v);
    let body = "";
    for (const g of inherited) {
      body += `<tr class="pf-grouprow"><td colspan="10">Inherited from «${esc(g.stereotype)}»</td></tr>`;
      body += g.properties.map(p => `<tr class="pf-inherited"><td></td><td>${esc(p.name)}</td><td>${esc(p.type)}</td><td>${esc(p.unit)}</td>
        <td>${esc(p.default_display)}</td><td>${esc(fmt(p.min))}</td><td>${esc(fmt(p.max))}</td><td>${esc(p.literals.join(", "))}</td>
        <td>${esc(p.description)}</td><td></td></tr>`).join("");
    }
    if (inherited.length) body += `<tr class="pf-grouprow"><td colspan="10">Own properties of «${esc(s.qualified_name)}»</td></tr>`;
    const n = s.properties.length;
    body += s.properties.map((p, i) => {
      const pending = this.pendingEnum.has(p.id);
      const type = pending ? "enumeration" : p.type;
      const numeric = NUMERIC.has(type);
      const k = (col) => `data-col="${col}" data-focus-key="prop-${esc(p.id)}-${col}"`;
      const dflt = type === "enumeration" && !pending
        ? `<select ${k("default")} aria-label="Default of ${esc(p.name)}">${p.literals.map(l => option(l, l, l === p.default)).join("")}</select>`
        : type === "boolean"
          ? `<select ${k("default")} aria-label="Default of ${esc(p.name)}">${option("false", "false", !p.default)}${option("true", "true", !!p.default)}</select>`
          : `<input ${k("default")} value="${esc(numeric ? (p.default_display || "").replace(new RegExp(`\\s*${escapeRe(p.unit)}$`), "") : fmt(p.default))}" ${pending ? "disabled" : ""} aria-label="Default of ${esc(p.name)}" autocomplete="off"/>`;
      return `<tr data-prop-id="${esc(p.id)}" class="${pending ? "pf-pending" : ""}">
        <td class="pf-num-cell">${i + 1}</td>
        <td><input ${k("name")} value="${esc(p.name)}" aria-label="Property name" autocomplete="off"/></td>
        <td><select ${k("type")} aria-label="Type of ${esc(p.name)}">${(p.type === "any" ? ["any", ...META.types] : META.types).map(t => option(t, t, t === type)).join("")}</select></td>
        <td><input ${k("unit")} value="${esc(p.unit)}" list="pf-units" ${numeric ? "" : "disabled"} aria-label="Unit of ${esc(p.name)}" autocomplete="off"/></td>
        <td>${dflt}</td>
        <td><input ${k("min")} value="${esc(fmt(p.min))}" ${numeric ? "" : "disabled"} aria-label="Minimum of ${esc(p.name)}" autocomplete="off"/></td>
        <td><input ${k("max")} value="${esc(fmt(p.max))}" ${numeric ? "" : "disabled"} aria-label="Maximum of ${esc(p.name)}" autocomplete="off"/></td>
        <td><input ${k("literals")} value="${esc(p.literals.join(", "))}" ${type === "enumeration" ? "" : "disabled"}
                   placeholder="${type === "enumeration" ? "A, B, C" : ""}" aria-label="Literals of ${esc(p.name)}" autocomplete="off"/></td>
        <td><input ${k("description")} value="${esc(p.description)}" aria-label="Description of ${esc(p.name)}" autocomplete="off"/></td>
        <td class="pf-actions">
          <button type="button" class="pf-icon-btn" data-move="-1" title="Move up" aria-label="Move ${esc(p.name)} up" ${i === 0 ? "disabled" : ""}>▲</button>
          <button type="button" class="pf-icon-btn" data-move="1" title="Move down" aria-label="Move ${esc(p.name)} down" ${i === n - 1 ? "disabled" : ""}>▼</button>
          <button type="button" class="pf-icon-btn danger" data-remove-prop title="Delete property" aria-label="Delete ${esc(p.name)}">✕</button>
        </td></tr>`;
    }).join("");
    if (!n && !inherited.length) body += `<tr><td colspan="10" class="text-xs text-slate-400" style="padding:8px">No properties — use <b>Add Property</b>.</td></tr>`;
    const units = `<datalist id="pf-units">${META.units.map(u => `<option value="${esc(u.symbol)}">${esc(u.name)} (${esc(u.quantity)})</option>`).join("")}</datalist>`;
    return `<div class="pf-table-wrap"><table class="pf-table" data-pf="props">${head}<tbody>${body}</tbody></table></div>${units}`;
  }

  bindPropertyTable(host, s) {
    for (const tr of host.querySelectorAll("tr[data-prop-id]")) {
      const pid = tr.dataset.propId;
      const prop = s.properties.find(p => p.id === pid);
      const url = `/api/stereotypes/${encodeURIComponent(s.id)}/properties/${encodeURIComponent(pid)}`;
      const commit = async (input) => {
        const col = input.dataset.col;
        let value = input.value;
        const orig = { name: prop.name, type: prop.type, unit: prop.unit, description: prop.description,
                       min: prop.min ?? "", max: prop.max ?? "", literals: prop.literals.join(", "),
                       default: input.tagName === "SELECT" ? String(prop.default) : input.getAttribute("value") ?? "" }[col];
        if (String(value) === String(orig ?? "") && !(col === "literals" && this.pendingEnum.has(pid))) return;
        let body = { [col]: value };
        if (col === "type" && value === "enumeration" && !prop.literals.length) {
          // An enumeration needs literals: keep the row pending until they are entered.
          this.pendingEnum.set(pid, true);
          this.withFocus(() => this.renderDetails());
          const lit = this.pane.querySelector(`tr[data-prop-id="${CSS.escape(pid)}"] [data-col="literals"]`);
          lit?.focus();
          this.message("Enter the enumeration literals (comma separated) to finish the type change.", "");
          return;
        }
        if (col === "literals") {
          if (!value.trim()) { this.message("An enumeration needs at least one literal.", "err"); return; }
          body = { literals: value.split(",").map(x => x.trim()).filter(Boolean) };
          if (this.pendingEnum.has(pid)) body.type = "enumeration";
        }
        if (col === "default" && prop.type === "boolean") body = { default: value === "true" };
        if ((col === "min" || col === "max" || col === "default") && value === "" && col !== "default") body = { [col]: null };
        if (col === "default" && value === "" ) body = { default: null };
        if (!once(input, JSON.stringify(body))) return;
        await this.save(async () => {
          const out = await this.studio.api("PATCH", url, body);
          this.pendingEnum.delete(pid);
          const extra = out.reset?.length ? `; ${out.reset.length} value(s) reset to the default` :
                        out.converted ? `; ${out.converted} value(s) converted` : "";
          if (out.reset?.length) this.studio.log(`Reset values: ${out.reset.join("; ")}`, "warning");
          return `${out.path}: ${col} updated${extra}`;
        });
      };
      for (const input of tr.querySelectorAll("[data-col]")) {
        input.addEventListener("change", () => commit(input));
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); commit(input); }
          if (e.key === "Escape" && input.tagName === "INPUT") { input.value = input.getAttribute("value") ?? ""; }
        });
      }
      for (const b of tr.querySelectorAll("[data-move]")) {
        b.addEventListener("click", () => this.save(async () => {
          const index = s.properties.indexOf(prop) + Number(b.dataset.move);
          await this.studio.api("PATCH", url, { index });
          return `${prop.path}: moved`;
        }));
      }
      tr.querySelector("[data-remove-prop]").addEventListener("click", () => {
        const doDelete = () => this.save(async () => {
          const out = await this.studio.api("DELETE", url);
          this.pendingEnum.delete(pid);
          return `Deleted ${out.deleted}${out.values_removed ? ` (${out.values_removed} value(s) removed)` : ""}`;
        });
        if (!s.application_count) return doDelete();
        openModal(this.studio, "Delete property", `<p class="text-sm">Delete <b>${esc(prop.path)}</b>?
          Its values on ${s.application_count} stereotyped element(s) are removed.</p>`, doDelete);
      });
    }
  }

  /** Bind data-field inputs: commit on change / Enter, revert on Escape. */
  bindFields(host, patch, isProfile = false) {
    for (const el of host.querySelectorAll("[data-field]")) {
      const commit = () => this.save(async () => {
        const value = el.type === "checkbox" ? el.checked : el.value;
        return patch(el.dataset.field, value);
      }, isProfile);
      el.addEventListener("change", commit);
      if (el.tagName === "INPUT" && el.type === "text" || el.tagName === "INPUT" && !el.type) {
        el.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); el.blur(); el.focus(); }
          if (e.key === "Escape") { el.value = el.getAttribute("value") ?? ""; }
        });
      }
    }
  }

  /** Run an edit, then reload and re-render keeping focus; show the outcome inline and in the log. */
  async save(fn, refreshTree = true) {
    let text;
    try {
      text = await fn();
    } catch (e) {
      await this.refresh();
      this.message(errorText(e), "err");
      return;
    }
    if (refreshTree) await this.studio.refreshTree();   // triggers model-changed -> refresh()
    await this.refresh();
    if (text) { this.studio.log(text, "ok"); this.message(text, "ok"); }
  }
}
