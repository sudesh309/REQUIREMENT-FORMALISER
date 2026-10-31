// Avionics pack: the FHA table editor. Edit cells (classification, text, function), add a row
// through the dialog, delete it, undo, and see the avionics rules follow (Safety check, Model
// Check); the FHA rows are model elements (tree, Properties) and survive Save JSON / Load JSON.
import { unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, waitReady, expect, api, errors }, step) {
  const native = [];
  page.on("dialog", (d) => { native.push(`${d.type()}: ${d.message()}`); d.dismiss().catch(() => {}); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await api("POST", "/api/new/avionics", { template: "ima_example" });
  await waitReady();

  const until = (fn, arg, what, timeout = 15000) => page.waitForFunction(fn, arg, { timeout })
    .catch(() => { throw new Error(`timed out: ${what}`); });
  const undoIs = (label) => until((l) => document.querySelector('button[data-plugin-button="undo"]')?.title === `Undo ${l} (Ctrl+Z)`,
                                  label, `undo step '${label}'`);
  const tab = async (id) => {
    await page.click(`#tab-bar .tab[data-tab="${id}"]`);
    await until((t) => !document.querySelector(`#tab-${t}`)?.classList.contains("hidden"), id, `${id} tab shown`);
  };
  const view = async (v) => {
    await tab("avionics");
    await page.click(`[data-av-go="${v}"]`);
    await page.waitForSelector(`[data-av-view="${v}"]:not(.off)`);
  };
  const row = (id) => `[data-av-fha="${id}"]`;
  const rowCount = () => page.$$eval("[data-av-fha]", (r) => r.length);
  const dalOf = (id) => page.$eval(`${row(id)} [data-av-cell="dal"]`, (c) => c.textContent.trim());
  const apiRow = async (id) => (await api("GET", "/api/avionics/fha")).rows.find((r) => r.fha_id === id);
  // Ctrl+Z is a studio shortcut outside text fields: leave the cell first.
  const undoKey = async () => { await page.click('[data-av="status"]'); await page.keyboard.press("Control+z"); };

  // =========================================================================================
  step("table");
  await view("fha");
  await page.waitForSelector('[data-av="fha-table"]');
  expect(await rowCount() === 21, `21 FHA rows (${await rowCount()})`);
  const counts = await page.$eval('[data-av="fha-counts"]', (c) => c.textContent);
  expect(/Catastrophic 4/.test(counts) && /Hazardous 8/.test(counts) && /No Safety Effect 1/.test(counts), `class counts: ${counts}`);
  expect(await dalOf("FHA-1") === "B" && await dalOf("FHA-2") === "A" && await dalOf("FHA-21") === "E", "assigned DALs follow the mapping");
  expect(await page.$eval(`${row("FHA-1")} [data-av-field="function"]`, (s) => s.selectedOptions[0].textContent) === "ProvideAirData",
         "the function column names the function");
  const items = await page.$eval(`${row("FHA-1")} [data-av-cell="items"]`, (c) => c.textContent);
  expect(/AirDataSystem \(A\)/.test(items) && /ADC1 \(B\)/.test(items) && /ADC2 \(B\)/.test(items), `allocated items: ${items}`);

  // =========================================================================================
  step("classification edit fires a rule");
  const before = (await api("GET", "/api/avionics/safety")).counts;
  expect(before.error === 0, "no error to begin with");
  await page.selectOption(`${row("FHA-9")} [data-av-field="classification"]`, "Catastrophic");
  await undoIs("Set classification of FHA-9 to Catastrophic");
  await until(() => document.querySelector('[data-av-fha="FHA-9"] [data-av-cell="dal"]')?.textContent.trim() === "A", null, "DAL chip follows");
  expect((await apiRow("FHA-9")).classification === "Catastrophic", "stored on the server");
  // The tree shows the row's badges (the tree was refreshed by the edit).
  await until(() => [...document.querySelectorAll("#tree .tree-node")].some((n) =>
    n.textContent.includes("FHA-9") && n.textContent.includes("Catastrophic")), null, "tree badge");
  await view("safety");
  await page.waitForSelector('tr[data-av-issue][data-rule="avionics.dal.allocation"]');
  const text = (await page.$$eval('tr[data-av-issue][data-rule="avionics.dal.allocation"]', (rs) => rs.map((r) => r.textContent))).join(" | ");
  expect(/ManageFlight needs DAL A \(FHA-9\)/.test(text) && /FlightManagement \(DAL C\)/.test(text) && /P_FMS \(DAL C\)/.test(text),
         `rule text: ${text.slice(0, 300)}`);
  expect((await api("GET", "/api/interop/check")).by_rule["avionics.dal.allocation"] === 2, "Model Check lists both layers too");
  // Undo with the keyboard (outside a text field): the row and the rules go back.
  await undoKey();
  await until(() => !document.querySelector('button[data-plugin-button="undo"]')?.title.includes("FHA-9"), null, "undone");
  expect((await apiRow("FHA-9")).classification === "Major", "classification restored");
  await view("fha");
  await until(() => document.querySelector('[data-av-fha="FHA-9"] [data-av-field="classification"]')?.value === "Major", null, "table follows undo");
  expect((await api("GET", "/api/avionics/safety")).counts.error === 0, "rules quiet again");

  // =========================================================================================
  step("text edits");
  const fc = `${row("FHA-9")} [data-av-field="failure_condition"]`;
  await page.fill(fc, "Loss of flight management function");
  await page.press(fc, "Enter");
  await undoIs("Edit the failure condition of FHA-9");
  expect((await apiRow("FHA-9")).failure_condition === "Loss of flight management function", "failure condition saved");
  // Escape puts the stored value back without a request.
  await page.fill(fc, "typo");
  await page.press(fc, "Escape");
  expect(await page.inputValue(fc) === "Loss of flight management function", "Escape reverts the cell");
  // Flight phases are normalised by the server.
  const ph = `${row("FHA-9")} [data-av-field="flight_phase"]`;
  await page.fill(ph, "cruise, climb");
  await page.press(ph, "Enter");
  await until((s) => document.querySelector(s)?.value === "Climb,Cruise", ph, "phases normalised");
  // Clearing the function leaves the failure condition without an allocated function.
  await page.selectOption(`${row("FHA-9")} [data-av-field="function"]`, "");
  await undoIs("Clear the function of FHA-9");
  await until(() => document.querySelector('[data-av-fha="FHA-9"] [data-av-cell="items"]')?.textContent.includes("no function"), null, "no function chip");
  expect((await api("GET", "/api/avionics/safety?rule=avionics.fha.unallocated")).issues.length === 1, "the rule reports it");
  await undoKey();
  await until(() => document.querySelector('[data-av-fha="FHA-9"] [data-av-field="function"]')?.selectedOptions[0]?.textContent === "ManageFlight", null, "function back");

  // An invalid value is refused: the server says why, the cell goes back.
  step("invalid value");
  await page.fill(ph, "Orbit");
  await page.press(ph, "Enter");
  await until((s) => document.querySelector(s)?.value === "Climb,Cruise", ph, "refused phase reverts");
  expect(await page.$eval("#log", (l) => l.textContent.includes("flight phase 'Orbit' is not one of")), "the reason is in the Output log");
  errors.length = 0;                                   // the refused request is expected

  // =========================================================================================
  step("add and delete a row");
  await page.click('[data-av-act="fha-add"]');
  await page.waitForSelector('#modal-root [name="failure_condition"]');
  await page.selectOption('#modal-root [name="function"]', { label: "ProvideAttitude" });
  await page.fill('#modal-root [name="failure_condition"]', "Hardover of attitude output");
  await page.uncheck('#modal-root [name="phase_All"]');
  await page.check('#modal-root [name="phase_Climb"]');
  await page.check('#modal-root [name="phase_Cruise"]');
  await page.fill('#modal-root [name="effect"]', "Misleading attitude");
  await page.selectOption('#modal-root [name="classification"]', "Hazardous");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForSelector(row("FHA-22"));
  await undoIs("Add FHA row FHA-22");
  expect(await rowCount() === 22 && await dalOf("FHA-22") === "B", "the new row has its DAL");
  expect(await page.inputValue(`${row("FHA-22")} [data-av-field="flight_phase"]`) === "Climb,Cruise", "phases from the checkboxes");
  expect(/IRU1/.test(await page.$eval(`${row("FHA-22")} [data-av-cell="items"]`, (c) => c.textContent)), "its function's items are listed");
  await page.click('[data-av-del="FHA-22"]');
  await page.waitForSelector('#modal-root [data-modal-submit]');
  await page.click("#modal-root [data-modal-submit]");
  await until(() => !document.querySelector('[data-av-fha="FHA-22"]'), null, "row deleted");
  await undoIs("Delete FHA row FHA-22");
  await undoKey();
  await page.waitForSelector(row("FHA-22"));

  // =========================================================================================
  step("rows are model elements");
  await tab("properties");
  await page.click('#tree .tree-node > .row:has-text("FHA-9")');
  await page.waitForSelector('[data-section="avionics-safety"] [data-av-act="open-fha"]');
  const sect = await page.$eval('[data-section="avionics-safety"]', (s) => s.textContent);
  expect(/Major/.test(sect) && /ManageFlight/.test(sect), `FHA section: ${sect.slice(0, 160)}`);
  await page.click('[data-section="avionics-safety"] [data-av-act="open-fha"]');
  await page.waitForSelector('[data-av-view="fha"]:not(.off) [data-av="fha-table"]');

  // =========================================================================================
  step("save and load");
  const [saved] = await Promise.all([page.waitForEvent("download"), page.click('header [data-cmd="save"]')]);
  const path = join(tmpdir(), `fha-${Date.now()}-${saved.suggestedFilename()}`);
  await saved.saveAs(path);
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root input[name=name]");
  await page.fill("#modal-root input[name=name]", "Scratch");
  await page.press("#modal-root input[name=name]", "Enter");
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("Scratch"), null, "new project");
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click('header [data-cmd="load"]')]);
  await chooser.setFiles(path);
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("IMA_Avionics"), null, "project loaded");
  await view("fha");
  await until(() => document.querySelectorAll("[data-av-fha]").length === 22, null, "22 rows after loading");
  expect(await page.inputValue(`${row("FHA-9")} [data-av-field="failure_condition"]`) === "Loss of flight management function",
         "edits survived Save / Load");
  unlinkSync(path);

  // =========================================================================================
  step("hygiene");
  expect(native.length === 0, `no window.prompt / confirm / alert: ${native.join(" | ")}`);
  expect(errors.length === 0, `no browser errors: ${errors.join(" | ")}`);
}
