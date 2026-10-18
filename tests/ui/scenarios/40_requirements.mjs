// Requirements perspective: author a set by clicking, link to a component (Link to Selection),
// see implementation status, make a link suspect by editing text, then link from the matrix.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ReqUi");
  const arch = await api("POST", "/api/element", { kind: "PartDefinition", name: "Aircraft" });
  const fcc = await api("POST", "/api/element", { kind: "PartUsage", name: "FCC", parent: arch.id });
  const adc = await api("POST", "/api/element", { kind: "PartUsage", name: "ADC", parent: arch.id });
  await waitReady();

  const idle = () => page.waitForFunction(() => document.body.dataset.rqPending === "0", null, { timeout: 10000 });
  const submitModal = async () => {
    await page.click("#modal-root [data-modal-submit]");
    await page.waitForSelector("#modal-root .modal", { state: "detached" });
    await idle();
  };
  const row = (reqId) => `#tab-requirements tr[data-req-id="${reqId}"]`;
  const attr = (sel, name) => page.getAttribute(sel, name);

  // --- create a set with two requirements and a child, by clicking ---------------------
  await page.click('.tab[data-tab="requirements"]');
  await idle();
  await page.click('[data-rq="new-set"]');
  await page.fill('#modal-form input[name="name"]', "Flight Controls");
  await page.fill('#modal-form input[name="prefix"]', "FCS-");
  await submitModal();
  expect((await page.textContent('[data-rq="set-select"]')).includes("Flight Controls"), "set listed");

  await page.click('[data-rq="add"]');
  await idle();
  await page.fill(`${row("FCS-1")} input[data-f="summary"]`, "Pitch control");
  await page.press(`${row("FCS-1")} input[data-f="summary"]`, "Enter");
  await idle();
  await page.click('[data-rq="add"]');
  await idle();
  await page.fill(`${row("FCS-2")} input[data-f="summary"]`, "Roll control");
  await page.press(`${row("FCS-2")} input[data-f="summary"]`, "Enter");
  await idle();
  await page.click(`${row("FCS-1")} .rq-idx`);
  await page.click('[data-rq="add-child"]');
  await idle();
  await page.fill(`${row("FCS-3")} input[data-f="summary"]`, "Pitch rate limit");
  await page.press(`${row("FCS-3")} input[data-f="summary"]`, "Enter");
  await idle();
  await page.selectOption(`${row("FCS-3")} select[data-f="type"]`, "performance");
  await idle();

  const order = await page.$$eval("#tab-requirements tr[data-req-id]", (trs) =>
    trs.map((t) => `${t.querySelector(".rq-idx").textContent.replace(/[^0-9.]/g, "")}:${t.querySelector('[data-f="summary"]').value}`));
  expect(JSON.stringify(order) === JSON.stringify(["1:Pitch control", "1.1:Pitch rate limit", "2:Roll control"]),
         `hierarchy ${JSON.stringify(order)}`);
  const table = await api("GET", "/api/req/table");
  expect(table.rows.find((r) => r.req_id === "FCS-3").type === "performance", "inline type edit saved");
  expect((await page.textContent("#tree")).includes("Pitch rate limit"), "tree shows the new requirement");

  // --- Link to Selection: component selected in the tree, requirement in the table ------
  await page.click(`#tree .tree-node[data-id="${fcc.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector('[data-rq="sel-note"]').textContent.includes("FCC"));
  await page.click(`${row("FCS-2")} .rq-idx`);
  expect(await page.inputValue('[data-rq="link-type"]') === "implement", "default link type is Implement");
  await page.click('[data-rq="link-to"]');
  await idle();
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.implPct === "100",
                             `${row("FCS-2")} td[data-impl-pct]`);
  expect(await attr(`${row("FCS-1")} td[data-impl-pct]`, "data-impl-pct") === "0", "FCS-1 not implemented");
  expect(await attr('[data-rq="rollup"]', "data-impl-pct") === "50", "set roll-up 1 of 2 leaves");
  await page.waitForSelector('[data-rq="detail-links"] .rq-link[data-type="implement"]');

  // --- edit the requirement text: the link becomes suspect, then clear it ---------------
  await page.fill('[data-rq="detail"] textarea[data-d="description"]', "The FCS shall control roll within 30 deg/s.");
  await page.press('[data-rq="detail"] textarea[data-d="description"]', "Control+Enter");
  await idle();
  await page.waitForSelector('[data-rq="detail-links"] .rq-link.suspect');
  expect(await attr(`${row("FCS-2")} td.rq-linkcell`, "data-suspect") === "1", "row shows a suspect link");
  const issues = (await api("GET", "/api/validate")).issues.map((i) => i.rule);
  expect(issues.includes("requirements.suspect-link"), "validator reports the suspect link");

  // --- context menu ----------------------------------------------------------------------
  await page.click(`${row("FCS-1")} .rq-idx`, { button: "right" });
  await page.waitForSelector('[data-rq="context-menu"]');
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-rq="context-menu"]', { state: "detached" });

  // --- drag a requirement onto a tree node: Implement link ------------------------------
  await page.dragAndDrop(`${row("FCS-3")} .rq-grip`, `#tree .tree-node[data-id="${adc.id}"] > .row`);
  await idle();
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.implPct === "100",
                             `${row("FCS-3")} td[data-impl-pct]`);

  // --- traceability matrix: create a link by clicking a cell ----------------------------
  const fcs1 = await attr(row("FCS-1"), "data-id");
  const fcs2 = await attr(row("FCS-2"), "data-id");
  await page.click('.tab[data-tab="traceability"]');
  await idle();
  await page.waitForSelector('[data-tm="matrix"]');
  const suspectCell = `td.rq-cell[data-row="${fcs2}"][data-col="${fcc.id}"] .rq-mlink.suspect`;
  expect(await page.$(suspectCell), "matrix shows the suspect implement link");
  expect(await page.$(`th.rq-rowhead.unlinked[data-row-head="${fcs1}"]`), "FCS-1 row highlighted as unlinked");
  await page.click(`td.rq-cell[data-row="${fcs1}"][data-col="${fcc.id}"]`);
  await page.waitForSelector('#modal-form select[name="choice"]');
  expect((await page.inputValue('#modal-form select[name="choice"]')).startsWith("implement|"), "Implement offered first");
  await submitModal();
  await page.waitForSelector(`td.rq-cell[data-row="${fcs1}"][data-col="${fcc.id}"] .rq-mlink`);
  const links = await api("GET", `/api/req/links?element=${fcc.id}`);
  expect(links.links.length === 2, `FCC implements two requirements (${links.links.length})`);

  // --- traceability diagram --------------------------------------------------------------
  await page.click('[data-tm="view-diagram"]');
  await idle();
  await page.waitForSelector('[data-tm="diagram"] svg', { timeout: 10000 });

  // --- inspector section on the component ------------------------------------------------
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${fcc.id}"] > .row`);
  // FCC was already selected, so wait for the re-rendered section rather than the old one.
  await page.waitForFunction(() => document.querySelectorAll(
    '[data-section="requirements-links"] .rq-link[data-type="implement"]').length === 2, null, { timeout: 10000 });
  await page.click('[data-section="requirements-links"] [data-insp="highlight"]');
  await page.click('[data-section="requirements-links"] .rq-link.suspect [data-act="clear"]');
  await idle();
  await page.waitForFunction(() => !document.querySelector('[data-section="requirements-links"] .rq-link.suspect'));
}
