// Model Check in a System Composer style model (PO-6, SU-10): inline components, connectors
// and ports without an interface raise no 'feature.typed' noise, every message names its
// element, the open port of each reference usage is reported on that usage, and clicking an
// issue shows its element where it lives: the canvas composition (with the element selected)
// for components and ports, the Properties tab for everything else.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, api, fresh, waitReady, expect }, step) {
  await fresh("CheckNav");
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (composition, name, x, y, definition) =>
    api("POST", "/api/arch/component", { composition, name, layout: { x, y }, definition });
  const adc = await mk(root.id, "ADC", 120, 80), fms = await mk(root.id, "FMS", 520, 80);
  const filter = await mk(fms.id, "Filter", 200, 100);
  await api("POST", "/api/arch/port", { owner: adc.id, name: "airData", direction: "out" });
  const spare = await api("POST", "/api/arch/port", { owner: adc.id, name: "spare", direction: "out" });
  await api("POST", "/api/arch/port", { owner: fms.id, name: "air", direction: "in" });
  await api("POST", "/api/arch/connector", { composition: root.id, source: { component: adc.id, port: "airData" },
                                             target: { component: fms.id, port: "air" } });
  // A definition whose inside drives its output, used twice: each usage leaves it open.
  const fcc = await api("POST", "/api/element", { kind: "PartDefinition", name: "FlightControlComputer" });
  await api("POST", "/api/arch/port", { owner: fcc.id, name: "surfaceCmd", direction: "out" });
  const law = await mk(fcc.id, "ControlLaw", 100, 100);
  await api("POST", "/api/arch/port", { owner: law.id, name: "cmd", direction: "out" });
  await api("POST", "/api/arch/connector", { composition: fcc.id, source: { component: law.id, port: "cmd" },
                                             target: { port: "surfaceCmd" } });
  await mk(root.id, "FCC-L", 120, 320, fcc.id);
  const fccR = await mk(root.id, "FCC-R", 520, 320, fcc.id);
  const req = await api("POST", "/api/element", { kind: "RequirementDefinition", name: "REQ_001" });
  await waitReady();
  const block = (id) => `#tab-architecture .arch-block[data-id="${id}"]`;
  const row = (text) => `#tab-checks tr.io-issue:has-text("${text}")`;

  step("no feature.typed noise");
  await page.click('.tab[data-tab="checks"]');
  await page.waitForSelector("#tab-checks tr.io-issue");
  const check = await api("GET", "/api/interop/check");
  expect(!check.by_rule["feature.typed"], `no feature.typed issues: ${JSON.stringify(check.by_rule)}`);
  const rules = await page.$$eval('#tab-checks select[data-k="rule"] option', (os) => os.map((o) => o.value));
  expect(!rules.includes("feature.typed"), `rule filter has no feature.typed: ${rules}`);
  const texts = await page.$$eval("#tab-checks tr.io-issue", (trs) => trs.map((tr) => tr.textContent));
  expect(!texts.some((t) => t.includes("FeatureTyping")), "no 'has no FeatureTyping' message");
  // Validate (F5) lists the same core issues in the output, each naming its element.
  await page.keyboard.press("F5");
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("port.typed: Port 'spare' has no interface"));
  expect(!(await page.textContent("#log")).includes("FeatureTyping"), "Validate output has no FeatureTyping noise");

  step("reference usages are reported one by one");
  for (const u of ["FCC-L", "FCC-R"]) {
    expect(texts.some((t) => t.includes(`Port ${u}.surfaceCmd is not connected in Aircraft`)), `${u}.surfaceCmd reported`);
  }

  step("a reference usage opens on the canvas");
  await page.click(row("FCC-R.surfaceCmd"));
  await page.waitForFunction(() => window.studio.state.tab === "architecture");
  await page.waitForSelector(`${block(fccR.id)}.sel`);
  expect(await page.textContent(".arch-path b") === "Aircraft", "the Aircraft composition is open");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, fccR.id);

  step("a nested component opens its composition");
  await page.click('.tab[data-tab="checks"]');
  expect(await page.$eval(row("FCC-R.surfaceCmd"), (tr) => tr.classList.contains("sel")), "the clicked row stays marked");
  await page.click(row("Component 'Filter' has no documentation"));
  await page.waitForFunction(() => window.studio.state.tab === "architecture"
    && document.querySelector(".arch-path b")?.textContent === "FMS");
  await page.waitForSelector(`${block(filter.id)}.sel`);

  step("a port is selected on its component");
  await page.click('.tab[data-tab="checks"]');
  await page.click(row("Port ADC.spare is not connected"));
  await page.waitForFunction(() => window.studio.state.tab === "architecture"
    && document.querySelector(".arch-path b")?.textContent === "Aircraft");
  await page.waitForSelector(`#tab-architecture [data-kind="port"].sel[data-id="${spare.id}"]`);

  step("anything else opens Properties");
  await page.click('.tab[data-tab="checks"]');
  await page.click(row("Requirement 'REQ_001'"));
  await page.waitForFunction(() => window.studio.state.tab === "properties");
  await page.waitForFunction(() => document.querySelector("#props-qname")?.textContent === "CheckNav::REQ_001");
  expect(await page.isVisible("#tab-properties"), "Properties is shown");
  await page.waitForFunction((id) => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, req.id);
}
