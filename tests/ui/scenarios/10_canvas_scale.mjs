// PO-1 / SU-12b: Arrange on a realistic cyclic avionics network (30 LRUs, 90 data
// connectors to random other LRUs) gives a compact grid that Fit shows at a readable zoom.
import { join } from "node:path";

export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("Scale");
  const arch = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const names = ["ADIRU1", "ADIRU2", "ADIRU3", "FMC1", "FMC2", "DU_CPT_PFD", "DU_CPT_ND", "DU_FO_PFD",
                 "DU_FO_ND", "DU_EICAS", "AFDX_SW1", "AFDX_SW2", "CPIOM_A", "CPIOM_B", "CPIOM_C",
                 "RDC1", "RDC2", "GPS1", "GPS2", "RA1", "RA2", "FCC1", "FCC2", "FCC3", "TCAS",
                 "WXR", "VHF1", "VHF2", "MCDU1", "MCDU2"];
  const ids = [];
  for (const name of names) {
    const c = await api("POST", "/api/arch/component", { composition: arch.id, name });
    await api("POST", "/api/arch/port", { owner: c.id, name: "out", direction: "out" });
    ids.push(c.id);
  }
  let seed = 11;
  const rnd = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (const id of ids) {
    for (let k = 0; k < 3; k++) {
      let t;
      do { t = ids[rnd(ids.length)]; } while (t === id);
      await api("POST", "/api/arch/connector", { composition: arch.id, source: { component: id, port: "out" },
                                                target: { component: t, new_port: true } });
    }
  }
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-block").length === 30
    && document.querySelectorAll(".arch-conn").length === 90, null, { timeout: 15000 });

  const t0 = Date.now();
  await page.click('[data-canvas-act="arrange"]');
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("Arranged Aircraft"));
  const arrangeMs = Date.now() - t0;
  await page.click('[data-canvas-act="fit"]');
  await page.waitForTimeout(100);

  const m = await page.evaluate(() => {
    const ed = studio.architecture.canvas;
    const svg = document.querySelector(".arch-svg").getBoundingClientRect();
    const blocks = [...document.querySelectorAll(".arch-block .arch-body")].map(b => b.getBoundingClientRect());
    const frame = document.querySelector(".arch-frame-box").getBoundingClientRect();
    const xs = new Set(ed.scene.blocks.map(b => b.box.x + b.box.w / 2));
    let overlaps = 0;
    for (let i = 0; i < blocks.length; i++) {
      for (let j = i + 1; j < blocks.length; j++) {
        const a = blocks[i], b = blocks[j];
        if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) overlaps++;
      }
    }
    const name = document.querySelector(".arch-block .arch-name").getBoundingClientRect();
    return { zoom: ed.vp.zoom, columns: xs.size, overlaps, nameH: name.height,
             frame: { l: frame.left, t: frame.top, r: frame.right, b: frame.bottom, w: frame.width, h: frame.height },
             svg: { l: svg.left, t: svg.top, r: svg.right, b: svg.bottom } };
  });
  console.error(`[scale] arrange ${arrangeMs} ms, zoom ${(m.zoom * 100).toFixed(0)}%, ${m.columns} columns, frame ${Math.round(m.frame.w)}x${Math.round(m.frame.h)} px`);
  expect(m.zoom >= 0.4, `Fit zoom ${m.zoom} (want >= 40%)`);
  expect(m.columns <= Math.ceil(Math.sqrt(30)) + 2, `${m.columns} layers side by side`);
  expect(m.overlaps === 0, `${m.overlaps} overlapping blocks`);
  expect(m.frame.w / m.frame.h <= 3 && m.frame.h / m.frame.w <= 3, `frame aspect ${m.frame.w}x${m.frame.h}`);
  expect(m.frame.l >= m.svg.l - 1 && m.frame.r <= m.svg.r + 1 && m.frame.t >= m.svg.t - 1 && m.frame.b <= m.svg.b + 1,
         "the arranged frame fits the canvas");
  expect(m.nameH >= 5, `block names are drawn at a readable size (${m.nameH}px)`);
  expect(arrangeMs < 3000, `Arrange round trip took ${arrangeMs} ms`);
  // Screenshot check: the arranged network fills the canvas (no thin strip with empty space).
  const shot = join(process.env.UI_ARTIFACT_DIR || "/tmp", "10_canvas_scale_arranged.png");
  await page.screenshot({ path: shot, clip: { x: m.svg.l, y: m.svg.t, width: m.svg.r - m.svg.l, height: m.svg.b - m.svg.t } });
  const fill = (m.frame.w * m.frame.h) / ((m.svg.r - m.svg.l) * (m.svg.b - m.svg.t));
  expect(fill > 0.45, `the arranged frame covers ${Math.round(fill * 100)}% of the canvas`);
  // Deterministic: arranging again changes nothing (no undo step is recorded).
  const label = (await api("GET", "/api/undo/state")).undo_label;
  const before = await api("GET", `/api/arch/view/${arch.id}`);
  await page.click('[data-canvas-act="arrange"]');
  await page.waitForTimeout(400);
  const after = await api("GET", `/api/arch/view/${arch.id}`);
  expect(JSON.stringify(before.components.map(c => c.layout)) === JSON.stringify(after.components.map(c => c.layout)),
         "Arrange is deterministic");
  expect((await api("GET", "/api/undo/state")).undo_label === label, "a repeated Arrange records no new step");
}
