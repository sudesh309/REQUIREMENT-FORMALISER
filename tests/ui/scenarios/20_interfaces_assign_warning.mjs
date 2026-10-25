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
  const centre = async (sel) => { const b = await (await page.$(sel)).boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
  const idle = () => page.waitForFunction(() => !Number(document.body.dataset.ifcPending || 0));
  const logText = () => page.textContent("#log");
  const clearLog = async () => {
    await page.click('[data-cmd="clear-log"]');
    await page.evaluate(() => document.querySelectorAll(".arch-toast").forEach(t => t.remove()));
  };
  const warningLines = () => page.$$eval("#log .log-warning", (els) => els.map((e) => e.textContent));
  const conn = () => api("GET", `/api/arch/view/${root.id}`).then(v => v.connectors[0]);
  const CONNECTOR = "ADC.airData → FMS.air";

  // A port with the wrong interface is picked on the canvas and fixed in its Property Inspector.
  const dockAssign = async (comp, name, label) => {
    const p = await centre(`${portSel(comp, name)} .arch-port-hit`);
    await page.mouse.click(p.x, p.y);
    await page.waitForSelector('.arch-dock [data-dock="port-interface"]');
    await page.selectOption('.arch-dock [data-dock="port-interface"]', { label });
  };

  // 1. The port tooltip names the interface (SVG <title>).
  const tip = await page.$eval(`${portSel("FMS", "air")} title`, (e) => e.textContent);
  expect(tip.startsWith("air — in data port"), `port tooltip keeps the port facts: ${tip}`);
  expect(/\nInterface: AirDataWord$/.test(tip), `port tooltip names the interface: ${JSON.stringify(tip)}`);
  expect(!(await warningLines()).length, "compatible connector: nothing to warn about");
  expect(!(await page.$(".arch-conn.bad")), "compatible connector is drawn normally");

  // 2. PO-14 on the canvas: fixing the port is silent, breaking it again warns.
  await clearLog();
  await dockAssign("FMS", "air", "AirDataWord (DataInterface)");
  await page.waitForFunction(() => !document.querySelector(".arch-conn.bad"));
  expect(!(await warningLines()).length && !(await page.$(".arch-toast.warning")), "an assignment that fixes the connector does not warn");
  await dockAssign("FMS", "air", "InertialData (DataInterface)");
  await page.waitForSelector(".arch-toast.warning");
  expect((await page.textContent(".arch-toast.warning")).includes(CONNECTOR), "toast names the connector after the assignment");
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  expect((await warningLines())[0].includes("element 'altitude'"), "Output line gives the reason");
  await page.waitForSelector(".arch-conn.bad", { state: "attached" });
  // the assignment itself succeeded
  expect((await api("GET", `/api/interfaces/port/${fmsIn.id}`)).interface.name === "InertialData", "the port took the interface");

  // 4. PO-14 in the Properties tab: Interface dropdown of the port.
  await page.click('.tab[data-tab="properties"]');
  const treeRow = (id) => `#tree .tree-node[data-id="${id}"] > .row`;
  await page.click(treeRow(fmsIn.id));
  await page.waitForSelector('[data-ifc="port-interface"]');
  await idle();
  await clearLog();
  await page.selectOption('[data-ifc="port-interface"]', { label: "AirDataWord" });
  await idle();
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("now uses AirDataWord"));
  expect(!(await warningLines()).length, "compatible assignment: no warning in the Properties tab");
  await page.waitForSelector('[data-ifc="port-interface"]');
  await idle();
  await page.selectOption('[data-ifc="port-interface"]', { label: "InertialData" });
  await page.waitForFunction(() => document.querySelector("#log .log-warning"));
  const propLines = await warningLines();
  expect(propLines.length === 1 && propLines[0].includes(CONNECTOR) && propLines[0].includes("'altitude'"), `Properties tab warns: ${JSON.stringify(propLines)}`);
  await idle();

  // 5. PO-14 by drag and drop: an interface dropped on a port from the containment tree.
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
  expect(dropLines.length === 1 && dropLines[0].includes(CONNECTOR) && dropLines[0].includes("element 'pitch'"), `drop warns: ${JSON.stringify(dropLines)}`);
  await page.waitForSelector(".arch-toast.warning");
  await page.waitForSelector(".arch-conn.bad", { state: "attached" });
  await idle();

  // 6. Validate reports the same connector.
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("interfaces.compatibility"));
}
