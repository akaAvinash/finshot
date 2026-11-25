import type { ReportPeriod, ReportTrade } from "@/lib/api/paper-report-types";

export const reportCsvPath = "/api/v1/reports/paper/trades.csv";
export const reportCsvFilename = "tradeo-paper-trades.csv";

export function isReportDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function parseReportPeriod(from: string | string[] | undefined, to: string | string[] | undefined) {
  const period: ReportPeriod = {
    from: typeof from === "string" && isReportDate(from) ? from : null,
    to: typeof to === "string" && isReportDate(to) ? to : null,
  };
  if ((from && !period.from) || (to && !period.to)) {
    return { period, error: "Enter valid dates for the report range." };
  }
  if (period.from && period.to && period.from > period.to) {
    return { period, error: "The start date must be on or before the end date." };
  }
  return { period, error: null };
}

export function reportQuery({ from, to }: ReportPeriod) {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const query = params.toString();
  return query ? `?${query}` : "";
}

const reportTime = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata", hourCycle: "h23",
});

export function formatReportTime(value: string) {
  return reportTime.format(new Date(value));
}

export const fillReason: Record<ReportTrade["reason"], string> = {
  entry: "Entry", "signal-exit": "Signal exit", "stop-loss": "Stop loss", "end-of-replay": "Replay ended",
};
