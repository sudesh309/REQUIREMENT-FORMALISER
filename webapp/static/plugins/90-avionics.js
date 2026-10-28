// Avionics domain pack (see docs/features/avionics.md).
//
//   * "New from template…" in the header (File commands): a blank avionics project or the
//     complete IMA avionics example. Replaces the project like New (a fresh undo history).
//   * Tab "Avionics" (id "avionics", order 95) with five views:
//       Start               template chooser, project status (profile, libraries, FHA, safety),
//                           mass / power roll-up
//       Interface library   ARINC 429 / 664 / 825 / 653, MIL-STD-1553B, discrete, analog, power:
//                           import the selected items (or all) into the interface dictionary
//       Requirement library ARP4754A system / item and DO-178C HLR / LLR skeleton sets and the
//                           verification guidance per DAL
//       FHA                 the functional hazard assessment as an editable table
//       Safety check        the avionics.* rule results (DAL, partitioning, FHA, verification
//                           guidance) with links to the elements they name
//   * Toolstrip: Modeling > Avionics (open the tab, From template…); Analysis > Safety Check.
//   * Inspector section "Avionics safety" on FHA rows and on elements with a DAL.
//
// Backend: webapp/routes/avionics.py. Events used: navigate, project-changed, model-changed,
// element-changed, tab-shown.

const STYLES = `
.av-root { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; background:#fff; }
.av-nav { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #e2e8f0; background:#f8fafc; flex:none; flex-wrap:wrap; }
.av-seg { display:inline-flex; border:1px solid #cbd5e1; border-radius:6px; overflow:hidden; background:#fff; }
.av-seg button { padding:4px 14px; font-size:12px; color:#475569; }
.av-seg button + button { border-left:1px solid #cbd5e1; }
.av-seg button.on { background:#dbeafe; color:#1d4ed8; font-weight:600; }
.av-seg button:focus-visible { outline:2px solid #2563eb; outline-offset:-2px; }
.av-spacer { flex:1; }
.av-body { flex:1; min-height:0; overflow:auto; position:relative; }
.av-view { padding:12px 14px 24px; display:flex; flex-direction:column; gap:12px; }
.av-view.off { display:none; }
.av-h { font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:#64748b; font-weight:600; margin:0; }
.av-muted { color:#64748b; }
.av-small { font-size:12px; }
.av-banner { padding:6px 10px; border-radius:6px; font-size:12px; border:1px solid; }
.av-banner.warn { background:#fffbeb; color:#92400e; border-color:#fde68a; }
.av-banner.ok { background:#f0fdf4; color:#166534; border-color:#bbf7d0; }
.av-banner.err { background:#fef2f2; color:#991b1b; border-color:#fecaca; }
.av-banner.info { background:#eff6ff; color:#1e40af; border-color:#bfdbfe; }
.av-btn { font-size:12px; padding:3px 10px; border:1px solid #cbd5e1; border-radius:5px; background:#fff; color:#334155; white-space:nowrap; }
.av-btn:hover:not(:disabled) { background:#f1f5f9; }
.av-btn:disabled { opacity:.4; cursor:not-allowed; }
.av-btn.primary { background:#2563eb; border-color:#2563eb; color:#fff; }
.av-btn.primary:hover:not(:disabled) { background:#1d4ed8; }
.av-btn.danger { color:#b91c1c; border-color:#fecaca; }
.av-btn:focus-visible { outline:2px solid #2563eb; outline-offset:1px; }
.av-cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:12px; }
.av-card { border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; display:flex; flex-direction:column; gap:6px; background:#fff; }
.av-card h3 { font-size:14px; font-weight:600; margin:0; }
.av-card ul { margin:0 0 0 16px; list-style:disc; font-size:12px; color:#475569; }
.av-card .actions { display:flex; gap:6px; margin-top:auto; padding-top:6px; flex-wrap:wrap; }
.av-kv { display:grid; grid-template-columns:auto 1fr; gap:3px 12px; font-size:12px; }
.av-kv > span:nth-child(odd) { color:#64748b; }
.av-table { border-collapse:collapse; width:100%; font-size:12px; }
.av-table th { position:sticky; top:0; z-index:1; background:#f1f5f9; text-align:left; font-weight:600; color:#475569; padding:4px 8px; border-bottom:1px solid #cbd5e1; white-space:nowrap; }
.av-table td { border-bottom:1px solid #eef2f7; padding:3px 8px; vertical-align:top; }
.av-table tr:hover td { background:#f8fafc; }
.av-table td.num { text-align:right; font-variant-numeric:tabular-nums; }
.av-table th.num { text-align:right; }
.av-table tr.group td { background:#f8fafc; font-weight:600; color:#334155; }
.av-chip { display:inline-flex; align-items:center; padding:0 7px; border-radius:9999px; font-size:11px; font-weight:600; white-space:nowrap; background:#f1f5f9; color:#334155; }
.av-chip.error { background:#fee2e2; color:#b91c1c; }
.av-chip.warning { background:#fef3c7; color:#92400e; }
.av-chip.info { background:#e0f2fe; color:#075985; }
.av-chip.ok { background:#dcfce7; color:#166534; }
.av-chip.Catastrophic { background:#fecaca; color:#991b1b; }
.av-chip.Hazardous { background:#fed7aa; color:#9a3412; }
.av-chip.Major { background:#fde68a; color:#92400e; }
.av-chip.Minor { background:#fef9c3; color:#854d0e; }
.av-chip.NoSafetyEffect { background:#dcfce7; color:#166534; }
.av-dal { font-variant-numeric:tabular-nums; min-width:22px; justify-content:center; }
.av-link { color:#1d4ed8; cursor:pointer; text-align:left; }
.av-link:hover { text-decoration:underline; }
.av-link:focus-visible { outline:2px solid #2563eb; }
.av-bar { display:flex; flex-wrap:wrap; align-items:center; gap:8px; font-size:12px; }
.av-input, .av-select { font-size:12px; border:1px solid #cbd5e1; border-radius:4px; padding:2px 5px; background:#fff; min-width:0; }
.av-input:focus, .av-select:focus { outline:2px solid #93c5fd; border-color:#3b82f6; }
.av-input.bad, .av-select.bad { border-color:#dc2626; background:#fef2f2; }
.av-sevbtn { display:inline-flex; align-items:center; gap:4px; padding:1px 9px; border-radius:9999px; font-size:12px; border:1px solid #e2e8f0; color:#94a3b8; background:#fff; }
.av-sevbtn.on.error { background:#fee2e2; color:#b91c1c; border-color:#fecaca; }
.av-sevbtn.on.warning { background:#fef3c7; color:#92400e; border-color:#fde68a; }
.av-sevbtn.on.info { background:#e0f2fe; color:#075985; border-color:#bae6fd; }
.av-fha td { vertical-align:middle; }
.av-fha td .av-input, .av-fha td .av-select { width:100%; }
.av-fha tr.sel td { background:#eff6ff; }
.av-fha tr.flash td { background:#dcfce7; }
.av-fha td:first-child { border-left:4px solid transparent; font-family:ui-monospace,monospace; white-space:nowrap; }
.av-fha tr[data-class="Catastrophic"] td:first-child { border-left-color:#dc2626; }
.av-fha tr[data-class="Hazardous"] td:first-child { border-left-color:#ea580c; }
.av-fha tr[data-class="Major"] td:first-child { border-left-color:#d97706; }
.av-fha tr[data-class="Minor"] td:first-child { border-left-color:#ca8a04; }
.av-fha tr[data-class="No Safety Effect"] td:first-child { border-left-color:#16a34a; }
.av-items { display:flex; flex-wrap:wrap; gap:2px 10px; }
.av-phases { display:flex; flex-wrap:wrap; gap:4px 12px; font-size:12px; }
.av-phases label { display:inline-flex; align-items:center; gap:3px; }
.av-field { display:block; font-size:13px; margin-bottom:6px; }
.av-field > span { display:block; color:#475569; font-size:12px; margin-bottom:2px; }
.av-field .input, .av-field select, .av-field textarea { width:100%; }
.av-radio { display:flex; flex-direction:column; gap:6px; font-size:13px; }
.av-radio label { display:flex; gap:6px; align-items:flex-start; border:1px solid #e2e8f0; border-radius:6px; padding:6px 8px; cursor:pointer; }
.av-radio label small { display:block; color:#64748b; }
.av-empty { padding:18px; color:#64748b; font-style:italic; font-size:13px; }
.av-guid td, .av-guid th { vertical-align:top; }
.av-lbl { font-family:ui-monospace,monospace; font-size:11px; color:#475569; }
.av-section { border:1px solid #e2e8f0; border-radius:6px; padding:6px 8px; margin-bottom:6px; font-size:12px; background:#fff; }
.av-section .av-issue { margin-top:4px; }
`;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m]));
const cls = (c) => String(c || "").replace(/\s+/g, "");
const SEVERITIES = ["error", "warning", "info"];
const SEV_ICON = { error: "●", warning: "▲", info: "i" };
const SEV_LABEL = { error: "Errors", warning: "Warnings", info: "Info" };
const VIEWS = [["start", "Start"], ["interfaces", "Interface library"], ["requirements", "Requirement library"],
               ["fha", "FHA"], ["safety", "Safety check"]];
const enc = encodeURIComponent;

export default async function install(studio) {
  const style = document.createElement("style");
  style.dataset.plugin = "avionics";
  style.textContent = STYLES;
  document.head.appendChild(style);

  const S = {
    pane: null, view: "start", visible: false, stale: {},
    info: null, templates: null, ifaces: null, ifaceSel: new Set(), ifaceQ: "",
    reqs: null, reqSel: new Set(), fha: null, fhaSel: null, safety: null,
    sev: new Set(["error", "warning", "info"]), rule: "", q: "", quiet: 0, banner: {},
  };
  const $ = (sel) => S.pane?.querySelector(sel);
  const viewEl = (v) => $(`[data-av-view="${v}"]`);

  /* ---------- small helpers ---------- */

  const dalChip = (d) => `<span class="av-chip av-dal ${d ? "" : "av-muted"}" title="${d ? `DAL ${esc(d)}` : "no DAL"}">${esc(d || "–")}</span>`;
  const banner = (kind, text) => `<div class="av-banner ${kind}" role="status">${esc(text)}</div>`;

  function setBanner(view, kind, text) {
    S.banner[view] = text ? { kind, text } : null;
    const host = viewEl(view)?.querySelector("[data-av-banner]");
    if (host) host.innerHTML = text ? banner(kind, text) : "";
  }
  const bannerHtml = (view) => `<div data-av-banner>${S.banner[view] ? banner(S.banner[view].kind, S.banner[view].text) : ""}</div>`;

  // Show an element: the canvas for what it draws (components, ports, connectors), Properties
  // for anything else; the tab is shown before `navigate` so the canvas can scroll to it.
  let showSeq = 0;
  async function showElement(id) {
    if (!id) return;
    const seq = ++showSeq;
    let tab = "properties";
    if (document.querySelector('#tab-bar .tab[data-tab="architecture"]')) {
      try {
        const r = await studio.api("GET", `/api/arch/locate/${enc(id)}`);
        if (r.composition === id || r.select === id) tab = "architecture";
      } catch { /* not part of an architecture */ }
    }
    if (seq !== showSeq) return;
    if (studio.state.tab !== tab) studio.switchTab(tab);
    studio.emit("navigate", { id });
  }

  // A model change made by this tab (its own request): refresh the tree so every view hears
  // of it, but do not rebuild this tab's tables under the user's cursor.
  async function refreshQuietly() {
    S.quiet++;
    try { await studio.refreshTree(); } finally { setTimeout(() => { S.quiet = Math.max(0, S.quiet - 1); }, 80); }
  }

  const safeApi = async (fn) => { try { return await fn(); } catch { return null; } };

  /* ---------- the tab ---------- */

  studio.registerTab({
    id: "avionics", title: "Avionics", order: 95,
    mount(pane) {
      S.pane = pane;
      pane.innerHTML = `
        <div class="av-root">
          <div class="av-nav" role="toolbar" aria-label="Avionics">
            <div class="av-seg" role="tablist" data-av="views">
              ${VIEWS.map(([id, label]) => `<button role="tab" data-av-go="${id}" aria-selected="false">${esc(label)}</button>`).join("")}
            </div>
            <span class="av-spacer"></span>
            <span class="av-muted av-small" data-av="status"></span>
          </div>
          <div class="av-body">
            ${VIEWS.map(([id]) => `<div class="av-view off" data-av-view="${id}"></div>`).join("")}
          </div>
        </div>`;
      pane.querySelector('[data-av="views"]').addEventListener("click", (e) => {
        const b = e.target.closest("[data-av-go]");
        if (b) go(b.dataset.avGo);
      });
      pane.addEventListener("click", onClick);
      pane.addEventListener("change", onChange);
      pane.addEventListener("input", onInput);
      pane.addEventListener("keydown", onKey);
      go("start", { quiet: true });
    },
    onShow() { S.visible = true; loadView(S.view).catch(() => {}); },
  });

  function go(view, { quiet = false } = {}) {
    S.view = view;
    for (const [id] of VIEWS) {
      viewEl(id)?.classList.toggle("off", id !== view);
      const b = $(`[data-av-go="${id}"]`);
      b?.classList.toggle("on", id === view);
      b?.setAttribute("aria-selected", id === view ? "true" : "false");
    }
    if (!quiet || S.visible) loadView(view).catch(() => {});
  }

  async function loadView(view) {
    S.stale[view] = false;
    if (view === "start") await loadStart();
    else if (view === "interfaces") await loadInterfaces();
    else if (view === "requirements") await loadRequirements();
    else if (view === "fha") await loadFha();
    else if (view === "safety") await loadSafety();
  }

  studio.on("tab-shown", (id) => { S.visible = id === "avionics"; });
  const onModel = () => {
    for (const [id] of VIEWS) S.stale[id] = true;
    if (!S.visible) return;
    if (S.quiet) return;
    if (S.view === "fha" && S.pane?.contains(document.activeElement) &&
        /^(input|select|textarea)$/i.test(document.activeElement.tagName)) return;   // never under the cursor
    loadView(S.view).catch(() => {});
  };
  studio.on("model-changed", onModel);
  studio.on("element-changed", onModel);
  studio.on("project-changed", () => {
    S.info = S.ifaces = S.reqs = S.fha = S.safety = null;
    S.fhaSel = null; S.ifaceSel.clear(); S.reqSel.clear(); S.banner = {};
  });

  /* =====================================================================
   *  Start
   * ===================================================================== */

  async function loadStart() {
    const [info, tpl] = await Promise.all([studio.api("GET", "/api/avionics/info"),
                                           safeApi(() => studio.api("GET", "/api/avionics/templates"))]);
    S.info = info;
    S.templates = tpl?.templates || info.templates;
    renderStart();
    // Counts of what the templates build take a moment the first time.
    safeApi(() => studio.api("GET", "/api/avionics/templates?counts=1")).then((r) => {
      if (r?.templates) { S.templates = r.templates; if (S.view === "start") renderStart(); }
    });
  }

  function countsLine(t) {
    const c = t.counts;
    if (!c) return "";
    if (t.id === "ima_example") {
      return `${c.physical_components} physical components · ${c.requirements} requirements · ${c.test_cases} test cases · ${c.fha_rows} FHA rows · ${c.interfaces} interfaces`;
    }
    return `${c.interfaces} interfaces · ${c.requirements} requirement skeletons`;
  }

  function renderStart() {
    const host = viewEl("start");
    if (!host || !S.info) return;
    const i = S.info;
    const c = i.safety.counts;
    host.innerHTML = `
      ${bannerHtml("start")}
      <h2 class="av-h">Start a project from a template</h2>
      <div class="av-cards" data-av="templates">
        ${(S.templates || []).map((t) => `
          <div class="av-card" data-av-template="${esc(t.id)}">
            <h3>${esc(t.name)}</h3>
            <div class="av-small">${esc(t.description)}</div>
            <ul>${(t.includes || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
            <div class="av-small av-muted" data-av="counts">${esc(countsLine(t))}</div>
            <div class="actions"><button class="av-btn primary" data-av-new="${esc(t.id)}">Create project…</button></div>
          </div>`).join("")}
      </div>
      <h2 class="av-h">This project</h2>
      <div class="av-cards">
        <div class="av-card" data-av="status-profile">
          <h3>Avionics profile</h3>
          ${i.profile.present
            ? `<div class="av-small"><span class="av-chip ok">present</span> version ${esc(i.profile.version)}, ${i.profile.stereotypes.length} of ${i.profile.expected.length} stereotypes</div>`
            : `<div class="av-small"><span class="av-chip warning">missing</span> Equipment, LRU, LRM, Partition, SoftwareItem, DataBusPort ... stereotypes with DAL, mass, power, MTBF.</div>`}
          <div class="actions"><button class="av-btn" data-av-act="profile">${i.profile.present ? "Complete the profile" : "Add the Avionics profile"}</button>
            <button class="av-btn" data-av-act="profile-editor">Profile Editor</button></div>
        </div>
        <div class="av-card" data-av="status-interfaces">
          <h3>Interface library</h3>
          <div class="av-small"><span class="av-chip ${i.interfaces.present ? "ok" : ""}">${i.interfaces.present} of ${i.interfaces.total}</span> library items are in the interface dictionary.</div>
          <div class="actions"><button class="av-btn" data-av-go="interfaces">Browse and import…</button></div>
        </div>
        <div class="av-card" data-av="status-requirements">
          <h3>Requirements</h3>
          <div class="av-small">${i.requirement_sets.length
            ? i.requirement_sets.map((s) => `<div>${esc(s.name)} <span class="av-muted">${esc(s.prefix)} · ${s.requirements}</span></div>`).join("")
            : "No requirement set yet."}</div>
          <div class="actions"><button class="av-btn" data-av-go="requirements">Requirement library…</button></div>
        </div>
        <div class="av-card" data-av="status-safety">
          <h3>Safety</h3>
          <div class="av-small">${i.fha.rows} FHA row(s) ·
            <span class="av-chip error">${c.error} errors</span> <span class="av-chip warning">${c.warning} warnings</span> <span class="av-chip info">${c.info} hints</span></div>
          <div class="actions"><button class="av-btn" data-av-go="fha">FHA table</button>
            <button class="av-btn" data-av-go="safety">Safety check</button></div>
        </div>
      </div>
      <h2 class="av-h">Equipment roll-up</h2>
      ${i.equipment.length ? `
      <table class="av-table" data-av="equipment"><thead><tr><th>Architecture</th><th class="num">Items</th><th class="num">Mass (kg)</th>
        <th class="num">Nominal power (W)</th><th class="num">Peak power (W)</th><th>Items per DAL</th></tr></thead><tbody>
        ${i.equipment.map((e) => `<tr data-av-arch="${esc(e.id)}"><td><button class="av-link" data-av-open="${esc(e.id)}">${esc(e.name)}</button></td>
          <td class="num">${e.items}</td><td class="num">${e.mass_kg}</td><td class="num">${e.power_nominal_w}</td><td class="num">${e.power_peak_w}</td>
          <td>${Object.entries(e.by_dal).map(([d, n]) => `<span class="av-chip">DAL ${esc(d)} × ${n}</span>`).join(" ")}</td></tr>`).join("")}
      </tbody></table>`
        : `<div class="av-empty">No equipment with mass or power values yet. Apply an Avionics stereotype (LRU, Computer, Sensor ...) to part definitions and enter their values.</div>`}`;
    $('[data-av="status"]').textContent = i.project;
  }

  async function newFromTemplate(templateId) {
    const tpls = S.templates || (await safeApi(() => studio.api("GET", "/api/avionics/templates")))?.templates || [];
    const pick = tpls.find((t) => t.id === templateId) || tpls[0];
    if (!pick) return;
    const why = await studio.unsavedReason?.();
    const pending = studio.dialog("New avionics project", `
      <div class="av-radio" data-av="template-choice">
        ${tpls.map((t) => `<label><input type="radio" name="template" value="${esc(t.id)}" ${t.id === pick.id ? "checked" : ""}/>
          <span><b>${esc(t.name)}</b><small>${esc(t.description)}</small></span></label>`).join("")}
      </div>
      <label class="av-field"><span>Project name</span><input class="input" name="name" value="${esc(pick.default_name || "AvionicsProject")}" autocomplete="off" /></label>
      ${studio.unsavedHtml(why, "The new project replaces it.")}`,
      { ok: why ? "Discard changes and create" : "Create", danger: !!why });
    // The suggested name follows the chosen template until the user types their own.
    const form = document.querySelector("#modal-root #modal-form");
    let typed = false;
    form?.querySelector('[name="name"]')?.addEventListener("input", () => { typed = true; });
    form?.addEventListener("change", (e) => {
      if (e.target.name !== "template" || typed) return;
      const t = tpls.find((x) => x.id === e.target.value);
      if (t) form.querySelector('[name="name"]').value = t.default_name || "AvionicsProject";
    });
    const v = await pending;
    if (!v) return;
    const template = v.template || pick.id;
    const name = (v.name || "").trim();
    const res = await studio.api("POST", "/api/new/avionics", { template, ...(name ? { name } : {}) });
    studio.state.selectedId = null;
    studio.emit("project-changed", { reason: "new" });
    await studio.refreshTree();
    studio.log(`New avionics project ${res.name} (${template === "ima_example" ? "complete IMA example" : "blank"})`, "ok");
    if (res.open) {
      studio.switchTab("architecture");
      studio.emit("navigate", { id: res.open });
    }
  }

  /* =====================================================================
   *  Interface library
   * ===================================================================== */

  async function loadInterfaces() {
    S.ifaces = await studio.api("GET", "/api/avionics/interfaces/library");
    renderInterfaces();
  }

  function renderInterfaces() {
    const host = viewEl("interfaces");
    const lib = S.ifaces;
    if (!host || !lib) return;
    const q = S.ifaceQ.toLowerCase();
    const items = (g) => g.items.filter((it) => !q || `${it.name} ${it.description} ${it.kind}`.toLowerCase().includes(q));
    const missing = lib.groups.flatMap((g) => g.items).filter((it) => !it.present).length;
    const sel = S.ifaceSel.size;
    host.innerHTML = `
      ${bannerHtml("interfaces")}
      <div class="av-banner warn" data-av="icd-warning">${esc(lib.warning)}</div>
      <div class="av-bar">
        <button class="av-btn primary" data-av-act="import-selected" ${sel ? "" : "disabled"}>Import selected (${sel})</button>
        <button class="av-btn" data-av-act="import-all" ${missing ? "" : "disabled"}>Import all missing (${missing})</button>
        <button class="av-btn" data-av-act="select-missing">Select missing</button>
        <button class="av-btn" data-av-act="select-none" ${sel ? "" : "disabled"}>Clear</button>
        <input class="av-input" data-av="iface-filter" placeholder="Filter…" aria-label="Filter the interface library" value="${esc(S.ifaceQ)}" style="width:200px" />
        <span class="av-muted">${lib.present} of ${lib.count} in the project. Items a selection needs (value types, enumerations) are imported with it.</span>
      </div>
      <table class="av-table" data-av="iface-table"><thead><tr><th style="width:26px"></th><th>Name</th><th>Kind</th><th>Description</th><th class="num">Elements</th><th>Labels (octal)</th><th>Status</th></tr></thead><tbody>
      ${lib.groups.map((g) => { const its = items(g); return its.length ? `
        <tr class="group"><td colspan="7">${esc(g.title)}</td></tr>
        ${its.map((it) => `<tr data-av-iface="${esc(it.name)}">
          <td><input type="checkbox" data-av-pick="${esc(it.name)}" aria-label="Select ${esc(it.name)}" ${S.ifaceSel.has(it.name) ? "checked" : ""} ${it.present ? "disabled" : ""}/></td>
          <td><b>${esc(it.name)}</b></td><td>${esc(it.kind.replace(/([A-Z])/g, " $1").trim())}${it.units ? ` <span class="av-muted">[${esc(it.units)}]</span>` : ""}</td>
          <td>${esc(it.description)}${it.requires.length ? `<div class="av-muted">needs ${esc(it.requires.join(", "))}</div>` : ""}</td>
          <td class="num">${it.elements || ""}</td>
          <td class="av-lbl">${it.labels.map((l) => `<span title="${esc(l.element)}: ${esc(l.description)}">${esc(l.label)}</span>`).join(" ")}</td>
          <td>${it.present ? `<span class="av-chip ok">in project</span>` : `<span class="av-chip">not imported</span>`}</td></tr>`).join("")}` : ""; }).join("")}
      </tbody></table>`;
  }

  async function importInterfaces(body, what) {
    const res = await studio.api("POST", "/api/avionics/interfaces/import", body);
    const n = res.created.length;
    setBanner("interfaces", "ok", `Imported ${n} item${n === 1 ? "" : "s"}${res.skipped.length ? `, ${res.skipped.length} already there` : ""}${res.dependencies.length ? ` (${res.dependencies.length} needed by the selection)` : ""}.`);
    studio.log(`Imported ${n} avionics interface item(s) ${what}`, "ok");
    S.ifaceSel.clear();
    await refreshQuietly();
    await loadInterfaces();
  }

  /* =====================================================================
   *  Requirement library
   * ===================================================================== */

  async function loadRequirements() {
    S.reqs = await studio.api("GET", "/api/avionics/requirements/library");
    renderRequirements();
  }

  function renderRequirements() {
    const host = viewEl("requirements");
    const lib = S.reqs;
    if (!host || !lib) return;
    const dalSel = $('[data-av="req-dal"]')?.value || "";
    host.innerHTML = `
      ${bannerHtml("requirements")}
      <div class="av-bar">
        <button class="av-btn primary" data-av-act="req-import" ${S.reqSel.size ? "" : "disabled"}>Import selected (${S.reqSel.size})</button>
        <button class="av-btn" data-av-act="req-all">Select all</button>
        <label class="av-small">DAL of every requirement
          <select class="av-select" data-av="req-dal" aria-label="DAL of the imported requirements">
            <option value="">typical level of each entry</option>
            ${["A", "B", "C", "D", "E"].map((d) => `<option value="${d}" ${d === dalSel ? "selected" : ""}>${d}</option>`).join("")}
          </select></label>
        <span class="av-muted">Skeleton statements carry &lt;placeholders&gt;; set the levels from your FHA.</span>
      </div>
      <div class="av-cards" data-av="req-sets">
        ${lib.sets.map((s) => `<label class="av-card" data-av-reqset="${esc(s.key)}">
          <h3><input type="checkbox" data-av-reqpick="${esc(s.key)}" ${S.reqSel.has(s.key) ? "checked" : ""}/> ${esc(s.title)}</h3>
          <div class="av-small">${esc(s.description)}</div>
          <div class="av-small av-muted">Set ${esc(s.name)} · prefix ${esc(s.prefix)} · ${s.requirements} requirements ·
            level ${esc(s.level)} ${s.present ? `<span class="av-chip ok">set in project</span>` : ""}</div></label>`).join("")}
      </div>
      <h2 class="av-h">Verification guidance per DAL (validator guidance, not standard text)</h2>
      <table class="av-table av-guid" data-av="guidance"><thead><tr><th>DAL</th><th>Failure condition</th><th class="num">DO-178C objectives</th>
        <th class="num">with independence</th><th>Structural coverage</th><th>System-level methods</th><th>Guidance</th></tr></thead><tbody>
        ${Object.entries(lib.guidance).map(([d, g]) => `<tr><td>${dalChip(d)}</td><td>${esc(g.failure)}</td><td class="num">${g.objectives}</td>
          <td class="num">${g.independent}</td><td>${esc(g.coverage)}</td><td>${esc(g.system_methods.join(", "))}</td><td>${esc(g.text)}</td></tr>`).join("")}
      </tbody></table>
      <h2 class="av-h">Rules</h2>
      <table class="av-table"><tbody>
        ${Object.entries(lib.rules).map(([id, r]) => `<tr><td><span class="av-chip ${esc(r.severity)}">${esc(r.severity)}</span></td><td><b>${esc(r.title)}</b> <span class="av-lbl">${esc(id)}</span></td><td>${esc(r.description)}</td></tr>`).join("")}
      </tbody></table>`;
  }

  /* =====================================================================
   *  FHA
   * ===================================================================== */

  async function loadFha() {
    S.fha = await studio.api("GET", "/api/avionics/fha");
    renderFha();
  }

  const classOptions = (f, sel) => f.classifications.map((c) =>
    `<option value="${esc(c)}" ${c === sel ? "selected" : ""}>${esc(c)} · ${esc(f.dal_by_classification[c])}</option>`).join("");
  const functionOptions = (f, sel) => `<option value="">(no function)</option>` + f.functions.map((fn) =>
    `<option value="${esc(fn.id)}" ${fn.id === sel ? "selected" : ""}>${esc(fn.name)}</option>`).join("");

  function fhaRow(f, r) {
    const bad = !r.valid;
    return `<tr data-av-fha="${esc(r.fha_id)}" data-id="${esc(r.id)}" data-class="${esc(r.classification)}" class="${S.fhaSel === r.id ? "sel" : ""}">
      <td>${esc(r.fha_id)}</td>
      <td><select class="av-select" data-av-field="function" aria-label="Function of ${esc(r.fha_id)}" style="min-width:130px">${functionOptions(f, r.function?.id)}</select></td>
      <td><input class="av-input" data-av-field="failure_condition" value="${esc(r.failure_condition)}" aria-label="Failure condition of ${esc(r.fha_id)}" style="min-width:260px" /></td>
      <td><input class="av-input ${bad ? "bad" : ""}" data-av-field="flight_phase" list="av-phases" value="${esc(r.flight_phase)}" aria-label="Flight phase of ${esc(r.fha_id)}" style="min-width:90px" /></td>
      <td><input class="av-input" data-av-field="effect" value="${esc(r.effect)}" aria-label="Effect of ${esc(r.fha_id)}" style="min-width:260px" /></td>
      <td><select class="av-select ${bad ? "bad" : ""}" data-av-field="classification" aria-label="Classification of ${esc(r.fha_id)}" style="min-width:150px">${classOptions(f, r.classification)}</select></td>
      <td data-av-cell="dal">${dalChip(r.dal)}</td>
      <td data-av-cell="prob" class="av-small av-muted">${esc(r.probability)}</td>
      <td data-av-cell="items">${itemsHtml(r)}</td>
      <td><button class="av-btn danger" data-av-del="${esc(r.fha_id)}" title="Delete ${esc(r.fha_id)}" aria-label="Delete ${esc(r.fha_id)}">✕</button></td></tr>`;
  }

  function itemsHtml(r) {
    if (!r.function) return `<span class="av-chip warning" title="Name the function that can cause this failure condition">no function</span>`;
    if (!r.allocated) return `<span class="av-chip warning" title="The function is not allocated to any item">not allocated</span>`;
    return `<span class="av-items">${r.items.map((it) =>
      `<button class="av-link av-chip" data-av-open="${esc(it.id)}" title="Layer ${it.layer}: ${esc(it.qualified_name)}">${esc(it.name)}${it.dal ? ` (${esc(it.dal)})` : ""}</button>`).join("")}</span>`;
  }

  function renderFha() {
    const host = viewEl("fha");
    const f = S.fha;
    if (!host || !f) return;
    host.innerHTML = `
      ${bannerHtml("fha")}
      <div class="av-bar">
        <button class="av-btn primary" data-av-act="fha-add">Add row…</button>
        <span class="av-muted">Functional hazard assessment: the classification gives the assigned DAL (Catastrophic A, Hazardous B, Major C, Minor D, No Safety Effect E).
          Edits are saved as you leave a cell and are undoable.</span>
        <span class="av-spacer"></span>
        <span data-av="fha-counts">${f.classifications.map((c) => f.counts[c] ? `<span class="av-chip ${cls(c)}">${esc(c)} ${f.counts[c]}</span>` : "").join(" ")}</span>
      </div>
      <datalist id="av-phases">${f.phases.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>
      ${f.rows.length ? `
      <div style="overflow-x:auto"><table class="av-table av-fha" data-av="fha-table"><thead><tr><th>ID</th><th>Function</th><th>Failure condition</th><th>Flight phase</th>
        <th>Effect</th><th>Classification</th><th>DAL</th><th>Probability / FH</th><th>Allocated to</th><th></th></tr></thead><tbody>
        ${f.rows.map((r) => fhaRow(f, r)).join("")}</tbody></table></div>`
        : `<div class="av-empty" data-av="fha-empty">No failure conditions yet. <b>Add row…</b> names a function, its failure condition, the flight phases, the effect and the classification.</div>`}`;
  }

  function rowOf(fhaId) { return S.fha?.rows.find((r) => r.fha_id === fhaId); }

  async function commitFha(tr, field, value) {
    const r = rowOf(tr.dataset.avFha);
    if (!r) return;
    const stored = field === "function" ? (r.function?.id || "") : r[field];
    if (value === stored) return;
    const body = { [field]: field === "function" ? (value || null) : value };
    const input = tr.querySelector(`[data-av-field="${field}"]`);
    S.quiet++;                       // the edit's own revision change must not rebuild the table
    setTimeout(() => { S.quiet = Math.max(0, S.quiet - 1); }, 400);
    try {
      const upd = await studio.api("PATCH", `/api/avionics/fha/${enc(r.id)}`, body);
      Object.assign(r, upd);
      input?.classList.remove("bad");
      tr.dataset.class = r.classification;
      tr.querySelector('[data-av-cell="dal"]').innerHTML = dalChip(r.dal);
      tr.querySelector('[data-av-cell="prob"]').textContent = r.probability;
      tr.querySelector('[data-av-cell="items"]').innerHTML = itemsHtml(r);
      if (field === "flight_phase" && input) input.value = r.flight_phase;
      recount();
      await refreshQuietly();
    } catch {
      // The request failed (the Output log has the reason): put the stored value back.
      if (input) {
        input.value = stored;
        input.classList.add("bad");
        setTimeout(() => input.classList.remove("bad"), 1500);
      }
    }
  }

  function recount() {
    const f = S.fha;
    f.counts = {};
    for (const r of f.rows) f.counts[r.classification] = (f.counts[r.classification] || 0) + 1;
    const host = $('[data-av="fha-counts"]');
    if (host) host.innerHTML = f.classifications.map((c) => f.counts[c] ? `<span class="av-chip ${cls(c)}">${esc(c)} ${f.counts[c]}</span>` : "").join(" ");
  }

  async function addFhaRow() {
    if (!S.fha) await loadFha();
    const f = S.fha;
    const v = await studio.dialog("Add FHA row", `
      <label class="av-field"><span>Function</span><select name="function" class="input">${functionOptions(f, "")}</select></label>
      <label class="av-field"><span>Failure condition</span><input name="failure_condition" class="input" placeholder="Loss of ..." autocomplete="off" /></label>
      <div class="av-field"><span>Flight phases</span><div class="av-phases">
        ${f.phases.map((p) => `<label><input type="checkbox" name="phase_${esc(p)}" ${p === "All" ? "checked" : ""}/> ${esc(p)}</label>`).join("")}</div></div>
      <label class="av-field"><span>Effect</span><textarea name="effect" class="input" rows="2"></textarea></label>
      <label class="av-field"><span>Classification</span><select name="classification" class="input">${classOptions(f, "Major")}</select></label>`,
      { ok: "Add" });
    if (!v) return;
    const phases = f.phases.filter((p) => v[`phase_${p}`] === "on");
    const body = { failure_condition: v.failure_condition || "", classification: v.classification,
                   flight_phase: phases.length ? phases.join(",") : "All", effect: v.effect || "" };
    if (v.function) body.function = v.function;
    try {
      const row = await studio.api("POST", "/api/avionics/fha", body);
      S.fhaSel = row.id;
      await refreshQuietly();
      await loadFha();
      const tr = $(`[data-av-fha="${CSS.escape(row.fha_id)}"]`);
      tr?.classList.add("flash");
      tr?.scrollIntoView({ block: "nearest" });
      setTimeout(() => tr?.classList.remove("flash"), 1200);
    } catch { /* logged; the dialog is closed, the table unchanged */ }
  }

  async function deleteFhaRow(fhaId) {
    const r = rowOf(fhaId);
    if (!r) return;
    const ok = await studio.dialog("Delete FHA row", `<p class="text-sm">Delete <b>${esc(r.fha_id)}</b> “${esc(r.failure_condition)}”? You can undo with Ctrl+Z.</p>`,
      { ok: "Delete", danger: true });
    if (!ok) return;
    try {
      await studio.api("DELETE", `/api/avionics/fha/${enc(r.id)}`);
      await refreshQuietly();
      await loadFha();
    } catch { /* logged */ }
  }

  /* =====================================================================
   *  Safety check
   * ===================================================================== */

  async function loadSafety() {
    S.safety = await studio.api("GET", "/api/avionics/safety");
    renderSafety();
  }

  function shownIssues() {
    const r = S.safety;
    if (!r) return [];
    const q = S.q.toLowerCase();
    return r.issues.filter((i) => S.sev.has(i.severity) && (!S.rule || i.rule === S.rule) &&
      (!q || `${i.message} ${i.rule} ${i.elements.map((e) => e.qualified_name).join(" ")}`.toLowerCase().includes(q)));
  }

  function renderSafety() {
    const host = viewEl("safety");
    const r = S.safety;
    if (!host || !r) return;
    const rows = shownIssues();
    const ruleOptions = r.rules.filter((x) => x.count).map((x) =>
      `<option value="${esc(x.id)}" ${x.id === S.rule ? "selected" : ""}>${esc(x.title)} · ${esc(x.id)} (${x.count})</option>`).join("");
    const keepQ = document.activeElement?.dataset?.av === "safety-search";
    host.innerHTML = `
      ${bannerHtml("safety")}
      <div class="av-bar">
        <button class="av-btn primary" data-av-act="safety-run">Run check</button>
        <span data-av="sev">${SEVERITIES.map((s) => `<button class="av-sevbtn ${s} ${S.sev.has(s) ? "on" : ""}" data-av-sev="${s}" aria-pressed="${S.sev.has(s)}">${SEV_ICON[s]} <span data-av-count="${s}">${r.counts[s]}</span> ${SEV_LABEL[s]}</button>`).join(" ")}</span>
        <select class="av-select" data-av="safety-rule" aria-label="Rule filter" style="max-width:330px"><option value="">All rules (${r.total})</option>${ruleOptions}</select>
        <input class="av-input" data-av="safety-search" placeholder="Search…" aria-label="Search issues" value="${esc(S.q)}" style="width:180px" />
      </div>
      ${rows.length ? `
      <table class="av-table" data-av="safety-table"><thead><tr><th style="width:90px">Severity</th><th>Rule</th><th>Message</th><th>Elements</th></tr></thead><tbody>
        ${rows.map((i, n) => `<tr data-av-issue="${n}" data-rule="${esc(i.rule)}" data-sev="${esc(i.severity)}">
          <td><span class="av-chip ${esc(i.severity)}">${SEV_ICON[i.severity]} ${esc(i.severity)}</span></td>
          <td><b>${esc(i.title)}</b><div class="av-lbl">${esc(i.rule)}</div></td>
          <td>${esc(i.message)}</td>
          <td><span class="av-items">${i.elements.map((e) => `<button class="av-link" data-av-open="${esc(e.id)}" title="${esc(e.qualified_name)}">${esc(e.name)}</button>`).join("")}</span></td></tr>`).join("")}
      </tbody></table>`
        : `<div class="av-empty" data-av="safety-empty">${r.total ? "No issue matches the filters." : "✓ The avionics rules found nothing to report."}</div>`}`;
    if (keepQ) { const el = $('[data-av="safety-search"]'); el?.focus(); el?.setSelectionRange(el.value.length, el.value.length); }
  }

  /* =====================================================================
   *  Events
   * ===================================================================== */

  async function onClick(e) {
    const t = e.target;
    const newBtn = t.closest("[data-av-new]");
    if (newBtn) { newFromTemplate(newBtn.dataset.avNew).catch(() => {}); return; }
    const go1 = t.closest("[data-av-go]");
    if (go1 && !go1.closest('[data-av="views"]')) { go(go1.dataset.avGo); return; }
    const open = t.closest("[data-av-open]");
    if (open) { showElement(open.dataset.avOpen); return; }
    const sev = t.closest("[data-av-sev]");
    if (sev) {
      const s = sev.dataset.avSev;
      S.sev.has(s) ? S.sev.delete(s) : S.sev.add(s);
      renderSafety();
      return;
    }
    const del = t.closest("[data-av-del]");
    if (del) { deleteFhaRow(del.dataset.avDel).catch(() => {}); return; }
    const row = t.closest("[data-av-fha]");
    if (row && !t.closest("button")) {
      S.fhaSel = row.dataset.id;
      S.pane.querySelectorAll("[data-av-fha]").forEach((tr) => tr.classList.toggle("sel", tr === row));
    }
    const act = t.closest("[data-av-act]")?.dataset.avAct;
    if (!act) return;
    try {
      if (act === "profile") {
        const res = await studio.api("POST", "/api/avionics/profile");
        setBanner("start", "ok", res.created ? "Added the Avionics profile." : res.added ? `Added ${res.added} missing stereotype(s).` : "The Avionics profile is complete.");
        await refreshQuietly();
        await loadStart();
      } else if (act === "profile-editor") {
        studio.switchTab("profiles");
      } else if (act === "import-selected") {
        await importInterfaces({ names: [...S.ifaceSel] }, "selected");
      } else if (act === "import-all") {
        await importInterfaces({}, "(all missing)");
      } else if (act === "select-missing") {
        S.ifaceSel = new Set(S.ifaces.groups.flatMap((g) => g.items).filter((it) => !it.present).map((it) => it.name));
        renderInterfaces();
      } else if (act === "select-none") {
        S.ifaceSel.clear();
        renderInterfaces();
      } else if (act === "req-all") {
        S.reqSel = new Set(S.reqs.sets.map((s) => s.key));
        renderRequirements();
      } else if (act === "req-import") {
        const dal = $('[data-av="req-dal"]')?.value || "";
        const res = await studio.api("POST", "/api/avionics/requirements/import", { sets: [...S.reqSel], ...(dal ? { dal } : {}) });
        setBanner("requirements", "ok", `Created ${res.sets.map((s) => `${s.name} (${s.requirements})`).join(", ")}.`);
        studio.log(`Imported ${res.requirements} requirement skeleton(s)`, "ok");
        S.reqSel.clear();
        await refreshQuietly();
        await loadRequirements();
      } else if (act === "fha-add") {
        await addFhaRow();
      } else if (act === "safety-run") {
        await loadSafety();
      }
    } catch { /* the request failed: studio.api logged the reason */ }
  }

  function onChange(e) {
    const t = e.target;
    const pick = t.closest("[data-av-pick]");
    if (pick) {
      pick.checked ? S.ifaceSel.add(pick.dataset.avPick) : S.ifaceSel.delete(pick.dataset.avPick);
      renderInterfaces();
      return;
    }
    const rp = t.closest("[data-av-reqpick]");
    if (rp) {
      rp.checked ? S.reqSel.add(rp.dataset.avReqpick) : S.reqSel.delete(rp.dataset.avReqpick);
      renderRequirements();
      return;
    }
    if (t.dataset.av === "safety-rule") { S.rule = t.value; renderSafety(); return; }
    const field = t.dataset.avField;
    const tr = t.closest("[data-av-fha]");
    if (field && tr) commitFha(tr, field, t.value.trim()).catch(() => {});
  }

  function onInput(e) {
    const t = e.target;
    if (t.dataset.av === "iface-filter") {
      S.ifaceQ = t.value.trim();
      const pos = t.selectionStart;
      renderInterfaces();
      const el = $('[data-av="iface-filter"]');
      el?.focus(); el?.setSelectionRange(pos, pos);
    } else if (t.dataset.av === "safety-search") {
      S.q = t.value.trim();
      renderSafety();
    }
  }

  function onKey(e) {
    const t = e.target;
    if (t.dataset?.avField && t.tagName === "INPUT") {
      if (e.key === "Enter") { e.preventDefault(); t.blur(); }
      else if (e.key === "Escape") {
        const tr = t.closest("[data-av-fha]");
        const r = tr && rowOf(tr.dataset.avFha);
        if (r) { t.value = r[t.dataset.avField]; t.blur(); }
      }
    }
  }

  /* =====================================================================
   *  Toolstrip, header command, inspector section
   * ===================================================================== */

  const openBtn = studio.registerToolbarButton({
    id: "avionics", label: "Avionics", group: "Avionics", section: "modeling",
    title: "Avionics: templates, interface and requirement libraries, FHA", onClick() { studio.switchTab("avionics"); go("start"); },
  });
  openBtn.dataset.openTab = "avionics";
  studio.registerToolbarButton({
    id: "avionics-safety", label: "Safety Check", group: "Analysis", section: "analysis",
    title: "Avionics safety / DAL rules: requirement DAL, FHA allocation, partitioning, verification guidance",
    onClick() { studio.switchTab("avionics"); go("safety"); },
  });

  // File > New from template…: next to New in the header.
  const newCmd = document.querySelector('header [data-cmd="new"]');
  if (newCmd) {
    const b = document.createElement("button");
    b.className = "btn-ghost";
    b.dataset.avionics = "new-template";
    b.title = "New project from an avionics template";
    b.textContent = "New from template…";
    newCmd.after(b);
    b.addEventListener("click", () => newFromTemplate().catch(() => {}));
  }

  // Properties tab: the safety side of an FHA row or of an element with a DAL.
  studio.registerInspectorSection({
    id: "avionics-safety", title: "Avionics safety", order: 60,
    render(el, box) {
      if (el.kind !== "FhaEntry" && !el.avionics_dal) return false;
      box.dataset.avSection = el.kind === "FhaEntry" ? "fha" : "dal";
      const head = el.kind === "FhaEntry"
        ? `<div class="av-section"><b>${esc(el.name)}</b> ${el.fha ? `<span class="av-chip ${cls(el.fha.classification)}">${esc(el.fha.classification)}</span> ${dalChip(el.fha.dal)}` : ""}
            <div class="av-small">${esc(el.fha?.failure_condition || "")}</div>
            <div class="av-small av-muted">Function: ${el.fha?.function ? `<button class="av-link" data-av-open="${esc(el.fha.function.id)}">${esc(el.fha.function.name)}</button>` : "none"}</div>
            <button class="av-btn" data-av-act="open-fha">Open in the FHA table</button></div>`
        : `<div class="av-section">Development assurance level ${dalChip(el.avionics_dal)}</div>`;
      box.innerHTML = `${head}<div data-av="el-issues" class="av-small av-muted">Checking the avionics rules…</div>`;
      box.addEventListener("click", (e) => {
        const open = e.target.closest("[data-av-open]");
        if (open) showElement(open.dataset.avOpen);
        if (e.target.closest('[data-av-act="open-fha"]')) { studio.switchTab("avionics"); go("fha"); }
      });
      studio.api("GET", `/api/avionics/safety?element=${enc(el.id)}`).then((r) => {
        const host = box.querySelector('[data-av="el-issues"]');
        if (!host) return;
        host.className = "av-small";
        host.innerHTML = r.issues.length ? r.issues.map((i) => `<div class="av-section av-issue" data-rule="${esc(i.rule)}">
          <span class="av-chip ${esc(i.severity)}">${esc(i.severity)}</span> <b>${esc(i.title)}</b><div>${esc(i.message)}</div></div>`).join("")
          : `<span class="av-muted">No avionics rule names this element.</span>`;
      }).catch(() => {});
    },
  });
}
