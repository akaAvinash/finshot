const asOf = "2026-11-24T10:00:00Z";
const instruments = [
  { id: "NSE:NIFTY50", symbol: "NIFTY 50", name: "NSE Nifty 50", kind: "index", aliases: ["nifty"] },
  { id: "NSE:SBIN", symbol: "SBIN", name: "State Bank of India", kind: "equity", aliases: ["sbi"] },
  { id: "NSE:M&M", symbol: "M&M", name: "Mahindra & Mahindra", kind: "equity", aliases: ["mahindra"] },
].map((row) => ({ ...row, exchange: "NSE", currency: "INR" }));

const quotes = [23123.45, 503, 2712].map((price, index) => ({
  instrumentId: instruments[index].id, price, previousClose: price - 10, change: 10,
  changePercent: 10 / (price - 10) * 100, open: price - 4, high: price + 2, low: price - 6,
  volume: index === 0 ? null : 8500, trend: "up",
}));

export function stagingInstruments(query) {
  const term = query?.toLowerCase();
  return { instruments: term ? instruments.filter((row) =>
    [row.id, row.symbol, row.name, ...row.aliases].some((value) => value.toLowerCase().includes(term))) : instruments };
}

export function stagingOverview(mode) {
  return {
    source: "demo", asOf, quotes: mode === "no-quotes" ? [] : quotes,
    session: {
      exchange: "NSE", status: "closed", timezone: "Asia/Kolkata",
      opensAt: "2026-11-24T03:45:00Z", closesAt: "2026-11-24T10:00:00Z",
    },
  };
}

export function stagingCandles(instrumentId, timeframe, mode) {
  const quote = quotes.find((value) => value.instrumentId === instrumentId);
  if (!quote) return null;
  const candles = mode === "empty" ? [] : ["2026-11-23T09:30:00Z", "2026-11-24T09:30:00Z"].map((time, index) => ({
    time, open: quote.open, high: quote.high, low: quote.low, close: quote.price - 2 + index, volume: quote.volume,
  }));
  return { instrumentId, timeframe, source: "demo", asOf, freshness: mode === "stale" ? "stale" : "fresh", candles };
}
