import type { Instrument, InstrumentQuote, MarketCandle, MarketOverview, MarketTimeframe } from "./market-types";

type FixtureInstrument = Instrument & { close: number; previousClose: number; volume: number | null };

const listings: Array<{ ticker: string; symbol?: string; name: string; aliases?: string[]; close: number; previousClose: number; volume?: number }> = [
  { ticker: "NIFTY50", symbol: "NIFTY 50", name: "Nifty 50 Index", aliases: ["NIFTY"], close: 24481.10, previousClose: 24349.61 },
  { ticker: "BANKNIFTY", name: "Nifty Bank Index", aliases: ["BANK NIFTY", "NIFTY BANK"], close: 52364.20, previousClose: 52015.70 },
  { ticker: "FINNIFTY", name: "Nifty Financial Services Index", aliases: ["NIFTY FIN SERVICE"], close: 24832.55, previousClose: 24735.80 },
  { ticker: "INDIAVIX", symbol: "INDIA VIX", name: "India Volatility Index", close: 12.46, previousClose: 12.87 },
  { ticker: "RELIANCE", name: "Reliance Industries", aliases: ["RIL"], close: 1429.65, previousClose: 1432.23, volume: 8235640 },
  { ticker: "HDFCBANK", name: "HDFC Bank", aliases: ["HDFC"], close: 988.25, previousClose: 984.12, volume: 12104783 },
  { ticker: "SBIN", name: "State Bank of India", aliases: ["SBI"], close: 857.30, previousClose: 854.22, volume: 9812250 },
  { ticker: "TCS", name: "Tata Consultancy Services", close: 3124.50, previousClose: 3096.94, volume: 2648120 },
  { ticker: "INFY", name: "Infosys", close: 1546.35, previousClose: 1551.16, volume: 6123250 },
  { ticker: "ICICIBANK", name: "ICICI Bank", close: 1382.80, previousClose: 1376.15, volume: 7081460 },
  { ticker: "BHARTIARTL", name: "Bharti Airtel", aliases: ["AIRTEL"], close: 1738.75, previousClose: 1745.55, volume: 4821160 },
  { ticker: "ITC", name: "ITC Limited", close: 412.30, previousClose: 412.30, volume: 7453125 },
];

export const marketFixture: FixtureInstrument[] = listings.map(({ ticker, symbol = ticker, name, aliases = [], close, previousClose, volume }) => ({
  id: `NSE:${ticker}`,
  symbol,
  name,
  aliases,
  kind: volume === undefined ? "index" : "equity",
  exchange: "NSE",
  currency: "INR",
  close,
  previousClose,
  volume: volume ?? null,
}));

export const demoInstruments: Instrument[] = marketFixture.map(({ id, symbol, name, aliases, kind, exchange, currency }) => ({
  id, symbol, name, aliases, kind, exchange, currency,
}));

const sessionDate = "2026-11-23";
const openUtc = "T03:45:00.000Z";
const closeUtc = "T10:00:00.000Z";
const minutesPerSession = 375;
const intervalMinutes: Record<Exclude<MarketTimeframe, "1D">, number> = { "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60 };
const sessionCounts: Record<MarketTimeframe, number> = { "1m": 1, "5m": 1, "15m": 3, "30m": 5, "1h": 9, "1D": 38 };

function roundPrice(value: number) {
  return Math.round(value * 100) / 100;
}

function dateForSession(session: number) {
  const date = new Date(`${sessionDate}T00:00:00Z`);

  for (let remaining = session; remaining > 0;) {
    date.setUTCDate(date.getUTCDate() - 1);
    if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) remaining--;
  }

  return date.toISOString().slice(0, 10);
}

function seededRandom(key: string) {
  let state = Array.from(key).reduce((seed, letter) => (Math.imul(seed, 31) + letter.charCodeAt(0)) >>> 0, 7);
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function closingPrice(instrument: FixtureInstrument, session: number): number {
  if (session === 0) return instrument.close;
  if (session === 1) return instrument.previousClose;

  const random = seededRandom(`${instrument.id}:close:${session}`);
  const movement = -session * 0.00115 + Math.sin(session * 0.63) * 0.008 + (random() - 0.5) * 0.011;
  return roundPrice(instrument.previousClose * (1 + movement));
}

function createSession(instrument: FixtureInstrument, session: number): MarketCandle[] {
  const date = dateForSession(session);
  const start = Date.parse(`${date}${openUtc}`);
  const random = seededRandom(`${instrument.id}:${date}`);
  const previousClose = closingPrice(instrument, session + 1);
  const close = closingPrice(instrument, session);
  const intradayAmplitude = close * (instrument.kind === "index" ? 0.0033 : 0.0043);
  const phase = random() * Math.PI;
  const opening = roundPrice(previousClose * (1 + (random() - 0.5) * 0.003));
  const totalVolume = instrument.volume === null ? null : session === 0
    ? instrument.volume : Math.round(instrument.volume * (0.7 + random() * 0.57));
  let open = opening;
  let drift = 0;
  let weightTotal = 0;

  const weights = Array.from({ length: minutesPerSession }, (_, minute) => {
    const progress = minute / (minutesPerSession - 1);
    const weight = 0.54 + (progress - 0.49) ** 2 * 3.6 + random() * 0.45;
    weightTotal += weight;
    return weight;
  });
  let remainingVolume = totalVolume;

  return weights.map((weight, minute) => {
    const progress = (minute + 1) / minutesPerSession;
    const envelope = Math.sin(progress * Math.PI);
    drift = drift * 0.9 + (random() - 0.5) * 0.21;
    const wave = Math.sin(progress * 13 + phase) * 0.52 + Math.cos(progress * 26 + phase) * 0.25 + drift;
    const next = minute === minutesPerSession - 1
      ? close : roundPrice(opening + (close - opening) * progress + intradayAmplitude * envelope * wave);
    const wick = close * 0.00038;
    const high = roundPrice(Math.max(open, next) + random() * wick);
    const low = roundPrice(Math.min(open, next) - random() * wick);
    const volume = remainingVolume === null || totalVolume === null ? null : minute === minutesPerSession - 1
      ? remainingVolume : Math.floor(totalVolume * weight / weightTotal);
    if (remainingVolume !== null && volume !== null) remainingVolume -= volume;

    const candle = { time: new Date(start + minute * 60_000).toISOString(), open, high, low, close: next, volume };
    open = next;
    return candle;
  });
}

function aggregateSession(candles: MarketCandle[], interval: number): MarketCandle[] {
  const bars: MarketCandle[] = [];

  for (let start = 0; start < candles.length; start += interval) {
    const chunk = candles.slice(start, start + interval);
    const first = chunk[0];
    bars.push({
      time: first.time,
      open: first.open,
      high: Math.max(...chunk.map(({ high }) => high)),
      low: Math.min(...chunk.map(({ low }) => low)),
      close: chunk[chunk.length - 1].close,
      volume: first.volume === null ? null : chunk.reduce((total, { volume }) => total + (volume ?? 0), 0),
    });
  }

  return bars;
}

export function marketSnapshotDate(stale = false) {
  return `${dateForSession(stale ? 1 : 0)}${closeUtc}`;
}

export function generateMarketCandles(instrument: FixtureInstrument, timeframe: MarketTimeframe, stale = false): MarketCandle[] {
  const offset = stale ? 1 : 0;
  const count = sessionCounts[timeframe];
  const interval = timeframe === "1D" ? minutesPerSession : intervalMinutes[timeframe];

  return Array.from({ length: count }, (_, index) => (
    aggregateSession(createSession(instrument, count - 1 - index + offset), interval)
  )).flat();
}

export function getOverviewFixture(): MarketOverview {
  const quotes: InstrumentQuote[] = marketFixture.map((instrument) => {
    const [day] = aggregateSession(createSession(instrument, 0), minutesPerSession);
    const change = roundPrice(day.close - instrument.previousClose);
    return {
      instrumentId: instrument.id,
      price: day.close,
      previousClose: instrument.previousClose,
      change,
      changePercent: roundPrice((change / instrument.previousClose) * 100),
      open: day.open,
      high: day.high,
      low: day.low,
      volume: day.volume,
      trend: change > 0 ? "up" : change < 0 ? "down" : "flat",
    };
  });

  return {
    source: "demo",
    asOf: marketSnapshotDate(),
    session: {
      exchange: "NSE",
      status: "closed",
      timezone: "Asia/Kolkata",
      opensAt: `${sessionDate}${openUtc}`,
      closesAt: `${sessionDate}${closeUtc}`,
    },
    quotes,
  };
}
