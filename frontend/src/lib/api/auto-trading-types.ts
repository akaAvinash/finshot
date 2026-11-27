export type PaperEngine = "idle" | "running" | "halted";
export type PaperStrategy = { id: string; name: string; instrument: string };
export type PaperOrder = {
  id: string;
  instrument: string;
  side: "Buy" | "Sell";
  quantity: number;
  limitPaise: number;
  approval: "approved" | "pending";
  status: "queued" | "held" | "filled" | "cancelled";
};
export type PaperTrade = {
  id: string;
  instrument: string;
  side: "Buy" | "Sell";
  quantity: number;
  fillPaise: number;
  pnlPaise: number;
  filledAt: string;
};
export type PaperEvent = Readonly<{ id: string; at: string; message: string }>;
export type PaperLimits = {
  profitLimitPaise: number | null;
  lossLimitPaise: number;
  tradeLimit: number;
  postCapConfidencePercent: number;
  maxConsecutiveLosses: number;
  stopLossBps: number;
  takeProfitBps: number;
  maxRiskPerTradePaise: number;
  maxPositionSizeBps: number;
};

export type PaperSnapshot = Readonly<{
  source: "demo";
  environment: "PAPER";
  asOf: string;
  engine: PaperEngine;
  strategies: readonly PaperStrategy[];
  strategyId: string | null;
  agent: { name: string; ready: boolean };
  sampleEntry: { pricePaise: number; equityPaise: number; confidencePercent: number | null };
  risk: PaperLimits & {
    status: "approved" | "blocked";
    dailyLossPaise: number;
    tradesToday: number;
  };
  orders: readonly PaperOrder[];
  trades: readonly PaperTrade[];
  events: readonly PaperEvent[];
}>;

export type PaperEngineCommand =
  | { action: "assign"; strategyId: string }
  | { action: "start" | "pause" | "reset" }
  | { action: "halt"; confirmation: "STOP" };

export type PaperCommand = PaperEngineCommand | { action: "set-limits"; limits: PaperLimits };

export type PaperScenario = "ready" | "empty" | "stale" | "denied" | "error";

export type PaperResult =
  | { status: "ready" | "stale"; data: PaperSnapshot }
  | { status: "empty" | "denied" };

export interface PaperTradingClient {
  getPaperTrading(options?: { scenario?: PaperScenario; signal?: AbortSignal }): Promise<PaperResult>;
  sendPaperCommand(command: PaperCommand, options?: { scenario?: PaperScenario; signal?: AbortSignal }): Promise<PaperSnapshot>;
}
