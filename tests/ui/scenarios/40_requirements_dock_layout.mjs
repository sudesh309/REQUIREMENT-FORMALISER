// PO-9: the Requirements Perspective docked under the architecture canvas takes its height
// from the canvas instead of covering it. The canvas host shrinks (its ResizeObserver refits a
// fitted view), the status bar stays under the drawing and above the dock, Fit uses the room
// left, the splitter between canvas and dock can be dragged (and moved with the keyboard), the
// height is remembered, and a zoomed view keeps the selected block in sight.
export default async function ({ page, api, fresh, waitReady, expect }) {
  await fresh("ReqDockLayout");
  const root = await api("POST", "/api/arch/architecture", { name: "Cockpit" });
  const names = ["FMS", "ADC", "PFD_CA", "PFD_FO", "MFD", "EICAS", "FCC1", "FCC2", "IRS1", "IRS2"];
  const ids = {};
  for (const [i, name] of names.entries()) {
    const c = await api("POST", "/api/arch/component", { composition: root.id, name,
                                                          layout: { x: 60 + 260 * (i % 4), y: 60 + 180 * Math.floor(i / 4) } });
    ids[name] = c.id;
  }
  const set = await api("POST", "/api/req/sets", { name: "SRS", prefix: "REQ-" });
  await api("POST", "/api/req/requirements", { parent: set.id, summary: "Display attitude" });
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 10);

  const idle = () => page.waitForFunction(() => document.body.dataset.rqPending === "0", null, { timeout: 10000 });
  const settle = () => page.evaluate(() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok))));
  const layout = () => page.evaluate(() => {
    const r = (s) => { const b = document.querySelector(s)?.getBoundingClientRect(); return b && { top: b.top, bottom: b.bottom, h: b.height }; };
    const blocks = [...document.querySelectorAll(".arch-block")].map((b) => b.getBoundingClientRect());
    const frame = document.querySelector(".arch-l-frame").getBoundingClientRect();
    return { host: r(".arch-host"), svg: r(".arch-svg"), status: r(".arch-status"), dock: r('[data-rq="dock"]'),
             frame: { top: frame.top, bottom: frame.bottom },
             blocksTop: Math.min(...blocks.map((b) => b.top)), blocksBottom: Math.max(...blocks.map((b) => b.bottom)),
             zoom: parseInt(document.querySelector('[data-canvas-act="zoom-reset"]').textContent, 10) };
  });
  const show = (l) => JSON.stringify(l);
  // The whole frame is drawn inside the drawing area, above the status bar.
  const fitted = (l, what) => {
    expect(l.frame.top >= l.svg.top - 1 && l.frame.bottom <= l.svg.bottom + 1, `${what}: frame inside the canvas ${show(l)}`);
    expect(l.blocksBottom <= l.status.top, `${what}: no block under the status bar ${show(l)}`);
  };
  // The status bar is a strip under the drawing area and the dock starts below the canvas host.
  const stacked = (l, what) => {
    expect(Math.abs(l.status.top - l.svg.bottom) <= 1, `${what}: status bar right under the drawing ${show(l)}`);
    expect(l.status.bottom <= l.host.bottom + 1, `${what}: status bar inside the canvas host ${show(l)}`);
    if (l.dock) expect(l.dock.top >= l.host.bottom - 1, `${what}: the dock does not cover the canvas ${show(l)}`);
  };
  const undoDepth = async () => (await api("GET", "/api/undo/state")).undo_depth;

  const closed = await layout();
  fitted(closed, "dock closed");
  stacked({ ...closed, dock: null }, "dock closed");

  // --- opening the dock shrinks the canvas host; the fitted view is fitted again -------------
  await page.click('[data-plugin-button="req-perspective"]');
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off) tr[data-req-id="REQ-1"]');
  await idle();
  await settle();
  const open = await layout();
  stacked(open, "dock open");
  fitted(open, "dock open");
  expect(open.host.h < closed.host.h - 200, `the canvas host gave its room to the dock ${show(open)}`);
  expect(open.zoom < closed.zoom, `refitted to the smaller canvas (${closed.zoom}% -> ${open.zoom}%)`);

  // --- the splitter drags: the dock grows by 60 px, the canvas shrinks and refits ------------
  const depth = await undoDepth();
  const sp = await (await page.$('[data-dock="splitter"]')).boundingBox();
  await page.mouse.move(sp.x + 300, sp.y + sp.height / 2);
  await page.mouse.down();
  await page.mouse.move(sp.x + 300, sp.y - 30, { steps: 4 });
  await page.mouse.move(sp.x + 300, sp.y - 60, { steps: 4 });
  await page.mouse.up();
  await settle();
  const dragged = await layout();
  expect(Math.abs(dragged.dock.h - (open.dock.h + 60)) <= 3, `dock height follows the splitter ${show(dragged)}`);
  expect(Math.abs(dragged.host.h - (open.host.h - 60)) <= 3, `canvas host shrinks by as much ${show(dragged)}`);
  stacked(dragged, "after the splitter drag");
  fitted(dragged, "after the splitter drag");
  expect(await undoDepth() === depth, "dragging the splitter changes nothing in the model");
  expect(await page.evaluate(() => document.querySelectorAll(".arch-block.sel").length) === 0, "nor the canvas selection");

  // --- the canvas keeps a usable height however far the splitter goes ----------------------
  await page.mouse.move(sp.x + 300, sp.y - 60);
  await page.mouse.down();
  await page.mouse.move(sp.x + 300, 10, { steps: 6 });
  await page.mouse.up();
  await settle();
  const highest = await layout();
  expect(highest.host.h >= 160, `the canvas keeps room above the dock ${show(highest)}`);
  stacked(highest, "dock at its maximum");
  fitted(highest, "dock at its maximum");

  // --- keyboard: ↓ gives 16 px back to the canvas; double-click restores the default ---------
  await page.focus('[data-dock="splitter"]');
  await page.keyboard.press("ArrowDown");
  await settle();
  expect(Math.abs((await layout()).dock.h - (highest.dock.h - 16)) <= 1, "ArrowDown on the splitter");
  await page.dblclick('[data-dock="splitter"]');
  await settle();
  expect(Math.abs((await layout()).dock.h - 240) <= 1, "double-click: default height");
  await page.keyboard.press("Shift+ArrowUp");
  await settle();
  const kept = await layout();
  // 64 px more, but never beyond the largest dock this window allows (measured above): the room
  // left depends on the toolstrip height, which depends on the fonts of the machine.
  const wanted = Math.min(304, highest.dock.h);
  expect(Math.abs(kept.dock.h - wanted) <= 1, `Shift+ArrowUp: 64 px more (or the maximum) ${show(kept)}`);
  fitted(kept, "after keyboard resizing");

  // --- Fit uses the room left above the dock ---------------------------------------------
  await page.click('[data-canvas-act="zoom-in"]');
  await page.click('[data-canvas-act="zoom-in"]');
  await page.click('[data-canvas-act="fit"]');
  await settle();
  const fit = await layout();
  stacked(fit, "Fit with the dock open");
  fitted(fit, "Fit with the dock open");

  // --- closing the dock gives the room back; the fitted view grows again --------------------
  await page.click('[data-dock="close"]');
  await page.waitForSelector('[data-rq="dock"].rq-off', { state: "attached" });
  await settle();
  const reclosed = await layout();
  expect(Math.abs(reclosed.host.h - closed.host.h) <= 1, `canvas host back to its height ${show(reclosed)}`);
  expect(reclosed.zoom > fit.zoom, `refitted to the bigger canvas (${fit.zoom}% -> ${reclosed.zoom}%)`);
  fitted(reclosed, "dock closed again");

  // --- a zoomed view keeps its zoom and the selected block in sight -------------------------
  // (A click in the containment tree scrolls the canvas to the block, as before SU-1.)
  const inSight = async (name) => {
    const l = await layout();
    const b = await page.evaluate((n) => {
      const r = document.querySelector(`.arch-block[data-name="${n}"] .arch-body`).getBoundingClientRect();
      return { top: r.top, bottom: r.bottom };
    }, name);
    expect(b.top >= l.svg.top - 1 && b.bottom <= l.svg.bottom + 1, `${name} in sight ${show({ block: b, svg: l.svg, zoom: l.zoom })}`);
    return l;
  };
  const treeSelect = async (name) => {
    await page.click(`#tree .tree-node[data-id="${ids[name]}"] > .row`);
    await page.waitForFunction((n) => document.querySelector(`.arch-block[data-name="${n}"]`)?.classList.contains("sel"), name);
    await settle();
  };
  await page.click('[data-canvas-act="zoom-reset"]');               // no longer a fitted view
  await page.click('[data-canvas-act="zoom-in"]');
  await page.click('[data-canvas-act="zoom-in"]');                  // 156%: FMS and IRS2 out of sight
  await treeSelect("FMS");
  const zoom = (await inSight("FMS")).zoom;
  expect(zoom > 150, `zoomed in (${zoom}%)`);
  await treeSelect("IRS2");
  await inSight("IRS2");
  await page.click('[data-plugin-button="req-perspective"]');
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off)');
  await settle();
  const z = await inSight("IRS2");                                   // the selected block stays in sight
  expect(z.zoom === zoom, `the zoom is kept when the dock opens (${zoom}% -> ${z.zoom}%)`);
  expect(Math.abs(z.dock.h - kept.dock.h) <= 1, `the dock reopens at its last height (${z.dock.h}, was ${kept.dock.h})`);

  // --- the dock height is remembered across sessions ---------------------------------------
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("ready"), null, { timeout: 15000 });
  await page.waitForSelector('[data-rq="dock"]:not(.rq-off)');
  await settle();
  const again = await layout();
  expect(Math.abs(again.dock.h - kept.dock.h) <= 1, `dock height remembered (${again.dock.h}, was ${kept.dock.h})`);
  stacked(again, "after a reload");
  fitted(again, "after a reload: the first fit uses the room above the dock");
}
