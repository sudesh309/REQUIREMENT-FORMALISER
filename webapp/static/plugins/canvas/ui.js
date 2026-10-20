// Small UI pieces for the canvas: toasts, a keyboard-navigable context menu and the
// inline name editor. No window.prompt / alert / confirm.
import { esc } from "./common.js";

export function createToasts(host) {
  const box = document.createElement("div");
  box.className = "arch-toasts";
  box.setAttribute("aria-live", "polite");
  host.appendChild(box);
  return function toast(message, severity = "info", ms) {
    const t = document.createElement("div");
    t.className = `arch-toast ${severity}`;
    t.dataset.toast = severity;
    t.setAttribute("role", severity === "error" ? "alert" : "status");
    t.textContent = message;
    t.title = "Click to dismiss";
    t.addEventListener("click", () => t.remove());
    box.appendChild(t);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => t.remove(), ms ?? (severity === "error" ? 8000 : 3500));
    return t;
  };
}

// items: [{label, cmd, hint?, disabled?, danger?} | "-" | {group: label, items: [...]}]
export function createMenu(host, onCommand) {
  const menu = document.createElement("div");
  menu.className = "arch-menu";
  menu.hidden = true;
  menu.setAttribute("role", "menu");
  host.appendChild(menu);
  let restoreFocus = null;

  function close() {
    if (menu.hidden) return;
    menu.hidden = true;
    menu.innerHTML = "";
    restoreFocus?.focus({ preventScroll: true });
  }

  function itemHtml(it) {
    if (it === "-") return `<div class="arch-menu-sep" role="separator"></div>`;
    if (it.group) {
      return `<div class="arch-menu-row" role="group" aria-label="${esc(it.group)}"><span class="arch-menu-glabel">${esc(it.group)}</span>
        ${it.items.map(x => `<button type="button" role="menuitem" tabindex="-1" class="arch-menu-chip" data-menu-cmd="${esc(x.cmd)}"
          ${x.disabled ? "disabled" : ""} title="${esc(x.hint || x.label)}">${esc(x.label)}</button>`).join("")}</div>`;
    }
    return `<button type="button" role="menuitem" tabindex="-1" class="arch-menu-item${it.danger ? " danger" : ""}"
      data-menu-cmd="${esc(it.cmd)}" ${it.disabled ? "disabled" : ""}><span>${esc(it.label)}</span>
      ${it.hint ? `<kbd>${esc(it.hint)}</kbd>` : ""}</button>`;
  }

  function open(items, x, y, context) {
    restoreFocus = document.activeElement;
    menu.innerHTML = items.map(itemHtml).join("");
    menu.hidden = false;
    menu._context = context;
    const hr = host.getBoundingClientRect();
    const mw = menu.offsetWidth, mh = menu.offsetHeight;
    menu.style.left = `${Math.max(4, Math.min(x, hr.width - mw - 4))}px`;
    menu.style.top = `${Math.max(4, Math.min(y, hr.height - mh - 4))}px`;
    focusables()[0]?.focus({ preventScroll: true });
  }

  const focusables = () => [...menu.querySelectorAll("button:not([disabled])")];

  menu.addEventListener("click", (e) => {
    const b = e.target.closest("[data-menu-cmd]");
    if (!b || b.disabled) return;
    const ctx = menu._context;
    close();
    onCommand(b.dataset.menuCmd, ctx);
  });
  menu.addEventListener("keydown", (e) => {
    const items = focusables();
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowRight") { items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Escape") { close(); }
    else if (e.key === "Tab") { close(); }
    else return;
    e.preventDefault();
    e.stopPropagation();
  });
  menu.addEventListener("contextmenu", e => e.preventDefault());
  document.addEventListener("pointerdown", (e) => { if (!menu.hidden && !menu.contains(e.target)) close(); }, true);
  return { open, close, get isOpen() { return !menu.hidden; }, el: menu };
}

// Inline editor over an SVG text element: Enter commits, Escape cancels, blur commits.
export function createInlineEditor(host) {
  const input = document.createElement("input");
  input.className = "arch-inline-edit";
  input.hidden = true;
  input.setAttribute("aria-label", "Name");
  input.spellcheck = false;
  host.appendChild(input);
  let current = null;

  function finish(commit) {
    if (!current) return;
    const { onCommit, onCancel, initial, always } = current;
    current = null;
    const value = input.value.trim();
    input.hidden = true;
    host.focus({ preventScroll: true });
    if (commit && value && (always || value !== initial)) onCommit(value);
    else if (!commit || !value) onCancel?.();
  }

  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));

  // `always`: commit even an unchanged name (naming something not created yet);
  // `onCancel`: Escape, or an empty name.
  function edit(target, initial, onCommit, { minWidth = 110, always = false, onCancel = null } = {}) {
    finish(false);
    const hr = host.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    const w = Math.max(minWidth, r.width + 40);
    input.style.width = `${w}px`;
    input.style.left = `${Math.max(2, Math.min(r.left - hr.left + r.width / 2 - w / 2, hr.width - w - 2))}px`;
    input.style.top = `${Math.max(2, r.top - hr.top + r.height / 2 - 13)}px`;
    input.value = initial;
    input.hidden = false;
    current = { onCommit, onCancel, initial, always };
    input.focus();
    input.select();
  }
  return { edit, cancel: () => finish(false), get active() { return !!current; }, el: input };
}
