import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { capture, openDashboard } from "./preview-helpers";

async function openBacktesting(page: Page) {
  await openDashboard(page);
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Backtesting", exact: true }).click();
  await expect(page).toHaveURL(/\/backtesting$/);
  await expect(page.getByRole("heading", { name: "Demo backtest results" })).toBeVisible();
}

test("queues and exports a demo backtest without making backend requests", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) externalRequests.push(url.href);
  });

  await page.goto("/backtesting");
  await expect(page).toHaveURL(/\/login$/);
  await openBacktesting(page);
  await expect(page.getByRole("group", { name: "Demo equity curve" }).locator("canvas").first()).toBeVisible();
  await capture(page, "backtesting-desktop");
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await capture(page, "backtesting-desktop-light");

  await page.getByRole("combobox", { name: "Strategy revision" }).selectOption({ label: "BankNifty Range · v1" });
  await expect(page.getByRole("combobox", { name: "Instrument", exact: true })).toHaveValue("NSE:BANKNIFTY");
  await page.getByRole("combobox", { name: "Instrument", exact: true }).selectOption("NSE:RELIANCE");
  await page.getByLabel("Fees (bps)").fill("12");
  await page.getByRole("button", { name: "Run demo backtest" }).click();
  const queue = page.getByRole("region", { name: "Run queue" });
  await expect(queue.getByText("Queued", { exact: true })).toBeVisible();
  await expect(queue.getByRole("button", { name: /BankNifty Range.*Completed/ })).toBeVisible();
  await expect(page.getByText("BankNifty Range · v1 · RELIANCE", { exact: true })).toBeVisible();
  const drawdown = page.getByRole("button", { name: "Drawdown" });
  await drawdown.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("group", { name: "Demo drawdown chart" }).locator("canvas").first()).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("tradeo-demo-backtest-1.csv");
  const path = await file.path();
  expect(await readFile(path, "utf8")).toContain("DEMO,backtest-1,NSE:RELIANCE,");
  expect(externalRequests).toEqual([]);
});

test("fits 390px mobile and tablet, including the scrollable trade table", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openBacktesting(page);
  const table = page.getByRole("region", { name: "Simulated trades table" });
  await expect(table).toBeVisible();
  await capture(page, "backtesting-mobile");
  await table.focus();
  await expect(table).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, "backtesting-tablet");
  await page.getByRole("combobox", { name: "Backtest preview data" }).selectOption("stale");
  await expect(page.getByRole("button", { name: "Run demo backtest" })).toBeDisabled();
  await page.getByRole("button", { name: "Load latest backtest data" }).click();
  await expect(page.getByRole("button", { name: "Run demo backtest" })).toBeEnabled();
});
