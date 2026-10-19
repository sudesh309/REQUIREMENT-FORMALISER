// Interop with a stereotype from a real profile (Profile Editor / engine.profiles): the
// Model Tables grid shows `Avionics.LRU.*` columns with stored (kg) values, a value typed with
// another unit is converted on Apply, a unit change in the Profiles sheet converts the stored
// values; the XLSX export re-imported as a new project compares with "No differences", a value
// change shows up as an `Avionics.LRU.mass` property diff, and Model Check reports (and
// navigates to) an invalid stereotype value.
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const XMI = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "data", "interop_avionics_cameo.xmi");

async function chooseFile(page, inputSelector, path) {
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click(inputSelector)]);
  await chooser.setFiles(path);
}

// Grid cell (row, column) of `column` in the row whose cells match every entry of `match`.
const findCell = (page, match, column) => page.evaluate(({ match, column }) => {
  const heads = [...document.querySelectorAll("#tab-interop .io-grid thead th")].map((t) => t.textContent);
  const col = (name) => heads.indexOf(name) - 1;
  const tr = [...document.querySelectorAll("#tab-interop .io-grid tbody tr")].find((r) =>
    Object.entries(match).every(([k, v]) => r.querySelector(`td[data-c="${col(k)}"]`)?.textContent === v));
  return tr ? { r: tr.dataset.r, c: col(column), text: tr.querySelector(`td[data-c="${col(column)}"]`)?.textContent } : null;
}, { match, column });

async function editCell(page, cell, value) {
  await page.dblclick(`#tab-interop tr[data-r="${cell.r}"] td[data-c="${cell.c}"]`);
  await page.fill("#tab-interop td.editing input", value);
  await page.keyboard.press("Enter");
}

const close = (a, b) => Math.abs(a - b) < 1e-6;

export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("InteropProfilesUi");
  // The Cameo model brings a legacy «LRU» (XMI_Profiles::LRU, untyped); add a real profile next to it.
  await api("POST", "/api/interop/xmi/import", { text: readFileSync(XMI, "utf8"), mode: "new" });
  await api("POST", "/api/profiles", { name: "Avionics", version: "2.1" });
  await api("POST", "/api/profiles/Avionics/stereotypes", { name: "LRU", applies_to: "Component",
                                                            style: { fill: "#dbeafe", icon: "computer" } });
  await api("POST", "/api/stereotypes/Avionics.LRU/properties",
            { name: "mass", type: "double", unit: "kg", default: "1.5", min: 0 });
  await api("POST", "/api/stereotypes/Avionics.LRU/properties",
            { name: "dal", type: "enumeration", literals: "A,B,C,D,E" });
  const gps = await api("GET", "/api/element/Structure::FlightDeck::gps");
  await api("POST", `/api/elements/${gps.id}/stereotypes`,
            { stereotype: "Avionics.LRU", values: { "Avionics.LRU.mass": "3 lb", "Avionics.LRU.dal": "b" } });
  const mass = async () => (await api("GET", `/api/elements/${gps.id}/stereotypes`))
    .applied.find((a) => a.qualified_name === "Avionics.LRU").values.mass;
  await waitReady();

  // 1. Model Tables: the gps row carries the profile's columns with the stored value in kg.
  await page.click('.tab[data-tab="interop"]');
  await page.waitForSelector("#tab-interop .io-grid tbody tr");
  await page.click('#tab-interop .io-sheet[data-sheet="Components"]');
  const massCell = await findCell(page, { Name: "gps" }, "Avionics.LRU.mass");
  expect(massCell && close(Number(massCell.text), 1.36077711), `stored mass in kg: ${massCell?.text}`);
  expect((await findCell(page, { Name: "gps" }, "Stereotypes")).text === "Avionics.LRU", "Stereotypes cell");
  expect((await findCell(page, { Name: "FlightManagementComputer" }, "LRU.mass"))?.text === "4.2",
         "legacy «LRU» (plain package) column kept under its bare name");

  // 2. Type a value with another unit; Apply converts it through the profiles feature.
  await editCell(page, massCell, "2 lb");
  await page.click('#tab-interop [data-t="apply"]');
  await page.waitForSelector('#tab-interop .io-banner.ok:has-text("1 updated")');
  expect(close(await mass(), 0.90718474), "2 lb stored as 0.90718474 kg");
  expect(close(Number((await findCell(page, { Name: "gps" }, "Avionics.LRU.mass")).text), 0.90718474),
         "grid reloaded with the converted value");

  // 3. Change the unit in the Profiles sheet: stored values follow (kg -> g).
  await page.click('#tab-interop .io-sheet[data-sheet="Profiles"]');
  const unit = await findCell(page, { Profile: "Avionics", Stereotype: "LRU", Property: "mass" }, "Unit");
  expect(unit && unit.text === "kg", `profile unit cell: ${unit?.text}`);
  await editCell(page, unit, "g");
  await page.click('#tab-interop [data-t="apply"]');
  await page.waitForSelector('#tab-interop .io-banner.ok:has-text("updated property Avionics.LRU.mass: unit")');
  expect(close(await mass(), 907.18474), "stored value converted to grams");
  const original = await api("GET", "/api/interop/tables?format=json");

  // 4. Export XLSX, re-import it as a new project, compare: no differences.
  const work = mkdtempSync(join(tmpdir(), "interop-profiles-ui-"));
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop [data-io="export-xlsx"]')]);
  const xlsxPath = join(work, download.suggestedFilename());
  await download.saveAs(xlsxPath);
  await api("POST", "/api/new", { name: "Blank" });
  await page.evaluate(() => window.studio.refreshTree());
  await page.click('#tab-interop [data-io="import-tables"]');
  await chooseFile(page, '#modal-form input[name="file"]', xlsxPath);
  await page.check('#modal-form input[name="mode"][value="new"]');
  await page.click("[data-modal-submit]");
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent.startsWith("FlightDeckModel"));
  const reimported = await api("GET", "/api/interop/tables?format=json");
  expect(JSON.stringify(reimported.tables) === JSON.stringify(original.tables), "profile tables round trip");
  expect((await api("GET", "/api/profiles")).profiles.some((p) => p.name === "Avionics" && p.version === "2.1"),
         "the profile itself was recreated");
  expect(close(await mass(), 907.18474), "typed value survives the round trip");
  await page.click('#tab-interop [data-io="compare-file"]');
  await chooseFile(page, '#modal-form input[name="file"]', xlsxPath);
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#tab-compare [data-c="nodiff"]');

  // 5. Change the value: Compare (Refresh) shows the property diff under the profile's name.
  await api("PATCH", `/api/elements/${gps.id}/stereotypes`, { values: { "Avionics.LRU.mass": "1 kg" } });
  await page.click('#tab-compare [data-io="refresh"]');
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${gps.id}"] .io-props`);
  const props = await page.textContent(`#tab-compare .io-tnode[data-id="${gps.id}"] .io-props`);
  expect(props.includes("Avionics.LRU.mass") && props.includes("1000"), `profile value diff: ${props}`);

  // 6. Model Check: an out-of-range stored value (e.g. from a hand-edited file) is reported by
  //    the profiles rule; filter to it and click to navigate to the element.
  const lru = await api("GET", "/api/stereotypes/Avionics.LRU");
  const saved = JSON.parse((await api("GET", "/api/save")).text);
  saved.elements.find((e) => e.id === gps.id).stereotypes
    .find((s) => s.stereotype === lru.id).values.mass = -5;
  await api("POST", "/api/load", { text: JSON.stringify(saved) });
  await page.evaluate(() => window.studio.refreshTree());
  await page.click('.tab[data-tab="checks"]');
  await page.waitForSelector('#tab-checks table[data-k="issues"] tr.io-issue');
  await page.waitForFunction(() => [...document.querySelectorAll('#tab-checks select[data-k="rule"] option')]
    .some((o) => o.value === "profile.value.invalid"));
  expect((await page.getAttribute('.tab[data-tab="checks"] .io-tab-badge', "class")).includes("error"),
         "badge shows errors");
  await page.selectOption('#tab-checks select[data-k="rule"]', "profile.value.invalid");
  const issue = await page.$eval("#tab-checks tr.io-issue", (tr) => ({ id: tr.dataset.id, text: tr.textContent }));
  expect(issue.id === gps.id && issue.text.includes("Avionics.LRU.mass"), `invalid value reported: ${issue.text}`);
  await page.click("#tab-checks tr.io-issue");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, gps.id);
}
