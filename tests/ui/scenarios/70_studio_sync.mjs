// Cross-cutting: an edit saved in one tab shows everywhere without a reload (PO-3, SU-8).
// A stereotype value typed in the Properties tab reaches the canvas Property Inspector
// (with its unit) and enables both Undo buttons; the Properties editor keeps its focus.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, fresh, waitReady, expect, api }, step) {
  await fresh("StudioSync");
  const prof = await api("POST", "/api/profiles", { name: "Avionics" });
  const lru = await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "LRU", applies_to: "Component" });
  await api("POST", `/api/stereotypes/${lru.id}/properties`, { name: "mass", type: "double", unit: "kg", default: 4.5 });
  await api("POST", `/api/stereotypes/${lru.id}/properties`, { name: "power", type: "double", unit: "W", default: 0 });
  const root = await api("POST", "/api/arch/architecture", { name: "AircraftAvionics" });
  const mk = (name, x) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y: 100 } });
  const fms = await mk("FMS", 140);
  await mk("ADIRU", 460);
  await api("POST", `/api/elements/${fms.id}/stereotypes`, { stereotype: "Avionics.LRU" });
  await waitReady();
  await page.waitForSelector('.arch-block[data-name="FMS"]');
  const until = (fn, arg, what) => page.waitForFunction(fn, arg, { timeout: 10000 })
    .catch(() => { throw new Error(`timed out: ${what}`); });
  // Click a block on its body, away from the name label.
  const clickBlock = async (name) => {
    const b = await (await page.waitForSelector(`.arch-block[data-name="${name}"] .arch-body`)).boundingBox();
    await page.mouse.click(b.x + 14, b.y + b.height - 12);
  };
  const dockMass = () => page.$eval('.arch-dock [data-stereo-value="mass"] b', el => el.textContent.trim());

  step("dock shows units");
  await clickBlock("FMS");
  await page.waitForSelector('.arch-dock [data-stereo-value="mass"]');
  expect(await dockMass() === "4.5 kg", `mass with its unit in the dock: ${await dockMass()}`);

  step("edit in the Properties tab");
  await page.click('.arch-dock [data-dock-act="properties"]');
  const mass = '[data-section="stereotypes"] [data-path="Avionics.LRU.mass"]';
  await page.waitForSelector(mass);
  const before = (await api("GET", "/api/undo/state")).undo_depth;
  await page.fill(mass, "7");
  await page.press(mass, "Tab");                       // commit and move on to power
  await until(() => document.querySelector('[data-section="stereotypes"] [data-path="Avionics.LRU.mass"]')?.dataset.orig === "7",
              null, "mass stored");
  // The editor keeps the keyboard focus (no re-render under the user's fingers).
  expect(await page.evaluate(() => document.activeElement?.dataset.path) === "Avionics.LRU.power",
         "focus moved on to the next value and stayed there");
  const st = await api("GET", `/api/elements/${fms.id}/stereotypes`);
  expect(st.applied[0].groups[0].properties.find(p => p.name === "mass").value === 7, "stored 7 kg");

  step("undo buttons refresh");
  expect((await api("GET", "/api/undo/state")).undo_depth === before + 1, "one undo step");
  await until(() => !document.querySelector('button[data-plugin-button="undo"]').disabled, null,
              "studio Undo enabled after a Properties-tab edit");
  await until(() => !document.querySelector('[data-canvas-act="undo"]').disabled, null,
              "canvas Undo enabled after a Properties-tab edit");

  step("canvas dock is current");
  await page.click('.tab[data-tab="architecture"]');
  await until(() => document.querySelector('.arch-dock [data-stereo-value="mass"] b')?.textContent.trim() === "7 kg",
              null, "dock shows the new mass without a reload");
  await clickBlock("ADIRU");
  await clickBlock("FMS");
  await until(() => document.querySelector('.arch-dock [data-stereo-value="mass"] b')?.textContent.trim() === "7 kg",
              null, "dock shows the new mass after reselecting");

  step("undo from the canvas");
  await page.click('[data-canvas-act="undo"]');
  await until(() => document.querySelector('.arch-dock [data-stereo-value="mass"] b')?.textContent.trim() === "4.5 kg",
              null, "undo restored the mass in the dock");
}
