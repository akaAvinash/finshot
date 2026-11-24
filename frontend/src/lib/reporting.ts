import type { ReportMark, ReportSnapshot, ReportTrade } from "./api/report-types";

const sessionDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
});
const timestamp = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function reportDay(instant: string) {
  return sessionDate.format(new Date(instant));
}

export function formatReportTime(instant: string) {
  return `${timestamp.format(new Date(instant))} IST`;
}

export function offsetReportDay(day: string, offset: number) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

function grossPnl(position: ReportTrade | ReportMark, exitPaise: number) {
  const direction = position.side === "long" ? 1 : -1;
  return (exitPaise - position.entryPaise) * position.quantity * direction;
}

export function reportTradePnl(trade: ReportTrade) {
  const grossPaise = grossPnl(trade, trade.exitPaise);
  const chargesPaise = trade.brokeragePaise + trade.taxesPaise;
  return { grossPaise, chargesPaise, netPaise: grossPaise - chargesPaise };
}

export function summarizeReport(snapshot: ReportSnapshot) {
  const realized = snapshot.trades.reduce((totals, trade) => {
    const pnl = reportTradePnl(trade);
    totals.grossPaise += pnl.grossPaise;
    totals.brokeragePaise += trade.brokeragePaise;
    totals.taxesPaise += trade.taxesPaise;
    totals.realizedPaise += pnl.netPaise;
    return totals;
  }, { grossPaise: 0, brokeragePaise: 0, taxesPaise: 0, realizedPaise: 0 });

  const unrealizedPaise = snapshot.marks?.reduce((total, mark) => total + grossPnl(mark, mark.markPaise), 0) ?? null;
  return {
    ...realized,
    chargesPaise: realized.brokeragePaise + realized.taxesPaise,
    unrealizedPaise,
    netPaise: unrealizedPaise === null ? null : realized.realizedPaise + unrealizedPaise,
  };
}

export function dailyReport(snapshot: ReportSnapshot) {
  const netByDay = new Map<string, { netPaise: number; trades: number }>();
  for (const trade of snapshot.trades) {
    const day = reportDay(trade.closedAt);
    const entry = netByDay.get(day) ?? { netPaise: 0, trades: 0 };
    entry.netPaise += reportTradePnl(trade).netPaise;
    entry.trades++;
    netByDay.set(day, entry);
  }

  let cumulativePaise = 0;
  const days = [];
  for (let date = snapshot.range.from; date <= snapshot.range.to; date = offsetReportDay(date, 1)) {
    const { netPaise, trades } = netByDay.get(date) ?? { netPaise: 0, trades: 0 };
    cumulativePaise += netPaise;
    days.push({ date, netPaise, trades, cumulativePaise });
  }
  return days;
}

export function reportBreakdown(trades: readonly ReportTrade[], field: "broker" | "strategy") {
  const rows = new Map<string, { label: string; netPaise: number; trades: number }>();
  for (const trade of trades) {
    const label = trade[field];
    const row = rows.get(label) ?? { label, netPaise: 0, trades: 0 };
    row.netPaise += reportTradePnl(trade).netPaise;
    row.trades++;
    rows.set(label, row);
  }
  return [...rows.values()].sort((a, b) => b.netPaise - a.netPaise || a.label.localeCompare(b.label));
}

function csvCell(value: string | number) {
  if (typeof value === "number") return String(value);
  const safe = /^[=+\-@\t\r\n]/.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function reportTradesCsv(snapshot: ReportSnapshot) {
  const header = "environment,source,as_of,period_start,period_end,trade_id,closed_utc,symbol,broker,strategy,side,quantity,entry_inr,exit_inr,gross_inr,brokerage_inr,taxes_inr,net_realized_inr";
  const amount = (paise: number) => (paise / 100).toFixed(2);
  const rows = snapshot.trades.map((trade) => {
    const pnl = reportTradePnl(trade);
    const text = [snapshot.environment, snapshot.source, snapshot.asOf, snapshot.range.from, snapshot.range.to,
      trade.id, trade.closedAt, trade.symbol, trade.broker, trade.strategy, trade.side, trade.quantity].map(csvCell);
    const money = [trade.entryPaise, trade.exitPaise, pnl.grossPaise, trade.brokeragePaise, trade.taxesPaise, pnl.netPaise].map(amount);
    return [...text, ...money].join(",");
  });
  return `${[header, ...rows].join("\r\n")}\r\n`;
}
