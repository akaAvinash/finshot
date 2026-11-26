import { isReportDate } from "@/lib/paper-reporting";
import type { PaperReport, PaperReportResult } from "./paper-report-types";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function integers(row: Record<string, unknown>, keys: readonly string[]) {
  return keys.every((key) => Number.isSafeInteger(row[key]));
}

function date(value: unknown): value is string {
  return typeof value === "string" && isReportDate(value);
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function strategy(value: unknown) {
  return value === null || (object(value) && typeof value.id === "string" && typeof value.name === "string" && integers(value, ["version"]));
}

function isPaperReport(data: unknown): data is PaperReport {
  if (!object(data) || data.source !== "demo" || data.environment !== "PAPER" || !timestamp(data.asOf) ||
      !object(data.period) || !(data.period.from === null || date(data.period.from)) || !(data.period.to === null || date(data.period.to)) ||
      !object(data.summary) || !integers(data.summary, ["realisedPaise", "unrealisedPaise", "netPaise", "feesPaise", "fills", "closedTrades", "winningTrades", "losingTrades"]) ||
      typeof data.journalTruncated !== "boolean") return false;

  const { openPosition, reconciliation, daily, strategies, journal } = data;
  if (openPosition !== null && (!object(openPosition) || typeof openPosition.instrument !== "string" || !timestamp(openPosition.markedAt) ||
      !integers(openPosition, ["quantity", "entryPaise", "markPaise", "unrealisedPaise"]))) return false;
  if (reconciliation !== null && (!object(reconciliation) || (reconciliation.status !== "matched" && reconciliation.status !== "mismatch") ||
      !integers(reconciliation, ["replay", "ledgerCashPaise", "accountCashPaise", "ledgerQuantity", "accountQuantity"]))) return false;

  return Array.isArray(daily) && daily.every((row) => object(row) && date(row.date) && integers(row, ["realisedPaise", "feesPaise", "fills"])) &&
    Array.isArray(strategies) && strategies.every((row) => object(row) && strategy(row.strategy) && integers(row, ["realisedPaise", "feesPaise", "fills", "closedTrades"])) &&
    Array.isArray(journal) && journal.every((row) => object(row) && date(row.date) && timestamp(row.filledAt) &&
      typeof row.id === "string" && typeof row.instrument === "string" && strategy(row.strategy) && (row.side === "Buy" || row.side === "Sell") &&
      typeof row.reason === "string" && ["entry", "signal-exit", "stop-loss", "end-of-replay"].includes(row.reason) &&
      integers(row, ["replay", "quantity", "fillPaise", "feesPaise", "pnlPaise"]));
}

export function parsePaperReportResult(result: unknown): PaperReportResult | undefined {
  if (object(result) && result.status === "empty") return { status: "empty" };
  if (object(result) && result.status === "ready" && isPaperReport(result.data)) return { status: "ready", data: result.data };
}
