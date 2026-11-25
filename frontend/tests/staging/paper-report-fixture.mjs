const strategy = { id: "staging-strategy-id", name: "Staging ledger", version: 3 };
const base = { replay: 4, strategy, instrument: "SBIN", quantity: 5, feesPaise: 50 };
const journal = [
  { ...base, id: "staging-sell", date: "2026-11-13", side: "Sell", fillPaise: 50300,
    pnlPaise: 6400, filledAt: "2026-11-13T09:30:00Z", reason: "signal-exit" },
  { ...base, id: "staging-buy", date: "2026-11-12", side: "Buy", fillPaise: 49000,
    pnlPaise: 0, filledAt: "2026-11-12T04:00:00Z", reason: "entry" },
];
const journalLimit = 500;
const historicalFills = Array.from({ length: 501 }, (_, index) => {
  const filledAt = new Date(Date.UTC(2024, 0, index + 1, 4)).toISOString();
  return { ...base, replay: 3, id: `historical-fill-${index + 1}`, date: filledAt.slice(0, 10),
    side: "Buy", fillPaise: 49000, pnlPaise: 0, filledAt, reason: "entry" };
}).reverse();

function selectedFills(period, mode) {
  if (mode === "empty") return [];
  const available = mode === "large" ? [...journal, ...historicalFills] : journal;
  return available.filter(({ date }) => (!period.from || date >= period.from) && (!period.to || date <= period.to));
}

export function stagingReport(period, mode) {
  const fills = selectedFills(period, mode);
  const realisedPaise = fills.reduce((total, trade) => total + trade.pnlPaise, 0);
  const feesPaise = fills.reduce((total, trade) => total + trade.feesPaise, 0);
  const closedTrades = fills.filter(({ side }) => side === "Sell").length;
  const daily = fills.map((fill) => ({ date: fill.date, realisedPaise: fill.pnlPaise, feesPaise: fill.feesPaise, fills: 1 })).reverse();

  return {
    status: "ready",
    data: {
      source: "demo", environment: "PAPER", asOf: "2026-11-25T10:00:00Z",
      period: { from: period.from ?? daily[0]?.date ?? null, to: period.to ?? daily.at(-1)?.date ?? null },
      summary: { realisedPaise, unrealisedPaise: 0, netPaise: realisedPaise, feesPaise, fills: fills.length,
        closedTrades, winningTrades: closedTrades, losingTrades: 0 },
      openPosition: null, daily, journal: fills.slice(0, journalLimit), journalTruncated: fills.length > journalLimit,
      strategies: fills.length ? [{ strategy, realisedPaise, feesPaise, fills: fills.length, closedTrades }] : [],
      reconciliation: { status: mode === "mismatch" ? "mismatch" : "matched", replay: 4, ledgerCashPaise: 2506400,
        accountCashPaise: mode === "mismatch" ? 2506500 : 2506400, ledgerQuantity: 0, accountQuantity: 0 },
    },
  };
}

export function stagingReportCsv(period, mode) {
  const header = "date,filled_at,replay,strategy,version,instrument,side,quantity,fill_inr,fees_inr,pnl_inr,reason,trade_id";
  const rows = selectedFills(period, mode).reverse().map((row) => [row.date, row.filledAt, row.replay, strategy.name, strategy.version,
    row.instrument, row.side, row.quantity, (row.fillPaise / 100).toFixed(2), (row.feesPaise / 100).toFixed(2),
    (row.pnlPaise / 100).toFixed(2), row.reason, row.id].join(","));
  return [header, ...rows, ""].join("\r\n");
}
