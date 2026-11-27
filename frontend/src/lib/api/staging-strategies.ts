import { strategyInstruments, strategyRiskTiers, strategyTimeframes, type StrategyClient, type StrategySnapshot } from "./strategy-types";
import { hasIntegers, hasStrings, isOneOf, isRecord, isSnapshot, isTimestamp, parseSnapshot, stagingRequest } from "./staging-client";

function isParameters(value: unknown) {
  return isRecord(value) && hasStrings(value, ["name", "description"]) && hasIntegers(value, ["positionSizeBps", "stopLossBps"]) &&
    isOneOf(value.instrument, strategyInstruments) && isOneOf(value.timeframe, strategyTimeframes) && isOneOf(value.riskTier, strategyRiskTiers);
}

function isDraft(value: unknown) {
  return value === null || (isRecord(value) && isParameters(value.parameters) &&
    isOneOf(value.backtest, ["passed", "failed", "unavailable"]) && isOneOf(value.riskReview, ["approved", "rejected", "pending"]));
}

function isStrategySnapshot(value: unknown): value is StrategySnapshot {
  return isSnapshot(value, "DEMO") && Array.isArray(value.strategies) && value.strategies.every((row) =>
    isRecord(row) && typeof row.id === "string" && isOneOf(row.status, ["active", "paused", "draft"]) &&
    isDraft(row.draft) && row.metrics === null && Array.isArray(row.versions) && row.versions.every((version) =>
      isRecord(version) && isParameters(version.parameters) && Number.isSafeInteger(version.number) &&
      isTimestamp(version.activatedAt) && version.backtest === "passed" && version.riskReview === "approved"));
}

export const stagingStrategies: StrategyClient = {
  getStrategies: (options) => stagingRequest("strategies/preview", (value) => parseSnapshot(value, isStrategySnapshot), options?.signal),
  sendStrategyCommand: (command, options) => stagingRequest("strategies/preview/commands",
    (value) => isStrategySnapshot(value) ? value : undefined, options?.signal, command),
};
