// Profile Editor main flow: create profile Avionics with stereotype LRU (Component) having
// mass (double, kg, default 1.5) and dal (enumeration A..E), apply it to a component from the
// inspector, enter mass as '3 lb', see it converted to kg and the «LRU» badge in the tree.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ProfilesUi");
  const arch = await api("POST", "/api/element", { kind: "PartDefinition", name: "Aircraft" });
  const fcc = await api("POST", "/api/element", { kind: "PartUsage", name: "FCC", parent: arch.id });
  await waitReady();
  const until = (fn, arg) => page.waitForFunction(fn, arg, { timeout: 10000 });

  // --- Profile Editor: new profile ------------------------------------------------
  await page.click('.tab[data-tab="profiles"]');
  await page.waitForSelector('[data-pf-cmd="new-profile"]');
  await page.click('[data-pf-cmd="new-profile"]');
  await page.fill('#modal-form [name="name"]', "Avionics");
  await page.fill('#modal-form [name="description"]', "Avionics equipment profile");
  await page.press('#modal-form [name="name"]', "Enter");             // Enter submits the dialog
  await page.waitForSelector('.pf-row[data-kind="profile"]');
  expect((await page.textContent('.pf-row[data-kind="profile"]')).includes("Avionics"), "profile in the browser");

  // --- new stereotype LRU applying to components ------------------------------------
  await page.click('[data-pf-cmd="new-stereotype"]');
  await page.fill('#modal-form [name="name"]', "LRU");
  await page.selectOption('#modal-form [name="applies_to"]', "Component");
  await page.click("[data-modal-submit]");
  await page.waitForSelector('.pf-row[data-kind="stereotype"]');
  expect((await page.textContent(".pf-title")).includes("«Avionics.LRU»"), "stereotype details shown");
  expect(await page.$eval("#pf-s-applies", el => el.value) === "Component", "applies to Component");

  // --- property mass: double, kg, default 1.5 ------------------------------------------
  await page.click('[data-pf-cmd="add-property"]');
  await page.waitForSelector('tr[data-prop-id] [data-col="name"]');
  const row = (i) => `tr[data-prop-id]:nth-of-type(${i})`;
  const cellValue = (i, col) => page.$eval(`${row(i)} [data-col="${col}"]`, el => el.value);
  await page.fill(`${row(1)} [data-col="name"]`, "mass");
  await page.press(`${row(1)} [data-col="name"]`, "Enter");
  await until(() => document.querySelector('tr[data-prop-id] [data-col="name"]')?.getAttribute("value") === "mass");
  expect(await cellValue(1, "type") === "double", "new properties are doubles");
  await page.fill(`${row(1)} [data-col="unit"]`, "kg");
  await page.press(`${row(1)} [data-col="unit"]`, "Enter");
  await until(() => document.querySelector('tr[data-prop-id] [data-col="unit"]')?.getAttribute("value") === "kg");
  await page.fill(`${row(1)} [data-col="default"]`, "1.5");
  await page.press(`${row(1)} [data-col="default"]`, "Enter");
  await until(() => document.querySelector('tr[data-prop-id] [data-col="default"]')?.getAttribute("value") === "1.5");

  // --- property dal: enumeration A..E ---------------------------------------------------
  await page.click('[data-pf="add-prop"]');
  await until(() => document.querySelectorAll("tr[data-prop-id]").length === 2);
  await page.fill(`${row(2)} [data-col="name"]`, "dal");
  await page.press(`${row(2)} [data-col="name"]`, "Enter");
  await until(() => document.querySelectorAll('tr[data-prop-id] [data-col="name"]')[1]?.getAttribute("value") === "dal");
  await page.selectOption(`${row(2)} [data-col="type"]`, "enumeration");
  await page.waitForSelector(`${row(2)}.pf-pending`);                 // waits for its literals
  await page.fill(`${row(2)} [data-col="literals"]`, "A, B, C, D, E");
  await page.press(`${row(2)} [data-col="literals"]`, "Enter");
  await until(() => document.querySelectorAll('tr[data-prop-id] [data-col="literals"]')[1]?.getAttribute("value") === "A, B, C, D, E");
  expect(await cellValue(2, "type") === "enumeration", "dal is an enumeration");
  expect(await cellValue(2, "default") === "A", "enumeration default is its first literal");

  const st = await api("GET", "/api/stereotypes/Avionics.LRU");
  expect(st.applies_to === "Component", "saved applies-to");
  expect(JSON.stringify(st.properties.map(p => [p.name, p.type, p.unit, p.default])) ===
         JSON.stringify([["mass", "double", "kg", 1.5], ["dal", "enumeration", "", "A"]]), "saved properties");
  expect(JSON.stringify(st.properties[1].literals) === JSON.stringify(["A", "B", "C", "D", "E"]), "saved literals");

  // --- apply to FCC from the inspector ----------------------------------------------
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${fcc.id}"] > .row`);
  await page.waitForSelector('[data-section="stereotypes"] [data-pf="add-stereotype"]:not([disabled])');
  await page.selectOption('[data-pf="add-stereotype"]', { label: "Avionics.LRU" });
  await page.waitForSelector('details.pf-app [data-path="Avionics.LRU.mass"]');
  expect(await page.$eval('[data-path="Avionics.LRU.mass"]', el => el.value) === "1.5", "default mass shown");
  expect(await page.$eval('[data-path="Avionics.LRU.dal"]', el => el.value) === "A", "default dal shown");

  // --- edit mass as '3 lb': converted to kg ---------------------------------------------
  await page.fill('[data-path="Avionics.LRU.mass"]', "3 lb");
  await page.press('[data-path="Avionics.LRU.mass"]', "Enter");
  await until(() => document.querySelector('[data-path="Avionics.LRU.mass"]')?.value === "1.36077711");
  expect((await page.textContent('[data-section="stereotypes"] .pf-unit')).trim() === "kg", "unit shown next to the value");
  await page.selectOption('[data-path="Avionics.LRU.dal"]', "B");
  await until(() => document.querySelector('[data-section="stereotypes"] [data-pf=msg]')?.textContent.includes("dal = B"));
  const view = await api("GET", `/api/elements/${fcc.id}/stereotypes`);
  expect(JSON.stringify(view.applied[0].values) === JSON.stringify({ mass: 1.36077711, dal: "B" }), "values stored converted");

  // --- «LRU» badge in the containment tree ------------------------------------------
  const badge = `#tree .tree-node[data-id="${fcc.id}"] > .row > .tree-badge.pf-badge`;
  await page.waitForSelector(badge);
  expect((await page.textContent(badge)).trim() === "«LRU»", "«LRU» badge on FCC");
  expect(await page.isVisible(badge), "badge visible");

  // The project round-trips through Save / Load with the values intact.
  const saved = await api("GET", "/api/save");
  await api("POST", "/api/load", { text: saved.text });
  const again = await api("GET", "/api/elements/Aircraft::FCC/stereotypes");
  expect(again.applied[0].values.mass === 1.36077711, "value survives save/load");
}
