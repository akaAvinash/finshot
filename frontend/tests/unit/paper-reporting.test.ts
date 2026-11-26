import { describe, expect, it } from "vitest";
import { samplePaperCsv, samplePaperReport } from "@/lib/api/paper-report-preview";
import { dashboardDate, dashboardLedger } from "@/lib/dashboard-ledger";
import { isReportDate, parseReportPeriod, reportQuery } from "@/lib/paper-reporting";

describe("paper report periods", () => {
  it("accepts inclusive or open IST dates and rejects invalid, reversed or repeated values", () => {
    expect(isReportDate("2024-02-29")).toBe(true);
    expect(isReportDate("2026-02-29")).toBe(false);
    expect(isReportDate("0000-01-01")).toBe(false);
    expect(parseReportPeriod("2026-11-22", "2026-11-21").error).toContain("start date");
    expect(parseReportPeriod(["2026-11-22", "2026-11-23"], undefined).error).toContain("valid dates");
    const { period, error } = parseReportPeriod("", "2026-11-12");
    expect(error).toBeNull();
    expect(reportQuery(period)).toBe("?to=2026-11-12");
  });

  it("shares the inclusive period between preview metrics and CSV without re-deducting fees", () => {
    const period = { from: "2026-11-11", to: "2026-11-12" };
    const report = samplePaperReport(period);
    expect(report).toMatchObject({
      status: "ready",
      data: {
        summary: { fills: 2, feesPaise: 1746, realisedPaise: -61746, unrealisedPaise: 24556, netPaise: -37190, closedTrades: 1 },
        daily: [
          { date: "2026-11-11", fills: 1, feesPaise: 882, realisedPaise: 0 },
          { date: "2026-11-12", fills: 1, feesPaise: 864, realisedPaise: -61746 },
        ],
        strategies: [{
          strategy: { id: "demo-pullback", name: "Pullback replay", version: 1 },
          fills: 2, feesPaise: 1746, realisedPaise: -61746, closedTrades: 1,
        }],
        journal: [{ date: "2026-11-12" }, { date: "2026-11-11" }],
      },
    });
    const csv = samplePaperCsv(period);
    const [, ...rows] = csv.trimEnd().split("\r\n");
    expect(rows.map((row) => row.split(",")[0])).toEqual(["2026-11-11", "2026-11-12"]);
    expect(csv).toContain("-617.46,stop-loss");
    expect(csv).not.toContain("INFY");
  });

  it("uses the IST date and keeps missing dashboard P&L distinct from a recorded zero", () => {
    const report = samplePaperReport({ from: "2026-11-11", to: "2026-11-12" });
    if (report.status !== "ready") throw new Error("Expected paper fills");
    const previous = dashboardDate(new Date("2026-11-11T18:29:00Z"));
    const today = dashboardDate(new Date("2026-11-11T18:30:00Z"));
    expect(previous).toBe("2026-11-11");
    expect(today).toBe("2026-11-12");
    expect(dashboardLedger(report.data, previous, new Map())).toMatchObject({ dayPnl: 0, monthPnl: 0 });
    expect(dashboardLedger(report.data, today, new Map())).toMatchObject({
      dayPnl: -617.46, monthPnl: -617.46,
      points: [{ date: previous, value: 0 }, { date: today, value: -617.46 }],
      recentTrades: [{ symbol: "RELIANCE", timeIst: "2026-11-12 · 15:00" },
        { symbol: "RELIANCE", timeIst: "2026-11-11 · 09:30" }],
    });
    expect(dashboardLedger(report.data, "2026-12-01", new Map())).toMatchObject({ dayPnl: null, monthPnl: null });
  });
});
