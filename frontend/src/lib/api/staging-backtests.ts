import { isReportDate } from "@/lib/paper-reporting";
import type { BacktestClient, BacktestRun, BacktestWorkspace } from "./backtest-types";
import { hasIntegers, hasStrings, isRecord, isSnapshot, isTimestamp, stagingRequest } from "./staging-client";

function isDate(value: unknown) {
  return typeof value === "string" && isReportDate(value);
}

function isConfig(value: unknown) {
  return isRecord(value) && hasStrings(value, ["strategyId", "instrumentId"]) &&
    isDate(value.from) && isDate(value.to) && isDate(value.outOfSampleFrom) &&
    hasIntegers(value, ["capitalPaise", "feeBps", "slippageBps"]);
}

function isResult(value: unknown) {
  return isRecord(value) &&
    hasIntegers(value, ["endingEquityPaise", "netPnlPaise", "returnBps", "maxDrawdownBps", "totalFeesPaise"]) &&
    (value.winRateBps === null || Number.isSafeInteger(value.winRateBps)) &&
    Array.isArray(value.points) && value.points.every((row) => isRecord(row) &&
      isDate(row.date) && hasIntegers(row, ["equityPaise", "drawdownBps"])) &&
    Array.isArray(value.trades) && value.trades.every((row) => isRecord(row) && typeof row.id === "string" &&
      isTimestamp(row.entryAt) && isTimestamp(row.exitAt) && hasIntegers(row, ["quantity", "entryPaise", "exitPaise", "feesPaise", "pnlPaise"]));
}

function isRun(value: unknown): value is BacktestRun {
  if (!isSnapshot(value, "DEMO") || typeof value.id !== "string" ||
    !isTimestamp(value.queuedAt) || !isConfig(value.config)) return false;
  switch (value.status) {
    case "queued":
    case "running":
      return true;
    case "completed":
      return isResult(value.result);
    case "failed":
      return typeof value.message === "string";
    default:
      return false;
  }
}

function isWorkspace(value: unknown): value is BacktestWorkspace {
  return isSnapshot(value, "DEMO") && isDate(value.from) && isDate(value.to) &&
    Array.isArray(value.strategies) && value.strategies.every((row) => isRecord(row) &&
      hasStrings(row, ["id", "name", "instrumentId"]) && Number.isSafeInteger(row.positionSizeBps) &&
      (row.revision === "draft" || Number.isSafeInteger(row.revision))) &&
    Array.isArray(value.instruments) && value.instruments.every((row) => isRecord(row) && hasStrings(row, ["id", "symbol"])) &&
    Array.isArray(value.runs) && value.runs.every(isRun);
}

const preview = "backtests/preview";
const parseRun = (value: unknown) => isRun(value) ? value : undefined;

export const stagingBacktests: BacktestClient = {
  getBacktestWorkspace: (options) => stagingRequest(preview, (value) => {
    if (isRecord(value) && (value.status === "ready" || value.status === "stale") && isWorkspace(value.data)) {
      return { status: value.status, data: value.data };
    }
  }, options?.signal),
  startBacktest: (config, options) => stagingRequest(`${preview}/runs`, parseRun, options?.signal, config),
  getBacktestRun: (id, options) => stagingRequest(`${preview}/runs/${encodeURIComponent(id)}`, parseRun, options?.signal),
};
