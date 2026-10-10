// Headless-browser UI scenarios for the web frontend.
//
//   node tests/ui/run_scenarios.mjs <base-url> [scenario-name-filter]
//
// Every module in tests/ui/scenarios/*.mjs default-exports
//   async function (ctx) { ... }   // throw to fail
// where ctx = { page, base, api(method, path, body), fresh(name), waitReady(), expect(cond, msg) }.
// Playwright is resolved from PLAYWRIGHT_MODULE (path to the package's index.mjs).
// Prints one JSON line per scenario and exits non-zero if any failed.
import { readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [base, filter = ""] = process.argv.slice(2);
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const dir = join(dirname(fileURLToPath(import.meta.url)), "scenarios");
const files = readdirSync(dir).filter(f => f.endsWith(".mjs") && f.includes(filter)).sort();

const browser = await chromium.launch();
let failed = 0;
for (const file of files) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  const api = async (method, path, body) => {
    const r = await fetch(base + path, { method, headers: body ? { "Content-Type": "application/json" } : {},
                                         body: body ? JSON.stringify(body) : undefined });
    const text = await r.text();
    if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}: ${text.slice(0, 300)}`);
    return text ? JSON.parse(text) : null;
  };
  const ctx = {
    page, base, api, errors,
    expect(cond, msg) { if (!cond) throw new Error(`expectation failed: ${msg}`); },
    async fresh(name = "UiTest") { await api("POST", "/api/new", { name }); },
    async waitReady() {
      await page.goto(base + "/");
      await page.waitForFunction(() => document.querySelector("#log")?.textContent.includes("ready"),
                                 null, { timeout: 15000 });
    },
  };
  const started = performance.now();
  try {
    const mod = await import(pathToFileURL(join(dir, file)).href);
    await mod.default(ctx);
    // Scenarios may allow expected errors by clearing ctx.errors themselves.
    if (errors.length) throw new Error(`browser errors: ${errors.join(" | ").slice(0, 500)}`);
    console.log(JSON.stringify({ scenario: file, ok: true, ms: Math.round(performance.now() - started) }));
  } catch (e) {
    failed++;
    const shot = join(process.env.UI_ARTIFACT_DIR || "/tmp", file.replace(".mjs", ".png"));
    try { await page.screenshot({ path: shot, fullPage: true }); } catch {}
    console.log(JSON.stringify({ scenario: file, ok: false, error: String(e).slice(0, 800), screenshot: shot }));
  }
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
