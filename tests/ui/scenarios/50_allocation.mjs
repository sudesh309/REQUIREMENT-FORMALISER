// Allocation Editor: create a set and a scenario by clicking, allocate three sources by clicking
// matrix cells, filter unallocated sources, select row/allocation, then reload the page (and a
// saved/reloaded project) and check that the matrix state persisted.
export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("AllocUi");
  const el = (kind, name, parent) => api("POST", "/api/element", { kind, name, parent });
  const logical = await el("PartDefinition", "LogicalArch");
  const src = {};
  for (const n of ["FlightMgmt", "Navigation", "Display", "Maintenance"]) src[n] = await el("PartUsage", n, logical.id);
  const physical = await el("PartDefinition", "PhysicalArch");
  const tgt = {};
  for (const n of ["IMA_Cabinet", "CDU", "MFD"]) tgt[n] = await el("PartUsage", n, physical.id);
  await waitReady();

  // Open the editor: empty state first.
  await page.click('.tab[data-tab="allocation"]');
  await page.waitForSelector("#tab-allocation .alloc-empty");

  // New Set (toolstrip) -> modal.
  await page.click('.alloc-toolstrip [data-alloc-act="new-set"]');
  await page.waitForSelector("#modal-form");
  await page.fill('#modal-form [name="name"]', "L2P");
  await page.selectOption('#modal-form [name="source"]', logical.id);
  await page.selectOption('#modal-form [name="target"]', physical.id);
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#alloc-browser [data-type="set"]:has-text("L2P")');
  await page.waitForSelector("#alloc-matrix");

  // New Scenario (toolstrip) -> modal; Enter submits.
  await page.click('.alloc-toolstrip [data-alloc-act="new-scenario"]');
  await page.waitForSelector("#modal-form");
  await page.fill('#modal-form [name="name"]', "Dual IMA");
  await page.press('#modal-form [name="name"]', "Enter");
  await page.waitForSelector('#alloc-browser [data-type="scenario"]:has-text("Dual IMA")');
  await page.waitForFunction(() => document.querySelector("#alloc-mhead .crumb")?.textContent.includes("Dual IMA"));

  // Back to Scenario 1 and allocate three sources by clicking cells.
  await page.click('#alloc-browser [data-type="scenario"]:has-text("Scenario 1")');
  await page.waitForFunction(() => document.querySelector("#alloc-mhead .crumb")?.textContent.includes("Scenario 1"));
  const pairs = [["FlightMgmt", "IMA_Cabinet"], ["Navigation", "IMA_Cabinet"], ["Display", "MFD"]];
  const cell = (s, t) => `td.cell[data-src="${src[s].id}"][data-tgt="${tgt[t].id}"]`;
  for (const [s, t] of pairs) {
    await page.click(cell(s, t));
    await page.waitForSelector(`${cell(s, t)}.on`);
  }
  expect(await page.locator("#alloc-matrix td.cell.on").count() === 3, "three allocated cells");
  await page.waitForFunction(() => document.querySelector("#alloc-stats")?.textContent.startsWith("3 allocations"));
  // The last allocation is selected: properties card + containment tree entry.
  await page.waitForSelector('[data-alloc-card="allocation"]:has-text("Display")');
  await page.waitForSelector('#tree .tree-node .row:has-text("Display → MFD")');

  // Toggle off and on again (click toggles).
  await page.click(cell("Display", "MFD"));
  await page.waitForSelector(`${cell("Display", "MFD")}:not(.on)`);
  await page.click(cell("Display", "MFD"));
  await page.waitForSelector(`${cell("Display", "MFD")}.on`);

  // Selecting a row header highlights its allocated targets (cross-feature event).
  await page.evaluate(() => { window.__hl = null; window.studio.on("highlight", (p) => { window.__hl = p; }); });
  await page.click(`#alloc-matrix .row-head[data-id="${src.FlightMgmt.id}"]`);
  await page.waitForFunction(() => window.__hl && window.__hl.reason === "allocation");
  const hl = await page.evaluate(() => window.__hl);
  expect(hl.color === "#8b5cf6" && hl.ids.length === 1 && hl.ids[0] === tgt.IMA_Cabinet.id, `highlight payload ${JSON.stringify(hl)}`);
  await page.waitForSelector(`#alloc-matrix .col-head.hl[data-id="${tgt.IMA_Cabinet.id}"]`);
  await page.waitForSelector('[data-alloc-card="element"]:has-text("FlightMgmt")');

  // Alt+click selects an existing allocation without toggling it.
  await page.click(cell("Navigation", "IMA_Cabinet"), { modifiers: ["Alt"] });
  await page.waitForSelector(`${cell("Navigation", "IMA_Cabinet")}.on.sel`);
  await page.waitForSelector('[data-alloc-card="allocation"]:has-text("Navigation")');

  // Coverage and chain panels.
  await page.click('[data-alloc-side="coverage"]');
  await page.waitForFunction(() => document.querySelector("#alloc-cov-pct")?.textContent === "75%");
  expect((await page.locator("#alloc-cov-unallocated li").allTextContents()).join().includes("Maintenance"),
         "Maintenance listed as unallocated");
  await page.click('[data-alloc-side="chain"]');
  await page.waitForSelector('[data-alloc-card="chain"] svg', { timeout: 10000 });
  await page.click('[data-alloc-side="properties"]');

  // Filter: unallocated sources only.
  await page.selectOption("#alloc-show", "unallocated");
  await page.waitForFunction(() => document.querySelectorAll("#alloc-matrix tbody tr").length === 1);
  const rows = await page.locator("#alloc-matrix tbody .row-head .nm").allTextContents();
  expect(rows.length === 1 && rows[0] === "Maintenance", `unallocated rows: ${rows}`);
  await page.selectOption("#alloc-show", "all");
  await page.waitForFunction(() => document.querySelectorAll("#alloc-matrix tbody tr").length === 4);

  // Reload the page: the matrix state comes back from the server.
  const checkPersisted = async () => {
    await page.click('.tab[data-tab="allocation"]');
    await page.waitForSelector("#alloc-matrix td.cell.on");
    await page.waitForFunction(() => document.querySelector("#alloc-mhead .crumb")?.textContent.includes("Scenario 1"));
    for (const [s, t] of pairs) expect(await page.locator(`${cell(s, t)}.on`).count() === 1, `${s} -> ${t} persisted`);
    expect(await page.locator("#alloc-matrix td.cell.on").count() === 3, "exactly three allocations after reload");
    expect(await page.locator('#alloc-browser [data-type="scenario"]').count() === 2, "two scenarios after reload");
  };
  await waitReady();
  await checkPersisted();

  // Save the project JSON, load it into a fresh session, reload: still there.
  const saved = await api("GET", "/api/save");
  await api("POST", "/api/new", { name: "Other" });
  await api("POST", "/api/load", { text: saved.text });
  await waitReady();
  await checkPersisted();
}
