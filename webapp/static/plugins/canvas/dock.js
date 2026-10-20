// Property Inspector docked at the right of the canvas (System Composer style): edits the
// selected component, port or connector, or summarizes the composition being viewed.
// Reads the editor's view model; every change goes through the editor's actions.
import { DIRECTIONS, esc, interfaceChoices, options, treeNodes } from "./common.js";
import { StereoSection } from "./stereo.js";
import { icon } from "./toolstrip.js";

// Where the editable Stereotypes section (stereo.js) goes in a body; it is kept in the DOM
// while the rest of the dock is redrawn around it.
const STEREO = "<!--stereotypes-->";

const SIDES = ["left", "right", "top", "bottom"];

function interfaceOptions(studio, selectedId) {
  return options(interfaceChoices(studio, selectedId), selectedId || "", { empty: "— none —" });
}

function stereoRows(stereotypes) {
  if (!stereotypes?.length) return `<div class="arch-dock-muted">None</div>`;
  return stereotypes.map(s => {
    // `display` (profiles feature) carries the value with its unit, e.g. "7 kg".
    const shown = (k, v) => s.display?.[k] ?? (v !== null && typeof v === "object" ? JSON.stringify(v) : v);
    const vals = Object.entries(s.values || {}).map(([k, v]) => `<div class="arch-kv" data-stereo-value="${esc(k)}"><span>${esc(k)}</span><b>${esc(shown(k, v))}</b></div>`).join("");
    return `<div class="arch-stereo-row">«${esc(s.name)}»${vals}</div>`;
  }).join("");
}

// Where a reference component's ports live: shared on the definition, or on this usage only.
function portsWhere(c) {
  const own = c.ports.filter(p => !p.on_definition).length;
  const shared = c.ports.length - own;
  return `${shared} on ${esc(c.definition.name)}${own ? `, ${own} on this component only` : ""}`;
}

function pills(badges) {
  return (badges || []).map(b => `<span class="tree-badge">${esc(b)}</span>`).join("") || `<span class="arch-dock-muted">—</span>`;
}

export function createDock(el, studio, act) {
  let last = null;
  el.innerHTML = `<div class="arch-dock-head"><span>Property Inspector</span>
      <button type="button" class="arch-x" data-dock-act="close" title="Hide the Property Inspector">×</button></div>
    <div class="arch-dock-body"><div class="arch-dock-part" data-part="top"></div><div class="arch-dock-part" data-part="bottom"></div></div>`;
  const top = el.querySelector('[data-part="top"]');
  const bottom = el.querySelector('[data-part="bottom"]');
  const stereo = new StereoSection(studio, { changed: () => act.stereotypesChanged?.() });
  bottom.before(stereo.el);

  function field(label, control) {
    return `<label class="arch-field"><span>${esc(label)}</span>${control}</label>`;
  }

  function portRow(p, allowed, usageOnly = false) {
    const kinds = [...new Set([...allowed, p.kind])];
    return `<div class="arch-prow${usageOnly ? " usage-only" : ""}" data-port-row="${esc(p.id)}"
        ${usageOnly ? `title="Only on this component (not on the referenced definition)"` : ""}>
      <input class="input" data-dock-port="name" data-id="${esc(p.id)}" value="${esc(p.name)}" aria-label="Port name"/>
      <select class="input" data-dock-port="direction" data-id="${esc(p.id)}" aria-label="Direction of ${esc(p.name)}" ${p.kind !== "data" ? "disabled" : ""}>
        ${options(DIRECTIONS.map(d => [d, d]), p.direction)}</select>
      <select class="input" data-dock-port="kind" data-id="${esc(p.id)}" aria-label="Kind of ${esc(p.name)}">${options(kinds.map(k => [k, k]), p.kind)}</select>
      <button type="button" class="arch-x" data-dock-act="delete-port" data-id="${esc(p.id)}" title="Delete port ${esc(p.name)}" aria-label="Delete port ${esc(p.name)}">×</button>
    </div>`;
  }

  function componentHtml(c, v) {
    const defs = treeNodes(studio, ["PartDefinition"]).filter(n => n.id !== v.composition.id)
      .map(n => [n.id, n.qualified_name || n.name]);
    const portButtons = v.allowed_port_kinds.flatMap(k => k === "data" ? ["in", "out", "inout"] : [k])
      .map(k => `<button type="button" class="btn-action" data-dock-act="add-port" data-port="${k}">+ ${esc(k === "inout" ? "InOut" : k[0].toUpperCase() + k.slice(1))}</button>`).join("");
    return `
      <div class="arch-dock-kind">${icon(c.is_reference ? "ref" : "component")} ${c.is_reference ? "Reference component" : "Component"}</div>
      ${field("Name", `<input class="input" data-dock="name" value="${esc(c.name)}"/>`)}
      ${field("Reference", `<select class="input" data-dock="definition">${options(defs, c.definition?.id || "", { empty: "— inline component —" })}</select>`)}
      ${STEREO}
      <div class="arch-dock-sub">Badges</div><div>${pills(c.badges)}</div>
      <div class="arch-dock-sub" data-dock-ports-head>Ports (${c.ports.length})${c.is_reference ? ` <span class="arch-dock-muted">${portsWhere(c)}</span>` : ""}</div>
      <div class="arch-dock-ports">${c.ports.map(p => portRow(p, v.allowed_port_kinds, c.is_reference && !p.on_definition)).join("")
        || `<div class="arch-dock-muted">No ports</div>`}</div>
      <div class="arch-dock-btns">${portButtons}</div>
      <div class="arch-dock-sub">Layout</div>
      <div class="arch-dock-muted">${Math.round(c.layout.x)}, ${Math.round(c.layout.y)} · ${Math.round(c.layout.w)} × ${Math.round(c.layout.h)}
        ${c.sized ? `<button type="button" class="btn-action" data-dock-act="reset-size">Auto size</button>` : ""}</div>
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="open">Open ⤵</button>
        <button type="button" class="btn-action" data-dock-act="properties">Properties tab ↗</button>
      </div>`;
  }

  function portHtml(p, ctxName, v) {
    const kinds = [...new Set([...v.allowed_port_kinds, p.kind])];
    return `
      <div class="arch-dock-kind">${icon(p.kind === "data" ? p.direction : p.kind)} ${ctxName ? `Port of ${esc(ctxName)}` : "Boundary port"}</div>
      ${field("Name", `<input class="input" data-dock="port-name" value="${esc(p.name)}"/>`)}
      ${field("Direction", `<select class="input" data-dock="port-direction" ${p.kind !== "data" ? "disabled" : ""}>${options(DIRECTIONS.map(d => [d, d]), p.direction)}</select>`)}
      ${field("Kind", `<select class="input" data-dock="port-kind">${options(kinds.map(k => [k, k]), p.kind)}</select>`)}
      ${field("Interface", `<select class="input" data-dock="port-interface">${interfaceOptions(studio, p.interface?.id)}</select>`)}
      ${field("Side", `<select class="input" data-dock="port-side">${options(SIDES.map(s => [s, s]), p.side)}</select>`)}
      ${p.on_definition ? `<p class="arch-dock-muted">Defined on the referenced definition: shared by every usage.</p>` : ""}
      ${STEREO}
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="properties">Properties tab ↗</button>
        <button type="button" class="btn-action" data-dock-act="delete">Delete</button>
      </div>`;
  }

  function connectorHtml(k, info) {
    return `
      <div class="arch-dock-kind">${icon("connect")} ${esc(k.kind)} connector</div>
      ${field("Name", `<input class="input" data-dock="conn-name" value="${esc(k.name)}"/>`)}
      <div class="arch-kv"><span>From</span><b>${esc(info.from)}</b></div>
      <div class="arch-kv"><span>To</span><b>${esc(info.to)}</b></div>
      <div class="arch-kv"><span>Interfaces</span><b>${esc(k.interfaces.join(", ") || "—")}</b></div>
      ${k.issues.length ? `<div class="arch-dock-sub">Problems</div>${k.issues.map(i => `<div class="arch-pill warn">${esc(i)}</div>`).join("")}` : ""}
      ${STEREO}
      <div class="arch-dock-sub">Route</div>
      <div class="arch-dock-muted">${k.points ? "Manual (drag the handles on the line)" : "Automatic"}
        ${k.points ? `<button type="button" class="btn-action" data-dock-act="reset-route">Reset route</button>` : ""}</div>
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="properties">Properties tab ↗</button>
        <button type="button" class="btn-action" data-dock-act="delete">Delete</button>
      </div>`;
  }

  function compositionHtml(v) {
    const c = v.composition;
    const bad = v.connectors.filter(k => k.issues.length).length;
    const kind = c.is_reference ? `Reference to ${c.definition.name} (shared by ${c.shared_by})`
      : c.kind === "PartDefinition" ? "Architecture" : "Inline component";
    return `
      <div class="arch-dock-kind">${icon("boundary")} ${esc(kind)}</div>
      ${field("Name", `<input class="input" data-dock="comp-name" value="${esc(c.name)}"/>`)}
      <div class="arch-kv"><span>Model type</span><b>${esc(v.model_type)}</b></div>
      <div class="arch-kv"><span>Components</span><b>${v.components.length}</b></div>
      <div class="arch-kv"><span>Boundary ports</span><b>${v.boundary_ports.length}</b></div>
      <div class="arch-kv"><span>Connectors</span><b>${v.connectors.length}${bad ? ` <span class="arch-pill warn">${bad} with problems</span>` : ""}</b></div>
      ${STEREO}
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="arrange">Arrange</button>
        <button type="button" class="btn-action" data-dock-act="fit">Fit</button>
        <button type="button" class="btn-action" data-dock-act="properties">Properties tab ↗</button>
      </div>
      <div class="arch-dock-sub">Tips</div>
      <ul class="arch-tips">
        <li>Drag from a port to another port to connect; drop on a block or the frame edge to create a port.</li>
        <li>Shift+drag a port to move it along the border.</li>
        <li>Double-click a block to open it, its name to rename it.</li>
        <li>Drag the background to select; Space+drag or the Hand tool to pan; wheel to zoom.</li>
      </ul>`;
  }

  function multiHtml(sel) {
    return `
      <div class="arch-dock-kind">${sel.length} items selected</div>
      <div class="arch-kv"><span>Components</span><b>${sel.filter(k => k.startsWith("c:")).length}</b></div>
      <div class="arch-kv"><span>Ports</span><b>${sel.filter(k => k.startsWith("p:")).length}</b></div>
      <div class="arch-kv"><span>Connectors</span><b>${sel.filter(k => k.startsWith("k:")).length}</b></div>
      ${STEREO}
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="group">Group into Component</button>
        <button type="button" class="btn-action" data-dock-act="duplicate">Duplicate</button>
        <button type="button" class="btn-action" data-dock-act="delete">Delete</button>
      </div>`;
  }

  // An element selected elsewhere (the tree, another tab) that this canvas does not draw.
  function externalHtml(e) {
    const doc = (e.doc || "").trim();
    return `
      <div class="arch-dock-kind">${esc(e.kind)}</div>
      <div class="arch-kv"><span>Name</span><b>${esc(e.name || "—")}</b></div>
      <div class="arch-dock-muted" style="word-break:break-all">${esc(e.qualified_name || "")}</div>
      ${e.req_id ? `<div class="arch-kv"><span>Id</span><b>${esc(e.req_id)}</b></div>` : ""}
      ${e.text ? `<div class="arch-dock-sub">Text</div><div>${esc(e.text)}</div>` : ""}
      ${doc ? `<div class="arch-dock-sub">Documentation</div><div>${esc(doc.length > 300 ? doc.slice(0, 299) + "…" : doc)}</div>` : ""}
      <div class="arch-dock-sub">Stereotypes</div>${stereoRows(e.stereotypes)}
      <p class="arch-dock-muted">Selected in the model browser; not drawn on this canvas.</p>
      <div class="arch-dock-btns">
        <button type="button" class="btn-action" data-dock-act="properties" data-id="${esc(e.id)}">Properties tab ↗</button>
      </div>`;
  }

  function render(snapshot) {
    last = snapshot;
    const { view: v, sel, primary, info, external, draft } = snapshot;
    let body, ids = null;
    if (draft) body = `<div class="arch-dock-kind">${icon("boundary")} New architecture</div>
      <p class="arch-dock-muted">Type its name on the canvas and press Enter (Escape cancels).</p>`;
    else if (!v) body = `<div class="arch-dock-muted">No architecture open.</div>`;
    else if (!sel.length && external) body = externalHtml(external);
    else if (sel.length > 1) {
      body = multiHtml(sel);
      ids = sel.filter(k => k.startsWith("c:")).map(k => k.slice(2));     // every selected component
    }
    else if (!primary) { body = compositionHtml(v); ids = v.composition.id ? [v.composition.id] : null; }
    else if (info?.type === "component") { body = componentHtml(info.c, v); ids = [info.c.id]; }
    else if (info?.type === "port") { body = portHtml(info.p, info.ctxName, v); ids = [info.p.id]; }
    else if (info?.type === "connector") { body = connectorHtml(info.k, info); ids = [info.k.id]; }
    else { body = compositionHtml(v); ids = v.composition.id ? [v.composition.id] : null; }
    const [before, after = ""] = body.split(STEREO);
    top.innerHTML = before;
    bottom.innerHTML = after;
    stereo.show(ids);
  }

  el.addEventListener("change", (e) => {
    const t = e.target;
    if (!last) return;
    const { info } = last;
    const val = t.value;
    if (t.dataset.dockPort) {
      const id = t.dataset.id;
      const key = t.dataset.dockPort;
      act.updatePort(id, { [key]: key === "name" ? val.trim() : val });
      return;
    }
    switch (t.dataset.dock) {
      case "name": act.rename(last.primary, val); break;
      case "definition": act.setDefinition(info.c.id, val || null); break;
      case "port-name": act.rename(last.primary, val); break;
      case "port-direction": act.updatePort(info.p.id, { direction: val }); break;
      case "port-kind": act.updatePort(info.p.id, { kind: val }); break;
      case "port-interface": act.updatePort(info.p.id, { interface: val || null }); break;
      case "port-side": act.movePort(last.primary, val); break;
      case "conn-name": act.rename(last.primary, val); break;
      case "comp-name": act.renameComposition(val); break;
      default:
    }
  });
  el.addEventListener("keydown", (e) => {
    // The studio's global Delete handler would delete the tree selection with a confirm().
    if (e.key === "Delete" || e.key === "Backspace") e.stopPropagation();
    if (e.key === "Enter" && e.target.matches("input")) e.target.blur();
  });
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-dock-act]");
    if (!b || !last) return;
    const a = b.dataset.dockAct;
    const { info } = last;
    if (a === "close") act.toggleDock(false);
    else if (a === "add-port") {
      const k = b.dataset.port;
      act.addPort(["in", "out", "inout"].includes(k) ? "data" : k, ["in", "out", "inout"].includes(k) ? k : "inout");
    }
    else if (a === "delete-port") act.deleteIds([b.dataset.id]);
    else if (a === "reset-size") act.resetSize(info.c.id);
    else if (a === "reset-route") act.resetRoute(info.k.id);
    else if (a === "open") act.open(info.c.id);
    else if (a === "properties") act.showProperties(b.dataset.id || null);
    else if (a === "delete") act.deleteSelection();
    else if (a === "arrange") act.arrange();
    else if (a === "fit") act.fit();
    else if (a === "group") act.group();
    else if (a === "duplicate") act.duplicate();
  });
  return { render };
}
