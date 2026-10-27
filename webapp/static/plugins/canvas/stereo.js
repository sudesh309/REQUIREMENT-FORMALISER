// Stereotypes section of the canvas's Property Inspector (System Composer Property Inspector):
// add (applicable, non-abstract) and remove stereotypes and edit their typed values in
// place, for the selected element or for every selected component at once.
//
//  - one element: the same API as the Properties tab's Stereotypes section
//    (/api/elements/<id>/stereotypes);
//  - several components: /api/arch/stereotypes, one request per edit, so one undo step, and
//    nothing is stored when a value is refused for any of them. Values that differ between
//    the components are shown as "mixed"; typing a value sets it on all of them.
//
// The value editors (number + unit and expressions, enumeration list, checkbox, text), the
// checks and the inline error marking are the profiles plugin's (studio.profiles.ui); without
// that plugin the section lists the stereotypes read-only.
//
// Values are shown with their unit and rounded (4.5359237 kg reads 4.54 kg); the field shows the
// stored precision while it has the focus, and what is typed is stored as typed (a number, an
// expression such as 2*1.5, or a value with a compatible unit such as 10 lb).
//
// A reference component shows the stereotypes and values it inherits from its definition,
// marked as inherited; typing a value overrides it for this component, "Reset" inherits the
// definition's again.
//
// The section's element stays in the dock while the dock re-renders around it, so a field
// keeps its focus and text; it re-reads the values when the selection changes, or when the
// model changed elsewhere (undo, Properties tab, MCP) and none of its fields is being edited.
import { esc } from "./common.js";

const MIXED = "Mixed: type a value for all";

export class StereoSection {
  constructor(studio, { changed } = {}) {
    this.studio = studio;
    this.changed = changed;
    this.el = document.createElement("section");
    this.el.className = "arch-dock-stereo";
    this.el.hidden = true;
    this.ids = [];
    this.key = null;
    this.view = null;
    this.seq = 0;
    this.stale = false;
    this.quiet = false;
    this.collapsed = new Set();
    // Edits saved elsewhere arrive as model-changed (tree refresh) or element-changed (in place).
    for (const ev of ["model-changed", "element-changed"])
      studio.on(ev, () => { if (!this.quiet) this.stale = true; });
    this.el.addEventListener("change", e => this.onChange(e));
    this.el.addEventListener("click", e => this.onClick(e));
    this.el.addEventListener("keydown", e => this.onKey(e));
    // `toggle` does not bubble: listen in the capture phase.
    this.el.addEventListener("toggle", (e) => {
      const d = e.target;
      if (d.matches?.("details[data-app]")) d.open ? this.collapsed.delete(d.dataset.app) : this.collapsed.add(d.dataset.app);
    }, true);
  }

  get ui() { return this.studio.profiles?.ui || null; }
  get many() { return this.ids.length > 1; }

  // Show the stereotypes of the elements `ids` (null or [] hides the section).
  show(ids) {
    const idx = this.studio.state.treeIndex;
    // A dock drawn from a view older than the tree (New, Load, an undo that removed the
    // element) asks for elements that are gone: wait for the next one.
    const key = ids?.length && ids.every(id => idx.has(id)) ? ids.join(",") : null;
    if (!key) { this.el.hidden = true; this.key = null; this.ids = []; return; }
    this.el.hidden = false;
    if (key !== this.key) {
      this.key = key;
      this.ids = [...ids];
      this.view = null;
      this.stale = false;
      this.el.innerHTML = `<div class="arch-dock-sub">Stereotypes</div><div class="arch-dock-muted">Loading…</div>`;
      this.load();
    } else if (this.stale && !this.el.contains(document.activeElement)) {
      this.stale = false;
      this.load();
    }
  }

  async load() {
    const seq = ++this.seq;
    const key = this.key;
    try {
      const v = this.many
        ? await this.studio.api("GET", `/api/arch/stereotypes?ids=${this.ids.map(encodeURIComponent).join(",")}`)
        : await this.studio.api("GET", `/api/elements/${encodeURIComponent(this.ids[0])}/stereotypes`);
      if (seq === this.seq && key === this.key) this.fill(v);
    } catch (e) {
      if (seq === this.seq && key === this.key) {
        this.el.innerHTML = `<div class="arch-dock-sub">Stereotypes</div><div class="pf-msg err">${esc(errorText(e))}</div>`;
      }
    }
  }

  fill(v) {
    this.view = v;
    const ui = this.ui;
    const n = this.ids.length;
    const applicable = v.applicable || [];
    const head = `<div class="arch-dock-sub">Stereotypes${this.many ? ` <span class="arch-dock-muted">of ${n} components</span>` : ""}</div>`;
    if (!ui) {                         // no profiles plugin: read-only
      this.el.innerHTML = head + (v.applied.length ? v.applied.map(a => `<div class="arch-stereo-row">«${esc(a.qualified_name)}»</div>`).join("")
        : `<div class="arch-dock-muted">None</div>`);
      return;
    }
    const add = `<select class="input" data-st-add aria-label="Add stereotype${this.many ? " to all selected" : ""}" ${applicable.length ? "" : "disabled"}
        title="Stereotypes of the model's profiles that apply${this.many ? " to every selected component" : ""}">
      <option value="">${applicable.length ? (this.many ? "Add stereotype to all…" : "Add stereotype…") : "No applicable stereotypes"}</option>
      ${applicable.map(s => `<option value="${esc(s.id)}">${esc(s.qualified_name)}</option>`).join("")}</select>`;
    const partial = (v.partial || []).map(p => `<div class="arch-st-partial">
        <span>«${esc(p.qualified_name)}» on ${p.count} of ${n}</span>
        <button type="button" class="btn-action" data-st-apply="${esc(p.id)}" title="Apply «${esc(p.qualified_name)}» to the other selected components">Apply to all</button></div>`).join("");
    if (!this.roundingBound) { this.roundingBound = true; ui.rounding(this.el); }
    const groups = v.applied.map((app) => {
      const withProps = app.groups.filter(g => g.properties.length);
      const heads = withProps.length > 1 || withProps.some(g => g.id !== app.id);
      const from = app.inherited_from?.name;
      const rows = app.groups.map(g => (!g.properties.length ? ""
        : (heads ? `<div class="pf-ghead">${esc(g.stereotype)}${g.id !== app.id ? " (inherited)" : ""}</div>` : "")
          + g.properties.map(p => ui.propertyEditor(p, { round: true, from })).join(""))).join("");
      return `<details class="pf-app" data-app="${esc(app.id)}" ${this.collapsed.has(app.id) ? "" : "open"}>
        <summary title="${esc(app.description || "")}"><span class="pf-caret">▸</span>
          <span class="pf-name">«${esc(app.qualified_name)}»</span><span data-group-tag>${ui.groupTag(app)}</span><span class="flex-1"></span>
          <span data-group-rm>${this.removeButton(app)}</span></summary>
        <div class="pf-props">${rows || '<div class="arch-dock-muted" style="grid-column:1/-1">No properties.</div>'}</div>
      </details>`;
    }).join("");
    this.el.innerHTML = head + `<div class="arch-st-bar">${add}</div>` + partial
      + (groups || `<div class="arch-dock-muted">None applied.</div>`) + `<div class="pf-msg" data-st-msg role="status"></div>`;
    for (const app of v.applied) for (const g of app.groups) for (const p of g.properties) {
      if (!p.mixed) continue;
      const input = this.el.querySelector(`[data-path="${CSS.escape(p.path)}"]`);
      if (!input) continue;
      input.dataset.mixed = "1";
      if (input.type === "checkbox") input.indeterminate = true;
      else if (input.tagName === "SELECT") { const o = input.querySelector('option[value=""]'); if (o) o.textContent = "— mixed —"; }
      else { input.dataset.hint = input.placeholder; input.placeholder = MIXED; input.title = MIXED; }
    }
  }

  // The group's remove button (none for a stereotype that is only inherited).
  removeButton(app) {
    return this.ui.removeButton(app, `data-st-remove="${esc(app.id)}"`, this.many ? " from every selected component" : "");
  }

  msg(text, cls = "") {
    const m = this.el.querySelector("[data-st-msg]");
    if (m) { m.textContent = text; m.className = `pf-msg ${cls}`; }
  }

  // Tell the canvas (block «stereotype» lines, badges, undo) without re-reading this section.
  async notify() {
    this.quiet = true;
    try { await this.changed?.(); } finally { this.quiet = false; }
  }

  what() {
    return this.many ? `${this.ids.length} components` : (this.view?.element?.name || "element");
  }

  async apply(stId, select = null) {
    const name = [...(this.view?.applicable || []), ...(this.view?.partial || [])].find(s => s.id === stId)?.qualified_name || stId;
    try {
      const v = this.many
        ? await this.studio.api("POST", "/api/arch/stereotypes", { ids: this.ids, stereotype: stId })
        : await this.studio.api("POST", `/api/elements/${encodeURIComponent(this.ids[0])}/stereotypes`, { stereotype: stId });
      this.studio.log(`Applied «${name}» to ${this.what()}`, "ok");
      this.fill(v);
      this.el.querySelector(`details[data-app="${CSS.escape(stId)}"] [data-path]`)?.focus();
      await this.notify();
    } catch (e) {
      if (select) select.value = "";
      this.msg(errorText(e), "err");
    }
  }

  async remove(stId) {
    const name = this.view?.applied.find(a => a.id === stId)?.qualified_name || stId;
    try {
      const v = this.many
        ? await this.studio.api("DELETE", "/api/arch/stereotypes", { ids: this.ids, stereotype: stId })
        : await this.studio.api("DELETE", `/api/elements/${encodeURIComponent(this.ids[0])}/stereotypes/${encodeURIComponent(stId)}`);
      this.studio.log(`Removed «${name}» from ${this.what()}`, "warning");
      this.fill(v);
      await this.notify();
    } catch (e) { this.msg(errorText(e), "err"); }
  }

  async commit(input) {
    const ui = this.ui;
    if (!ui) return;
    const path = input.dataset.path;
    const value = input.type === "checkbox" ? input.checked : input.value;
    if (input.type !== "checkbox" && value === input.dataset.orig) return;
    if (!ui.once(input, value)) return;
    try {
      const v = this.many
        ? await this.studio.api("PATCH", "/api/arch/stereotypes", { ids: this.ids, property: path, value })
        : await this.studio.api("PATCH", `/api/elements/${encodeURIComponent(this.ids[0])}/stereotypes`, { property: path, value });
      this.view = v;
      const shown = ui.findValue(v, path);
      // Update this editor in place (no re-render): focus may already be in the next field.
      if (shown) {
        ui.showStored(input, shown);
        const app = v.applied.find(a => a.groups.some(g => g.properties.some(p => p.path === path)));
        ui.markOrigin(input, shown, app);
        ui.markGroup(input.closest("details.pf-app"), app, this.removeButton(app));
        if (input.dataset.mixed) {
          delete input.dataset.mixed;
          input.indeterminate = false;
          if (input.dataset.hint !== undefined) input.placeholder = input.dataset.hint;
        }
      }
      const where = this.many ? ` on ${this.ids.length} components` : "";
      // What was stored, rounded for reading: "mass = 4.54 kg (stored 4.5359237 kg)".
      const kept = shown && shown.display_short !== shown.display ? ` (stored ${shown.display})` : "";
      // A value typed with a unit says what it came to: "10 lb" -> "mass = 4.54 kg (stored 4.5359237 kg)".
      const typed = input.type !== "checkbox" && /[A-DF-Za-df-z%°]/.test(String(value)) && shown?.unit ? ` (entered as ${String(value).trim()})` : "";
      const text = `${path} = ${shown?.display_short ?? shown?.display ?? ""}${kept}${typed}${where}`;
      this.studio.log(`${this.many ? "" : `${this.what()}: `}${path} = ${shown?.display ?? ""}${where}`, "ok");
      this.msg(text, "ok");
      await this.notify();
    } catch (e) {
      input.classList.add("pf-invalid");
      input.setAttribute("aria-invalid", "true");
      input.title = errorText(e);
      this.msg(errorText(e), "err");
    }
  }

  async reset(path) {
    try {
      const v = this.many
        ? await this.studio.api("POST", "/api/arch/stereotypes/reset", { ids: this.ids, properties: [path] })
        : await this.studio.api("POST", `/api/elements/${encodeURIComponent(this.ids[0])}/stereotypes/reset`, { properties: [path] });
      this.studio.log(`${this.many ? `${this.ids.length} components` : this.what()}: ${path} is inherited again`, "ok");
      this.fill(v);
      await this.notify();
    } catch (e) { this.msg(errorText(e), "err"); }
  }

  onChange(e) {
    const t = e.target;
    if (t.matches("[data-st-add]")) { if (t.value) this.apply(t.value, t); }
    else if (t.dataset.path) this.commit(t);
  }

  onClick(e) {
    const rm = e.target.closest("[data-st-remove]");
    if (rm) { e.preventDefault(); e.stopPropagation(); this.remove(rm.dataset.stRemove); return; }
    const ap = e.target.closest("[data-st-apply]");
    if (ap) { this.apply(ap.dataset.stApply); return; }
    const rs = e.target.closest("[data-reset]");
    if (rs) { e.preventDefault(); this.reset(rs.dataset.reset); }
  }

  onKey(e) {
    const t = e.target;
    if (!t.dataset?.path) return;
    if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); this.commit(t); }
    else if (e.key === "Escape" && t.dataset.orig !== undefined) {
      e.stopPropagation();
      t.value = t.dataset.orig;
      t.classList.remove("pf-invalid");
      t.removeAttribute("aria-invalid");
    }
  }
}

function errorText(e) { return String(e?.message || e).replace(/^Error:\s*/, ""); }
