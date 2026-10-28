// SU-7: "Apply stereotypes" tags only the intended elements of the chosen scope (the composition
// scope covers what the composition contains: not the composition itself, not the internals of the
// definitions its reference components are typed by) and the dialog says how many elements will be
// affected before anything is applied. SU-15: a reference component whose definition carries the
// stereotype inherits it, so the batch leaves it alone.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ProfilesBatch");
  const prof = await api("POST", "/api/profiles", { name: "Avionics" });
  const lru = await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "LRU", applies_to: "Component" });
  await api("POST", `/api/stereotypes/${lru.id}/properties`, { name: "mass", type: "double", unit: "kg", default: 1.5 });
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const fccDef = await api("POST", "/api/arch/architecture", { name: "FCC" });
  const core1 = await api("POST", "/api/arch/component", { composition: fccDef.id, name: "core1" });
  const core2 = await api("POST", "/api/arch/component", { composition: fccDef.id, name: "core2" });
  const ima = await api("POST", "/api/arch/component", { composition: root.id, name: "ima" });
  const cpu = await api("POST", "/api/arch/component", { composition: ima.id, name: "cpu" });
  const fcc1 = await api("POST", "/api/arch/component", { composition: root.id, name: "fcc1", definition: fccDef.id });
  const fcc2 = await api("POST", "/api/arch/component", { composition: root.id, name: "fcc2", definition: fccDef.id });
  await waitReady();
  const until = (fn, arg) => page.waitForFunction(fn, arg, { timeout: 10000 });
  const carriers = async () => {
    const out = [];
    for (const [name, e] of Object.entries({ Aircraft: root, FCC: fccDef, core1, core2, ima, cpu, fcc1, fcc2 })) {
      const v = await api("GET", `/api/elements/${e.id}/stereotypes`);
      if (v.applied.length) out.push(`${name}${v.applied[0].inherited ? "*" : ""}`);
    }
    return out.sort();
  };
  const depth = async () => (await api("GET", "/api/undo/state")).undo_depth;
  const open = async () => {
    await page.click('[data-plugin-button="batch-apply-stereotype"]');
    await page.waitForSelector('#modal-form [name="stereotype"]');
  };
  const count = async () => {
    await until(() => document.querySelector('[data-pf="batch-count"]'));
    return Number(await page.$eval('[data-pf="batch-preview"]', b => b.dataset.count));
  };

  // --- the composition scope: what Aircraft contains, counted before applying -----------------
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${root.id}"] > .row`);
  const d = await depth();
  await open();
  await page.selectOption('#modal-form [name="stereotype"]', lru.id);
  await page.check('#modal-form input[name="scope"][value="composition"]');
  expect(await count() === 4, "the preview counts ima, cpu, fcc1 and fcc2");
  const text = await page.textContent('[data-pf="batch-preview"]');
  expect(text.includes("4 elements will get «Avionics.LRU»"), `preview text: ${text}`);
  expect((await page.textContent("[data-modal-submit]")).includes("Apply to 4 elements"), "the button says how many");
  expect((await carriers()).length === 0, "nothing is applied while the dialog counts");
  expect(await depth() === d, "counting is not an undo step");
  await page.click('[data-pf="batch-preview"] summary');
  const listed = await page.$$eval('[data-pf="batch-preview"] li', ls => ls.map(l => l.textContent));
  expect(listed.some(l => l.includes("Aircraft::ima")) && !listed.some(l => /Aircraft$/.test(l.trim()) || l.includes("FCC")),
         `the list names the intended elements only: ${listed}`);
  // the preview follows the choices
  await page.check('#modal-form input[name="scope"][value="model"]');
  await until(() => document.querySelector('[data-pf="batch-preview"]')?.dataset.count === "6");
  await page.selectOption('#modal-form [name="category"]', "Port");
  await until(() => document.querySelector('[data-pf="batch-preview"]')?.dataset.count === "0");
  expect(await page.$eval("[data-modal-submit]", b => b.disabled), "nothing to apply: the button is disabled");
  await page.selectOption('#modal-form [name="category"]', "");
  await page.check('#modal-form input[name="scope"][value="composition"]');
  expect(await count() === 4, "back to the composition");
  await page.click("[data-modal-submit]");
  await until(() => document.querySelector("#log")?.textContent.includes("Applied «Avionics.LRU» to 4 element(s)"));
  expect((await carriers()).join() === "cpu,fcc1,fcc2,ima", `only the contained elements: ${await carriers()}`);
  expect(await depth() === d + 1, "one undo step");

  // --- applying again: everything is already there --------------------------------------------------
  await open();
  await page.selectOption('#modal-form [name="stereotype"]', lru.id);
  await page.check('#modal-form input[name="scope"][value="composition"]');
  expect(await count() === 0, "nothing left to apply");
  expect((await page.textContent('[data-pf="batch-preview"]')).includes("4 already applied"), "says why");
  await page.click("[data-modal-cancel]");

  // --- internals of a referenced definition: only when selected explicitly --------------------------
  await page.evaluate(ids => window.studio.setSelection(ids), [core1.id, core2.id]);
  await open();
  await page.selectOption('#modal-form [name="stereotype"]', lru.id);
  await page.check('#modal-form input[name="scope"][value="selection"]');
  expect(await count() === 2, "the explicit selection counts both internals");
  await page.click("[data-modal-submit]");
  await until(() => document.querySelector("#log")?.textContent.includes("Applied «Avionics.LRU» to 2 element(s)"));
  expect((await carriers()).join() === "core1,core2,cpu,fcc1,fcc2,ima", `explicit selection: ${await carriers()}`);

  // --- a definition that carries the stereotype is inherited by its reference components -------------
  await api("DELETE", `/api/elements/${fcc1.id}/stereotypes`);
  await api("DELETE", `/api/elements/${fcc2.id}/stereotypes`);
  await api("POST", `/api/elements/${fccDef.id}/stereotypes`, { stereotype: lru.id, values: { mass: 3 } });
  expect((await carriers()).join() === "FCC,core1,core2,cpu,fcc1*,fcc2*,ima", `inherited: ${await carriers()}`);
  await page.click(`#tree .tree-node[data-id="${root.id}"] > .row`);
  await open();
  await page.selectOption('#modal-form [name="stereotype"]', lru.id);
  await page.check('#modal-form input[name="scope"][value="composition"]');
  expect(await count() === 0, "the reference components read it from FCC: nothing to apply");
  expect((await page.textContent('[data-pf="batch-preview"]')).includes("2 inherited from its definition"), "the preview says so");
  await page.click("[data-modal-cancel]");

  // --- a stereotype that cannot be batched shows the reason instead of a count ----------------------------
  const any = await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "Tagged" });
  await open();
  await page.selectOption('#modal-form [name="stereotype"]', any.id);
  await page.check('#modal-form input[name="scope"][value="model"]');
  await until(() => document.querySelector('[data-pf="batch-preview"]')?.textContent.includes("choose an element category"));
  expect(await page.$eval("[data-modal-submit]", b => b.disabled), "no Apply without a count");
  await page.click("[data-modal-cancel]");
}
