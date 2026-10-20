// SU-5: automatically routed connectors never run under a block that is not one of their
// ends (that would read as a false data flow), and connector labels are not drawn on
// blocks or on each other; the branches of a fan-out share one label.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("Routing");
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (composition, name, x, y) => api("POST", "/api/arch/component", { composition, name, layout: { x, y } });
  const port = (owner, name, direction) => api("POST", "/api/arch/port", { owner, name, direction });
  const word = await api("POST", "/api/element", { kind: "PortDefinition", name: "AirDataWord" });
  // (a) ADC left, FMS in the middle, FCC-L right, at about the same height.
  const adc = await mk(root.id, "ADC", 140, 100);
  const fms = await mk(root.id, "FMS", 440, 90);
  const fcc = await mk(root.id, "FCC-L", 760, 100);
  const air = await port(adc.id, "airData", "out");
  await api("PATCH", `/api/arch/port/${air.id}`, { interface: word.id });
  await port(fms.id, "route", "in");
  await port(fms.id, "guidance", "out");
  const fccAir = await port(fcc.id, "airData", "in");
  await api("PATCH", `/api/arch/port/${fccAir.id}`, { interface: word.id });
  // (b) inside FCC-L: ControlLaw and Monitor, both fed from the boundary airData.
  await mk(fcc.id, "ControlLaw", 200, 100);
  await mk(fcc.id, "Monitor", 520, 110);
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 3);

  const problems = () => page.evaluate(async () => {
    const G = await import("/static/plugins/canvas/geometry.js");
    const sc = studio.architecture.canvas.scene;
    const out = [];
    for (const k of sc.conns) {
      const ends = [k.a.owner, k.b.owner].filter(Boolean);
      const others = sc.blocks.filter(b => !ends.includes(b)).map(b => b.box);
      if (G.routeHits(k.pts, others, ends.map(b => b.box))) out.push(`${k.c.name} crosses a block: ${JSON.stringify(k.pts)}`);
    }
    const labels = [...document.querySelectorAll(".arch-clabel text")].map(t => t.getBoundingClientRect());
    const bodies = [...document.querySelectorAll(".arch-block .arch-body")].map(r => r.getBoundingClientRect());
    const hit = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    labels.forEach((l, i) => {
      if (bodies.some(b => hit(l, b))) out.push(`label ${i} on a block`);
      labels.slice(i + 1).forEach((m, j) => { if (hit(l, m)) out.push(`labels ${i} and ${i + j + 1} overlap`); });
    });
    return out;
  });

  // (a) Drag ADC.airData onto FCC-L.airData: the line goes around FMS, not through it.
  const center = async (sel) => {
    const r = await (await page.$(sel)).boundingBox();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  };
  const from = await center('.arch-block[data-name="ADC"] .arch-port[data-name="airData"] .arch-port-glyph');
  const to = await center('.arch-block[data-name="FCC-L"] .arch-port[data-name="airData"] .arch-port-glyph');
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 10, from.y + 4, { steps: 2 });
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 1);
  let bad = await problems();
  expect(!bad.length, `top level: ${bad.join("; ")}`);
  expect(await page.$$eval(".arch-clabel text", ts => ts.map(t => t.textContent).join()) === "AirDataWord", "label drawn once");

  // (b) Open FCC-L, connect its boundary airData to ControlLaw and to Monitor by dropping
  // on the blocks (new ports), then Arrange.
  await page.dblclick('.arch-block[data-name="FCC-L"] .arch-body', { position: { x: 30, y: 60 } });
  await page.waitForFunction(() => document.querySelector(".arch-frame-title")?.textContent.startsWith("FCC-L"));
  await page.click('[data-canvas-act="fit"]');
  for (const target of ["ControlLaw", "Monitor"]) {
    const n = await page.$$eval(".arch-conn", xs => xs.length);
    const a = await center('.arch-l-bports .arch-port[data-name="airData"] .arch-port-glyph');
    const box = await (await page.$(`.arch-block[data-name="${target}"] .arch-body`)).boundingBox();
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(a.x + 10, a.y + 4, { steps: 2 });
    await page.mouse.move(box.x + 12, box.y + box.height / 2, { steps: 12 });
    await page.mouse.up();
    await page.waitForFunction(k => document.querySelectorAll(".arch-conn").length === k + 1, n);
  }
  await page.click('[data-canvas-act="arrange"]');
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("Arranged FCC-L"));
  await page.waitForTimeout(150);
  bad = await problems();
  expect(!bad.length, `inside FCC-L after Arrange: ${bad.join("; ")}`);
  const labels = await page.$$eval(".arch-clabel text", ts => ts.map(t => t.textContent));
  expect(labels.length === 1 && labels[0] === "AirDataWord", `the fan-out has one label: ${labels}`);

  // Moving a block so that ControlLaw stands in the way re-routes around it once dropped.
  const law = await (await page.$('.arch-block[data-name="ControlLaw"] .arch-body')).boundingBox();
  const mon = await (await page.$('.arch-block[data-name="Monitor"] .arch-body')).boundingBox();
  await page.mouse.move(mon.x + 20, mon.y + 6);
  await page.mouse.down();
  await page.mouse.move(mon.x + 30, mon.y + 10, { steps: 2 });
  await page.mouse.move(law.x + law.width + 100, law.y + 6, { steps: 10 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelector('[data-canvas-act="undo"]')?.title.includes("Move"));
  await page.waitForTimeout(150);
  bad = await problems();
  expect(!bad.length, `after moving Monitor: ${bad.join("; ")}`);
}
