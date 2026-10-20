// Three-way merge through the Compare tab (one conflict resolved with "Theirs", one change
// merged automatically), Compare with Last Saved after the header's Save JSON, and the HTML
// report: preview with rendered Mermaid diagrams, then download.
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const XMI = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "data", "interop_avionics_cameo.xmi");

const selectedId = (page) => page.evaluate(() => document.querySelector("#tree .tree-node.selected")?.dataset.id);

export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("MergeUi");
  await api("POST", "/api/interop/xmi/import", { text: readFileSync(XMI, "utf8"), mode: "new" });
  const work = mkdtempSync(join(tmpdir(), "interop-merge-"));

  // base = the imported model; theirs renames gps (conflict) and pfd (no conflict).
  const base = (await api("GET", "/api/save")).text;
  const theirs = JSON.parse(base);
  const byName = (data, name) => data.elements.find((e) => e.name === name);
  byName(theirs, "gps").name = "gnssTheirs";
  byName(theirs, "pfd").name = "display";
  writeFileSync(join(work, "base.json"), base);
  writeFileSync(join(work, "theirs.json"), JSON.stringify(theirs));
  // mine = the current project with gps renamed differently.
  const gpsId = byName(theirs, "gnssTheirs").id;
  const pfdId = byName(theirs, "display").id;
  await api("PATCH", `/api/element/${gpsId}`, { props: { name: "gnssMine" } });
  await waitReady();

  // 1. Three-way merge dialog: base + theirs files, mine = current project.
  await page.click('.tab[data-tab="compare"]');
  await page.click('#tab-compare [data-io="merge"]');
  await page.setInputFiles('#modal-form input[name="base"]', join(work, "base.json"));
  await page.setInputFiles('#modal-form input[name="theirs"]', join(work, "theirs.json"));
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#tab-compare table[data-c="conflicts"]');
  expect((await page.textContent('#tab-compare [data-c="conflict-count"]')).startsWith("1 conflict"), "one conflict");
  const row = await page.textContent("#tab-compare [data-conflict-row]");
  expect(row.includes("gnssMine") && row.includes("gnssTheirs") && row.includes("gps"), `conflict shows base/mine/theirs: ${row}`);
  // The conflict's element link navigates to it.
  await page.click("#tab-compare [data-conflict-row] [data-nav]");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, gpsId);
  // Choose Theirs, apply: the result becomes the current project.
  await page.click('#tab-compare [data-conflict-row] label:has-text("Theirs")');
  await page.waitForSelector('#tab-compare [data-conflict-row] label.on:has-text("Theirs")');
  await page.click('#tab-compare [data-merge="apply"]');
  await page.waitForSelector('#tab-compare .io-banner:has-text("Merge applied")');
  expect((await api("GET", `/api/element/${gpsId}`)).name === "gnssTheirs", "conflict resolved with theirs");
  expect((await api("GET", `/api/element/${pfdId}`)).name === "display", "non-conflicting change merged automatically");
  await page.waitForSelector('#tree .tree-node .row:has-text("gnssTheirs")');
  expect(!(await selectedId(page)), "selection cleared after the project changed");

  // 2. Before any save there is nothing to compare with; Save JSON (header) remembers the
  //    saved state and Compare with Last Saved shows the next edit.
  await page.click('#tab-compare [data-io="compare-saved"]');
  await page.waitForSelector('#tab-compare .io-banner.info:has-text("no saved version")');
  const [saved] = await Promise.all([page.waitForEvent("download"), page.click('header [data-cmd="save"]')]);
  expect(saved.suggestedFilename() === "project.json", "project saved");
  await page.waitForFunction(async () => (await (await fetch("/api/interop/snapshot")).json()).label === "Last saved");
  await api("PATCH", `/api/element/${pfdId}`, { props: { name: "pfdLeft" } });
  await page.click('#tab-compare [data-io="compare-saved"]');
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${pfdId}"]`);
  expect((await page.textContent('#tab-compare [data-count="modified"]')).includes("1 modified"), "edit since save");
  // Search filters the tree.
  await page.fill('#tab-compare input[data-c="search"]', "nothing-matches-this");
  await page.waitForSelector('#tab-compare .io-empty:has-text("No differences match")');
  await page.fill('#tab-compare input[data-c="search"]', "pfdLeft");
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${pfdId}"]`);

  // 3. Report: preview renders the Mermaid diagrams; Download HTML saves the file.
  await page.click('.tab[data-tab="interop"]');
  await page.click('#tab-interop [data-io="report"]');
  await page.fill('#tab-interop input[data-r="title"]', "Flight Deck SAR");
  await page.click('#tab-interop button[data-r="generate"]');
  const frame = page.frameLocator('#tab-interop iframe[data-r="frame"]');
  await frame.locator("h1:has-text('Flight Deck SAR')").waitFor({ timeout: 15000 });
  await frame.locator("#sec-diagrams svg").first().waitFor({ timeout: 15000 });
  expect((await frame.locator("#sec-components").textContent()).includes("display"), "components section lists merged names");
  await page.uncheck('#tab-interop input[data-r="inline"]');
  const [report] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop button[data-r="download"]')]);
  expect(report.suggestedFilename() === "FlightDeckModel_report.html", `report file: ${report.suggestedFilename()}`);
  const html = readFileSync(await report.path(), "utf8");
  expect(html.includes("<title>Flight Deck SAR</title>") && html.includes("/static/vendor/mermaid"), "report html");
}
