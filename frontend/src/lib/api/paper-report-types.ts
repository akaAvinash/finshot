export type ReportPeriod = { from: string | null; to: string | null };

export type ReportSummary = {
  realisedPaise: number;
  unrealisedPaise: number;
  netPaise: number;
  feesPaise: number;
  fills: number;
  closedTrades: number;
  winningTrades: number;
  losingTrades: number;
};

export type ReportDay = { date: string; realisedPaise: number; feesPaise: number; fills: number };
export type ReportStrategyRef = { id: string; name: string; version: number };
export type ReportStrategy = {
  strategy: ReportStrategyRef | null;
  realisedPaise: number;
  feesPaise: number;
  fills: number;
  closedTrades: number;
};

export type ReportTrade = {
  id: string;
  date: string;
  replay: number;
  strategy: ReportStrategyRef | null;
  instrument: string;
  side: "Buy" | "Sell";
  quantity: number;
  fillPaise: number;
  feesPaise: number;
  pnlPaise: number;
  filledAt: string;
  reason: "entry" | "signal-exit" | "stop-loss" | "end-of-replay";
};

export type PaperReport = {
  source: "demo";
  environment: "PAPER";
  asOf: string;
  period: ReportPeriod;
  summary: ReportSummary;
  openPosition: {
    instrument: string;
    quantity: number;
    entryPaise: number;
    markPaise: number;
    markedAt: string;
    unrealisedPaise: number;
  } | null;
  daily: ReportDay[];
  strategies: ReportStrategy[];
  journal: ReportTrade[];
  journalTruncated: boolean;
  reconciliation: {
    status: "matched" | "mismatch";
    replay: number;
    ledgerCashPaise: number;
    accountCashPaise: number;
    ledgerQuantity: number;
    accountQuantity: number;
  } | null;
};

export type PaperReportResult = { status: "ready"; data: PaperReport } | { status: "empty" };
