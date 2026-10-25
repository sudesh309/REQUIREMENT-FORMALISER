// SVG markup for the architecture canvas: frame, component blocks, ports, connectors.
// Pure string builders (no DOM access) so the editor can redraw a single block or
// connector cheaply while dragging.
import { esc } from "./common.js";
import { fit, glyphPath, hashColor, nameLines, pathD, PORT } from "./geometry.js";

export const PORT_CHAR_W = 6.3;      // port labels are 11.5 px (engine.architecture.PORT_CHAR_W)
const NAME_CHAR_W = 7.4, DEF_CHAR_W = 6, NAME_LINE_H = 14;

const KIND_COLOR = { data: "#334155", physical: "#a16207", client: "#6d28d9", server: "#6d28d9" };
const CONN_COLOR = { data: "#1e293b", physical: "#a16207", "client-server": "#6d28d9", unknown: "#64748b" };
const HIDDEN_BADGES = new Set(["ref", "inline", "leaf", "composite", "in", "out", "inout"]);

export function portColor(p) {
  return p.style?.stroke || (p.interface ? hashColor(p.interface.name || p.interface.id) : KIND_COLOR[p.kind] || KIND_COLOR.data);
}

export function connectorColor(c, sourcePort) {
  if (c.style?.stroke) return c.style.stroke;
  if (c.kind === "data" && sourcePort?.style?.stroke) return sourcePort.style.stroke;
  if (c.kind === "data" && c.interfaces?.length) return hashColor(c.interfaces[0]);
  return CONN_COLOR[c.kind] || CONN_COLOR.unknown;
}

// One arrow marker per colour (markers cannot inherit the line colour everywhere yet).
export class Markers {
  constructor() { this.ids = new Map(); }
  id(color) {
    if (!this.ids.has(color)) this.ids.set(color, `arch-m${this.ids.size}`);
    return this.ids.get(color);
  }
  defs() {
    return [...this.ids].map(([color, id]) =>
      `<marker id="${id}" viewBox="0 0 10 10" refX="10" refY="5" markerUnits="userSpaceOnUse" markerWidth="8"
        markerHeight="8" orient="auto-start-reverse"><path d="M0 1.5 L10 5 L0 8.5 L2.5 5 z" fill="${esc(color)}"/></marker>`).join("");
  }
}

export function staticDefs() {
  return `
    <pattern id="arch-grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="#dbe3ee"/></pattern>
    <filter id="arch-glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3"/></filter>`;
}

function stereoText(stereotypes) {
  const names = (stereotypes || []).map(s => s.name).filter(Boolean);
  return names.length ? `«${names.join(", ")}»` : "";
}

function hlStyle(id, hl) {
  return hl && hl.ids.has(id) ? ` hl" style="--hl:${esc(hl.color)}` : "";
}

// A port glyph + label, positioned in its owner's coordinates (box).
export function portSvg(pt, { sel, hl, connect } = {}) {
  const { p, key, ctx, local, inward } = pt;
  const color = portColor(p);
  const cls = ["arch-port", `k-${p.kind}`, `d-${p.direction}`];
  if (sel?.has(key)) cls.push("sel");
  if (connect?.has(key)) cls.push(connect.get(key).ok ? "can" : "cannot");
  const { x, y } = local;
  const side = p.side;
  let lx = 0, ly = 3.5, anchor = "middle";
  const out = inward ? 1 : -1;     // labels: inside a block, outside the frame
  if (side === "left") { lx = -12 * out; anchor = inward ? "end" : "start"; }
  else if (side === "right") { lx = 12 * out; anchor = inward ? "start" : "end"; }
  else if (side === "top") { ly = inward ? -10 : 18; }
  else { ly = inward ? 19 : -10; }
  const maxLabel = pt.labelWidth || 90;
  // Sources are filled, sinks hollow: an arrowhead ending at an input reads as one arrow.
  const hollow = p.kind === "physical" || p.kind === "server" || (p.kind === "data" && p.direction === "in");
  const fill = hollow ? "#ffffff" : color;
  const title = `${p.name} — ${p.kind === "data" ? p.direction + " " : ""}${p.kind} port`
    + `\nInterface: ${p.interface ? p.interface.name + (p.badges?.includes("owned") ? " (owned by this port)" : "") : "none"}`
    + (connect?.get(key)?.reason ? `\n${connect.get(key).reason}` : "");
  return `<g class="${cls.join(" ")}${hlStyle(p.id, hl)}" data-kind="port" data-key="${esc(key)}" data-id="${esc(p.id)}"
      data-ctx="${esc(ctx || "")}" data-name="${esc(p.name)}" data-dir="${esc(p.direction)}" transform="translate(${r1(x)},${r1(y)})">
    <title>${esc(title)}</title>
    <circle class="arch-port-ring" r="${PORT + 4}"/>
    <circle class="arch-port-hit" r="${PORT + 5}"/>
    <path class="arch-port-glyph" d="${glyphPath(p.kind, p.direction, side)}" fill="${esc(fill)}" stroke="${esc(color)}"/>
    <text class="arch-port-label" data-role="port-label" x="${lx}" y="${ly}" text-anchor="${anchor}">${esc(fit(p.name, maxLabel, PORT_CHAR_W))}</text>
  </g>`;
}

// Where a block's title (stereotype line, name on 1 or 2 lines, `: Definition` line) goes so
// that it keeps clear of the port labels inside the left and right edges that are level with
// it. Tried in this order, the first one that shows the whole name wins: centred on one line,
// centred on two lines, at the top on one line, at the top on two lines (the top is skipped
// when ports sit on the top edge). When none does, the widest place shows what fits.
// Returns {lines, top (y of the title block), max (width available to the text)}.
export function nameLayout(c, hasStereo, w, h, ports) {
  const height = n => (hasStereo ? 15 : 0) + n * NAME_LINE_H + (c.definition ? 13 : 0);
  const freeWidth = (y0, y1) => {
    const side = s => Math.max(0, ...ports.filter(pt => pt.p.side === s && pt.local.y + 7 > y0 && pt.local.y - 7 < y1)
      .map(pt => fit(pt.p.name, pt.labelWidth || 90, PORT_CHAR_W).length * PORT_CHAR_W + 14));
    return Math.max(40, w - 2 * Math.max(side("left"), side("right")) - 12);
  };
  const name = String(c.name ?? "");
  const hasTop = ports.some(pt => pt.p.side === "top");
  const tried = [];
  for (const [where, n] of [["centre", 1], ["centre", 2], ["top", 1], ["top", 2]]) {
    if (where === "top" && hasTop) continue;
    const top = where === "centre" ? (h - height(n)) / 2 : 6;
    const max = freeWidth(top, top + height(n));
    const lines = n === 1 ? [fit(name, max, NAME_CHAR_W)] : nameLines(name, max, NAME_CHAR_W);
    const option = { lines, top: where === "centre" ? (h - height(lines.length)) / 2 : top, max };
    if (!lines.some(l => l.endsWith("…") && !name.endsWith("…"))) return option;
    tried.push(option);
  }
  return tried.reduce((a, b) => (b.lines.join("").length > a.lines.join("").length ? b : a));
}

// A component block (group translated to its box) with its ports.
export function blockSvg(b, ports, opts = {}) {
  const { c, box, key } = b;
  const { sel, hl, filter } = opts;
  const w = box.w, h = box.h;
  const st = c.style || {};
  const cls = ["arch-block"];
  if (c.is_reference) cls.push("ref");
  if (sel?.has(key)) cls.push("sel");
  if (filter && !filter.ids.has(c.id)) cls.push(filter.hide ? "f-hidden" : "f-dim");
  const stereo = stereoText(c.stereotypes);
  const { lines, top, max: nameMax } = nameLayout(c, !!stereo, w, h, ports);
  const nameY = top + (stereo ? 15 : 0) + 11;
  const defY = nameY + (lines.length - 1) * NAME_LINE_H + 14;
  const fill = st.fill || (c.is_reference ? "#f4f8ff" : "#ffffff");
  const stroke = st.stroke || "#475569";
  const dash = st.dash ? ` stroke-dasharray="${esc(st.dash)}"` : "";
  const textColor = st.text || "#0f172a";
  const badges = (c.badges || []).filter(x => !HIDDEN_BADGES.has(x));
  let bx = w - 6;
  const pills = [];
  for (const t of badges) {
    const label = fit(t, 70, 5.4);
    const pw = 8 + label.length * 5.4;
    if (bx - pw < 24) break;
    bx -= pw;
    pills.push(`<g class="arch-pill" transform="translate(${r1(bx)},${h - 17})"><rect width="${r1(pw)}" height="12" rx="6"/>
      <text x="${r1(pw / 2)}" y="9" text-anchor="middle">${esc(label)}</text></g>`);
    bx -= 3;
  }
  const icon = st.icon && st.icon !== "reference" && [...st.icon].length <= 2
    ? `<text class="arch-icon" x="8" y="17">${esc(st.icon)}</text>` : "";
  return `<g class="${cls.join(" ")}${hlStyle(c.id, hl)}" data-kind="component" data-key="${esc(key)}" data-id="${esc(c.id)}"
      data-name="${esc(c.name)}" transform="translate(${r1(box.x)},${r1(box.y)})">
    <title>${esc(c.name)}${c.definition ? ` : ${esc(c.definition.name)} (reference)` : ""} — double-click to open</title>
    <rect class="arch-hl-ring" x="-5" y="-5" width="${w + 10}" height="${h + 10}" rx="10"/>
    <rect class="arch-body" width="${w}" height="${h}" rx="6" fill="${esc(fill)}" stroke="${esc(stroke)}"${dash}/>
    ${stereo ? `<text class="arch-stereo" x="${w / 2}" y="${r1(nameY - 15)}" text-anchor="middle">${esc(fit(stereo, w - 16, 5.6))}</text>` : ""}
    <text class="arch-name" data-role="name" x="${w / 2}" y="${r1(nameY)}" text-anchor="middle" fill="${esc(textColor)}">${lines.length === 1 ? esc(lines[0])
      : lines.map((l, i) => `<tspan x="${w / 2}" dy="${i ? NAME_LINE_H : 0}">${esc(l)}</tspan>`).join("")}</text>
    ${c.definition ? `<text class="arch-def" x="${w / 2}" y="${r1(defY)}" text-anchor="middle">${esc(fit(c.definition.name, nameMax, DEF_CHAR_W))}</text>` : ""}
    ${c.is_reference ? `<g class="arch-refmark" transform="translate(7,${h - 15})"><title>Reference component: ports and internals are shared by every usage of ${esc(c.definition?.name || "")}</title>
      <rect x="0" y="2" width="9" height="7" rx="3.5"/><rect x="5" y="2" width="9" height="7" rx="3.5"/></g>` : ""}
    ${c.has_children ? `<g class="arch-compmark" transform="translate(${w - 18},6)"><title>Composite: double-click to open</title>
      <rect width="12" height="9" rx="1.5"/><rect x="2.5" y="2.5" width="3" height="4"/><rect x="6.5" y="2.5" width="3" height="4"/></g>` : ""}
    ${icon}${pills.join("")}
    <path class="arch-resize" d="M${w - 10} ${h - 3} L${w - 3} ${h - 10} M${w - 6} ${h - 3} L${w - 3} ${h - 6}"/>
    <rect class="arch-resize-hit" data-role="resize" x="${w - 12}" y="${h - 12}" width="14" height="14"/>
    ${ports.map(pt => portSvg(pt, opts)).join("")}
  </g>`;
}

function connClasses(k, base, opts) {
  const cls = [base, `k-${k.c.kind}`];
  if (opts.sel?.has(k.key)) cls.push("sel");
  if (k.c.issues?.length) cls.push("bad");
  if (opts.filter && k.filtered) cls.push(opts.filter.hide ? "f-hidden" : "f-dim");
  return cls.join(" ") + hlStyle(k.c.id, opts.hl);
}

export const LABEL_MAX = 180;
// 10.5 px connector labels; a connector with a problem (incompatible interfaces, a structural
// issue) is marked with a warning sign next to its label.
export const labelText = c => fit(c.label && c.issues?.length ? `⚠ ${c.label}` : (c.label || ""), LABEL_MAX, 5.8);

// The connector line (drawn under the blocks).
export function connectorSvg(k, opts = {}) {
  const { c, pts, key, color } = k;
  const d = pathD(pts);
  const arrow = c.kind === "data" || c.kind === "client-server";
  const stroke = c.issues?.length ? "#dc2626" : color;
  const marker = arrow && opts.markers ? ` marker-end="url(#${opts.markers.id(stroke)})"` : "";
  const tip = [c.label || c.name, ...(c.issues || [])].filter(Boolean).join("\n");
  return `<g class="${connClasses(k, "arch-conn", opts)}" data-kind="connector" data-key="${esc(key)}" data-id="${esc(c.id)}">
    <title>${esc(tip)}</title>
    <path class="arch-conn-hit" d="${d}"/>
    <path class="arch-conn-line" d="${d}" stroke="${esc(stroke)}"${marker}/>
  </g>`;
}

// The connector label (drawn above the blocks so it stays readable); k.labelPos from
// geometry.labelPlacement.
export function connectorLabelSvg(k, opts = {}) {
  const text = labelText(k.c);
  if (!text || !k.labelPos) return "";
  const { x, y, anchor } = k.labelPos;
  return `<g class="${connClasses(k, "arch-clabel", opts)}" data-kind="connector" data-label-for="${esc(k.key)}" data-id="${esc(k.c.id)}">
    <text class="arch-conn-label" data-role="conn-label" x="${r1(x)}" y="${r1(y)}" text-anchor="${anchor}">${esc(text)}</text>
  </g>`;
}

export function frameSvg(scene, opts = {}) {
  const { frame: f, comp } = scene;
  const stereo = stereoText(comp.stereotypes);
  const kindText = comp.is_reference
    ? `: ${comp.definition?.name || ""} — shared by ${comp.shared_by} component(s)`
    : comp.kind === "PartDefinition" ? "architecture" : "inline component";
  const badges = (comp.badges || []).filter(x => !HIDDEN_BADGES.has(x));
  return `<g class="arch-frame" data-kind="frame" data-id="${esc(comp.id)}">
    <rect class="arch-frame-box" x="${r1(f.x)}" y="${r1(f.y)}" width="${r1(f.w)}" height="${r1(f.h)}" rx="8"/>
    <path class="arch-frame-head" d="M${r1(f.x)} ${r1(f.y + 28)} H${r1(f.x + f.w)}"/>
    <text class="arch-frame-title" data-role="frame-name" x="${r1(f.x + 12)}" y="${r1(f.y + 19)}">${stereo ? `<tspan class="arch-stereo">${esc(stereo)} </tspan>` : ""}${esc(comp.name)}<tspan class="arch-frame-sub" dx="8">${esc(kindText)}</tspan>${badges.length ? `<tspan class="arch-frame-sub" dx="8">[${esc(badges.join(", "))}]</tspan>` : ""}</text>
  </g>`;
}

export function frameBoxPath(f) {
  return { x: r1(f.x), y: r1(f.y), width: r1(f.w), height: r1(f.h) };
}

function r1(v) { return Math.round(v * 10) / 10; }
