export const strategyInstruments = ["NIFTY 50", "BANKNIFTY", "FINNIFTY", "RELIANCE", "HDFCBANK", "SBIN"] as const;
export const strategyTimeframes = ["5m", "15m", "30m", "1h", "1D"] as const;
export const strategyRiskTiers = ["low", "medium", "high"] as const;

export type StrategyStatus = "active" | "paused" | "draft";
export type StrategyRiskTier = (typeof strategyRiskTiers)[number];
export type StrategyScenario = "ready" | "stale" | "empty" | "denied" | "error";

export type StrategyParameters = Readonly<{
  name: string;
  description: string;
  instrument: (typeof strategyInstruments)[number];
  timeframe: (typeof strategyTimeframes)[number];
  riskTier: StrategyRiskTier;
  positionSizeBps: number;
  stopLossBps: number;
}>;

export type StrategyRevision = Readonly<{
  parameters: StrategyParameters;
  backtest: "passed" | "failed" | "unavailable";
  riskReview: "approved" | "rejected" | "pending";
}>;

export type StrategyVersion = StrategyRevision & Readonly<{
  number: number;
  activatedAt: string;
  backtest: "passed";
  riskReview: "approved";
}>;

export type Strategy = Readonly<{
  id: string;
  status: StrategyStatus;
  draft: StrategyRevision | null;
  versions: readonly StrategyVersion[];
  metrics: Readonly<{ pnlPaise: number; winRateBps: number }> | null;
}>;

export type StrategySnapshot = Readonly<{
  source: "demo";
  environment: "DEMO";
  asOf: string;
  strategies: readonly Strategy[];
}>;

export type StrategyResult =
  | { status: "ready" | "stale"; data: StrategySnapshot }
  | { status: "empty" | "denied" };

export type StrategyCommand =
  | { action: "create"; parameters: StrategyParameters }
  | { action: "save-draft"; id: string; parameters: StrategyParameters }
  | { action: "activate" | "pause"; id: string };

type StrategyRequestOptions = { scenario?: StrategyScenario; signal?: AbortSignal };

export interface StrategyClient {
  getStrategies(options?: StrategyRequestOptions): Promise<StrategyResult>;
  sendStrategyCommand(command: StrategyCommand, options?: StrategyRequestOptions): Promise<StrategySnapshot>;
}
