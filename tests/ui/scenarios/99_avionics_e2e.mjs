// Wave gate (PO-16): build a small avionics model in the studio with GUI gestures only —
// clicks, drags and the keyboard; no API call changes the model (API GETs only check it).
//
//   1. New model: functional architecture (functions + flows) on the canvas
//   2. Physical architecture: LRUs, ports, connectors drawn port to port
//   3. Interfaces: ARINC 429 word from a template, dragged onto a canvas port
//   4. Profile: Avionics.LRU with mass / power / DAL, applied and valued
//   5. Requirements: a set authored in the table, linked by dragging rows onto blocks
//   6. Allocation: functions to LRUs in the matrix
//   7. Model Check count, report, Save JSON / New / Load JSON
//
// Checks the canvas Property Inspector, block badges, undo labels and the Model Check count
// along the way. Run it before closing every wave (docs/EXTENDING.md, "Wave gate").
import { readFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, waitReady, expect, api }, step) {
  const native = [];
  page.on("dialog", (d) => { native.push(`${d.type()}: ${d.message()}`); d.dismiss().catch(() => {}); });
  const failed = [];                                       // every request of the GUI succeeds
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await waitReady();

  const until = (fn, arg, what, timeout = 10000) => page.waitForFunction(fn, arg, { timeout })
    .catch(() => { throw new Error(`timed out: ${what}`); });
  const modalGone = () => until(() => !document.querySelector("#modal-root .modal"), null, "dialog closed");
  const submitModal = async () => { await page.click("#modal-root [data-modal-submit]"); await modalGone(); };
  const tab = async (id) => {
    await page.click(`#tab-bar .tab[data-tab="${id}"]`);
    await until((t) => !document.querySelector(`#tab-${t}`)?.classList.contains("hidden"), id, `${id} tab shown`);
  };
  // UI_E2E_SHOTS=1 keeps a screenshot of every stage in UI_ARTIFACT_DIR for reviewers.
  const shot = async (name) => {
    if (process.env.UI_E2E_SHOTS) await page.screenshot({ path: join(process.env.UI_ARTIFACT_DIR || tmpdir(), `99_${name}.png`) });
  };
  const undoTip = () => page.getAttribute('button[data-plugin-button="undo"]', "title");
  const undoIs = (label) => until((l) => document.querySelector('button[data-plugin-button="undo"]')?.title === `Undo ${l} (Ctrl+Z)`,
                                  label, `undo step '${label}'`);

  // ---- canvas helpers --------------------------------------------------------------------
  const block = (n) => `.arch-block[data-name="${n}"]`;
  const port = (c, p) => `${block(c)} .arch-port[data-name="${p}"]`;
  const box = async (sel) => {
    for (let i = 0; i < 60; i++) {
      const h = await page.$(sel);
      const b = h && await h.boundingBox();
      if (b) return b;
      await page.waitForTimeout(50);
    }
    throw new Error(`not on screen: ${sel}`);
  };
  const center = async (sel) => { const b = await box(sel); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
  const nameInPlace = async (name) => {
    await page.waitForSelector(".arch-inline-edit:not([hidden])");
    await page.fill(".arch-inline-edit", name);
    await page.press(".arch-inline-edit", "Enter");
  };
  const clickBlock = async (name) => {
    const b = await box(`${block(name)} .arch-body`);
    await page.mouse.click(b.x + 14, b.y + b.height - 12);
    await until((s) => document.querySelector(s)?.classList.contains("sel"), block(name), `${name} selected`);
  };
  const addComponent = async (name) => {
    await page.click('[data-canvas-act="add-component"]');
    await nameInPlace(name);
    await page.waitForSelector(block(name));
  };
  const addPort = async (comp, dir, name) => {
    await clickBlock(comp);
    await page.click(`[data-canvas-act="add-port-${dir}"]`);
    await nameInPlace(name);
    await page.waitForSelector(port(comp, name));
  };
  const connect = async (from, to) => {
    const n = await page.$$eval(".arch-conn", (xs) => xs.length);
    const a = await center(`${from} .arch-port-glyph`);
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(a.x + 12, a.y + 4, { steps: 3 });
    const b = await center(`${to} .arch-port-glyph`);
    await page.mouse.move(b.x, b.y, { steps: 10 });
    await page.mouse.up();
    await until((k) => document.querySelectorAll(".arch-conn").length === k, n + 1, "connector drawn");
  };
  // Arrange (toolstrip): blocks that grew with their port labels are laid out side by side.
  const arrange = async () => {
    await page.click('[data-canvas-act="arrange"]');
    await undoIs("Arrange");
  };
  const frameIs = (name) => until((n) => document.querySelector(".arch-frame-title")?.textContent.startsWith(n),
                                  name, `${name} open on the canvas`);
  const openArchitecture = async (name) => {
    await page.selectOption('[data-canvas="open"]', { label: `AircraftAvionics::${name}` });
    await frameIs(name);
  };
  // A second architecture: the canvas's own New architecture command when the canvas has one,
  // else a generic Part Def from Advanced ▾ (inside the project root), opened with Open ▾.
  const newArchitecture = async (name) => {
    const onCanvas = await page.$('.arch-bar [data-canvas-act="new-architecture"]');
    if (onCanvas) {
      await onCanvas.click();
      await nameInPlace(name);
      await frameIs(name);
      return;
    }
    await page.click("#tree > li > .row");
    await until(() => document.querySelector("#status")?.textContent.startsWith("Package"), null, "project root selected");
    await page.click('[data-cmd="advanced-menu"]');
    await page.click('#advanced-menu .btn-add[data-kind="PartDefinition"]');
    await page.fill('#modal-form [name="name"]', name);
    await page.press('#modal-form [name="name"]', "Enter");
    await modalGone();
    await tab("architecture");
    await openArchitecture(name);
  };
  // The canvas Property Inspector's value of a stereotype property with its unit ("7 kg"):
  // a read-only row, or a value editor followed by its unit.
  const DOCK_VALUE = (k) => {
    const row = document.querySelector(`.arch-dock [data-stereo-value="${k}"] b`);
    if (row) return row.textContent.trim();
    const input = document.querySelector(`.arch-dock [data-path$=".${k}"]`);
    if (!input) return null;
    const unit = input.nextElementSibling?.matches(".pf-unit") ? input.nextElementSibling.textContent.trim() : "";
    return unit ? `${input.value} ${unit}` : input.value;
  };
  const dockValue = (key) => page.evaluate(DOCK_VALUE, key);
  const dockValueIs = (key, v, what) => page.waitForFunction(`(${DOCK_VALUE})(${JSON.stringify(key)}) === ${JSON.stringify(v)}`,
                                                             null, { timeout: 10000 })
    .catch(async () => { throw new Error(`timed out: ${what} (the dock shows ${await dockValue(key)})`); });
  const pills = (name) => page.$$eval(`${block(name)} .arch-pill text`, (ts) => ts.map((t) => t.textContent));

  // =========================================================================================
  step("new model");
  await page.click('[data-plugin-button="new-model"]');
  await page.fill('#modal-form [name="name"]', "AircraftAvionics");
  await page.fill('#modal-form [name="arch"]', "FunctionalArch");
  await submitModal();
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("AircraftAvionics"), null, "project named");
  await until(() => document.querySelector(".arch-frame-title")?.textContent.startsWith("FunctionalArch"), null, "root architecture open");

  // =========================================================================================
  step("functional architecture");
  for (const f of ["AcquireAirData", "ComputeNavigation", "DisplayFlightData"]) await addComponent(f);
  expect(await undoTip() === "Undo Add component DisplayFlightData (Ctrl+Z)", `add + name is one step: ${await undoTip()}`);
  await addPort("AcquireAirData", "out", "airData");
  await addPort("ComputeNavigation", "in", "airData");
  await addPort("ComputeNavigation", "out", "navSolution");
  await addPort("DisplayFlightData", "in", "navSolution");
  await arrange();
  await connect(port("AcquireAirData", "airData"), port("ComputeNavigation", "airData"));
  await connect(port("ComputeNavigation", "navSolution"), port("DisplayFlightData", "navSolution"));
  expect(await undoTip() === "Undo Connect ComputeNavigation.navSolution → DisplayFlightData.navSolution (Ctrl+Z)",
         `connector step named: ${await undoTip()}`);

  // =========================================================================================
  step("physical architecture");
  await newArchitecture("PhysicalArch");
  for (const lru of ["ADIRU", "FMS", "CDS"]) await addComponent(lru);
  await addPort("ADIRU", "out", "airData");
  await addPort("FMS", "in", "airData");
  await addPort("FMS", "out", "navData");
  await addPort("CDS", "in", "navData");
  await arrange();
  await connect(port("ADIRU", "airData"), port("FMS", "airData"));
  await connect(port("FMS", "navData"), port("CDS", "navData"));
  await page.keyboard.press("Escape");                     // nothing selected: the dock describes the architecture
  await until(() => document.querySelector(".arch-dock")?.textContent.includes("Architecture"), null, "dock shows the architecture");
  const archKv = await page.$$eval(".arch-dock .arch-kv", (xs) => Object.fromEntries(
    xs.map((x) => [x.querySelector("span").textContent, x.querySelector("b").textContent.trim()])));
  expect(archKv.Components === "3" && archKv.Connectors === "2", `dock counts ${JSON.stringify(archKv)}`);

  // =========================================================================================
  step("interfaces");
  // Interface Editor: an ARINC 429 word from the avionics template ...
  const ifcIdle = () => until(() => !Number(document.body.dataset.ifcPending || 0), null, "interface editor idle");
  await page.click('#ribbon [data-plugin-button="interface-editor"]');
  await ifcIdle();
  await page.selectOption('[data-ifc="template"]', "arinc429");
  await ifcIdle();
  await page.waitForSelector('.ifc-item.sel:has-text("A429Word")');
  // ... dragged from the editor's list onto ADIRU's output port: holding the drag over the
  // Architecture tab opens the canvas.
  const item = await center('.ifc-item:has-text("A429Word")');
  await page.mouse.move(item.x, item.y);
  await page.mouse.down();
  await page.mouse.move(item.x + 10, item.y + 6, { steps: 3 });
  const archTab = await center('#tab-bar .tab[data-tab="architecture"]');
  await page.mouse.move(archTab.x, archTab.y, { steps: 8 });
  await until(() => !document.querySelector("#tab-architecture").classList.contains("hidden"), null, "spring-loaded Architecture tab");
  const target = await center(`${port("ADIRU", "airData")} .arch-port-glyph`);
  await page.mouse.move(target.x, target.y, { steps: 8 });
  await page.mouse.up();
  await undoIs("Assign A429Word to ADIRU.airData");
  // The other end through the Property Inspector: select the port, pick the interface.
  const portSel = async (c, p) => {
    await page.click(`${port(c, p)} .arch-port-glyph`);
    await until((s) => document.querySelector(s)?.classList.contains("sel"), port(c, p), `${c}.${p} selected`);
  };
  await portSel("FMS", "airData");
  await page.selectOption('.arch-dock [data-dock="port-interface"]', { label: "A429Word (DataInterface)" });
  await undoIs("Assign A429Word to FMS.airData");
  await portSel("ADIRU", "airData");
  expect(await page.$eval('.arch-dock [data-dock="port-interface"]', (s) => s.selectedOptions[0]?.textContent) === "A429Word (DataInterface)",
         "the dock shows the dropped interface");
  await shot("interfaces");

  // =========================================================================================
  step("profile");
  await page.click('#ribbon [data-plugin-button="profile-editor"]');
  await page.click('[data-pf-cmd="new-profile"]');
  await page.fill('#modal-form [name="name"]', "Avionics");
  await page.press('#modal-form [name="name"]', "Enter");
  await page.waitForSelector('.pf-row[data-kind="profile"]');
  await page.click('[data-pf-cmd="new-stereotype"]');
  await page.fill('#modal-form [name="name"]', "LRU");
  await page.selectOption('#modal-form [name="applies_to"]', "Component");
  await submitModal();
  await until(() => document.querySelector(".pf-title")?.textContent.includes("«Avionics.LRU»"), null, "stereotype shown");
  const propRow = (i) => `tr[data-prop-id]:nth-of-type(${i})`;
  const propCell = async (i, col, value) => {
    await page.fill(`${propRow(i)} [data-col="${col}"]`, value);
    await page.press(`${propRow(i)} [data-col="${col}"]`, "Enter");
    await until(([i, col, v]) => document.querySelectorAll(`tr[data-prop-id] [data-col="${col}"]`)[i - 1]?.getAttribute("value") === v,
                [i, col, value], `property ${i} ${col} = ${value}`);
  };
  await page.click('[data-pf-cmd="add-property"]');
  await propCell(1, "name", "mass");
  await propCell(1, "unit", "kg");
  await page.click('[data-pf="add-prop"]');
  await until(() => document.querySelectorAll("tr[data-prop-id]").length === 2, null, "second property row");
  await propCell(2, "name", "power");
  await propCell(2, "unit", "W");
  await page.click('[data-pf="add-prop"]');
  await until(() => document.querySelectorAll("tr[data-prop-id]").length === 3, null, "third property row");
  await propCell(3, "name", "dal");
  await page.selectOption(`${propRow(3)} [data-col="type"]`, "enumeration");
  await page.waitForSelector(`${propRow(3)}.pf-pending`);
  await propCell(3, "literals", "A, B, C, D, E");

  // Apply «Avionics.LRU» to the three LRUs selected on the canvas (Ctrl+A).
  await tab("architecture");
  await clickBlock("ADIRU");
  await page.keyboard.press("Control+a");
  await until(() => document.querySelectorAll(".arch-block.sel").length === 3, null, "all LRUs selected");
  await page.click('#ribbon [data-plugin-button="batch-apply-stereotype"]');
  await page.waitForSelector('#modal-form [name="stereotype"]');
  expect(await page.isChecked('#modal-form input[name="scope"][value="selection"]'), "the canvas selection is the default scope");
  await submitModal();
  await until(() => document.querySelector("#log")?.textContent.includes("Applied «Avionics.LRU» to 3 element(s)"), null, "applied to 3");
  for (const lru of ["ADIRU", "FMS", "CDS"]) {
    await until((s) => [...document.querySelectorAll(`${s} .arch-pill text`)].some((t) => t.textContent === "«LRU»"),
                block(lru), `«LRU» badge on ${lru}`);
  }
  await undoIs("Apply «Avionics.LRU» to 3 element(s)");

  // Values in the Properties tab (opened from the canvas Property Inspector); the dock follows.
  const setValues = async (lru, values) => {
    await tab("architecture");
    await clickBlock(lru);
    await page.click('.arch-dock [data-dock-act="properties"]');
    for (const [prop, value] of Object.entries(values)) {
      const sel = `[data-section="stereotypes"] [data-path="Avionics.LRU.${prop}"]`;
      await page.waitForSelector(sel);
      if (prop === "dal") await page.selectOption(sel, value);
      else { await page.fill(sel, value); await page.press(sel, "Enter"); }
      await undoIs(`Set Avionics.LRU.${prop} of ${lru}`);
    }
  };
  await setValues("FMS", { mass: "7", power: "120", dal: "B" });
  await setValues("ADIRU", { mass: "9 lb", power: "45" });
  await setValues("CDS", { mass: "6.5", power: "85" });
  await tab("architecture");
  await clickBlock("FMS");
  await dockValueIs("mass", "7 kg", "FMS mass in the dock");
  expect(await dockValue("power") === "120 W" && await dockValue("dal") === "B",
         `FMS values in the dock: ${await dockValue("power")}, ${await dockValue("dal")}`);
  await clickBlock("ADIRU");
  await dockValueIs("mass", "4.08233133 kg", "ADIRU mass converted from lb");
  await shot("profile");

  // =========================================================================================
  step("requirements");
  const rqIdle = () => until(() => document.body.dataset.rqPending === "0", null, "requirements idle");
  const reqRow = (id) => `#tab-requirements tr[data-req-id="${id}"]`;
  await page.click('#ribbon [data-open-tab="requirements"]');
  await rqIdle();
  await page.click('[data-rq="new-set"]');
  await page.fill('#modal-form input[name="name"]', "AvionicsSystemRequirements");
  await page.fill('#modal-form input[name="prefix"]', "SYS-");
  await submitModal();
  await rqIdle();
  const summaries = ["Provide air data to the flight management function",
                     "Compute the navigation solution",
                     "Display navigation data to the crew"];
  for (const [i, text] of summaries.entries()) {
    await page.click('[data-rq="add"]');
    await rqIdle();
    await page.fill(`${reqRow(`SYS-${i + 1}`)} input[data-f="summary"]`, text);
    await page.press(`${reqRow(`SYS-${i + 1}`)} input[data-f="summary"]`, "Enter");
    await rqIdle();
  }
  await undoIs("Add requirement SYS-3");

  // Requirements Perspective under the canvas: drag rows onto the LRU blocks.
  await page.click('#ribbon [data-plugin-button="req-perspective"]');
  await tab("architecture");
  const dockRow = (id) => `[data-rq="dock"] tr[data-req-id="${id}"]`;
  await page.waitForSelector(dockRow("SYS-3"));
  await page.click('[data-canvas-act="fit"]');             // the perspective took room: show every block
  await page.waitForTimeout(100);
  const dragRowTo = async (reqId, lru) => {
    const from = await center(`${dockRow(reqId)} td:nth-child(3)`);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(from.x + 8, from.y - 6, { steps: 3 });
    const b = await box(`${block(lru)} .arch-body`);
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2 - 10, { steps: 10 });
    await page.mouse.up();
    await until((s) => document.querySelector(s)?.dataset.implPct === "100", `${dockRow(reqId)} td[data-impl-pct]`,
                `${reqId} implemented by ${lru}`);
  };
  await dragRowTo("SYS-1", "ADIRU");
  await dragRowTo("SYS-2", "FMS");
  await dragRowTo("SYS-3", "CDS");
  await undoIs("Add link CDS implements SYS-3");
  for (const lru of ["ADIRU", "FMS", "CDS"]) {
    await until((s) => [...document.querySelectorAll(`${s} .arch-pill text`)].some((t) => t.textContent === "1 req"),
                block(lru), `"1 req" badge on ${lru}`);
  }
  await page.keyboard.press("Alt+Shift+R");                // close the perspective again
  await shot("requirements");

  // =========================================================================================
  step("allocation");
  await page.click('#ribbon [data-open-tab="allocation"]');
  await page.click('#tab-allocation [data-alloc-act="new-set"]');
  await page.waitForSelector('#modal-form [name="source"]');
  const archOption = (sel, name) => page.$eval(sel, (s, n) => [...s.options].find((o) => o.textContent.includes(`::${n} `))?.value, name);
  await page.fill('#modal-form [name="name"]', "FunctionsToLRUs");
  await page.selectOption('#modal-form [name="source"]', await archOption('#modal-form [name="source"]', "FunctionalArch"));
  await page.selectOption('#modal-form [name="target"]', await archOption('#modal-form [name="target"]', "PhysicalArch"));
  await submitModal();
  await page.waitForSelector("#alloc-matrix");
  const headId = (axis, name) => page.$eval(`#alloc-matrix .${axis}-head[data-id]`, () => null)
    .then(() => page.evaluate(([axis, name]) => [...document.querySelectorAll(`#alloc-matrix .${axis}-head[data-id]`)]
      .find((h) => h.querySelector(".nm")?.textContent === name)?.dataset.id, [axis, name]));
  const cell = async (fn, lru) => `#alloc-matrix td.cell[data-src="${await headId("row", fn)}"][data-tgt="${await headId("col", lru)}"]`;
  const pairs = [["AcquireAirData", "ADIRU"], ["ComputeNavigation", "FMS"], ["DisplayFlightData", "CDS"]];
  for (const [fn, lru] of pairs) {
    const c = await cell(fn, lru);
    await page.click(c);
    await page.waitForSelector(`${c}.on`);
    await undoIs(`Allocate ${fn} → ${lru}`);
  }
  await until(() => document.querySelector("#alloc-stats")?.textContent.startsWith("3 allocations · 3/3 rows"), null, "three allocations");
  await page.click('[data-alloc-side="coverage"]');
  await until(() => document.querySelector("#alloc-cov-pct")?.textContent === "100%", null, "full coverage");
  // Selecting a function highlights its LRU on the canvas (the function itself is selected).
  await page.click(`#alloc-matrix .row-head[data-id="${await headId("row", "ComputeNavigation")}"]`);
  await tab("architecture");
  await page.waitForSelector('.arch-banner[data-banner="highlight"]');
  await openArchitecture("PhysicalArch");
  await until((s) => document.querySelector(s)?.classList.contains("hl"), block("FMS"), "FMS highlighted on the canvas");
  await page.click('.arch-banner [data-banner-clear="highlight"]');
  await shot("allocation");

  // =========================================================================================
  step("model check");
  await page.click('#ribbon [data-open-tab="checks"]');
  await page.waitForSelector('.tab[data-tab="checks"] .io-tab-badge');
  await until(() => !document.querySelector('.tab[data-tab="checks"] .io-tab-badge')?.classList.contains("stale"), null, "checks ran");
  const badge = async () => Number(await page.textContent('.tab[data-tab="checks"] .io-tab-badge'));
  const check = await api("GET", "/api/interop/check");
  expect(await badge() === check.total, `badge ${await badge()} = ${check.total} issues`);
  expect(check.counts.error === 0, `no errors in the model: ${JSON.stringify(check.counts)}`);
  const rows = await page.$$eval("#tab-checks tr.io-issue", (trs) => trs.length);
  expect(rows === check.total, `${rows} rows listed`);
  await shot("model-check");
  // Fix one finding through the GUI: a requirement without text. Clicking the issue selects
  // the requirement; the Requirements editor gets its text; Model Check re-runs: one less.
  await page.selectOption('#tab-checks select[data-k="rule"]', "requirement.empty");
  const emptyReqs = await page.$$eval("#tab-checks tr.io-issue", (trs) => trs.length);
  expect(emptyReqs === 3, `three requirements without text (${emptyReqs})`);
  await page.click('#tab-checks tr.io-issue:has-text("Compute the navigation solution")');
  await until(() => document.querySelector("#tree .tree-node.selected")?.textContent.includes("Compute the navigation solution"),
              null, "the issue selects its requirement");
  await page.click('#ribbon [data-open-tab="requirements"]');
  await rqIdle();
  await page.click(`${reqRow("SYS-2")} .rq-idx`);
  await page.fill('[data-rq="detail"] textarea[data-d="description"]',
                  "The FMS shall compute the aircraft position from ADIRU air data at 20 Hz.");
  await page.press('[data-rq="detail"] textarea[data-d="description"]', "Control+Enter");
  await rqIdle();
  await undoIs("Edit SYS-2 description");
  // The changed requirement made FMS's Implement link suspect (change impact): review it,
  // clear it, and the Model Check count goes down by one.
  const checksSettled = (n, what) => until((n) => Number(document.querySelector('.tab[data-tab="checks"] .io-tab-badge')?.textContent) === n
    && !document.querySelector('.tab[data-tab="checks"] .io-tab-badge').classList.contains("stale"), n, what);
  await page.click('#ribbon [data-open-tab="checks"]');
  await checksSettled(check.total, "one finding fixed, one suspect link more");
  expect((await api("GET", "/api/interop/check")).by_rule["requirements.suspect-link"] === 1, "the FMS link is suspect");
  await page.click('#ribbon [data-open-tab="requirements"]');
  await rqIdle();
  await page.waitForSelector('[data-rq="detail-links"] .rq-link.suspect');
  await page.click('[data-rq="clear-suspect"]');
  await rqIdle();
  await undoIs("Clear suspect links of SYS-2");
  await page.click('#ribbon [data-open-tab="checks"]');
  await checksSettled(check.total - 1, "Model Check count went down by one");
  expect(await page.$$eval("#tab-checks tr.io-issue", (trs) => trs.length) === 2, "two requirements without text left");
  const issuesAfterFix = check.total - 1;

  // =========================================================================================
  step("report");
  await page.click('#ribbon [data-open-tab="interop"]');
  await page.click('#tab-interop [data-io="report"]');
  await until(() => document.querySelector('#tab-interop [data-r="meta"]')?.textContent.includes("generated"), null, "report generated");
  const [reportFile] = await Promise.all([page.waitForEvent("download"), page.click('#tab-interop [data-r="download"]')]);
  expect(/\.html$/.test(reportFile.suggestedFilename()), `report file ${reportFile.suggestedFilename()}`);
  const report = readFileSync(await reportFile.path(), "utf8");
  const missing = ["AircraftAvionics", "PhysicalArch", "ADIRU", "FMS", "CDS", "A429Word", "SYS-1", "SYS-3", "Avionics.LRU"]
    .filter((w) => !report.includes(w));
  expect(!missing.length, `the report names the model's elements; missing ${missing.join(", ")}`);
  await shot("report");

  // =========================================================================================
  step("save / new / load");
  const [saved] = await Promise.all([page.waitForEvent("download"), page.click('header [data-cmd="save"]')]);
  const savedPath = join(tmpdir(), `e2e-${Date.now()}-${saved.suggestedFilename()}`);
  await saved.saveAs(savedPath);
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root input[name=name]");
  expect(!(await page.$("#modal-root [data-unsaved-warning]")), "saved: New does not warn");
  await page.fill("#modal-root input[name=name]", "Scratch");
  await page.press("#modal-root input[name=name]", "Enter");
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("Scratch"), null, "new project");
  await tab("architecture");
  await page.waitForSelector(".arch-empty:not([hidden])");
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click('header [data-cmd="load"]')]);
  await chooser.setFiles(savedPath);
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("AircraftAvionics"), null, "project loaded");
  await openArchitecture("PhysicalArch");
  await clickBlock("FMS");
  await dockValueIs("mass", "7 kg", "FMS mass after loading");
  expect(await dockValue("power") === "120 W" && await dockValue("dal") === "B", "FMS values after loading");
  for (const lru of ["ADIRU", "FMS", "CDS"]) {
    const p = await pills(lru);
    expect(p.includes("«LRU»") && p.includes("1 req"), `${lru} badges after loading: ${p}`);
  }
  await portSel("FMS", "airData");
  expect(await page.$eval('.arch-dock [data-dock="port-interface"]', (s) => s.selectedOptions[0]?.textContent) === "A429Word (DataInterface)",
         "port interface after loading");
  expect(await page.getAttribute('[data-canvas-act="undo"]', "title") === "Nothing to undo (Ctrl+Z)", "a loaded project starts a new history");
  await page.click('#ribbon [data-open-tab="allocation"]');
  await until(() => document.querySelector("#alloc-stats")?.textContent.startsWith("3 allocations"), null, "allocations after loading");
  await page.click('#ribbon [data-open-tab="checks"]');
  await checksSettled(issuesAfterFix, "same Model Check count after loading");
  unlinkSync(savedPath);

  // =========================================================================================
  step("hygiene");
  expect(native.length === 0, `no window.prompt / confirm / alert: ${native.join(" | ")}`);
  expect(failed.length === 0, `no failed request: ${failed.join(", ")}`);
  const log = await page.textContent("#log");
  expect(!/\b(GET|POST|PATCH|DELETE) \/api\//.test(log) && !/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-/.test(log),
         "the Output log speaks of the model, not of HTTP requests or ids");
  expect(!(await page.$("#log .log-error")), `no errors logged: ${await page.$eval("#log .log-error", (e) => e.textContent).catch(() => "")}`);
}
