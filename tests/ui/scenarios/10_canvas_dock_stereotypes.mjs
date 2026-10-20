// PO-4: the canvas's Property Inspector applies stereotypes and edits their typed values in
// place (number with unit and expression, enumeration, text, checkbox), with the profiles'
// checks and inline errors; with several components selected it applies, edits and removes
// for all of them, one undo step each.
export default async function (ctx) {
  const { page, api, fresh, waitReady, expect } = ctx;
  await fresh("DockStereotypes");
  const prof = await api("POST", "/api/profiles", { name: "Avionics" });
  await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "Equipment", applies_to: "Component", abstract: true });
  const lru = await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "LRU", applies_to: "Component" });
  for (const b of [{ name: "mass", type: "double", unit: "kg", min: 0 }, { name: "power", type: "double", unit: "W" },
                   { name: "dal", type: "enumeration", literals: ["A", "B", "C", "D", "E"] },
                   { name: "ataChapter", type: "string" }, { name: "ima", type: "boolean" }]) {
    await api("POST", `/api/stereotypes/${lru.id}/properties`, b);
  }
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const adiru = await mk("ADIRU", 60, 60);
  const fmc = await mk("FMC", 320, 60);
  const du = await mk("DU", 60, 240);
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 3);
  const depth = async () => (await api("GET", "/api/undo/state")).undo_depth;
  const values = async (c) => {
    const v = await api("GET", `/api/elements/${c.id}/stereotypes`);
    return Object.fromEntries((v.applied[0]?.groups || []).flatMap(g => g.properties).map(p => [p.name, p.value]));
  };
  const field = path => `.arch-dock [data-path="Avionics.LRU.${path}"]`;
  const click = (name, modifiers = []) => page.click(`.arch-block[data-name="${name}"] .arch-body`, { position: { x: 10, y: 10 }, modifiers });

  // One component: the Add list offers the applicable, non-abstract stereotypes.
  await click("ADIRU");
  await page.waitForSelector(".arch-dock [data-st-add]:not([disabled])");
  const offered = await page.$$eval(".arch-dock [data-st-add] option", os => os.map(o => o.textContent).filter(t => !t.endsWith("…")));
  expect(offered.join() === "Avionics.LRU", `offered: ${offered}`);
  let d = await depth();
  await page.selectOption(".arch-dock [data-st-add]", { label: "Avionics.LRU" });
  await page.waitForSelector(field("mass"));
  await page.waitForFunction(() => document.querySelector('.arch-block[data-name="ADIRU"] .arch-stereo')?.textContent.includes("LRU"));
  expect(await depth() === d + 1, "applying is one undo step");

  // Number with an expression; Tab keeps the focus in the next field (the dock is not rebuilt under it).
  await page.fill(field("mass"), "2*1.5");
  await page.press(field("mass"), "Tab");
  await page.waitForFunction(() => document.querySelector(".arch-dock [data-st-msg]")?.textContent.includes("mass"));
  await page.waitForTimeout(300);
  expect((await values(adiru)).mass === 3, "mass = 2*1.5 kg");
  expect(await page.evaluate(() => document.activeElement?.dataset.path) === "Avionics.LRU.power", "focus stays in the next field");
  // A unit of the wrong quantity is refused inline; nothing is stored.
  d = await depth();
  await page.fill(field("power"), "-5 kg");
  await page.press(field("power"), "Enter");
  await page.waitForSelector(`${field("power")}.pf-invalid`);
  const err = await page.textContent(".arch-dock [data-st-msg]");
  expect(/cannot convert kg/.test(err), `inline error: ${err}`);
  expect((await values(adiru)).power === null && await depth() === d, "refused value not stored");
  ctx.errors.length = 0;                       // the refused PATCH (400) is expected
  await page.fill(field("power"), "35");
  await page.press(field("power"), "Enter");
  await page.waitForFunction(s => !document.querySelector(s).classList.contains("pf-invalid"), field("power"));
  await page.selectOption(field("dal"), "C");
  await page.fill(field("ataChapter"), "34");
  await page.press(field("ataChapter"), "Enter");
  await page.check(field("ima"));
  await page.waitForFunction(() => document.querySelector(".arch-dock [data-st-msg]")?.textContent.includes("ima"));
  await page.waitForTimeout(300);
  const v1 = await values(adiru);
  expect(v1.power === 35 && v1.dal === "C" && v1.ataChapter === "34" && v1.ima === true, `values: ${JSON.stringify(v1)}`);

  // Several components: the stereotype on one of them is applied to the others in one step.
  await click("FMC");
  await click("DU", ["Shift"]);
  await click("ADIRU", ["Shift"]);
  await page.waitForSelector('.arch-dock [data-st-apply]');
  expect((await page.textContent(".arch-dock-stereo .arch-dock-sub")).includes("3 components"), "multi-selection heading");
  d = await depth();
  await page.click('.arch-dock [data-st-apply]');
  await page.waitForSelector(field("mass"));
  expect(await depth() === d + 1, "apply to all is one undo step");
  for (const c of [fmc, du]) expect((await values(c)).dal === "A", `${c.name} got «LRU» with its defaults`);
  // Differing values are shown as mixed; one entry sets all three (one undo step).
  expect(await page.getAttribute(field("mass"), "placeholder") === "Mixed: type a value for all", "mixed mass");
  expect(await page.$eval(field("ima"), e => e.indeterminate), "mixed checkbox");
  expect((await page.inputValue(field("dal"))) === "", "mixed enumeration");
  d = await depth();
  await page.fill(field("mass"), "4.5 kg");
  await page.press(field("mass"), "Enter");
  await page.waitForFunction(() => document.querySelector(".arch-dock [data-st-msg]")?.textContent.includes("on 3 components"));
  for (const c of [adiru, fmc, du]) expect((await values(c)).mass === 4.5, `${c.name} mass 4.5`);
  expect(await depth() === d + 1, "a multi-edit is one undo step");
  // A value refused for one of them is stored for none.
  await page.fill(field("power"), "1 kg");
  await page.press(field("power"), "Enter");
  await page.waitForSelector(`${field("power")}.pf-invalid`);
  expect((await values(adiru)).power === 35 && (await values(fmc)).power === null, "nothing stored");
  ctx.errors.length = 0;
  // Undo takes the multi-edit back; the dock shows the restored values.
  await page.click('[data-canvas-act="undo"]');
  await page.waitForFunction(() => document.querySelector(".arch-dock [data-path='Avionics.LRU.mass']")?.placeholder.startsWith("Mixed"));
  expect((await values(adiru)).mass === 3 && (await values(fmc)).mass === null, "undo restores every component");
  // Remove from all, one step.
  d = await depth();
  await page.click('.arch-dock [data-st-remove]');
  await page.waitForFunction(() => !document.querySelector(".arch-dock [data-path]"));
  for (const c of [adiru, fmc, du]) expect(!(await api("GET", `/api/elements/${c.id}/stereotypes`)).applied.length, `${c.name}: removed`);
  expect(await depth() === d + 1, "remove from all is one undo step");
  await page.waitForFunction(() => !document.querySelector('.arch-block[data-name="ADIRU"] .arch-stereo'));
}
