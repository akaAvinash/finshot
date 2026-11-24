export const reportPeriods = ["7d", "30d", "90d"] as const;

export type ReportPeriod = (typeof reportPeriods)[number];
export type ReportScenario = "ready" | "stale" | "empty" | "denied" | "error";
export type ReportBroker = "Zerodha" | "Fyers";

type ReportPosition = {
  id: string;
  symbol: string;
  broker: ReportBroker;
  strategy: string;
  side: "long" | "short";
  quantity: number;
  entryPaise: number;
};

export type ReportTrade = ReportPosition & {
  closedAt: string;
  exitPaise: number;
  brokeragePaise: number;
  taxesPaise: number;
};

export type ReportMark = ReportPosition & { markPaise: number };

export type ReportSnapshot = {
  source: "demo";
  environment: "DEMO";
  currency: "INR";
  asOf: string;
  period: ReportPeriod;
  range: { from: string; to: string };
  trades: readonly ReportTrade[];
  marks: readonly ReportMark[] | null;
};

export type ReportResult =
  | { status: "ready" | "stale"; data: ReportSnapshot }
  | { status: "empty" | "denied" };

export interface ReportingClient {
  getReport(period: ReportPeriod, options?: { scenario?: ReportScenario; signal?: AbortSignal }): Promise<ReportResult>;
}
