// Model Tables grid (spreadsheet-style editing applied through the table importer):
// rename a component, add a component row, reject an invalid port direction without
// touching the model; then the SysML v2 text view, its download, and importing SysML text
// through the dialog; finally the CSV export.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const XMI = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "data", "interop_avionics_cameo.xmi");

// Row / column of the cell in `column` of the row whose `keyColumn` equals `key`.
const findCell = (page, keyColumn, key, column) => page.evaluate(({ keyColumn, key, column }) => {
  const heads = [...document.querySelectorAll("#tab-interop .io-grid thead th")].map((t) => t.textContent);
  const kc = heads.indexOf(keyColumn) - 1;
  const c = heads.indexOf(column) - 1;
  const tr = [...document.querySelectorAll("#tab-interop .io-grid tbody tr")]
    .find((r) => r.querySelector(`td[data-c="${kc}"]`)?.textContent === key);
  return tr ? { r: tr.dataset.r, c } : null;
}, { keyColumn, key, column });

async function editCell(page, cell, value) {
  await page.dblclick(`#tab-interop tr[data-r="${cell.r}"] td[data-c="${cell.c}"]`);
  await page.fill("#tab-interop td.editing input", value);
  await page.keyboard.press("Enter");
}

// The browser logs every non-2xx response; drop the one an intentionally rejected request causes.
function allowRejected(errors, expect) {
  const i = errors.findIndex((e) => e.includes("status of 400"));
  expect(i >= 0, "the rejected request answered 400");
  errors.splice(i, 1);
}

export default async function ({ page, api, fresh, waitReady, expect, errors }) {
  await fresh("TablesUi");
  await api("POST", "/api/interop/xmi/import", { text: readFileSync(XMI, "utf8"), mode: "new" });
  await waitReady();
  await page.click('.tab[data-tab="interop"]');
  await page.waitForSelector("#tab-interop .io-grid tbody tr");

  // 1. Rename gps -> gnss in the Components sheet (double-click, type, Enter), apply.
  await page.click('#tab-interop .io-sheet[data-sheet="Components"]');
  const gps = await findCell(page, "Name", "gps", "Name");
  expect(gps, "gps row in the Components sheet");
  await editCell(page, gps, "gnss");
  await page.waitForSelector("#tab-interop td.edited");
  expect((await page.textContent('#tab-interop .io-sheet[data-sheet="Components"]')).includes("●"), "sheet marked dirty");
  await page.click('#tab-interop [data-t="apply"]');
  await page.waitForSelector('#tab-interop .io-banner.ok:has-text("1 updated")');
  await page.waitForSelector('#tree .tree-node .row:has-text("gnss")');

  // 2. Keyboard: arrows move the active cell, typing starts editing, Escape cancels.
  const fmc = await findCell(page, "Name", "fmc", "Name");
  await page.click(`#tab-interop tr[data-r="${fmc.r}"] td[data-c="${fmc.c}"]`);
  await page.keyboard.press("x");
  await page.waitForSelector("#tab-interop td.editing input");
  await page.keyboard.press("Escape");
  expect(await page.textContent(`#tab-interop tr[data-r="${fmc.r}"] td[data-c="${fmc.c}"]`) === "fmc", "Escape cancels");
  await page.keyboard.press("ArrowDown");
  expect(await page.$eval("#tab-interop td.active", (td) => td.parentElement.dataset.r) !== fmc.r, "ArrowDown moves");

  // 3. Add a component row: name + parent (qualified name); the reference column stays empty.
  await page.click('#tab-interop [data-t="add"]');
  await page.fill("#tab-interop td.editing input", "adiru");
  await page.keyboard.press("Enter");
  const added = await findCell(page, "Name", "adiru", "Parent");
  await editCell(page, added, "Structure::FlightDeck");
  await page.click('#tab-interop [data-t="apply"]');
  await page.waitForSelector('#tab-interop .io-banner.ok:has-text("1 created")');
  await page.waitForSelector('#tree .tree-node .row:has-text("adiru")');
  const created = await api("GET", "/api/interop/tables?format=json");
  const [ch, ...crows] = created.tables.Components;
  const adiru = crows.find((r) => r[ch.indexOf("Name")] === "adiru");
  expect(adiru && adiru[ch.indexOf("Parent")] === "Structure::FlightDeck", "adiru created under FlightDeck");

  // 4. An invalid direction is rejected with the importer's message; nothing changes.
  const before = (await api("GET", "/api/save")).text;
  await page.click('#tab-interop .io-sheet[data-sheet="Ports"]');
  const navIn = await findCell(page, "Name", "navIn", "Direction");
  await editCell(page, navIn, "sideways");
  await page.click('#tab-interop [data-t="apply"]');
  await page.waitForSelector('#tab-interop .io-banner.err:has-text("sideways")');
  allowRejected(errors, expect);
  expect((await api("GET", "/api/save")).text === before, "model unchanged after a rejected import");
  await page.click('#tab-interop [data-t="revert"]');
  expect(!(await page.$("#tab-interop td.edited")), "revert discards edits");

  // 5. SysML v2 text view and download.
  await page.click('#tab-interop [data-io-view="sysml"]');
  await page.waitForFunction(() => document.querySelector('#tab-interop [data-s="text"]')?.textContent.includes("part def FlightDeck"));
  const [sysml] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop [data-io="export-sysml"]')]);
  expect(sysml.suggestedFilename() === "FlightDeckModel.sysml", `sysml file: ${sysml.suggestedFilename()}`);
  expect(readFileSync(await sysml.path(), "utf8").includes("part adiru"), "exported text has the new part");

  // 6. Import SysML v2 text (pasted) into the current project.
  await page.click('#tab-interop [data-io="import-sysml"]');
  await page.fill('#modal-form textarea[name="text"]', "package GroundSupport { part def MaintenanceTerminal; }");
  await page.check('#modal-form input[name="mode"][value="merge"]');
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#tree .tree-node .row:has-text("MaintenanceTerminal")');
  // A syntax error keeps the dialog open with the parser message.
  await page.click('#tab-interop [data-io="import-sysml"]');
  await page.fill('#modal-form textarea[name="text"]', "package Broken { part def }");
  await page.click("[data-modal-submit]");
  await page.waitForFunction(() => document.querySelector("#modal-root [data-io-modal-error]")?.textContent.length > 0);
  allowRejected(errors, expect);
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("#modal-root .modal"));

  // 7. Export the tables as a ZIP of CSV files.
  const [csv] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop [data-io="export-csv"]')]);
  expect(csv.suggestedFilename() === "FlightDeckModel_tables.zip", `csv zip: ${csv.suggestedFilename()}`);
  expect(readFileSync(await csv.path()).subarray(0, 2).toString() === "PK", "zip container");
}
