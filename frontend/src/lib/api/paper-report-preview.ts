import type { PaperReportResult, ReportDay, ReportPeriod, ReportStrategy, ReportStrategyRef, ReportTrade } from "./paper-report-types";

const momentum = { id: "demo-momentum", name: "Trend replay", version: 2 };
const pullback = { id: "demo-pullback", name: "Pullback replay", version: 1 };
const markedAt = "2026-11-23T10:00:00Z";

function makeFill(id: number, date: string, replay: number, strategy: ReportStrategyRef | null, instrument: string,
  quantity: number, fillPaise: number, feesPaise: number, reason: ReportTrade["reason"], pnlPaise = 0): ReportTrade {
  const side = reason === "entry" ? "Buy" : "Sell";
  return { id: `demo-fill-${id}`, date, replay, strategy, instrument, side, quantity, fillPaise, feesPaise, pnlPaise,
    reason, filledAt: `${date}T${side === "Buy" ? "04:00" : "09:30"}:00Z` };
}

const fills = [
  makeFill(7, "2026-11-23", 3, momentum, "INFY", 10, 148000, 444, "entry"),
  makeFill(6, "2026-11-18", 2, pullback, "SBIN", 25, 85600, 642, "signal-exit", 106248),
  makeFill(5, "2026-11-17", 2, pullback, "SBIN", 25, 81300, 610, "entry"),
  makeFill(4, "2026-11-12", 2, pullback, "RELIANCE", 10, 288000, 864, "stop-loss", -61746),
  makeFill(3, "2026-11-11", 2, pullback, "RELIANCE", 10, 294000, 882, "entry"),
  makeFill(2, "2026-11-09", 1, null, "INFY", 20, 147500, 885, "end-of-replay", 48245),
  makeFill(1, "2026-11-06", 1, null, "INFY", 20, 145000, 870, "entry"),
];

function periodFills({ from, to }: ReportPeriod) {
  return fills.filter(({ date }) => (!from || date >= from) && (!to || date <= to));
}

export function samplePaperReport(period: ReportPeriod): PaperReportResult {
  const journal = periodFills(period);
  const days = new Map<string, ReportDay>();
  const versions = new Map<string | null, ReportStrategy>();
  let realisedPaise = 0;
  let feesPaise = 0;
  let closedTrades = 0;
  let winningTrades = 0;
  let losingTrades = 0;

  for (const fill of journal) {
    const version = fill.strategy ? `${fill.strategy.id}:${fill.strategy.version}` : null;
    const day = days.get(fill.date) ?? { date: fill.date, realisedPaise: 0, feesPaise: 0, fills: 0 };
    const row = versions.get(version) ?? { strategy: fill.strategy, realisedPaise: 0, feesPaise: 0, fills: 0, closedTrades: 0 };
    day.realisedPaise += fill.pnlPaise;
    day.feesPaise += fill.feesPaise;
    day.fills++;
    row.realisedPaise += fill.pnlPaise;
    row.feesPaise += fill.feesPaise;
    row.fills++;
    realisedPaise += fill.pnlPaise;
    feesPaise += fill.feesPaise;
    if (fill.side === "Sell") {
      row.closedTrades++;
      closedTrades++;
      if (fill.pnlPaise > 0) winningTrades++;
      if (fill.pnlPaise < 0) losingTrades++;
    }
    days.set(fill.date, day);
    versions.set(version, row);
  }

  const daily = [...days.values()].reverse();
  const unrealisedPaise = 24556;
  const strategies = [...versions.values()].sort((a, b) => {
    if (!a.strategy) return 1;
    if (!b.strategy) return -1;
    return a.strategy.name.localeCompare(b.strategy.name) || a.strategy.version - b.strategy.version;
  });

  return { status: "ready", data: {
    source: "demo", environment: "PAPER", asOf: markedAt,
    period: { from: period.from ?? daily[0]?.date ?? null, to: period.to ?? daily.at(-1)?.date ?? null },
    summary: { realisedPaise, unrealisedPaise, netPaise: realisedPaise + unrealisedPaise, feesPaise,
      fills: journal.length, closedTrades, winningTrades, losingTrades },
    openPosition: { instrument: "INFY", quantity: 10, entryPaise: 148000, markPaise: 150500, markedAt, unrealisedPaise },
    daily, strategies, journal, journalTruncated: false,
    reconciliation: { status: "matched", replay: 3, ledgerCashPaise: 8519556, accountCashPaise: 8519556, ledgerQuantity: 10, accountQuantity: 10 },
  } };
}

export function samplePaperCsv(period: ReportPeriod) {
  const rows = periodFills(period).reverse().map((trade) => [trade.date, trade.filledAt, trade.replay, trade.strategy?.name ?? "",
    trade.strategy?.version ?? "", trade.instrument, trade.side, trade.quantity, (trade.fillPaise / 100).toFixed(2),
    (trade.feesPaise / 100).toFixed(2), (trade.pnlPaise / 100).toFixed(2), trade.reason, trade.id]);
  return ["date,filled_at,replay,strategy,version,instrument,side,quantity,fill_inr,fees_inr,pnl_inr,reason,trade_id",
    ...rows.map((row) => row.join(",")), ""].join("\r\n");
}
