export type BacktestScenario = "ready" | "stale" | "empty" | "denied" | "error" | "run-error";

export type BacktestStrategy = {
  id: string;
  name: string;
  revision: number | "draft";
  instrumentId: string;
  positionSizeBps: number;
};

export type BacktestInstrument = { id: string; symbol: string };

export type BacktestConfig = {
  strategyId: string;
  instrumentId: string;
  from: string;
  to: string;
  outOfSampleFrom: string;
  capitalPaise: number;
  feeBps: number;
  slippageBps: number;
};

export type BacktestPoint = { date: string; equityPaise: number; drawdownBps: number };

export type BacktestTrade = {
  id: string;
  entryAt: string;
  exitAt: string;
  quantity: number;
  entryPaise: number;
  exitPaise: number;
  feesPaise: number;
  pnlPaise: number;
};

export type BacktestResult = {
  endingEquityPaise: number;
  netPnlPaise: number;
  returnBps: number;
  maxDrawdownBps: number;
  winRateBps: number | null;
  totalFeesPaise: number;
  points: readonly BacktestPoint[];
  trades: readonly BacktestTrade[];
};

type BacktestRunBase = {
  id: string;
  source: "demo";
  environment: "DEMO";
  asOf: string;
  queuedAt: string;
  config: BacktestConfig;
};

export type BacktestRun = BacktestRunBase & (
  | { status: "queued" | "running" }
  | { status: "completed"; result: BacktestResult }
  | { status: "failed"; message: string }
);

export type BacktestWorkspace = {
  source: "demo";
  environment: "DEMO";
  asOf: string;
  from: string;
  to: string;
  strategies: readonly BacktestStrategy[];
  instruments: readonly BacktestInstrument[];
  runs: readonly BacktestRun[];
};

export type BacktestWorkspaceResult =
  | { status: "ready" | "stale"; data: BacktestWorkspace }
  | { status: "denied" };

type Options = { scenario?: BacktestScenario; signal?: AbortSignal };

export interface BacktestClient {
  getBacktestWorkspace(options?: Options): Promise<BacktestWorkspaceResult>;
  startBacktest(config: BacktestConfig, options?: Options): Promise<BacktestRun>;
  getBacktestRun(id: string, options?: { signal?: AbortSignal }): Promise<BacktestRun>;
}
