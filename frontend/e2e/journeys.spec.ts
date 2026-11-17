import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "e2e-token-0123456789";
let errors: string[] = [];

/** Open the app the way a user does: the token URL sets the cookie, then deep-link into a hash route. */
async function open(page: Page, hash = "/") {
  await page.goto(`/?token=${TOKEN}`);
  await page.goto(`/#${hash}`);
  await expect(page.locator("#main")).toBeVisible();
}

test.beforeEach(({ page }) => {
  errors = [];
  // Any console error (CSP violations included) or uncaught exception fails the journey.
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
});
test.afterEach(() => expect(errors, "console errors / CSP violations").toEqual([]));

test("1 · Today after several items were captured shows what happened and what needs me", async ({ page }) => {
  await open(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Good (morning|afternoon|evening)|Late night/);
  // The reel without a transcriber is a real "needs you" state, named in plain language.
  const needs = page.getByRole("region", { name: "Needs you" });
  await expect(needs).toContainText("pasta-reel.mp4");
  await expect(needs.getByRole("button", { name: "Try again" }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "New notes" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Capture sources" })).toContainText("Drop folder");
  await expect(page.getByLabel(/\d+ need you/).first()).toBeVisible();
});

test("2 · Inspect a waiting item and recover it by pasting the text", async ({ page }) => {
  await open(page, "/inbox?show=attention");
  await page.getByRole("button", { name: /blank-notes/ }).click();
  await expect(page.getByText("What happened")).toBeVisible();
  await page.getByRole("button", { name: "Paste text instead" }).click();
  await page
    .getByLabel("Text to use instead")
    .fill("Pasta trick: add a spoon of starchy pasta water to the sauce and toss for 30 seconds off the heat so it emulsifies.");
  await page.getByRole("button", { name: "Use this text" }).click();
  await expect(page.getByText("Queued with your text.")).toBeVisible();
  await page.getByRole("tab", { name: /Done/ }).click();
  await expect(page.getByRole("button", { name: /blank-notes/ })).toContainText("In library", { timeout: 30_000 });
});

test("2b · A problem pasted text cannot fix is named honestly, with no false remedy", async ({ page }) => {
  await open(page, "/inbox?show=attention");
  await page.getByRole("button", { name: /pasta-reel/ }).click();
  const card = page.getByText("Pith has no way to read this yet");
  await expect(card.first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Paste text instead" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Try again" }).first()).toBeVisible();
});

test("3 · Library is virtualized: many notes, few DOM rows, more load on scroll", async ({ page }) => {
  await open(page, "/library");
  await expect(page.getByTestId("note-row").first()).toBeVisible();
  const total = Number(
    (
      await page
        .getByText(/\d+ notes/)
        .first()
        .textContent()
    )?.match(/(\d+) notes/)?.[1],
  );
  expect(total).toBeGreaterThan(70);
  const initial = await page.getByTestId("note-row").count();
  expect(initial).toBeLessThan(total);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(page.getByText(/That is everything/)).toBeVisible({ timeout: 15_000 });
  expect(await page.getByTestId("note-row").count()).toBeLessThan(total); // still virtualized at the end
});

test("4 · Filter the library by type and topic, URL-backed", async ({ page }) => {
  await open(page, "/library");
  await page.getByRole("group", { name: "Filter by type" }).getByRole("button", { name: /Notes/ }).click();
  await expect(page).toHaveURL(/type=note/);
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page).not.toHaveURL(/type=/);
});

test("5 · Find an older note by search, read it, edit it and see the edit persist", async ({ page }) => {
  // The library is newest-first and long, so reach the older note the way a person would: search.
  await open(page, "/search?q=logical%20replication");
  await page.getByRole("region", { name: "Search results" }).getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Postgres logical replication");
  await expect(page.getByRole("complementary", { name: "About this note" })).toBeVisible();
  await expect(page.getByText("Why you saved this")).toBeVisible();
  await page.keyboard.press("e");
  const title = page.getByLabel("Title");
  await title.fill("Postgres logical replication (edited)");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Postgres logical replication (edited)");
  await expect(page.getByText("Edited by you")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Postgres logical replication (edited)"); // deep link survives reload
});

test("6 · Find a tool mentioned once, then open the whole note from the passage", async ({ page }) => {
  await open(page, "/search");
  await page.getByRole("searchbox").fill("pgbadger");
  const hit = page.getByRole("region", { name: "Search results" });
  await expect(hit.locator("mark.hit").first()).toHaveText(/pgbadger/i);
  await hit.getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page).toHaveURL(/#\/note\//);
});

test("7 · Ask a question: answer is visibly separate from search results, with sources", async ({ page }) => {
  await open(page, "/search?q=replica");
  await expect(page.getByRole("region", { name: "Search results" })).toBeVisible();
  await page.getByRole("button", { name: /Ask this question/ }).click();
  const answer = page.getByRole("region", { name: "Answer" });
  await expect(answer).toBeVisible();
  // No model is configured in the test backend, so the honest result is "no answer, here are passages".
  await expect(answer.getByText("No answer was written.")).toBeVisible({ timeout: 30_000 });
  await expect(answer.getByRole("list", { name: "Sources" })).toBeVisible();
});

test("8 · Keyboard only: go-to sequences, search focus, help, capture, escape", async ({ page }) => {
  await open(page);
  await page.keyboard.press("g");
  await page.keyboard.press("l");
  await expect(page).toHaveURL(/#\/library/);
  await page.keyboard.press("g");
  await page.keyboard.press("i");
  await expect(page).toHaveURL(/#\/inbox/);
  await page.keyboard.press("/");
  await expect(page).toHaveURL(/#\/search/);
  await expect(page.getByRole("searchbox")).toBeFocused();
  await page.keyboard.press("Escape"); // typing target: does not leave the page
  await page.locator("#main").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.keyboard.press("n");
  await expect(page.getByRole("dialog", { name: "Save something" })).toBeVisible();
  await expect(page.getByLabel("Link or text")).toBeFocused();
  await page.keyboard.press("Escape");
  // Library list: j/k move, x selects, Esc clears.
  await open(page, "/library");
  await expect(page.getByTestId("note-row").first()).toBeVisible();
  await page.keyboard.press("j");
  await page.keyboard.press("x");
  await expect(page.getByRole("toolbar", { name: "Bulk actions" })).toContainText("1 selected");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("toolbar", { name: "Bulk actions" })).toBeHidden();
});

test("9 · Settings: theme switch applies instantly; model settings load from the real config", async ({ page }) => {
  await open(page, "/settings");
  await page.getByLabel("Theme").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Theme").selectOption("system");
  await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
  await expect(page.getByText("What each job uses")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled(); // nothing changed
});

test("10 · Accessibility: no serious or critical axe violations on the main screens", async ({ page }) => {
  for (const hash of ["/", "/inbox", "/library", "/search?q=pgbadger", "/settings"]) {
    await open(page, hash);
    await page.waitForTimeout(400);
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(
      bad.map((v) => `${hash}: ${v.id} (${v.nodes.length})`),
      `axe on ${hash}`,
    ).toEqual([]);
  }
});

test("11 · @mobile narrow viewport: tab bar, no horizontal scroll, reader usable", async ({ page }) => {
  await open(page);
  await expect(page.getByRole("navigation", { name: "Primary" }).last()).toBeVisible();
  for (const [name, hash] of [
    ["Library", "/library"],
    ["Inbox", "/inbox"],
    ["Search", "/search"],
    ["Settings", "/settings"],
  ] as const) {
    await page
      .getByRole("navigation", { name: "Primary" })
      .last()
      .getByRole("link", { name: new RegExp(name) })
      .click();
    await expect(page).toHaveURL(new RegExp(`#${hash}`));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow on ${hash}`).toBeLessThanOrEqual(0);
  }
  await open(page, "/library");
  await page.getByTestId("note-row").first().getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});
