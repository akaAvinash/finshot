import { searchInstruments } from "@/lib/market/search";
import { demoInstruments, generateMarketCandles, getOverviewFixture, marketFixture, marketSnapshotDate } from "./market-fixture";
import type { MarketDataClient } from "./market-types";
import { waitForMock } from "./mock-delay";

export const marketChartScenarios = [
  { value: "ready", label: "Latest demo candles" },
  { value: "stale", label: "Stale candles" },
  { value: "empty", label: "Empty chart" },
  { value: "error", label: "Request error" },
] as const;

export type MarketChartScenario = (typeof marketChartScenarios)[number]["value"];

export function createMarketMock(scenario: MarketChartScenario = "ready"): MarketDataClient {
  return {
    async getInstruments({ query = "", signal } = {}) {
      await waitForMock(signal, 180);
      return { source: "demo", instruments: structuredClone(searchInstruments(demoInstruments, query)) };
    },
    async getMarketOverview({ signal } = {}) {
      await waitForMock(signal, 180);
      return getOverviewFixture();
    },
    async getMarketCandles(instrumentId, timeframe, { signal } = {}) {
      await waitForMock(signal, 360);
      if (scenario === "error") throw new Error("Simulated candle request failure");
      const instrument = marketFixture.find(({ id }) => id === instrumentId);
      if (!instrument) throw new Error("Unknown instrument");

      const stale = scenario === "stale";
      return {
        instrumentId,
        timeframe,
        source: "demo",
        asOf: marketSnapshotDate(stale),
        freshness: stale ? "stale" : "fresh",
        candles: scenario === "empty" ? [] : generateMarketCandles(instrument, timeframe, stale),
      };
    },
  };
}
