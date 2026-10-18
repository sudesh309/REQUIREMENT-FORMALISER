// Interface dictionary workflows by clicking: avionics template, value type editing,
// keyboard reordering, export + re-import with the collision dialog, adapter mappings,
// and delete with confirmation.
import { readFileSync } from "node:fs";

export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("IfcDict");
  const sys = await api("POST", "/api/element", { kind: "PartDefinition", name: "Cockpit" });
  await waitReady();
  const idle = () => page.waitForFunction(() => !Number(document.body.dataset.ifcPending || 0));
  const names = () => page.$$eval('#ifc-table > tbody > tr [data-field="name"]', (els) => els.map((e) => e.value));

  await page.click('.tab[data-tab="interfaces"]');
  await idle();

  // Template: ARINC 429 word.
  await page.selectOption('[data-ifc="template"]', "arinc429");
  await idle();
  await page.waitForSelector('.ifc-item.sel:has-text("A429Word")');
  expect((await names()).join() === "label,sdi,data,ssm,parity", "ARINC 429 template elements");

  // Keyboard: select "parity", Alt+ArrowUp moves it up; Insert adds an element after it.
  await page.click('#ifc-table > tbody > tr:nth-child(5) [data-field="description"]');
  await page.keyboard.press("Alt+ArrowUp");
  await idle();
  expect((await names()).join() === "label,sdi,data,parity,ssm", "Alt+ArrowUp reorders elements");
  await page.click('#ifc-table > tbody > tr:nth-child(4) > td:first-child', { position: { x: 4, y: 4 } });
  await page.click('[data-ifc-act="down"]');
  await idle();
  expect((await names()).join() === "label,sdi,data,ssm,parity", "toolstrip Down reorders elements");

  // Value type: create and edit its units in the single-row table.
  await page.click('[data-ifc-act="new-vt"]');
  await idle();
  await page.fill('[data-ifc="name"]', "Airspeed");
  await page.press('[data-ifc="name"]', "Enter");
  await idle();
  await page.fill('#ifc-table [data-field="units"]', "kn");
  await page.press('#ifc-table [data-field="units"]', "Tab");
  await idle();
  await page.fill('#ifc-table [data-field="maximum"]', "450");
  await page.press('#ifc-table [data-field="maximum"]', "Tab");
  await idle();
  const vt = (await api("GET", "/api/interfaces")).items.find((i) => i.name === "Airspeed");
  expect(vt && vt.units === "kn" && vt.maximum === 450, "value type units/maximum saved");

  // Export, then import the same file: every item collides; choose "Rename" for all.
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('[data-ifc-act="export"]')]);
  const text = readFileSync(await download.path(), "utf-8");
  expect(JSON.parse(text).items.length === 2, "exported dictionary has two items");
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click('[data-ifc-act="import"]')]);
  await chooser.setFiles({ name: "Interfaces.json", mimeType: "application/json", buffer: Buffer.from(text) });
  await page.waitForSelector('#modal-root [data-ifc="all-choice"]');
  await page.selectOption('#modal-root [data-ifc="all-choice"]', "rename");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForSelector('.ifc-item:has-text("A429Word_1")');
  await page.waitForSelector('.ifc-item:has-text("Airspeed_1")');
  const importLog = await page.textContent("#log");
  expect(importLog.includes("A429Word→A429Word_1") && importLog.includes("Airspeed→Airspeed_1"), "import report logged");

  // Delete the renamed copy through the confirmation dialog.
  await page.click('.ifc-item:has-text("A429Word_1")');
  await idle();
  await page.click('[data-ifc-act="delete"]');
  await page.waitForSelector("#modal-root .modal");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForFunction(() => ![...document.querySelectorAll(".ifc-item")].some((n) => n.textContent.includes("A429Word_1")));

  // Adapter: select the architecture, toolbar "Adapter", then map an element.
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${sys.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector("#props-kind")?.textContent === "PartDefinition");
  await page.click('[data-plugin-button="add-adapter"]');
  await page.fill('#modal-root input[name="name"]', "UnitConverter");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForSelector('[data-section="adapter-mappings"] [data-m-add]');
  await page.click('[data-section="adapter-mappings"] [data-m-add]');
  await page.fill('[data-section="adapter-mappings"] [data-m="target"]', "alt_m");
  await page.fill('[data-section="adapter-mappings"] [data-m="source"]', "alt_ft");
  await page.fill('[data-section="adapter-mappings"] [data-m="note"]', "ft x 0.3048");
  await page.click('[data-section="adapter-mappings"] [data-m-save]');
  await idle();
  const tree = await api("GET", "/api/tree");
  const adapter = tree.children.find((c) => c.name === "Cockpit").children.find((c) => c.name === "UnitConverter");
  expect(adapter && adapter.kind === "Adapter" && adapter.badges.includes("Adapter"), "adapter in the tree");
  expect(adapter.mappings.length === 1 && adapter.mappings[0].note === "ft x 0.3048", "adapter mapping saved");
}
