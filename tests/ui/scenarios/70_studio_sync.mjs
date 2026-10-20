// Cross-cutting: an edit saved in one tab shows everywhere without a reload (PO-3, SU-8).
// A stereotype value typed in the Properties tab reaches the canvas Property Inspector
// (with its unit) and enables both Undo buttons; the Properties editor keeps its focus.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, fresh, waitReady, expect, api, errors }, step) {
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
  // A rejected value is reported in words (no HTTP method, route or id in the log).
  await page.fill(mass, "heavy");
  await page.press(mass, "Enter");
  await until(() => document.querySelector("#log .log-error"), null, "rejected value logged");
  const err = await page.textContent("#log .log-error");
  expect(!/\b(PATCH|POST)\b|\/api\/|[0-9a-f]{8}-[0-9a-f]{4}-/.test(err), `readable error: ${err}`);
  errors.splice(0);                // the browser reports the expected 400 on its console
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
  // Human-readable step names, no HTTP routes or ids (PO-5, SU-8).
  const tip = await page.getAttribute('button[data-plugin-button="undo"]', "title");
  expect(tip === "Undo Set Avionics.LRU.mass of FMS (Ctrl+Z)", `undo tooltip: ${tip}`);
  expect(await page.getAttribute('[data-canvas-act="undo"]', "title") === tip, "canvas Undo names the same step");

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

  step("group and name in place is one undo step");
  const names = () => page.$$eval(".arch-block", xs => xs.map(x => x.dataset.name).sort().join());
  await clickBlock("ADIRU");
  await page.keyboard.down("Control");
  await clickBlock("FMS");
  await page.keyboard.up("Control");
  await until(() => document.querySelectorAll(".arch-block.sel").length === 2, null, "two blocks selected");
  await page.keyboard.press("Control+g");
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  await page.keyboard.press("Control+a");
  await page.keyboard.type("CPM_Pair");
  await page.keyboard.press("Enter");
  await until(() => document.querySelector('.arch-block[data-name="CPM_Pair"]'), null, "group named in place");
  await until(() => /^Undo Group (ADIRU, FMS|FMS, ADIRU) into CPM_Pair \(Ctrl\+Z\)$/
    .test(document.querySelector('button[data-plugin-button="undo"]').title), null, "one step named after the group");
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press("Control+z");
  await until(() => [...document.querySelectorAll(".arch-block")].map(x => x.dataset.name).sort().join() === "ADIRU,FMS",
              null, "one Ctrl+Z removes the group (no 'Component' left)");
  expect(await names() === "ADIRU,FMS", `blocks after undo: ${await names()}`);
  // The Output log speaks of steps, not of HTTP requests.
  const log = await page.textContent("#log");
  expect(!/\b(GET|POST|PATCH|DELETE) \/api\//.test(log), "no HTTP routes in the Output log");
}
