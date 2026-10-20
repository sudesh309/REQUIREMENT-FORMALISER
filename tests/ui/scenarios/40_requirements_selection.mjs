// SU-1: Link to / from Selection uses the latest selection anywhere. A click in the
// containment tree (or a navigate from a link list) replaces an earlier canvas pick, so the
// Selection note, the editor and the Requirements Perspective dock never link a stale element
// (a wrong ARP4754A trace link).
export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("ReqSelection");
  const root = await api("POST", "/api/arch/architecture", { name: "Cockpit" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const fms = await mk("FMS", 60, 60);
  const adc = await mk("ADC", 320, 60);
  const irs = await mk("IRS", 60, 240);
  const set = await api("POST", "/api/req/sets", { name: "SRS", prefix: "REQ-" });
  await api("POST", "/api/req/requirements", { parent: set.id, summary: "Compute position" });
  await api("POST", "/api/req/requirements", { parent: set.id, summary: "Air data" });
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 3);

  const idle = () => page.waitForFunction(() => document.body.dataset.rqPending === "0", null, { timeout: 10000 });
  const selection = () => page.evaluate(() => window.studio.getSelection());
  const pick = (name, modifiers = []) =>
    page.click(`.arch-block[data-name="${name}"] .arch-body`, { position: { x: 10, y: 10 }, modifiers });
  const treeClick = (id) => page.click(`#tree .tree-node[data-id="${id}"] > .row`);
  const canvasSel = () => page.$$eval(".arch-block.sel", (els) => els.map((e) => e.dataset.name).sort().join());
  const noteIs = (sel, text) => page.waitForFunction(([s, t]) => document.querySelector(s)?.textContent === t,
                                                     [sel, text], { timeout: 5000 });
  const links = async (el) => (await api("GET", `/api/req/links?element=${el.id}`)).links;
  const logText = () => page.textContent("#log");
  const editorNote = '[data-rq="sel-note"]';
  const dockNote = '[data-dock="sel-note"]';

  // --- the reported case: canvas pick FMS, requirement row, tree click ADC, Link to Selection ---
  await pick("FMS");
  await page.waitForFunction(() => window.studio.state.selected?.name === "FMS");
  expect((await selection()).join() === fms.id, "the canvas pick is the selection");
  await page.click('.tab[data-tab="requirements"]');
  await idle();
  await page.click('#tab-requirements tr[data-req-id="REQ-1"] .rq-idx');
  await noteIs(editorNote, "Selection: FMS (PartUsage)");
  await treeClick(adc.id);
  await noteIs(editorNote, "Selection: ADC (PartUsage)");
  expect((await selection()).join() === adc.id, `tree click replaces the canvas pick: ${await selection()}`);
  await page.click('[data-rq="link-to"]');
  await idle();
  expect((await logText()).includes("Linked: ADC implements REQ-1"), "ADC implements REQ-1");
  expect(!(await logText()).includes("FMS implements"), "no link from the stale canvas pick");
  expect((await links(adc)).length === 1 && (await links(fms)).length === 0, "the link is ADC's, not FMS's");

  // --- the tree selection shows on the canvas; a multi-selection is replaced by a tree click ---
  await page.click('.tab[data-tab="architecture"]');
  await page.waitForFunction(() => document.querySelector('.arch-block[data-name="ADC"]')?.classList.contains("sel"));
  expect(await canvasSel() === "ADC", `canvas follows the tree: ${await canvasSel()}`);
  await pick("FMS");
  await pick("IRS", ["Shift"]);
  await page.waitForFunction(() => window.studio.getSelection().length === 2);
  await page.click('[data-plugin-button="req-perspective"]');
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off) tr[data-req-id="REQ-2"]');
  await idle();
  await noteIs(dockNote, "Selection: FMS (PartUsage), IRS (PartUsage)");
  await treeClick(irs.id);
  await noteIs(dockNote, "Selection: IRS (PartUsage)");
  expect((await selection()).join() === irs.id, "tree click replaces a canvas multi-selection");
  expect(await canvasSel() === "IRS", `canvas shows the tree selection only: ${await canvasSel()}`);

  // --- Link from Selection in the dock uses the tree selection too --------------------------
  await page.click('[data-rq="dock"] tr[data-req-id="REQ-2"] td:nth-child(3)');
  await page.click('[data-dock="link-from"]');
  await idle();
  expect((await logText()).includes("Linked: IRS implements REQ-2"), "IRS implements REQ-2 (dock)");
  expect((await links(fms)).length === 0, "FMS, picked earlier on the canvas, is not linked");

  // --- selecting the architecture in the tree clears the canvas pick ------------------------
  await pick("FMS");
  await page.waitForFunction(() => window.studio.state.selected?.name === "FMS");
  await treeClick(root.id);
  await noteIs(dockNote, "Selection: Cockpit (PartDefinition)");
  expect((await selection()).join() === root.id, "architecture selected");
  expect(await canvasSel() === "", `no block left selected on the canvas: ${await canvasSel()}`);

  // --- the canvas still publishes its own picks after tree clicks ----------------------------
  await pick("ADC");
  await noteIs(dockNote, "Selection: ADC (PartUsage)");
  expect((await selection()).join() === adc.id, "canvas pick after a tree click");

  // --- navigate (a link in the requirement's detail panel) is a selection too ---------------
  await pick("FMS", ["Shift"]);
  await page.waitForFunction(() => window.studio.getSelection().length === 2);
  await page.click('.tab[data-tab="requirements"]');
  await idle();
  await page.click('#tab-requirements tr[data-req-id="REQ-2"] .rq-idx');
  await page.waitForSelector(`[data-rq="detail-links"] [data-act="nav"][data-id="${irs.id}"]`);
  await page.click(`[data-rq="detail-links"] [data-act="nav"][data-id="${irs.id}"]`);
  await noteIs(editorNote, "Selection: IRS (PartUsage)");
  expect((await selection()).join() === irs.id, "navigate replaces the canvas multi-selection");
}
