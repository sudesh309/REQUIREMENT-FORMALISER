// Unit tests for webapp/static/plugins/canvas/geometry.js (run: node tests/ui/10_canvas_geometry.test.mjs).
// Run by tests/test_architecture_canvas.py; exits non-zero on the first failure.
import assert from "node:assert/strict";
import * as G from "../../webapp/static/plugins/canvas/geometry.js";

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const orthogonal = pts => pts.every((p, i) => i === 0
  || Math.abs(p.x - pts[i - 1].x) < 0.01 || Math.abs(p.y - pts[i - 1].y) < 0.01);

test("port points and attach points", () => {
  const box = { x: 100, y: 50, w: 160, h: 90 };
  assert.deepEqual(G.portPoint(box, "left", 0.5), { x: 100, y: 95 });
  assert.deepEqual(G.portPoint(box, "right", 0), { x: 260, y: 50 });
  assert.deepEqual(G.portPoint(box, "top", 0.25), { x: 140, y: 50 });
  assert.deepEqual(G.portPoint(box, "bottom", 1), { x: 260, y: 140 });
  const a = G.attachPoint(box, "right", 0.5);
  assert.deepEqual([a.x, a.y, a.nx, a.ny], [266, 95, 1, 0]);
  const inward = G.attachPoint(box, "right", 0.5, true);      // boundary port reached from inside
  assert.deepEqual([inward.x, inward.nx], [254, -1]);
});

test("nearest side keeps ports off the corners", () => {
  const box = { x: 0, y: 0, w: 100, h: 100 };
  assert.deepEqual(G.nearestSide(box, { x: 98, y: 40 }), { side: "right", offset: 0.4 });
  assert.deepEqual(G.nearestSide(box, { x: 50, y: -20 }), { side: "top", offset: 0.5 });
  assert.equal(G.nearestSide(box, { x: -5, y: 500 }).offset, 0.94);
});

test("facing ports get a Z route", () => {
  const a = { x: 266, y: 95, nx: 1, ny: 0 }, b = { x: 394, y: 135, nx: -1, ny: 0 };
  const pts = G.route(a, b);
  assert.ok(orthogonal(pts));
  assert.equal(pts.length, 4);
  assert.deepEqual(pts[0], { x: 266, y: 95 });
  assert.deepEqual(pts[pts.length - 1], { x: 394, y: 135 });
  assert.equal(pts[1].x, 330);
  assert.equal(G.route(a, { ...b, y: 95 }).length, 2);         // straight line
});

test("backward route detours below the boxes", () => {
  const a = { x: 400, y: 100, nx: 1, ny: 0 }, b = { x: 100, y: 110, nx: -1, ny: 0 };
  const avoid = [{ x: 250, y: 50, w: 150, h: 100 }, { x: 100, y: 60, w: 150, h: 100 }];
  const pts = G.route(a, b, { avoid });
  assert.ok(orthogonal(pts));
  assert.ok(Math.max(...pts.map(p => p.y)) > 160, JSON.stringify(pts));
});

test("Z routes bend around other blocks", () => {
  const a = { x: 230, y: 100, nx: 1, ny: 0 }, b = { x: 700, y: 200, nx: -1, ny: 0 };
  const block = { x: 430, y: 60, w: 160, h: 100 };              // straddles the middle
  const pts = G.route(a, b, { obstacles: [block] });
  assert.ok(orthogonal(pts));
  for (let i = 0; i < pts.length - 1; i++) {
    assert.ok(!G.segmentHits(pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y, [block], 0), JSON.stringify(pts));
  }
  assert.equal(G.route(a, b).length, 4);
  assert.equal(G.segmentHits(0, 0, 100, 0, [{ x: 40, y: -5, w: 10, h: 10 }]), true);
  assert.equal(G.segmentHits(0, 0, 100, 0, [{ x: 40, y: 20, w: 10, h: 10 }]), false);
});

test("mixed and vertical sides stay orthogonal", () => {
  for (const [an, bn] of [[[1, 0], [0, -1]], [[0, 1], [-1, 0]], [[0, 1], [0, -1]], [[0, -1], [0, -1]], [[1, 0], [1, 0]]]) {
    const pts = G.route({ x: 0, y: 0, nx: an[0], ny: an[1] }, { x: 200, y: 150, nx: bn[0], ny: bn[1] });
    assert.ok(orthogonal(pts), JSON.stringify({ an, bn, pts }));
  }
});

test("manual route points are kept and joined orthogonally", () => {
  const a = { x: 0, y: 0, nx: 1, ny: 0 }, b = { x: 300, y: 200, nx: -1, ny: 0 };
  const pts = G.route(a, b, { points: [[100, 0], [100, 250], [250, 250]] });
  assert.ok(orthogonal(pts), JSON.stringify(pts));
  assert.ok(pts.some(p => p.x === 100 && p.y === 250));
  assert.deepEqual(pts[pts.length - 1], { x: 300, y: 200 });
});

test("segment handles and moving a segment", () => {
  const pts = G.route({ x: 0, y: 0, nx: 1, ny: 0 }, { x: 200, y: 100, nx: -1, ny: 0 });
  const handles = G.segmentHandles(pts);
  assert.equal(handles.length, 1);
  assert.equal(handles[0].horizontal, false);
  const stored = G.moveSegment(pts, handles[0].i, 40, 999);
  assert.deepEqual(stored, [[140, 0], [140, 100]]);
  const again = G.route({ x: 0, y: 0, nx: 1, ny: 0 }, { x: 200, y: 100, nx: -1, ny: 0 }, { points: stored });
  assert.deepEqual(again.map(p => [p.x, p.y]), [[0, 0], [140, 0], [140, 100], [200, 100]]);
});

test("frame, bbox and rubber band helpers", () => {
  const boxes = [{ x: 160, y: 60, w: 160, h: 90 }, { x: 430, y: 220, w: 160, h: 90 }];
  const f = G.frameFor(boxes);
  for (const b of boxes) assert.ok(G.inside({ x: b.x, y: b.y }, f) && G.inside({ x: b.x + b.w, y: b.y + b.h }, f));
  assert.deepEqual(G.frameFor([]), { x: 40, y: 20, w: 520, h: 320 });
  const band = G.rectFrom({ x: 500, y: 300 }, { x: 150, y: 50 });
  assert.deepEqual(band, { x: 150, y: 50, w: 350, h: 250 });
  assert.ok(G.intersects(band, boxes[0]) && G.intersects(band, boxes[1]));
  assert.ok(!G.intersects({ x: 0, y: 0, w: 10, h: 10 }, boxes[0]));
});

test("zoom keeps the cursor point fixed; fit centres the content", () => {
  const v = { zoom: 1, panX: 10, panY: 20 };
  const z = G.zoomAt(v, 2, 110, 120);
  assert.equal(z.zoom, 2);
  assert.deepEqual([(110 - z.panX) / z.zoom, (120 - z.panY) / z.zoom], [100, 100]);
  assert.equal(G.zoomAt(v, 1000, 0, 0).zoom, G.ZOOM_MAX);
  const f = G.fitTransform({ x: 0, y: 0, w: 1000, h: 500 }, 600, 400, { pad: 50 });
  assert.equal(f.zoom, 0.5);
  assert.deepEqual([f.panX, f.panY], [50, 75]);
});

test("free spot avoids existing boxes", () => {
  const boxes = [{ x: 160, y: 60, w: 160, h: 90 }];
  const p = G.freeSpot(boxes, 160, 90, { x: 100, y: 40, w: 800, h: 500 });
  assert.ok(!G.intersects({ ...p, w: 160, h: 90 }, boxes[0]));
  assert.deepEqual(G.freeSpot([], 160, 90, null), { x: 160, y: 60 });
});

test("glyphs: inputs point in, outputs point out", () => {
  const tip = d => d.match(/^M(-?[\d.]+) (-?[\d.]+)/).slice(1).map(Number);
  assert.deepEqual(tip(G.glyphPath("data", "in", "left")), [6, 0]);      // into the block / frame (right)
  assert.deepEqual(tip(G.glyphPath("data", "out", "left")), [-6, 0]);    // out of the block (left)
  assert.deepEqual(tip(G.glyphPath("data", "out", "right")), [6, 0]);    // boundary output leaves the frame
  assert.deepEqual(tip(G.glyphPath("data", "in", "top")), [0, 6]);       // pointing down, into the owner
  assert.ok(G.glyphPath("physical", "inout", "top").endsWith("Z"));
  assert.ok(G.glyphPath("client", "inout", "right").includes("A"));
});

test("text fitting, snapping and colours", () => {
  assert.equal(G.fit("FlightManagementSystem", 64), "FlightMan…");
  assert.equal(G.fit("ADC", 64), "ADC");
  assert.equal(G.snap(104), 100);
  assert.equal(G.hashColor("AirData"), G.hashColor("AirData"));
  assert.notEqual(G.hashColor("AirData"), G.hashColor("Power28V"));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`ok   ${name}`); }
  catch (e) { failed++; console.log(`FAIL ${name}\n${e.stack}`); }
}
process.exit(failed ? 1 : 0);
