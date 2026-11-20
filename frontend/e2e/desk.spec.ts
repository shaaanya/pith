import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const headers = { "X-Token": "e2e-token-0123456789" };
async function getDesk(request: APIRequestContext) {
  return (await request.get("/api/desk", { headers })).json();
}
async function reset(request: APIRequestContext) {
  const desk = await getDesk(request);
  expect((await request.patch("/api/desk", { headers, data: { revision: desk.revision, groups: [] } })).ok()).toBeTruthy();
}
async function open(page: Page) {
  await page.goto("/?token=e2e-token-0123456789");
  await page.evaluate(() => localStorage.removeItem("pith.desk.view.v1"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your Working Desk" })).toBeVisible();
}
async function create(page: Page, name: string, query = "logical replication") {
  await page.getByRole("button", { name: "New group", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "New group", exact: true });
  await expect(editor.getByLabel("Group name")).toBeFocused();
  await editor.getByLabel("Group name").fill(name);
  await editor.getByLabel("Find items").fill(query);
  const checkbox =
    query === "logical replication"
      ? editor.locator(".desk-membership-list").getByRole("checkbox", { name: /Postgres logical replication, step by step/ })
      : editor
          .locator(".desk-membership-list")
          .getByRole("checkbox", { name: /sourdough/i })
          .first();
  await expect(checkbox).toBeVisible();
  await checkbox.check();
  await editor.getByRole("button", { name: "Save group" }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole("button", { name: new RegExp(name) }).first()).toBeVisible();
}
async function refresh(page: Page) {
  const response = page.waitForResponse((r) => r.url().endsWith("/api/desk") && r.request().method() === "GET");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    window.dispatchEvent(new Event("visibilitychange"));
    Reflect.deleteProperty(document, "visibilityState");
    window.dispatchEvent(new Event("visibilitychange"));
  });
  await response;
}
let errors: string[];
test.beforeEach(async ({ request, page }) => {
  errors = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("status of 409")) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  await reset(request);
});
test.afterEach(async ({ request }) => {
  await reset(request);
  expect(errors).toEqual([]);
});

test("V5 real groups persist, Focus and Undo work, reader closes to its opener", async ({ page, request }) => {
  await open(page);
  await create(page, "Database work");
  const saved = await getDesk(request);
  expect(saved.groups[0].item_ids).toHaveLength(1);
  expect(saved.groups[0].items[0].title).toContain("Postgres");
  await page.reload();
  const trigger = page.locator(".desk-group-trigger").filter({ hasText: "Database work" });
  await trigger.click();
  const row = page
    .locator(".desk-group")
    .filter({ hasText: "Database work" })
    .getByRole("button", { name: /Postgres/ });
  await row.click();
  const reader = page.getByRole("dialog", { name: "Saved knowledge" });
  await expect(reader.getByRole("heading", { level: 1 })).toContainText("Postgres");
  await expect(reader.getByText(/wal_level/).first()).toBeVisible();
  await expect(reader.getByRole("complementary", { name: "About this note" })).toBeVisible();
  await page.screenshot({ path: "test-results/v5-reader-desktop.png" });
  await reader.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Delete this note?" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Delete this note?" })).toHaveCount(0);
  await expect(reader).toBeVisible();
  const related = reader.getByRole("button", { name: /Kubernetes debugging cheatsheet/ });
  await expect(related).toBeVisible();
  const position = await reader.locator(".desk-reader-body").evaluate((el) => {
    el.scrollTop = 180;
    return el.scrollTop;
  });
  await related.click();
  await expect(reader.getByRole("heading", { level: 1 })).toHaveText("Kubernetes debugging cheatsheet");
  await reader.getByRole("button", { name: "Back", exact: true }).click();
  await expect(reader.getByRole("heading", { level: 1 })).toContainText("Postgres");
  await expect.poll(() => reader.locator(".desk-reader-body").evaluate((el) => el.scrollTop)).toBeGreaterThanOrEqual(position);
  await page.keyboard.press("Escape");
  await expect(reader).toHaveCount(0);
  await expect(row).toBeFocused();
  await page.getByRole("button", { name: "Options for Database work" }).click();
  await page.getByRole("button", { name: "Add to Focus" }).click();
  await page.getByRole("button", { name: /^Focus/ }).click();
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await page.reload();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Options for Database work" }).click();
  await page.getByRole("button", { name: "Remove group", exact: true }).click();
  await expect(trigger).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your Working Desk" })).toBeFocused();
  await page.getByRole("button", { name: "Undo last change" }).click();
  await expect(trigger).toBeVisible();
  const restored = await getDesk(request);
  expect(restored.groups[0].item_ids).toEqual(saved.groups[0].item_ids);
  expect((await request.get(`/api/items/${saved.groups[0].item_ids[0]}`, { headers })).ok()).toBeTruthy();
  await page.screenshot({ path: "test-results/v5-desk-desktop.png", fullPage: true });
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
    await page.screenshot({ path: `test-results/v5-desk-${width}.png`, fullPage: true });
  }
});

test("V5 mixed groups, independent expansion, arrange, editor preservation and live conflicts", async ({ page, request }) => {
  await open(page);
  await create(page, "Database work");
  await create(page, "Weekend plans", "sourdough");
  const first = page.locator(".desk-group-trigger").filter({ hasText: "Database work" });
  const second = page.locator(".desk-group-trigger").filter({ hasText: "Weekend plans" });
  await first.click();
  await second.click();
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await expect(second).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Arrange", exact: true }).click();
  await page.getByRole("button", { name: "Move Weekend plans up" }).click();
  await expect(page.locator(".desk-group-trigger").first()).toContainText("Weekend plans");
  await page.getByRole("button", { name: "Options for Database work" }).click();
  await page.getByRole("button", { name: "Edit group", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Edit group" });
  await expect(editor.getByLabel("Group name")).toBeFocused();
  await editor.getByLabel("Find items").fill("sourdough");
  await editor
    .locator(".desk-membership-list")
    .getByRole("checkbox", { name: /sourdough/i })
    .first()
    .check();
  await editor.getByRole("button", { name: "Save group" }).click();
  await expect(editor).toHaveCount(0);
  expect((await getDesk(request)).groups.find((g: { title: string }) => g.title === "Database work").item_ids).toHaveLength(2);
  // Another tab's revision is fetched while an old editor remains open: never rebase its snapshot silently.
  await page.getByRole("button", { name: "Options for Database work" }).click();
  await page.getByRole("button", { name: "Edit group", exact: true }).click();
  await editor.getByLabel("Group name").fill("My stale edit");
  const current = await getDesk(request);
  const external = {
    ...current,
    groups: current.groups.map(
      (g: { id: string; title: string; description: string; icon: string; focused: boolean; item_ids: string[] }) => ({
        id: g.id,
        title: `${g.title} external`,
        description: g.description,
        icon: g.icon,
        focused: g.focused,
        item_ids: g.item_ids,
      }),
    ),
  };
  expect((await request.patch("/api/desk", { headers, data: external })).ok()).toBeTruthy();
  await refresh(page);
  await editor.getByRole("button", { name: "Save group" }).click();
  await expect(editor.getByRole("alert")).toContainText("not been saved");
  expect((await getDesk(request)).groups[0].title).toContain("external");
  await editor.getByRole("button", { name: "Load latest desk" }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.locator(".desk-group-trigger").first()).toContainText("external");
});

test("V5 stale Undo cannot overwrite another tab after a background refetch", async ({ page, request }) => {
  await open(page);
  await create(page, "Database work");
  const current = await getDesk(request);
  await request.patch("/api/desk", {
    headers,
    data: {
      ...current,
      groups: current.groups.map((g: { id: string; description: string; icon: string; focused: boolean; item_ids: string[] }) => ({
        id: g.id,
        title: "Another tab",
        description: g.description,
        icon: g.icon,
        focused: g.focused,
        item_ids: g.item_ids,
      })),
    },
  });
  await refresh(page);
  await page.getByRole("button", { name: "Undo last change" }).click();
  await expect(page.getByRole("alert")).toContainText("not been saved");
  expect((await getDesk(request)).groups[0].title).toBe("Another tab");
});

test("V5 @mobile real desk, modal focus and light/dark accessibility", async ({ page }) => {
  await open(page);
  await create(page, "My saved context");
  const trigger = page.locator(".desk-group-trigger");
  await trigger.click();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(result.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
    await page.screenshot({ path: `test-results/v5-desk-mobile-${theme}.png`, fullPage: true });
  }
  await page
    .locator(".desk-group")
    .getByRole("button", { name: /Postgres/ })
    .click();
  const reader = page.getByRole("dialog", { name: "Saved knowledge" });
  await expect(reader.getByRole("heading", { level: 1 })).toContainText("Postgres");
  await page.keyboard.press("Tab");
  expect(await reader.evaluate((dialog) => dialog.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press("Escape");
  await expect(reader).toHaveCount(0);
});
