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
  await response.selectOption("denied");
  await expect(page.getByRole("heading", { name: "Paper workspace access denied" })).toBeVisible();
  await response.selectOption("error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Paper workspace could not load");
  await page.getByRole("button", { name: "Retry paper data" }).click();
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();
});
