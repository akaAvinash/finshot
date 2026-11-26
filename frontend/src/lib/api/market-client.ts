import { createMarketMock, type MarketChartScenario } from "./market-mock";
import type { Instrument, InstrumentQuote, MarketCandle, MarketCandles, MarketDataClient, MarketOverview } from "./market-types";

export type MarketMode = "preview" | "staging";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function instrumentId(value: unknown): value is string {
  return typeof value === "string" && /^NSE:[A-Z0-9_.&-]+$/.test(value);
}

function instrument(value: unknown): value is Instrument {
  return object(value) && instrumentId(value.id) && typeof value.symbol === "string" && Boolean(value.symbol)
    && typeof value.name === "string" && value.exchange === "NSE" && value.currency === "INR"
    && (value.kind === "index" || value.kind === "equity")
    && Array.isArray(value.aliases) && value.aliases.every((alias) => typeof alias === "string");
}

function price(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function volume(value: unknown) {
  return value === null || (price(value) && Number.isSafeInteger(value));
}

function ohlc(low: unknown, open: unknown, close: unknown, high: unknown) {
  return price(low) && price(open) && price(close) && price(high)
    && low <= Math.min(open, close) && high >= Math.max(open, close);
}

function quote(value: unknown): value is InstrumentQuote {
  return object(value) && instrumentId(value.instrumentId)
    && ohlc(value.low, value.open, value.price, value.high)
    && price(value.previousClose) && Number.isFinite(value.change) && Number.isFinite(value.changePercent)
    && volume(value.volume) && (value.trend === "up" || value.trend === "down" || value.trend === "flat");
}

function candle(value: unknown): value is MarketCandle {
  return object(value) && timestamp(value.time) && ohlc(value.low, value.open, value.close, value.high) && volume(value.volume);
}

function overview(value: unknown): value is MarketOverview {
  if (!object(value) || (value.source !== "demo" && value.source !== "market") || !timestamp(value.asOf)
    || !Array.isArray(value.quotes) || !value.quotes.every(quote) || !object(value.session)) return false;

  const { exchange, timezone, status, opensAt, closesAt } = value.session;
  return exchange === "NSE" && timezone === "Asia/Kolkata"
    && (status === "open" || status === "closed" || status === "preopen")
    && timestamp(opensAt) && timestamp(closesAt) && Date.parse(opensAt) < Date.parse(closesAt);
}

async function read(path: string, signal: AbortSignal | undefined): Promise<unknown> {
  const response = await fetch(`/api/v1/market/${path}`, {
    headers: { Accept: "application/json" }, credentials: "omit", cache: "no-store", redirect: "error", signal,
  });
  if (!response.ok) throw new Error("Market data is unavailable.");
  return response.json();
}

const stagingMarketClient: MarketDataClient = {
  async getInstruments({ query, signal } = {}) {
    const search = query ? `?${new URLSearchParams({ query })}` : "";
    const data = await read(`instruments${search}`, signal);
    if (object(data) && Array.isArray(data.instruments) && data.instruments.every(instrument)
      && new Set(data.instruments.map(({ id }) => id)).size === data.instruments.length) return { instruments: data.instruments };
    throw new Error("The instrument catalog response was invalid.");
  },
  async getMarketOverview({ signal } = {}) {
    const data = await read("overview", signal);
    if (overview(data) && new Set(data.quotes.map(({ instrumentId }) => instrumentId)).size === data.quotes.length) return data;
    throw new Error("The market overview response was invalid.");
  },
  async getMarketCandles(id, timeframe, { signal } = {}) {
    const data = await read(`instruments/${encodeURIComponent(id)}/candles?${new URLSearchParams({ timeframe })}`, signal);
    if (object(data) && data.instrumentId === id && data.timeframe === timeframe
      && (data.source === "demo" || data.source === "market") && timestamp(data.asOf)
      && (data.freshness === "fresh" || data.freshness === "stale")
      && Array.isArray(data.candles) && data.candles.every(candle)
      && data.candles.every(({ time }, index, candles) => index === 0 || Date.parse(candles[index - 1].time) < Date.parse(time))) {
      const result: MarketCandles = {
        instrumentId: id, timeframe, source: data.source, asOf: data.asOf, freshness: data.freshness, candles: data.candles,
      };
      return result;
    }
    throw new Error("The candle response was invalid.");
  },
};

export function marketDataClient(mode: MarketMode, scenario?: MarketChartScenario) {
  return mode === "staging" ? stagingMarketClient : createMarketMock(scenario);
}
