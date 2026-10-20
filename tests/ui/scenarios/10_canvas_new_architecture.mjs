// PO-2 / SU-13: a second (and third) architecture is created from the canvas with GUI
// gestures only (empty-canvas card, Open ▾, ＋ New architecture, background menu), named in
// place, one undo step each, and offered by the Allocation editor; an allocation set is
// made between them. Header New / Load warn about unsaved changes with styled dialogs, and
// no window.prompt / confirm / alert is ever shown.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("AircraftAvionics");
  const native = [];
  page.on("dialog", async (d) => { native.push(`${d.type()}: ${d.message()}`); await d.dismiss(); });
  await waitReady();
  const undoState = () => api("GET", "/api/undo/state");
  const title = () => page.$eval(".arch-frame-title", e => e.textContent);
  const nameInPlace = async (name) => {
    await page.waitForSelector(".arch-inline-edit:not([hidden])");
    await page.fill(".arch-inline-edit", name);
    await page.press(".arch-inline-edit", "Enter");
    await page.waitForFunction(n => document.querySelector(".arch-frame-title")?.textContent.startsWith(n)
      && document.querySelector(".arch-frame")?.dataset.id, name);
  };
  const archNames = async () => (await api("GET", "/api/arch/roots")).roots.map(r => r.name).sort().join();

  // 1) Empty canvas card.
  await page.click('.arch-empty [data-canvas-act="new-architecture"]');
  await nameInPlace("AircraftAvionics");
  const s1 = await undoState();
  expect(s1.undo_depth === 1 && s1.undo_label === "New architecture", `one undo step: ${JSON.stringify(s1)}`);

  // 2) Open ▾ -> "＋ New architecture…": named in place, opened, one more undo step.
  await page.selectOption('[data-canvas="open"]', { label: "＋ New architecture…" });
  await nameInPlace("FunctionalArch");
  let s = await undoState();
  expect(s.undo_depth === 2 && s.undo_label === "New architecture", `Open ▾ creates one step: ${JSON.stringify(s)}`);
  expect((await page.$eval('[data-canvas="open"]', e => e.selectedOptions[0]?.textContent)).endsWith("FunctionalArch"),
         "Open ▾ shows the new architecture");

  // 3) The ＋ New architecture button next to Open ▾.
  await page.click('.arch-bar [data-canvas-act="new-architecture"]');
  await nameInPlace("PhysicalArch");
  expect(await archNames() === "AircraftAvionics,FunctionalArch,PhysicalArch", `architectures: ${await archNames()}`);

  // 4) Background context menu -> New architecture…, Escape cancels and returns.
  const frame = await (await page.$(".arch-frame-box")).boundingBox();
  await page.mouse.click(frame.x + frame.width / 2, frame.y + frame.height / 2, { button: "right" });
  await page.click('.arch-menu [data-menu-cmd="new-architecture"]');
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  expect((await page.inputValue(".arch-inline-edit")) === "Architecture", "a unique name is suggested");
  await page.press(".arch-inline-edit", "Escape");
  await page.waitForFunction(() => document.querySelector(".arch-frame-title")?.textContent.startsWith("PhysicalArch"));
  expect(await archNames() === "AircraftAvionics,FunctionalArch,PhysicalArch", "Escape creates nothing");
  // A taken name is refused with a message and can be corrected in place.
  await page.click('.arch-bar [data-canvas-act="new-architecture"]');
  await page.waitForSelector(".arch-inline-edit:not([hidden])");
  await page.fill(".arch-inline-edit", "FunctionalArch");
  await page.press(".arch-inline-edit", "Enter");
  await page.waitForSelector('.arch-toast.error');
  await nameInPlace("SoftwareArch");
  // One undo step removes it again.
  const depth = (await undoState()).undo_depth;
  await page.click('[data-canvas-act="undo"]');
  await page.waitForFunction(() => !document.querySelector(".arch-frame-title")?.textContent.startsWith("SoftwareArch"));
  expect((await undoState()).undo_depth === depth - 1 && !(await archNames()).includes("SoftwareArch"), "undo removes it");

  // 5) Allocation: both architectures are offered; create F2L between them with the GUI.
  await page.click('.tab[data-tab="allocation"]');
  await page.click('.alloc-toolstrip [data-alloc-act="new-set"]');
  await page.waitForSelector("#modal-form");
  const opts = await page.$$eval('#modal-form [name="source"] option', os => os.map(o => o.textContent));
  expect(opts.some(o => o.includes("FunctionalArch")) && opts.some(o => o.includes("PhysicalArch")), `allocation sources: ${opts}`);
  await page.fill('#modal-form [name="name"]', "F2P");
  await page.selectOption('#modal-form [name="source"]', { label: opts.find(o => o.includes("FunctionalArch")) });
  await page.selectOption('#modal-form [name="target"]', { label: opts.find(o => o.includes("PhysicalArch")) });
  await page.click("[data-modal-submit]");
  await page.waitForSelector('#alloc-browser [data-type="set"]:has-text("F2P")');
  await page.click('.tab[data-tab="architecture"]');

  // 6) Header New with unsaved changes: styled warning; Cancel keeps the project.
  expect((await undoState()).dirty, "edits make the project dirty");
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root [data-unsaved-warning]");
  await page.click("#modal-root [data-modal-cancel]");
  await page.waitForFunction(() => !document.querySelector("#modal-root .modal"));
  expect(await archNames() === "AircraftAvionics,FunctionalArch,PhysicalArch", "Cancel keeps the project");
  // Load warns too (Escape cancels before any file chooser opens).
  await page.click('header [data-cmd="load"]');
  await page.waitForSelector("#modal-root [data-unsaved-warning]");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("#modal-root .modal"));
  // Save JSON clears the dirty state: New asks for a name only.
  const download = page.waitForEvent("download");
  await page.click('header [data-cmd="save"]');
  await download;
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("Saved project.json"));
  expect(!(await undoState()).dirty, "saved: not dirty");
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root input[name=name]");
  expect(!(await page.$("#modal-root [data-unsaved-warning]")), "no warning after saving");
  await page.fill("#modal-root input[name=name]", "Fresh");
  await page.press("#modal-root input[name=name]", "Enter");
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent.startsWith("Fresh"));
  await page.waitForSelector(".arch-empty:not([hidden])");

  // Core "Add" buttons (now in the Advanced menu) and element delete use styled dialogs too.
  await page.click('[data-cmd="advanced-menu"]');
  await page.click('#advanced-menu .btn-add[data-kind="Package"]');
  await page.waitForSelector("#modal-root input[name=name]");
  await page.fill("#modal-root input[name=name]", "Pkg");
  await page.press("#modal-root input[name=name]", "Enter");
  await page.waitForSelector('#tree .tree-node .row:has-text("Pkg")');
  await page.click('#tree .tree-node .row:has-text("Pkg")');
  await page.waitForFunction(() => document.querySelector("#props-qname")?.textContent.endsWith("Pkg"));
  await page.click('.tab[data-tab="properties"]');
  await page.click('[data-cmd="delete-element"]');
  await page.waitForSelector("#modal-root .modal:has-text('Delete')");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForFunction(() => ![...document.querySelectorAll("#tree .row")].some(r => r.textContent.includes("Pkg")));
  expect(!native.length, `native dialogs shown: ${native.join(" | ")}`);
}
