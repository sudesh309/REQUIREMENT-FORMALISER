// PO-8 / SU-12a: adding ports makes a block grow; it pushes the neighbours it would cover
// instead of hiding them, so no blocks intersect and every port stays reachable (a drag to
// the last port lands on that port, not on the block below).
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("Growth");
  const root = await api("POST", "/api/arch/architecture", { name: "Avionics" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  await mk("DisplayFlightData", 140, 80);
  await mk("Monitor", 460, 80);
  await mk("DistributePower", 140, 240);
  await mk("Recorder", 460, 240);
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 4);
  const block = n => `.arch-block[data-name="${n}"]`;
  const select = async (n) => {
    await page.click(`${block(n)} .arch-body`, { position: { x: 14, y: 12 } });
    await page.waitForFunction(s => document.querySelector(s)?.classList.contains("sel"), block(n));
  };
  const addPorts = async (n, dir, count) => {
    for (let i = 0; i < count; i++) {
      await select(n);
      const before = await page.$$eval(`${block(n)} .arch-port`, xs => xs.length);
      await page.click(`[data-canvas-act="add-port-${dir}"]`);
      await page.waitForSelector(".arch-inline-edit:not([hidden])");
      await page.press(".arch-inline-edit", "Escape");                  // keep the automatic name
      await page.waitForFunction(([s, k]) => document.querySelectorAll(`${s} .arch-port`).length === k + 1,
                                 [block(n), before]);
    }
  };
  const intersections = () => page.$$eval(".arch-block .arch-body", (rs) => {
    const bs = rs.map(r => ({ name: r.closest(".arch-block").dataset.name, b: r.getBoundingClientRect() }));
    const out = [];
    for (let i = 0; i < bs.length; i++) {
      for (let j = i + 1; j < bs.length; j++) {
        const a = bs[i].b, b = bs[j].b;
        if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) out.push(`${bs[i].name}/${bs[j].name}`);
      }
    }
    return out;
  });

  await addPorts("DisplayFlightData", "in", 10);
  expect((await intersections()).length === 0, `blocks intersect: ${await intersections()}`);
  const v = await api("GET", `/api/arch/view/${root.id}`);
  const lay = Object.fromEntries(v.components.map(c => [c.name, c.layout]));
  expect(lay.DistributePower.y >= lay.DisplayFlightData.y + lay.DisplayFlightData.h, "the block below was pushed down");
  expect(lay.Monitor.x === 460 && lay.Monitor.y === 80, "the block beside it stays");

  // Every port of the grown block is hit-testable at its glyph.
  const missed = await page.$$eval(`${block("DisplayFlightData")} .arch-port`, ps => ps.filter((p) => {
    const r = p.querySelector(".arch-port-glyph").getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest(".arch-port");
    return hit !== p;
  }).map(p => p.dataset.name));
  expect(!missed.length, `ports covered by another block: ${missed}`);

  // The repro: 8 outputs on the block below, then drag the last output to the last input.
  await addPorts("DistributePower", "out", 8);
  expect((await intersections()).length === 0, `blocks intersect after growing the lower block: ${await intersections()}`);
  await page.click('[data-canvas-act="fit"]');
  await page.waitForTimeout(100);
  const center = async (sel) => {
    const r = await (await page.$(sel)).boundingBox();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  };
  const from = await center(`${block("DistributePower")} .arch-port[data-name="Out7"] .arch-port-glyph`);
  const to = await center(`${block("DisplayFlightData")} .arch-port[data-name="In9"] .arch-port-glyph`);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 8, from.y - 8, { steps: 2 });
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 1);
  const k = (await api("GET", `/api/arch/view/${root.id}`)).connectors[0];
  const names = await api("GET", `/api/arch/view/${root.id}`).then(w => {
    const port = id => w.components.flatMap(c => c.ports).find(p => p.id === id)?.name;
    return `${port(k.source.port_id)}->${port(k.target.port_id)}`;
  });
  expect(names === "Out7->In9", `connected ${names}`);
  expect(!(await page.$(".arch-toast.error")), "no 'own component' error toast");
}
