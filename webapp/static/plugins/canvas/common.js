// Shared helpers for the architecture plugin modules (no third-party code).

export const DIRECTIONS = ["in", "out", "inout"];
export const PORT_KINDS = ["data", "physical", "client", "server"];
export const INTERFACE_KINDS = new Set(["PortDefinition", "InterfaceDefinition", "ItemDefinition",
                                        "AttributeDefinition"]);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     "\"": "&quot;", "'": "&#39;" }[m]));
}

// A PartDefinition (architecture) or a part usage (component) can be opened as a composition.
export function isComposition(el) {
  return el && (el.kind === "PartDefinition" || el.kind === "PartUsage");
}

export function isComponent(el) {
  return el?.kind === "PartUsage" && (el.badges || []).some(b => b === "inline" || b === "ref");
}

// Nodes of the containment tree (already loaded by the studio) of the given kinds.
export function treeNodes(studio, kinds) {
  const want = kinds instanceof Set ? kinds : new Set(kinds);
  return [...studio.state.treeIndex.values()].filter(n => want.has(n.kind));
}

export function options(items, selected, { empty } = {}) {
  const head = empty !== undefined ? `<option value="">${esc(empty)}</option>` : "";
  return head + items.map(([value, label]) =>
    `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`).join("");
}

// studio.modal plus keyboard handling: Enter submits, Escape cancels, first field focused.
export function openForm(studio, title, html, onSubmit) {
  studio.modal(esc(title), html, onSubmit);
  const root = document.querySelector("#modal-root");
  const form = root.querySelector("#modal-form");
  form.addEventListener("submit", e => {
    e.preventDefault();
    root.querySelector("[data-modal-submit]")?.click();
  });
  root.querySelector(".modal")?.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); root.querySelector("[data-modal-cancel]")?.click(); }
  });
  root.querySelector("[data-modal-cancel]")?.setAttribute("type", "button");
  root.querySelector("[data-modal-submit]")?.setAttribute("type", "button");
  // A hidden submit button lets Enter in a text field submit the form.
  const hidden = document.createElement("button");
  hidden.type = "submit"; hidden.hidden = true; form.appendChild(hidden);
  form.querySelector("input, select, textarea")?.focus();
  return root;
}

// Reload the tree after the model was replaced (undo/redo) or edited, keeping the
// selection when the element still exists.
export async function reload(studio, selectId = studio.state.selectedId) {
  await studio.refreshTree();
  if (selectId && studio.state.treeIndex.has(selectId)) {
    await studio.selectElement(selectId);
  } else if (studio.state.selectedId && !studio.state.treeIndex.has(studio.state.selectedId)) {
    clearSelection(studio);
  }
}

export function clearSelection(studio) {
  studio.state.selectedId = null;
  studio.state.selected = null;
  document.querySelector("#props-form")?.classList.add("hidden");
  document.querySelector("#props-placeholder")?.classList.remove("hidden");
  const host = document.querySelector("#inspector-sections");
  if (host) host.innerHTML = "";
  studio.setStatus("");
}

let styled = false;
export function injectStyles() {
  if (styled) return;
  styled = true;
  const st = document.createElement("style");
  st.dataset.plugin = "architecture";
  st.textContent = `
    .btn-action[disabled] { opacity:.45; cursor:not-allowed; }
    .arch-strip { display:flex; flex-wrap:wrap; gap:.25rem; align-items:center; padding:.35rem;
                  background:#f8fafc; border:1px solid #e2e8f0; border-radius:.375rem; }
    .arch-strip .sep { width:1px; height:1.1rem; background:#cbd5e1; margin:0 .25rem; }
    .arch-table { width:100%; font-size:.8rem; border-collapse:collapse; }
    .arch-table th { text-align:left; font-weight:600; color:#64748b; font-size:.7rem; text-transform:uppercase;
                     letter-spacing:.04em; padding:.25rem .35rem; border-bottom:1px solid #e2e8f0; }
    .arch-table td { padding:.15rem .35rem; border-bottom:1px solid #f1f5f9; vertical-align:middle; }
    .arch-table tr:hover td { background:#f8fafc; }
    .arch-table .input { padding:.15rem .35rem; font-size:.8rem; }
    .arch-pill { display:inline-block; font-size:.65rem; padding:0 .4rem; border-radius:999px;
                 background:#e0e7ff; color:#3730a3; }
    .arch-pill.warn { background:#fee2e2; color:#991b1b; }
    .arch-crumbs button { color:#1d4ed8; }
    .arch-crumbs button:hover { text-decoration:underline; }
    .arch-x { color:#94a3b8; padding:0 .3rem; border-radius:.25rem; }
    .arch-x:hover { color:#b91c1c; background:#fee2e2; }
    .arch-h { font-size:.72rem; font-weight:600; color:#475569; margin:.6rem 0 .2rem; }
  `;
  document.head.appendChild(st);
}
