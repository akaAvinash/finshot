import { isReportDate } from "@/lib/paper-reporting";
import type { PaperEngineCommand, PaperSnapshot, PaperStrategy } from "./auto-trading-types";
import { hasIntegers, hasStrings, isOneOf, isRecord, isSnapshot, isTimestamp, parseSnapshot, stagingRequest } from "./staging-client";

const paperBlockedReasons = ["HALTED", "LOSS_LIMIT", "TRADE_LIMIT", "PROFIT_CAP", "CONSECUTIVE_LOSSES"] as const;
type StagingPaperSnapshot = Pick<PaperSnapshot, "source" | "environment" | "asOf" | "engine" | "strategyId" | "agent" | "orders" | "trades" | "events"> & {
  strategies: readonly (PaperStrategy & { version: number })[];
  risk: Pick<PaperSnapshot["risk"], "status" | "dailyLossPaise" | "lossLimitPaise" | "tradesToday" | "tradeLimit"> & {
    blockedReason?: (typeof paperBlockedReasons)[number] | null; consecutiveLosses?: number; controlsRevision?: number;
  };
  account: { capitalPaise: number; cashPaise: number; equityPaise: number; positionQuantity: number; perTradeRiskPaise: number };
  replay: { sessionDate: string | null; sessionsDone: number; sessionsTotal: number; finished: boolean };
};

function hasTradeControlsRisk(risk: Record<string, unknown>) {
  // During rollout the earlier paper engine omits all three fields.
  if (risk.blockedReason === undefined && risk.consecutiveLosses === undefined && risk.controlsRevision === undefined) return true;
  return (risk.blockedReason === null || isOneOf(risk.blockedReason, paperBlockedReasons)) &&
    [risk.consecutiveLosses, risk.controlsRevision].every((value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0);
}

function isPaperSnapshot(value: unknown): value is StagingPaperSnapshot {
  if (!isSnapshot(value, "PAPER") || !isOneOf(value.engine, ["idle", "running", "halted"]) ||
      !(value.strategyId === null || typeof value.strategyId === "string")) return false;
  const { strategies, agent, risk, account, replay, orders, trades, events } = value;
  return Array.isArray(strategies) && strategies.every((row) => isRecord(row) &&
    hasStrings(row, ["id", "name", "instrument"]) && Number.isSafeInteger(row.version)) &&
    isRecord(agent) && typeof agent.name === "string" && typeof agent.ready === "boolean" &&
    isRecord(risk) && isOneOf(risk.status, ["approved", "blocked"]) &&
    hasTradeControlsRisk(risk) && hasIntegers(risk, ["dailyLossPaise", "lossLimitPaise", "tradesToday", "tradeLimit"]) &&
    isRecord(account) && hasIntegers(account, ["capitalPaise", "cashPaise", "equityPaise", "positionQuantity", "perTradeRiskPaise"]) &&
    isRecord(replay) && typeof replay.finished === "boolean" && hasIntegers(replay, ["sessionsDone", "sessionsTotal"]) &&
    (replay.sessionDate === null || (typeof replay.sessionDate === "string" && isReportDate(replay.sessionDate))) &&
    Array.isArray(orders) && orders.every((row) => isRecord(row) && hasStrings(row, ["id", "instrument"]) &&
      isOneOf(row.side, ["Buy", "Sell"]) && isOneOf(row.status, ["queued", "filled", "cancelled"]) &&
      row.approval === "approved" && hasIntegers(row, ["quantity", "limitPaise"])) &&
    Array.isArray(trades) && trades.every((row) => isRecord(row) && hasStrings(row, ["id", "instrument"]) &&
      isOneOf(row.side, ["Buy", "Sell"]) && isTimestamp(row.filledAt) && hasIntegers(row, ["quantity", "fillPaise", "pnlPaise"])) &&
    Array.isArray(events) && events.every((row) => isRecord(row) && isTimestamp(row.at) && hasStrings(row, ["id", "message"]));
}

export type StagingPaperResult = { status: "ready"; data: StagingPaperSnapshot } | { status: "empty" };

export function getStagingPaper(signal?: AbortSignal) {
  return stagingRequest<StagingPaperResult>("auto-trading/paper", (value) => {
    if (isRecord(value) && value.status === "empty") return { status: "empty" };
    return parseSnapshot(value, isPaperSnapshot);
  }, signal);
}

export function sendStagingPaper(command: PaperEngineCommand, signal?: AbortSignal) {
  return stagingRequest("auto-trading/paper/commands", (value) => isPaperSnapshot(value) ? value : undefined, signal, command);
}
