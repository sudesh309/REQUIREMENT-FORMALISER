// SU-2: reuse an LRU type for a second channel. FCC-L is saved as a reference
// definition, then FCC-R (inline, same port names, connected) is set to reference it in
// the Property Inspector: its ports merge into the definition's (no duplicates drawn on
// top of each other), its connectors are kept, and Validate reports no arch.port.unique.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("IMA Avionics Demo");
  const root = await api("POST", "/api/arch/architecture", { name: "Aircraft" });
  const mk = (name, x, y) => api("POST", "/api/arch/component", { composition: root.id, name, layout: { x, y } });
  const port = (c, name, direction) => api("POST", "/api/arch/port", { owner: c.id, name, direction });
  const link = (a, ap, b, bp) => api("POST", "/api/arch/connector", { composition: root.id,
    source: { component: a.id, port: ap }, target: { component: b.id, port: bp } });
  const adc = await mk("ADC", 140, 80), iru = await mk("IRU", 140, 300), srv = await mk("Servos", 760, 190);
  await port(adc, "airData", "out");
  await port(iru, "inertial", "out");
  await port(srv, "cmdL", "in");
  await port(srv, "cmdR", "in");
  const fccs = {};
  for (const [name, y, cmd] of [["FCC-L", 80, "cmdL"], ["FCC-R", 300, "cmdR"]]) {
    const f = fccs[name] = await mk(name, 450, y);
    await port(f, "airData", "in");
    await port(f, "inertial", "in");
    await port(f, "surfaceCmd", "out");
    await link(adc, "airData", f, "airData");
    await link(iru, "inertial", f, "inertial");
    await link(f, "surfaceCmd", srv, cmd);
  }
  await waitReady();
  await page.waitForFunction(() => document.querySelectorAll(".arch-conn").length === 6);
  const block = n => `.arch-block[data-name="${n}"]`;
  const clickBlock = async (n) => {
    const b = await (await page.waitForSelector(`${block(n)} .arch-body`)).boundingBox();
    await page.mouse.click(b.x + b.width / 2, b.y + 12);
    await page.waitForFunction(s => document.querySelector(s)?.classList.contains("sel"), block(n));
  };

  // 1-2) FCC-L -> toolstrip Save as Ref -> name FlightControlComputer -> Submit.
  await clickBlock("FCC-L");
  await page.click('[data-canvas-act="save-ref"]');
  await page.fill("#modal-root input[name=name]", "FlightControlComputer");
  await page.click("#modal-root [data-modal-submit]");
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("as reference FlightControlComputer"));
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains("ref"), block("FCC-L"));

  // 3) FCC-R -> Property Inspector -> Reference = the definition.
  await clickBlock("FCC-R");
  const defOption = await page.$$eval('.arch-dock [data-dock="definition"] option',
    os => os.find(o => o.textContent.endsWith("::FlightControlComputer"))?.value);
  expect(defOption, "the definition is offered as a Reference");
  await page.selectOption('.arch-dock [data-dock="definition"]', defOption);
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("were merged into the definition's ports"));
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains("ref"), block("FCC-R"));

  // 4) Exactly the definition's 3 ports, each drawn once; the inspector says where they are.
  await page.waitForFunction(() => /Ports \(3\)/.test(document.querySelector(".arch-dock [data-dock-ports-head]")?.textContent || ""));
  const head = await page.textContent(".arch-dock [data-dock-ports-head]");
  expect(/3 on FlightControlComputer/.test(head) && !/only/.test(head), `inspector port header: ${head}`);
  const glyphs = await page.$$eval(`${block("FCC-R")} .arch-port`, ps => ps.map(p => `${p.dataset.name}@${p.getAttribute("transform")}`));
  expect(glyphs.length === 3, `FCC-R draws ${glyphs.length} ports: ${glyphs.join(" ")}`);
  expect(new Set(glyphs.map(g => g.split("@")[1])).size === 3, "no two ports drawn at the same spot");

  // The connectors stayed, now on the shared definition ports, and nothing is broken.
  const v = await api("GET", `/api/arch/view/${root.id}`);
  const fccR = v.components.find(c => c.name === "FCC-R");
  expect(fccR.ports.every(p => p.on_definition), "every FCC-R port is the definition's");
  const onR = v.connectors.filter(k => k.source.component_id === fccR.id || k.target.component_id === fccR.id);
  expect(v.connectors.length === 6 && onR.length === 3, `connectors: ${v.connectors.length}, on FCC-R: ${onR.length}`);
  expect(onR.every(k => fccR.ports.some(p => p.id === k.source.port_id || p.id === k.target.port_id)),
         "FCC-R's connectors end on its (definition) ports");
  expect(v.connectors.every(k => !k.issues.length), "no broken connector");
  await page.click('[data-cmd="validate"]');
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("Validation:"));
  const log = await page.textContent("#log");
  expect(!log.includes("arch.port.unique"), "Validate reports no arch.port.unique");

  // One undo step restores the inline FCC-R with its own ports.
  await page.keyboard.press("Control+z");
  await page.waitForFunction(s => !document.querySelector(s)?.classList.contains("ref"), block("FCC-R"));
  const back = await api("GET", `/api/arch/view/${root.id}`);
  const r2 = back.components.find(c => c.name === "FCC-R");
  expect(!r2.is_reference && r2.ports.length === 3 && r2.ports.every(p => !p.on_definition), "undo restores FCC-R");
}
