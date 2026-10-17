// "Architecture" inspector section: edit a composition (architecture or component),
// a port or a connector by clicking — components, boundary ports, connectors,
// duplicate, create-component-from-selection, expand, save as reference, inline,
// arrange. Everything goes through /api/arch/* (see docs/features/architecture.md).
import {
  DIRECTIONS, INTERFACE_KINDS, esc, injectStyles, isComponent, isComposition,
  openForm, options, reload, treeNodes,
} from "./common.js";

export function installInspector(studio) {
  injectStyles();
  studio.registerInspectorSection({
    id: "architecture", title: "Architecture", order: 10,
    render(el, box) {
      if (isComposition(el)) { renderComposition(studio, el, box); return undefined; }
      if (el.kind === "PortUsage") { renderPort(studio, el, box); return undefined; }
      if (el.kind === "ConnectionUsage" && (el.end_ids || []).length) {
        renderConnector(studio, el, box); return undefined;
      }
      return false;
    },
  });
}

function interfaceOptions(studio, selectedId) {
  const items = treeNodes(studio, INTERFACE_KINDS).map(n => [n.id, `${n.name} (${n.kind.replace("Definition", "")})`]);
  return options(items, selectedId || "", { empty: "— none —" });
}

function interfaceIdOf(studio, port) {
  if (port.interface) return port.interface.id;
  const qn = (port.typed_by || [])[0];
  if (!qn) return "";
  const hit = [...studio.state.treeIndex.values()].find(n => n.qualified_name === qn);
  return hit ? hit.id : "";
}

function kindChoices(allowed, current) {
  const list = [...allowed];
  if (current && !list.includes(current)) list.push(current);
  return list.map(k => [k, k]);
}

async function guarded(studio, fn, after) {
  try {
    await fn();
  } catch (e) {
    /* studio.api already logged the server's message */
  }
  if (after) await after();
}

function portRows(studio, ports, allowed) {
  if (!ports.length) return `<tr><td colspan="5" class="text-slate-400 italic">No ports</td></tr>`;
  return ports.map(p => `
    <tr data-port-row="${esc(p.id)}">
      <td><input class="input" aria-label="Port name" data-port-name="${esc(p.id)}" value="${esc(p.name)}" /></td>
      <td><select class="input" aria-label="Direction" data-port-dir="${esc(p.id)}" ${p.kind !== "data" ? "disabled" : ""}>
            ${options(DIRECTIONS.map(d => [d, d]), p.direction)}</select></td>
      <td><select class="input" aria-label="Kind" data-port-kind="${esc(p.id)}">
            ${options(kindChoices(allowed, p.kind), p.kind)}</select></td>
      <td><select class="input" aria-label="Interface" data-port-iface="${esc(p.id)}">
            ${interfaceOptions(studio, interfaceIdOf(studio, p))}</select></td>
      <td class="text-right whitespace-nowrap">
        ${p.on_definition ? `<span class="tree-badge" title="Defined on the referenced definition">def</span>` : ""}
        <button type="button" class="arch-x" title="Delete port" data-del="${esc(p.id)}">×</button></td>
    </tr>`).join("");
}

function endpointLabel(v, ep) {
  if (!ep) return "?";
  if (!ep.component_id) {
    const b = v.boundary_ports.find(p => p.id === ep.port_id);
    return `${esc(b ? b.name : "?")} <span class="text-slate-400">(boundary)</span>`;
  }
  const c = v.components.find(x => x.id === ep.component_id);
  const p = c?.ports.find(x => x.id === ep.port_id);
  return `${esc(c ? c.name : "?")}${p ? "." + esc(p.name) : ""}`;
}

function endpoints(v) {
  const out = v.boundary_ports.map(p => [`|${p.id}`, `${p.name} (boundary ${p.kind === "data" ? p.direction : p.kind})`]);
  for (const c of v.components) {
    for (const p of c.ports) out.push([`${c.id}|${p.id}`, `${c.name}.${p.name} (${p.kind === "data" ? p.direction : p.kind})`]);
  }
  return out;
}

async function renderComposition(studio, el, box) {
  box.innerHTML = `<div class="text-xs text-slate-400">Loading architecture…</div>`;
  let v;
  try { v = await studio.api("GET", `/api/arch/view/${el.id}`); } catch { box.innerHTML = ""; return; }
  if (!box.isConnected) return;
  const comp = v.composition;
  const component = isComponent(el);
  const crumbs = comp.breadcrumbs.map((c, i) => i === comp.breadcrumbs.length - 1
    ? `<b>${esc(c.name)}</b>`
    : `<button type="button" data-goto="${esc(c.id)}">${esc(c.name)}</button>`).join(" › ");
  const eps = endpoints(v);
  const comps = v.components.map(c => `
    <tr>
      <td class="w-6"><input type="checkbox" aria-label="Select ${esc(c.name)}" data-pick="${esc(c.id)}" /></td>
      <td><input class="input" aria-label="Component name" data-rename="${esc(c.id)}" value="${esc(c.name)}" /></td>
      <td class="text-xs">${c.definition ? `<button type="button" class="text-blue-700 hover:underline" data-goto="${esc(c.definition.id)}">${esc(c.definition.name)}</button>` : `<span class="text-slate-400">inline</span>`}</td>
      <td class="text-xs">${c.ports.length}</td>
      <td class="text-xs">${(c.badges || []).map(b => `<span class="tree-badge">${esc(b)}</span>`).join("")}</td>
      <td class="text-right"><button type="button" class="btn-action" data-goto="${esc(c.id)}" title="Open ${esc(c.name)}">Open</button></td>
    </tr>`).join("") || `<tr><td colspan="6" class="text-slate-400 italic">No components yet — use “+ Component”.</td></tr>`;
  const conns = v.connectors.map(c => `
    <tr>
      <td>${endpointLabel(v, c.source)}</td>
      <td class="text-slate-400">→</td>
      <td>${endpointLabel(v, c.target)}</td>
      <td class="text-xs">${esc(c.kind)}${c.interfaces.length ? ` · ${esc(c.interfaces.join(", "))}` : ""}
        ${c.issues.map(i => `<div class="arch-pill warn" title="${esc(i)}">${esc(i)}</div>`).join("")}</td>
      <td class="text-right"><button type="button" class="arch-x" title="Delete connector" data-del="${esc(c.id)}">×</button></td>
    </tr>`).join("") || `<tr><td colspan="5" class="text-slate-400 italic">No connectors</td></tr>`;

  box.innerHTML = `
    <div class="arch-crumbs text-xs mb-1" aria-label="Breadcrumbs">${crumbs}</div>
    <div class="flex flex-wrap gap-1 items-center text-xs mb-2">
      <span class="arch-pill" title="Architecture model type">${esc(v.model_type)}</span>
      ${comp.is_reference ? `<span>references <button type="button" class="text-blue-700 hover:underline" data-goto="${esc(comp.definition.id)}">${esc(comp.definition.name)}</button>
        — internals are shared by ${comp.shared_by} component(s)</span>` : ""}
    </div>
    <div class="arch-strip" role="toolbar" aria-label="Architecture tools">
      <button type="button" class="btn-action" data-act="add-component" title="Add a component inside ${esc(comp.name)}">+ Component</button>
      <button type="button" class="btn-action" data-act="add-port" title="Add a port to ${esc(comp.name)}">+ Port</button>
      <button type="button" class="btn-action" data-act="connect" ${eps.length < 2 ? "disabled" : ""} title="Connect two ports">Connect…</button>
      <button type="button" class="btn-action" data-act="arrange" ${v.components.length ? "" : "disabled"} title="Arrange left to right by signal flow">Arrange</button>
      ${component ? `<span class="sep"></span>
        <button type="button" class="btn-action" data-act="duplicate" title="Copy with ports and internals">Duplicate</button>
        ${comp.is_reference
          ? `<button type="button" class="btn-action" data-act="inline" title="Copy the definition into this component only">Inline</button>`
          : `<button type="button" class="btn-action" data-act="save-ref" title="Make a reusable definition">Save as reference…</button>`}
        ${!comp.is_reference && v.components.length ? `<button type="button" class="btn-action" data-act="expand" title="Move the sub-components up one level">Expand</button>` : ""}
        <button type="button" class="btn-action" data-act="delete" title="Delete this component">Delete</button>` : ""}
    </div>
    <div class="arch-h">Components (${v.components.length})</div>
    <table class="arch-table" data-table="components">
      <thead><tr><th></th><th>Name</th><th>Reference</th><th>Ports</th><th>Badges</th><th></th></tr></thead>
      <tbody>${comps}</tbody>
    </table>
    <div class="flex gap-1 mt-1">
      <button type="button" class="btn-action" data-act="group" disabled title="Create Component from Selection">Group selected…</button>
      <button type="button" class="btn-action" data-act="duplicate-selected" disabled>Duplicate selected</button>
      <button type="button" class="btn-action" data-act="delete-selected" disabled>Delete selected</button>
    </div>
    <div class="arch-h">Ports of ${esc(comp.name)} <span class="font-normal text-slate-400">(boundary ports when viewing its inside)</span></div>
    <table class="arch-table" data-table="ports">
      <thead><tr><th>Name</th><th>Direction</th><th>Kind</th><th>Interface</th><th></th></tr></thead>
      <tbody>${portRows(studio, v.boundary_ports, v.allowed_port_kinds)}</tbody>
    </table>
    <div class="arch-h">Connectors (${v.connectors.length})</div>
    <table class="arch-table" data-table="connectors">
      <thead><tr><th>Source</th><th></th><th>Target</th><th>Kind</th><th></th></tr></thead>
      <tbody>${conns}</tbody>
    </table>`;

  const again = () => reload(studio, el.id);
  const picked = () => [...box.querySelectorAll("[data-pick]:checked")].map(x => x.dataset.pick);

  box.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.pick !== undefined) {
      const ids = picked();
      studio.setSelection(ids);
      for (const act of ["group", "duplicate-selected", "delete-selected"]) {
        box.querySelector(`[data-act="${act}"]`).disabled = !ids.length;
      }
    } else if (t.dataset.rename) {
      guarded(studio, async () => {
        await studio.api("PATCH", `/api/arch/component/${t.dataset.rename}`, { name: t.value.trim() });
        studio.log(`Renamed component to ${t.value.trim()}`, "ok");
      }, again);
    } else {
      portChange(studio, t, again);
    }
  });

  box.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t || t.disabled) return;
    if (t.dataset.goto) { studio.emit("navigate", { id: t.dataset.goto }); return; }
    if (t.dataset.del) {
      guarded(studio, () => studio.api("POST", "/api/arch/delete", { ids: [t.dataset.del] }), again);
      return;
    }
    const act = t.dataset.act;
    if (act === "add-component") addComponent(studio, el, comp);
    else if (act === "add-port") addPort(studio, el, v.allowed_port_kinds);
    else if (act === "connect") connect(studio, el, eps);
    else if (act === "arrange") {
      guarded(studio, async () => {
        await studio.api("POST", "/api/arch/auto-layout", { composition: el.id });
        studio.log(`Arranged ${comp.name}`, "ok");
      }, again);
    }
    else if (act === "duplicate" || act === "duplicate-selected") {
      const ids = act === "duplicate" ? [el.id] : picked();
      guarded(studio, async () => {
        const r = await studio.api("POST", "/api/arch/duplicate", { ids });
        studio.log(`Duplicated as ${r.components.map(c => c.name).join(", ")}`, "ok");
        await reload(studio, act === "duplicate" ? r.components[0].id : el.id);
      });
    }
    else if (act === "save-ref") saveAsReference(studio, el);
    else if (act === "inline") {
      guarded(studio, async () => {
        await studio.api("POST", "/api/arch/inline", { component: el.id });
        studio.log(`${el.name} is now an inline component`, "ok");
      }, again);
    }
    else if (act === "expand") {
      guarded(studio, async () => {
        await studio.api("POST", "/api/arch/expand", { component: el.id });
        studio.log(`Expanded ${el.name}`, "ok");
        await reload(studio, el.owner_id);
      });
    }
    else if (act === "delete") confirmDelete(studio, [el.id], `component ${el.name}`, el.owner_id);
    else if (act === "delete-selected") confirmDelete(studio, picked(), `${picked().length} component(s)`, el.id);
    else if (act === "group") group(studio, el, picked());
  });
}

function portChange(studio, t, after) {
  let id, body;
  if (t.dataset.portName) { id = t.dataset.portName; body = { name: t.value.trim() }; }
  else if (t.dataset.portDir) { id = t.dataset.portDir; body = { direction: t.value }; }
  else if (t.dataset.portKind) { id = t.dataset.portKind; body = { kind: t.value }; }
  else if (t.dataset.portIface !== undefined && t.matches("[data-port-iface]")) {
    id = t.dataset.portIface; body = { interface: t.value || null };
  } else return;
  guarded(studio, async () => {
    await studio.api("PATCH", `/api/arch/port/${id}`, body);
    studio.log(`Updated port ${Object.keys(body)[0]}`, "ok");
  }, after);
}

function addComponent(studio, el, comp) {
  const defs = treeNodes(studio, ["PartDefinition"]).filter(n => n.id !== el.id && n.id !== comp.definition?.id)
    .map(n => [n.id, n.qualified_name]);
  openForm(studio, `Add component to ${el.name}`, `
    <label class="block text-sm">Name <span class="text-slate-400">(empty: Component, Component1, …)</span>
      <input class="input" name="name" autocomplete="off" /></label>
    <label class="block text-sm">Reference
      <select class="input" name="definition">${options(defs, "", { empty: "— inline component —" })}</select></label>
  `, async (v) => {
    const c = await studio.api("POST", "/api/arch/component", {
      composition: el.id, name: v.name?.trim() || undefined, definition: v.definition || undefined });
    studio.log(`Added component ${c.name}`, "ok");
    await reload(studio, el.id);
  });
}

function addPort(studio, el, allowed) {
  openForm(studio, `Add port to ${el.name}`, `
    <label class="block text-sm">Name <span class="text-slate-400">(empty: In, Out, …)</span>
      <input class="input" name="name" autocomplete="off" /></label>
    <div class="grid grid-cols-2 gap-2">
      <label class="block text-sm">Direction
        <select class="input" name="direction">${options(DIRECTIONS.map(d => [d, d]), "in")}</select></label>
      <label class="block text-sm">Kind
        <select class="input" name="kind">${options(allowed.map(k => [k, k]), "data")}</select></label>
    </div>
    <label class="block text-sm">Interface
      <select class="input" name="interface">${interfaceOptions(studio, "")}</select></label>
    <label class="inline-flex items-center gap-1 text-sm">
      <input type="checkbox" name="usage_only" /> Only on this component (not on its referenced definition)</label>
  `, async (v) => {
    const p = await studio.api("POST", "/api/arch/port", {
      owner: el.id, name: v.name?.trim() || undefined, direction: v.direction, kind: v.kind,
      interface: v.interface || undefined, usage_only: v.usage_only === "on" });
    studio.log(`Added ${p.kind} port ${p.name}`, "ok");
    await reload(studio, el.id);
  });
}

function connect(studio, el, eps) {
  openForm(studio, `Connect ports in ${el.name}`, `
    <label class="block text-sm">From
      <select class="input" name="source">${options(eps, eps[0]?.[0])}</select></label>
    <label class="block text-sm">To
      <select class="input" name="target">${options(eps, eps[1]?.[0])}</select></label>
    <label class="block text-sm">Name <span class="text-slate-400">(optional)</span>
      <input class="input" name="name" autocomplete="off" /></label>
    <p class="text-xs text-slate-500">Data flows from an output to an input (a boundary input feeds the inside);
      the direction is fixed automatically. Physical ports connect to physical ports, clients to servers.</p>
  `, async (v) => {
    const [sc, sp] = v.source.split("|");
    const [tc, tp] = v.target.split("|");
    const c = await studio.api("POST", "/api/arch/connector", {
      composition: el.id, name: v.name?.trim() || undefined,
      source: { component: sc || null, port: sp }, target: { component: tc || null, port: tp } });
    studio.log(`Connected (${c.kind}) ${c.name}`, "ok");
    await reload(studio, el.id);
  });
}

function saveAsReference(studio, el) {
  const base = (el.name || "Component").replace(/^./, ch => ch.toUpperCase());
  openForm(studio, `Save ${el.name} as reference`, `
    <label class="block text-sm">Definition name
      <input class="input" name="name" value="${esc(base)}" /></label>
    <p class="text-xs text-slate-500">The component's ports and internals move into a new part definition that
      other components can reference; this component becomes a reference to it.</p>
  `, async (v) => {
    const r = await studio.api("POST", "/api/arch/save-as-reference", { component: el.id, name: v.name?.trim() || undefined });
    studio.log(`Saved ${el.name} as reference ${r.definition.name}`, "ok");
    await reload(studio, el.id);
  });
}

function group(studio, el, ids) {
  openForm(studio, "Create component from selection", `
    <label class="block text-sm">New component name <span class="text-slate-400">(optional)</span>
      <input class="input" name="name" autocomplete="off" /></label>
    <p class="text-xs text-slate-500">${ids.length} component(s) move into a new component; connectors that cross
      the selection are routed through new ports.</p>
  `, async (v) => {
    const g = await studio.api("POST", "/api/arch/group", {
      composition: el.id, component_ids: ids, name: v.name?.trim() || undefined });
    studio.log(`Created ${g.name} from ${ids.length} component(s)`, "ok");
    studio.setSelection([]);
    await reload(studio, el.id);
  });
}

function confirmDelete(studio, ids, what, selectAfter) {
  openForm(studio, "Delete", `<p class="text-sm">Delete ${esc(what)} and the connectors attached to it?
    You can undo with Ctrl+Z.</p>`, async () => {
    await studio.api("POST", "/api/arch/delete", { ids });
    studio.log(`Deleted ${what}`, "warning");
    studio.setSelection([]);
    await reload(studio, selectAfter);
  });
}

async function renderPort(studio, el, box) {
  let t;
  try { t = await studio.api("GET", "/api/arch/model-type"); } catch { return; }
  if (!box.isConnected) return;
  const kind = el.port_kind || "data";
  box.innerHTML = `
    <div class="grid grid-cols-[110px_1fr] gap-2 items-center text-sm">
      <label for="arch-port-dir">Direction</label>
      <select id="arch-port-dir" class="input" data-port-dir="${esc(el.id)}" ${kind !== "data" ? "disabled" : ""}>
        ${options(DIRECTIONS.map(d => [d, d]), el.direction === "none" ? "in" : el.direction)}</select>
      <label for="arch-port-kind">Kind</label>
      <select id="arch-port-kind" class="input" data-port-kind="${esc(el.id)}">
        ${options(kindChoices(t.allowed_port_kinds, kind), kind)}</select>
      <label for="arch-port-iface">Interface</label>
      <select id="arch-port-iface" class="input" data-port-iface="${esc(el.id)}">
        ${interfaceOptions(studio, interfaceIdOf(studio, el))}</select>
    </div>
    <p class="text-xs text-slate-500 mt-2">Port of <button type="button" class="text-blue-700 hover:underline"
      data-goto="${esc(el.owner_id)}">${esc((el.qualified_name || "").split("::").slice(-2, -1)[0] || "owner")}</button>.
      Changes that would break existing connectors are refused.</p>`;
  box.addEventListener("change", e => portChange(studio, e.target, () => reload(studio, el.id)));
  box.addEventListener("click", e => {
    const b = e.target.closest("[data-goto]");
    if (b) studio.emit("navigate", { id: b.dataset.goto });
  });
}

async function renderConnector(studio, el, box) {
  if (!isComposition(studio.state.treeIndex.get(el.owner_id))) { box.closest("section")?.remove(); return; }
  let v = null;
  try { v = await studio.api("GET", `/api/arch/view/${el.owner_id}`); } catch { /* not an architecture */ }
  if (!box.isConnected) return;
  const c = v?.connectors.find(x => x.id === el.id);
  if (!c) { box.closest("section")?.remove(); return; }
  box.innerHTML = `
    <div class="text-sm">${endpointLabel(v, c.source)} <span class="text-slate-400">→</span> ${endpointLabel(v, c.target)}</div>
    <div class="text-xs text-slate-500 mt-1">${esc(c.kind)} connector in
      <button type="button" class="text-blue-700 hover:underline" data-goto="${esc(el.owner_id)}">${esc(v.composition.name)}</button>
      ${c.interfaces.length ? ` · interface ${esc(c.interfaces.join(", "))}` : ""}</div>
    ${c.issues.map(i => `<div class="arch-pill warn mt-1">${esc(i)}</div>`).join("")}
    <div class="mt-2"><button type="button" class="btn-action" data-act="delete-connector">Delete connector</button></div>`;
  box.addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.goto) studio.emit("navigate", { id: b.dataset.goto });
    else if (b.dataset.act === "delete-connector") {
      guarded(studio, async () => {
        await studio.api("POST", "/api/arch/delete", { ids: [el.id] });
        studio.log("Deleted connector", "warning");
        await reload(studio, el.owner_id);
      });
    }
  });
}

