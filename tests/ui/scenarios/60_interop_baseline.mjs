// "Compare with Last Saved" right after opening a project (PO-12): Save JSON, New, Load JSON
// of the same file, Compare -> With Last Saved reports "No differences" (the loaded file is
// the last saved version), an edit after loading shows up, and Undo keeps the baseline.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "data", "interop_ima_avionics_demo.json");

export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("BaselineUi");
  await api("POST", "/api/load", { text: readFileSync(FIXTURE, "utf8") });
  await waitReady();
  const logHas = (text) => page.waitForFunction((t) => document.querySelector("#log")?.textContent.includes(t), text);

  // Save JSON (header) downloads the project file.
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('header [data-cmd="save"]')]);
  const savedText = readFileSync(await download.path(), "utf8");
  await logHas("Saved project.json");

  // New project, then Load JSON of the saved file through the file chooser.
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root input[name=name]");
  await page.fill("#modal-root input[name=name]", "Scratch");
  await page.press("#modal-root input[name=name]", "Enter");
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent.startsWith("Scratch"));
  const chooser = page.waitForEvent("filechooser");
  await page.click('header [data-cmd="load"]');
  await (await chooser).setFiles({ name: "project.json", mimeType: "application/json", buffer: Buffer.from(savedText) });
  await logHas("Loaded project");

  // Compare -> With Last Saved: the loaded file is the baseline, so nothing differs.
  await page.click('.tab[data-tab="compare"]');
  await page.click('#tab-compare [data-io="compare-saved"]');
  await page.waitForSelector('#tab-compare [data-c="nodiff"]');
  expect((await page.textContent('#tab-compare [data-c="nodiff"]')).includes("No differences"), "no differences after Load JSON");
  expect(!(await page.$('#tab-compare .io-banner.info:has-text("no saved version")')), "a baseline exists");

  // An edit after loading is a difference; Undo goes back to the loaded state, still compared
  // with the same baseline.
  const tree = await api("GET", "/api/tree");
  const find = (n, name) => n.name === name ? n : (n.children || []).reduce((hit, c) => hit || find(c, name), null);
  const fms = find(tree, "FMS");
  await api("PATCH", `/api/element/${fms.id}`, { props: { name: "FMS2" } });
  await page.click('#tab-compare [data-io="compare-saved"]');
  await page.waitForSelector(`#tab-compare .io-tnode[data-id="${fms.id}"]`);
  expect((await page.textContent('#tab-compare [data-count="modified"]')).includes("1 modified"), "edit after load");
  await api("POST", "/api/undo");
  await page.click('#tab-compare [data-io="compare-saved"]');
  await page.waitForSelector('#tab-compare [data-c="nodiff"]');
}
