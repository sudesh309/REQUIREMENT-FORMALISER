// Pure geometry for the architecture canvas (no DOM): port placement, orthogonal
// connector routing, frames, hit rectangles, zoom/pan maths. Unit-tested by
// tests/ui/10_canvas_geometry.test.mjs.

export const GRID = 10;            // snap step (model units)
export const PORT = 6;             // half size of a port glyph
export const STUB = 16;            // straight segment leaving a port before the first bend
export const FRAME_PAD = 70;       // frame margin around the components
export const FRAME_HEAD = 28;      // frame title band
export const MIN_W = 80;
export const MIN_H = 50;
export const ZOOM_MIN = 0.15;
export const ZOOM_MAX = 3;

export const NORMALS = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1] };

export const snap = (v, g = GRID) => Math.round(v / g) * g;
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// Point on a box edge for a port at {side, offset} (offset 0..1 along the edge).
export function portPoint(box, side, offset) {
  const o = clamp(Number.isFinite(offset) ? offset : 0.5, 0, 1);
  switch (side) {
    case "right": return { x: box.x + box.w, y: box.y + o * box.h };
    case "top": return { x: box.x + o * box.w, y: box.y };
    case "bottom": return { x: box.x + o * box.w, y: box.y + box.h };
    default: return { x: box.x, y: box.y + o * box.h };
  }
}

// Where a connector attaches to a port: just outside the glyph, with the direction the
// line leaves in. Boundary ports on the frame are reached from inside (inward = true).
export function attachPoint(box, side, offset, inward = false) {
  const p = portPoint(box, side, offset);
  const [nx, ny] = NORMALS[side] || NORMALS.left;
  const s = inward ? -1 : 1;
  return { x: p.x + nx * PORT * s, y: p.y + ny * PORT * s, nx: nx * s, ny: ny * s };
}

// Nearest edge of a box to a point, as {side, offset} (offset kept off the corners).
export function nearestSide(box, pt, margin = 0.06) {
  const d = {
    left: Math.abs(pt.x - box.x), right: Math.abs(pt.x - (box.x + box.w)),
    top: Math.abs(pt.y - box.y), bottom: Math.abs(pt.y - (box.y + box.h)),
  };
  const side = Object.keys(d).reduce((a, b) => (d[b] < d[a] ? b : a));
  const along = side === "left" || side === "right" ? (pt.y - box.y) / box.h : (pt.x - box.x) / box.w;
  return { side, offset: Math.round(clamp(along, margin, 1 - margin) * 100) / 100 };
}

export function bbox(boxes) {
  if (!boxes.length) return null;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const b of boxes) {
    x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
    x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h);
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

// The composition frame drawn around its components (boundary ports sit on its edges).
export function frameFor(boxes, { pad = FRAME_PAD, minW = 520, minH = 320 } = {}) {
  const b = bbox(boxes);
  if (!b) return { x: 40, y: 20, w: minW, h: minH };
  const x = b.x - pad, y = b.y - pad - FRAME_HEAD / 2;
  return { x, y, w: Math.max(minW, b.w + 2 * pad), h: Math.max(minH, b.h + 2 * pad + FRAME_HEAD / 2) };
}

export function union(a, b) {
  if (!a) return b;
  if (!b) return a;
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
}

export function rectFrom(p, q) {
  return { x: Math.min(p.x, q.x), y: Math.min(p.y, q.y), w: Math.abs(p.x - q.x), h: Math.abs(p.y - q.y) };
}

export function intersects(a, b) {
  return a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h;
}

export function inside(pt, r, pad = 0) {
  return pt.x >= r.x - pad && pt.x <= r.x + r.w + pad && pt.y >= r.y - pad && pt.y <= r.y + r.h + pad;
}

// Drop the zero-length and collinear points of an orthogonal polyline.
export function simplify(points) {
  const pts = [];
  for (const p of points) {
    const last = pts[pts.length - 1];
    if (last && Math.abs(last.x - p.x) < 0.01 && Math.abs(last.y - p.y) < 0.01) continue;
    pts.push({ x: p.x, y: p.y });
  }
  for (let i = pts.length - 2; i > 0; i--) {
    const a = pts[i - 1], b = pts[i], c = pts[i + 1];
    if ((Math.abs(a.x - b.x) < 0.01 && Math.abs(b.x - c.x) < 0.01)
        || (Math.abs(a.y - b.y) < 0.01 && Math.abs(b.y - c.y) < 0.01)) pts.splice(i, 1);
  }
  return pts;
}

// Add an elbow between two points that are not on one horizontal or vertical line.
function link(out, p, q, horizontalFirst) {
  if (Math.abs(p.x - q.x) < 0.01 || Math.abs(p.y - q.y) < 0.01) return;
  out.push(horizontalFirst ? { x: q.x, y: p.y } : { x: p.x, y: q.y });
}

// Orthogonal (elbow) route from attach point a to attach point b. Both carry the unit
// direction (nx, ny) the line leaves them in. `points` (stored interior points of a
// manual route) are kept and joined orthogonally; `avoid` boxes help backward routes.
export function route(a, b, { points = null, stub = STUB, avoid = [] } = {}) {
  const a1 = { x: a.x + a.nx * stub, y: a.y + a.ny * stub };
  const b1 = { x: b.x + b.nx * stub, y: b.y + b.ny * stub };
  const out = [{ x: a.x, y: a.y }, a1];
  if (points && points.length) {
    // Each bend turns perpendicular to the segment before it; the last one lines up
    // with the target's stub.
    let prev = a1, horiz = a.nx !== 0;
    for (const raw of points) {
      const q = { x: raw[0] ?? raw.x, y: raw[1] ?? raw.y };
      link(out, prev, q, !horiz);
      out.push(q);
      const before = out[out.length - 2];
      horiz = Math.abs(before.y - q.y) < 0.01 && Math.abs(before.x - q.x) >= 0.01 ? true
        : Math.abs(before.x - q.x) < 0.01 && Math.abs(before.y - q.y) >= 0.01 ? false : horiz;
      prev = q;
    }
    link(out, prev, b1, b.nx !== 0);
  } else {
    const ah = a.nx !== 0, bh = b.nx !== 0;
    if (ah && bh) {
      if (a.nx === -b.nx) {
        if ((b1.x - a1.x) * a.nx >= 0) {
          const mx = (a1.x + b1.x) / 2;
          out.push({ x: mx, y: a1.y }, { x: mx, y: b1.y });
        } else {
          const my = detourY(a, b, stub, avoid);
          out.push({ x: a1.x, y: my }, { x: b1.x, y: my });
        }
      } else {
        const mx = a.nx > 0 ? Math.max(a1.x, b1.x) : Math.min(a1.x, b1.x);
        out.push({ x: mx, y: a1.y }, { x: mx, y: b1.y });
      }
    } else if (!ah && !bh) {
      if (a.ny === -b.ny) {
        if ((b1.y - a1.y) * a.ny >= 0) {
          const my = (a1.y + b1.y) / 2;
          out.push({ x: a1.x, y: my }, { x: b1.x, y: my });
        } else {
          const mx = detourX(a, b, stub, avoid);
          out.push({ x: mx, y: a1.y }, { x: mx, y: b1.y });
        }
      } else {
        const my = a.ny > 0 ? Math.max(a1.y, b1.y) : Math.min(a1.y, b1.y);
        out.push({ x: a1.x, y: my }, { x: b1.x, y: my });
      }
    } else if (ah) {
      if ((b1.x - a1.x) * a.nx >= 0 && (a1.y - b1.y) * b.ny >= 0) out.push({ x: b1.x, y: a1.y });
      else out.push({ x: a1.x, y: b1.y });
    } else {
      if ((b1.y - a1.y) * a.ny >= 0 && (a1.x - b1.x) * b.nx >= 0) out.push({ x: a1.x, y: b1.y });
      else out.push({ x: b1.x, y: a1.y });
    }
  }
  out.push(b1, { x: b.x, y: b.y });
  return simplify(out);
}

function detourY(a, b, stub, avoid) {
  if (Math.abs(a.y - b.y) > 4 * stub && !avoid.length) return (a.y + b.y) / 2;
  const bottoms = [a.y, b.y, ...avoid.map(r => r.y + r.h)];
  return Math.max(...bottoms) + 2 * stub;
}

function detourX(a, b, stub, avoid) {
  if (Math.abs(a.x - b.x) > 4 * stub && !avoid.length) return (a.x + b.x) / 2;
  const rights = [a.x, b.x, ...avoid.map(r => r.x + r.w)];
  return Math.max(...rights) + 2 * stub;
}

export function pathD(points) {
  return points.map((p, i) => `${i ? "L" : "M"}${round1(p.x)} ${round1(p.y)}`).join(" ");
}

const round1 = v => Math.round(v * 10) / 10;

// Label anchor: the middle of the longest segment.
export function labelAnchor(points) {
  let best = null, len = -1;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    const l = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
    if (l > len) { len = l; best = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, horizontal: Math.abs(a.y - b.y) < 0.01 }; }
  }
  return best || { x: 0, y: 0, horizontal: true };
}

// Draggable segments of a route: every segment but the two port stubs.
export function segmentHandles(points) {
  const out = [];
  for (let i = 1; i < points.length - 2; i++) {
    const a = points[i], b = points[i + 1];
    out.push({ i, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, horizontal: Math.abs(a.y - b.y) < 0.01 });
  }
  return out;
}

// Move segment i perpendicular to itself; returns the interior points to store
// (everything between the two attach points).
export function moveSegment(points, i, dx, dy) {
  const pts = points.map(p => ({ ...p }));
  const a = pts[i], b = pts[i + 1];
  if (Math.abs(a.y - b.y) < 0.01) { a.y += dy; b.y += dy; } else { a.x += dx; b.x += dx; }
  return pts.slice(1, -1).map(p => [round1(p.x), round1(p.y)]);
}

// Zoom by `factor` keeping the screen point (cx, cy) fixed.
export function zoomAt(v, factor, cx, cy, min = ZOOM_MIN, max = ZOOM_MAX) {
  const zoom = clamp(v.zoom * factor, min, max);
  const k = zoom / v.zoom;
  return { zoom, panX: cx - (cx - v.panX) * k, panY: cy - (cy - v.panY) * k };
}

// Viewport that shows `r` (model units) inside a width x height screen area.
export function fitTransform(r, width, height, { pad = 40, maxZoom = 1, minZoom = ZOOM_MIN } = {}) {
  const zoom = clamp(Math.min((width - 2 * pad) / Math.max(r.w, 1), (height - 2 * pad) / Math.max(r.h, 1)),
                     minZoom, maxZoom);
  return { zoom, panX: (width - r.w * zoom) / 2 - r.x * zoom, panY: (height - r.h * zoom) / 2 - r.y * zoom };
}

// A free spot for a w x h box inside `area`, scanning rows from its top-left; falls back
// to the right of everything.
export function freeSpot(boxes, w, h, area, { gap = 30, step = GRID * 2 } = {}) {
  const ok = (x, y) => !boxes.some(b => intersects({ x: x - gap, y: y - gap, w: w + 2 * gap, h: h + 2 * gap }, b));
  if (area && area.w > w && area.h > h) {
    for (let y = snap(area.y); y + h <= area.y + area.h; y += step) {
      for (let x = snap(area.x); x + w <= area.x + area.w; x += step) {
        if (ok(x, y)) return { x, y };
      }
    }
  }
  const b = bbox(boxes);
  return b ? { x: snap(b.x + b.w + 2 * gap), y: snap(b.y) } : { x: 160, y: 60 };
}

// Stable colour for an interface without a profile colour.
export function hashColor(text) {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return `hsl(${h % 360} 62% 38%)`;
}

// Text that fits `maxWidth` pixels at roughly `charW` per character.
export function fit(text, maxWidth, charW = 6.4) {
  const s = String(text ?? "");
  const n = Math.floor(maxWidth / charW);
  if (n <= 1) return s ? "…" : "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// SVG path of a port glyph centred on (0, 0) on the `side` edge of its owner (a block, or
// the frame for a boundary port). An input's arrow points into the owner, an output's
// out of it, so a boundary input on the frame points into the composition it feeds;
// physical ports are diamonds, client ports circles and server ports squares.
export function glyphPath(kind, direction, side, s = PORT) {
  const [ox, oy] = NORMALS[side] || NORMALS.left;    // outward of the owner
  const px = -oy, py = ox;                            // perpendicular
  const P = (a, b) => `${round1(a)} ${round1(b)}`;
  if (kind === "physical") return `M${P(ox * s, oy * s)} L${P(px * s, py * s)} L${P(-ox * s, -oy * s)} L${P(-px * s, -py * s)} Z`;
  if (kind === "client") return `M${P(-s, 0)} A${s} ${s} 0 1 0 ${P(s, 0)} A${s} ${s} 0 1 0 ${P(-s, 0)} Z`;
  if (kind === "server") return `M${P(-s, -s)} H${round1(s)} V${round1(s)} H${round1(-s)} Z`;
  if (direction === "inout") {
    const t = 0.35, w = 0.75;
    return `M${P(ox * s, oy * s)} L${P(ox * s * t + px * s * w, oy * s * t + py * s * w)} `
      + `L${P(-ox * s * t + px * s * w, -oy * s * t + py * s * w)} L${P(-ox * s, -oy * s)} `
      + `L${P(-ox * s * t - px * s * w, -oy * s * t - py * s * w)} L${P(ox * s * t - px * s * w, oy * s * t - py * s * w)} Z`;
  }
  const ux = direction === "out" ? ox : -ox, uy = direction === "out" ? oy : -oy;
  const vx = -uy, vy = ux;
  return `M${P(ux * s, uy * s)} L${P(-ux * s + vx * s, -uy * s + vy * s)} L${P(-ux * s - vx * s, -uy * s - vy * s)} Z`;
}
