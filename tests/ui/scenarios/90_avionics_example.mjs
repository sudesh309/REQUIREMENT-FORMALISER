// Avionics pack: open the complete IMA example from "New from template…", navigate the canvas
// down into the IMA cabinet, a core module and a partition, Arrange, check the model, then edit a
// DAL in the Properties tab and watch the avionics rules fire (Model Check, Safety check, the
// canvas) and go away again with Undo.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, waitReady, expect, api, errors }, step) {
  const native = [];
  page.on("dialog", (d) => { native.push(`${d.type()}: ${d.message()}`); d.dismiss().catch(() => {}); });
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await waitReady();

  const until = (fn, arg, what, timeout = 15000) => page.waitForFunction(fn, arg, { timeout })
    .catch(() => { throw new Error(`timed out: ${what}`); });
  const tab = async (id) => {
    await page.click(`#tab-bar .tab[data-tab="${id}"]`);
    await until((t) => !document.querySelector(`#tab-${t}`)?.classList.contains("hidden"), id, `${id} tab shown`);
  };
  const undoIs = (label) => until((l) => document.querySelector('button[data-plugin-button="undo"]')?.title === `Undo ${l} (Ctrl+Z)`,
                                  label, `undo step '${label}'`);
  const block = (n) => `.arch-block[data-name="${n}"]`;
  const frameIs = (name) => until((n) => document.querySelector(".arch-frame-title")?.textContent.replace(/^(«[^»]*»\s*)+/, "").startsWith(n),
                                  name, `${name} open on the canvas`);
  const blockNames = () => page.$$eval(".arch-block", (bs) => bs.map((b) => b.dataset.name).sort());
  const pills = (name) => page.$$eval(`${block(name)} .arch-pill text`, (ts) => ts.map((t) => t.textContent));
  const box = async (sel) => {
    for (let i = 0; i < 60; i++) {
      const h = await page.$(sel);
      const b = h && await h.boundingBox();
      if (b) return b;
      await page.waitForTimeout(50);
    }
    throw new Error(`not on screen: ${sel}`);
  };
  // Select a block (a click at the bottom of its body, away from the name and the ports) and
  // press Enter to open it; Alt+Up goes back.
  const open = async (name, frame) => {
    const b = await box(`${block(name)} .arch-body`);
    await page.mouse.click(b.x + b.width / 2, b.y + b.height - 8);
    await until((s) => document.querySelector(s)?.classList.contains("sel"), block(name), `${name} selected`);
    await page.keyboard.press("Enter");
    await frameIs(frame);
  };
  const up = async (frame) => { await page.keyboard.press("Alt+ArrowUp"); await frameIs(frame); };
  const checkBadge = () => page.$eval('.tab[data-tab="checks"] .io-tab-badge', (b) => ({ n: Number(b.textContent), cls: b.className }));
  const checksSettled = (n, what) => until((n) => {
    const b = document.querySelector('.tab[data-tab="checks"] .io-tab-badge');
    return b && Number(b.textContent) === n && !b.classList.contains("stale");
  }, n, what);

  // =========================================================================================
  step("new from template");
  await page.click('header [data-avionics="new-template"]');
  await page.waitForSelector('#modal-root input[name="template"]');
  expect(await page.$$eval('#modal-root input[name="template"]', (xs) => xs.map((x) => x.value).join()) === "blank,ima_example",
         "both templates are offered");
  await page.check('#modal-root input[value="ima_example"]');
  expect(await page.inputValue('#modal-root input[name="name"]') === "IMA_Avionics", "the name follows the template");
  await page.click("#modal-root [data-modal-submit]");
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("IMA_Avionics"), null, "project named");
  await frameIs("PhysicalArchitecture");
  expect(!(await page.$("#modal-root .modal")), "the dialog closed");
  await until(() => document.querySelectorAll(".arch-block").length === 24, null, "24 components drawn");
  expect((await blockNames()).includes("IMA_Cabinet"), "the cabinet is on the canvas");
  await until(() => document.querySelectorAll(".arch-conn").length === 73, null, "73 connectors drawn");
  expect((await api("GET", "/api/undo/state")).can_undo === false, "a new project starts without undo history");

  // =========================================================================================
  step("canvas");
  const fcc = await pills("FCC_L");
  expect(fcc.includes("SM") && fcc.includes("DAL A") && fcc.includes("3 req"), `FCC_L badges: ${fcc}`);
  expect((await pills("ADC1")).includes("DAL B"), "ADC1 shows the DAL of its definition");
  // Arrange: readable, no block covers another.
  // The example is saved arranged; Arrange (whatever it changes) must leave no block over another.
  await page.click('[data-canvas-act="arrange"]');
  await page.waitForTimeout(400);
  await until(() => document.querySelectorAll(".arch-block").length === 24, null, "24 blocks after Arrange");
  const boxes = await page.$$eval(".arch-block .arch-body", (bs) => bs.map((b) => {
    const r = b.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }));
  expect(boxes.length === 24, "24 blocks after Arrange");
  let overlaps = 0;
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const [a, b] = [boxes[i], boxes[j]];
    if (a[0] < b[2] - 1 && b[0] < a[2] - 1 && a[1] < b[3] - 1 && b[1] < a[3] - 1) overlaps++;
  }
  expect(overlaps === 0, `no overlapping blocks after Arrange (${overlaps})`);

  // Down into the IMA cabinet, a core processing module and a partition; back up.
  await open("IMA_Cabinet", "IMA_Cabinet");
  expect(JSON.stringify(await blockNames()) === JSON.stringify(["CPM1", "CPM2", "PSM"]), "the cabinet holds three modules");
  expect((await pills("CPM1")).includes("DAL B"), "the module shows its DAL");
  await open("CPM1", "CPM1");
  expect(JSON.stringify(await blockNames()) === JSON.stringify(["P_FMS", "P_FWS"]), "the module hosts two partitions");
  await open("P_FMS", "P_FMS");
  expect(JSON.stringify(await blockNames()) === JSON.stringify(["FMS_Nav", "FMS_Perf"]), "the partition hosts two software items");
  expect((await pills("FMS_Nav")).includes("DAL C"), "software item DAL");
  await up("CPM1");
  await up("IMA_Cabinet");
  await up("PhysicalArchitecture");
  await open("FCC_L", "FCC_L");
  expect(JSON.stringify(await blockNames()) === JSON.stringify(["CommandLane", "MonitorLane"]), "the FCC has a command and a monitor lane");
  await up("PhysicalArchitecture");

  // =========================================================================================
  step("model check");
  await page.click('#ribbon [data-open-tab="checks"]');
  await page.waitForSelector('.tab[data-tab="checks"] .io-tab-badge');
  const check = await api("GET", "/api/interop/check");
  expect(check.counts.error === 0, `no errors: ${JSON.stringify(check.counts)}`);
  await checksSettled(check.total, "Model Check ran");
  expect((await checkBadge()).n === check.total, "the badge counts the issues");
  const rules = await page.$$eval('#tab-checks select[data-k="rule"] option', (os) => os.map((o) => o.textContent));
  expect(rules.some((r) => r.includes("Requirement without verification")), `rule titles are listed: ${rules.join(" | ")}`);

  // =========================================================================================
  step("safety check panel");
  await page.click('#ribbon [data-plugin-button="avionics-safety"]');
  await until(() => !document.querySelector("#tab-avionics")?.classList.contains("hidden"), null, "Avionics tab shown");
  await page.waitForSelector('[data-av-view="safety"] [data-av="safety-table"]');
  const safety0 = await api("GET", "/api/avionics/safety");
  expect(safety0.counts.error === 0 && safety0.counts.warning === 6 && safety0.counts.info === 7, JSON.stringify(safety0.counts));
  expect(await page.$$eval('[data-av-view="safety"] tr[data-av-issue]', (r) => r.length) === safety0.total, "every issue is listed");
  expect(await page.$$eval('tr[data-av-issue][data-sev="error"]', (r) => r.length) === 0, "no error rows");

  // =========================================================================================
  step("edit a DAL");
  const undoBefore = await page.getAttribute('[data-canvas-act="undo"]', "title");
  await tab("properties");
  await page.click('#tree .tree-node > .row:has-text("FlightControlComputer")');
  const dalSel = '[data-section="stereotypes"] [data-path="Avionics.Computer.dal"]';
  await page.waitForSelector(dalSel);
  expect(await page.inputValue(dalSel) === "A", "the FCC definition is DAL A");
  await page.selectOption(dalSel, "C");
  await undoIs("Set Avionics.Computer.dal of FlightControlComputer");
  // Model Check follows (badge turns red), the Safety check lists the errors.
  await page.click('#ribbon [data-open-tab="checks"]');
  const after = await api("GET", "/api/avionics/safety");
  expect(after.counts.error >= 2, `rules fire: ${JSON.stringify(after.counts)}`);
  await checksSettled((await api("GET", "/api/interop/check")).total, "Model Check re-ran");
  expect((await checkBadge()).cls.includes("error"), "the Model Check badge is red");
  await page.click('#ribbon [data-plugin-button="avionics-safety"]');
  await page.waitForSelector('[data-av-view="safety"] tr[data-av-issue][data-sev="error"]');
  const errRules = await page.$$eval('tr[data-av-issue][data-sev="error"]', (rs) => [...new Set(rs.map((r) => r.dataset.rule))]);
  expect(errRules.includes("avionics.dal.allocation") && errRules.includes("avionics.dal.requirement"), `error rules: ${errRules}`);
  const row = await page.$eval('tr[data-av-issue][data-rule="avionics.dal.allocation"]', (r) => r.textContent);
  expect(/ComputeFlightControlLaws needs DAL A/.test(row) && /FCC_L \(DAL C\)/.test(row), `the issue names function and items: ${row.slice(0, 200)}`);
  // A link in the row shows the element on the canvas.
  await page.click('tr[data-av-issue][data-rule="avionics.dal.allocation"] [data-av-open]');
  await until(() => !document.querySelector("#tab-architecture")?.classList.contains("hidden"), null, "canvas shown");
  await frameIs("PhysicalArchitecture");
  await until((s) => document.querySelector(s)?.classList.contains("sel"), block("FCC_L"), "FCC_L selected on the canvas");
  expect((await pills("FCC_L")).includes("DAL C"), "the block shows the new DAL");
  // The Properties tab's Avionics safety section names the rules touching the element.
  await tab("properties");
  await page.waitForSelector('[data-section="avionics-safety"] .av-issue');
  const sect = await page.$eval('[data-section="avionics-safety"]', (s) => s.textContent);
  expect(sect.includes("Function allocated below its FHA DAL") && sect.includes("Development assurance level"), `inspector section: ${sect.slice(0, 160)}`);

  // =========================================================================================
  step("undo");
  await tab("architecture");
  await page.click('[data-canvas-act="undo"]');
  await until((t) => document.querySelector('[data-canvas-act="undo"]')?.title === t, undoBefore, "DAL edit undone");
  expect((await api("GET", "/api/avionics/safety")).counts.error === 0, "the rules are quiet again");
  await page.click('#ribbon [data-plugin-button="avionics-safety"]');
  await until(() => document.querySelectorAll('tr[data-av-issue][data-sev="error"]').length === 0 &&
                    document.querySelector('[data-av-view="safety"] [data-av-count="error"]')?.textContent === "0", null, "Safety check is clean again");

  // =========================================================================================
  step("hygiene");
  expect(native.length === 0, `no window.prompt / confirm / alert: ${native.join(" | ")}`);
  expect(failed.length === 0, `no failed request: ${failed.join(", ")}`);
  expect(errors.length === 0, `no browser errors: ${errors.join(" | ")}`);
  // Model Check reports its findings as error lines while the DAL is lowered; nothing else may.
  const logged = await page.$$eval("#log .log-error", (xs) => xs.map((e) => e.textContent.trim()).filter((t) => !/Model Check: \d+ error/.test(t)));
  expect(logged.length === 0, `no errors logged: ${logged.join(" | ")}`);
}
