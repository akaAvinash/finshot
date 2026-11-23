import type { DashboardSnapshot, PortfolioPoint } from "./types";

const asOf = "2026-11-23T15:30:00+05:30";
const values = [
  107200, 107610, 107130, 108270, 109080, 108410, 108900, 110040, 110460, 110980,
  110220, 111470, 111970, 111550, 110990, 111460, 112570, 112020, 113210, 113940,
  114720, 115260, 114190, 114590, 115430, 116650, 117290, 117970, 117400, 118280,
  119450, 119080, 120200, 120990, 119210, 119720, 120610, 121700, 122410, 121864,
  124580,
];

function samplePortfolio(): PortfolioPoint[] {
  const end = new Date("2026-11-23T00:00:00Z");
  const points: PortfolioPoint[] = [];

  for (const value of [...values].reverse()) {
    while (end.getUTCDay() === 0 || end.getUTCDay() === 6) {
      end.setUTCDate(end.getUTCDate() - 1);
    }
    points.push({ date: end.toISOString().slice(0, 10), value });
    end.setUTCDate(end.getUTCDate() - 1);
  }

  return points.reverse();
}

export const dashboardFixture: DashboardSnapshot = {
  asOf,
  portfolioValue: 124580,
  dayPnl: 2716,
  dayReturn: 2.23,
  monthPnl: 9150,
  monthReturn: 7.93,
  winningTrades: 26,
  totalTrades: 38,
  indices: [
    { symbol: "NIFTY 50", name: "NSE broad market index", price: 24481.10, changePercent: 0.54 },
    { symbol: "BANK NIFTY", name: "NSE banking index", price: 52364.20, changePercent: 0.67 },
    { symbol: "INDIA VIX", name: "NSE volatility index", price: 12.46, changePercent: -3.21 },
  ],
  watchlist: [
    { symbol: "RELIANCE", name: "Reliance Industries", price: 1429.65, changePercent: -0.18 },
    { symbol: "HDFCBANK", name: "HDFC Bank", price: 988.25, changePercent: 0.42 },
    { symbol: "TCS", name: "Tata Consultancy Services", price: 3124.50, changePercent: 0.89 },
    { symbol: "INFY", name: "Infosys", price: 1546.35, changePercent: -0.31 },
    { symbol: "SBIN", name: "State Bank of India", price: 857.30, changePercent: 0.36 },
  ],
  portfolio: samplePortfolio(),
  recentTrades: [
    { id: "trd-1", symbol: "NIFTY 50 24500 CE", side: "Buy", quantity: 75, price: 182.40, pnl: 1627.50, timeIst: "14:52" },
    { id: "trd-2", symbol: "BANK NIFTY 52300 PE", side: "Sell", quantity: 30, price: 478.25, pnl: 493.50, timeIst: "13:37" },
    { id: "trd-3", symbol: "HDFCBANK", side: "Buy", quantity: 100, price: 991.20, pnl: -295, timeIst: "12:11" },
    { id: "trd-4", symbol: "SBIN", side: "Buy", quantity: 100, price: 850.20, pnl: 710, timeIst: "11:02" },
  ],
};
