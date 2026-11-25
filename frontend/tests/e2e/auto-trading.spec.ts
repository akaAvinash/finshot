import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function openAutoTrading(page: Page) {
  await openDashboard(page);
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  if (await openNavigation.isVisible()) await openNavigation.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Auto Trading", exact: true }).click();
  await expect(page).toHaveURL(/\/auto-trading$/);
  await expect(page.getByRole("heading", { name: "Paper engine" })).toBeVisible();
}

test("protects the route and keeps the paper workflow local", async ({ page }) => {
  const apiRequests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/auto-trading");
  await expect(page).toHaveURL(/\/login$/);
  await openAutoTrading(page);
  await capture(page, "auto-trading-desktop");

  const strategy = page.getByRole("combobox", { name: "Assigned strategy" });
  await strategy.selectOption("bank-range");
  await expect(strategy).toHaveValue("bank-range");
  await page.getByRole("button", { name: "Start paper engine" }).click();
  await expect(page.getByRole("button", { name: "Pause paper engine" })).toBeVisible();

  const killSwitch = page.getByRole("button", { name: "Paper kill switch" });
  await killSwitch.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Halt paper trading?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Confirm paper halt" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(killSwitch).toBeFocused();

  await killSwitch.click();
  await dialog.getByRole("textbox", { name: "Type STOP to confirm" }).fill("STOP");
  await dialog.getByRole("button", { name: "Confirm paper halt" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeFocused();
  await expect(page.getByText("Cancelled", { exact: true })).toHaveCount(2);
  await page.getByRole("tab", { name: "Event log" }).click();
  await expect(page.getByText(/Cancelled 2 pending paper orders/)).toBeVisible();
  await page.getByRole("button", { name: "Clear paper halt" }).click();
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();

  expect(apiRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test("renders the responsive workspace and recovers from preview failures", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openAutoTrading(page);
  await capture(page, "auto-trading-mobile");

  async function expectNoOverflow() {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth));
  }

  await expectNoOverflow();
  await page.setViewportSize({ width: 768, height: 1024 });
  await expectNoOverflow();
  await capture(page, "auto-trading-tablet");

  const response = page.getByRole("combobox", { name: "Paper preview data" });
  await response.selectOption("stale");
  await expect(page.getByText("Paper data is stale. Controls are paused.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Paper kill switch" })).toBeDisabled();
  await expect(page.getByRole("spinbutton", { name: "Stop loss (%)" })).toBeDisabled();
  await response.selectOption("denied");
  await expect(page.getByRole("heading", { name: "Paper workspace access denied" })).toBeVisible();
  await response.selectOption("error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Paper workspace could not load");
  await page.getByRole("button", { name: "Retry paper data" }).click();
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();
});

test("saves daily and per-trade preview limits and explains entry blocks", async ({ page }) => {
  await openAutoTrading(page);
  const controls = page.getByRole("region", { name: "Trade controls" });
  const cap = controls.getByRole("spinbutton", { name: "Daily profit cap (₹)" });
  const confidence = controls.getByRole("spinbutton", { name: "Confidence needed after the profit cap" });
  const losses = controls.getByRole("spinbutton", { name: "Stop for the day after this many losses in a row" });
  const stop = controls.getByRole("spinbutton", { name: "Stop loss (%)" });
  const save = controls.getByRole("button", { name: "Save demo limits" });
  const start = page.getByRole("button", { name: "Start paper engine" });
  const saved = controls.getByText("Demo trade limits saved.");
  await expect(controls.getByText("+₹285.00")).toBeVisible();
  await expect(controls.getByText("₹580.00", { exact: true })).toBeVisible();
  await expect(confidence).toHaveValue("70");
  await expect(losses).toHaveValue("3");
  await capture(page, "trade-controls-desktop");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(controls.getByRole("heading", { name: "Per-trade risk controls" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await capture(page, "trade-controls-mobile");
  await stop.fill("0");
  await save.click();
  await expect(saved).toBeHidden();
  expect(await stop.evaluate((input: HTMLInputElement) => input.validity.rangeUnderflow)).toBe(true);

  await cap.fill("580");
  await confidence.fill("90");
  await stop.fill("2.5");
  await controls.getByRole("spinbutton", { name: "Take profit (%)" }).fill("3");
  await controls.getByRole("spinbutton", { name: "Max risk per trade (₹)" }).fill("100");
  await controls.getByRole("spinbutton", { name: "Max position size (%)" }).fill("5");
  await save.click();
  await expect(saved).toBeVisible();
  await expect(controls.getByText("Profit cap reached. A new entry needs at least 90% confidence.")).toBeVisible();
  await expect(controls.getByText(/Stop ₹177\.84 · Target ₹187\.88 · Max 21 units/)).toBeVisible();
  await expect(start).toBeDisabled();

  await confidence.fill("75");
  await losses.fill("1");
  await save.click();
  await expect(controls.getByText("Consecutive loss limit reached. New entries are paused for the day.")).toBeVisible();
  await expect(start).toBeDisabled();

  await losses.fill("0");
  await save.click();
  await expect(controls.getByText("Profit cap reached. The sample entry meets the 75% confidence requirement.")).toBeVisible();
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByRole("button", { name: "Pause paper engine" })).toBeEnabled();
  await expect(save).toBeDisabled();
});
