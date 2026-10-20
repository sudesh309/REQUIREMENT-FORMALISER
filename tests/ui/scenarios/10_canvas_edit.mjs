// Canvas editing by mouse and keyboard: rubber-band selection, Group into Component,
// context menu Duplicate, Delete key + Ctrl+Z, Ctrl+C / Ctrl+V, resize from the corner,
// Shift+drag a port to another side, drop a connector on a block and on the frame edge
// (new ports), and drag a connector segment (manual route) then reset it.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, fresh, waitReady, expect, api }, step) {
  await fresh("CanvasEdit");
  const root = await api("POST", "/api/arch/architecture", { name: "Avionics" });
  const mk = async (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const adc = await mk("ADC", 140, 80), fms = await mk("FMS", 420, 80), disp = await mk("Display", 700, 80);
  await mk("IRS", 140, 300);
  await api("POST", "/api/arch/port", { owner: adc.id, name: "airData", direction: "out" });
  await api("POST", "/api/arch/port", { owner: fms.id, name: "air", direction: "in" });
  await api("POST", "/api/arch/port", { owner: fms.id, name: "route", direction: "out" });
  await api("POST", "/api/arch/port", { owner: disp.id, name: "route", direction: "in" });
  await api("POST", "/api/arch/connector", { composition: root.id, source: { component: adc.id, port: "airData" }, target: { component: fms.id, port: "air" } });
  await api("POST", "/api/arch/connector", { composition: root.id, source: { component: fms.id, port: "route" }, target: { component: disp.id, port: "route" } });
  await waitReady();
  await page.waitForSelector('.arch-block[data-name="IRS"]');

  const block = n => `.arch-block[data-name="${n}"]`;
  const view = () => api("GET", `/api/arch/view/${root.id}`);
  // The canvas re-renders after every saved edit: measure an element that is still attached.
  const box = async (sel) => {
    for (let i = 0; i < 40; i++) {
      const b = await (await page.waitForSelector(sel)).boundingBox();
      if (b) return b;
      await page.waitForTimeout(50);
    }
    throw new Error(`no bounding box for ${sel}`);
  };
  const names = () => page.$$eval(".arch-block", xs => xs.map(x => x.dataset.name).sort().join());
  const selected = () => page.$$eval(".arch-block.sel", xs => xs.map(x => x.dataset.name).sort().join());
  const drag = async (a, b, steps = 10) => {
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(a.x + 6, a.y + 6, { steps: 2 });
    await page.mouse.move(b.x, b.y, { steps });
    await page.mouse.up();
  };
  const until = async (fn, what) => {
    for (let i = 0; i < 80; i++) { const v = await fn(); if (v) return v; await page.waitForTimeout(75); }
    throw new Error(`timed out: ${what}`);
  };

  step("rubber band");
  // Rubber band around ADC and FMS (from empty canvas inside the frame).
  const a = await box(`${block("ADC")} .arch-body`), f = await box(`${block("FMS")} .arch-body`);
  await drag({ x: a.x - 25, y: a.y - 20 }, { x: f.x + f.width + 15, y: f.y + f.height + 20 });
  await page.waitForFunction(() => document.querySelectorAll(".arch-block.sel").length === 2);
  expect(await selected() === "ADC,FMS", `band selection: ${await selected()}`);

  step("group");
  // Group into Component from the toolstrip, then name it in place.
  await page.click('[data-canvas-act="group"]');
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  await page.fill(".arch-inline-edit", "AirDataUnit");
  await page.press(".arch-inline-edit", "Enter");
  await page.waitForSelector(`${block("AirDataUnit")} .arch-compmark`);
  expect(await names() === "AirDataUnit,Display,IRS", `grouped: ${await names()}`);
  expect((await view()).connectors.length === 1, "the crossing connector now leaves the new component");

  step("duplicate");
  // Context menu on IRS -> Duplicate.
  const irs = await box(`${block("IRS")} .arch-body`);
  await page.mouse.click(irs.x + 12, irs.y + 10, { button: "right" });
  await page.waitForSelector(".arch-menu:not([hidden])");
  await page.click('.arch-menu [data-menu-cmd="duplicate"]');
  await page.waitForSelector(block("IRS1"));
  expect(await selected() === "IRS1", "the copy is selected");

  step("delete+undo");
  // Delete key removes the selection; Ctrl+Z (studio shortcut) brings it back.
  await page.keyboard.press("Delete");
  await page.waitForFunction(s => !document.querySelector(s), block("IRS1"));
  await page.keyboard.press("Control+z");
  await page.waitForSelector(block("IRS1"));

  step("copy/paste");
  // Ctrl+C / Ctrl+V on the canvas.
  await page.mouse.click(irs.x + 12, irs.y + 10);
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains("sel"), block("IRS"));
  await page.keyboard.press("Control+c");
  await page.waitForSelector(".arch-toast");
  await page.waitForSelector('[data-canvas-act="paste"]:not([disabled])');
  await page.keyboard.press("Control+v");
  await page.waitForSelector(block("IRS2"));

  step("resize");
  // Resize Display from its bottom-right corner; the size is saved.
  const d = await box(`${block("Display")} .arch-body`);
  await drag({ x: d.x + d.width - 3, y: d.y + d.height - 3 }, { x: d.x + d.width + 77, y: d.y + d.height + 47 });
  const resized = await until(async () => {
    const c = (await view()).components.find(x => x.name === "Display");
    return c.sized && c.layout.w > 200 ? c : null;
  }, "resize saved");
  expect(resized.layout.h > 120, `resized: ${JSON.stringify(resized.layout)}`);

  step("port move");
  // Shift+drag Display.route to the top edge.
  const pr = await box(`${block("Display")} .arch-port[data-name="route"] .arch-port-glyph`);
  const d2 = await box(`${block("Display")} .arch-body`);
  await page.keyboard.down("Shift");
  await drag({ x: pr.x + pr.width / 2, y: pr.y + pr.height / 2 }, { x: d2.x + d2.width / 2, y: d2.y + 2 });
  await page.keyboard.up("Shift");
  await until(async () => (await view()).components.find(x => x.name === "Display").ports[0].side === "top", "port moved to top");
  expect((await api("GET", "/api/undo/state")).undo_label === "Move", "port move is one undo step");

  step("new port on block");
  // Drop a connector from AirDataUnit's output on IRS: a matching input port is created.
  const out = await box(`${block("AirDataUnit")} .arch-port[data-dir="out"] .arch-port-glyph`);
  const irsBox = await box(`${block("IRS")} .arch-body`);
  await drag({ x: out.x + out.width / 2, y: out.y + out.height / 2 }, { x: irsBox.x + 20, y: irsBox.y + irsBox.height / 2 });
  await page.waitForSelector(`${block("IRS")} .arch-port[data-dir="in"]`);
  step("new boundary port");
  // ... and on the frame's right edge: a boundary output port.
  const frame = await box(".arch-frame-box");
  await drag({ x: out.x + out.width / 2, y: out.y + out.height / 2 }, { x: frame.x + frame.width - 6, y: frame.y + frame.height / 2 });
  await page.waitForSelector('.arch-l-bports .arch-port[data-dir="out"]');
  const v = await view();
  expect(v.boundary_ports.length === 1 && v.connectors.length === 3, `new ports connected: ${v.connectors.length}`);

  step("route");
  // Select a connector by clicking its line, drag its middle segment, then reset the route.
  const conn = v.connectors.find(c => c.target.component_id === null);
  const pointOn = () => page.waitForFunction((id) => {        // a visible point on the connector
    const p = document.querySelector(`.arch-conn[data-id="${id}"] .arch-conn-hit`);
    if (!p) return null;
    const len = p.getTotalLength(), m = p.getScreenCTM();
    for (let f = 0.3; f < 0.95; f += 0.05) {
      const pt = p.getPointAtLength(len * f);
      const s = { x: pt.x * m.a + m.e, y: pt.y * m.d + m.f };
      if (document.elementFromPoint(s.x, s.y)?.closest(".arch-conn")?.dataset.id === id) return s;
    }
    return null;
  }, conn.id).then(h => h.jsonValue());
  let mid = await pointOn();
  await page.mouse.click(mid.x, mid.y);
  await page.waitForFunction(id => document.querySelector(`.arch-conn[data-id="${id}"]`)?.classList.contains("sel"), conn.id);
  const handle = await page.waitForSelector(".arch-seg");
  const hb = await box(".arch-seg");
  const horizontal = (await handle.getAttribute("style")).includes("ns-resize");
  await drag({ x: hb.x + hb.width / 2, y: hb.y + hb.height / 2 },
             horizontal ? { x: hb.x + hb.width / 2, y: hb.y + 60 } : { x: hb.x + 60, y: hb.y + hb.height / 2 });
  await until(async () => (await view()).connectors.find(c => c.id === conn.id).points, "route saved");
  await page.waitForFunction(() => document.querySelector(".arch-dock")?.textContent.includes("Manual"));
  mid = await pointOn();
  await page.mouse.click(mid.x, mid.y, { button: "right" });
  await page.waitForSelector('.arch-menu [data-menu-cmd="reset-route"]:not([disabled])');
  await page.click('.arch-menu [data-menu-cmd="reset-route"]');
  await until(async () => (await view()).connectors.find(c => c.id === conn.id).points === null, "route reset");

  step("escape");
  // Escape clears the selection; the dock then describes the architecture.
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector(".arch-l-conns .sel, .arch-block.sel"));
  expect((await page.textContent(".arch-dock")).includes("Architecture"), "dock shows the composition");
}
