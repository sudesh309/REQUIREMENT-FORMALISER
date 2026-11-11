// Interface Editor main flow, driven by real clicks:
//   create a data interface with three elements in the Interfaces tab, assign it to two
//   ports from the Properties inspector, connect the ports (compatible), give the target
//   port an owned copy, change one element type and see the incompatibility in Validate.
export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("IfcUi");
  const sys = await api("POST", "/api/element", { kind: "PartDefinition", name: "Avionics" });
  const adiru = await api("POST", "/api/element", { kind: "PartUsage", name: "ADIRU", parent: sys.id });
  const fms = await api("POST", "/api/element", { kind: "PartUsage", name: "FMS", parent: sys.id });
  const out = await api("POST", "/api/element", { kind: "PortUsage", name: "AirDataOut", parent: adiru.id,
                                                  properties: { direction: "out" } });
  const inp = await api("POST", "/api/element", { kind: "PortUsage", name: "AirDataIn", parent: fms.id,
                                                  properties: { direction: "in" } });
  await waitReady();

  const idle = () => page.waitForFunction(() => !Number(document.body.dataset.ifcPending || 0));
  const row = (i) => page.locator("#ifc-table > tbody > tr").nth(i);
  const editCell = async (i, field, value) => {
    const cell = row(i).locator(`[data-field="${field}"]`);
    if (await cell.evaluate((e) => e.tagName) === "SELECT") await cell.selectOption(value);
    else { await cell.fill(value); await cell.press("Tab"); }
    await idle();
  };
  const treeRow = (id) => `#tree .tree-node[data-id="${id}"] > .row`;

  // 1. Interfaces tab -> toolstrip "Data Interface" -> rename in the header.
  await page.click('.tab[data-tab="interfaces"]');
  await idle();
  await page.click('[data-ifc-act="new-data"]');
  await idle();
  expect(await page.inputValue('[data-ifc="name"]') === "interface0", "new interface gets a default name");
  await page.fill('[data-ifc="name"]', "AirData");
  await page.press('[data-ifc="name"]', "Enter");
  await idle();
  await page.waitForSelector('.ifc-item.sel:has-text("AirData")');

  // 2. Three elements via the toolstrip "Add" button, edited inline in the table.
  for (let n = 1; n <= 3; n++) {
    await page.click('[data-ifc-act="add-element"]');
    await idle();
    await page.waitForFunction((k) => document.querySelectorAll("#ifc-table > tbody > tr").length === k, n);
  }
  await editCell(0, "name", "altitude");
  await editCell(0, "units", "ft");
  await editCell(1, "name", "airspeed");
  await editCell(1, "units", "kn");
  await editCell(2, "name", "valid");
  await editCell(2, "type", "boolean");
  const names = await page.$$eval('#ifc-table > tbody > tr [data-field="name"]', (els) => els.map((e) => e.value));
  expect(names.join() === "altitude,airspeed,valid", `element names in the table: ${names}`);
  const listing = await api("GET", "/api/interfaces");
  const airData = listing.items.find((i) => i.name === "AirData");
  expect(airData && airData.element_count === 3, "AirData saved with three elements");
  const detail = await api("GET", `/api/interfaces/item/${airData.id}`);
  expect(detail.elements.map((e) => `${e.name}:${e.type}:${e.units}`).join() ===
         "altitude:double:ft,airspeed:double:kn,valid:boolean:", "element fields persisted");

  // 3. Assign AirData to both ports from Properties > Interface.
  await page.click('.tab[data-tab="properties"]');
  for (const port of [out, inp]) {
    // The inspector of the previous port must be gone before the list is used: on a slow machine
    // the old list is still there right after the click and the choice went to the wrong port.
    const previous = await page.$('[data-ifc="port-interface"]');
    await page.click(treeRow(port.id));
    if (previous) await page.waitForFunction((el) => !el.isConnected, previous);
    await page.waitForSelector('[data-ifc="port-interface"]');
    await idle();
    await page.selectOption('[data-ifc="port-interface"]', { label: "AirData" });
    await idle();
    await page.waitForFunction((id) =>
      [...document.querySelectorAll(`#tree .tree-node[data-id="${id}"] > .row .tree-badge`)]
        .some((b) => b.textContent === "AirData"), port.id);
  }
  await page.waitForSelector('[data-ifc="port-elements"]');

  // 4. Connect the ports from the port inspector; the compatibility check passes.
  await page.click(treeRow(out.id));
  await page.waitForSelector('[data-ifc-port="connect"]');
  await idle();
  await page.click('[data-ifc-port="connect"]');
  await idle();
  await page.waitForSelector('#modal-root [data-ifc="connect-status"] .ifc-ok');
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForSelector('[data-ifc="compat-status"]');
  await idle();
  expect((await page.textContent('[data-ifc="compat-status"]')).includes("Compatible"), "connector is compatible");
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("Validation:"));
  expect(!(await page.textContent("#log")).includes("interfaces.compatibility"), "no compatibility errors yet");
  await page.click('[data-cmd="clear-log"]');

  // 5. Give the target port an owned copy and change one element type in the editor.
  await page.click(treeRow(inp.id));
  await page.waitForSelector('[data-ifc-port="owned"]');
  await idle();
  await page.click('[data-ifc-port="owned"]');
  await idle();
  await page.waitForSelector('[data-ifc-port="shared"]');          // now owned: offers "Convert to shared"
  await page.click('[data-ifc-port="edit"]');
  await idle();
  await page.waitForFunction(() => document.querySelector(".ifc-kind-badge")?.textContent.includes("owned"));
  await editCell(2, "type", "uint8");
  await page.waitForFunction(() =>
    [...document.querySelectorAll("#tree .tree-badge")].some((b) => b.textContent === "incompatible"));

  // 6. Validate reports the incompatible connector and names the mismatch.
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("interfaces.compatibility"));
  const log = await page.textContent("#log");
  expect(log.includes("type boolean vs uint8"), "validation names the element type mismatch");
  const v = await api("GET", "/api/validate");
  expect(v.issues.filter((i) => i.rule === "interfaces.compatibility").length === 1, "one incompatible connector");
}
