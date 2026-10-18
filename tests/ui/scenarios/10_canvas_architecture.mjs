// Architecture modeling by clicking: new System model, components, ports, a validated
// connection, undo/redo (button + Ctrl+Y), rename, create-component-from-selection, IBD.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ArchUi");
  await waitReady();

  const section = '[data-section="architecture"]';
  const compNames = () => page.$$eval(`${section} [data-table="components"] input[data-rename]`,
                                       xs => xs.map(x => x.value));
  const connectorCount = () => page.$$eval(`${section} [data-table="connectors"] [data-del]`, xs => xs.length);
  const submitModal = async () => {
    await page.click("#modal-root [data-modal-submit]");
    await page.waitForFunction(() => !document.querySelector("#modal-root .modal"));
  };
  const waitInspectorFor = async (name) => {
    await page.waitForFunction(n => document.querySelector("#props-form input[name=name]")?.value === n
      && document.querySelector('[data-section="architecture"] [data-table="components"]'), name);
  };

  // New model (System architecture with a root architecture) from the toolstrip.
  await page.click('button[data-plugin-button="new-model"]');
  await page.fill("#modal-root input[name=name]", "Avionics");
  await page.fill("#modal-root input[name=arch]", "AircraftSystem");
  await submitModal();
  await waitInspectorFor("AircraftSystem");
  expect((await page.textContent('button[data-plugin-button="model-type"]')).trim() === "System",
         "model type shown in the toolstrip");

  // Two components: one named, one auto-named (Enter submits the modal).
  await page.click(`${section} [data-act="add-component"]`);
  await page.fill("#modal-root input[name=name]", "ADC");
  await submitModal();
  await page.waitForFunction(() => document.querySelectorAll('[data-section="architecture"] input[data-rename]').length === 1);
  await page.click(`${section} [data-act="add-component"]`);
  await page.press("#modal-root input[name=name]", "Enter");
  await page.waitForFunction(() => document.querySelectorAll('[data-section="architecture"] input[data-rename]').length === 2);
  expect(JSON.stringify(await compNames()) === JSON.stringify(["ADC", "Component"]), "auto-numbered component");

  // Ports: open each component, add a port, come back through the breadcrumb.
  const addPort = async (component, name, direction) => {
    const rows = await page.$$(`${section} [data-table="components"] tbody tr`);
    for (const row of rows) {
      const v = await row.$eval("input[data-rename]", x => x.value);
      if (v === component) { await (await row.$("button[data-goto]:last-of-type")).click(); break; }
    }
    await waitInspectorFor(component);
    await page.click(`${section} [data-act="add-port"]`);
    await page.fill("#modal-root input[name=name]", name);
    await page.selectOption("#modal-root select[name=direction]", direction);
    await submitModal();
    await page.waitForFunction(n => [...document.querySelectorAll('[data-section="architecture"] input[data-port-name]')]
      .some(x => x.value === n), name);
    await page.click(`${section} .arch-crumbs button`);
    await waitInspectorFor("AircraftSystem");
  };
  await addPort("ADC", "airData", "out");
  await addPort("Component", "air", "in");

  // Connect: drawn from the input back to the output; the server orients it.
  await page.click(`${section} [data-act="connect"]`);
  await page.selectOption("#modal-root select[name=source]", { label: "Component.air (in)" });
  await page.selectOption("#modal-root select[name=target]", { label: "ADC.airData (out)" });
  await submitModal();
  await page.waitForFunction(() => document.querySelectorAll('[data-section="architecture"] [data-table="connectors"] [data-del]').length === 1);
  const row = await page.textContent(`${section} [data-table="connectors"] tbody tr`);
  expect(row.indexOf("ADC.airData") < row.indexOf("Component.air"), `connector oriented output -> input: ${row}`);

  // Undo with the toolstrip button, redo with Ctrl+Y.
  await page.waitForFunction(() => !document.querySelector('button[data-plugin-button="undo"]').disabled);
  await page.click('button[data-plugin-button="undo"]');
  await page.waitForFunction(() => document.querySelectorAll('[data-section="architecture"] [data-table="connectors"] [data-del]').length === 0);
  await page.waitForFunction(() => !document.querySelector('button[data-plugin-button="redo"]').disabled);
  await page.evaluate(() => document.activeElement?.blur());   // shortcuts apply outside form fields
  await page.keyboard.press("Control+y");
  await page.waitForFunction(() => document.querySelectorAll('[data-section="architecture"] [data-table="connectors"] [data-del]').length === 1);
  expect(await connectorCount() === 1, "redo restored the connector");

  // Rename inline in the components table.
  const inputs = await page.$$(`${section} input[data-rename]`);
  await inputs[1].fill("FMS");
  await inputs[1].press("Tab");
  await page.waitForFunction(() => [...document.querySelectorAll("#tree .tree-node > .row")]
    .some(r => r.textContent.includes("FMS")));
  // The inspector re-renders after the rename: the value *attribute* only exists in the new DOM.
  await page.waitForSelector(`${section} input[data-rename][value="FMS"]`);

  // Create component from selection.
  const picks = await page.$$(`${section} input[data-pick]`);
  for (const p of picks) await p.check();
  await page.waitForFunction(() => !document.querySelector('[data-section="architecture"] [data-act="group"]').disabled);
  await page.click(`${section} [data-act="group"]`);
  await page.fill("#modal-root input[name=name]", "AirDataUnit");
  await submitModal();
  await page.waitForFunction(() => {
    const xs = [...document.querySelectorAll('[data-section="architecture"] input[data-rename]')].map(x => x.value);
    return xs.length === 1 && xs[0] === "AirDataUnit";
  });

  // The server agrees, and the IBD of the architecture renders.
  const roots = await api("GET", "/api/arch/roots");
  const arch = roots.roots.find(r => r.name === "AircraftSystem");
  const view = await api("GET", `/api/arch/view/${arch.id}`);
  expect(view.components.length === 1 && view.components[0].badges.includes("composite"), "grouped component");
  const inner = await api("GET", `/api/arch/view/${view.components[0].id}`);
  expect(inner.connectors.length === 1 && inner.connectors[0].issues.length === 0, "connector moved inside");

  // Copy + paste: a deep copy with a fresh name, internals included.
  await page.check(`${section} input[data-pick]`);
  await page.click(`${section} [data-act="copy"]`);
  await page.waitForFunction(() => !document.querySelector('[data-section="architecture"] [data-act="paste"]').disabled);
  await page.click(`${section} [data-act="paste"]`);
  await page.waitForSelector(`${section} input[data-rename][value="AirDataUnit1"]`);
  const after = await api("GET", `/api/arch/view/${arch.id}`);
  const copy = after.components.find(c => c.name === "AirDataUnit1");
  const copyInner = await api("GET", `/api/arch/view/${copy.id}`);
  expect(copyInner.components.length === 2 && copyInner.connectors.length === 1, "pasted a deep copy");
  await page.click('.tab[data-tab="diagram"]');
  await page.click('.diag-mode[data-mode="ibd"]');
  await page.waitForSelector("#diagram svg", { timeout: 10000 });
}
