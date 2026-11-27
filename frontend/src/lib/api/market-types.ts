export const marketTimeframes = ["1m", "5m", "15m", "30m", "1h", "1D"] as const;

export type MarketTimeframe = (typeof marketTimeframes)[number];
export type MarketFreshness = "fresh" | "stale";
export type MarketSource = "demo" | "market";

export type Instrument = {
  id: string;
  symbol: string;
  name: string;
  exchange: "NSE";
  kind: "index" | "equity";
  currency: "INR";
  aliases: string[];
};

export type InstrumentQuote = {
  instrumentId: string;
  price: number;
  previousClose: number;
  change: number;
  changePercent: number;
  open: number;
  high: number;
  low: number;
  volume: number | null;
  trend: "up" | "down" | "flat";
};

export type MarketOverview = {
  source: MarketSource;
  asOf: string;
  session: {
    exchange: "NSE";
    status: "preopen" | "open" | "closed";
    timezone: "Asia/Kolkata";
    opensAt: string;
    closesAt: string;
  };
  quotes: InstrumentQuote[];
};

export type MarketCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

export type MarketCandles = {
  instrumentId: string;
  timeframe: MarketTimeframe;
  source: MarketSource;
  asOf: string;
  freshness: MarketFreshness;
  candles: MarketCandle[];
};

type RequestOptions = { signal?: AbortSignal };

export interface MarketDataClient {
  getInstruments(options?: RequestOptions & { query?: string }): Promise<{ source: MarketSource; instruments: Instrument[] }>;
  getMarketOverview(options?: RequestOptions): Promise<MarketOverview>;
  getMarketCandles(instrumentId: string, timeframe: MarketTimeframe, options?: RequestOptions): Promise<MarketCandles>;
}
