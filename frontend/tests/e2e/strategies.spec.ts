import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function openStrategies(page: Page) {
  await openDashboard(page);
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Strategies", exact: true }).click();
  await expect(page).toHaveURL(/\/strategies$/);
  await expect(page.getByRole("region", { name: "NIFTY Momentum" })).toBeVisible();
}

test("edits and activates demo drafts with version and eligibility checks", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) externalRequests.push(url.href);
  });

  await page.goto("/strategies");
  await expect(page).toHaveURL(/\/login$/);
  await openStrategies(page);
  await capture(page, "strategies-desktop");
  const theme = page.getByRole("button", { name: "Toggle color theme" });
  await theme.click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await capture(page, "strategies-desktop-light");
  await theme.click();
  await expect(page.locator("html")).toHaveClass(/dark/);

  const momentum = page.getByRole("button", { name: "View NIFTY Momentum" });
  await momentum.focus();
  await page.keyboard.press("Enter");
  const detail = page.getByRole("dialog", { name: "NIFTY Momentum" });
  await expect(detail.getByRole("heading", { name: "Version history" })).toBeVisible();
  await detail.getByText(/^Version 2/).click();
  await expect(detail.getByText("7.5%", { exact: true }).last()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(momentum).toBeFocused();
  await momentum.click();
  await detail.getByRole("button", { name: "Edit draft" }).click();
  const editor = page.getByRole("dialog", { name: "Edit strategy draft" });
  await expect(editor.getByLabel("Strategy name")).toBeFocused();
  await editor.getByLabel("Position size (%)").fill("8.25");
  await editor.getByRole("button", { name: "Save draft" }).click();
  await expect(detail.getByText("8.25%", { exact: true })).toBeVisible();
  await expect(detail.getByText("NIFTY Momentum · Version 2 remains unchanged.")).toBeVisible();
  await detail.getByRole("button", { name: "Pause demo" }).click();
  await expect(detail.getByRole("button", { name: "Activate demo" })).toBeDisabled();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "View HDFC Mean Reversion" }).click();
  const hdfc = page.getByRole("dialog", { name: "HDFC Mean Reversion" });
  await hdfc.getByRole("button", { name: "Activate demo" }).click();
  await expect(hdfc.getByText(/^Version 1/)).toBeVisible();
  await expect(hdfc.getByRole("button", { name: "Pause demo" })).toBeEnabled();
  expect(externalRequests).toEqual([]);
});

test("fits mobile and tablet and keeps filters, table and the draft editor usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStrategies(page);
  await capture(page, "strategies-mobile");

  async function expectNoPageOverflow() {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth));
  }

  await expectNoPageOverflow();
  await page.getByRole("searchbox", { name: "Search strategies" }).fill("sbin");
  await page.getByRole("combobox", { name: "Filter strategies by status" }).selectOption("draft");
  await page.getByRole("button", { name: "Table view" }).click();
  await expect(page.getByRole("rowheader", { name: "SBI Session Trend" })).toBeVisible();
  await expectNoPageOverflow();

  await page.getByRole("button", { name: "Create strategy" }).click();
  const editor = page.getByRole("dialog", { name: "Create strategy draft" });
  await editor.getByLabel("Strategy name").fill("Mobile sample draft");
  await editor.getByLabel("Instrument").selectOption("SBIN");
  await editor.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("rowheader", { name: "Mobile sample draft" })).toBeVisible();
  await page.setViewportSize({ width: 768, height: 1024 });
  await expectNoPageOverflow();
  await page.getByRole("button", { name: "Card view" }).click();
  await capture(page, "strategies-tablet");
});
