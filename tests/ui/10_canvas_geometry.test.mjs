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

// Every segment of a route misses the interior of every block but its two ends; the ends
// are only touched by the port stubs.
const clear = (pts, others, ends = []) => !G.routeHits(pts, others, ends);

test("SU-5: a straight run through a block in between goes around it", () => {
  const adc = { x: 100, y: 100, w: 160, h: 90 }, fms = { x: 400, y: 90, w: 160, h: 110 }, fcc = { x: 700, y: 100, w: 160, h: 90 };
  const a = G.attachPoint(adc, "right", 0.5), b = G.attachPoint(fcc, "left", 0.5);
  assert.ok(G.routeHits(G.route(a, b), [fms]), "the plain route runs through FMS");
  const pts = G.route(a, b, { obstacles: [fms], avoid: [adc, fcc] });
  assert.ok(orthogonal(pts), JSON.stringify(pts));
  assert.ok(clear(pts, [fms], [adc, fcc]), JSON.stringify(pts));
  assert.deepEqual(pts[0], { x: a.x, y: a.y });
  assert.deepEqual(pts[pts.length - 1], { x: b.x, y: b.y });
  assert.ok(pts.length <= 6, `few bends: ${JSON.stringify(pts)}`);
  // the stubs leave and enter the ports straight
  assert.equal(pts[1].y, a.y);
  assert.equal(pts[pts.length - 2].y, b.y);
});

test("SU-5: boundary port to an inner block does not pass under the block in front", () => {
  const frame = { x: 0, y: 0, w: 900, h: 400 };
  const law = { x: 200, y: 140, w: 160, h: 100 }, monitor = { x: 520, y: 150, w: 160, h: 90 };
  const a = G.attachPoint(frame, "left", 0.5, true), b = G.attachPoint(monitor, "left", 0.5);
  const pts = G.route(a, b, { obstacles: [law], avoid: [monitor] });
  assert.ok(clear(pts, [law], [monitor]), JSON.stringify(pts));
  assert.ok(orthogonal(pts));
});

test("SU-5: backward and wrapped routes avoid every block", () => {
  // A 3 x 3 grid of blocks; connect the right edge of the last block of row 1 to the left
  // edge of the first block of row 3 (a wrapped band), and backwards inside a row.
  const boxes = [];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) boxes.push({ x: 100 + c * 260, y: 100 + r * 180, w: 160, h: 100 });
  const pairs = [[2, 6], [8, 0], [5, 3], [1, 7], [6, 2]];
  for (const [s, t] of pairs) {
    const a = G.attachPoint(boxes[s], "right", 0.5), b = G.attachPoint(boxes[t], "left", 0.5);
    const others = boxes.filter((_, i) => i !== s && i !== t);
    const pts = G.route(a, b, { obstacles: others, avoid: [boxes[s], boxes[t]] });
    assert.ok(orthogonal(pts), `${s}->${t} ${JSON.stringify(pts)}`);
    assert.ok(clear(pts, others, [boxes[s], boxes[t]]), `${s}->${t} crosses a block: ${JSON.stringify(pts)}`);
  }
});

test("SU-5: avoidance stays fast on a 60-block network", () => {
  const boxes = [];
  for (let r = 0; r < 6; r++) for (let c = 0; c < 10; c++) boxes.push({ x: 100 + c * 250, y: 100 + r * 170, w: 160, h: 100 });
  let seed = 3;
  const rnd = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  const t0 = performance.now();
  let crossing = 0;
  for (let k = 0; k < 200; k++) {
    const s = rnd(60), t = (s + 1 + rnd(59)) % 60;
    const a = G.attachPoint(boxes[s], "right", 0.3 + rnd(5) / 10), b = G.attachPoint(boxes[t], "left", 0.3 + rnd(5) / 10);
    const others = boxes.filter((_, i) => i !== s && i !== t);
    if (!clear(G.route(a, b, { obstacles: others, avoid: [boxes[s], boxes[t]] }), others)) crossing++;
  }
  const ms = performance.now() - t0;
  assert.equal(crossing, 0);
  assert.ok(ms < 1500, `200 routes took ${ms.toFixed(0)} ms`);
});

test("SU-5: avoidPath finds no way into a walled-off target", () => {
  const wall = [{ x: 0, y: 0, w: 300, h: 20 }, { x: 0, y: 180, w: 300, h: 20 }, { x: 0, y: 0, w: 20, h: 200 }, { x: 280, y: 0, w: 20, h: 200 }];
  assert.equal(G.avoidPath({ x: 150, y: 100 }, { x: 500, y: 100 }, 0, 0, wall), null);
  const p = G.avoidPath({ x: 400, y: 100 }, { x: 600, y: 300 }, 0, 0, []);
  assert.ok(p && orthogonal(p) && p.length <= 4, JSON.stringify(p));      // two bends at most
  assert.deepEqual([p[0], p[p.length - 1]], [{ x: 400, y: 100 }, { x: 600, y: 300 }]);
});

test("SU-5: fan-out trunk labels sit near the source and labels avoid each other", () => {
  const pts = [{ x: 0, y: 0 }, { x: 16, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 150 }, { x: 400, y: 150 }];
  const trunk = G.labelPlacement(pts, "AirDataWord", [], { fromStart: true });
  assert.ok(trunk.x < 200, JSON.stringify(trunk));
  const first = G.labelPlacement(pts, "AirDataWord", []);
  const second = G.labelPlacement(pts, "AirDataWord", [first.box]);
  assert.ok(!G.intersects(first.box, second.box), JSON.stringify([first, second]));
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

test("labels go beside the longest free segment", () => {
  const pts = [{ x: 0, y: 0 }, { x: 60, y: 0 }, { x: 60, y: 200 }, { x: 120, y: 200 }];
  const right = G.labelPlacement(pts, "NavData");                     // longest = the vertical one
  assert.deepEqual([right.x, right.anchor], [66, "start"]);
  const blocked = G.labelPlacement(pts, "NavData", [{ x: 64, y: 80, w: 100, h: 60 }]);
  assert.deepEqual([blocked.x, blocked.anchor], [54, "end"]);           // moved to the other side
  const h = G.labelPlacement([{ x: 0, y: 50 }, { x: 300, y: 50 }], "airBus1 : AirData");
  assert.deepEqual([h.x, h.y, h.anchor], [150, 45, "middle"]);
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

test("block names wrap at word boundaries instead of being cut (SU-12c)", () => {
  assert.deepEqual(G.nameLines("SensorSuite", 200), ["SensorSuite"]);
  assert.deepEqual(G.nameLines("FlightControlComputer", 120), ["FlightControl", "Computer"]);
  assert.deepEqual(G.nameLines("Air Data Unit", 60), ["Air Data", "Unit"]);
  assert.deepEqual(G.nameLines("FCC_LEFT_CHANNEL", 80), ["FCC_LEFT_", "CHANNEL"]);
  assert.deepEqual(G.nameLines("ADIRUFMSXX", 40), ["ADIRU", "FMSXX"]);        // no boundary: the middle
});

test("block title layout keeps clear of port labels (SU-12c)", async () => {
  const R = await import("../../webapp/static/plugins/canvas/render.js");
  const port = (name, side, y, w = 160) => ({ p: { name, side }, local: { x: 0, y }, labelWidth: Math.max(28, w / 2 - 16) });
  const c = { name: "DisplayFlightDataAndWarnings", definition: null };
  // A short name with short labels: centred on one line.
  const small = R.nameLayout({ name: "ADC", definition: null }, false, 160, 90, [port("airData", "right", 45)]);
  assert.deepEqual(small.lines, ["ADC"]);
  assert.ok(Math.abs(small.top + 7 - 45) < 1);
  // A long name level with long labels: moved above them, whole.
  const ports = [port("primaryFlightDisplayData", "left", 45, 320), port("warnings", "right", 45, 320)];
  const lay = R.nameLayout(c, false, 320, 90, ports);
  assert.equal(lay.lines.join(""), c.name);
  assert.ok(lay.top + 14 < 45 - 7, "above the port labels");
  // Ports on the top edge: the title stays centred (wrapped) rather than covering them.
  const top = R.nameLayout(c, false, 320, 90, [...ports, port("pwr", "top", 0, 320)]);
  assert.ok(top.top > 6);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log(`ok   ${name}`); }
  catch (e) { failed++; console.log(`FAIL ${name}\n${e.stack}`); }
}
process.exit(failed ? 1 : 0);
