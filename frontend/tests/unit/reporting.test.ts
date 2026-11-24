import { describe, expect, it } from "vitest";
import { createReportingMock } from "@/lib/api/report-mock";
import type { ReportSnapshot } from "@/lib/api/report-types";
import { dailyReport, reportBreakdown, reportDay, reportTradePnl, reportTradesCsv, summarizeReport } from "@/lib/reporting";

const snapshot: ReportSnapshot = {
  source: "demo", environment: "DEMO", currency: "INR", period: "7d", asOf: "2026-11-23T10:00:00.000Z",
  range: { from: "2026-11-17", to: "2026-11-23" },
  trades: [
    { id: "one", symbol: "SBIN", broker: "Fyers", strategy: "Swing", side: "long", quantity: 2,
      entryPaise: 85001, exitPaise: 85101, brokeragePaise: 5, taxesPaise: 7, closedAt: "2026-11-23T06:00:00.000Z" },
    { id: "two", symbol: "RELIANCE", broker: "Zerodha", strategy: "Swing", side: "short", quantity: 2,
      entryPaise: 150001, exitPaise: 150101, brokeragePaise: 30, taxesPaise: 9, closedAt: "2026-11-18T20:00:00.000Z" },
  ],
  marks: [{ id: "open", symbol: "SBIN", broker: "Fyers", strategy: "Swing", side: "long", quantity: 2, entryPaise: 85000, markPaise: 85025 }],
};

describe("demo report ledger", () => {
  it("reconciles long and short fills, marks, daily totals, and breakdowns in paise", () => {
    expect(reportTradePnl(snapshot.trades[1])).toEqual({ grossPaise: -200, chargesPaise: 39, netPaise: -239 });
    expect(summarizeReport(snapshot)).toEqual({
      grossPaise: 0, brokeragePaise: 35, taxesPaise: 16, chargesPaise: 51,
      realizedPaise: -51, unrealizedPaise: 50, netPaise: -1,
    });
    expect(summarizeReport({ ...snapshot, marks: null })).toMatchObject({ realizedPaise: -51, unrealizedPaise: null, netPaise: null });
    expect(summarizeReport({ ...snapshot, marks: [] })).toMatchObject({ unrealizedPaise: 0, netPaise: -51 });
    expect(reportDay(snapshot.trades[1].closedAt)).toBe("2026-11-19");
    expect(dailyReport(snapshot).filter((day) => day.trades)).toEqual([
      { date: "2026-11-19", trades: 1, netPaise: -239, cumulativePaise: -239 },
      { date: "2026-11-23", trades: 1, netPaise: 188, cumulativePaise: -51 },
    ]);
    expect(reportBreakdown(snapshot.trades, "broker").map(({ netPaise }) => netPaise)).toEqual([188, -239]);
    expect(reportBreakdown(snapshot.trades, "strategy")).toEqual([{ label: "Swing", netPaise: -51, trades: 2 }]);
  });

  it("exports complete period trades with demo metadata and exact signed monetary values", () => {
    const changed = { ...snapshot, trades: [{ ...snapshot.trades[1], strategy: '=SUM(1,"2")' }] };
    const csv = reportTradesCsv(changed);
    expect(csv).toContain('"DEMO","demo","2026-11-23T10:00:00.000Z"');
    expect(csv).toContain('"\'=SUM(1,""2"")"');
    expect(csv).toContain("-2.00,0.30,0.09,-2.39");
  });

  it("limits each response to its selected IST period and withholds stale marks", async () => {
    const client = createReportingMock();
    const current = await client.getReport("7d");
    const stale = await client.getReport("30d", { scenario: "stale" });
    if (current.status !== "ready" || stale.status !== "stale") throw new Error("Expected demo ledgers.");
    expect(current.data.range).toEqual({ from: "2026-11-17", to: "2026-11-23" });
    expect(dailyReport(current.data)).toHaveLength(7);
    expect(dailyReport(stale.data)).toHaveLength(30);
    expect(stale.data.marks).toBeNull();
    expect(stale.data.trades.every(({ closedAt }) => closedAt <= stale.data.asOf && reportDay(closedAt) >= stale.data.range.from)).toBe(true);
  });
});
