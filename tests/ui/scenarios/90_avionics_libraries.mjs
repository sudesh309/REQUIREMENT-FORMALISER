// Avionics pack: start from a plain project, add the Avionics profile, import interfaces and
// requirement skeletons from the libraries, then replace the project with the blank avionics
// template (File > New from template…, with the unsaved-changes warning).
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, waitReady, expect, api, fresh }, step) {
  const native = [];
  page.on("dialog", (d) => { native.push(`${d.type()}: ${d.message()}`); d.dismiss().catch(() => {}); });
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await fresh("PlainProject");
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
  const banner = (v) => page.textContent(`[data-av-view="${v}"] [data-av-banner]`);

  // =========================================================================================
  step("start view and profile");
  // The ribbon entries are contextual: not shown in a project without the Avionics profile.
  expect(!(await page.isVisible('#ribbon [data-plugin-button="avionics"]')), "no Avionics ribbon entry yet");
  await tab("avionics");
  await page.waitForSelector('[data-av="status-profile"]');
  expect(/missing/.test(await page.textContent('[data-av="status-profile"]')), "the profile is missing");
  expect(await page.$$eval("[data-av-template]", (c) => c.map((x) => x.dataset.avTemplate).join()) === "blank,ima_example",
         "both templates are offered");
  expect(/No equipment with mass or power values/.test(await page.textContent("#tab-avionics")), "no equipment yet");
  await page.click('[data-av-act="profile"]');
  await undoIs("Add the Avionics profile");
  await until(() => document.querySelector('#ribbon [data-plugin-button="avionics"]')?.offsetParent !== null, null, "Avionics ribbon entry appears");
  await until(() => /present/.test(document.querySelector('[data-av="status-profile"]')?.textContent || ""), null, "profile present");
  expect(/16 of 16 stereotypes/.test(await page.textContent('[data-av="status-profile"]')), "all 16 stereotypes");
  // The Profile Editor lists the stereotypes with their units.
  await page.click('[data-av-act="profile-editor"]');
  await page.waitForSelector('.pf-row[data-kind="profile"]');
  expect((await page.textContent("#tab-profiles")).includes("Avionics"), "the Profile Editor shows the profile");

  // =========================================================================================
  step("interface library");
  await view("interfaces");
  await page.waitForSelector('[data-av="iface-table"]');
  expect(/typical values: verify every one against your programme's ICD/.test(await page.textContent('[data-av="icd-warning"]')),
         "the ICD warning is shown");
  expect(await page.$$eval("tr[data-av-iface]", (r) => r.length) === 37, "37 library items");
  const labels = await page.$eval('tr[data-av-iface="A429AirData"]', (r) => r.querySelector(".av-lbl").textContent);
  expect(labels.includes("203") && labels.includes("213"), `air data labels shown: ${labels}`);
  expect(await page.isDisabled('[data-av-act="import-selected"]'), "nothing selected: import disabled");
  await page.check('[data-av-pick="A429AirData"]');
  await page.check('[data-av-pick="A664Message"]');
  expect(/Import selected \(2\)/.test(await page.textContent('[data-av-act="import-selected"]')), "two selected");
  await page.fill('[data-av="iface-filter"]', "a429");
  await until(() => document.querySelectorAll("tr[data-av-iface]").length < 37, null, "filter narrows the list");
  expect(await page.$eval('[data-av-pick="A429AirData"]', (c) => c.checked), "the selection survives filtering");
  await page.fill('[data-av="iface-filter"]', "");
  await page.click('[data-av-act="import-selected"]');
  await until(() => /Imported \d+ items?/.test(document.querySelector('[data-av-view="interfaces"] [data-av-banner]')?.textContent || ""),
              null, "import banner");
  expect(/Imported 8 items/.test(await banner("interfaces")), `banner: ${await banner("interfaces")}`);
  await undoIs("Import A429AirData, A664Message (8 items)");
  expect(await page.$eval('tr[data-av-iface="A664Message"]', (r) => r.textContent.includes("in project")), "the item is in the project");
  expect(await page.$eval('[data-av-pick="A664Message"]', (c) => c.disabled), "imported items cannot be picked again");
  // The Interface Editor shows them.
  await page.click('#ribbon [data-plugin-button="interface-editor"]');
  await page.waitForSelector('.ifc-item:has-text("A664Message")');
  await view("interfaces");
  await page.click('[data-av-act="import-all"]');
  await until(() => document.querySelectorAll('tr[data-av-iface] .av-chip.ok').length === 37, null, "all 37 in the project");
  await undoIs("Import the avionics interface library (29 items)");
  expect((await api("GET", "/api/avionics/info")).interfaces.present === 37, "the server agrees");

  // =========================================================================================
  step("requirement library");
  await view("requirements");
  await page.waitForSelector('[data-av="req-sets"]');
  expect(await page.$$eval("[data-av-reqset]", (c) => c.length) === 4, "four skeleton sets");
  expect(await page.$$eval('[data-av="guidance"] tbody tr', (r) => r.length) === 5, "guidance rows A to E");
  expect(/MC\/DC/.test(await page.textContent('[data-av="guidance"]')), "guidance names the coverage");
  await page.check('[data-av-reqpick="do178c-hlr"]');
  await page.check('[data-av-reqpick="arp4754a-system"]');
  await page.selectOption('[data-av="req-dal"]', "B");
  await page.click('[data-av-act="req-import"]');
  await until(() => /Created .*SystemRequirements.*SoftwareHighLevelRequirements|Created .*SoftwareHighLevelRequirements.*SystemRequirements/
    .test(document.querySelector('[data-av-view="requirements"] [data-av-banner]')?.textContent || ""), null, "requirement import banner");
  await until(() => document.querySelector('button[data-plugin-button="undo"]')?.title.startsWith("Undo Import requirement sets "),
              null, "undo step names the sets");
  await until(() => document.querySelector('[data-av-reqset="arp4754a-system"]')?.textContent.includes("set in project"), null, "marked as present");
  await page.click('#ribbon [data-open-tab="requirements"]');
  await until(() => document.body.dataset.rqPending === "0", null, "requirements idle");
  const sets = await page.$$eval("#tab-requirements select option", (o) => o.map((x) => x.textContent));
  expect(sets.some((s) => s.includes("SystemRequirements")) && sets.some((s) => s.includes("SoftwareHighLevelRequirements")),
         `the Requirements editor lists the sets: ${sets.join(" | ")}`);
  const info = await api("GET", "/api/avionics/info");
  expect(info.requirement_sets.length === 2, "two sets in the project");

  // =========================================================================================
  step("new from template: blank");
  await page.click('header [data-avionics="new-template"]');
  await page.waitForSelector('#modal-root input[name="template"]');
  expect(await page.$("#modal-root [data-unsaved-warning]") !== null, "unsaved changes are warned about");
  expect(await page.inputValue('#modal-root input[name="name"]') === "AvionicsProject", "default name of the blank template");
  expect(/Discard changes and create/.test(await page.textContent("#modal-root [data-modal-submit]")), "the button says what happens");
  await page.click("#modal-root [data-modal-submit]");
  await until(() => document.querySelector("#project-name")?.textContent.startsWith("AvionicsProject"), null, "blank project created");
  await until(() => document.querySelector(".arch-frame-title")?.textContent.startsWith("SystemArchitecture"), null, "empty architecture open");
  await page.waitForSelector(".arch-empty:not([hidden]), .arch-frame-title");
  expect(await page.$$eval(".arch-block", (b) => b.length) === 0, "an empty system architecture");
  expect((await api("GET", "/api/undo/state")).can_undo === false, "a fresh history");
  await view("start");
  await until(() => /37 of 37/.test(document.querySelector('[data-av="status-interfaces"]')?.textContent || ""), null, "library imported");
  expect(/SystemRequirements/.test(await page.textContent('[data-av="status-requirements"]')) &&
         /SoftwareLowLevelRequirements/.test(await page.textContent('[data-av="status-requirements"]')), "requirement skeletons present");
  expect(/0 FHA row/.test(await page.textContent('[data-av="status-safety"]')), "empty FHA");
  await view("fha");
  await page.waitForSelector('[data-av="fha-empty"]');
  await view("safety");
  await page.waitForSelector('[data-av="safety-empty"]');
  const check = await api("GET", "/api/interop/check");
  expect(check.counts.error === 0, `Model Check: no errors in a blank avionics project (${JSON.stringify(check.counts)})`);

  // =========================================================================================
  step("hygiene");
  expect(native.length === 0, `no window.prompt / confirm / alert: ${native.join(" | ")}`);
  expect(failed.length === 0, `no failed request: ${failed.join(", ")}`);
}
