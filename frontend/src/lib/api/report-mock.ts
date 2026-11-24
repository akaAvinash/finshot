import { offsetReportDay, reportDay } from "../reporting";
import { waitForMock } from "./mock-delay";
import type { ReportingClient, ReportMark, ReportPeriod, ReportTrade } from "./report-types";

const asOf = "2026-11-23T10:00:00.000Z";
const priorAsOf = "2026-11-20T10:00:00.000Z";
const lengths: Record<ReportPeriod, number> = { "7d": 7, "30d": 30, "90d": 90 };
const listings = [
  { symbol: "RELIANCE", pricePaise: 142_965, strategy: "Reliance Swing" },
  { symbol: "HDFCBANK", pricePaise: 98_825, strategy: "HDFC Mean Reversion" },
  { symbol: "SBIN", pricePaise: 85_730, strategy: "SBI Session Trend" },
  { symbol: "TCS", pricePaise: 312_450, strategy: "Equity Momentum" },
  { symbol: "INFY", pricePaise: 154_635, strategy: "Equity Momentum" },
];

function makeTrades(): ReportTrade[] {
  const trades: ReportTrade[] = [];
  const latestDay = reportDay(asOf);
  for (let offset = 89; offset >= 0; offset--) {
    const date = offsetReportDay(latestDay, -offset);
    const weekday = new Date(`${date}T00:00:00Z`).getUTCDay();
    if (weekday === 0 || weekday === 6 || offset % 9 === 8) continue;
    const count = offset % 3 === 0 ? 2 : 1;
    for (let fill = 0; fill < count; fill++) {
      const sequence = trades.length + 1;
      const listing = listings[(offset + fill * 3) % listings.length];
      const quantity = 15 + (sequence % 5) * 5;
      const entryPaise = listing.pricePaise + ((offset * 219) % 2100) - 1050;
      const side = sequence % 5 === 0 ? "short" : "long";
      const movement = sequence % 7 < 4 ? 255 + (sequence * 137) % 950 : -180 - (sequence * 63) % 790;
      const exitPaise = entryPaise + movement * (side === "long" ? 1 : -1);
      trades.push({
        id: `demo-fill-${sequence}`,
        symbol: listing.symbol,
        strategy: listing.strategy,
        broker: sequence % 3 === 0 ? "Fyers" : "Zerodha",
        side,
        quantity,
        entryPaise,
        exitPaise,
        brokeragePaise: Math.min(4000, Math.round((entryPaise + exitPaise) * quantity * 0.0003)),
        taxesPaise: 220 + quantity * 8,
        closedAt: `${date}${fill === 0 ? "T07:20:00.000Z" : "T09:45:00.000Z"}`,
      });
    }
  }
  return trades.reverse();
}

const marks: ReportMark[] = [
  { id: "demo-open-1", symbol: "RELIANCE", broker: "Zerodha", strategy: "Reliance Swing", side: "long", quantity: 30, entryPaise: 141_780, markPaise: 142_965 },
  { id: "demo-open-2", symbol: "HDFCBANK", broker: "Fyers", strategy: "HDFC Mean Reversion", side: "long", quantity: 25, entryPaise: 99_156, markPaise: 98_825 },
];

export function createReportingMock(): ReportingClient {
  let history: ReportTrade[] | undefined;
  return {
    async getReport(period, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, 270);
      if (scenario === "error") throw new Error("The demo ledger is unavailable.");
      if (scenario === "denied" || scenario === "empty") return { status: scenario };

      const stale = scenario === "stale";
      const observedAt = stale ? priorAsOf : asOf;
      const to = reportDay(observedAt);
      const from = offsetReportDay(to, 1 - lengths[period]);
      history ??= makeTrades();
      return {
        status: stale ? "stale" : "ready",
        data: {
          source: "demo", environment: "DEMO", currency: "INR", asOf: observedAt, period,
          range: { from, to },
          trades: history.filter(({ closedAt }) => closedAt <= observedAt && reportDay(closedAt) >= from),
          marks: stale ? null : marks,
        },
      };
    },
  };
}
