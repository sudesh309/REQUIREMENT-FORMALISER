// Interop end to end through real clicks: import a Cameo XMI model, export it as an XLSX
// workbook (download intercepted), import the workbook into a new project through the file
// chooser, compare with the original export ("No differences"), see a property diff after an
// edit, then run Model Check, filter, and click an issue to navigate to its element.
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const XMI = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "data", "interop_avionics_cameo.xmi");

async function chooseFile(page, inputSelector, path) {
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click(inputSelector)]);
  await chooser.setFiles(path);
}

const projectName = (page) => page.evaluate(() => document.querySelector("#project-name")?.textContent || "");

export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("InteropUi");
  await waitReady();
  const work = mkdtempSync(join(tmpdir(), "interop-ui-"));

  // 1. Import the XMI model as a new project (toolstrip button + file chooser).
  await page.click('.tab[data-tab="interop"]');
  await page.click('#tab-interop [data-io="import-xmi"]');
  await chooseFile(page, '#modal-form input[name="file"]', XMI);
  await page.click("[data-modal-submit]");
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent.startsWith("FlightDeckModel"));
  expect(!(await page.$("#modal-root .modal")), "import dialog closed");
  await page.waitForSelector('#tree .tree-node .row:has-text("GPSReceiver")');
  expect((await page.textContent('#tab-interop [data-io-pane="activity"]')).includes("Imported XMI"), "activity shows the XMI import");

  // 2. Export Tables (XLSX) via the button; intercept the download.
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop [data-io="export-xlsx"]')]);
  expect(download.suggestedFilename() === "FlightDeckModel.xlsx", `xlsx file name: ${download.suggestedFilename()}`);
  const xlsxPath = join(work, download.suggestedFilename());
  await download.saveAs(xlsxPath);
  expect(readFileSync(xlsxPath).subarray(0, 2).toString() === "PK", "xlsx is a ZIP container");
  const original = await api("GET", "/api/interop/tables?format=json");

  // 3. Start from a blank project, then import the workbook into a new project via the file chooser.
  await api("POST", "/api/new", { name: "Blank" });
  await page.evaluate(() => window.studio.refreshTree());
  expect((await projectName(page)).startsWith("Blank"), "blank project before the import");
  await page.click('#tab-interop [data-io="import-tables"]');
  await chooseFile(page, '#modal-form input[name="file"]', xlsxPath);
  await page.check('#modal-form input[name="mode"][value="new"]');
  await page.click("[data-modal-submit]");
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent.startsWith("FlightDeckModel"));
  await page.waitForSelector('#tree .tree-node .row:has-text("PrimaryFlightDisplay")');
  const reimported = await api("GET", "/api/interop/tables?format=json");
  expect(JSON.stringify(reimported.tables) === JSON.stringify(original.tables), "table round trip preserves ids and values");

  // 4. Compare with the original export: no differences.
  await page.click('#tab-interop [data-io="compare-file"]');
  await chooseFile(page, '#modal-form input[name="file"]', xlsxPath);
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#tab-compare [data-c="nodiff"]');
  expect((await page.textContent('#tab-compare [data-c="nodiff"]')).includes("No differences"), "no differences shown");
  expect(await page.isVisible("#tab-compare"), "Compare tab is shown");

  // 5. Rename a component; Refresh shows one modified element with a property diff.
  const [hdr, ...comps] = reimported.tables.Components;
  const gps = { id: comps.find((r) => r[hdr.indexOf("Name")] === "gps")[hdr.indexOf("ID")] };
  await api("PATCH", `/api/element/${gps.id}`, { props: { name: "gnss" } });
  await page.click('#tab-compare [data-io="refresh"]');
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${gps.id}"]`);
  expect((await page.textContent('#tab-compare [data-count="modified"]')).includes("1 modified"), "one modified element");
  const props = await page.textContent(`#tab-compare .io-tnode[data-id="${gps.id}"] .io-props`);
  expect(props.includes("gps") && props.includes("gnss"), `property diff old/new: ${props}`);
  // Filters: hiding "modified" leaves nothing to show.
  await page.uncheck('#tab-compare input[data-filter="modified"]');
  await page.waitForSelector('#tab-compare .io-empty:has-text("No differences match")');
  await page.check('#tab-compare input[data-filter="modified"]');
  // Collapse / expand with the keyboard, then navigate with Enter.
  await page.click(`#tab-compare .io-tnode[data-id="${gps.id}"] > .io-trow .io-tkind`);
  await page.keyboard.press("ArrowLeft");
  await page.waitForFunction((id) => !document.querySelector(`#tab-compare .io-tnode[data-id="${id}"] .io-props`), gps.id);
  await page.keyboard.press("ArrowRight");
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${gps.id}"] .io-props`);
  await page.click(`#tab-compare .io-tnode[data-id="${gps.id}"] > .io-trow [data-nav]`);
  await page.waitForFunction((id) => document.querySelector(`#tree .tree-node.selected`)?.dataset.id === id, gps.id);

  // 6. Model Check: add a port nobody wires, run, check the badge, filter, click an issue to navigate.
  const gpsDef = comps.find((r) => r[hdr.indexOf("Name")] === "GPSReceiver")[hdr.indexOf("ID")];
  await api("POST", "/api/element", { kind: "PortUsage", name: "maintenance", parent: gpsDef });
  await page.evaluate(() => window.studio.refreshTree());
  await page.click('.tab[data-tab="checks"]');
  await page.waitForSelector('#tab-checks table[data-k="issues"] tr.io-issue');
  const badge = await page.textContent('.tab[data-tab="checks"] .io-tab-badge');
  expect(Number(badge) > 0, `badge shows the issue count: ${badge}`);
  await page.click('#tab-checks [data-sev="info"]');
  const sevs = await page.$$eval("#tab-checks tr.io-issue", (rows) => rows.map((r) => r.dataset.sev));
  expect(sevs.length && sevs.every((s) => s !== "info"), `info hidden: ${sevs}`);
  await page.selectOption('#tab-checks select[data-k="rule"]', "advisor.unconnected-port");
  const issue = await page.$eval("#tab-checks tr.io-issue", (tr) => ({ id: tr.dataset.id, qn: tr.querySelector(".io-qn").textContent, text: tr.textContent }));
  await page.click("#tab-checks tr.io-issue");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, issue.id);
  await page.waitForFunction((qn) => document.querySelector("#props-qname")?.textContent === qn, issue.qn);
  // The port belongs to the GPSReceiver definition: the issue names the usage that leaves it open.
  expect(issue.qn.endsWith("FlightDeck::gnss") && issue.text.includes("Port gnss.maintenance is not connected in FlightDeck"),
         `unconnected port reported on its usage: ${issue.qn} ${issue.text}`);
  // Back to all rules; search narrows the table; keyboard Enter navigates as well.
  await page.selectOption('#tab-checks select[data-k="rule"]', "");
  await page.fill('#tab-checks input[data-k="search"]', "maintenance");
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll("#tab-checks tr.io-issue")];
    return rows.length && rows.every((r) => r.textContent.includes("maintenance"));
  });
  const kbIssue = await page.$eval("#tab-checks tr.io-issue", (tr) => tr.dataset.id);
  await page.focus("#tab-checks tr.io-issue");
  await page.keyboard.press("Enter");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, kbIssue);
}
