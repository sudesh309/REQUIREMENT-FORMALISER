// SU-12 c/e/f: block names are shown whole (on one or two lines, moved above the port
// labels when these leave no room in the middle) and so are reference definition names;
// a pasted copy is placed where it covers no block; Load JSON fits the loaded model
// instead of keeping the previous zoom.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("Readability");
  const root = await api("POST", "/api/arch/architecture", { name: "Avionics" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const port = (owner, name, direction) => api("POST", "/api/arch/port", { owner, name, direction });
  const sens = await mk("SensorSuite", 60, 60);
  const fcc = await mk("FlightControlComputer", 320, 60);
  const disp = await mk("DisplayFlightDataAndWarnings", 60, 260);
  await mk("FCC-R", 420, 260);
  for (const n of ["airData", "inertial"]) await port(sens.id, n, "out");
  for (const n of ["airData", "inertial"]) await port(fcc.id, n, "in");
  await port(fcc.id, "surfaceCmd", "out");
  await port(disp.id, "primaryFlightDisplayData", "in");
  await port(disp.id, "warnings", "out");
  await api("POST", "/api/arch/save-as-reference", { component: fcc.id, name: "FlightControlComputerUnit" });
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 4);
  await page.click('[data-canvas-act="fit"]');

  // (c) Every name and definition name is complete (no ellipsis) and inside its block.
  const shown = await page.$$eval(".arch-block", bs => bs.map((b) => {
    const body = b.querySelector(".arch-body").getBoundingClientRect();
    const name = b.querySelector(".arch-name");
    const r = name.getBoundingClientRect();
    const labels = [...b.querySelectorAll(".arch-port-label")].map(l => l.getBoundingClientRect());
    return { block: b.dataset.name, name: name.textContent, def: b.querySelector(".arch-def")?.textContent ?? null,
             inside: r.left >= body.left && r.right <= body.right && r.top >= body.top && r.bottom <= body.bottom,
             clash: labels.some(l => l.left < r.right && r.left < l.right && l.top < r.bottom && r.top < l.bottom) };
  }));
  for (const s of shown) {
    expect(s.name.replace(/\s/g, "") === s.block.replace(/\s/g, ""), `name of ${s.block} shown as ${JSON.stringify(s.name)}`);
    expect(s.inside, `name of ${s.block} inside its block`);
    expect(!s.clash, `name of ${s.block} clear of its port labels`);
  }
  expect(shown.find(s => s.block === "FlightControlComputer").def === "FlightControlComputerUnit",
         `definition name: ${JSON.stringify(shown)}`);

  // (f) Copy + paste: the copy covers no block (it used to land 30 px off the original).
  await page.click('.arch-block[data-name="SensorSuite"] .arch-body', { position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 5);
  const v = await api("GET", `/api/arch/view/${root.id}`);
  const boxes = v.components.map(c => ({ n: c.name, ...c.layout }));
  const copy = boxes.find(b => b.n === "SensorSuite1");
  const covered = boxes.filter(b => b !== copy && b.x < copy.x + copy.w && copy.x < b.x + b.w && b.y < copy.y + copy.h && copy.y < b.y + b.h);
  expect(!covered.length, `pasted copy covers ${covered.map(b => b.n)}`);

  // (e) Zoom far out, then Load JSON: the loaded model is fitted, not shown at the old zoom.
  await page.click('[data-canvas-act="fit"]');
  const fitted = await page.textContent(".arch-zoom");
  for (let i = 0; i < 6; i++) await page.click('[data-canvas-act="zoom-out"]');
  const small = await page.textContent(".arch-zoom");
  expect(parseInt(small, 10) < parseInt(fitted, 10), `zoomed out: ${small} < ${fitted}`);
  const saved = (await api("GET", "/api/save")).text;
  await page.click('header [data-cmd="load"]');
  await page.waitForSelector("#modal-root [data-unsaved-warning]");          // the paste is unsaved
  const chooser = page.waitForEvent("filechooser");
  await page.click("#modal-root [data-modal-submit]");
  await (await chooser).setFiles({ name: "project.json", mimeType: "application/json", buffer: Buffer.from(saved) });
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("Loaded project"));
  await page.waitForFunction(z => document.querySelector(".arch-zoom")?.textContent !== z, small, { timeout: 5000 });
  const after = await page.textContent(".arch-zoom");
  expect(after === fitted, `after Load the view is fitted (${after}, fit ${fitted}, before ${small})`);
}
