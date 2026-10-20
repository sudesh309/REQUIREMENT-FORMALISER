// Requirements perspective, second flow: import a CSV through the dialog, filter, keyboard
// indent / outdent, test case result driving verification status, ReqIF export + re-import,
// inspector "Link requirement…", matrix Verify link and the trace diagram following the selection.
import { readFileSync } from "node:fs";

const CSV = [
  "id,summary,description,type,priority,parent_id",
  "SRS-1,Navigation,The FMS shall compute the aircraft position.,functional,high,",
  "SRS-2,Position accuracy,RNP 0.3 lateral accuracy.,performance,high,SRS-1",
  "SRS-3,Partitioning,Hosted in an ARINC 653 partition.,safety,medium,",
].join("\n") + "\n";

export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ReqImport");
  const arch = await api("POST", "/api/element", { kind: "PartDefinition", name: "Avionics" });
  const fms = await api("POST", "/api/element", { kind: "PartUsage", name: "FMS", parent: arch.id });
  await waitReady();

  const idle = () => page.waitForFunction(() => document.body.dataset.rqPending === "0", null, { timeout: 10000 });
  const submitModal = async () => {
    await page.click("#modal-root [data-modal-submit]");
    await page.waitForSelector("#modal-root .modal", { state: "detached" });
    await idle();
  };
  const row = (reqId) => `#tab-requirements tr[data-req-id="${reqId}"]`;
  const shownIds = () => page.$$eval("#tab-requirements tr[data-req-id]", (trs) => trs.map((t) => t.dataset.reqId));
  const indexOf = (reqId) => page.$eval(`${row(reqId)} .rq-idx`, (el) => el.textContent.replace(/[^0-9.]/g, ""));

  // --- import a CSV file into a new set --------------------------------------------------
  await page.click('.tab[data-tab="requirements"]');
  await idle();
  await page.click('[data-rq="import"]');
  await page.setInputFiles('#modal-form input[name="file"]',
                           { name: "srs.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await submitModal();
  expect(JSON.stringify(await shownIds()) === '["SRS-1","SRS-2","SRS-3"]', `imported rows ${await shownIds()}`);
  expect(await indexOf("SRS-2") === "1.1", "parent_id nests SRS-2 under SRS-1");
  expect((await page.textContent('[data-rq="set-select"]')).includes("srs"), "set named after the file");

  // --- filters ---------------------------------------------------------------------------
  await page.selectOption('[data-rq="filter-type"]', "safety");
  expect(JSON.stringify(await shownIds()) === '["SRS-3"]', "type filter");
  await page.selectOption('[data-rq="filter-type"]', "");
  await page.fill('[data-rq="filter-text"]', "RNP");
  expect(JSON.stringify(await shownIds()) === '["SRS-1","SRS-2"]', "text filter keeps the ancestor");
  expect(await page.$(`${row("SRS-1")}.dim`) && !(await page.$(`${row("SRS-2")}.dim`)), "ancestor dimmed");
  await page.fill('[data-rq="filter-text"]', "");
  expect((await shownIds()).length === 3, "filter cleared");

  // --- keyboard: indent / outdent ---------------------------------------------------------
  await page.click(`${row("SRS-3")} input[data-f="summary"]`);
  await page.keyboard.press("Alt+Shift+ArrowRight");
  await idle();
  expect(await indexOf("SRS-3") === "1.2", "Alt+Shift+Right indents under the previous sibling");
  await page.keyboard.press("Alt+Shift+ArrowLeft");
  await idle();
  expect(await indexOf("SRS-3") === "2", "Alt+Shift+Left outdents");

  // --- test case verifying SRS-2; its result drives the verification status ----------------
  await page.click(`${row("SRS-2")} .rq-idx`);
  await page.click('[data-rq="add-test"]');
  await page.fill('#modal-form input[name="name"]', "RNP flight test");
  await submitModal();
  expect(await page.getAttribute(`${row("SRS-2")} td[data-ver-state]`, "data-ver-state") === "unexecuted",
         "verified by an unexecuted test");
  await page.click('[data-rq="view-tests"]');
  await page.selectOption('#tab-requirements tr[data-id] select[data-f="result"]', "passed");
  await idle();
  await page.click('[data-rq="view-req"]');
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.verState === "passed",
                             `${row("SRS-2")} td[data-ver-state]`);

  // --- export ReqIF (download) and import it back as a second set ----------------------------
  await page.click('[data-rq="export"]');
  await page.selectOption('#modal-form select[name="format"]', "reqif");
  const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#modal-root [data-modal-submit]")]);
  await idle();
  expect(dl.suggestedFilename() === "srs.reqif", `download name ${dl.suggestedFilename()}`);
  const xml = readFileSync(await dl.path(), "utf8");
  expect(xml.includes("SPEC-HIERARCHY") && xml.includes("Position accuracy"), "ReqIF content");
  await page.click('[data-rq="import"]');
  await page.setInputFiles('#modal-form input[name="file"]',
                           { name: "supplier.reqif", mimeType: "application/xml", buffer: Buffer.from(xml) });
  await page.selectOption('#modal-form select[name="set"]', "");
  await page.fill('#modal-form input[name="new_set"]', "Supplier SRS");
  await submitModal();
  const sets = await api("GET", "/api/req/sets");
  expect(sets.length === 2 && sets[1].name === "Supplier SRS" && sets[1].count === 3, "ReqIF re-imported");

  // --- set properties dialog: rename -------------------------------------------------------
  await page.click('[data-rq="set-props"]');
  await page.fill('#modal-form input[name="name"]', "Supplier SRS v2");
  await submitModal();
  expect((await page.textContent('[data-rq="set-select"]')).includes("Supplier SRS v2"), "set renamed");

  // --- inspector: link the FMS component to SRS-1 -------------------------------------------
  const srs1 = (await api("GET", `/api/req/table?set=${sets[0].id}`)).rows.find((r) => r.req_id === "SRS-1");
  await page.click('.tab[data-tab="properties"]');
  await page.click(`#tree .tree-node[data-id="${fms.id}"] > .row`);
  await page.click('[data-section="requirements-links"] [data-insp="link"]');
  expect(await page.inputValue('#modal-form select[name="type"]') === "implement", "Implement offered first");
  await page.selectOption('#modal-form select[name="target"]', srs1.id);
  await submitModal();
  await page.waitForSelector('[data-section="requirements-links"] .rq-link[data-type="implement"]');

  // --- matrix with test case columns: a Verify link by clicking a cell -----------------------
  const tc = (await api("GET", `/api/req/table?set=${sets[0].id}`)).test_cases[0];
  await page.click('.tab[data-tab="traceability"]');
  await idle();
  await page.selectOption('[data-tm="set"]', sets[0].id);
  await idle();
  await page.selectOption('[data-tm="columns"]', "test-cases");
  await idle();
  await page.click(`td.rq-cell[data-row="${srs1.id}"][data-col="${tc.id}"]`);
  expect((await page.inputValue('#modal-form select[name="choice"]')).startsWith("verify|"), "Verify offered first");
  await submitModal();
  await page.waitForSelector(`td.rq-cell[data-row="${srs1.id}"][data-col="${tc.id}"] .rq-mlink`);
  const [csv] = await Promise.all([page.waitForEvent("download"), page.click('[data-tm="export-csv"]')]);
  await idle();
  expect(readFileSync(await csv.path(), "utf8").includes("RNP flight test"), "matrix CSV has the test case column");

  // --- the trace diagram follows the selected element ---------------------------------------
  await page.click('[data-tm="view-diagram"]');
  await idle();
  expect(await page.inputValue('[data-tm="element"]') === fms.id, "diagram centred on the selected component");
  await page.waitForSelector('[data-tm="diagram"] svg', { timeout: 10000 });
  expect((await page.textContent('[data-tm="diagram"]')).includes("Navigation"), "diagram shows the linked requirement");
}
