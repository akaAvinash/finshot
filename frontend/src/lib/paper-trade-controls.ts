import type { PaperLimits, PaperSnapshot } from "./api/auto-trading-types";

const sessionDate = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "short" });
const basisPoints = 10_000;

function getSessionPnl({ asOf, trades }: PaperSnapshot) {
  const latest = new Date(asOf);
  const day = sessionDate.format(latest);
  const today = trades.filter(({ filledAt }) => {
    const time = new Date(filledAt);
    return time <= latest && sessionDate.format(time) === day;
  }).sort((first, second) => Date.parse(first.filledAt) - Date.parse(second.filledAt));

  let netPaise = 0;
  let peakPaise = 0;
  let streak = 0;
  let peakLossStreak = 0;
  for (const trade of today) {
    netPaise += trade.pnlPaise;
    peakPaise = Math.max(peakPaise, netPaise);
    streak = trade.pnlPaise < 0 ? streak + 1 : 0;
    peakLossStreak = Math.max(peakLossStreak, streak);
  }
  return { netPaise, peakPaise, peakLossStreak };
}

function entryLimitReason(risk: PaperSnapshot["risk"], peakLossStreak: number, profitCapReached: boolean, confidence: number | null, maxQuantity: number) {
  if (risk.dailyLossPaise >= risk.lossLimitPaise) return "Daily loss cap reached.";
  if (risk.tradesToday >= risk.tradeLimit) return "Daily trade limit reached.";
  if (risk.maxConsecutiveLosses > 0 && peakLossStreak >= risk.maxConsecutiveLosses) {
    return "Consecutive loss limit reached. New entries are paused for the day.";
  }
  if (risk.status === "blocked") return "Sample risk checks blocked the entry.";
  if (profitCapReached && (confidence === null || confidence < risk.postCapConfidencePercent)) {
    return `Profit cap reached. A new entry needs at least ${risk.postCapConfidencePercent}% confidence.`;
  }
  if (maxQuantity < 1) return "The sample entry exceeds the per-trade sizing limits.";
  return null;
}

export function getPaperTradeControls(snapshot: PaperSnapshot) {
  const { risk, sampleEntry } = snapshot;
  const { netPaise, peakPaise, peakLossStreak } = getSessionPnl(snapshot);
  const stopPaise = Math.max(1, Math.floor(sampleEntry.pricePaise * (basisPoints - risk.stopLossBps) / basisPoints));
  const targetPaise = Math.ceil(sampleEntry.pricePaise * (basisPoints + risk.takeProfitBps) / basisPoints);
  const positionPaise = Math.floor(sampleEntry.equityPaise * risk.maxPositionSizeBps / basisPoints);
  const riskPerUnitPaise = Math.max(1, sampleEntry.pricePaise - stopPaise);
  const maxQuantity = Math.min(
    Math.floor(positionPaise / sampleEntry.pricePaise),
    Math.floor(risk.maxRiskPerTradePaise / riskPerUnitPaise),
  );
  const profitCapReached = risk.profitLimitPaise !== null && peakPaise >= risk.profitLimitPaise;
  const limitReached = entryLimitReason(risk, peakLossStreak, profitCapReached, sampleEntry.confidencePercent, maxQuantity);

  return { netPaise, peakPaise, profitCapReached, limitReached, stopPaise, targetPaise, maxQuantity };
}

function isIntegerInRange(value: number, min: number, max = Number.MAX_SAFE_INTEGER) {
  return Number.isSafeInteger(value) && value >= min && value <= max;
}

export function validatePaperLimits(limits: PaperLimits) {
  if (limits.profitLimitPaise !== null && !isIntegerInRange(limits.profitLimitPaise, 1)) {
    return "Enter a positive daily profit cap or leave it blank.";
  }
  if (!isIntegerInRange(limits.lossLimitPaise, 1)) return "Enter a positive daily loss cap.";
  if (!isIntegerInRange(limits.tradeLimit, 1)) return "Enter a positive whole number of trades.";
  if (!isIntegerInRange(limits.postCapConfidencePercent, 0, 100)) return "Enter a whole confidence percentage from 0 to 100.";
  if (!isIntegerInRange(limits.maxConsecutiveLosses, 0)) return "Enter a whole number of consecutive losses, or 0 to turn it off.";
  if (!isIntegerInRange(limits.stopLossBps, 1, basisPoints - 1)) return "Enter a stop loss from 0.01% to 99.99%.";
  if (!isIntegerInRange(limits.takeProfitBps, 1, basisPoints)) return "Enter a take profit from 0.01% to 100%.";
  if (!isIntegerInRange(limits.maxRiskPerTradePaise, 1)) return "Enter a positive maximum risk per trade.";
  if (!isIntegerInRange(limits.maxPositionSizeBps, 1, basisPoints)) return "Enter a maximum position size from 0.01% to 100%.";
  return null;
}
