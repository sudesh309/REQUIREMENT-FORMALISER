// SU-15: a reference component (typed by a definition) shows the stereotypes and values of its
// definition marked as inherited, lets the user override a value and reset it to the inherited
// one, in the Properties tab and in the canvas's Property Inspector. SU-11: the dock shows values
// with their unit and rounded (4.5359237 kg -> 4.54 kg) while the stored precision stays.
// PO-13: the Profile Editor offers the AllocationSet category.
export default async function ({ page, fresh, waitReady, expect, api, errors }) {
  await fresh("ProfilesInheritance");
  const prof = await api("POST", "/api/profiles", { name: "Avionics" });
  const lru = await api("POST", `/api/profiles/${prof.id}/stereotypes`,
                        { name: "LRU", applies_to: "Component", style: { fill: "#ffeeaa", icon: "computer" } });
  for (const b of [{ name: "mass", type: "double", unit: "kg", default: 1.5, min: 0 },
                   { name: "dal", type: "enumeration", literals: ["A", "B", "C", "D", "E"] }])
    await api("POST", `/api/stereotypes/${lru.id}/properties`, b);
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const fccDef = await api("POST", "/api/arch/architecture", { name: "FCC" });
  await api("POST", `/api/elements/${fccDef.id}/stereotypes`,
            { stereotype: lru.id, values: { mass: 3, dal: "A" } });
  const mk = (name, x, y, definition) => api("POST", "/api/arch/component",
    { composition: root.id, name, definition, layout: { x, y } });
  const fcc1 = await mk("fcc1", 60, 60, fccDef.id);
  const fcc2 = await mk("fcc2", 340, 60, fccDef.id);
  const plain = await mk("plain", 60, 240);
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 3);
  const until = (fn, arg) => page.waitForFunction(fn, arg, { timeout: 10000 });
  const depth = async () => (await api("GET", "/api/undo/state")).undo_depth;
  const label = async () => (await api("GET", "/api/undo/state")).undo_label;
  const props = async (c) => {
    const v = await api("GET", `/api/elements/${c.id}/stereotypes`);
    return Object.fromEntries((v.applied[0]?.groups || []).flatMap(g => g.properties).map(p => [p.name, p]));
  };
  const tree = id => `#tree .tree-node[data-id="${id}"] > .row`;

  // --- Properties tab: inherited values, marked, read from the definition -----------------------
  await page.click('.tab[data-tab="properties"]');
  await page.click(tree(fcc1.id));
  const mass = '[data-section="stereotypes"] [data-path="Avionics.LRU.mass"]';
  const dal = '[data-section="stereotypes"] [data-path="Avionics.LRU.dal"]';
  await page.waitForSelector(mass);
  expect(await page.inputValue(mass) === "3", "fcc1 shows the definition's mass");
  expect(await page.inputValue(dal) === "A", "and its dal");
  const head = await page.textContent('[data-section="stereotypes"] .pf-app > summary');
  expect(head.includes("«Avionics.LRU»") && head.includes("inherited from FCC"), `group marked inherited: ${head}`);
  expect(await page.$eval(mass, e => e.classList.contains("pf-inh")), "an inherited value is styled as such");
  expect((await page.textContent('[data-section="stereotypes"] [data-note-for="Avionics.LRU.mass"]')).includes("inherited"), "note under the value");
  expect(await page.$('[data-section="stereotypes"] [data-pf=remove]') === null, "an inherited stereotype has no remove button");
  expect(await page.$eval('[data-section="stereotypes"] [data-pf=remove-all]', b => b.disabled), "nothing of its own to remove");
  expect(await page.$eval('[data-section="stereotypes"] [data-pf=add-stereotype]', s => s.disabled), "nothing left to add: LRU is already carried");
  const badge = `${tree(fcc1.id)} > .tree-badge.pf-badge`;
  await page.waitForSelector(badge);
  expect(await page.$eval(badge, b => b.classList.contains("pf-badge-inh") && b.textContent.includes("LRU")), "the tree shows the inherited «LRU» badge");

  // --- override one value (unit-aware), the other stays inherited ---------------------------------
  let d = await depth();
  await page.fill(mass, "10 lb");
  await page.press(mass, "Enter");
  await until(() => document.querySelector('[data-section="stereotypes"] [data-note-for="Avionics.LRU.mass"] .pf-reset'));
  let p = await props(fcc1);
  expect(p.mass.value === 4.5359237 && p.mass.origin === "own" && p.mass.overridden, `mass overridden ${JSON.stringify(p.mass)}`);
  expect(p.dal.origin === "inherited" && p.dal.value === "A", "dal still inherited");
  expect(await depth() === d + 1, "the override is one undo step");
  expect(await label() === "Set Avionics.LRU.mass of fcc1", `undo label: ${await label()}`);
  expect(await page.inputValue(mass) === "4.5359237", "the Properties tab shows the stored precision");
  expect(await page.$eval(mass, e => e.classList.contains("pf-ovr") && !e.classList.contains("pf-inh")), "styled as overridden");
  const note = await page.textContent('[data-section="stereotypes"] [data-note-for="Avionics.LRU.mass"]');
  expect(note.includes("overridden") && note.includes("FCC has 3 kg"), `note: ${note}`);
  expect((await props(fcc2)).mass.value === 3 && (await props(fccDef)).mass.value === 3, "other users of the definition unchanged");
  const gtag = await page.textContent('[data-section="stereotypes"] .pf-app > summary');
  expect(gtag.includes("overrides FCC"), `group now an override: ${gtag}`);
  expect(await page.$('[data-section="stereotypes"] [data-pf=remove]') !== null, "the override can be removed");

  // --- the definition changes: the inherited dal follows, the override does not ---------------------
  await api("PATCH", `/api/elements/${fccDef.id}/stereotypes`, { values: { "Avionics.LRU.dal": "D", "Avionics.LRU.mass": 9 } });
  const massIs = (value) => until(v => document.querySelector('[data-section="stereotypes"] [data-path="Avionics.LRU.mass"]')?.value === v, value);
  await page.click(tree(fcc2.id));
  await massIs("9");
  expect(await page.inputValue(dal) === "D", "fcc2 follows the definition (mass and dal)");
  await page.click(tree(fcc1.id));
  await massIs("4.5359237");
  expect(await page.inputValue(dal) === "D", "fcc1 follows the definition's dal but keeps its mass override");

  // --- reset to inherited -----------------------------------------------------------------------------
  d = await depth();
  await page.click('[data-section="stereotypes"] [data-reset="Avionics.LRU.mass"]');
  await until(() => document.querySelector('[data-section="stereotypes"] [data-path="Avionics.LRU.mass"]')?.value === "9");
  p = await props(fcc1);
  expect(p.mass.origin === "inherited" && p.mass.value === 9, `reset: ${JSON.stringify(p.mass)}`);
  expect(await depth() === d + 1 && await label() === "Reset Avionics.LRU.mass of fcc1 to the inherited value", `reset step: ${await label()}`);
  expect((await page.textContent('[data-section="stereotypes"] .pf-app > summary')).includes("inherited from FCC"), "inherited again");
  expect((await api("GET", `/api/elements/${fcc1.id}/stereotypes`)).applied[0].overridden === false, "the empty override is gone");

  // --- canvas Property Inspector: rounding, units, override and reset -----------------------------------
  await page.click('.tab[data-tab="architecture"]');
  await page.waitForSelector('.arch-block[data-name="fcc1"]');
  await page.click('.arch-block[data-name="fcc1"] .arch-body', { position: { x: 10, y: 10 } });
  const dmass = '.arch-dock [data-path="Avionics.LRU.mass"]';
  await page.waitForSelector(dmass);
  expect(await page.inputValue(dmass) === "9", "the dock shows the inherited mass");
  expect(await page.$eval(dmass, e => e.classList.contains("pf-inh")), "marked as inherited in the dock");
  expect((await page.textContent(".arch-dock .pf-app > summary")).includes("inherited from FCC"), "dock group is marked");
  expect(await page.$(".arch-dock [data-st-remove]") === null, "no remove button on an inherited group");
  await page.waitForFunction(() => document.querySelector('.arch-block[data-name="fcc1"] .arch-stereo')?.textContent.includes("LRU"));

  d = await depth();
  await page.fill(dmass, "10 lb");
  await page.press(dmass, "Enter");
  await until(() => document.querySelector('.arch-dock [data-note-for="Avionics.LRU.mass"] .pf-reset'));
  expect((await props(fcc1)).mass.value === 4.5359237, "the dock stores the converted value at full precision");
  expect(await depth() === d + 1, "one undo step");
  // SU-11: 4.5359237 kg reads 4.54 kg; the focus shows the stored precision.
  await page.press(dmass, "Tab");
  await until(() => document.querySelector('.arch-dock [data-path="Avionics.LRU.mass"]')?.value === "4.54");
  expect(await page.inputValue(dmass) === "4.54", "rounded when not focused");
  expect((await page.$eval(dmass, e => e.title)).includes("4.5359237 kg"), "the tooltip has the stored precision");
  const msg = await page.textContent(".arch-dock [data-st-msg]");
  expect(msg.includes("4.54 kg") && msg.includes("entered as 10 lb"), `the message gives the rounded value and what was typed: ${msg}`);
  expect((await page.getAttribute(dmass, "placeholder")).includes("(e.g. 3 lb)"), "the field says which units it accepts");
  expect((await page.textContent('.arch-dock [data-path="Avionics.LRU.mass"] + .pf-unit')) === "kg", "the unit is shown next to it");
  await page.focus(dmass);
  expect(await page.inputValue(dmass) === "4.5359237", "the focused field shows the stored precision");
  await page.press(dmass, "Tab");
  expect(await page.inputValue(dmass) === "4.54", "and rounds again when left");
  expect((await props(fcc1)).mass.value === 4.5359237, "leaving the field without a change stored nothing");
  expect(await depth() === d + 1, "no extra step");
  // dock reset
  d = await depth();
  await page.click('.arch-dock [data-reset="Avionics.LRU.mass"]');
  await until(() => document.querySelector('.arch-dock [data-path="Avionics.LRU.mass"]')?.value === "9");
  expect((await props(fcc1)).mass.origin === "inherited", "the dock reset inherits again");
  expect(await depth() === d + 1, "reset is one undo step");

  // several components: override both in one step, reset both in one step
  await page.click('.arch-block[data-name="fcc2"] .arch-body', { position: { x: 10, y: 10 }, modifiers: ["Shift"] });
  await until(() => document.querySelector(".arch-dock-stereo .arch-dock-sub")?.textContent.includes("2 components"));
  d = await depth();
  await page.fill(dmass, "2 kg");
  await page.press(dmass, "Enter");
  await until(() => document.querySelector('.arch-dock [data-note-for="Avionics.LRU.mass"] .pf-reset'));
  expect((await props(fcc1)).mass.value === 2 && (await props(fcc2)).mass.value === 2, "both overridden");
  expect(await depth() === d + 1, "one undo step for both");
  expect((await label()).includes("fcc1, fcc2"), `label names both: ${await label()}`);
  await page.click('.arch-dock [data-reset="Avionics.LRU.mass"]');
  await until(() => document.querySelector('.arch-dock [data-path="Avionics.LRU.mass"]')?.value === "9");
  expect((await props(fcc1)).mass.origin === "inherited" && (await props(fcc2)).mass.origin === "inherited", "both inherit again");
  expect((await label()).startsWith("Reset Avionics.LRU.mass of fcc1, fcc2"), `reset label: ${await label()}`);
  // an unrelated component has no inherited stereotype, and the dock offers it
  await page.click('.arch-block[data-name="plain"] .arch-body', { position: { x: 10, y: 10 } });
  await page.waitForSelector(".arch-dock [data-st-add]:not([disabled])");
  expect(!(await page.$(".arch-dock [data-path]")), "a plain component has no stereotype values");

  // --- PO-13: the Profile Editor lists the AllocationSet category -----------------------------------
  await page.click('.tab[data-tab="profiles"]');
  await page.click('[data-pf-cmd="new-stereotype"]');
  await page.waitForSelector('#modal-form [name="applies_to"]');
  const cats = await page.$$eval('#modal-form [name="applies_to"] option', os => os.map(o => o.value));
  expect(cats.includes("Allocation") && cats.includes("AllocationSet"), `categories offered: ${cats}`);
  await page.click("[data-modal-cancel]");
  await page.click(`.pf-row[data-pf-id="${lru.id}"]`);
  const catsEdit = await page.$$eval("#pf-s-applies option", os => os.map(o => o.value)).catch(() => []);
  expect(catsEdit.includes("AllocationSet"), `the stereotype's Applies to list has it: ${catsEdit}`);
  expect(errors.length === 0, `no browser errors: ${errors}`);
}
