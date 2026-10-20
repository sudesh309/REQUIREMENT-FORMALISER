// Interface Editor: System Composer style interfaces and interface dictionary.
//
//   * "Interfaces" tab: toolstrip, interface list grouped by kind, editable
//     element table (nested interfaces expandable), "ports using this interface".
//   * Inspector sections: port interface assignment (+ connect), connector
//     compatibility with bus element selection, adapter mappings, interface summary.
//   * Toolbar group "Interfaces": Interface Editor, Adapter.
//   * Drag and drop: list rows are drag sources (application/x-sysml-element); an interface
//     dropped on a canvas port (drop-on-element) is assigned to that port.
//
// Backend: webapp/routes/interfaces.py (see docs/features/interfaces.md).

const GROUPS = [
  ["DataInterface", "Data Interfaces", "▦"],
  ["ValueType", "Value Types", "◇"],
  ["PhysicalInterface", "Physical Interfaces", "⚡"],
  ["ServiceInterface", "Service Interfaces", "⇄"],
  ["Enumeration", "Enumerations", "≡"],
  ["Constant", "Constants", "π"],
];
const KIND_LABEL = {
  DataInterface: "Data Interface", ValueType: "Value Type", PhysicalInterface: "Physical Interface",
  ServiceInterface: "Service Interface", Enumeration: "Enumeration", Constant: "Constant",
  PortDefinition: "Port Definition",
};
const WITH_ELEMENTS = new Set(["DataInterface", "PhysicalInterface", "ServiceInterface", "Enumeration"]);
const WITH_COLOR = new Set(["DataInterface", "PhysicalInterface", "ServiceInterface", "ValueType"]);
// Kinds a port can be typed by (engine/interfaces.py INTERFACE_KINDS).
const PORT_TYPES = new Set(["DataInterface", "ValueType", "PhysicalInterface", "ServiceInterface"]);
// Cross-feature drag data type (docs/EXTENDING.md, "Dragging elements").
const ELEMENT_MIME = "application/x-sysml-element";

const STYLES = `
.ifc-pane { background:#fff; }
.ifc-toolstrip { display:flex; flex-wrap:wrap; align-items:stretch; background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:4px 4px 0; }
.ifc-ts-section { display:flex; flex-direction:column; justify-content:space-between; padding:0 6px; border-right:1px solid #e2e8f0; }
.ifc-ts-buttons { display:flex; gap:2px; align-items:flex-start; }
.ifc-ts-btn { display:flex; flex-direction:column; align-items:center; gap:2px; min-width:52px; padding:4px 5px; border-radius:4px; font-size:11px; line-height:1.1; color:#334155; }
.ifc-ts-btn:hover:not(:disabled) { background:#e2e8f0; }
.ifc-ts-btn:focus-visible { outline:2px solid #2563eb; }
.ifc-ts-btn:disabled { opacity:.35; cursor:not-allowed; }
.ifc-ts-icon { font-size:17px; line-height:18px; color:#1d4ed8; }
.ifc-ts-label { font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:#94a3b8; text-align:center; padding:2px 0 3px; }
.ifc-ts-select { font-size:11px; border:1px solid #cbd5e1; border-radius:4px; padding:2px 4px; margin-top:4px; max-width:130px; background:#fff; }
.ifc-body { flex:1; display:flex; min-height:0; }
.ifc-list { width:250px; flex:none; border-right:1px solid #e2e8f0; display:flex; flex-direction:column; min-height:0; background:#fcfcfd; }
.ifc-filter { margin:6px; width:auto !important; font-size:12px !important; padding:.25rem .45rem !important; }
.ifc-groups { flex:1; overflow:auto; outline:none; padding-bottom:8px; }
.ifc-group-title { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#64748b; padding:6px 10px 2px; display:flex; gap:6px; }
.ifc-item { display:flex; align-items:center; gap:6px; padding:3px 10px 3px 14px; cursor:pointer; font-size:13px; white-space:nowrap; }
.ifc-item:hover { background:#f1f5f9; }
.ifc-item.sel { background:#dbeafe; color:#1d4ed8; }
.ifc-groups:focus .ifc-item.sel { box-shadow: inset 2px 0 0 #2563eb; }
.ifc-item .ifc-count { margin-left:auto; color:#94a3b8; font-size:11px; }
.ifc-swatch { width:11px; height:11px; border-radius:2px; border:1px solid rgba(0,0,0,.25); flex:none; }
.ifc-main { flex:1; min-width:0; display:flex; flex-direction:column; }
.ifc-head { display:flex; align-items:center; gap:8px; padding:8px 10px 4px; }
.ifc-kind-badge { font-size:11px; padding:1px 6px; border-radius:9999px; background:#eef2ff; color:#3730a3; white-space:nowrap; }
.ifc-name { max-width:280px; font-weight:600; }
.ifc-qname { font-size:11px; color:#94a3b8; font-family:ui-monospace,monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ifc-color input { width:28px; height:24px; padding:0; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; }
.ifc-desc { margin:0 10px 6px; width:calc(100% - 20px) !important; font-size:12px !important; resize:vertical; }
.ifc-owned-banner { margin:0 10px 6px; padding:4px 8px; font-size:12px; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; display:flex; align-items:center; gap:8px; }
.ifc-empty { padding:24px; color:#64748b; font-style:italic; font-size:13px; }
.ifc-table-wrap { flex:1; overflow:auto; border-top:1px solid #e2e8f0; min-height:80px; }
.ifc-table { border-collapse:collapse; width:100%; font-size:12px; }
.ifc-table th { position:sticky; top:0; z-index:1; background:#f1f5f9; text-align:left; font-weight:600; color:#475569; padding:4px 6px; border-bottom:1px solid #cbd5e1; border-right:1px solid #e2e8f0; white-space:nowrap; }
.ifc-table td { border-bottom:1px solid #eef2f7; border-right:1px solid #f1f5f9; padding:0; vertical-align:middle; }
.ifc-table td input, .ifc-table td select { width:100%; min-width:48px; border:1px solid transparent; background:transparent; padding:3px 5px; font-size:12px; border-radius:2px; }
.ifc-table td input[type=checkbox] { width:auto; min-width:0; margin:0 8px; }
.ifc-table td input:hover:not(:disabled), .ifc-table td select:hover:not(:disabled) { border-color:#e2e8f0; }
.ifc-table td input:focus, .ifc-table td select:focus { outline:none; border-color:#2563eb; background:#fff; }
.ifc-table td :disabled { color:#94a3b8; }
.ifc-table tr.sel > td { background:#eff6ff; }
.ifc-table tr.ifc-nested > td { background:#fafafa; }
.ifc-table tr.ifc-nested input, .ifc-table tr.ifc-nested select { font-style:italic; }
.ifc-table .ifc-namecell { display:flex; align-items:center; }
.ifc-twisty { width:16px; flex:none; text-align:center; color:#64748b; cursor:pointer; user-select:none; }
.ifc-twisty.empty { cursor:default; }
.ifc-warn { border-color:#f59e0b !important; background:#fffbeb !important; }
.ifc-err { border-color:#dc2626 !important; background:#fef2f2 !important; }
.ifc-usage { border-top:1px solid #e2e8f0; padding:6px 10px; font-size:12px; max-height:150px; overflow:auto; background:#fcfcfd; }
.ifc-usage-head { font-weight:600; color:#475569; display:flex; align-items:center; gap:8px; margin-bottom:2px; }
.ifc-link { color:#1d4ed8; text-decoration:none; font-family:ui-monospace,monospace; }
.ifc-link:hover { text-decoration:underline; }
.ifc-ok { color:#15803d; font-weight:600; }
.ifc-bad { color:#b91c1c; font-weight:600; }
.ifc-reasons { margin:2px 0 0 14px; list-style:disc; color:#7f1d1d; font-size:12px; }
.ifc-mini th, .ifc-mini td { padding:2px 6px; }
.ifc-insp-row { display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:13px; }
.ifc-insp-row > label { width:92px; flex:none; color:#475569; }
`;

export default function install(studio) {
  // studio.api logs HTTP errors to the Output pane; tag them so run() does not log twice.
  const api = async (...args) => {
    try { return await studio.api(...args); }
    catch (e) { e.fromApi = true; throw e; }
  };
  const esc = (v) => studio.escapeHtml(String(v ?? ""));
  const S = {
    listing: null, meta: null, currentId: null, detail: null, sel: null,
    expanded: new Set(), nested: new Map(), filter: "", visible: false, busy: false,
  };
  let pane, listEl, headerEl, tableWrap, usageEl;

  const style = document.createElement("style");
  style.dataset.plugin = "interfaces";
  style.textContent = STYLES;
  document.head.appendChild(style);

  // ------------------------------------------------------------------ helpers
  // Every UI-triggered operation runs through run(): errors are reported once, and the
  // number of operations in flight is published as <body data-ifc-pending> (tests wait on it).
  let pending = 0;
  const mark = (delta) => { pending += delta; document.body.dataset.ifcPending = String(pending); };
  const run = (fn) => async (...args) => {
    mark(1);
    try { return await fn(...args); }
    catch (e) {
      if (!e?.fromApi) { console.error(e); studio.log(`Interfaces: ${e}`, "error"); }
      return undefined;
    } finally { mark(-1); }
  };
  const allItems = () => [...(S.listing?.items || []), ...(S.listing?.owned || [])];
  const itemsOf = (kind) => (S.listing?.items || []).filter((i) => i.kind === kind);
  const fmtNum = (v) => (v === null || v === undefined ? "" : String(v));
  const option = (value, label, selected) =>
    `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label ?? value)}</option>`;

  function openModal(title, html, onSubmit) {
    studio.modal(esc(title), html, onSubmit);
    const root = document.getElementById("modal-root");
    const form = root.querySelector("#modal-form");
    const submit = () => root.querySelector("[data-modal-submit]")?.click();
    form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") { e.preventDefault(); submit(); }
    });
    root.querySelector(".modal")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); root.querySelector("[data-modal-cancel]")?.click(); }
    });
    setTimeout(() => form.querySelector("input:not([type=hidden]), select, textarea")?.focus(), 0);
    return root;
  }

  async function refreshTreeQuietly() {
    S.busy = true;
    try { await studio.refreshTree(); } finally { S.busy = false; }
  }

  function goTo(id) {
    studio.emit("navigate", { id });
    setTimeout(() => { if (studio.state.tab === "interfaces") studio.switchTab("properties"); }, 0);
  }

  function typeOptions(current, selfId) {
    const prim = (S.meta?.primitive_types || []).map((t) => option(t, t, t === current)).join("");
    const vts = itemsOf("ValueType").map((i) => `ValueType: ${i.name}`);
    const buses = itemsOf("DataInterface").filter((i) => i.id !== selfId).map((i) => `Bus: ${i.name}`);
    const enums = itemsOf("Enumeration").map((i) => `Enum: ${i.name}`);
    const known = new Set([...(S.meta?.primitive_types || []), ...vts, ...buses, ...enums]);
    const extra = current && !known.has(current) ? option(current, current, true) : "";
    const grp = (label, vals) => vals.length
      ? `<optgroup label="${label}">${vals.map((v) => option(v, v, v === current)).join("")}</optgroup>` : "";
    return `${extra}<optgroup label="Built-in">${prim}</optgroup>${grp("Value types", vts)}` +
           `${grp("Interfaces (nested)", buses)}${grp("Enumerations", enums)}`;
  }

  const primOptions = (current) => {
    const vts = itemsOf("ValueType").map((i) => `ValueType: ${i.name}`);
    const vals = [...(S.meta?.primitive_types || []), ...vts];
    if (current && !vals.includes(current)) vals.unshift(current);
    return vals.map((v) => option(v, v, v === current)).join("");
  };

  // ------------------------------------------------------------------ the tab
  studio.registerTab({
    id: "interfaces", title: "Interfaces", order: 20,
    mount(p) { pane = p; buildShell(); },
    onShow() { S.visible = true; run(reload)(); },
  });
  studio.on("tab-shown", (id) => { S.visible = id === "interfaces"; });
  studio.on("model-changed", () => {
    if (S.visible && !S.busy) run(reload)({ keepTable: tableHasFocus() });
  });
  studio.on("select", (el) => {
    if (!S.visible || !el) return;
    if (el.interface_category === "InterfaceElement") openItem(el.owner_id, el.id);
    else if (el.interface_category && (el.interface_kind || el.kind)) openItem(el.id);
  });

  function buildShell() {
    pane.classList.add("ifc-pane");
    const btn = (act, icon, label, title) =>
      `<button type="button" class="ifc-ts-btn" data-ifc-act="${act}" title="${esc(title)}">` +
      `<span class="ifc-ts-icon" aria-hidden="true">${icon}</span><span>${esc(label)}</span></button>`;
    const section = (label, inner) =>
      `<div class="ifc-ts-section"><div class="ifc-ts-buttons">${inner}</div><div class="ifc-ts-label">${label}</div></div>`;
    pane.innerHTML = `
      <div class="ifc-toolstrip" role="toolbar" aria-label="Interface Editor">
        ${section("New", btn("new-data", "▦", "Data Interface", "New data interface") +
                         btn("new-vt", "◇", "Value Type", "New value type") +
                         btn("new-phys", "⚡", "Physical", "New physical interface") +
                         btn("new-svc", "⇄", "Service", "New service interface") +
                         btn("new-enum", "≡", "Enumeration", "New enumeration") +
                         btn("new-const", "π", "Constant", "New named constant") +
                         `<select class="ifc-ts-select" data-ifc="template" title="New interface from an avionics bus template"><option value="">Template…</option></select>`)}
        ${section("Dictionary", btn("import", "⤓", "Import", "Import an interface dictionary (JSON)") +
                                btn("export", "⤒", "Export", "Export the interface dictionary (JSON)") +
                                btn("move-owned", "⇪", "Save Owned", "Move every port-owned interface into the dictionary"))}
        ${section("Element", btn("add-element", "＋", "Add", "Add element (Insert)") +
                             btn("del-element", "−", "Remove", "Delete the selected element") +
                             btn("up", "↑", "Up", "Move element up (Alt+↑)") +
                             btn("down", "↓", "Down", "Move element down (Alt+↓)"))}
        ${section("Edit", btn("delete", "✕", "Delete", "Delete the selected interface"))}
      </div>
      <div class="ifc-body">
        <aside class="ifc-list">
          <input class="input ifc-filter" data-ifc="filter" placeholder="Filter interfaces…" aria-label="Filter interfaces" />
          <div class="ifc-groups" data-ifc="list" tabindex="0" aria-label="Interfaces"></div>
        </aside>
        <section class="ifc-main">
          <div data-ifc="header"></div>
          <div class="ifc-table-wrap" data-ifc="table"></div>
          <div class="ifc-usage" data-ifc="usage"></div>
        </section>
      </div>
      <datalist id="ifc-units"></datalist>`;
    listEl = pane.querySelector('[data-ifc="list"]');
    headerEl = pane.querySelector('[data-ifc="header"]');
    tableWrap = pane.querySelector('[data-ifc="table"]');
    usageEl = pane.querySelector('[data-ifc="usage"]');

    pane.addEventListener("click", (e) => {
      const actBtn = e.target.closest("[data-ifc-act]");
      if (actBtn && !actBtn.disabled) { e.preventDefault(); run(action)(actBtn.dataset.ifcAct); return; }
      const nav = e.target.closest("[data-nav]");
      if (nav) { e.preventDefault(); goTo(nav.dataset.nav); return; }
      const item = e.target.closest(".ifc-item");
      if (item) { openItem(item.dataset.id); return; }
      const tw = e.target.closest("[data-toggle]");
      if (tw) {
        const key = tw.dataset.toggle;
        S.expanded.has(key) ? S.expanded.delete(key) : S.expanded.add(key);
        run(renderTable)();
        return;
      }
      const tr = e.target.closest("tr[data-id]");
      if (tr && tableWrap.contains(tr) && !tr.classList.contains("ifc-nested")) setSel(tr.dataset.id);
    });
    pane.querySelector('[data-ifc="filter"]').addEventListener("input", (e) => {
      S.filter = e.target.value.trim().toLowerCase(); renderList();
    });
    pane.querySelector('[data-ifc="template"]').addEventListener("change", (e) => {
      const t = e.target.value; e.target.value = "";
      if (t) run(createItem)(null, { template: t });
    });
    headerEl.addEventListener("change", (e) => {
      const f = e.target.dataset.ifc;
      if (f === "name" || f === "color" || f === "description" || f === "default")
        run(patchItem)({ [f]: e.target.value });
    });
    headerEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.dataset.ifc === "name") { e.preventDefault(); e.target.blur(); }
      if (e.key === "Escape" && e.target.dataset.ifc === "name") { e.target.value = S.detail?.name || ""; e.target.blur(); }
    });
    tableWrap.addEventListener("change", (e) => run(onCellChange)(e.target));
    tableWrap.addEventListener("focusin", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr && !tr.classList.contains("ifc-nested")) setSel(tr.dataset.id);
      if (e.target.dataset.field) e.target.dataset.orig = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    });
    tableWrap.addEventListener("keydown", onTableKey);
    listEl.addEventListener("keydown", onListKey);
    listEl.addEventListener("dragstart", (e) => {
      const item = e.target.closest?.('.ifc-item[draggable="true"]');
      if (!item || !e.dataTransfer) return;
      const it = allItems().find((i) => i.id === item.dataset.id);
      e.dataTransfer.setData(ELEMENT_MIME, item.dataset.id);
      e.dataTransfer.setData("text/plain", it?.qualified_name || item.dataset.id);
      e.dataTransfer.effectAllowed = "copyLink";
    });
    pane.addEventListener("keydown", (e) => {
      const inField = e.target.closest("input, select, textarea");
      if (e.key === "Insert" && !inField) { e.preventDefault(); run(action)("add-element"); }
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && S.sel) {
        e.preventDefault(); run(action)(e.key === "ArrowUp" ? "up" : "down");
      }
    });
  }

  function tableHasFocus() {
    return !!(tableWrap && tableWrap.contains(document.activeElement) && document.activeElement !== tableWrap);
  }

  async function reload({ keepTable = false } = {}) {
    if (!pane) return;
    const data = await api("GET", "/api/interfaces");
    S.listing = data; S.meta = data.meta;
    const tpl = pane.querySelector('[data-ifc="template"]');
    if (tpl && tpl.options.length === 1)
      tpl.insertAdjacentHTML("beforeend", data.meta.templates.map((t) => option(t.id, t.label)).join(""));
    const dl = pane.querySelector("#ifc-units");
    if (dl && !dl.children.length) dl.innerHTML = data.meta.units.map((u) => `<option value="${esc(u)}"></option>`).join("");
    const all = allItems();
    if (S.currentId && !all.some((i) => i.id === S.currentId)) { S.currentId = null; S.detail = null; }
    if (!S.currentId && all.length) S.currentId = all[0].id;
    renderList();
    if (!S.currentId) { S.detail = null; renderDetail(); }
    else if (!keepTable || !S.detail || S.detail.id !== S.currentId) await loadDetail(S.currentId);
    updateToolstrip();
  }

  async function loadDetail(id) {
    S.detail = await api("GET", `/api/interfaces/item/${encodeURIComponent(id)}`);
    S.nested.clear();
    await renderDetail();
  }

  function openItem(id, elementId = null) {
    if (!id) return;
    if (S.currentId !== id) { S.expanded.clear(); }
    S.currentId = id; S.sel = elementId;
    if (S.visible) run(reload)();
  }

  function setSel(id) {
    if (S.sel === id) return;
    S.sel = id;
    tableWrap.querySelectorAll("tr.sel").forEach((r) => r.classList.remove("sel"));
    tableWrap.querySelector(`tr[data-key="${CSS.escape(id)}"]`)?.classList.add("sel");
    updateToolstrip();
  }

  // ------------------------------------------------------------------ list
  function renderList() {
    if (!listEl) return;
    const f = S.filter;
    const match = (i) => !f || i.name.toLowerCase().includes(f);
    // Shared interfaces and value types can be dragged onto a port on the Architecture canvas.
    const row = (i, label) =>
      `<div class="ifc-item${i.id === S.currentId ? " sel" : ""}" data-id="${esc(i.id)}"` +
      (PORT_TYPES.has(i.kind) && !i.owned
        ? ` draggable="true" title="${esc(i.qualified_name)}\nDrag onto a port on the Architecture canvas to assign it (hold over the Architecture tab to switch)">`
        : ` title="${esc(i.qualified_name)}">`) +
      `<span class="ifc-swatch" style="background:${esc(i.color || "transparent")}"></span>` +
      `<span class="truncate">${esc(label ?? i.name)}</span>` +
      (WITH_ELEMENTS.has(i.kind) ? `<span class="ifc-count">${i.element_count}</span>` : "") + `</div>`;
    let html = "";
    for (const [kind, title, icon] of GROUPS) {
      const items = itemsOf(kind).filter(match);
      if (!items.length) continue;
      html += `<div class="ifc-group-title"><span aria-hidden="true">${icon}</span>${title}</div>` + items.map((i) => row(i)).join("");
    }
    const owned = (S.listing?.owned || []).filter(match);
    if (owned.length) {
      html += `<div class="ifc-group-title"><span aria-hidden="true">⊙</span>Port-owned interfaces</div>` +
        owned.map((i) => row(i, `${i.owner_port.qualified_name.split("::").slice(-2).join(".")} (owned)`)).join("");
    }
    if (!html) {
      html = `<div class="ifc-empty">${f ? "No match." : "The interface dictionary is empty. Create a data interface or value type with the toolstrip."}</div>`;
    }
    listEl.innerHTML = html;
  }

  function onListKey(e) {
    const ids = [...listEl.querySelectorAll(".ifc-item")].map((n) => n.dataset.id);
    const i = ids.indexOf(S.currentId);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = ids[Math.max(0, Math.min(ids.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (next) openItem(next);
    } else if (e.key === "F2") {
      e.preventDefault(); focusName();
    } else if (e.key === "Delete") {
      e.preventDefault(); e.stopPropagation(); run(action)("delete");
    }
  }

  function updateToolstrip() {
    if (!pane) return;
    const d = S.detail;
    const hasEl = d && WITH_ELEMENTS.has(d.kind);
    const selOk = hasEl && S.sel && d.elements?.some((x) => x.id === S.sel);
    const set = (act, on) => { const b = pane.querySelector(`[data-ifc-act="${act}"]`); if (b) b.disabled = !on; };
    set("add-element", hasEl); set("del-element", selOk); set("up", selOk); set("down", selOk);
    set("delete", !!d); set("move-owned", (S.listing?.owned || []).length > 0);
  }

  // ------------------------------------------------------------------ detail
  async function renderDetail() {
    renderHeader();
    await renderTable();
    renderUsage();
    updateToolstrip();
  }

  function focusName() {
    const n = headerEl.querySelector('[data-ifc="name"]');
    if (n) { n.focus(); n.select(); }
  }

  function renderHeader() {
    const d = S.detail;
    if (!d) {
      headerEl.innerHTML = `<div class="ifc-empty">No interface selected. Use <b>New</b> in the toolstrip to create a data interface, value type, physical or service interface.</div>`;
      return;
    }
    const color = WITH_COLOR.has(d.kind)
      ? `<label class="ifc-color" title="Interface colour (used for ports and connectors)"><input type="color" data-ifc="color" value="${esc(d.color || "#64748b")}" aria-label="Interface colour" /></label>` : "";
    const enumDefault = d.kind === "Enumeration"
      ? `<label class="text-xs text-slate-600 flex items-center gap-1">Default <select class="input" style="width:auto" data-ifc="default">${option("", "(none)", !d.default)}${(d.elements || []).map((l) => option(l.name, l.name, l.name === d.default)).join("")}</select></label>` : "";
    headerEl.innerHTML = `
      <div class="ifc-head">
        <span class="ifc-kind-badge">${esc(KIND_LABEL[d.kind] || d.kind)}${d.owned ? " · owned" : ""}</span>
        <input class="input ifc-name" data-ifc="name" value="${esc(d.name)}" aria-label="Interface name" />
        ${color}${enumDefault}
        <span class="ifc-qname" title="${esc(d.qualified_name)}">${esc(d.qualified_name)}</span>
      </div>
      ${d.owned ? `<div class="ifc-owned-banner">Owned by port <a href="#" class="ifc-link" data-nav="${esc(d.owner_port.id)}">${esc(d.owner_port.qualified_name)}</a><span class="flex-1"></span><button type="button" class="btn-action" data-ifc-act="make-shared">Convert to shared…</button></div>` : ""}
      <textarea class="input ifc-desc" data-ifc="description" rows="1" placeholder="Description" aria-label="Description">${esc(d.description)}</textarea>`;
  }

  async function collectNested(elements, prefix, depth) {
    for (const el of elements || []) {
      const path = prefix + el.name;
      if (el.type_kind === "interface" && el.type_id && S.expanded.has(path) && depth < 5) {
        if (!S.nested.has(el.type_id))
          S.nested.set(el.type_id, await api("GET", `/api/interfaces/item/${encodeURIComponent(el.type_id)}`));
        await collectNested(S.nested.get(el.type_id).elements, path + ".", depth + 1);
      }
    }
  }

  function captureFocus() {
    const a = document.activeElement;
    if (!a || !tableWrap.contains(a) || !a.dataset.field) return null;
    return { key: a.closest("tr")?.dataset.key, field: a.dataset.field };
  }

  function restoreFocus(f) {
    if (!f) return;
    const tr = tableWrap.querySelector(`tr[data-key="${CSS.escape(f.key || "")}"]`);
    const el = tr?.querySelector(`[data-field="${f.field}"]`);
    if (el && !el.disabled) { el.focus(); if (el.tagName === "INPUT" && el.type !== "checkbox") el.select(); }
  }

  async function renderTable() {
    const d = S.detail;
    if (!d) { tableWrap.innerHTML = ""; return; }
    if (d.kind === "DataInterface" || d.kind === "PortDefinition") await collectNested(d.elements, "", 0);
    const focus = captureFocus();
    let head = [], rows = "";
    if (d.kind === "DataInterface" || d.kind === "PortDefinition") {
      head = ["Name", "Type", "Dimensions", "Units", "Complexity", "Minimum", "Maximum", "Description"];
      rows = dataRows(d.elements, "", 0, true, d.id);
    } else if (d.kind === "PhysicalInterface") {
      head = ["Name", "Domain", "Description"];
      rows = d.elements.map((el) => `<tr data-id="${esc(el.id)}" data-key="${esc(el.id)}"${el.id === S.sel ? ' class="sel"' : ""}>
        <td><div class="ifc-namecell"><span class="ifc-twisty empty"></span>${inp("name", el.name)}</div></td>
        <td><select data-field="domain" aria-label="Domain">${S.meta.physical_domains.map((x) => option(x.id, x.label, x.id === el.domain)).join("")}</select></td>
        <td>${inp("description", el.description)}</td></tr>`).join("");
    } else if (d.kind === "ServiceInterface") {
      head = ["Name", "Function prototype", "Asynchronous", "Description"];
      rows = d.elements.map((el) => serviceRows(el)).join("");
    } else if (d.kind === "Enumeration") {
      head = ["Literal", "Value", "Description"];
      rows = d.elements.map((el) => `<tr data-id="${esc(el.id)}" data-key="${esc(el.id)}"${el.id === S.sel ? ' class="sel"' : ""}>
        <td><div class="ifc-namecell"><span class="ifc-twisty empty"></span>${inp("name", el.name)}</div></td>
        <td>${inp("value", fmtNum(el.value))}</td><td>${inp("description", el.description)}</td></tr>`).join("");
    } else if (d.kind === "ValueType") {
      head = ["Base type", "Dimensions", "Units", "Complexity", "Minimum", "Maximum"];
      rows = `<tr data-id="${esc(d.id)}" data-key="item" data-item="1">
        <td><select data-field="base_type" aria-label="Base type">${(S.meta.primitive_types || []).map((t) => option(t, t, t === d.base_type)).join("")}</select></td>
        <td>${inp("dimensions", d.dimensions)}</td>
        <td>${inp("units", d.units, { list: "ifc-units", warn: d.units_warning })}</td>
        <td>${complexitySelect(d.complexity)}</td>
        <td>${inp("minimum", fmtNum(d.minimum))}</td><td>${inp("maximum", fmtNum(d.maximum))}</td></tr>`;
    } else if (d.kind === "Constant") {
      head = ["Value", "Type", "Units"];
      rows = `<tr data-id="${esc(d.id)}" data-key="item" data-item="1">
        <td>${inp("value", d.value)}</td>
        <td><select data-field="type" aria-label="Type">${(S.meta.primitive_types || []).map((t) => option(t, t, t === d.type)).join("")}</select></td>
        <td>${inp("units", d.units, { list: "ifc-units" })}</td></tr>`;
    }
    const empty = WITH_ELEMENTS.has(d.kind) && !d.elements.length
      ? `<div class="ifc-empty">No elements yet. Click <b>Add</b> in the toolstrip (or press Insert).</div>` : "";
    const WIDTH = { Name: "16%", Literal: "22%", Type: "18%", Dimensions: "9%", Units: "9%", Complexity: "9%",
                    Minimum: "8%", Maximum: "8%", Domain: "30%", "Function prototype": "34%", Asynchronous: "10%",
                    Value: "20%", "Base type": "18%" };
    tableWrap.innerHTML = `<table class="ifc-table" id="ifc-table"><thead><tr>${head.map((h) =>
      `<th${WIDTH[h] ? ` style="width:${WIDTH[h]}"` : ""}>${h}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>${empty}`;
    restoreFocus(focus);
  }

  function inp(field, value, { disabled = false, list = "", warn = "", label = "" } = {}) {
    return `<input type="text" data-field="${field}" value="${esc(value)}" aria-label="${esc(label || field)}"` +
      `${disabled ? " disabled" : ""}${list ? ` list="${list}"` : ""}${warn ? ` class="ifc-warn" title="${esc(warn)}"` : ""} />`;
  }

  function complexitySelect(current, disabled = false) {
    return `<select data-field="complexity" aria-label="Complexity"${disabled ? " disabled" : ""}>` +
      (S.meta?.complexities || ["real", "complex", "auto"]).map((c) => option(c, c, c === current)).join("") + `</select>`;
  }

  function dataRows(elements, prefix, depth, editable, selfId) {
    let out = "";
    for (const el of elements || []) {
      const path = prefix + el.name;
      const nested = el.type_kind === "interface";
      const vt = el.type_kind === "value_type";
      const open = nested && S.expanded.has(path);
      const eff = el.effective || {};
      const lock = !editable || nested || vt;
      const tw = nested
        ? `<span class="ifc-twisty" data-toggle="${esc(path)}" title="${open ? "Collapse" : "Expand"} nested interface">${open ? "▾" : "▸"}</span>`
        : `<span class="ifc-twisty empty"></span>`;
      const cls = [editable ? "" : "ifc-nested", editable && el.id === S.sel ? "sel" : ""].filter(Boolean).join(" ");
      const lockedTitle = vt ? ` title="Inherited from ${esc(el.type)}"` : "";
      out += `<tr data-id="${esc(el.id)}" data-key="${esc(editable ? el.id : "n:" + path)}" data-name="${esc(el.name)}"${cls ? ` class="${cls}"` : ""}>
        <td><div class="ifc-namecell" style="padding-left:${depth * 14}px">${tw}${inp("name", el.name, { disabled: !editable })}</div></td>
        <td>${editable ? `<select data-field="type" aria-label="Type">${typeOptions(el.type, selfId)}</select>` : inp("type", el.type, { disabled: true })}</td>
        <td${lockedTitle}>${inp("dimensions", nested ? "" : (vt ? eff.dimensions : el.dimensions), { disabled: lock })}</td>
        <td${lockedTitle}>${inp("units", nested ? "" : eff.units, { disabled: lock, list: "ifc-units", warn: lock ? "" : el.units_warning })}</td>
        <td${lockedTitle}>${nested ? inp("complexity", "", { disabled: true }) : complexitySelect(eff.complexity || el.complexity, lock)}</td>
        <td${lockedTitle}>${inp("minimum", nested ? "" : fmtNum(eff.minimum), { disabled: lock })}</td>
        <td${lockedTitle}>${inp("maximum", nested ? "" : fmtNum(eff.maximum), { disabled: lock })}</td>
        <td>${inp("description", el.description, { disabled: !editable })}</td></tr>`;
      if (open && S.nested.has(el.type_id)) out += dataRows(S.nested.get(el.type_id).elements, path + ".", depth + 1, false, selfId);
    }
    return out;
  }

  function serviceRows(el) {
    const key = `fn:${el.id}`;
    const open = S.expanded.has(key);
    let out = `<tr data-id="${esc(el.id)}" data-key="${esc(el.id)}"${el.id === S.sel ? ' class="sel"' : ""}>
      <td><div class="ifc-namecell"><span class="ifc-twisty" data-toggle="${esc(key)}" title="Arguments">${open ? "▾" : "▸"}</span>${inp("name", el.name)}</div></td>
      <td>${inp("prototype", el.prototype)}</td>
      <td><input type="checkbox" data-field="asynchronous" aria-label="Asynchronous"${el.asynchronous ? " checked" : ""} /></td>
      <td>${inp("description", el.description)}</td></tr>`;
    if (open) {
      out += `<tr class="ifc-nested"><td colspan="4" style="padding:2px 8px 6px 36px">
        <table class="ifc-table"><thead><tr><th>Argument</th><th>Direction</th><th>Type</th><th>Dimensions</th><th>Units</th><th>Description</th></tr></thead><tbody>
        ${el.arguments.map((a) => `<tr data-id="${esc(el.id)}" data-arg="${esc(a.name)}" data-key="${esc(el.id + ":" + a.name)}">
          <td>${inp("argname", a.name, { disabled: true })}</td><td>${inp("direction", a.direction, { disabled: true })}</td>
          <td><select data-field="type" aria-label="Argument type">${primOptions(a.type)}</select></td>
          <td>${inp("dimensions", a.dimensions)}</td><td>${inp("units", a.units, { list: "ifc-units" })}</td>
          <td>${inp("description", a.description)}</td></tr>`).join("")}
        </tbody></table></td></tr>`;
    }
    return out;
  }

  function renderUsage() {
    const d = S.detail;
    if (!d) { usageEl.innerHTML = ""; return; }
    if (d.kind === "Enumeration" || d.kind === "Constant") {
      const users = d.used_by || [];
      usageEl.innerHTML = `<div class="ifc-usage-head">Used by (${users.length})</div>` + (users.length
        ? users.map((u) => `<div><a href="#" class="ifc-link" data-nav="${esc(u.id)}">${esc(u.qualified_name)}</a></div>`).join("")
        : `<div class="text-slate-400 italic">Not used as an element type.</div>`);
      return;
    }
    const ports = d.ports || [];
    const users = d.used_by || [];
    usageEl.innerHTML = `
      <div class="ifc-usage-head">Ports using this interface (${ports.length})
        ${ports.length ? `<button type="button" class="btn-action" data-ifc-act="highlight" title="Highlight these ports on the canvas">Highlight</button>` : ""}</div>
      <div data-ifc="ports">${ports.length
        ? ports.map((p) => `<div><a href="#" class="ifc-link" data-nav="${esc(p.id)}">${esc(p.qualified_name)}</a> <span class="text-slate-400">${esc(p.direction)}</span></div>`).join("")
        : `<div class="text-slate-400 italic">No port uses this interface yet. Drag it from the list onto a port on the Architecture canvas, or select a port and pick it in Properties › Interface.</div>`}</div>
      ${users.length ? `<div class="ifc-usage-head mt-1">Nested in (${users.length})</div>` +
        users.map((u) => `<div><a href="#" class="ifc-link" data-nav="${esc(u.id)}">${esc(u.qualified_name)}</a></div>`).join("") : ""}`;
  }

  // ------------------------------------------------------------------ table editing
  function onTableKey(e) {
    const t = e.target;
    if (!t.dataset?.field) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (t.dataset.orig !== undefined) { if (t.type === "checkbox") t.checked = t.dataset.orig === "true"; else t.value = t.dataset.orig; }
      t.blur();
    } else if (e.key === "Enter" && t.tagName === "INPUT") {
      e.preventDefault();
      // Spreadsheet-like: commit and move to the same column in the next editable row.
      const rows = [...tableWrap.querySelectorAll("tbody tr[data-key]")];
      const idx = rows.indexOf(t.closest("tr"));
      const next = rows.slice(idx + 1).map((r) => r.querySelector(`[data-field="${t.dataset.field}"]:not(:disabled)`)).find(Boolean);
      if (next) next.focus(); else t.blur();
    }
  }

  async function onCellChange(t) {
    const field = t.dataset.field;
    const tr = t.closest("tr");
    if (!field || !tr || tr.classList.contains("ifc-nested") && !tr.dataset.arg) return;
    const value = t.type === "checkbox" ? t.checked : t.value;
    if (tr.dataset.item) return patchItem({ [field]: value });
    const d = S.detail;
    const el = d.elements.find((x) => x.id === tr.dataset.id);
    if (!el) return;
    if (tr.dataset.arg) {
      const args = el.arguments.map((a) => (a.name === tr.dataset.arg ? { ...a, [field]: value } : a));
      return patchElement(el, { arguments: args }, field);
    }
    return patchElement(el, { [field]: value }, field);
  }

  async function patchElement(el, fields, field) {
    const d = S.detail;
    // Naming a just-added element joins its creation's undo step.
    const created = S.created === el.id && "name" in fields ? el.id : null;
    S.created = null;
    try {
      const r = await api("PATCH", `/api/interfaces/item/${encodeURIComponent(d.id)}/elements/${encodeURIComponent(el.id)}`, fields,
                          { undoMerge: created });
      S.detail = r.interface;
      for (const w of r.warnings || []) studio.log(`${d.name}.${r.element.name}: ${w}`, "warning");
      S.nested.clear();
      await renderTable();
      syncAround();
      if ("name" in fields || "type" in fields) { await refreshTreeQuietly(); await reload({ keepTable: true }); }
    } catch (e) {
      await renderTable();
      const cell = tableWrap.querySelector(`tr[data-key="${CSS.escape(el.id)}"] [data-field="${field}"]`);
      if (cell) { cell.classList.add("ifc-err"); cell.title = e.message; }
    }
  }

  // Header (enumeration default literal) and usage pane follow element edits.
  function syncAround() {
    if (S.detail?.kind === "Enumeration") renderHeader();
    renderUsage();
    updateToolstrip();
  }

  async function patchItem(fields) {
    const d = S.detail;
    if (!d) return;
    const created = S.created === d.id && "name" in fields ? d.id : null;
    S.created = null;
    try {
      const r = await api("PATCH", `/api/interfaces/item/${encodeURIComponent(d.id)}`, fields, { undoMerge: created });
      for (const w of r.warnings || []) studio.log(`${r.name}: ${w}`, "warning");
      S.detail = r;
      if ("name" in fields) studio.log(`Renamed ${d.name} → ${r.name}`, "ok");
      if ("name" in fields || "color" in fields || "default" in fields) {
        await refreshTreeQuietly();
        await reload({ keepTable: false });
      } else {
        await renderDetail();
      }
    } catch (e) {
      await renderDetail();
    }
  }

  // ------------------------------------------------------------------ actions
  async function action(name) {
    const d = S.detail;
    const kinds = { "new-data": "DataInterface", "new-vt": "ValueType", "new-phys": "PhysicalInterface",
                    "new-svc": "ServiceInterface", "new-enum": "Enumeration", "new-const": "Constant" };
    if (kinds[name]) return createItem(kinds[name]);
    switch (name) {
      case "import": return importDictionary();
      case "export": {
        const r = await api("GET", "/api/interfaces/dictionary/export");
        studio.download(r.filename, r.text);
        studio.log(`Exported ${r.document.items.length} dictionary item(s) to ${r.filename}`, "ok");
        return;
      }
      case "move-owned": {
        const r = await api("POST", "/api/interfaces/move-owned", { on_conflict: "rename" });
        for (const m of r.moved) studio.log(`Saved ${m.port} interface to the dictionary as ${m.interface}`, "ok");
        await refreshTreeQuietly(); return reload();
      }
      case "add-element": {
        if (!d || !WITH_ELEMENTS.has(d.kind)) return;
        const idx = d.elements.findIndex((x) => x.id === S.sel);
        const r = await api("POST", `/api/interfaces/item/${encodeURIComponent(d.id)}/elements`,
                            idx >= 0 ? { index: idx + 1 } : {});
        S.detail = r.interface; S.sel = r.element.id; S.created = r.element.id;
        await refreshTreeQuietly();
        await reload({ keepTable: true });
        await renderTable();
        syncAround();
        const n = tableWrap.querySelector(`tr[data-key="${CSS.escape(r.element.id)}"] [data-field="name"]`);
        if (n) { n.focus(); n.select(); }
        return;
      }
      case "del-element": {
        if (!d || !S.sel) return;
        const i = d.elements.findIndex((x) => x.id === S.sel);
        const r = await api("DELETE", `/api/interfaces/item/${encodeURIComponent(d.id)}/elements/${encodeURIComponent(S.sel)}`);
        S.detail = r.interface;
        S.sel = r.interface.elements[Math.min(i, r.interface.elements.length - 1)]?.id || null;
        await refreshTreeQuietly(); return reload({ keepTable: false });
      }
      case "up": case "down": {
        if (!d || !S.sel) return;
        const r = await api("POST", `/api/interfaces/item/${encodeURIComponent(d.id)}/elements/${encodeURIComponent(S.sel)}/move`,
                            { delta: name === "up" ? -1 : 1 });
        S.detail = r.interface;
        await refreshTreeQuietly(); await reload({ keepTable: true }); await renderTable(); syncAround();
        tableWrap.querySelector(`tr[data-key="${CSS.escape(S.sel)}"] [data-field="name"]`)?.focus();
        return;
      }
      case "delete": {
        if (!d) return;
        const n = (d.ports || []).length;
        openModal(`Delete ${KIND_LABEL[d.kind] || d.kind}`, `<p class="text-sm">Delete <b>${esc(d.name)}</b>?` +
          (n ? ` ${n} port(s) using it will have no interface.` : "") +
          ((d.used_by || []).length ? ` Elements typed by it fall back to <code>double</code>.` : "") + `</p>`,
          async () => {
            await api("DELETE", `/api/interfaces/item/${encodeURIComponent(d.id)}`);
            studio.log(`Deleted ${d.name}`, "warning");
            S.currentId = null; S.detail = null;
            await refreshTreeQuietly(); await reload();
          });
        return;
      }
      case "make-shared": return makeSharedDialog(d.owner_port.id, d.name);
      case "highlight": {
        studio.emit("highlight", { ids: (d.ports || []).map((p) => p.id), color: d.color, reason: `Interface ${d.name}` });
        studio.log(`Highlighted ${(d.ports || []).length} port(s) using ${d.name}`, "info");
        return;
      }
    }
  }

  async function createItem(kind, extra = {}) {
    const item = await api("POST", "/api/interfaces", kind ? { kind, ...extra } : extra);
    studio.log(`Created ${KIND_LABEL[item.kind] || item.kind} ${item.name}`, "ok");
    S.currentId = item.id; S.sel = null; S.expanded.clear(); S.created = item.id;
    await refreshTreeQuietly();
    await reload();
    focusName();
  }

  function importDictionary() {
    studio.openFile(".json,application/json", run(async (text) => {
      const preview = await api("POST", "/api/interfaces/dictionary/import", { text, dry_run: true });
      if (!preview.collisions.length) return doImport(text, {});
      const rows = preview.collisions.map((c) => `<tr><td class="p-1 font-mono">${esc(c.name)}</td>
          <td class="p-1 text-xs text-slate-500">${esc(c.existing_kind)} ← ${esc(c.incoming_kind)}</td>
          <td class="p-1"><select class="input" name="choice:${esc(c.name)}">
            ${option("keep", "Keep existing")}${option("replace", "Replace existing")}${option("rename", `Rename to ${c.suggested_rename}`)}</select></td></tr>`).join("");
      openModal("Resolve dictionary conflicts", `
        <p class="text-sm text-slate-600">${preview.collisions.length} of ${preview.items.length} item(s) already exist in this project's dictionary.</p>
        <label class="block text-sm">Apply to all
          <select class="input" data-ifc="all-choice"><option value="">(choose per item)</option>${option("keep", "Keep existing")}${option("replace", "Replace existing")}${option("rename", "Rename imported")}</select></label>
        <table class="w-full text-sm"><thead><tr class="text-xs text-slate-500"><th class="text-left p-1">Name</th><th class="text-left p-1">Kind</th><th class="text-left p-1">Action</th></tr></thead><tbody>${rows}</tbody></table>`,
        async (values) => {
          const resolution = {};
          for (const [k, v] of Object.entries(values)) if (k.startsWith("choice:")) resolution[k.slice(7)] = v;
          await doImport(text, resolution);
        });
      document.querySelector('#modal-root [data-ifc="all-choice"]')?.addEventListener("change", (e) => {
        if (!e.target.value) return;
        document.querySelectorAll('#modal-root select[name^="choice:"]').forEach((s) => { s.value = e.target.value; });
      });
    }));
  }

  async function doImport(text, resolution) {
    const r = await api("POST", "/api/interfaces/dictionary/import", { text, resolution, default: "keep" });
    const parts = [];
    if (r.added.length) parts.push(`added ${r.added.join(", ")}`);
    if (r.replaced.length) parts.push(`replaced ${r.replaced.join(", ")}`);
    const ren = Object.entries(r.renamed);
    if (ren.length) parts.push(`renamed ${ren.map(([a, b]) => `${a}→${b}`).join(", ")}`);
    if (r.kept.length) parts.push(`kept ${r.kept.join(", ")}`);
    studio.log(`Imported dictionary: ${parts.join("; ") || "nothing to do"}`, "ok");
    await refreshTreeQuietly();
    await reload();
  }

  function makeSharedDialog(portId, name, after) {
    openModal("Save interface to dictionary", `
      <label class="block text-sm">Name in the dictionary <input class="input" name="name" value="${esc(name)}" /></label>
      <label class="block text-sm">If the name already exists
        <select class="input" name="on_conflict">${option("rename", "Save under a new name")}${option("keep", "Keep the existing interface (use it for this port)")}${option("replace", "Replace the existing interface")}</select></label>`,
      async (v) => {
        const r = await api("POST", "/api/interfaces/make-shared", { port: portId, name: v.name, on_conflict: v.on_conflict });
        studio.log(`Port interface saved to the dictionary as ${r.interface.name}`, "ok");
        S.currentId = r.interface.id;
        await refreshTreeQuietly();
        if (S.visible) await reload();
        if (after) await after();
      });
  }

  // ------------------------------------------------------------------ toolbar
  studio.registerToolbarButton({
    id: "interface-editor", label: "Interface Editor", group: "Interfaces",
    title: "Open the Interface Editor (Alt+I)", onClick() { studio.switchTab("interfaces"); },
  });
  studio.registerToolbarButton({
    id: "add-adapter", label: "Adapter", group: "Interfaces",
    title: "Add an interface adapter to the selected architecture or component",
    onClick() {
      const sel = studio.selected;
      if (!sel || !["PartDefinition", "PartUsage"].includes(sel.kind)) {
        studio.log("Select an architecture (part definition) or component (part) to hold the adapter.", "warning");
        return;
      }
      openModal("Add adapter", `<p class="text-sm text-slate-600">Inside <b>${esc(sel.qualified_name)}</b>. The adapter gets an <i>In</i> and an <i>Out</i> port; map output elements from input elements in its Properties.</p>
        <label class="block text-sm">Name <input class="input" name="name" value="Adapter" /></label>`,
        async (v) => {
          const a = await api("POST", "/api/interfaces/adapter", { parent: sel.id, name: v.name });
          studio.log(`Added adapter ${a.name}`, "ok");
          await studio.refreshTree(); await studio.selectElement(a.id);
        });
    },
  });
  studio.registerShortcut({ key: "i", alt: true, handler() { studio.switchTab("interfaces"); } });

  // ------------------------------------------------------------------ drag and drop
  // The canvas reports HTML5 drops as drop-on-element (docs/EXTENDING.md). An interface or
  // value type (from this editor's list or the containment tree) dropped on a port becomes the
  // port's interface, as in System Composer. Other dragged elements belong to other features.
  const canTypePort = (n) => n?.interface_category === "Interface" || n?.kind === "PortDefinition";
  studio.on("drop-on-element", (p) => {
    if (!p?.dragged_id || !p?.target_id) return;
    const iface = studio.state.treeIndex.get(p.dragged_id);
    if (!canTypePort(iface)) return;
    const target = studio.state.treeIndex.get(p.target_id);
    if (target?.kind !== "PortUsage") {
      studio.log(`Drop ${iface.name} on a port to make it the port's interface.`, "info");
      return;
    }
    run(assignDropped)(iface, target);
  });

  async function assignDropped(iface, port) {
    if (port.interface?.id === iface.id) { studio.log(`${port.name} already uses ${iface.name}`, "info"); return; }
    if (iface.owned) {
      studio.log(`${iface.name} is owned by another port; convert it to a shared interface to reuse it.`, "warning");
      return;
    }
    await api("POST", "/api/interfaces/assign", { port: port.id, interface: iface.id });
    studio.log(`Port ${port.name} now uses interface ${iface.name}`, "ok");
    await studio.refreshTree();
    await studio.selectElement(port.id);
  }

  // ------------------------------------------------------------------ inspector: port
  studio.registerInspectorSection({
    id: "port-interface", title: "Interface", order: 20,
    render(el, box) {
      if (el.kind !== "PortUsage") return false;
      box.innerHTML = `<div class="text-xs text-slate-400">Loading…</div>`;
      run(renderPortSection)(el, box);
      return true;
    },
  });

  async function renderPortSection(el, box) {
    const [info, listing] = await Promise.all([
      api("GET", `/api/interfaces/port/${encodeURIComponent(el.id)}`), api("GET", "/api/interfaces")]);
    if (!box.isConnected) return;
    S.meta = listing.meta;
    const iface = info.interface;
    const current = iface ? (iface.owned ? "owned" : iface.id) : "";
    const group = (kind, label) => {
      const items = listing.items.filter((i) => i.kind === kind);
      return items.length ? `<optgroup label="${label}">${items.map((i) => option(i.id, i.name, i.id === current)).join("")}</optgroup>` : "";
    };
    const pdefs = listing.port_definitions.length
      ? `<optgroup label="SysML port definitions">${listing.port_definitions.map((i) => option(i.id, i.name, i.id === current)).join("")}</optgroup>` : "";
    const preview = iface ? elementPreview(iface) : `<div class="text-xs text-slate-500 italic">No interface: compatible with any port.</div>`;
    const role = iface?.kind === "ServiceInterface"
      ? `<div class="ifc-insp-row"><label>Role</label><select class="input" data-ifc="port-role">
          ${option("out", "Client (calls functions)", info.port.direction === "out")}
          ${option("in", "Server (provides functions)", info.port.direction === "in")}
          ${option("inout", "Unspecified", !["in", "out"].includes(info.port.direction))}</select></div>` : "";
    const conns = info.connectors.length
      ? `<div class="mt-2 text-xs font-semibold text-slate-600">Connectors</div>` + info.connectors.map((c) =>
        `<div class="text-sm"><span class="${c.compatible ? "ifc-ok" : "ifc-bad"}">${c.compatible ? "✓" : "✗"}</span>
           <a href="#" class="ifc-link" data-nav="${esc(c.id)}">${esc(c.name)}</a> → ${esc(c.other || "")}
           ${c.reasons.length ? `<ul class="ifc-reasons">${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div>`).join("") : "";
    box.innerHTML = `
      <div class="ifc-insp-row"><label for="ifc-port-select">Interface</label>
        <select class="input" id="ifc-port-select" data-ifc="port-interface" aria-label="Port interface">
          ${option("", "<empty>", current === "")}${option("owned", "<owned>", current === "owned")}
          ${group("DataInterface", "Data interfaces")}${group("ValueType", "Value types")}
          ${group("PhysicalInterface", "Physical interfaces")}${group("ServiceInterface", "Service interfaces")}${pdefs}
        </select>
        ${iface ? `<span class="ifc-swatch" style="background:${esc(iface.color || "transparent")}"></span>` : ""}
      </div>
      ${role}
      ${preview}
      <div class="flex flex-wrap gap-1 mt-2">
        ${iface ? `<button type="button" class="btn-action" data-ifc-port="edit">Edit in Interface Editor</button>` : ""}
        ${iface && iface.owned ? `<button type="button" class="btn-action" data-ifc-port="shared">Convert to shared…</button>` : ""}
        ${iface && !iface.owned && iface.kind !== "ValueType" ? `<button type="button" class="btn-action" data-ifc-port="owned">Convert to owned</button>` : ""}
        <button type="button" class="btn-action" data-ifc-port="connect">Connect to…</button>
      </div>
      ${conns}`;
    const reselect = async () => { await studio.refreshTree(); await studio.selectElement(el.id); };
    box.querySelector('[data-ifc="port-interface"]').addEventListener("change", run(async (e) => {
      const value = e.target.value;
      await api("POST", "/api/interfaces/assign", { port: el.id, interface: value || null });
      const label = value === "owned" ? "an owned interface" : (value ? e.target.selectedOptions[0].textContent : "no interface");
      studio.log(`${el.name} now uses ${label}`, "ok");
      await reselect();
    }));
    box.querySelector('[data-ifc="port-role"]')?.addEventListener("change", run(async (e) => {
      await api("PATCH", `/api/element/${encodeURIComponent(el.id)}`, { props: { direction: e.target.value } });
      await reselect();
    }));
    box.addEventListener("click", run(async (e) => {
      const nav = e.target.closest("[data-nav]");
      if (nav) { e.preventDefault(); studio.emit("navigate", { id: nav.dataset.nav }); return; }
      const b = e.target.closest("[data-ifc-port]");
      if (!b) return;
      const what = b.dataset.ifcPort;
      if (what === "edit") { openItem(iface.id); studio.switchTab("interfaces"); }
      else if (what === "owned") {
        await api("POST", "/api/interfaces/make-owned", { port: el.id });
        studio.log(`${el.name} now owns a copy of ${iface.name}`, "ok");
        await reselect();
      } else if (what === "shared") makeSharedDialog(el.id, iface.name, reselect);
      else if (what === "connect") await connectDialog(el);
    }));
  }

  function elementPreview(iface) {
    const els = iface.elements || [];
    if (!els.length) return `<div class="text-xs text-slate-500 italic">${esc(iface.name)} has no elements.</div>`;
    const cols = iface.kind === "PhysicalInterface" ? ["Element", "Domain"]
      : iface.kind === "ServiceInterface" ? ["Function", "Prototype"]
      : iface.kind === "ValueType" ? [] : ["Element", "Type", "Dims", "Units"];
    if (!cols.length) return "";
    const cells = (x) => iface.kind === "PhysicalInterface" ? [x.name, x.domain]
      : iface.kind === "ServiceInterface" ? [x.name, x.prototype]
      : [x.name, x.type, x.effective?.dimensions ?? x.dimensions, x.effective?.units ?? x.units];
    return `<table class="ifc-table ifc-mini" data-ifc="port-elements"><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
      <tbody>${els.map((x) => `<tr>${cells(x).map((c) => `<td style="padding:2px 6px">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  async function connectDialog(port) {
    const r = await api("GET", `/api/interfaces/candidates/${encodeURIComponent(port.id)}`);
    if (!r.candidates.length) { studio.log(`No ports to connect ${port.name} to (add ports to sibling components).`, "warning"); return; }
    const isIn = r.port.direction === "in";
    const elOpts = (paths) => option("", "(whole port)") + paths.map((p) => option(p, p)).join("");
    const root = openModal(`Connect ${r.port.label}`, `
      <label class="block text-sm">${isIn ? "Source" : "Destination"} port
        <select class="input" name="other" data-ifc="connect-target">${r.candidates.map((c) =>
          option(c.id, `${c.compatible ? "✓" : "✗"} ${c.label}`)).join("")}</select></label>
      <div class="text-xs" data-ifc="connect-status"></div>
      <label class="block text-sm">Element of ${esc(r.port.label)}
        <select class="input" name="own_element">${elOpts(r.port.element_paths)}</select></label>
      <label class="block text-sm">Element of the other port
        <select class="input" name="other_element" data-ifc="connect-other-element"></select></label>`,
      async (v) => {
        const body = isIn
          ? { source: v.other, target: port.id, source_element: v.other_element, target_element: v.own_element }
          : { source: port.id, target: v.other, source_element: v.own_element, target_element: v.other_element };
        const c = await api("POST", "/api/interfaces/connect", body);
        studio.log(`Connected ${c.source.label} → ${c.target.label}: ${c.compatible ? "compatible" : "INCOMPATIBLE: " + c.reasons.join("; ")}`,
                   c.compatible ? "ok" : "warning");
        await studio.refreshTree();
        await studio.selectElement(c.connector.id);
      });
    const sel = root.querySelector('[data-ifc="connect-target"]');
    const update = () => {
      const c = r.candidates.find((x) => x.id === sel.value);
      root.querySelector('[data-ifc="connect-other-element"]').innerHTML = elOpts(c?.element_paths || []);
      root.querySelector('[data-ifc="connect-status"]').innerHTML = c?.compatible
        ? `<span class="ifc-ok">✓ Compatible</span>`
        : `<span class="ifc-bad">✗ Incompatible</span><ul class="ifc-reasons">${(c?.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    };
    sel.addEventListener("change", update);
    update();
  }

  // ------------------------------------------------------------------ inspector: connector
  studio.registerInspectorSection({
    id: "connector-interface", title: "Interface compatibility", order: 21,
    render(el, box) {
      if (el.compatibility === undefined) return false;
      box.innerHTML = `<div class="text-xs text-slate-400">Checking…</div>`;
      run(async () => {
        const r = await api("GET", `/api/interfaces/compatibility?connector=${encodeURIComponent(el.id)}`);
        if (box.isConnected) renderCompat(el, box, r);
      })();
      return true;
    },
  });

  function renderCompat(el, box, r) {
    const endRow = (end, field, label) => `
      <div class="ifc-insp-row" style="align-items:flex-start"><label class="pt-1">${label}</label>
        <div class="flex-1 min-w-0">
          <div class="text-sm" style="word-break:break-word">${esc(end.label)}
            ${end.interface ? `<span class="ifc-swatch inline-block align-middle" style="background:${esc(end.interface.color || "transparent")}"></span>` : ""}</div>
          ${end.interface && end.element_paths.length
            ? `<select class="input mt-1" data-ifc-end="${field}" aria-label="${label} element">
                 ${option("", "(whole port)", !end.element)}${end.element_paths.map((p) => option(p, `element: ${p}`, p === end.element)).join("")}</select>` : ""}
        </div>
      </div>`;
    box.innerHTML = `${endRow(r.source, "source_element", "Source")}${endRow(r.target, "target_element", "Destination")}
      <div data-ifc="compat-status" class="${r.compatible ? "ifc-ok" : "ifc-bad"}">${r.compatible ? "✓ Compatible" : "✗ Incompatible"}</div>
      ${r.reasons.length ? `<ul class="ifc-reasons" data-ifc="compat-reasons">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
    box.querySelectorAll("[data-ifc-end]").forEach((s) => s.addEventListener("change", run(async (e) => {
      const r2 = await api("POST", "/api/interfaces/connector-elements", { connector: el.id, [e.target.dataset.ifcEnd]: e.target.value });
      await refreshTreeQuietly();
      if (box.isConnected) renderCompat(el, box, r2);
    })));
  }

  // ------------------------------------------------------------------ inspector: adapter
  studio.registerInspectorSection({
    id: "adapter-mappings", title: "Adapter mappings", order: 22,
    render(el, box) {
      if (el.kind !== "Adapter") return false;
      run(async () => {
        const info = await api("GET", `/api/interfaces/adapter/${encodeURIComponent(el.id)}`);
        if (box.isConnected) renderAdapter(el, box, info);
      })();
      return true;
    },
  });

  function renderAdapter(el, box, info) {
    const rows = info.mappings.length ? info.mappings : [];
    const mapRow = (m) => `<tr data-mrow>
        <td><input list="ifc-adapter-out-${esc(el.id)}" data-m="target" value="${esc(m.target)}" aria-label="Output element" /></td>
        <td class="text-center text-slate-400">←</td>
        <td><input list="ifc-adapter-in-${esc(el.id)}" data-m="source" value="${esc(m.source)}" aria-label="Input element" /></td>
        <td><input data-m="note" value="${esc(m.note)}" placeholder="e.g. ft × 0.3048" aria-label="Conversion note" /></td>
        <td><button type="button" class="btn-action" data-m-del title="Remove mapping">✕</button></td></tr>`;
    box.innerHTML = `
      <div class="text-xs text-slate-500 mb-1">Input: <b>${esc(Object.entries(info.inputs).map(([p, i]) => `${p}: ${i || "—"}`).join(", ") || "—")}</b>
        · Output: <b>${esc(info.output || "—")}</b>. Unmapped output elements pass through from same-named input elements.</div>
      <datalist id="ifc-adapter-out-${esc(el.id)}">${info.target_paths.map((p) => `<option value="${esc(p)}"></option>`).join("")}</datalist>
      <datalist id="ifc-adapter-in-${esc(el.id)}">${info.source_paths.map((p) => `<option value="${esc(p)}"></option>`).join("")}</datalist>
      <table class="ifc-table"><thead><tr><th>Output element</th><th></th><th>Input element</th><th>Unit conversion / note</th><th></th></tr></thead>
        <tbody data-ifc="mappings">${rows.map(mapRow).join("")}</tbody></table>
      <div class="flex gap-1 mt-2"><button type="button" class="btn-action" data-m-add>Add mapping</button>
        <span class="flex-1"></span><button type="button" class="btn-primary" data-m-save>Save mappings</button></div>`;
    const body = box.querySelector('[data-ifc="mappings"]');
    box.querySelector("[data-m-add]").addEventListener("click", () => {
      body.insertAdjacentHTML("beforeend", mapRow({ target: "", source: "", note: "" }));
      body.lastElementChild.querySelector("input")?.focus();
    });
    body.addEventListener("click", (e) => { if (e.target.closest("[data-m-del]")) e.target.closest("tr").remove(); });
    box.querySelector("[data-m-save]").addEventListener("click", run(async () => {
      const mappings = [...body.querySelectorAll("tr[data-mrow]")].map((tr) => ({
        target: tr.querySelector('[data-m="target"]').value.trim(),
        source: tr.querySelector('[data-m="source"]').value.trim(),
        note: tr.querySelector('[data-m="note"]').value.trim(),
      })).filter((m) => m.target || m.source);
      const r = await api("PATCH", `/api/interfaces/adapter/${encodeURIComponent(el.id)}`, { mappings });
      studio.log(`Saved ${r.mappings.length} mapping(s) on ${el.name}`, "ok");
      await refreshTreeQuietly();
      if (box.isConnected) renderAdapter(el, box, r);
    }));
  }

  // ------------------------------------------------------------------ inspector: interface summary
  studio.registerInspectorSection({
    id: "interface-item", title: "Interface", order: 20,
    render(el, box) {
      if (!el.interface_category) return false;
      const isElement = el.interface_category === "InterfaceElement";
      const facts = isElement
        ? [["Type", el.type], ["Dimensions", el.dimensions], ["Units", el.units], ["Domain", el.domain], ["Prototype", el.prototype]]
        : [["Kind", KIND_LABEL[el.interface_kind] || el.interface_kind], ["Owned by a port", el.owned ? "yes" : null],
           ["Base type", el.base_type], ["Units", el.units]];
      box.innerHTML = `
        <div class="text-sm space-y-1">
          ${el.color ? `<div class="flex items-center gap-2"><span class="ifc-swatch" style="background:${esc(el.color)}"></span><span class="text-xs text-slate-500">${esc(el.color)}</span></div>` : ""}
          ${facts.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `<div><span class="text-slate-500 inline-block w-28">${k}</span>${esc(v)}</div>`).join("")}
          <button type="button" class="btn-action mt-1" data-ifc="open-editor">Open in Interface Editor</button>
        </div>`;
      box.querySelector('[data-ifc="open-editor"]').addEventListener("click", () => {
        if (isElement) openItem(el.owner_id, el.id); else openItem(el.id);
        studio.switchTab("interfaces");
      });
      return true;
    },
  });
}
