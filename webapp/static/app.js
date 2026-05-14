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
};

/* ---------- API ---------- */

async function api(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!resp.ok) {
    log(`${resp.status} ${method} ${path}: ${data?.error || text}`, "error");
    throw new Error(data?.error || text);
  }
  return data;
}

/* ---------- log + status ---------- */

function log(msg, severity = "info") {
  const pre = $("#log");
  const line = document.createElement("span");
  line.className = `log-${severity}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  pre.appendChild(line);
  pre.scrollTop = pre.scrollHeight;
}

function setStatus(text) { $("#status").textContent = text; }

/* ---------- tree ---------- */

async function refreshTree() {
  const tree = await api("GET", "/api/tree");
  const state_info = await api("GET", "/api/state");
  $("#project-name").textContent = `${state_info.name}  ·  ${state_info.element_count} elements`;
  state.treeIndex.clear();
  $("#tree").innerHTML = "";
  $("#tree").appendChild(renderTreeNode(tree, 0));
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
  const k = document.createElement("span"); k.className = "kind"; k.textContent = node.kind;
  row.appendChild(k);

  row.addEventListener("click", () => selectElement(node.id));

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
  fillProperties(el);
  renderLinksTab(el.links || []);
  if (state.tab === "diagram") refreshDiagram();
  setStatus(`${el.kind}  ${el.qualified_name}`);
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
  const name = prompt(`Name for the new ${kind}?`, kind.replace("Definition", "").replace("Usage", ""));
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
    const name = prompt("Project name?", "UntitledProject"); if (!name) return;
    await api("POST", "/api/new", { name });
    state.selectedId = null;
    await refreshTree(); log(`New project ${name}`, "ok");
  }
  else if (cmd === "save") {
    const r = await api("GET", "/api/save");
    download("project.json", r.text);
    log("Saved project.json", "ok");
  }
  else if (cmd === "load")          openFile("application/json", async (t) => {
    await api("POST", "/api/load", { text: t });
    state.selectedId = null; await refreshTree();
    log("Loaded project", "ok");
  });
  else if (cmd === "import-sysml")  openFile(".sysml,.kerml,text/plain", async (t) => {
    await api("POST", "/api/parse", { source: t });
    await refreshTree(); log("Imported .sysml", "ok");
  });
  else if (cmd === "validate")      doValidate();
  else if (cmd === "export-menu")   $("#export-menu").classList.toggle("hidden");
  else if (cmd === "clear-log")     $("#log").textContent = "";
  else if (cmd === "delete-element") {
    if (!state.selectedId) return;
    if (!confirm("Delete this element and its descendants?")) return;
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

$$(".tab").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.tab)));
function switchTab(name) {
  state.tab = name;
  $$(".tab").forEach(t => t.classList.toggle("tab-active", t.dataset.tab === name));
  $$(".tab-pane").forEach(p => p.classList.toggle("hidden", p.id !== `tab-${name}`));
  if (name === "diagram") refreshDiagram();
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
});

/* ---------- boot ---------- */

refreshTree().catch(e => log(String(e), "error"));
log("SysML v2 Studio ready.", "ok");
