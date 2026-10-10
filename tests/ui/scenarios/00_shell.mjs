// The SPA boots, vendored libraries load, and the plugin API is present.
export default async function ({ page, fresh, waitReady, expect, api }) {
  await fresh("Shell");
  const v = await api("POST", "/api/element", { kind: "PartDefinition", name: "Vehicle" });
  await waitReady();
  expect(await page.evaluate(() => typeof window.tailwind !== "undefined" || getComputedStyle(document.body).display === "flex"),
         "tailwind styles applied");
  expect(await page.evaluate(() => typeof window.mermaid?.run === "function"), "mermaid loaded");
  for (const fn of ["registerTab", "registerToolbarButton", "registerInspectorSection", "registerTreeBadge", "registerShortcut"])
    expect(await page.evaluate(f => typeof window.studio?.[f] === "function", fn), `studio.${fn}`);
  await page.click(`#tree .tree-node[data-id="${v.id}"] > .row`);
  await page.waitForFunction(() => document.querySelector("#props-kind")?.textContent === "PartDefinition");
  await page.click('.tab[data-tab="diagram"]');
  await page.waitForSelector("#diagram svg", { timeout: 10000 });
}
