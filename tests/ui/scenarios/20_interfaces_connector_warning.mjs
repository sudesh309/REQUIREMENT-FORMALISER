// SU-9: drawing a connector on the canvas between ports whose interfaces are incompatible.
// System Composer allows it, so the connector is created, but at once a toast and an Output line
// name the connector and the reason, and the connector is drawn with a warning style (red,
// dashed, thicker, a warning sign on its label, the reasons as its tooltip).
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("IfcConnectorWarning");
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const adc = await mk("ADC", 140, 80), fms = await mk("FMS", 460, 80);
  const adcOut = await api("POST", "/api/arch/port", { owner: adc.id, name: "airData", direction: "out" });
  const fmsIn = await api("POST", "/api/arch/port", { owner: fms.id, name: "air", direction: "in" });
  const word = await api("POST", "/api/interfaces", { kind: "DataInterface", name: "AirDataWord", color: "#0891b2",
                                                      elements: [{ name: "altitude", type: "double" }] });
  const inertial = await api("POST", "/api/interfaces", { kind: "DataInterface", name: "InertialData", color: "#ea580c",
                                                          elements: [{ name: "pitch", type: "double" }] });
  await api("POST", "/api/interfaces/assign", { port: adcOut.id, interface: word.id });
  await api("POST", "/api/interfaces/assign", { port: fmsIn.id, interface: inertial.id });
  await waitReady();
  await page.waitForSelector('.arch-block[data-name="FMS"]');

  const portSel = (comp, name) => `.arch-block[data-name="${comp}"] .arch-port[data-name="${name}"]`;
  const centre = async (sel) => { const b = await (await page.$(sel)).boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
  const drag = async (from, to) => {
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move((from.x + to.x) / 2, from.y, { steps: 6 });
    await page.mouse.move(to.x, to.y, { steps: 6 });
    await page.mouse.up();
  };

  // Draw the connector: ADC.airData (AirDataWord) -> FMS.air (InertialData).
  expect((await api("GET", `/api/arch/view/${root.id}`)).connectors.length === 0, "no connector yet");
  await drag(await centre(`${portSel("ADC", "airData")} .arch-port-hit`), await centre(`${portSel("FMS", "air")} .arch-port-hit`));
  const toast = await page.waitForSelector(".arch-toast.warning");
  const toastText = await toast.textContent();
  expect(toastText.includes("ADC.airData → FMS.air"), `toast names the connector: ${toastText}`);
  expect(toastText.includes("element 'altitude' is in 'AirDataWord' but not in 'InertialData'"), `toast gives the reason: ${toastText}`);
  await page.waitForFunction(() => document.querySelector("#log .log-warning")?.textContent.includes("Incompatible interfaces"));
  const lines = await page.$$eval("#log .log-warning", (els) => els.map((e) => e.textContent));
  expect(lines.length === 1 && lines[0].includes("ADC.airData → FMS.air") && lines[0].includes("element 'altitude'"),
         `Output line: ${JSON.stringify(lines)}`);
  expect((await page.textContent("#log")).includes("(see the warning above)"), "the Connected line points to the warning");

  // The connector exists and is drawn with a warning style.
  const view = await api("GET", `/api/arch/view/${root.id}`);
  expect(view.connectors.length === 1 && view.connectors[0].issues.length === 1, "the connector was created with the finding");
  const id = view.connectors[0].id;
  const line = `.arch-conn[data-id="${id}"]`;
  await page.waitForSelector(`${line}.bad`, { state: "attached" });
  expect(await page.$eval(`${line} .arch-conn-line`, (e) => e.getAttribute("stroke")) === "#dc2626", "red line");
  expect(await page.$eval(`${line} .arch-conn-line`, (e) => getComputedStyle(e).strokeDasharray !== "none"), "dashed line");
  expect(await page.$eval(`${line} .arch-conn-line`, (e) => parseFloat(getComputedStyle(e).strokeWidth)) > 2, "thicker than a normal line");
  const label = await page.textContent(`.arch-clabel[data-id="${id}"]`);
  expect(label.trim().startsWith("⚠") && label.includes("AirDataWord"), `warning sign on the label: ${label}`);
  const tip = await page.$eval(`${line} title`, (e) => e.textContent);
  expect(tip.includes("Incompatible interfaces AirDataWord → InertialData"), `connector tooltip: ${tip}`);
  // ... and the Property Inspector lists the problem.
  await page.waitForFunction(() => document.querySelector(".arch-dock")?.textContent.includes("Problems"));
  expect((await page.textContent(".arch-dock")).includes("Incompatible interfaces"), "the dock lists the problem");

  // Validate reports it too.
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("interfaces.compatibility"));

  // Once both ports use the same interface the connector is drawn normally again.
  await api("POST", "/api/interfaces/assign", { port: fmsIn.id, interface: word.id });
  await page.evaluate(() => studio.refreshTree());
  await page.waitForFunction(() => !document.querySelector(".arch-conn.bad"));
  expect(!(await page.textContent(`.arch-clabel[data-id="${id}"]`)).includes("⚠"), "no warning sign on a compatible connector");
}
