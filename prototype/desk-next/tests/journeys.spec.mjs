import {
  test,
  expect,
} from "../../../frontend/node_modules/@playwright/test/index.mjs";
import AxeBuilder from "../../../frontend/node_modules/@axe-core/playwright/dist/index.mjs";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const evidence = fileURLToPath(new URL("../evidence/", import.meta.url));
const key = "pith.prototype.desk-next.v1";
const group = (page, id) => page.locator(`[data-group-id="${id}"]`);
const tools = (page) =>
  group(page, "tools").getByRole("button", { name: /^Tools to Check Out/ });
const close = (page) =>
  page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
async function settings(page) {
  await page
    .getByRole("button", { name: "Example collection & appearance" })
    .click();
}
async function dataset(page, name) {
  await settings(page);
  await page
    .getByRole("dialog")
    .getByRole("radio", { name: new RegExp("^" + name) })
    .check();
  await close(page);
}
async function openRga(page) {
  await tools(page).click();
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
}
test.beforeEach(async ({ page }) => {
  const errors = [],
    forbidden = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("request", (request) => {
    const u = new URL(request.url());
    if (
      u.pathname.startsWith("/api") ||
      !["127.0.0.1", "localhost"].includes(u.hostname)
    )
      forbidden.push(request.url());
  });
  page.__audit = { errors, forbidden };
  await page.addInitScript(() => {
    for (const k of ["pith.theme", "pith.lastVisit", "pith.mind.v1"])
      if (localStorage.getItem(k) === null)
        localStorage.setItem(k, "production-sentinel");
  });
  await page.goto("/");
});
test.afterEach(async ({ page }) => {
  expect(page.__audit.errors, "console/page errors").toEqual([]);
  expect(page.__audit.forbidden, "no external assets or API requests").toEqual(
    [],
  );
  if (!page.__blockedStorage)
    expect(
      await page.evaluate(() =>
        ["pith.theme", "pith.lastVisit", "pith.mind.v1"].map((k) =>
          localStorage.getItem(k),
        ),
      ),
    ).toEqual([
      "production-sentinel",
      "production-sentinel",
      "production-sentinel",
    ]);
});

test("@cross-browser two independent disclosures, full reader, Escape and focus return", async ({
  page,
}) => {
  const order = await page
    .locator("[data-group-id]")
    .evaluateAll((els) => els.map((e) => e.dataset.groupId));
  await tools(page).focus();
  await page.keyboard.press("Enter");
  await group(page, "systems")
    .getByRole("button", { name: /^SQL & Systems/ })
    .click();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
  await expect(
    group(page, "systems").getByRole("button", { name: /^SQL & Systems/ }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("[data-group-id]")).toHaveCount(order.length);
  expect(
    await page
      .locator("[data-group-id]")
      .evaluateAll((els) => els.map((e) => e.dataset.groupId)),
  ).toEqual(order);
  const opener = group(page, "tools").getByRole("button", {
    name: /^ripgrep-all/,
  });
  await opener.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { level: 2 })).toBeFocused();
  await expect(
    dialog.getByText("A useful distinction", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Tab");
  expect(
    await page.evaluate(() => !!document.activeElement.closest("dialog")),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
  await page.reload();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
});

test("Focus is a chosen subset, with its own expansion state", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Focus", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Choose what stays close" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Go to Overview" }).click();
  await tools(page).click();
  await page
    .getByRole("button", { name: "Options for Tools to Check Out" })
    .click();
  await page.getByRole("button", { name: "Add to Focus", exact: true }).click();
  await close(page);
  await page.getByRole("button", { name: "Focus 1", exact: true }).click();
  await expect(page.locator("[data-group-id]")).toHaveCount(1);
  await expect(tools(page)).toHaveAttribute("aria-expanded", "false");
  await tools(page).click();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
  await page.reload();
  await page.getByRole("button", { name: "Focus 1", exact: true }).click();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
});

test("create a mixed group, edit membership, remove and Undo without deleting knowledge", async ({
  page,
}) => {
  await page.getByRole("button", { name: "New group", exact: true }).click();
  await page.getByLabel("Group name", { exact: true }).fill("A Sunday thread");
  await page.getByLabel(/A little context/).fill("A tool, a film, a thought");
  await page.getByRole("checkbox", { name: /^ripgrep-all/ }).check();
  await page.getByRole("checkbox", { name: /^Five films/ }).check();
  await page.getByRole("button", { name: "Save group", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: /^A Sunday thread/ }).click();
  const g = page
    .locator(".group-card")
    .filter({ has: page.getByRole("button", { name: /^A Sunday thread/ }) });
  await expect(g.locator(".item-row")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Options for A Sunday thread" })
    .click();
  await page.getByRole("button", { name: "Edit name & items" }).click();
  await expect(page.getByLabel("Group name", { exact: true })).toBeFocused();
  await page.getByRole("checkbox", { name: /^ripgrep-all/ }).uncheck();
  await page.getByRole("button", { name: "Save group", exact: true }).click();
  await expect(g.locator(".item-row")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Options for A Sunday thread" })
    .click();
  await page
    .getByRole("button", { name: "Remove group · keep its items" })
    .click();
  await expect(
    page.getByRole("button", { name: /^A Sunday thread/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^A Sunday thread/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "All knowledge", exact: true })
    .click();
  await page
    .getByRole("searchbox", { name: "Search example knowledge" })
    .fill("ripgrep-all");
  await expect(page.locator(".item-row")).toHaveCount(1);
});

test("Arrange preserves order on reload and Undo preserves unrelated appearance", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Arrange", exact: true }).click();
  await page
    .getByRole("button", { name: "Move Tools to Check Out up", exact: true })
    .click();
  await expect(page.locator("[data-group-id]").first()).toHaveAttribute(
    "data-group-id",
    "tools",
  );
  await expect(tools(page)).toBeFocused();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator("[data-group-id]").first()).toHaveAttribute(
    "data-group-id",
    "systems",
  );
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .getByRole("button", { name: "Move Tools to Check Out up", exact: true })
    .click();
  await page.reload();
  await expect(page.locator("[data-group-id]").first()).toHaveAttribute(
    "data-group-id",
    "tools",
  );
});

test("compact lists reveal real remaining rows without another destination", async ({
  page,
}) => {
  await tools(page).click();
  await expect(group(page, "tools").locator(".item-row")).toHaveCount(5);
  await group(page, "tools")
    .getByRole("button", { name: "Show remaining 1 item" })
    .click();
  await expect(group(page, "tools").locator(".item-row")).toHaveCount(6);
  await group(page, "tools")
    .getByRole("button", { name: "Show fewer" })
    .click();
  await expect(group(page, "tools").locator(".item-row")).toHaveCount(5);
  await group(page, "reading")
    .getByRole("button", { name: /^A Longer Reading Thread/ })
    .click();
  await group(page, "reading")
    .getByRole("button", { name: "Show 10 more" })
    .click();
  await expect(group(page, "reading").locator(".item-row")).toHaveCount(15);
});

test("related reading keeps one modal and restores reading scroll", async ({
  page,
}) => {
  await openRga(page);
  await page
    .locator(".reader-content")
    .evaluate((el) => (el.scrollTop = el.scrollHeight));
  const before = await page
    .locator(".reader-content")
    .evaluate((el) => el.scrollTop);
  await page
    .getByRole("button", { name: /SQLite WAL and shared storage/ })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.getByRole("button", { name: "Back to previous item" }).click();
  await expect(
    page.getByRole("heading", {
      name: "ripgrep-all: search inside documents",
      exact: true,
    }),
  ).toBeVisible();
  expect(
    await page.locator(".reader-content").evaluate((el) => el.scrollTop),
  ).toBeGreaterThanOrEqual(before - 2);
});

test("copy failure is honest and loading/error examples recover", async ({
  page,
}) => {
  await openRga(page);
  await page.evaluate(() => {
    navigator.clipboard.writeText = async () => {
      throw new Error("denied");
    };
  });
  await page.getByRole("button", { name: "Copy command", exact: true }).click();
  await expect(
    page.getByText("Copy was blocked by your browser.", { exact: false }),
  ).toBeVisible();
  await close(page);
  await settings(page);
  await page.getByRole("radio", { name: "Error", exact: true }).check();
  await close(page);
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByText("A useful distinction", { exact: true }),
  ).toBeVisible();
  await close(page);
  await settings(page);
  await page.getByRole("radio", { name: "Loading", exact: true }).check();
  await close(page);
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  await expect(
    page.getByText("Opening saved knowledge…", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Finish sample load" }).click();
  await expect(
    page.getByText("A useful distinction", { exact: true }),
  ).toBeVisible();
});

test("@cross-browser modal bounds, backdrop scroll and narrow navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openRga(page);
  const y = await page.evaluate(() => window.scrollY);
  await page
    .locator(".reader-content")
    .evaluate((el) => (el.scrollTop = el.scrollHeight));
  await page.mouse.move(200, 350);
  await page.mouse.wheel(0, 900);
  expect(await page.evaluate(() => window.scrollY)).toBe(y);
  const box = await page.getByRole("dialog").boundingBox();
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(813);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "All knowledge", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "All knowledge", exact: true }),
  ).toBeVisible();
});

test("empty, sparse and rich across widths and themes: overflow, axe and screenshots", async ({
  page,
}) => {
  test.setTimeout(120000);
  await mkdir(evidence, { recursive: true });
  for (const [name, id] of [
    ["Empty", "empty"],
    ["A few saved things", "sparse"],
    ["A larger library", "rich"],
  ]) {
    await dataset(page, name);
    for (const theme of ["light", "dark"]) {
      await settings(page);
      await page
        .getByRole("radio", {
          name: theme === "light" ? "Light" : "Dark",
          exact: true,
        })
        .check();
      await close(page);
      for (const width of [320, 375, 768, 1280, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        expect(
          await page.evaluate(
            () =>
              document.documentElement.scrollWidth <=
              document.documentElement.clientWidth,
          ),
          `${id}/${theme}/${width} page overflow`,
        ).toBe(true);
        await page.screenshot({
          animations: "disabled",
          path: `${evidence}${id}-${theme}-${width}.png`,
          fullPage: true,
        });
      }
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(
        results.violations.filter((v) =>
          ["serious", "critical"].includes(v.impact),
        ),
        `${id}/${theme} axe`,
      ).toEqual([]);
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await tools(page).click();
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}expanded-desktop.png`,
    fullPage: true,
  });
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  const axe = await new AxeBuilder({ page }).analyze();
  expect(
    axe.violations.filter((v) => ["serious", "critical"].includes(v.impact)),
  ).toEqual([]);
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}reader-desktop.png`,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}reader-phone.png`,
  });
});

test("@cross-browser reduced motion, text scaling and backdrop dismissal", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await tools(page).click();
  expect(
    await tools(page)
      .locator(".disclosure")
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  const dialog = page.getByRole("dialog");
  const box = await dialog.boundingBox();
  await page.mouse.move(box.x + 50, box.y + 100);
  await page.mouse.down();
  await page.mouse.move(4, 4);
  await page.mouse.up();
  await expect(dialog).toBeVisible();
  await page.mouse.click(4, 4);
  await expect(dialog).toHaveCount(0);
  await page.setViewportSize({ width: 640, height: 900 });
  await page.evaluate(() => (document.documentElement.style.fontSize = "200%"));
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test("Undo remains available after the announcement expires", async ({
  page,
}) => {
  await page.clock.install();
  await page
    .getByRole("button", { name: "Options for Tools to Check Out" })
    .click();
  await page
    .getByRole("button", { name: "Remove group · keep its items" })
    .click();
  await page.clock.fastForward(7000);
  await expect(
    page.getByRole("button", { name: "Undo", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(tools(page)).toBeVisible();
});

test("mobile Search and Settings return focus to a reachable control", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const menu = page.getByRole("button", { name: "Open navigation" });
  await page.evaluate(() => window.scrollTo(0, 300));
  await menu.click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Search", exact: true })
    .click();
  await expect(
    page.getByRole("searchbox", { name: "Search example knowledge" }),
  ).toBeFocused();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await menu.click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Prototype settings", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("heading", { name: "Prototype settings" }),
  ).toBeFocused();
  await close(page);
  await expect(menu).toBeFocused();
});

test("scrolled desktop stays put behind the reader through wheel and PageDown", async ({
  page,
}) => {
  await group(page, "reading")
    .getByRole("button", { name: /^A Longer Reading Thread/ })
    .click();
  for (let i = 0; i < 5; i++)
    await group(page, "reading")
      .getByRole("button", { name: "Show 10 more" })
      .click();
  await page.evaluate(() => window.scrollTo(0, 450));
  const opener = group(page, "reading").locator(".item-row").nth(7);
  await opener.click();
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(100);
  await page.mouse.move(4, 200);
  await page.mouse.wheel(0, 1200);
  await page.getByRole("dialog").getByRole("heading", { level: 2 }).focus();
  await page.keyboard.press("PageDown");
  await page
    .locator(".reader-content")
    .evaluate((el) => (el.scrollTop = el.scrollHeight));
  await page.mouse.move(700, 650);
  await page.mouse.wheel(0, 1200);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(before);
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  expect(await page.evaluate(() => window.scrollY)).toBe(before);
});

test("malformed and blocked local storage recover without touching production keys", async ({
  page,
}) => {
  await page.evaluate((k) => localStorage.setItem(k, "{invalid"), key);
  await page.reload();
  await expect(tools(page)).toBeVisible();
  await page.addInitScript((k) => {
    const get = Storage.prototype.getItem,
      set = Storage.prototype.setItem;
    Storage.prototype.getItem = function (name) {
      if (name === k) throw new DOMException("Blocked", "SecurityError");
      return get.call(this, name);
    };
    Storage.prototype.setItem = function (name, value) {
      if (name === k) throw new DOMException("Blocked", "SecurityError");
      return set.call(this, name, value);
    };
  }, key);
  await page.reload();
  await expect(page.getByText(/Browser storage is unavailable/)).toBeVisible();
  await tools(page).click();
  await expect(tools(page)).toHaveAttribute("aria-expanded", "true");
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  await expect(
    page.getByText("A useful distinction", { exact: true }),
  ).toBeVisible();
});

test("mixed knowledge stays complete, with honest evidence and missing content", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "All knowledge", exact: true })
    .click();
  const search = page.getByRole("searchbox", {
    name: "Search example knowledge",
  });
  for (const [query, section] of [
    ["Reading a query plan", "What this note does not cover"],
    ["Five films", "A note about availability"],
    ["A walk without headphones", "My note"],
    ["A saved talk", "A possible next step"],
    ["A thought about keeping", "Keep the door, not the whole room"],
  ]) {
    await search.fill(query);
    await page.locator(".item-row").first().click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: section, exact: true }),
    ).toBeVisible();
    if (query === "Five films")
      await expect(dialog.locator(".knowledge li")).toHaveCount(5);
    if (query === "A walk without headphones") {
      await expect(
        dialog.getByText("Edited by you", { exact: true }),
      ).toBeVisible();
      await expect(
        dialog.getByText(/no extracted source passages/),
      ).toBeVisible();
    }
    if (query === "A saved talk")
      await expect(
        dialog.getByText(/No transcript was available/),
      ).toBeVisible();
    await close(page);
    await expect(search).not.toBeFocused();
  }
});

test("review captures show the calm collapsed baseline and both disclosure levels", async ({
  page,
}) => {
  await mkdir(evidence, { recursive: true });
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}review-collapsed-desktop.png`,
    fullPage: true,
  });
  await tools(page).click();
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}review-expanded-desktop.png`,
    fullPage: true,
  });
  await group(page, "tools")
    .getByRole("button", { name: /^ripgrep-all/ })
    .click();
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}review-reader-desktop.png`,
  });
  await close(page);
  await tools(page).click();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({
    animations: "disabled",
    path: `${evidence}review-collapsed-phone.png`,
    fullPage: true,
  });
});

test("nested membership picker scrolls on desktop and at the phone editor edge", async ({
  page,
}) => {
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("button", { name: "New group", exact: true }).click();
    const body = page.locator(".editor-body"),
      list = page.locator(".membership-list");
    await body.evaluate((el) => (el.scrollTop = el.scrollHeight));
    await list.evaluate((el) => (el.scrollTop = 0));
    const box = await list.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 220);
    await expect
      .poll(() => list.evaluate((el) => el.scrollTop))
      .toBeGreaterThan(100);
    const y = await page.evaluate(() => window.scrollY);
    await list.evaluate((el) => (el.scrollTop = el.scrollHeight));
    await page.mouse.wheel(0, 900);
    expect(await page.evaluate(() => window.scrollY)).toBe(y);
    await close(page);
  }
});
