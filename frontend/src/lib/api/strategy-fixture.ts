import type { Strategy, StrategyParameters, StrategyRevision, StrategySnapshot, StrategyVersion } from "./strategy-types";

const snapshotTime = "2026-11-23T10:00:00.000Z";

export function unreviewedDraft(parameters: StrategyParameters): StrategyRevision {
  return { parameters, backtest: "unavailable", riskReview: "pending" };
}

function approvedRevision(parameters: StrategyParameters): Pick<StrategyVersion, "parameters" | "backtest" | "riskReview"> {
  return { parameters, backtest: "passed", riskReview: "approved" };
}

type DeployedExample = Omit<Strategy, "status" | "draft" | "versions"> & {
  status: "active" | "paused";
  parameters: StrategyParameters;
};

const examples: DeployedExample[] = [
  {
    id: "nifty-momentum", status: "active", metrics: { pnlPaise: 742_025, winRateBps: 7250 },
    parameters: { name: "NIFTY Momentum", description: "Intraday breakouts with confirmation from the trend.", instrument: "NIFTY 50", timeframe: "15m", riskTier: "medium", positionSizeBps: 900, stopLossBps: 125 },
  },
  {
    id: "banknifty-range", status: "active", metrics: { pnlPaise: 498_075, winRateBps: 6980 },
    parameters: { name: "BankNifty Range", description: "Range entries with a volatility filter.", instrument: "BANKNIFTY", timeframe: "30m", riskTier: "low", positionSizeBps: 650, stopLossBps: 90 },
  },
  {
    id: "finnifty-breakout", status: "paused", metrics: { pnlPaise: -125_040, winRateBps: 5520 },
    parameters: { name: "FinNifty Breakout", description: "Opening-range breakouts during wider price moves.", instrument: "FINNIFTY", timeframe: "5m", riskTier: "high", positionSizeBps: 1100, stopLossBps: 175 },
  },
  {
    id: "reliance-swing", status: "active", metrics: { pnlPaise: 276_040, winRateBps: 7100 },
    parameters: { name: "Reliance Swing", description: "Multi-session trends with volume confirmation.", instrument: "RELIANCE", timeframe: "1D", riskTier: "medium", positionSizeBps: 800, stopLossBps: 175 },
  },
];

export function createStrategyFixture(): StrategySnapshot {
  const deployed = examples.map(({ id, status, parameters, metrics }): Strategy => {
    const first = { ...approvedRevision({ ...parameters }), number: 1, activatedAt: "2026-11-13T05:00:00.000Z" };
    const versions = id === "nifty-momentum"
      ? [first, { ...approvedRevision({ ...parameters, positionSizeBps: 750 }), number: 2, activatedAt: "2026-11-20T04:30:00.000Z" }]
      : [first];
    return { id, status, draft: null, versions, metrics: metrics && { ...metrics } };
  });

  const eligibleDraft = approvedRevision({
    name: "HDFC Mean Reversion", description: "Sample retracement setup with reviewed risk settings.", instrument: "HDFCBANK", timeframe: "30m", riskTier: "low", positionSizeBps: 550, stopLossBps: 75,
  });
  const pendingDraft = unreviewedDraft({
    name: "SBI Session Trend", description: "Session trend prototype awaiting a backtest.", instrument: "SBIN", timeframe: "1h", riskTier: "medium", positionSizeBps: 700, stopLossBps: 125,
  });

  return {
    environment: "DEMO", source: "demo", asOf: snapshotTime,
    strategies: [...deployed,
      { id: "hdfc-reversion", status: "draft", draft: eligibleDraft, versions: [], metrics: null },
      { id: "sbi-trend", status: "draft", draft: pendingDraft, versions: [], metrics: null },
    ],
  };
}
