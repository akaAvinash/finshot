import type { PaperReport } from "@/lib/api/paper-report-types";
import type { PortfolioPoint, Trade } from "@/lib/api/types";
import { formatReportTime } from "@/lib/paper-reporting";

const istDate = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
});

export function dashboardDate(date: Date) {
  const parts = istDate.formatToParts(date);
  const part = (name: Intl.DateTimeFormatPartTypes) => parts.find(({ type }) => type === name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function dashboardLedger(report: PaperReport, today: string, symbols: ReadonlyMap<string, string>) {
  const daily = [...report.daily].sort((a, b) => a.date.localeCompare(b.date));
  const monthStart = `${today.slice(0, 7)}-01`;
  let total = 0;
  let dayPnl: number | null = null;
  let monthPaise: number | null = null;
  const points: PortfolioPoint[] = daily.map(({ date, realisedPaise }) => {
    if (date === today) dayPnl = realisedPaise / 100;
    if (date >= monthStart && date <= today) monthPaise = (monthPaise ?? 0) + realisedPaise;
    total += realisedPaise;
    return { date, value: total / 100 };
  });
  const recentTrades: Trade[] = report.journal.slice(0, 5).map(({ id, date, instrument, side, quantity, fillPaise, pnlPaise, filledAt }) => ({
    id, symbol: symbols.get(instrument) ?? instrument, side, quantity, price: fillPaise / 100,
    pnl: pnlPaise / 100, timeIst: `${date} · ${formatReportTime(filledAt)}`,
  }));
  return { dayPnl, monthPnl: monthPaise === null ? null : monthPaise / 100, points, recentTrades };
}
