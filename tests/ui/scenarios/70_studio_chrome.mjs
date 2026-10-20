// Studio chrome (PO-15): one toolstrip row grouped by task, generic elements and the Links /
// Parser tabs under Advanced ▾, styled dialogs only (no window.prompt / confirm), and an
// output pane that collapses and remembers it.
export default async function (ctx) {
  let step = "setup";
  try { await run(ctx, (name) => { step = name; }); } catch (e) { throw new Error(`[${step}] ${e.message}`); }
}

async function run({ page, fresh, waitReady, expect, api }, step) {
  await fresh("ChromeUi");
  const nativeDialogs = [];
  page.on("dialog", (d) => { nativeDialogs.push(d.message()); d.dismiss().catch(() => {}); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await waitReady();
  const until = (fn, arg, what) => page.waitForFunction(fn, arg, { timeout: 10000 })
    .catch(() => { throw new Error(`timed out: ${what}`); });
  const submitModal = async () => {
    await page.click("#modal-root [data-modal-submit]");
    await until(() => !document.querySelector("#modal-root .modal"), null, "dialog closed");
  };

  step("toolstrip grouped by task");
  const sections = await page.$$eval("#ribbon .rb-section", xs => xs.filter(x => x.offsetParent)
    .map(x => x.querySelector(".rb-caption").textContent.trim()));
  expect(JSON.stringify(sections) === JSON.stringify(["Modeling", "Views", "Requirements", "Analysis", "Interop"]),
         `sections: ${sections}`);
  const inSection = (sel, section) => page.$eval(sel, (b, s) => b.closest(".rb-section")?.dataset.section === s, section);
  expect(await inSection('button[data-plugin-button="undo"]', "modeling"), "Undo under Modeling");
  expect(await inSection('button[data-plugin-button="profile-editor"]', "modeling"), "Profile Editor under Modeling");
  expect(await inSection('button[data-plugin-button="req-perspective"]', "requirements"), "Req Perspective under Requirements");
  expect(await inSection('#ribbon [data-cmd="validate"]', "analysis"), "Validate under Analysis");
  expect(await inSection('#ribbon [data-open-tab="compare"]', "interop"), "Compare under Interop");
  const h = await page.$eval("#ribbon", el => el.getBoundingClientRect().height);
  expect(h <= 60, `the toolstrip is one row at 1600 px (${h} px)`);
  expect(!(await page.$(".btn-add:not(#advanced-menu .btn-add)")), "no generic element buttons outside Advanced");

  step("ribbon buttons open the editors");
  await page.click('#ribbon [data-open-tab="checks"]');
  await until(() => !document.querySelector("#tab-checks").classList.contains("hidden"), null, "Model Check open");
  expect(await page.$eval('#ribbon [data-open-tab="checks"]', b => b.classList.contains("rb-on")), "pressed state");

  step("Links and Parser live under Advanced");
  const visibleTabs = () => page.$$eval("#tab-bar .tab", xs => xs.filter(x => x.offsetParent).map(x => x.dataset.tab));
  expect(!(await visibleTabs()).includes("links") && !(await visibleTabs()).includes("parser"), "Links / Parser tabs hidden");
  await page.click('[data-cmd="advanced-menu"]');
  await page.waitForSelector("#advanced-menu:not(.hidden)");
  await page.click('#advanced-menu [data-show-tab="parser"]');
  await until(() => !document.querySelector("#tab-parser").classList.contains("hidden"), null, "Parser open");
  expect((await visibleTabs()).includes("parser"), "the open advanced tab shows in the tab bar");
  expect(await page.$eval("#advanced-menu", m => m.classList.contains("hidden")), "menu closed after the choice");
  await page.click('.tab[data-tab="properties"]');
  expect(!(await visibleTabs()).includes("parser"), "Parser tab hidden again");

  step("generic element through a styled dialog");
  await page.click('[data-cmd="advanced-menu"]');
  await page.click('#advanced-menu .btn-add[data-kind="PartDefinition"]');
  await page.waitForSelector("#modal-root .modal");
  await page.fill('#modal-form [name="name"]', "Gateway");
  await submitModal();
  await until(() => [...document.querySelectorAll("#tree .tree-node > .row")].some(r => r.textContent.includes("Gateway")),
              null, "element added");
  const tree = await api("GET", "/api/tree");
  const gw = tree.children.find(c => c.name === "Gateway");
  expect(gw?.kind === "PartDefinition", "PartDefinition Gateway created");

  step("delete asks in a styled dialog");
  await page.click(`#tree .tree-node[data-id="${gw.id}"] > .row`);
  await until(() => document.querySelector("#props-form input[name=name]")?.value === "Gateway", null, "selected");
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press("Delete");
  await page.waitForSelector("#modal-root .modal");
  expect((await page.textContent("#modal-root .modal")).includes("Gateway"), "the dialog names the element");
  await submitModal();
  await until(() => ![...document.querySelectorAll("#tree .tree-node > .row")].some(r => r.textContent.includes("Gateway")),
              null, "element deleted");

  step("new project through a styled dialog");
  await page.click('header [data-cmd="new"]');
  await page.waitForSelector("#modal-root .modal");
  await page.fill('#modal-form [name="name"]', "Fresh");
  await submitModal();
  await until(() => document.querySelector("#project-name").textContent.startsWith("Fresh"), null, "new project");

  step("output pane collapses and remembers it");
  const logH = () => page.$eval("#output-pane", el => el.getBoundingClientRect().height);
  const open = await logH();
  await page.click('[data-cmd="toggle-log"]');
  const closed = await logH();
  expect(closed < 40 && open > closed + 40, `collapsed ${closed} px (open ${open} px)`);
  await page.click('[data-cmd="validate"]');           // a warning while collapsed is counted
  await page.evaluate(() => window.studio.log("Something to look at", "warning"));
  await until(() => !document.querySelector("#log-unread").classList.contains("hidden"), null, "unread badge");
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("ready"));
  expect(await logH() < 40, "still collapsed after a reload");
  await page.click('[data-cmd="toggle-log"]');
  expect(await logH() > 60, "expanded again");
  expect(await page.$eval("#log-unread", b => b.classList.contains("hidden")), "badge cleared when expanded");

  expect(nativeDialogs.length === 0, `no window.prompt / confirm / alert: ${nativeDialogs.join(" | ")}`);
}
