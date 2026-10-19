// MATLAB-style toolstrip for the architecture canvas: labelled sections of icon buttons.
// Buttons carry data-canvas-act; the editor handles the actions and calls update().
import { esc } from "./common.js";

const I = {
  component: `<rect x="2.5" y="3.5" width="11" height="9" rx="1.5"/><path d="M5 7h6M5 9.5h4"/>`,
  in: `<path d="M1 8h7M5.5 5.5 8 8l-2.5 2.5"/><rect x="9" y="3" width="6" height="10" rx="1"/>`,
  out: `<rect x="1" y="3" width="6" height="10" rx="1"/><path d="M7 8h7M11.5 5.5 14 8l-2.5 2.5"/>`,
  inout: `<path d="M2 8h12M4.5 5.5 2 8l2.5 2.5M11.5 5.5 14 8l-2.5 2.5"/>`,
  physical: `<path d="M8 2.5 13.5 8 8 13.5 2.5 8z"/>`,
  client: `<circle cx="8" cy="8" r="5"/>`,
  server: `<rect x="3" y="3" width="10" height="10"/>`,
  boundary: `<rect x="3.5" y="2.5" width="11" height="11" rx="1" stroke-dasharray="2 1.5"/><path d="M1 8h5M4 6l2 2-2 2"/>`,
  connect: `<circle cx="3" cy="12" r="1.8"/><circle cx="13" cy="4" r="1.8"/><path d="M4.5 11.5h4v-7h3"/>`,
  group: `<rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke-dasharray="2 1.5"/><rect x="3.5" y="5.5" width="4" height="5"/><rect x="9" y="5.5" width="4" height="5"/>`,
  ref: `<rect x="1.5" y="5" width="7" height="6" rx="3"/><rect x="7.5" y="5" width="7" height="6" rx="3"/>`,
  inline: `<rect x="1" y="5" width="6" height="6" rx="3"/><rect x="9" y="5" width="6" height="6" rx="3"/><path d="M8 2v2M8 12v2"/>`,
  expand: `<path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4"/><rect x="5.5" y="5.5" width="5" height="5"/>`,
  copy: `<rect x="5" y="5" width="9" height="9" rx="1"/><path d="M3 11V3a1 1 0 0 1 1-1h7"/>`,
  paste: `<rect x="3" y="3" width="10" height="11" rx="1"/><path d="M6 2h4v2H6zM5.5 8h5M5.5 10.5h3.5"/>`,
  duplicate: `<rect x="1.5" y="1.5" width="8" height="8" rx="1"/><rect x="6.5" y="6.5" width="8" height="8" rx="1"/>`,
  delete: `<path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.5 6.5v5M9.5 6.5v5"/>`,
  undo: `<path d="M5 3 2 6l3 3"/><path d="M2 6h7a4 4 0 0 1 0 8H6"/>`,
  redo: `<path d="m11 3 3 3-3 3"/><path d="M14 6H7a4 4 0 0 0 0 8h3"/>`,
  arrange: `<rect x="1.5" y="2" width="4" height="4"/><rect x="1.5" y="10" width="4" height="4"/><rect x="10.5" y="6" width="4" height="4"/><path d="M5.5 4h2.5v8H5.5M8 8h2.5"/>`,
  zoomin: `<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3.5 3.5M5 7h4M7 5v4"/>`,
  zoomout: `<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3.5 3.5M5 7h4"/>`,
  fit: `<path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/><rect x="5" y="5" width="6" height="6" rx="1"/>`,
  pan: `<path d="M5.5 8V3.5a1 1 0 0 1 2 0V7M7.5 7V2.5a1 1 0 0 1 2 0V7M9.5 7V3.5a1 1 0 0 1 2 0V9c0 3-1.5 5-4.5 5-2 0-3-1-4-3L2 8.5a1 1 0 0 1 1.6-1.2L5.5 9"/>`,
  dock: `<rect x="1.5" y="2.5" width="13" height="11" rx="1"/><path d="M10 2.5v11M11.5 5h1.5M11.5 7.5h1.5"/>`,
  up: `<path d="M8 13V3M4 7l4-4 4 4"/>`,
};

export function icon(name) {
  return `<svg class="arch-ico" viewBox="0 0 16 16" aria-hidden="true">${I[name] || ""}</svg>`;
}

function btn(act, label, ico, title, { big = false, toggle = false } = {}) {
  return `<button type="button" class="arch-tbtn${big ? " big" : ""}" data-canvas-act="${act}"
    ${toggle ? `aria-pressed="false"` : ""} title="${esc(title)}" aria-label="${esc(title)}">${icon(ico)}<span>${esc(label)}</span></button>`;
}

function section(label, body) {
  return `<div class="arch-tsec" role="group" aria-label="${esc(label)}"><div class="arch-tsec-body">${body}</div>
    <div class="arch-tsec-label">${esc(label)}</div></div>`;
}

export function toolstripHtml() {
  return `<div class="arch-toolstrip" role="toolbar" aria-label="Architecture canvas tools">
    ${section("Component", `
      ${btn("add-component", "Component", "component", "Add Component (inline, at a free spot)", { big: true })}
      <div class="arch-tcol">
        ${btn("group", "Group", "group", "Create Component from Selection (Ctrl+G)")}
        ${btn("expand", "Expand", "expand", "Expand: move the sub-components of the selected inline component up one level")}
      </div>
      <div class="arch-tcol">
        ${btn("save-ref", "Save as Ref", "ref", "Save as Reference: make the selected inline component a reusable definition")}
        ${btn("inline", "Inline", "inline", "Inline: copy the definition into the selected reference component only")}
      </div>`)}
    ${section("Port", `
      <div class="arch-tgrid">
        ${btn("add-port-in", "In", "in", "Add input port to the selected component(s)")}
        ${btn("add-port-out", "Out", "out", "Add output port to the selected component(s)")}
        ${btn("add-port-inout", "InOut", "inout", "Add bidirectional data port to the selected component(s)")}
        ${btn("add-port-physical", "Physical", "physical", "Add physical port to the selected component(s)")}
        ${btn("add-port-client", "Client", "client", "Add client port to the selected component(s)")}
        ${btn("add-port-server", "Server", "server", "Add server port to the selected component(s)")}
      </div>
      ${btn("add-boundary", "Boundary", "boundary", "Add Boundary Port to the architecture or component being viewed", { big: true })}`)}
    ${section("Connect", `
      ${btn("connect", "Connect", "connect", "Connect mode: click a port, then another port (or drag from any port). Esc leaves the mode", { big: true, toggle: true })}`)}
    ${section("Edit", `
      <div class="arch-tgrid">
        ${btn("copy", "Copy", "copy", "Copy the selected components (Ctrl+C)")}
        ${btn("paste", "Paste", "paste", "Paste into the composition being viewed (Ctrl+V)")}
        ${btn("duplicate", "Duplicate", "duplicate", "Duplicate the selected components (Ctrl+D)")}
        ${btn("delete", "Delete", "delete", "Delete the selection (Delete)")}
        ${btn("undo", "Undo", "undo", "Undo (Ctrl+Z)")}
        ${btn("redo", "Redo", "redo", "Redo (Ctrl+Y)")}
      </div>`)}
    ${section("Layout", `${btn("arrange", "Arrange", "arrange", "Auto-Arrange left to right by signal flow", { big: true })}`)}
    ${section("View", `
      <div class="arch-tgrid">
        ${btn("zoom-out", "", "zoomout", "Zoom out (-)")}
        <button type="button" class="arch-tbtn arch-zoom" data-canvas-act="zoom-reset" title="Zoom to 100% (0)" aria-label="Zoom to 100%">100%</button>
        ${btn("zoom-in", "", "zoomin", "Zoom in (+)")}
        ${btn("fit", "Fit", "fit", "Fit to view (Space)")}
        ${btn("pan", "Pan", "pan", "Hand tool: drag the background to pan (or hold Space / the middle button)", { toggle: true })}
        ${btn("dock", "Inspector", "dock", "Show or hide the Property Inspector", { toggle: true })}
      </div>`)}
  </div>`;
}

// Enable/disable and toggle state from the editor's state snapshot.
export function updateToolstrip(root, s) {
  const set = (act, enabled, title) => {
    const b = root.querySelector(`[data-canvas-act="${act}"]`);
    if (!b) return;
    b.disabled = !enabled;
    if (title) b.title = title;
  };
  const press = (act, on) => root.querySelector(`[data-canvas-act="${act}"]`)?.setAttribute("aria-pressed", on ? "true" : "false");
  const has = !!s.view;
  set("add-component", has);
  set("add-boundary", has);
  for (const k of ["in", "out", "inout", "physical", "client", "server"]) {
    const kind = ["in", "out", "inout"].includes(k) ? "data" : k;
    const b = root.querySelector(`[data-canvas-act="add-port-${k}"]`);
    if (b) b.hidden = has && !s.allowedKinds.includes(kind);
    set(`add-port-${k}`, has && s.comps.length > 0);
  }
  set("group", s.comps.length > 0 && !s.readOnlyChildren);
  set("expand", s.comps.length === 1 && !s.comps[0].is_reference && s.comps[0].has_children);
  set("save-ref", s.comps.length === 1 && !s.comps[0].is_reference);
  set("inline", s.comps.length === 1 && s.comps[0].is_reference);
  set("connect", has);
  set("copy", s.comps.length > 0);
  set("duplicate", s.comps.length > 0);
  set("paste", has && s.clipboard > 0, s.clipboard ? `Paste ${s.clipboard} component(s) here (Ctrl+V)` : "Copy components first (Ctrl+C)");
  set("delete", s.selCount > 0);
  set("undo", s.canUndo, s.undoLabel ? `Undo ${s.undoLabel} (Ctrl+Z)` : "Nothing to undo (Ctrl+Z)");
  set("redo", s.canRedo, s.redoLabel ? `Redo ${s.redoLabel} (Ctrl+Y)` : "Nothing to redo (Ctrl+Y)");
  set("arrange", has && s.componentCount > 0);
  for (const a of ["zoom-in", "zoom-out", "zoom-reset", "fit"]) set(a, has);
  press("connect", s.mode === "connect");
  press("pan", s.mode === "pan");
  press("dock", s.dockOpen);
  const z = root.querySelector('[data-canvas-act="zoom-reset"]');
  if (z) z.textContent = `${Math.round(s.zoom * 100)}%`;
}
