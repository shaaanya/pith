/** Check existing engines with the installed Playwright runtime that owns their revisions. */
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
const require = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);
const pw = require("playwright");
const version = require("playwright/package.json").version;
const evidence = fileURLToPath(new URL("./evidence/", import.meta.url));
await mkdir(evidence, { recursive: true });
const results = [];
for (const name of ["firefox", "webkit"]) {
  const result = {
    engine: name,
    runtime: version,
    executable: pw[name].executablePath(),
    checks: [],
    errors: [],
  };
  results.push(result);
  let browser;
  try {
    browser = await pw[name].launch({ headless: true });
    result.browserVersion = browser.version();
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [],
      forbidden = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("request", (r) => {
      const u = new URL(r.url());
      if (
        !["localhost", "127.0.0.1"].includes(u.hostname) ||
        u.pathname.startsWith("/api")
      )
        forbidden.push(r.url());
    });
    await page.goto("http://127.0.0.1:5175/");
    const group = (id) => page.locator(`[data-group-id="${id}"]`);
    const tools = group("tools").getByRole("button", {
      name: /^Tools to Check Out/,
    });
    await tools.focus();
    await page.keyboard.press("Enter");
    await group("systems")
      .getByRole("button", { name: /^SQL & Systems/ })
      .click();
    assert.equal(await tools.getAttribute("aria-expanded"), "true");
    assert.equal(
      await group("systems")
        .getByRole("button", { name: /^SQL & Systems/ })
        .getAttribute("aria-expanded"),
      "true",
    );
    const opener = group("tools").getByRole("button", { name: /^ripgrep-all/ });
    await opener.click();
    const title = page.getByRole("dialog").getByRole("heading", { level: 2 });
    await title.waitFor();
    assert(await title.evaluate((el) => el === document.activeElement));
    await page.keyboard.press("Tab");
    assert(
      await page.evaluate(() => !!document.activeElement.closest("dialog")),
    );
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await page.waitForFunction(() =>
      document.activeElement?.classList.contains("item-row"),
    );
    assert(await opener.evaluate((el) => el === document.activeElement));
    await page.reload();
    assert.equal(await tools.getAttribute("aria-expanded"), "true");
    result.checks.push(
      "Independent disclosures, native reader focus/Tab/Escape, explicit opener return, reload persistence",
    );
    await group("reading")
      .getByRole("button", { name: /^A Longer Reading Thread/ })
      .click();
    for (let i = 0; i < 5; i++)
      await group("reading")
        .getByRole("button", { name: "Show 10 more" })
        .click();
    await page.evaluate(() => window.scrollTo(0, 450));
    const reading = group("reading").locator(".item-row").nth(7);
    await reading.click();
    const before = await page.evaluate(() => window.scrollY);
    assert(before > 100);
    await page.mouse.move(4, 200);
    await page.mouse.wheel(0, 1200);
    await page.getByRole("dialog").getByRole("heading", { level: 2 }).focus();
    await page.keyboard.press("PageDown");
    await page
      .locator(".reader-content")
      .evaluate((el) => (el.scrollTop = el.scrollHeight));
    await page.mouse.move(700, 650);
    await page.mouse.wheel(0, 1200);
    await page.screenshot({
      animations: "disabled",
      path: `${evidence}${name}-scrolled-reader.png`,
    });
    assert.equal(
      await page.evaluate(() => window.scrollY),
      before,
      "Background must stay at its nonzero scroll position",
    );
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });
    assert.equal(await page.evaluate(() => window.scrollY), before);
    result.checks.push(
      "Nonzero desktop background scroll retained through backdrop wheel, PageDown, reader end and dismissal",
    );
    await page.setViewportSize({ width: 375, height: 812 });
    await page.evaluate(() => window.scrollTo(0, 0));
    const menu = page.getByRole("button", { name: "Open navigation" });
    await menu.click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Search", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await page.waitForFunction(
      () => document.activeElement?.getAttribute("type") === "search",
    );
    assert(
      await page
        .getByRole("searchbox", { name: "Search example knowledge" })
        .evaluate((el) => el === document.activeElement),
    );
    await menu.click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Prototype settings", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("heading", { name: "Prototype settings" })
      .waitFor();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Close", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await page.waitForFunction(
      () => document.activeElement?.id === "navigation-toggle",
    );
    result.checks.push(
      "Phone navigation closes before Search focus or Settings, returns focus to menu",
    );
    await menu.click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Your desk", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await opener.click();
    const bounds = await page.getByRole("dialog").boundingBox();
    assert(bounds.y >= 0 && bounds.y + bounds.height <= 813);
    assert(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    );
    await page.screenshot({
      animations: "disabled",
      path: `${evidence}${name}-phone-reader.png`,
    });
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(
      await tools
        .locator(".disclosure")
        .evaluate((el) => getComputedStyle(el).transitionDuration),
      "0s",
    );
    await opener.click();
    const box = await page.getByRole("dialog").boundingBox();
    await page.mouse.move(box.x + 50, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(4, 4);
    await page.mouse.up();
    assert(await page.getByRole("dialog").isVisible());
    await page.mouse.click(4, 4);
    await page.getByRole("dialog").waitFor({ state: "detached" });
    result.checks.push(
      "Phone reader bounds/reflow, reduced motion, selection release preserves modal, intentional backdrop click closes",
    );
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 900 });
      await page
        .getByRole("button", { name: "New group", exact: true })
        .click();
      const body = page.locator(".editor-body"),
        list = page.locator(".membership-list");
      await body.evaluate((el) => (el.scrollTop = el.scrollHeight));
      await list.evaluate((el) => (el.scrollTop = 0));
      const box = await list.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(0, 220);
      await page.waitForFunction(
        () => document.querySelector(".membership-list").scrollTop > 100,
      );
      const y = await page.evaluate(() => window.scrollY);
      await list.evaluate((el) => (el.scrollTop = el.scrollHeight));
      await page.mouse.wheel(0, 900);
      await page.screenshot({
        animations: "disabled",
        path: `${evidence}${name}-picker-${width}.png`,
      });
      assert.equal(await page.evaluate(() => window.scrollY), y);
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Close", exact: true })
        .click();
      await page.getByRole("dialog").waitFor({ state: "detached" });
    }
    result.checks.push(
      "Nested membership picker scrolls at desktop/phone editor edges without moving the background",
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(forbidden, []);
    result.checks.push(
      "No console/page errors, external assets or API requests",
    );
    result.status = "passed";
  } catch (error) {
    result.status = "failed";
    result.errors.push(error.stack ?? String(error));
    process.exitCode = 1;
  } finally {
    await browser?.close();
  }
  console.log(`${name}: ${result.status} (${result.checks.length} checks)`);
}
await writeFile(
  `${evidence}cross-browser.json`,
  JSON.stringify({ checkedAt: new Date().toISOString(), results }, null, 2),
);
