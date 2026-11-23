import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

function chart(page: Page, timeframe: string) {
  return page.getByRole("group", { name: `Demo ${timeframe} candlestick chart` });
}

async function openMarkets(page: Page) {
  await openDashboard(page);
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  if (await openNavigation.isVisible()) await openNavigation.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Markets", exact: true }).click();
  await expect(page).toHaveURL(/\/markets$/);
  await expect(page.getByRole("heading", { name: "Markets", exact: true })).toBeVisible();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();
}

async function chooseResponse(page: Page, name: string) {
  await page.getByRole("button", { name: "Chart demo data" }).click();
  const dialog = page.getByRole("dialog", { name: "Chart demo data" });
  await dialog.getByRole("radio", { name }).check();
  await dialog.getByRole("button", { name: "Apply chart response" }).click();
}

test("protects Markets and renders searchable instruments with all six candlestick timeframes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/login$/);
  await openMarkets(page);
  await expect(page.getByText("Demo data", { exact: true })).toBeVisible();
  await expect(page.getByText("Market closed", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Markets", exact: true })).toHaveAttribute("aria-current", "page");
  await capture(page, "markets-desktop-dark");

  await page.getByRole("button", { name: "Find instrument" }).click();
  const dialog = page.getByRole("dialog", { name: "Find an instrument" });
  await dialog.getByRole("searchbox").fill("State Bank");
  await dialog.getByRole("button", { name: "Select SBIN" }).click();
  await expect(page.getByRole("heading", { name: "SBIN", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Instrument details" })).toContainText("State Bank of India");

  for (const timeframe of ["1m", "5m", "15m", "30m", "1h", "1D"]) {
    const option = page.getByRole("group", { name: "Chart timeframe" }).getByRole("button", { name: timeframe, exact: true });
    await option.click();
    await expect(option).toHaveAttribute("aria-pressed", "true");
    await expect(chart(page, timeframe).locator("canvas").first()).toBeVisible();
  }

  const candles = chart(page, "1D").locator("canvas");
  const canvasImage = () => candles.evaluateAll((elements) => elements.map((element) => (element as HTMLCanvasElement).toDataURL()));
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const darkCanvas = await canvasImage();
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await expect.poll(canvasImage).not.toEqual(darkCanvas);
  await capture(page, "markets-desktop-light");
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Trading overview" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("adds, filters, selects, persists and removes watchlist entries", async ({ page }) => {
  await openMarkets(page);
  await page.getByRole("button", { name: "Add instrument", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Find an instrument" });
  await dialog.getByRole("searchbox").fill("finnifty");
  await dialog.getByRole("button", { name: "Add FINNIFTY to watchlist" }).click();
  await dialog.getByRole("button", { name: "Close dialog" }).click();

  const watchlist = page.getByRole("region", { name: /^Watchlist/ });
  await watchlist.getByRole("searchbox").fill("fin");
  await expect(watchlist.getByRole("button", { name: "View HDFCBANK from watchlist" })).toHaveCount(0);
  await watchlist.getByRole("button", { name: "View FINNIFTY from watchlist" }).click();
  await expect(page.getByRole("heading", { name: "FINNIFTY", exact: true })).toBeVisible();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();

  await page.reload();
  await expect(watchlist.getByRole("button", { name: "View FINNIFTY from watchlist" })).toBeVisible();
  await watchlist.getByRole("button", { name: "Remove FINNIFTY from watchlist" }).click();
  await expect(watchlist.getByRole("button", { name: "View FINNIFTY from watchlist" })).toHaveCount(0);
  await page.reload();
  await expect(watchlist.getByRole("button", { name: "View NIFTY 50 from watchlist" })).toBeVisible();
  await expect(watchlist.getByRole("button", { name: "View FINNIFTY from watchlist" })).toHaveCount(0);
});

test("displays loading, stale, empty and error chart states and recovers", async ({ page }) => {
  await openMarkets(page);
  await chooseResponse(page, "Stale candles");
  await expect(page.getByRole("status", { name: "Loading chart" })).toBeVisible();
  await expect(page.getByText("Showing stale demo candles.")).toBeVisible();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Load latest candles" }).click();
  await expect(page.getByText("Showing stale demo candles.")).toHaveCount(0);

  await chooseResponse(page, "Empty chart");
  await expect(page.getByText("No candles available")).toBeVisible();
  await expect(chart(page, "15m")).toHaveCount(0);
  await page.getByRole("button", { name: "Load demo candles" }).click();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();

  await chooseResponse(page, "Request error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Chart could not load");
  await page.getByRole("button", { name: "Retry chart" }).click();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();
});

test("fits compact phone and tablet layouts and keeps Markets controls usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openMarkets(page);
  await capture(page, "markets-mobile-dark");

  async function assertNoOverflow() {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth));
  }

  await assertNoOverflow();
  await page.getByRole("button", { name: "Find instrument" }).click();
  const dialog = page.getByRole("dialog", { name: "Find an instrument" });
  await dialog.getByRole("searchbox").fill("hdfc");
  await dialog.getByRole("button", { name: "Select HDFCBANK" }).click();
  await expect(page.getByRole("heading", { name: "HDFCBANK", exact: true })).toBeVisible();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();

  await page.setViewportSize({ width: 320, height: 700 });
  await assertNoOverflow();

  await page.setViewportSize({ width: 820, height: 1180 });
  await assertNoOverflow();
  await expect(page.getByRole("region", { name: /^Watchlist/ })).toBeVisible();
  await page.getByRole("button", { name: "View RELIANCE from watchlist" }).click();
  await expect(page.getByRole("heading", { name: "RELIANCE", exact: true })).toBeVisible();
  await expect(chart(page, "15m").locator("canvas").first()).toBeVisible();
});
