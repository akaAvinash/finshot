// @vitest-environment node
import { describe, expect, it } from "vitest";
import { createTradeoClient } from "@/lib/api/client";
import { demoInstruments, generateMarketCandles, getOverviewFixture, marketFixture } from "@/lib/api/market-fixture";
import { marketTimeframes } from "@/lib/api/market-types";
import { searchInstruments } from "@/lib/market/search";
import { defaultWatchlist, parseWatchlist } from "@/lib/market/watchlist";

const reliance = marketFixture.find(({ symbol }) => symbol === "RELIANCE")!;

describe("instrument search", () => {
  it.each([
    ["nifty-50", "NIFTY 50"],
    ["bank nifty", "BANKNIFTY"],
    ["financial services", "FINNIFTY"],
    ["ril", "RELIANCE"],
    ["HDFC bank", "HDFCBANK"],
    ["state bank", "SBIN"],
    ["NSE:INFY", "INFY"],
  ])("matches %s to %s", (query, symbol) => {
    expect(searchInstruments(demoInstruments, query)[0]?.symbol).toBe(symbol);
  });

  it("shows the catalog for a blank query and no matches for unrelated text", () => {
    expect(searchInstruments(demoInstruments, " ")).toEqual(demoInstruments);
    expect(searchInstruments(demoInstruments, "!!!")).toEqual([]);
    expect(searchInstruments(demoInstruments, "not listed")).toEqual([]);
  });
});

describe("demo market data", () => {
  it("repeats the same minute bars and rolls them up consistently into five-minute and daily bars", () => {
    const minute = generateMarketCandles(reliance, "1m");
    const fiveMinutes = generateMarketCandles(reliance, "5m");
    const daily = generateMarketCandles(reliance, "1D");
    const latest = daily.at(-1)!;
    const quote = getOverviewFixture().quotes.find(({ instrumentId }) => instrumentId === reliance.id)!;

    expect(minute).toEqual(generateMarketCandles(reliance, "1m"));
    expect(minute).toHaveLength(375);
    expect(fiveMinutes).toHaveLength(75);
    expect(fiveMinutes[0]).toMatchObject({
      time: minute[0].time,
      open: minute[0].open,
      close: minute[4].close,
      high: Math.max(...minute.slice(0, 5).map(({ high }) => high)),
      low: Math.min(...minute.slice(0, 5).map(({ low }) => low)),
      volume: minute.slice(0, 5).reduce((sum, { volume }) => sum + volume!, 0),
    });
    expect(quote).toMatchObject({ open: latest.open, high: latest.high, low: latest.low, price: latest.close, volume: latest.volume });
    expect(quote.previousClose).toBe(daily.at(-2)?.close);
    expect(fiveMinutes.reduce((sum, { volume }) => sum + volume!, 0)).toBe(quote.volume);
  });

  it("returns ordered, realistic bars for all six timeframes without inventing index volume", () => {
    const index = marketFixture[0];

    for (const timeframe of marketTimeframes) {
      const candles = generateMarketCandles(index, timeframe);
      expect(candles.length).toBeGreaterThan(0);
      expect(candles.at(-1)?.close).toBe(index.close);
      expect(candles.every((bar, i) => (
        (i === 0 || bar.time > candles[i - 1].time)
        && bar.high >= Math.max(bar.open, bar.close)
        && bar.low <= Math.min(bar.open, bar.close)
        && bar.low > 0
        && bar.volume === null
      ))).toBe(true);
    }
  });

  it("serves typed search, stale and empty results, and supports cancellation", async () => {
    const client = createTradeoClient();
    const controller = new AbortController();
    const cancelled = client.getMarketCandles(reliance.id, "15m", { signal: controller.signal });
    controller.abort();
    await expect(cancelled).rejects.toHaveProperty("name", "AbortError");

    const [list, latest, stale, empty] = await Promise.all([
      client.getInstruments({ query: "ril" }),
      client.getMarketCandles(reliance.id, "15m"),
      createTradeoClient({ marketChartScenario: "stale" }).getMarketCandles(reliance.id, "15m"),
      createTradeoClient({ marketChartScenario: "empty" }).getMarketCandles(reliance.id, "15m"),
    ]);

    expect(list.instruments.map(({ id }) => id)).toEqual([reliance.id]);
    expect(latest).toMatchObject({ instrumentId: reliance.id, timeframe: "15m", freshness: "fresh", source: "demo" });
    expect(stale.freshness).toBe("stale");
    expect(stale.asOf < latest.asOf).toBe(true);
    expect(stale.candles.at(-1)?.close).toBe(reliance.previousClose);
    expect(empty.candles).toEqual([]);
  });

  it("rejects unknown instruments and simulated request failures", async () => {
    await Promise.all([
      expect(createTradeoClient().getMarketCandles("NSE:INVALID", "1D")).rejects.toThrow("Unknown instrument"),
      expect(createTradeoClient({ marketChartScenario: "error" }).getMarketCandles(reliance.id, "1D")).rejects.toThrow("Simulated candle request failure"),
    ]);
  });
});

describe("local watchlist parsing", () => {
  it("keeps explicitly empty lists and removes duplicates", () => {
    expect(parseWatchlist("[]")).toEqual([]);
    expect(parseWatchlist('["NSE:SBIN","NSE:SBIN","NSE:ITC"]')).toEqual(["NSE:SBIN", "NSE:ITC"]);
  });

  it("restores defaults for missing or malformed storage", () => {
    for (const input of [null, "garbage", "[123]", "{}"]) {
      expect(parseWatchlist(input)).toEqual(defaultWatchlist);
    }
  });
});
