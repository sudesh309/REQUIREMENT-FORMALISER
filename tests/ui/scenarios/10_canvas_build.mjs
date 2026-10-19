// Build an architecture on the canvas purely by clicking and dragging: new architecture,
// three components, in/out ports, two connectors drawn port to port, a refused connection
// (dimmed target + error toast), drill down and back up with the breadcrumbs, move a block
// and find it in place after a page reload, then undo / redo the move.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("CanvasBuild");
  await waitReady();

  expect(await page.$eval(".tab.tab-active", e => e.dataset.tab) === "architecture", "Architecture tab is shown at start-up");
  const editName = async (name) => {
    await page.waitForSelector(".arch-inline-edit:not([hidden])");
    await page.fill(".arch-inline-edit", name);
    await page.press(".arch-inline-edit", "Enter");
  };

  // Empty state -> new architecture, named in place.
  await page.click('.arch-empty [data-canvas-act="new-architecture"]');
  await editName("AircraftSystem");
  await page.waitForFunction(() => document.querySelector(".arch-frame-title")?.textContent.startsWith("AircraftSystem"));
  const archId = await page.$eval(".arch-frame", e => e.dataset.id);

  // Three components from the toolstrip, each named in place.
  for (const name of ["ADC", "FMS", "Display"]) {
    await page.click('[data-canvas-act="add-component"]');
    await editName(name);
    await page.waitForSelector(`.arch-block[data-name="${name}"]`);
  }
  expect((await page.$$eval(".arch-block", xs => xs.map(x => x.dataset.name))).join() === "ADC,FMS,Display", "three blocks");

  // Ports: select a block, press In / Out in the toolstrip, type the name.
  const block = n => `.arch-block[data-name="${n}"]`;
  const select = async (n) => {
    await page.click(`${block(n)} .arch-body`, { position: { x: 14, y: 12 } });
    await page.waitForFunction(s => document.querySelector(s)?.classList.contains("sel"), block(n));
  };
  const addPort = async (comp, dir, name) => {
    await select(comp);
    await page.click(`[data-canvas-act="add-port-${dir}"]`);
    await editName(name);
    await page.waitForSelector(`${block(comp)} .arch-port[data-name="${name}"]`);
  };
  await addPort("ADC", "out", "airData");
  await addPort("FMS", "in", "air");
  await addPort("FMS", "out", "route");
  await addPort("Display", "in", "route");
  expect(await page.$eval(`${block("FMS")} .arch-port[data-name="air"]`, e => e.dataset.dir) === "in", "input port");

  // Draw connectors by dragging from port to port.
  const port = (c, p) => `${block(c)} .arch-port[data-name="${p}"] .arch-port-glyph`;
  const center = async (sel) => {
    const r = await (await page.waitForSelector(sel)).boundingBox();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  };
  const startDrag = async (from) => {
    const a = await center(from);
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(a.x + 12, a.y + 4, { steps: 3 });
  };
  const dropOn = async (to) => {
    const b = await center(to);
    await page.mouse.move(b.x, b.y, { steps: 10 });
    await page.mouse.up();
  };
  const conns = () => page.$$eval(".arch-conn", xs => xs.length);
  await startDrag(port("ADC", "airData"));
  await page.waitForSelector(".arch-rubber");
  await dropOn(port("FMS", "air"));
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 1);
  await startDrag(port("FMS", "route"));
  await dropOn(port("Display", "route"));
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 2);
  const marker = await page.$eval(".arch-conn.k-data .arch-conn-line", e => e.getAttribute("marker-end"));
  expect(/^url\(#arch-m\d+\)$/.test(marker || ""), `data connectors have an arrowhead: ${marker}`);

  // An invalid connection: Display.route already has a driver. The target is dimmed while
  // dragging and the server's reason is shown in a toast; nothing is added.
  await startDrag(port("ADC", "airData"));
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains("cannot"),
                             `${block("Display")} .arch-port[data-name="route"]`);
  expect(await page.$eval(`${block("FMS")} .arch-port[data-name="air"]`, e => e.classList.contains("cannot")),
         "an already connected pair is not offered again");
  await dropOn(port("Display", "route"));
  const toast = await page.waitForSelector(".arch-toast.error");
  const msg = await toast.textContent();
  expect(/already has an incoming connection/.test(msg), `error toast: ${msg}`);
  expect(await conns() === 2, "refused connection adds nothing");
  await toast.click();

  // Drill down into FMS (double-click) and back with the breadcrumbs.
  await page.dblclick(`${block("FMS")} .arch-body`, { position: { x: 14, y: 12 } });
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "FMS");
  const bports = await page.$$eval(".arch-l-bports .arch-port", xs => xs.map(x => x.dataset.name).sort());
  expect(bports.join() === "air,route", `FMS ports are boundary ports inside it: ${bports}`);
  expect(await page.$eval(".arch-l-bports .arch-port[data-name='air']", e => e.dataset.dir) === "in", "boundary input");
  await page.click('.arch-path button[data-crumb="0"]');
  await page.waitForFunction(() => document.querySelector(".arch-path b")?.textContent === "AircraftSystem");
  await page.waitForSelector(block("Display"));

  // Move Display; the layout is saved, survives a reload, and the move can be undone.
  const view0 = await api("GET", `/api/arch/view/${archId}`);
  const before = view0.components.find(c => c.name === "Display").layout;
  const bb = await (await page.$(`${block("Display")} .arch-body`)).boundingBox();
  await page.mouse.move(bb.x + 14, bb.y + 12);
  await page.mouse.down();
  await page.mouse.move(bb.x + 60, bb.y + 50, { steps: 6 });
  await page.mouse.move(bb.x + 134, bb.y + 112, { steps: 6 });
  await page.mouse.up();
  let moved = before;
  for (let i = 0; i < 60 && moved.x === before.x; i++) {
    await page.waitForTimeout(100);
    moved = (await api("GET", `/api/arch/view/${archId}`)).components.find(c => c.name === "Display").layout;
  }
  expect(moved.x > before.x + 40 && moved.y > before.y + 40 && moved.x % 10 === 0, `moved and snapped: ${JSON.stringify(moved)}`);

  await waitReady();          // reload the page
  await page.waitForSelector(block("Display"));
  const t = await page.$eval(block("Display"), e => e.getAttribute("transform"));
  expect(t === `translate(${moved.x},${moved.y})`, `position after reload: ${t}`);
  expect(await conns() === 2, "connectors after reload");

  const transformIs = (xy) => page.waitForFunction(([s, x, y]) => document.querySelector(s)?.getAttribute("transform") === `translate(${x},${y})`,
                                                   [block("Display"), xy.x, xy.y]);
  await page.waitForSelector('[data-canvas-act="undo"]:not([disabled])');
  expect((await page.getAttribute('[data-canvas-act="undo"]', "title")).includes("Move"), "undo names the step");
  await page.click('[data-canvas-act="undo"]');
  await transformIs(before);
  await page.waitForSelector('[data-canvas-act="redo"]:not([disabled])');
  await page.click('[data-canvas-act="redo"]');
  await transformIs(moved);
}
