import { expect, test } from "@playwright/test";
import { capture, openDashboard, requestCode } from "./preview-helpers";

test("protects routes and supports demo OTP validation, change number, and sign-out", async ({ page }) => {
  await page.goto("/strategies");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Preview sign-in" })).toBeVisible();
  await capture(page, "login-desktop-dark");

  await page.getByLabel("Mobile number").fill("1234567890");
  await page.getByRole("button", { name: "Get preview code" }).click();
  const formAlert = page.getByRole("main").getByRole("alert");
  await expect(formAlert).toContainText("Enter a valid 10-digit Indian mobile number");

  await requestCode(page);
  await page.getByRole("button", { name: "Change mobile number" }).click();
  await expect(page.getByLabel("Mobile number")).toHaveValue("98765 43210");

  await requestCode(page);
  await page.getByLabel("One-time code").fill("000000");
  await page.getByRole("button", { name: "Open dashboard" }).click();
  await expect(formAlert).toContainText("That code did not match");

  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Open dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Watchlist" })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("renders the chart and all placeholder routes, with persistent dark and light themes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openDashboard(page);
  await expect(page.locator("html")).toHaveClass(/dark/);
  await capture(page, "dashboard-desktop-dark");

  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/light/);
  await expect(page.locator("canvas").first()).toBeVisible();
  await capture(page, "dashboard-desktop-light");

  const nav = page.getByRole("navigation", { name: "Workspace" });
  for (const title of ["Backtesting", "Reports", "Agents", "Alerts", "Settings"]) {
    await nav.getByRole("link", { name: title, exact: true }).click();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(page.getByText("Placeholder", { exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: title, exact: true })).toHaveAttribute("aria-current", "page");
  }

  await page.getByRole("link", { name: "Open alerts" }).click();
  await expect(page).toHaveURL(/\/alerts$/);
  expect(errors).toEqual([]);
});

test("exercises stale, empty, and error preview responses and recovery", async ({ page }) => {
  await openDashboard(page);
  const preview = page.getByRole("button", { name: "Preview data" });
  const choose = async (scenario: string) => {
    await preview.click();
    const dialog = page.getByRole("dialog", { name: "Preview data" });
    await dialog.getByRole("radio", { name: scenario }).check();
    await dialog.getByRole("button", { name: "Apply preview" }).click();
  };

  await choose("Stale data");
  await expect(page.getByText("Showing an older sample snapshot.")).toBeVisible();
  await page.getByRole("button", { name: "Load latest sample" }).click();
  await expect(page.getByText("Sample data refreshed")).toBeVisible();

  await choose("Empty dashboard");
  await expect(page.getByRole("heading", { name: "No sample data" })).toBeVisible();

  await choose("Request error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Sample data could not load");
  await page.getByRole("button", { name: "Retry with sample data" }).click();
  await expect(page.getByRole("heading", { name: "Recent trades" })).toBeVisible();
});

test("fits phone and tablet widths and supports the compact navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);

  async function assertNoHorizontalPageOverflow() {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth));
  }

  await assertNoHorizontalPageOverflow();
  await capture(page, "dashboard-mobile-dark");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const navigation = page.getByRole("dialog", { name: "Workspace navigation" });
  await expect(navigation).toBeVisible();
  await navigation.getByRole("link", { name: "Markets" }).click();
  await expect(navigation).toBeHidden();
  await expect(page.getByRole("heading", { name: "Markets", exact: true })).toBeVisible();

  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Watchlist" })).toBeVisible();
  await assertNoHorizontalPageOverflow();
});
