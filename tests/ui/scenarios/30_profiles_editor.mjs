// Profile Editor details: abstract base stereotype + inheritance, styling, the Apply stereotypes
// dialog, value errors, rename propagation, export / delete / import of a profile file.
import { readFileSync } from "node:fs";

export default async function ({ page, fresh, waitReady, expect, api, errors }) {
  await fresh("ProfilesEditorUi");
  const arch = await api("POST", "/api/element", { kind: "PartDefinition", name: "Aircraft" });
  const fcc = await api("POST", "/api/element", { kind: "PartUsage", name: "FCC", parent: arch.id });
  const adc = await api("POST", "/api/element", { kind: "PartUsage", name: "ADC", parent: arch.id });
  const prof = await api("POST", "/api/profiles", { name: "Avionics", version: "1.0" });
  const eq = await api("POST", `/api/profiles/${prof.id}/stereotypes`, { name: "Equipment", applies_to: "Component" });
  await api("POST", `/api/stereotypes/${eq.id}/properties`, { name: "mass", type: "double", unit: "kg", default: 2, min: 0 });
  await waitReady();
  const until = (fn, arg) => page.waitForFunction(fn, arg, { timeout: 10000 });
  const msg = () => page.textContent('[data-pf="details"] [data-pf=msg]');

  // --- make Equipment abstract --------------------------------------------------------
  await page.click('[data-plugin-button="profile-editor"]');           // toolbar button opens the tab
  await page.click(`.pf-row[data-pf-id="${eq.id}"]`);
  await page.check("#pf-s-abstract");
  await until(() => document.querySelector(".pf-row.sel")?.classList.contains("abstract"));
  expect((await api("GET", `/api/stereotypes/${eq.id}`)).abstract === true, "Equipment saved abstract");

  // --- Sensor derives from Equipment ---------------------------------------------------
  await page.click('[data-pf-cmd="new-stereotype"]');
  await page.fill('#modal-form [name="name"]', "Sensor");
  await page.selectOption('#modal-form [name="applies_to"]', "");
  await page.selectOption('#modal-form [name="base"]', { label: "Avionics.Equipment" });
  await page.click("[data-modal-submit]");
  await until(() => document.querySelector(".pf-title")?.textContent.includes("Avionics.Sensor"));
  expect((await page.textContent("tr.pf-grouprow")).includes("Inherited from «Avionics.Equipment»"), "inherited group");
  expect((await page.textContent("tr.pf-inherited")).includes("mass"), "inherited mass row");
  const sensor = await api("GET", "/api/stereotypes/Avionics.Sensor");
  expect(sensor.effective_applies_to === "Component" && sensor.base === "Avionics.Equipment", "Sensor inherits applies-to");

  // --- style: fill colour and icon ---------------------------------------------------------
  await page.fill("#pf-s-fill", "#ffcc00");
  await until(() => document.querySelector('[data-pf="details"] [data-pf=msg]')?.textContent.includes("style updated"));
  await page.selectOption("#pf-s-icon", "sensor");
  await page.waitForSelector(".pf-preview svg");                       // re-rendered after the save
  const style = (await api("GET", `/api/stereotypes/${sensor.id}`)).style;
  expect(style.fill === "#ffcc00" && style.icon === "sensor", `style saved ${JSON.stringify(style)}`);

  // --- Apply stereotypes dialog: whole model, components only ----------------------------
  await page.click('[data-plugin-button="batch-apply-stereotype"]');
  await page.waitForSelector('#modal-form [name="stereotype"]');
  const names = await page.$$eval('#modal-form [name="stereotype"] option', os => os.map(o => o.textContent));
  expect(!names.some(n => n.includes("Equipment")), "abstract stereotypes are not offered");
  await page.selectOption('#modal-form [name="stereotype"]', sensor.id);
  await page.check('#modal-form input[name="scope"][value="model"]');
  await page.click("[data-modal-submit]");
  await until(() => document.querySelector("#log")?.textContent.includes("Applied «Avionics.Sensor» to 3 element(s)"));
  const badge = `#tree .tree-node[data-id="${adc.id}"] > .row > .tree-badge.pf-badge`;
  await page.waitForSelector(badge);
  expect(await page.$eval(badge, b => getComputedStyle(b).backgroundColor) === "rgb(255, 204, 0)", "badge uses the fill colour");
  expect(await page.$(`${badge} svg`) !== null, "badge shows the icon");

  // --- inspector: inherited group, invalid value rejected, Escape restores -------------------
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${adc.id}"] > .row`);
  await page.waitForSelector('[data-path="Avionics.Sensor.mass"]');
  expect((await page.textContent(".pf-props")).includes("Avionics.Equipment"), "grouped by owning stereotype");
  await page.fill('[data-path="Avionics.Sensor.mass"]', "5 W");
  await page.press('[data-path="Avionics.Sensor.mass"]', "Enter");
  await until(() => document.querySelector('[data-path="Avionics.Sensor.mass"]')?.classList.contains("pf-invalid"));
  expect((await page.textContent('[data-section="stereotypes"] [data-pf=msg]')).includes("cannot convert W"), "unit error shown");
  errors.splice(0);                                                    // the expected 400 response
  await page.press('[data-path="Avionics.Sensor.mass"]', "Escape");
  expect(await page.$eval('[data-path="Avionics.Sensor.mass"]', el => el.value) === "2", "Escape restores the value");
  await page.fill('[data-path="Avionics.Sensor.mass"]', "2*1.25");
  await page.press('[data-path="Avionics.Sensor.mass"]', "Enter");
  await until(() => document.querySelector('[data-path="Avionics.Sensor.mass"]')?.value === "2.5");

  // --- rename the base property: the stored value follows -----------------------------
  await page.click('.tab[data-tab="profiles"]');
  await page.click(`.pf-row[data-pf-id="${eq.id}"]`);
  await page.fill('tr[data-prop-id] [data-col="name"]', "weight");
  await page.press('tr[data-prop-id] [data-col="name"]', "Enter");
  await until(() => document.querySelector('tr[data-prop-id] [data-col="name"]')?.getAttribute("value") === "weight");
  const vals = (await api("GET", `/api/elements/${adc.id}/stereotypes`)).applied[0].values;
  expect(vals.weight === 2.5 && !("mass" in vals), `value follows the rename ${JSON.stringify(vals)}`);

  // --- export the profile file ----------------------------------------------------------
  await page.click('.pf-row[data-kind="profile"]');
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('[data-pf-cmd="export"]')]);
  expect(download.suggestedFilename() === "Avionics.profile.json", "export file name");
  const text = readFileSync(await download.path(), "utf-8");
  const file = JSON.parse(text);
  expect(file.format === "sysmlv2-profile/1" && file.profile.stereotypes.length === 2, "exported profile file");

  // --- delete Sensor: applications disappear --------------------------------------------
  await page.click(`.pf-row[data-pf-id="${sensor.id}"]`);
  await page.click('[data-pf-cmd="delete"]');
  await page.waitForSelector("#modal-form");
  expect((await page.textContent("#modal-form")).includes("applied to 3 element(s)"), "delete warns about applications");
  await page.click("[data-modal-submit]");
  await until(() => !document.querySelector(".pf-row.st:not(.abstract)"));
  await page.waitForSelector(badge, { state: "detached" });

  // --- import the file back (same name: confirm replace) ---------------------------------
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click('[data-pf-cmd="import"]')]);
  await chooser.setFiles({ name: "Avionics.profile.json", mimeType: "application/json", buffer: Buffer.from(text) });
  await page.waitForSelector("#modal-form");
  expect((await page.textContent("#modal-form")).includes("already has profile"), "replace confirmation");
  await page.click("[data-modal-submit]");
  await until(() => [...document.querySelectorAll(".pf-row.st")].some(r => r.textContent.includes("Sensor")));
  await page.click('[data-pf-cmd="manage"]');
  await page.waitForSelector('[data-pf="import-log"]');
  expect((await page.textContent('[data-pf="import-log"]')).includes("Avionics.profile.json"), "import history lists the file");
  expect((await api("GET", "/api/stereotypes/Avionics.Sensor")).style.fill === "#ffcc00", "imported style");
  expect(!(await msg() || "").includes("error"), "no error shown");

  // --- making an applied stereotype abstract asks before removing its applications ----------
  const sensor2 = await api("GET", "/api/stereotypes/Avionics.Sensor");
  await api("POST", `/api/elements/${adc.id}/stereotypes`, { stereotype: sensor2.id });
  await page.click('.tab[data-tab="properties"]');
  await page.click('.tab[data-tab="profiles"]');                      // showing the tab reloads it
  await page.click(`.pf-row[data-pf-id="${sensor2.id}"]`);
  await page.check("#pf-s-abstract");
  await page.waitForSelector("#modal-form");
  expect((await page.textContent("#modal-form")).includes("applied to 1 element(s)"), "abstract change is confirmed");
  await page.click("[data-modal-submit]");
  await until(() => document.querySelector(".pf-row.sel")?.classList.contains("abstract"));
  expect((await api("GET", `/api/elements/${adc.id}/stereotypes`)).applied.length === 0, "application removed");
}
