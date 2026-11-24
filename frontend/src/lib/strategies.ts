import type { Strategy, StrategyParameters, StrategyRevision } from "./api/strategy-types";
import { strategyInstruments, strategyRiskTiers, strategyTimeframes } from "./api/strategy-types";

export const riskLabels = { low: "Low", medium: "Medium", high: "High" } as const;
export const strategyStatusLabels = { draft: "Draft", active: "Active", paused: "Paused" } as const;

export function latestStrategyVersion(strategy: Strategy) {
  return strategy.versions.at(-1);
}

export function strategyCandidate(strategy: Strategy) {
  return strategy.draft ?? latestStrategyVersion(strategy);
}

export function listedStrategyRevision(strategy: Strategy) {
  // Continue to show the deployed parameters while a replacement draft is in progress.
  return latestStrategyVersion(strategy) ?? strategy.draft;
}

export function activationBlocker(revision: StrategyRevision | undefined) {
  if (!revision || revision.backtest !== "passed") return "A passing backtest for this revision is required.";
  if (revision.riskReview !== "approved") return "An approved risk review for this revision is required.";
  return null;
}

export function validateStrategyParameters(parameters: StrategyParameters) {
  const name = parameters.name.trim();
  if (name.length < 3 || name.length > 64) return "Enter a strategy name of 3–64 characters.";
  if (parameters.description.trim().length > 240) return "Keep the description within 240 characters.";
  if (!strategyInstruments.includes(parameters.instrument) || !strategyTimeframes.includes(parameters.timeframe) || !strategyRiskTiers.includes(parameters.riskTier)) {
    return "Select a supported instrument, timeframe and risk tier.";
  }
  if (!Number.isInteger(parameters.positionSizeBps) || parameters.positionSizeBps < 1 || parameters.positionSizeBps > 10_000) {
    return "Enter a position size between 0.01% and 100%.";
  }
  if (!Number.isInteger(parameters.stopLossBps) || parameters.stopLossBps < 1 || parameters.stopLossBps > 10_000) {
    return "Enter a stop loss between 0.01% and 100%.";
  }
  return null;
}
