import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function openBrokers(page: Page) {
  await openDashboard(page);
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Brokers", exact: true }).click();
  await expect(page).toHaveURL(/\/brokers$/);
  await expect(page.getByRole("region", { name: "Zerodha" })).toBeVisible();
}

test("protects the route and supports the complete broker demo without API requests", async ({ page }) => {
  const nonPreviewRequests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) {
      nonPreviewRequests.push(url.href);
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/brokers");
  await expect(page).toHaveURL(/\/login$/);
  await openBrokers(page);
  await capture(page, "brokers-desktop");

  const fyers = page.getByRole("region", { name: "Fyers" });
  const reconnect = fyers.getByRole("button", { name: "Reconnect demo" });
  await reconnect.focus();
  await page.keyboard.press("Enter");
  const reconnectDialog = page.getByRole("dialog", { name: "Reconnect Fyers demo?" });
  await expect(reconnectDialog).toBeVisible();
  await expect(reconnectDialog.getByRole("textbox")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(reconnectDialog).toBeHidden();
  await expect(reconnect).toBeFocused();
  await reconnect.click();
  await reconnectDialog.getByRole("button", { name: "Reconnect demo account" }).click();
  await expect(fyers.getByText("Connected", { exact: true })).toBeVisible();
  await expect(fyers.getByRole("heading", { name: "Fyers" })).toBeFocused();
  await fyers.getByRole("button", { name: "Sync demo account" }).click();
  await expect(page.getByText("Fyers demo account synced")).toBeVisible();

  await fyers.getByRole("button", { name: "Disconnect" }).click();
  await page.getByRole("dialog", { name: "Disconnect Fyers demo?" }).getByRole("button", { name: "Disconnect demo account" }).click();
  await expect(fyers.getByText("Disconnected", { exact: true })).toBeVisible();
  await fyers.getByRole("button", { name: "Connect demo" }).click();
  const connectDialog = page.getByRole("dialog", { name: "Connect Fyers demo?" });
  await expect(connectDialog.getByRole("textbox")).toHaveCount(0);
  await connectDialog.getByRole("button", { name: "Connect demo account" }).click();
  await expect(fyers.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByText("Account disconnected", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(nonPreviewRequests).toEqual([]);
});

test("checks phone and tablet layouts and recovers from broker preview problems", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openBrokers(page);
  await capture(page, "brokers-mobile");

  async function assertNoOverflow() {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth));
  }

  await assertNoOverflow();
  await page.setViewportSize({ width: 768, height: 1024 });
  await assertNoOverflow();
  await capture(page, "brokers-tablet");

  const response = page.getByRole("combobox", { name: "Broker preview data" });
  await response.selectOption("stale");
  await expect(page.getByRole("button", { name: "Reconnect demo" })).toBeDisabled();
  await response.selectOption("denied");
  await expect(page.getByRole("heading", { name: "Broker access denied" })).toBeVisible();
  await response.selectOption("error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Brokers could not load");
  await page.getByRole("button", { name: "Retry broker data" }).click();
  await expect(page.getByRole("button", { name: "Reconnect demo" })).toBeEnabled();
});
