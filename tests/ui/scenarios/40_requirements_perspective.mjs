// Requirements Perspective dock: requirements stay visible under another view so rows can be
// dragged onto model elements (tree drop and the canvas `drop-on-element` contract) and linked
// with Link to Selection. Then the Links view: change information, clear suspect, delete.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("ReqDock");
  const arch = await api("POST", "/api/element", { kind: "PartDefinition", name: "Aircraft" });
  const fcc = await api("POST", "/api/element", { kind: "PartUsage", name: "FCC", parent: arch.id });
  const ima = await api("POST", "/api/element", { kind: "PartUsage", name: "IMA", parent: arch.id });
  const port = await api("POST", "/api/element", { kind: "PortUsage", name: "a429_out", parent: fcc.id });
  const set = await api("POST", "/api/req/sets", { name: "SRS", prefix: "SRS-" });
  await api("POST", "/api/req/requirements", { parent: set.id, summary: "Partitioning", description: "ARINC 653" });
  const r2 = await api("POST", "/api/req/requirements", { parent: set.id, summary: "Bus output",
                                                          description: "ARINC 429 at 100 kbps" });
  await waitReady();

  const idle = () => page.waitForFunction(() => document.body.dataset.rqPending === "0", null, { timeout: 10000 });
  const dockRow = (reqId) => `[data-rq="dock"] tr[data-req-id="${reqId}"]`;
  const linkRows = () => page.$$eval("#tab-requirements tr.rq-linkrow", (trs) =>
    trs.map((t) => ({ type: t.dataset.type, suspect: t.dataset.suspect === "true", text: t.textContent })));

  // --- open the dock from the toolbar while the Properties tab is shown -------------------
  expect(await page.$('[data-rq="dock"].rq-off'), "dock closed by default");
  await page.click('[data-plugin-button="req-perspective"]');
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off) tr[data-req-id="SRS-1"]');
  await idle();

  // --- drag a requirement from the dock onto a component in the containment tree ----------
  await page.dragAndDrop(dockRow("SRS-1"), `#tree .tree-node[data-id="${ima.id}"] > .row`);
  await idle();
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.implPct === "100",
                             `${dockRow("SRS-1")} td[data-impl-pct]`);

  // --- the canvas reports drops with `drop-on-element`: a port implements SRS-2 -----------
  await page.evaluate(([d, t]) => window.studio.emit("drop-on-element", { dragged_id: d, target_id: t }),
                      [r2.id, port.id]);
  await idle();
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.implPct === "100",
                             `${dockRow("SRS-2")} td[data-impl-pct]`);

  // --- Link to Selection from the dock: FCC selected in the tree --------------------------
  await page.click(`#tree .tree-node[data-id="${fcc.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector('[data-dock="sel-note"]').textContent.includes("FCC"));
  await page.click(`${dockRow("SRS-2")} td:nth-child(3)`);
  await page.click('[data-dock="link-to"]');
  await idle();
  await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.links === "2", `${dockRow("SRS-2")} td[data-links]`);

  // --- the dock steps aside for the full editor ------------------------------------------
  await page.click('.tab[data-tab="requirements"]');
  await idle();
  expect(await page.$('[data-rq="dock"].rq-off'), "dock hidden under the Requirements tab");

  // --- edit SRS-2: its two links become suspect; the Links view shows change information --
  await page.click('#tab-requirements tr[data-req-id="SRS-2"] .rq-idx');
  await page.fill('[data-rq="detail"] textarea[data-d="description"]', "ARINC 429 high speed (100 kbps).");
  await page.press('[data-rq="detail"] textarea[data-d="description"]', "Control+Enter");
  await idle();
  await page.click('[data-rq="view-links"]');
  await idle();
  let links = await linkRows();
  expect(links.length === 3, `three links listed (${links.length})`);
  expect(links.filter((l) => l.suspect).length === 2, "two suspect links");
  expect(links.filter((l) => l.suspect).every((l) => l.text.includes("Destination changed")), "change information");
  await page.check('[data-rq="suspect-only"]');
  expect((await linkRows()).length === 2, "suspect-only filter");
  await page.click('#tab-requirements tr.rq-linkrow.suspect [data-act="clear"]');
  await idle();
  expect((await linkRows()).length === 1, "one suspect link left after Clear");
  await page.click('[data-rq="clear-all-suspect"]');
  await idle();
  expect((await linkRows()).length === 0, "Clear all suspect");
  await page.uncheck('[data-rq="suspect-only"]');
  links = await linkRows();
  expect(links.length === 3 && !links.some((l) => l.suspect), "links kept, none suspect");

  // --- delete a link from the list --------------------------------------------------------
  await page.click('#tab-requirements tr.rq-linkrow:has-text("IMA") [data-act="del"]');
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForSelector("#modal-root .modal", { state: "detached" });
  await idle();
  expect((await linkRows()).length === 2, "link deleted");
  expect((await api("GET", `/api/req/links?element=${ima.id}`)).links.length === 0, "IMA no longer linked");

  // --- the dock comes back on other tabs; Alt+Shift+R toggles it --------------------------
  await page.click('.tab[data-tab="properties"]');
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off)');
  await page.click(`#tree .tree-node[data-id="${arch.id}"] > .row`);
  await page.keyboard.press("Alt+Shift+R");
  await page.waitForSelector('[data-rq="dock"].rq-off', { state: "attached" });
}
