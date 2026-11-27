import { expect, test } from "@playwright/test";
import type { InstrumentQuote } from "../../src/lib/api/market-types";
import { signInStaging } from "./staging-helpers";

const fixture = "http://127.0.0.1:3102/__fixture";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

test("shows backend quotes and paper figures and keeps their failures independent", async ({ page, request }) => {
  await signInStaging(page);
  await expect(page.getByRole("heading", { name: "Trading overview" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Backend demo market indices" })).toContainText("23,123.45");
  await expect(page.getByText("₹25,064.00", { exact: true })).toBeVisible();
  await expect(page.getByText("100.0%", { exact: true })).toBeVisible();
  const recent = page.getByRole("region", { name: "Recent trades table" });
  await expect(recent.getByRole("rowheader", { name: "SBIN" })).toHaveCount(2);
  await expect(recent.getByText("+₹64.00")).toBeVisible();
  await expect(page.getByRole("group", { name: "Cumulative realised paper P&L chart" }).locator("canvas").first()).toBeVisible();
  await expect(page.getByText("Sample net equity")).toHaveCount(0);

  expect((await request.post(`${fixture}/market/unavailable`)).status()).toBe(204);
  await page.getByRole("button", { name: "Refresh dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Market snapshot could not load" })).toBeVisible();
  await expect(recent.getByText("+₹64.00")).toBeVisible();
  await expect(page.getByRole("region", { name: "Backend demo market indices" })).toHaveCount(0);

  expect((await request.post(`${fixture}/market/ready`)).status()).toBe(204);
  await page.getByRole("button", { name: "Retry market data" }).click();
  await expect(page.getByRole("region", { name: "Backend demo market indices" })).toBeVisible();
  expect((await request.post(`${fixture}/report/mismatch`)).status()).toBe(204);
  await page.getByRole("button", { name: "Refresh dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Paper ledger could not reconcile" })).toBeVisible();
  await expect(recent).toHaveCount(0);
  await expect(page.getByText("₹25,064.00", { exact: true })).toBeVisible();

  expect((await request.post(`${fixture}/report/unavailable`)).status()).toBe(204);
  await page.getByRole("button", { name: "Retry paper data" }).click();
  await expect(page.getByRole("heading", { name: "Paper ledger could not load" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Backend demo market indices" })).toBeVisible();

  expect((await request.post(`${fixture}/report/empty`)).status()).toBe(204);
  await page.getByRole("button", { name: "Retry paper data" }).click();
  await expect(page.getByRole("heading", { name: "No paper activity yet" })).toBeVisible();
  await expect(page.getByText("₹25,064.00", { exact: true })).toHaveCount(0);
  await expect(page.getByText("100.0%", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Backend demo market indices" })).toBeVisible();
});

test("uses the staged instrument catalog and handles candle state changes without samples", async ({ page, request }) => {
  await signInStaging(page, "/markets");
  await page.goto("/markets");
  await expect(page.getByText("Backend demo data", { exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: "Demo 15m candlestick chart" }).locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "View NIFTY 50 market overview" })).toContainText("23,123.45");
  await expect(page.getByRole("button", { name: "Chart demo data" })).toHaveCount(0);
  await page.getByRole("button", { name: "Find instrument" }).click();
  await page.getByRole("searchbox", { name: "Search instruments" }).fill("mahindra");
  await page.getByRole("button", { name: "Select M&M", exact: true }).click();
  await expect(page.getByRole("heading", { name: "M&M", exact: true })).toBeVisible();

  expect((await request.post(`${fixture}/market/stale`)).status()).toBe(204);
  await page.getByRole("button", { name: "1D", exact: true }).click();
  await expect(page.getByText("Showing stale demo candles.")).toBeVisible();
  expect((await request.post(`${fixture}/market/empty`)).status()).toBe(204);
  await page.getByRole("button", { name: "Load latest candles" }).click();
  await expect(page.getByText("No candles available")).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);

  expect((await request.post(`${fixture}/market/bad-candles`)).status()).toBe(204);
  await page.getByRole("button", { name: "Retry chart" }).click();
  await expect(page.getByText("Chart could not load")).toBeVisible();
  expect((await request.post(`${fixture}/market/ready`)).status()).toBe(204);
  await page.getByRole("button", { name: "Retry chart" }).click();
  await expect(page.getByRole("group", { name: "Demo 1D candlestick chart" }).locator("canvas").first()).toBeVisible();

  await page.getByRole("button", { name: "Add M&M to watchlist" }).first().click();
  await page.goto("/dashboard");
  await expect(page.getByRole("region", { name: "Watchlist" })).toContainText("M&M");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  expect((await request.post(`${fixture}/market/no-quotes`)).status()).toBe(204);
  await page.goto("/markets");
  await expect(page.getByRole("heading", { name: "No quotes available" })).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("refreshes market quotes and candles for the selected instrument and timeframe", async ({ page, request }) => {
  await signInStaging(page);
  let price = 503;
  await page.route("**/api/v1/market/overview", async (route) => {
    const response = await route.fetch();
    const overview = await response.json();
    const quotes = overview.quotes.map((quote: InstrumentQuote) => quote.instrumentId === "NSE:SBIN"
      ? { ...quote, price, high: Math.max(price, quote.high), change: price - quote.previousClose,
        changePercent: (price / quote.previousClose - 1) * 100 }
      : quote);
    await route.fulfill({ response, json: { ...overview, quotes, source: "market" } });
  });
  await page.route("**/api/v1/market/instruments/*/candles?*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), source: "market" } });
  });
  await page.goto("/markets");
  await page.getByRole("button", { name: "Find instrument" }).click();
  await page.getByRole("button", { name: "Select SBIN", exact: true }).click();
  await page.getByRole("button", { name: "5m", exact: true }).click();
  const chart = page.getByRole("region", { name: "SBIN", exact: true });
  await expect(chart.getByText("₹503.00", { exact: true })).toBeVisible();
  await expect(chart.getByRole("group", { name: "Market 5m candlestick chart" }).locator("canvas").first()).toBeVisible();

  price = 518;
  expect((await request.post(`${fixture}/market/stale`)).status()).toBe(204);
  await page.getByRole("button", { name: "Refresh market data" }).click();
  await expect(chart.getByText("₹518.00", { exact: true })).toBeVisible();
  await expect(chart.getByText("Showing stale market candles.")).toBeVisible();
  await expect(chart.getByRole("button", { name: "5m", exact: true })).toHaveAttribute("aria-pressed", "true");
});
