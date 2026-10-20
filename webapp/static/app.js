// Single-page controller for the SysML v2 web frontend.
// Talks to the stdlib HTTP backend (webapp/server.py); renders diagrams with
// mermaid.js (loaded from CDN by index.html).

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  selectedId: null,
  diagramMode: "bdd",
  tab: "properties",
  treeIndex: new Map(),   // id → node summary
  selected: null,         // full summary of the selected element (GET /api/element/<id>)
  selection: [],          // multi-selection ids (canvas, tables); defaults to [selectedId]
};

/* ---------- plugin event bus + registries (see the `studio` API at the bottom) ---------- */

const listeners = new Map();   // event name → Set<callback>
function on(event, cb) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(cb);
  return () => listeners.get(event).delete(cb);
}
function emit(event, payload) {
  for (const cb of listeners.get(event) || []) {
    try { cb(payload); } catch (e) { console.error(e); log(`plugin ${event} handler: ${e}`, "error"); }
  }
}
const tabs = new Map();              // plugin tab id → spec
const inspectorSections = [];        // {id, title, order, render}
const treeBadges = [];               // fn(node) → string | null
const shortcuts = [];                // {key, ctrl, shift, alt, handler}

/* ---------- API ---------- */

// opts.undoMerge = <element id>: this edit completes the creation of that element (naming
// it in place right after adding it), so it joins the creation's undo step.
async function api(method, path, body, opts = {}) {
  const headers = body ? { "Content-Type": "application/json" } : {};
  if (opts.undoMerge) headers["X-Undo-Merge"] = opts.undoMerge;
  let resp, text;
  rev.inflight++;
  try {
    resp = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    text = await resp.text();
  } finally {
    rev.inflight--;
    if (!rev.inflight && settlePending()) scheduleSettle();   // also after a network error
  }
  noteRevision(resp.headers.get("X-Model-Revision"));
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!resp.ok) {
    // Users read messages, not routes: no HTTP method, path or element ids.
    const message = readableError(data?.error || text || resp.statusText, resp.status);
    log(message, "error");
    throw new Error(message);
  }
  return data;
}

const UUID_RE = /'?\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'?/gi;

// An error message with element ids replaced by names (or "an element" when unknown).
function readableError(message, status = 0) {
  let text = String(message || "").trim();
  if (status >= 500) text = text.split("\n")[0] || "Internal error";
  text = text.replace(UUID_RE, (m) => {
    const id = m.replace(/'/g, "");
    const node = state.treeIndex.get(id);
    return node ? `'${node.name || node.kind}'` : "an element";
  });
  return text || (status === 404 ? "Not found" : "The request failed");
}

/* ---------- model revision: every view hears about every model change ---------- */
//
// The server stamps each API response with X-Model-Revision, which moves whenever a
// request changed the model, whichever feature sent it. A tree refresh emits
// "model-changed"; when the model moved and nobody refreshed the tree (an editor that
// saved in place, keeping its focus), the studio emits "element-changed" instead once
// the request's caller is done, so the canvas, its Property Inspector and the undo
// buttons are never stale. studio.selected follows silently (no re-render).
// "Done" means no studio.api request is in flight: a command that sends several requests
// before refreshing the tree (New model: new project, then its architecture) must not
// have views reload from the old tree in between.

const rev = { seen: null, tree: null, notified: null, refreshing: 0, inflight: 0, timer: 0 };

function noteRevision(header) {
  if (header === null || header === undefined) return;
  if (rev.seen === null) { rev.seen = rev.tree = rev.notified = header; return; }
  rev.seen = header;
  if (settlePending()) scheduleSettle();
}

// The model moved and no view has heard of it yet.
function settlePending() {
  return rev.seen !== null && rev.seen !== rev.tree && rev.seen !== rev.notified;
}

function scheduleSettle() {
  clearTimeout(rev.timer);
  // After the caller's continuation: a caller that refreshes the tree right after its
  // edit gets model-changed only.
  rev.timer = setTimeout(settle, 0);
}

async function settle() {
  // A request still running reschedules the settle when its answer arrives.
  if (rev.refreshing || rev.inflight || !settlePending()) return;
  const revision = rev.notified = rev.seen;
  let selected = null;
  if (state.selectedId) {
    try {
      // Plain fetch: an element deleted meanwhile is not an error worth logging.
      const r = await fetch(`/api/element/${encodeURIComponent(state.selectedId)}`);
      if (r.ok) {
        const el = await r.json();
        if (el?.id === state.selectedId) state.selected = selected = el;
      }
    } catch { /* offline: the next refresh catches up */ }
  }
  emit("element-changed", { revision, selected });
}

/* ---------- log + status ---------- */

function log(msg, severity = "info") {
  const pre = $("#log");
  const line = document.createElement("span");
  line.className = `log-${severity}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  pre.appendChild(line);
  pre.scrollTop = pre.scrollHeight;
  noteUnread(severity);
}

function setStatus(text) { $("#status").textContent = text; }

/* ---------- output pane: collapsible, remembers its state ---------- */

const LOG_KEY = "studio.output.collapsed";
let unread = 0;

function logCollapsed() { return $("#output-pane").classList.contains("collapsed"); }

function setLogCollapsed(on) {
  const pane = $("#output-pane"), btn = pane.querySelector('[data-cmd="toggle-log"]');
  pane.classList.toggle("collapsed", on);
  btn.textContent = on ? "▸" : "▾";
  btn.setAttribute("aria-expanded", on ? "false" : "true");
  btn.title = on ? "Show the output pane" : "Collapse the output pane";
  if (!on) { unread = 0; noteUnread(); }
  try { localStorage.setItem(LOG_KEY, on ? "1" : ""); } catch { /* private mode */ }
}

// While collapsed, warnings and errors are counted on the pane's header.
function noteUnread(severity) {
  const badge = $("#log-unread");
  if (!badge) return;
  if (severity && logCollapsed() && (severity === "error" || severity === "warning")) unread++;
  badge.textContent = unread ? `${unread} new` : "";
  badge.classList.toggle("hidden", !unread);
}

try { if (localStorage.getItem(LOG_KEY)) setLogCollapsed(true); } catch { /* private mode */ }

/* ---------- tree ---------- */

async function refreshTree() {
  rev.refreshing++;
  try {
    const tree = await api("GET", "/api/tree");
    const treeRevision = rev.seen;      // the revision this tree shows
    const state_info = await api("GET", "/api/state");
    $("#project-name").textContent = `${state_info.name}  ·  ${state_info.element_count} elements`;
    state.treeIndex.clear();
    $("#tree").innerHTML = "";
    $("#tree").appendChild(renderTreeNode(tree, 0));
    rev.tree = treeRevision;
    emit("model-changed", tree);
  } finally {
    rev.refreshing--;
    if (rev.seen !== rev.tree) scheduleSettle();   // changed while the tree was loading
  }
}

function renderTreeNode(node, depth) {
  state.treeIndex.set(node.id, node);
  const li = document.createElement("li");
  li.className = "tree-node";
  li.dataset.id = node.id;
  if (state.selectedId === node.id) li.classList.add("selected");

  const row = document.createElement("div"); row.className = "row";
  const tw = document.createElement("span");
  tw.className = "twisty" + (node.children?.length ? "" : " empty");
  tw.textContent = node.children?.length ? "▾" : "·";
  row.appendChild(tw);

  const nm = document.createElement("span");
  nm.textContent = node.name || `<${node.kind}>`;
  if (node.stereotypes?.length) {
    const stereo = document.createElement("span");
    stereo.textContent = " «" + node.stereotypes.map(s => s.name).join(", ") + "» ";
    stereo.style.color = "#7c3aed"; stereo.style.fontSize = ".7rem";
    nm.appendChild(stereo);
  }
  row.appendChild(nm);
  const badgeTexts = [...(node.badges || [])];
  for (const badge of treeBadges) {
    try { const t = badge(node); if (t) badgeTexts.push(t); } catch (e) { console.error(e); }
  }
  for (const text of badgeTexts) {
    {
      const b = document.createElement("span");
      b.className = "tree-badge"; b.textContent = text;
      row.appendChild(b);
    }
  }
  const k = document.createElement("span"); k.className = "kind"; k.textContent = node.kind;
  row.appendChild(k);

  row.addEventListener("click", () => selectSingle(node.id));

  li.appendChild(row);
  if (node.children?.length) {
    const ul = document.createElement("ul");
    node.children.forEach(c => ul.appendChild(renderTreeNode(c, depth + 1)));
    li.appendChild(ul);
  }
  return li;
}

/* ---------- selection + properties ---------- */

async function selectElement(id) {
  state.selectedId = id;
  $$("#tree .tree-node.selected").forEach(n => n.classList.remove("selected"));
  const li = document.querySelector(`#tree .tree-node[data-id="${id}"]`);
  if (li) li.classList.add("selected");
  const el = await api("GET", `/api/element/${id}`);
  state.selected = el;
  fillProperties(el);
  renderInspectorSections(el);
  renderLinksTab(el.links || []);
  if (state.tab === "diagram") refreshDiagram();
  setStatus(`${el.kind}  ${el.qualified_name}`);
  emit("select", el);
}

// A click in the containment tree or a `navigate` selects one element and replaces the
// multi-selection (an earlier canvas pick or table rows), so getSelection() is always the
// latest selection, wherever it was made: Link to Selection must never use a stale pick.
// selectElement alone keeps the multi-selection (the canvas publishes its picks with
// setSelection and then selects the primary one; editors re-select after a reload).
function selectSingle(id) {
  state.selection = [];
  const done = selectElement(id);           // sets selectedId at once
  emit("selection-changed", getSelection());
  return done;
}

function renderInspectorSections(el) {
  const host = $("#inspector-sections");
  host.innerHTML = "";
  for (const sec of [...inspectorSections].sort((a, b) => a.order - b.order)) {
    const box = document.createElement("section");
    box.className = "inspector-section";
    box.dataset.section = sec.id;
    if (sec.title) {
      const h = document.createElement("h4");
      h.className = "inspector-title"; h.textContent = sec.title;
      box.appendChild(h);
    }
    const body = document.createElement("div");
    box.appendChild(body);
    host.appendChild(box);
    try {
      // A section may return false to hide itself for this element.
      if (sec.render(el, body) === false) box.remove();
    } catch (e) { console.error(e); body.textContent = `Error: ${e}`; }
  }
}

function fillProperties(e) {
  $("#props-placeholder").classList.add("hidden");
  const f = $("#props-form");
  f.classList.remove("hidden");
  $("#props-kind").textContent = e.kind;
  $("#props-qname").textContent = e.qualified_name;
  $("#props-stereotypes").textContent = (e.stereotypes || [])
    .map(s => `«${s.name}» ${JSON.stringify(s.values)}`).join("  ");

  f.name.value = e.name || "";
  f.short_name.value = e.short_name || "";
  f.is_abstract.checked = !!e.is_abstract;

  const isFeature = e.multiplicity !== undefined;
  f.querySelectorAll("[data-feature]").forEach(el => el.style.display = isFeature ? "" : "none");
  if (isFeature) {
    f.mult_lower.value = e.multiplicity[0];
    f.mult_upper.value = e.multiplicity[1];
    f.typed_by.value = (e.typed_by || []).join(", ");
  }
  for (const attr of ["req_id", "text", "parameter_kind"]) {
    const present = e[attr] !== undefined;
    f.querySelectorAll(`[data-attr="${attr}"]`).forEach(el => el.style.display = present ? "" : "none");
    if (present) f[attr].value = e[attr] || "";
  }
  f.doc.value = e.doc || "";
}

$("#props-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = state.selectedId; if (!id) return;
  const f = ev.target;
  const props = {
    name: f.name.value.trim() || null,
    short_name: f.short_name.value.trim() || null,
    is_abstract: f.is_abstract.checked,
    doc: f.doc.value,
  };
  if (f.querySelector("[data-feature]").style.display !== "none") {
    props.multiplicity = [parseInt(f.mult_lower.value || "0", 10), f.mult_upper.value.trim() || "*"];
    if (f.typed_by.value.trim()) props.typed_by = f.typed_by.value.trim().split(",")[0].trim();
  }
  for (const attr of ["req_id", "text", "parameter_kind"]) {
    if (f.querySelector(`[data-attr="${attr}"]`)?.style.display !== "none") {
      props[attr] = f[attr].value;
    }
  }
  const updated = await api("PATCH", `/api/element/${id}`, { props });
  log(`Updated ${updated.qualified_name}`, "ok");
  await refreshTree();
  await selectElement(id);
});

/* ---------- toolbar (add element) ---------- */

$$(".btn-add").forEach(btn => btn.addEventListener("click", async () => {
  const kind = btn.dataset.kind;
  const where = state.selectedId ? state.selected?.qualified_name : null;
  const v = await dialog(`Add ${btn.textContent.trim()}`, `
    <label class="block text-sm">Name
      <input class="input" name="name" value="${escapeHtml(kind.replace("Definition", "").replace("Usage", ""))}" autocomplete="off" /></label>
    <p class="text-xs text-slate-500">New ${escapeHtml(kind)} inside ${escapeHtml(where || "the project root")}.</p>`, { ok: "Add" });
  const name = v?.name?.trim();
  if (!name) return;
  const parent = state.selectedId || null;
  const elem = await api("POST", "/api/element", { kind, name, parent });
  log(`Added ${kind} ${name}`, "ok");
  await refreshTree();
  await selectElement(elem.id);
}));

/* ---------- top header commands ---------- */

document.addEventListener("click", async (e) => {
  const cmd = e.target.dataset?.cmd;
  if (!cmd) return;
  if (cmd === "new") {
    const why = await unsavedReason();
    const v = await dialog("New project", `
      <label class="block text-sm">Project name
        <input class="input" name="name" value="UntitledProject" autocomplete="off" /></label>
      ${unsavedHtml(why, "A new project replaces it.")}`, { ok: why ? "Discard changes and create" : "Create", danger: !!why });
    const name = v?.name?.trim(); if (!name) return;
    await api("POST", "/api/new", { name });
    state.selectedId = null;
    emit("project-changed", { reason: "new" });
    await refreshTree(); log(`New project ${name}`, "ok");
  }
  else if (cmd === "save") {
    const r = await api("GET", "/api/save");
    download("project.json", r.text);
    await markSaved();
    log("Saved project.json", "ok");
  }
  else if (cmd === "load") {
    const why = await unsavedReason();
    if (why && !(await dialog("Load project", unsavedHtml(why, "Loading a project replaces it."),
                              { ok: "Discard changes and load…", danger: true }))) return;
    openFile("application/json", async (t) => {
      await api("POST", "/api/load", { text: t });
      state.selectedId = null;
      emit("project-changed", { reason: "load" });
      await refreshTree();
      log("Loaded project", "ok");
    });
  }
  else if (cmd === "import-sysml")  openFile(".sysml,.kerml,text/plain", async (t) => {
    await api("POST", "/api/parse", { source: t });
    await refreshTree(); log("Imported .sysml", "ok");
  });
  else if (cmd === "validate")      doValidate();
  else if (cmd === "export-menu")   $("#export-menu").classList.toggle("hidden");
  else if (cmd === "clear-log")     $("#log").textContent = "";
  else if (cmd === "delete-element") {
    if (!state.selectedId) return;
    const what = state.selected?.id === state.selectedId ? state.selected.qualified_name : "this element";
    if (!(await dialog("Delete element", `<p class="text-sm">Delete <b>${escapeHtml(what)}</b> and everything
        it contains? You can undo with Ctrl+Z.</p>`, { ok: "Delete", danger: true }))) return;
    await api("DELETE", `/api/element/${state.selectedId}`);
    state.selectedId = null; await refreshTree(); log("Deleted", "warning");
    $("#props-form").classList.add("hidden");
    $("#props-placeholder").classList.remove("hidden");
  }
  else if (cmd === "link")               openLinkDialog();
  else if (cmd === "define-stereotype")  openStereotypeDialog();
  else if (cmd === "apply-stereotype")   openApplyStereotypeDialog();
  else if (cmd === "sm-attach")          openSMAttachDialog();
  else if (cmd === "sm-state")           openSMStateDialog();
  else if (cmd === "sm-transition")      openSMTransitionDialog();
  else if (cmd === "sm-fire")            openSMFireDialog();
  else if (cmd === "parse") {
    await api("POST", "/api/parse", { source: $("#parser-source").value });
    await refreshTree(); log("Parsed", "ok");
  }
  else if (cmd === "diagram-refresh")    refreshDiagram();
  else if (cmd === "diagram-export-dot") downloadDiagramDot();
});

document.addEventListener("click", async (e) => {
  const fmt = e.target?.dataset?.export;
  if (!fmt) return;
  if (fmt === "dot") return downloadDiagramDot();
  const r = await api("GET", `/api/export/${fmt}`);
  download(`project.${fmt === "json-ld" ? "jsonld" : fmt}`, r.text);
  log(`Exported ${fmt}`, "ok");
  $("#export-menu").classList.add("hidden");
});

/* ---------- tabs ---------- */

$("#tab-bar").addEventListener("click", (e) => {
  const t = e.target.closest(".tab");
  if (t) switchTab(t.dataset.tab);
});
function switchTab(name) {
  state.tab = name;
  $$(".tab").forEach(t => t.classList.toggle("tab-active", t.dataset.tab === name));
  // Advanced tabs (Links, Parser) only show in the tab bar while they are open.
  $$(".tab[data-advanced-tab]").forEach(t => t.classList.toggle("hidden", t.dataset.tab !== name));
  $$("#ribbon [data-open-tab]").forEach(b => b.classList.toggle("rb-on", b.dataset.openTab === name));
  $$(".tab-pane").forEach(p => p.classList.toggle("hidden", p.id !== `tab-${name}`));
  if (name === "diagram") refreshDiagram();
  const spec = tabs.get(name);
  if (spec?.onShow) {
    try { spec.onShow(state.selected); } catch (e) { console.error(e); log(String(e), "error"); }
  }
  emit("tab-shown", name);
}

/* ---------- diagrams ---------- */

$$(".diag-mode").forEach(b => b.addEventListener("click", () => {
  $$(".diag-mode").forEach(x => x.classList.toggle("diag-active", x === b));
  state.diagramMode = b.dataset.mode;
  refreshDiagram();
}));

let mermaidSeq = 0;
async function refreshDiagram() {
  const target = state.selectedId || "";
  let kind = state.diagramMode;
  const params = new URLSearchParams({ kind });
  if (target) params.set("target", target);
  let r;
  try {
    r = await api("GET", `/api/diagram/mermaid?${params}`);
  } catch (e) {
    $("#diagram").textContent = String(e);
    return;
  }
  const id = `m${++mermaidSeq}`;
  const code = r.text || "%% empty diagram";
  $("#diagram").innerHTML = `<div class="mermaid" id="${id}">${escapeHtml(code)}</div>`;
  try {
    await window.mermaid.run({ nodes: [$(`#${id}`)] });
  } catch (e) {
    $("#diagram").innerHTML = `<pre class="text-red-600 text-xs whitespace-pre-wrap">${escapeHtml(String(e))}\n\n${escapeHtml(code)}</pre>`;
  }
}

async function downloadDiagramDot() {
  const target = state.selectedId || "";
  const params = new URLSearchParams({ kind: state.diagramMode });
  if (target) params.set("target", target);
  const r = await api("GET", `/api/diagram/dot?${params}`);
  download(`${state.diagramMode}.dot`, r.text);
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                       "\"": "&quot;", "'": "&#39;" }[m]));
}

/* ---------- links tab ---------- */

function renderLinksTab(links) {
  const tb = $("#links-tbody");
  tb.innerHTML = "";
  for (const l of links) {
    const tr = document.createElement("tr"); tr.className = "border-t";
    tr.innerHTML = `<td class="p-1"><span class="px-1.5 rounded bg-indigo-50 text-indigo-700 text-xs">«${l.kind}»</span></td>
                    <td class="p-1 font-mono text-xs">${l.source || ""}</td>
                    <td class="p-1 font-mono text-xs">${l.target || ""}</td>`;
    tb.appendChild(tr);
  }
}

/* ---------- validate ---------- */

async function doValidate() {
  const r = await api("GET", "/api/validate");
  log(`Validation: ${r.errors} error(s), ${r.warnings} warning(s)`,
      r.errors ? "error" : (r.warnings ? "warning" : "ok"));
  for (const i of r.issues) {
    log(`  [${i.severity}] ${i.rule}: ${i.message}  (${i.qualified_name})`, i.severity);
  }
}

/* ---------- modal helpers ---------- */

function modal(title, bodyHtml, onSubmit) {
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal">
        <h3>${title}</h3>
        <form id="modal-form" class="space-y-2">${bodyHtml}</form>
        <div class="actions">
          <button class="btn-secondary" data-modal-cancel>Cancel</button>
          <button class="btn-primary"   data-modal-submit>Submit</button>
        </div>
      </div>
    </div>`;
  const close = () => { root.innerHTML = ""; };
  root.querySelector("[data-modal-cancel]").onclick = close;
  root.querySelector("[data-modal-submit]").onclick = async () => {
    const fd = new FormData($("#modal-form"));
    const obj = Object.fromEntries(fd.entries());
    try { await onSubmit(obj); close(); }
    catch (e) { log(String(e), "error"); }
  };
}

// Styled replacement for window.prompt / window.confirm: resolves with the form's values,
// or null when cancelled (Cancel or Escape). Enter in a field submits.
function dialog(title, bodyHtml, { ok = "OK", danger = false } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    // Resolve after modal() has closed this dialog, so the caller may open the next one.
    modal(escapeHtml(title), bodyHtml, async (values) => { setTimeout(() => done(values), 0); });
    const root = $("#modal-root");
    const submit = root.querySelector("[data-modal-submit]");
    const cancel = root.querySelector("[data-modal-cancel]");
    submit.textContent = ok;
    submit.type = cancel.type = "button";
    if (danger) submit.classList.add("btn-danger");
    cancel.addEventListener("click", () => done(null));
    root.querySelector("#modal-form").addEventListener("submit", (e) => { e.preventDefault(); submit.click(); });
    root.querySelector(".modal").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); cancel.click(); }
    });
    const first = root.querySelector("#modal-form input, #modal-form select, #modal-form textarea");
    (first || submit).focus();
    first?.select?.();
  });
}

/* ---------- unsaved changes ---------- */
// Plugins report unsaved changes (e.g. the undo history): {check: async () => reason | null,
// saved: async () => {}}. New and Load warn before discarding them; Save JSON calls saved().
const unsavedChecks = [];
function registerUnsavedCheck(spec) { unsavedChecks.push(spec); }
async function unsavedReason() {
  for (const u of unsavedChecks) {
    try { const why = await u.check(); if (why) return why; } catch (e) { console.warn(e); }
  }
  return null;
}
async function markSaved() {
  for (const u of unsavedChecks) {
    try { await u.saved?.(); } catch (e) { console.warn(e); }
  }
  emit("project-saved", null);
}
function unsavedHtml(why, consequence) {
  return why ? `<p class="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-2" data-unsaved-warning>
    ${escapeHtml(why)}. ${escapeHtml(consequence)} Use <b>Save JSON</b> first to keep them.</p>` : "";
}

async function openLinkDialog() {
  const kinds = await api("GET", "/api/link_kinds");
  const opts = kinds.map(k => `<option value="${k.name}">${k.name} — ${k.description}</option>`).join("");
  modal("Create link", `
    <label class="block">Kind <select name="kind" class="input">${opts}</select></label>
    <label class="block">Source (qname or id) <input class="input" name="source" value="${state.selectedId || ''}" /></label>
    <label class="block">Target (qname or id) <input class="input" name="target" /></label>
  `, async (o) => {
    await api("POST", "/api/link", o);
    log(`Linked «${o.kind}»`, "ok");
    if (state.selectedId) await selectElement(state.selectedId);
    refreshDiagram();
  });
}

function openStereotypeDialog() {
  modal("Define stereotype", `
    <label class="block">Name <input class="input" name="name" /></label>
    <label class="block">Applies to (comma kinds, optional)
      <input class="input" name="applies_to" placeholder="PartDefinition, RequirementDefinition" />
    </label>
    <label class="block">Tags (comma names, optional)
      <input class="input" name="tags" placeholder="asilLevel, priority" />
    </label>
  `, async (o) => {
    const body = { name: o.name };
    if (o.applies_to) body.applies_to = o.applies_to.split(",").map(s => s.trim()).filter(Boolean);
    if (o.tags) body.tags = o.tags.split(",").map(s => ({ name: s.trim() })).filter(t => t.name);
    await api("POST", "/api/stereotype/define", body);
    log(`Defined stereotype «${o.name}»`, "ok");
    await refreshTree();
  });
}

function openApplyStereotypeDialog() {
  modal("Apply stereotype", `
    <label class="block">Stereotype qname <input class="input" name="stereotype" /></label>
    <label class="block">Target qname <input class="input" name="target" value="${state.selectedId || ''}" /></label>
    <label class="block">Values (JSON object, optional)
      <input class="input" name="values" placeholder='{"asilLevel": "D"}' />
    </label>
  `, async (o) => {
    const body = { stereotype: o.stereotype, target: o.target };
    if (o.values) body.values = JSON.parse(o.values);
    await api("POST", "/api/stereotype/apply", body);
    log(`Applied «${o.stereotype}» to ${o.target}`, "ok");
    await refreshTree();
  });
}

function openSMAttachDialog() {
  modal("Attach state machine", `
    <label class="block">Part qname <input class="input" name="part" value="${state.selectedId || ''}" /></label>
    <label class="block">State machine name <input class="input" name="name" value="SM" /></label>
  `, async (o) => {
    await api("POST", "/api/sm/attach", o);
    log(`Attached state machine ${o.name}`, "ok");
    await refreshTree();
  });
}

function openSMStateDialog() {
  modal("Add state", `
    <label class="block">State machine qname <input class="input" name="state_machine" value="${state.selectedId || ''}" /></label>
    <label class="block">State name <input class="input" name="name" /></label>
    <label class="block">Entry action <input class="input" name="entry" /></label>
    <label class="block">Do action <input class="input" name="do" /></label>
    <label class="block">Exit action <input class="input" name="exit" /></label>
    <label class="inline-flex items-center gap-1"><input type="checkbox" name="is_initial"/> initial</label>
    <label class="inline-flex items-center gap-1 ml-3"><input type="checkbox" name="is_final"/> final</label>
  `, async (o) => {
    o.is_initial = o.is_initial === "on"; o.is_final = o.is_final === "on";
    await api("POST", "/api/sm/state", o);
    log(`Added state ${o.name}`, "ok");
    await refreshTree(); refreshDiagram();
  });
}

function openSMTransitionDialog() {
  modal("Add transition", `
    <label class="block">State machine qname <input class="input" name="state_machine" value="${state.selectedId || ''}" /></label>
    <label class="block">Source state <input class="input" name="source" /></label>
    <label class="block">Target state <input class="input" name="target" /></label>
    <label class="block">Trigger <input class="input" name="trigger" /></label>
    <label class="block">Guard (Python expression over payload) <input class="input" name="guard" /></label>
    <label class="block">Effect <input class="input" name="effect" /></label>
  `, async (o) => {
    await api("POST", "/api/sm/transition", o);
    log(`Transition ${o.source}→${o.target} on ${o.trigger || '∅'}`, "ok");
    await refreshTree(); refreshDiagram();
  });
}

function openSMFireDialog() {
  modal("Fire event", `
    <label class="block">State machine qname <input class="input" name="state_machine" value="${state.selectedId || ''}" /></label>
    <label class="block">Event <input class="input" name="event" /></label>
    <label class="block">Payload (JSON, optional) <input class="input" name="payload" placeholder='{"speed":0}' /></label>
  `, async (o) => {
    const body = { state_machine: o.state_machine, event: o.event };
    if (o.payload) body.payload = JSON.parse(o.payload);
    const r = await api("POST", "/api/sm/fire", body);
    if (r.transitioned_to)
      log(`event '${o.event}' → ${r.transitioned_to}`, "ok");
    else
      log(`event '${o.event}' — no transition (still in ${r.current || '?'})`, "warning");
    refreshDiagram();
  });
}

/* ---------- file IO helpers ---------- */

function download(name, text) {
  const blob = new Blob([text], { type: "application/octet-stream" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
}

function openFile(accept, onText) {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = accept;
  inp.onchange = async () => {
    const f = inp.files?.[0]; if (!f) return;
    onText(await f.text());
  };
  inp.click();
}

/* ---------- keyboard shortcuts ---------- */

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea, select")) return;
  if (e.key === "F5") { e.preventDefault(); doValidate(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "l") { e.preventDefault(); openLinkDialog(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "e") { e.preventDefault(); openSMFireDialog(); }
  else if (e.key === "Delete" && state.selectedId) {
    document.querySelector('[data-cmd="delete-element"]')?.click();
  }
  else {
    for (const sc of shortcuts) {
      if (e.key.toLowerCase() === sc.key.toLowerCase() && !!sc.ctrl === (e.ctrlKey || e.metaKey)
          && !!sc.shift === e.shiftKey && !!sc.alt === e.altKey) {
        e.preventDefault(); sc.handler(e); break;
      }
    }
  }
});

/* ---------- plugin API ---------- */
//
// Frontend plugins are ES modules in webapp/static/plugins/*.js, loaded in
// file-name order. Each default-exports `function install(studio) {...}`.

function registerTab({ id, title, order = 100, mount, onShow }) {
  if (tabs.has(id)) throw new Error(`tab ${id} already registered`);
  tabs.set(id, { id, title, order, mount, onShow });
  const btn = document.createElement("button");
  btn.className = "tab"; btn.dataset.tab = id; btn.dataset.order = order; btn.textContent = title;
  const bar = $("#tab-bar");
  const after = [...bar.children].find(b => Number(b.dataset.order ?? 0) > order);
  bar.insertBefore(btn, after || null);
  const pane = document.createElement("div");
  pane.id = `tab-${id}`;
  pane.className = "tab-pane absolute inset-0 hidden flex-col overflow-hidden";
  $("#tab-panes").appendChild(pane);
  mount?.(pane);
  return pane;
}

/* ---------- toolstrip (ribbon) ---------- */
//
// The toolstrip is organised by task, like System Composer's: Modeling, Views,
// Requirements, Analysis, Interop, Advanced. A plugin button goes into the section of its
// `group` (or the `section` it names); each group is a cluster inside its section.

const RIBBON_SECTION_OF_GROUP = {
  Edit: "modeling", Model: "modeling", Interfaces: "modeling", Profiles: "modeling",
  Allocation: "modeling", Views: "views", View: "views", Requirements: "requirements",
  Analysis: "analysis", Interop: "interop", Advanced: "advanced",
};

// Buttons that open the editors (tabs) of the features, added once the plugins loaded.
const RIBBON_EDITORS = [
  { section: "modeling", group: "Allocation", tab: "allocation", label: "Allocation",
    title: "Allocate functions to components and hardware (Allocation tab)" },
  { section: "views", group: "Views", tab: "architecture", label: "Canvas", title: "Architecture canvas" },
  { section: "views", group: "Views", tab: "diagram", label: "Diagrams", title: "BDD, IBD, requirements and state machine diagrams" },
  { section: "requirements", group: "Requirements", tab: "requirements", label: "Requirements", first: true,
    title: "Requirement sets, requirements, links and test cases" },
  { section: "requirements", group: "Requirements", tab: "traceability", label: "Traceability",
    title: "Traceability matrix and diagram" },
  { section: "analysis", group: "Analysis", tab: "checks", label: "Model Check", title: "Model Check: validator and advisor checks" },
  { section: "interop", group: "Interop", tab: "interop", label: "Import / Export",
    title: "Model tables, SysML text, XMI, reports" },
  { section: "interop", group: "Interop", tab: "compare", label: "Compare", title: "Compare and merge models" },
];

function ribbonGroup(section, group) {
  const sec = $(`#ribbon [data-section="${section}"]`) || $('#ribbon [data-section="modeling"]');
  const tools = sec.querySelector(".rb-tools");
  let grp = [...tools.querySelectorAll(":scope > .rb-group")].find(g => g.dataset.group === group);
  if (!grp) {
    grp = document.createElement("span");
    grp.className = "rb-group";
    grp.dataset.group = group;
    tools.appendChild(grp);
  }
  return grp;
}

function registerToolbarButton({ id, label, title = "", group = "", section = "", onClick }) {
  const grp = ribbonGroup(section || RIBBON_SECTION_OF_GROUP[group] || "modeling", group || "Other");
  const btn = document.createElement("button");
  btn.className = "btn-action"; btn.textContent = label; btn.title = title;
  if (id) btn.dataset.pluginButton = id;
  btn.addEventListener("click", (e) => { e.stopPropagation(); onClick(e); });
  grp.appendChild(btn);
  return btn;
}

function addEditorButtons() {
  for (const ed of RIBBON_EDITORS) {
    if (!tabs.has(ed.tab) && !$(`.tab[data-tab="${ed.tab}"]`)) continue;
    const grp = ribbonGroup(ed.section, ed.group);
    const btn = document.createElement("button");
    btn.className = "btn-action"; btn.textContent = ed.label; btn.title = ed.title;
    btn.dataset.openTab = ed.tab;
    btn.addEventListener("click", (e) => { e.stopPropagation(); closeMenus(); switchTab(ed.tab); });
    if (ed.first) grp.prepend(btn); else grp.appendChild(btn);
  }
  $$("#ribbon [data-open-tab]").forEach(b => b.classList.toggle("rb-on", b.dataset.openTab === state.tab));
}

function closeMenus(except = null) {
  for (const m of $$("#advanced-menu, #export-menu")) {
    if (m !== except) m.classList.add("hidden");
  }
  $('[data-cmd="advanced-menu"]')?.setAttribute("aria-expanded", except?.id === "advanced-menu" ? "true" : "false");
}

// Ribbon commands (the header's File commands are handled above).
document.addEventListener("click", (e) => {
  const el = e.target.closest?.("[data-cmd]");
  const cmd = el?.dataset.cmd;
  if (cmd === "advanced-menu") {
    const menu = $("#advanced-menu");
    const open = menu.classList.contains("hidden");
    closeMenus(open ? menu : null);
    menu.classList.toggle("hidden", !open);
    if (open) menu.querySelector("button:not([hidden])")?.focus();
    return;
  }
  if (cmd === "toggle-log") { setLogCollapsed(!logCollapsed()); return; }
  if (cmd === "show-tab") { closeMenus(); switchTab(el.dataset.showTab); return; }
  // Any other click closes the menus (a menu item runs its command first).
  if (cmd !== "export-menu" && !e.target.closest?.("#advanced-menu .rb-menu-h")) closeMenus();
});
$("#advanced-menu").addEventListener("keydown", (e) => {
  const items = [...$("#advanced-menu").querySelectorAll("button")].filter(b => b.offsetParent);
  const i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); closeMenus(); $('[data-cmd="advanced-menu"]').focus(); }
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
  }
});

function registerInspectorSection({ id, title, order = 100, render }) {
  inspectorSections.push({ id, title, order, render });
}

function registerTreeBadge(fn) { treeBadges.push(fn); }

function registerShortcut({ key, ctrl = false, shift = false, alt = false, handler }) {
  shortcuts.push({ key, ctrl, shift, alt, handler });
}

function getSelection() {
  return state.selection.length ? [...state.selection] : (state.selectedId ? [state.selectedId] : []);
}
function setSelection(ids) {
  state.selection = [...ids];
  emit("selection-changed", getSelection());
}

// Cross-feature events (any plugin may emit or listen):
//   navigate  {id}                      show an element: tree + inspector select it, canvas opens its parent
//   highlight {ids, color?, reason?}    emphasize elements on the canvas; null clears
//   canvas-filter {ids, label?}         canvas shows only these components (views); null clears
//   selection-changed [ids]             multi-selection changed
on("navigate", ({ id }) => { if (id) selectSingle(id); });

const studio = {
  // data + backend
  api, state,
  get selected() { return state.selected; },
  getSelection, setSelection,
  refreshTree, selectElement, switchTab, refreshDiagram,
  // events: "select" (element summary), "model-changed" (tree), "tab-shown" (tab id),
  //         "element-changed" ({revision, selected}: the model changed without a tree refresh)
  on, emit,
  // UI helpers
  log, setStatus, escapeHtml, modal, dialog, download, openFile,
  // unsaved changes: plugins report them; New / Load warn
  registerUnsavedCheck, unsavedReason, unsavedHtml, markSaved,
  // registries
  registerTab, registerToolbarButton, registerInspectorSection, registerTreeBadge, registerShortcut,
};
window.studio = studio;

async function loadPlugins() {
  let urls = [];
  try { urls = await api("GET", "/api/plugins"); } catch { return; }
  for (const url of urls) {
    try {
      const mod = await import(url);
      await mod.default?.(studio);
    } catch (e) {
      console.error(e);
      log(`Plugin ${url} failed to load: ${e}`, "error");
    }
  }
}

/* ---------- boot ---------- */

(async () => {
  await loadPlugins();
  addEditorButtons();
  try { await refreshTree(); } catch (e) { log(String(e), "error"); }
  log("SysML v2 Studio ready.", "ok");
})();
