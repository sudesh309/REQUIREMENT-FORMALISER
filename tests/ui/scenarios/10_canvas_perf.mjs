// Performance: 60 components and 200 connectors (one textual import), full render time,
// per-frame cost of dragging the most connected block, a real drag that saves, Arrange + Fit.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("CanvasPerf");
  let seed = 7;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  const lines = ["package Big {", "  part def Avionics {"];
  for (let i = 0; i < 60; i++) lines.push(`    part lru${i} { in port i0; in port i1; in port i2; in port i3; out port o0; out port o1; }`);
  const free = [];
  for (let i = 0; i < 60; i++) for (let j = 0; j < 4; j++) free.push([i, j]);
  for (let i = free.length - 1; i > 0; i--) { const j = rnd(i + 1); [free[i], free[j]] = [free[j], free[i]]; }
  let n = 0;
  for (const [i, j] of free) {
    if (n >= 200) break;
    const s = rnd(60);
    if (s === i) continue;
    lines.push(`    connect lru${s}.o${rnd(2)} to lru${i}.i${j};`);
    n++;
  }
  lines.push("  }", "}");
  await api("POST", "/api/parse", { source: lines.join("\n") });
  const arch = (await api("GET", "/api/arch/roots")).roots.find(r => r.name === "Avionics");
  await api("POST", "/api/arch/auto-layout", { composition: arch.id });

  const t0 = Date.now();
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 200
    && document.querySelectorAll(".arch-block").length === 60, null, { timeout: 20000 });
  const loadMs = Date.now() - t0;

  const stats = await page.evaluate(() => {
    const ed = studio.architecture.canvas;
    const t = performance.now();
    for (let i = 0; i < 5; i++) ed.render();
    const renderMs = (performance.now() - t) / 5;
    // per-frame drag work for the block with the most connectors
    const sc = ed.scene;
    let best = null;
    for (const b of sc.blocks) if (!best || (sc.byComp.get(b.key) || []).length > (sc.byComp.get(best.key) || []).length) best = b;
    const box0 = { ...best.box };
    const frame0 = sc.frame;
    const t2 = performance.now();
    for (let i = 1; i <= 30; i++) {
      best.box = { ...box0, x: box0.x + i * 7, y: box0.y + i * 3 };
      ed.dom.get(best.key).setAttribute("transform", `translate(${best.box.x},${best.box.y})`);
      ed.afterBoxesChanged([best.key], frame0);
    }
    const frameMs = (performance.now() - t2) / 30;
    best.box = box0;
    ed.render();
    return { renderMs, frameMs, links: (sc.byComp.get(best.key) || []).length, name: best.c.name };
  });
  console.error(`[perf] load ${loadMs} ms, render ${stats.renderMs.toFixed(1)} ms, drag frame ${stats.frameMs.toFixed(2)} ms (${stats.links} connectors on ${stats.name})`);
  expect(stats.renderMs < 400, `full render ${stats.renderMs} ms`);
  expect(stats.frameMs < 16, `drag frame ${stats.frameMs} ms (60 fps budget)`);

  // A real drag of that block keeps up and saves once.
  await page.click('[data-canvas-act="zoom-reset"]');
  const sel = `.arch-block[data-name="${stats.name}"]`;
  const el = await page.$(`${sel} .arch-body`);
  await el.scrollIntoViewIfNeeded();
  const handle = await page.evaluate((s) => {
    studio.architecture.canvas.scrollIntoView(document.querySelector(s).dataset.key);
    const r = document.querySelector(`${s} .arch-body`).getBoundingClientRect();
    return { x: r.x + 10, y: r.y + 8 };
  }, sel);
  await page.waitForTimeout(50);
  const depth0 = (await api("GET", "/api/undo/state")).undo_depth;
  const before = await page.$eval(sel, e => e.getAttribute("transform"));
  const t3 = Date.now();
  await page.mouse.move(handle.x, handle.y);
  await page.mouse.down();
  await page.mouse.move(handle.x + 40, handle.y + 30, { steps: 20 });
  await page.mouse.up();
  const dragMs = Date.now() - t3;
  await page.waitForFunction(([s, b]) => document.querySelector(s)?.getAttribute("transform") !== b, [sel, before]);
  expect(dragMs < 3000, `20-step drag took ${dragMs} ms`);
  // The block moves at once; the layout is saved when the drag ends (asynchronously): wait
  // for the toolstrip's Undo to name it before reading the history.
  await page.waitForFunction(() => document.querySelector('[data-canvas-act="undo"]')?.title.includes("Move"));
  const undo = await api("GET", "/api/undo/state");
  expect(undo.undo_label === "Move" && undo.undo_depth === depth0 + 1,
         `one Move step: ${undo.undo_label}, ${undo.undo_depth - depth0} new step(s)`);

  // Arrange and Fit stay responsive.
  const t4 = Date.now();
  await page.click('[data-canvas-act="arrange"]');
  await page.waitForFunction(() => !document.querySelector('[data-canvas-act="undo"]').disabled
    && document.querySelector('[data-canvas-act="undo"]').title.includes("Arrange"), null, { timeout: 15000 });
  await page.waitForFunction(() => {             // Arrange ends with a fit to view
    const f = document.querySelector(".arch-frame-box")?.getBoundingClientRect();
    const s = document.querySelector(".arch-svg").getBoundingClientRect();
    return f && f.left >= s.left && f.right <= s.right + 1 && f.top >= s.top && f.bottom <= s.bottom + 1;
  }, null, { timeout: 15000 });
  expect(Date.now() - t4 < 8000, "arrange round trip");
  expect(!(await page.textContent(".arch-dock")).includes("Auto size"), "arranging does not freeze block sizes");
}
