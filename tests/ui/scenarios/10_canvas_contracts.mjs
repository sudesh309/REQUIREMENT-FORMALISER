// Cross-feature contracts of the canvas (docs/EXTENDING.md): highlight, canvas-filter,
// navigate, selection-changed / getSelection, the canvas following the model browser,
// HTML5 drops (drop-on-element; a part definition dragged from the tree becomes a
// reference component; an interface dragged from the Interface Editor, through the
// spring-loaded Architecture tab, or from the tree onto a port is assigned to it), plus
// zoom/fit, keyboard drill-down / rename and the software model's port kinds.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, fresh, waitReady, expect, api }, step) {
  await fresh("CanvasContracts");
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (composition, name, x, y) => api("POST", "/api/arch/component", { composition, name, layout: { x, y } });
  const adc = await mk(root.id, "ADC", 140, 80), fms = await mk(root.id, "FMS", 420, 80), disp = await mk(root.id, "Display", 700, 80);
  const filter = await mk(fms.id, "Filter", 200, 100);
  const adcOut = await api("POST", "/api/arch/port", { owner: adc.id, name: "airData", direction: "out" });
  const fmsIn = await api("POST", "/api/arch/port", { owner: fms.id, name: "air", direction: "in" });
  const conn = await api("POST", "/api/arch/connector", { composition: root.id, source: { component: adc.id, port: "airData" }, target: { component: fms.id, port: "air" } });
  const req = await api("POST", "/api/element", { kind: "RequirementDefinition", name: "REQ_001" });
  const unit = await api("POST", "/api/element", { kind: "PartDefinition", name: "AdcUnit" });
  const IF_COLOR = "#0891b2";
  const airDataIf = await api("POST", "/api/interfaces", { kind: "DataInterface", name: "AirData", color: IF_COLOR });
  await waitReady();
  await page.waitForSelector('.arch-block[data-name="Display"]');
  await page.evaluate(() => {
    window.__events = { filter: [], drop: [] };
    studio.on("canvas-filter", p => window.__events.filter.push(p));
    studio.on("drop-on-element", p => window.__events.drop.push(p));
  });
  const block = n => `.arch-block[data-name="${n}"]`;
  const crumb = () => page.$eval(".arch-path b", e => e.textContent);

  step("highlight");
  await page.evaluate(ids => studio.emit("highlight", { ids, color: "#dc2626", reason: "Trace REQ_001" }), [adc.id, conn.id]);
  await page.waitForSelector(`${block("ADC")}.hl`);
  expect(await page.$eval(`.arch-conn[data-id="${conn.id}"]`, e => e.classList.contains("hl")), "connector glows");
  expect(!(await page.$eval(block("FMS"), e => e.classList.contains("hl"))), "others do not");
  expect((await page.textContent('.arch-banner[data-banner="highlight"]')).includes("Trace REQ_001"), "highlight banner");
  await page.click('[data-banner-clear="highlight"]');
  await page.waitForFunction(() => !document.querySelector(".arch-block.hl"));

  step("canvas-filter");
  await page.evaluate(ids => studio.emit("canvas-filter", { ids, label: "Air data view" }), [adc.id, fms.id]);
  await page.waitForSelector(`${block("Display")}.f-dim`);
  expect(!(await page.$eval(block("ADC"), e => e.classList.contains("f-dim"))), "kept components stay");
  expect((await page.textContent('.arch-banner[data-banner="filter"]')).includes("2 of 3"), "filter banner");
  await page.check("[data-banner-hide]");
  await page.waitForSelector(`${block("Display")}.f-hidden`, { state: "attached" });
  expect(await page.$eval(block("Display"), e => getComputedStyle(e).display) === "none", "hidden, not just dimmed");
  await page.click('[data-banner-clear="filter"]');
  await page.waitForFunction(() => !document.querySelector(".arch-block.f-dim, .arch-block.f-hidden"));
  expect(await page.evaluate(() => window.__events.filter.at(-1) === null), "clearing emits canvas-filter null");

  step("navigate");
  await page.evaluate(id => studio.emit("navigate", { id }), filter.id);
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "FMS");
  await page.waitForSelector(`${block("Filter")}.sel`);
  await page.waitForFunction(id => document.querySelector("#tree .tree-node.selected")?.dataset.id === id, filter.id);

  step("canvas follows the model browser");
  await page.click(`#tree .tree-node[data-id="${disp.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "Aircraft");
  await page.waitForSelector(`${block("Display")}.sel`);

  step("selection sync");
  await page.evaluate(ids => studio.setSelection(ids), [adc.id, disp.id]);
  await page.waitForFunction(() => document.querySelectorAll(".arch-block.sel").length === 2);
  const adcBody = await (await page.$(`${block("ADC")} .arch-body`)).boundingBox();
  await page.mouse.click(adcBody.x + 12, adcBody.y + 10);
  await page.waitForFunction(id => JSON.stringify(studio.getSelection()) === JSON.stringify([id]), adc.id);
  const fmsBody = await (await page.$(`${block("FMS")} .arch-body`)).boundingBox();
  await page.keyboard.down("Shift");
  await page.mouse.click(fmsBody.x + 12, fmsBody.y + 10);
  await page.keyboard.up("Shift");
  await page.waitForFunction(() => studio.getSelection().length === 2);
  expect((await page.textContent(".arch-dock")).includes("2 items selected"), "dock shows the multi-selection");

  step("drop on element");
  await page.evaluate(({ id }) => {
    const el = document.querySelector('.arch-block[data-name="FMS"] .arch-body');
    const r = el.getBoundingClientRect();
    const dt = new DataTransfer();
    dt.setData("application/x-sysml-element", id);
    const o = { dataTransfer: dt, bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + 20 };
    el.dispatchEvent(new DragEvent("dragover", o));
    el.dispatchEvent(new DragEvent("drop", o));
  }, { id: req.id });
  const drop = await page.evaluate(() => window.__events.drop[0]);
  expect(drop?.dragged_id === req.id && drop?.target_id === fms.id, `drop-on-element: ${JSON.stringify(drop)}`);
  // the requirements feature links them and refreshes the tree: let it finish before the
  // next step drags a tree row (a row replaced mid-drag never drops)
  await page.waitForFunction(() => document.body.dataset.rqPending === "0");

  step("drag a definition from the tree");
  const host = await (await page.$(".arch-host")).boundingBox();
  await page.dragAndDrop(`#tree .tree-node[data-id="${unit.id}"] > .row`, ".arch-host",
                         { targetPosition: { x: host.width / 2, y: host.height - 120 } });
  await page.waitForSelector(`${block("AdcUnit")} .arch-refmark`);
  expect((await page.textContent(`${block("AdcUnit")} .arch-def`)) === "AdcUnit", "reference component shows its definition");

  step("Interface Editor rows carry the drag data");
  await page.click('.tab[data-tab="interfaces"]');
  const ifcRow = `.ifc-item[data-id="${airDataIf.id}"][draggable="true"]`;
  await page.waitForSelector(ifcRow);
  const dragData = await page.$eval(ifcRow, (el) => {
    const dt = new DataTransfer();
    el.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true, cancelable: true }));
    return { id: dt.getData("application/x-sysml-element"), text: dt.getData("text/plain") };
  });
  expect(dragData.id === airDataIf.id && dragData.text.endsWith("::AirData"), `drag data: ${JSON.stringify(dragData)}`);

  step("drag an interface from the Interface Editor onto a port");
  // A real HTML5 drag: hold over the Architecture tab (spring-loaded) to switch to the canvas,
  // then release on the port. The tab opens after a short hold, so wait for it before moving on.
  const portSel = (comp, name) => `${block(comp)} .arch-port[data-name="${name}"]`;
  const centre = async (sel) => { const b = await (await page.$(sel)).boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
  const src = await centre(ifcRow);
  await page.mouse.move(src.x, src.y);
  await page.mouse.down();
  await page.mouse.move(src.x + 20, src.y + 4, { steps: 4 });
  const tab = await centre('.tab[data-tab="architecture"]');
  await page.mouse.move(tab.x, tab.y, { steps: 6 });
  await page.waitForFunction(() => document.querySelector(".tab.tab-active")?.dataset.tab === "architecture");
  const adcPort = await centre(`${portSel("ADC", "airData")} .arch-port-hit`);
  await page.mouse.move(adcPort.x, adcPort.y, { steps: 8 });
  await page.mouse.up();
  await page.waitForFunction(id => document.querySelector(`.arch-clabel[data-id="${id}"]`)?.textContent.includes("AirData"), conn.id);
  await page.waitForFunction(([sel, color]) => document.querySelector(`${sel} .arch-port-glyph`)?.getAttribute("stroke") === color,
                             [portSel("ADC", "airData"), IF_COLOR]);
  const dropped = await page.evaluate(() => window.__events.drop.at(-1));
  expect(dropped?.dragged_id === airDataIf.id && dropped?.target_id === adcOut.id, `drop-on-element: ${JSON.stringify(dropped)}`);
  const typed = (await api("GET", `/api/arch/view/${root.id}`)).components.find(c => c.name === "ADC").ports[0];
  expect(typed.interface?.name === "AirData", `port typed by the dropped interface: ${JSON.stringify(typed.interface)}`);
  // the dropped-on port is selected and the Property Inspector shows its interface
  await page.waitForFunction(() => document.querySelector('.arch-dock [data-dock="port-interface"]')?.selectedOptions[0]?.textContent.startsWith("AirData"));
  expect((await page.textContent("#log")).includes("Port airData now uses interface AirData"), "assignment logged");
  await page.waitForFunction(() => document.body.dataset.ifcPending === "0");

  step("drop an interface from the tree on a port");
  await page.dragAndDrop(`#tree .tree-node[data-id="${airDataIf.id}"] > .row`, portSel("FMS", "air"));
  await page.waitForFunction(([sel, color]) => document.querySelector(`${sel} .arch-port-glyph`)?.getAttribute("stroke") === color,
                             [portSel("FMS", "air"), IF_COLOR]);
  await page.waitForFunction(() => document.body.dataset.ifcPending === "0");
  const fmsTyped = (await api("GET", `/api/interfaces/port/${fmsIn.id}`)).interface;
  expect(fmsTyped?.id === airDataIf.id, `FMS.air typed by AirData: ${JSON.stringify(fmsTyped)}`);
  // both ends use AirData: the connector is compatible and drawn in the interface colour
  await page.waitForFunction(([id, color]) => document.querySelector(`.arch-conn[data-id="${id}"] .arch-conn-line`)?.getAttribute("stroke") === color,
                             [conn.id, IF_COLOR]);

  step("an interface dropped on a block is not assigned");
  await page.evaluate(({ id }) => {
    const el = document.querySelector('.arch-block[data-name="Display"] .arch-body');
    const r = el.getBoundingClientRect();
    const dt = new DataTransfer();
    dt.setData("application/x-sysml-element", id);
    const o = { dataTransfer: dt, bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + 20 };
    el.dispatchEvent(new DragEvent("dragover", o));
    el.dispatchEvent(new DragEvent("drop", o));
  }, { id: airDataIf.id });
  await page.waitForFunction(() => document.querySelector("#log").textContent.includes("Drop AirData on a port"));

  step("keyboard: drill down, up, rename");
  await page.mouse.click(fmsBody.x + 12, fmsBody.y + 10);
  await page.waitForSelector(`${block("FMS")}.sel`);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "FMS");
  await page.keyboard.press("Alt+ArrowUp");
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "Aircraft");
  await page.waitForSelector(block("Display"));
  const dispBody = await (await page.$(`${block("Display")} .arch-body`)).boundingBox();
  await page.mouse.click(dispBody.x + 12, dispBody.y + 10);
  await page.keyboard.press("F2");
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  await page.fill(".arch-inline-edit", "PFD");
  await page.press(".arch-inline-edit", "Enter");
  await page.waitForSelector(block("PFD"));
  // a taken name is refused on the client with a clear message (no request is sent)
  await page.keyboard.press("F2");
  await page.fill(".arch-inline-edit", "ADC");
  await page.press(".arch-inline-edit", "Enter");
  expect((await (await page.waitForSelector(".arch-toast.error")).textContent()).includes("already has a member named 'ADC'"), "duplicate name refused");
  expect(await crumb() === "Aircraft", "still in the architecture");

  step("zoom and fit");
  const zoomText = () => page.textContent('[data-canvas-act="zoom-reset"]');
  const z0 = await zoomText();
  await page.click('[data-canvas-act="zoom-in"]');
  await page.waitForFunction(z => document.querySelector('[data-canvas-act="zoom-reset"]').textContent !== z, z0);
  await page.mouse.move(host.x + host.width / 2, host.y + host.height / 2);
  const z1 = await zoomText();
  await page.mouse.wheel(0, 400);
  await page.waitForFunction(z => document.querySelector('[data-canvas-act="zoom-reset"]').textContent !== z, z1);
  expect(parseInt(await zoomText(), 10) < parseInt(z1, 10), "wheel down zooms out");
  await page.click('[data-canvas-act="zoom-reset"]');
  await page.waitForFunction(() => document.querySelector('[data-canvas-act="zoom-reset"]').textContent === "100%");
  await page.click('[data-canvas-act="fit"]');
  const frame = await (await page.$(".arch-frame-box")).boundingBox();
  const svg = await (await page.$(".arch-svg")).boundingBox();
  expect(frame.x >= svg.x && frame.x + frame.width <= svg.x + svg.width + 1 && frame.y >= svg.y, "fit shows the whole frame");

  step("software model");
  await page.click('button[data-plugin-button="model-type"]');
  await page.selectOption("#modal-root select[name=type]", "software");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForFunction(() => !document.querySelector('[data-canvas-act="add-port-client"]').hidden
    && document.querySelector('[data-canvas-act="add-port-physical"]').hidden);
  await page.mouse.click(dispBody.x + 12, dispBody.y + 10);
  await page.click('[data-canvas-act="add-port-client"]');
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  await page.press(".arch-inline-edit", "Escape");
  await page.waitForSelector(`${block("PFD")} .arch-port.k-client`);

  step("elements the canvas does not draw");
  await page.click(`#tree .tree-node[data-id="${req.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector(".arch-dock")?.textContent.includes("not drawn on this canvas"));
  expect((await page.textContent(".arch-dock")).includes("REQ_001"), "dock shows the tree selection");
  expect(!(await page.$(".arch-block.sel")), "canvas selection cleared");
  await page.click('.arch-dock [data-dock-act="properties"]');
  await page.waitForFunction(() => document.querySelector(".tab.tab-active")?.dataset.tab === "properties"
    && document.querySelector("#props-kind")?.textContent === "RequirementDefinition");
}
