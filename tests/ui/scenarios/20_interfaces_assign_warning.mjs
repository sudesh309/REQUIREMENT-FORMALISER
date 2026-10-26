// PO-14: assigning an interface to a port that makes an existing connector incompatible succeeds
// and warns at once (an Output line, and a toast on the canvas) naming the connector and the
// reason, from the canvas Property Inspector, the Properties tab and a drag and drop;
// assignments that keep the connector compatible are silent. The canvas port tooltip names the
// port's interface.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("IfcAssignWarning");
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
  await api("POST", "/api/interfaces/assign", { port: fmsIn.id, interface: word.id });
  await api("POST", "/api/arch/connector", { composition: root.id, source: { component: adc.id, port: adcOut.id },
                                             target: { component: fms.id, port: fmsIn.id } });
  await waitReady();
  await page.waitForSelector('.arch-block[data-name="FMS"]');

  const portSel = (comp, name) => `.arch-block[data-name="${comp}"] .arch-port[data-name="${name}"]`;
  const centre = async (sel) => {                 // the canvas redraws: look the element up again each time
    for (let i = 0; i < 30; i++) {
      const b = await page.locator(sel).first().boundingBox();
      if (b) return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
      await page.waitForTimeout(100);
    }
    throw new Error(`${sel} is not on screen`);
  };
  const idle = () => page.waitForFunction(() => !Number(document.body.dataset.ifcPending || 0));
  const clearLog = async () => {
    await page.click('[data-cmd="clear-log"]');
    await page.evaluate(() => document.querySelectorAll(".arch-toast").forEach(t => t.remove()));
  };
  const warningLines = () => page.$$eval("#log .log-warning", (els) => els.map((e) => e.textContent));
  const CONNECTOR = "ADC.airData → FMS.air";

  // A port is picked on the canvas and its interface changed in the Property Inspector.
  const dockAssign = async (comp, name, label) => {
    const p = await centre(`${portSel(comp, name)} .arch-port-hit`);
    await page.mouse.click(p.x, p.y);
    await page.waitForSelector('.arch-dock [data-dock="port-interface"]');
    await page.selectOption('.arch-dock [data-dock="port-interface"]', { label });
  };

  // 1. The port tooltip names the interface (SVG <title>); the connector is fine so far.
  const tip = await page.$eval(`${portSel("FMS", "air")} title`, (e) => e.textContent);
  expect(tip.startsWith("air — in data port"), `port tooltip keeps the port facts: ${tip}`);
  expect(/\nInterface: AirDataWord$/.test(tip), `port tooltip names the interface: ${JSON.stringify(tip)}`);
  expect(!(await warningLines()).length, "compatible connector: nothing to warn about");
  expect(!(await page.$(".arch-conn.bad")), "compatible connector is drawn normally");

  // 2. Canvas Property Inspector: breaking the connector warns, fixing it is silent.
  await clearLog();
  await dockAssign("FMS", "air", "InertialData (DataInterface)");
  const toast = await page.waitForSelector(".arch-toast.warning");
  const toastText = await toast.textContent();
  expect(toastText.includes(CONNECTOR), `toast names the connector after the assignment: ${toastText}`);
  expect(toastText.includes("element 'altitude' is in 'AirDataWord' but not in 'InertialData'"), `toast gives the reason: ${toastText}`);
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  const canvasLines = await warningLines();
  expect(canvasLines.length === 1 && canvasLines[0].includes(CONNECTOR) && canvasLines[0].includes("element 'altitude'"),
         `Output line names the connector and the reason: ${JSON.stringify(canvasLines)}`);
  await page.waitForSelector(".arch-conn.bad", { state: "attached" });
  expect((await api("GET", `/api/interfaces/port/${fmsIn.id}`)).interface.name === "InertialData", "the assignment itself succeeded");
  await page.waitForFunction((sel) => /\nInterface: InertialData$/.test(document.querySelector(sel)?.textContent || ""),
                             `${portSel("FMS", "air")} title`);
  await clearLog();
  await dockAssign("FMS", "air", "AirDataWord (DataInterface)");
  await page.waitForFunction(() => !document.querySelector(".arch-conn.bad"));
  expect(!(await warningLines()).length && !(await page.$(".arch-toast.warning")), "an assignment that fixes the connector does not warn");

  // 3. Properties tab: the port's Interface dropdown (no canvas there: an Output line).
  await page.click('.tab[data-tab="properties"]');
  const treeRow = (id) => `#tree .tree-node[data-id="${id}"] > .row`;
  await page.click(treeRow(fmsIn.id));
  await page.waitForSelector('[data-ifc="port-interface"]');
  await idle();
  await clearLog();
  await page.selectOption('[data-ifc="port-interface"]', { label: "InertialData" });
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  const propLines = await warningLines();
  expect(propLines.length === 1 && propLines[0].includes(CONNECTOR) && propLines[0].includes("'altitude'"),
         `Properties tab warns: ${JSON.stringify(propLines)}`);
  await idle();
  await clearLog();
  await page.selectOption('[data-ifc="port-interface"]', { label: "AirDataWord" });
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("now uses AirDataWord"));
  expect(!(await warningLines()).length, "compatible assignment: no warning in the Properties tab");
  await idle();
  await page.selectOption('[data-ifc="port-interface"]', { label: "InertialData" });     // incompatible again
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  await idle();

  // 4. Drag and drop: an interface dragged from the containment tree onto a canvas port.
  await page.click('.tab[data-tab="architecture"]');
  await page.waitForSelector(".arch-conn.bad", { state: "attached" });
  await clearLog();
  await page.dragAndDrop(treeRow(inertial.id), portSel("ADC", "airData"));          // both ends InertialData now
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("now uses interface InertialData"));
  await idle();
  await page.waitForFunction(() => !document.querySelector(".arch-conn.bad"));
  expect(!(await warningLines()).length, "dropping the matching interface does not warn");
  await page.dragAndDrop(treeRow(word.id), portSel("FMS", "air"));
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  const dropLines = await warningLines();
  expect(dropLines.length === 1 && dropLines[0].includes(CONNECTOR) && dropLines[0].includes("element 'pitch'"),
         `drop warns: ${JSON.stringify(dropLines)}`);
  await page.waitForSelector(".arch-toast.warning");
  await page.waitForSelector(".arch-conn.bad", { state: "attached" });
  await idle();

  // 5. Validate reports the same connector.
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("interfaces.compatibility"));
}
