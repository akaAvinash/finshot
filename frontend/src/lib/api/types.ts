import type { MarketDataClient } from "./market-types";
import type { PaperTradingClient } from "./auto-trading-types";
import type { BrokerClient } from "./broker-types";
import type { StrategyClient } from "./strategy-types";

// Keep the DTOs and client interface independent of the mock transport.
// A future OpenAPI adapter can map generated DTOs and errors to this contract.
export type MarketQuote = {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
};

export type Trade = {
  id: string;
  symbol: string;
  side: "Buy" | "Sell";
  quantity: number;
  price: number;
  pnl: number;
  timeIst: string;
};

export type PortfolioPoint = { date: string; value: number };

export type DashboardSnapshot = {
  asOf: string;
  portfolioValue: number;
  dayPnl: number;
  dayReturn: number;
  monthPnl: number;
  monthReturn: number;
  winningTrades: number;
  totalTrades: number;
  indices: MarketQuote[];
  watchlist: MarketQuote[];
  portfolio: PortfolioPoint[];
  recentTrades: Trade[];
};

export type DashboardResult =
  | { status: "ready" | "stale"; data: DashboardSnapshot }
  | { status: "empty" };

export interface TradeoClient extends MarketDataClient, PaperTradingClient, BrokerClient, StrategyClient {
  getDashboard(options?: { signal?: AbortSignal }): Promise<DashboardResult>;
}
